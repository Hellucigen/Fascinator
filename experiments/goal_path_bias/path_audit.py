# path_audit.py — Phase-0 只读路径可达性审计（零激活写入）
# 对应 DESIGN.md §Phase 0 / TEST_PLAN 前置。回答："哪些域真的有可执行路径，
# 哪些域不得启用偏置"。输出 artifacts/path_audit_report.json。
import json
import os
import sys
import time
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import graphset as GS                                   # noqa: E402
import goal_path_bias as gpb                            # noqa: E402

ROOT = GS.ROOT
OUT = os.path.join(HERE, "artifacts")
os.makedirs(OUT, exist_ok=True)

AUDIT_CFG = dict(GS.ENG_CFG)
AUDIT_CFG["goal_path"] = dict(gpb.DEFAULTS, enabled=True, search=True,
                              bias=False)


def forward_reach(kg, nid, levels=2):
    """生产方向语义下的 forward 可达（出边全部；入边仅对称关系词）。
    与 diffusion_engine._edge_direction 同判据（graph_schema 全局覆盖）。"""
    import graph_schema as gs
    SYM = {"相关", "同一", "认识", "靠近", "关于", "涉及", "参与", "交互"}
    frontier = {nid}
    seen = {nid}
    for _ in range(levels):
        nxt = set()
        for f in frontier:
            for e in kg.get_out_edges(f):
                if e.dst not in seen:
                    nxt.add(e.dst)
            for e in kg.get_in_edges(f):
                if e.relation in SYM or gs.global_direction_override(
                        e.relation) == "bidirectional":
                    if e.src not in seen:
                        nxt.add(e.src)
        seen |= nxt
        frontier = nxt
    return len(seen) - 1


def audit_graph(name, kg, eng, ground_truth=None):
    items = [str(nid) for nid in kg.nodes if str(nid).startswith("物品:")]
    sinks = [i for i in items if not kg.get_out_edges(i)]
    rec = {"graph": name, "n_nodes": len(kg.nodes), "n_edges": len(kg.edges),
           "n_items": len(items), "item_sink_fraction":
           (len(sinks) / len(items)) if items else None,
           "statuses": collections.Counter(), "depths": [],
           "leaf_why": collections.Counter(),
           "forward2_mean": [], "errors": []}
    t0 = time.time()
    targets = ground_truth or items

    def _run(target_id):
        cfg = gpb._cfg(AUDIT_CFG)
        dv = gpb.search_goal_path(kg, cfg, target_id)
        st = ("PATH" if dv["resolved"] else
              ("PARTIAL_PATH" if dv["n_nodes"] > 1 else "NO_PATH"))
        rec["statuses"][st] += 1
        rec["depths"].append(max((m["hop"] for m in dv["nodes"].values()),
                                 default=0))
        for l in dv["leaves"]:
            rec["leaf_why"][l["status"] + (":" + l["why"].split("@")[0]
                                           if l["why"] else "")] += 1
        rec["forward2_mean"].append(forward_reach(kg, target_id, 2))
        return dv

    for t in targets:
        tid = t if t.startswith("物品:") else f"物品:{t}"
        if tid not in kg.nodes:
            rec["statuses"]["NO_TARGET_NODE"] += 1
            continue
        try:
            _run(tid)
        except Exception as e:
            rec["errors"].append(f"{tid}: {e!r}")
    rec["audit_ms"] = round((time.time() - t0) * 1000, 1)
    rec["statuses"] = dict(rec["statuses"])
    rec["leaf_why"] = dict(rec["leaf_why"])
    rec["depth_stats"] = _stats(rec["depths"])
    rec["forward2_stats"] = _stats(rec["forward2_mean"])
    rec["forward2_mean"] = None
    rec["depths"] = None
    return rec


def _stats(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": round(sum(xs) / len(xs), 3),
            "median": xs[len(xs) // 2], "max": xs[-1],
            "zero_fraction": round(sum(1 for x in xs if x == 0) / len(xs), 3)}


def main():
    report = {"date": "2026-10-09", "mode": "read-only",
              "note": "search-only 审计（bias=off）：对图零写入；"
                      "沙箱桥为实验事实源非生产知识", "graphs": []}
    # ① 生产路径图（mc_world+配方闭包，沙箱桥）
    kg, eng, cfgd = GS.build_mc_production()
    report["graphs"].append(audit_graph("mc_production(sandbox-bridge)",
                                        kg, eng))
    # ② 真实历史运行时快照
    snap = os.path.join(ROOT, "FAS_Research_Experiments", "baselines",
                        "run_20260928_113149", "full_graph.json")
    if os.path.exists(snap):
        kg, eng, _ = GS.build_baseline_snapshot(snap)
        report["graphs"].append(audit_graph("baseline_snapshot_20260928",
                                            kg, eng))
    # ③ 知识包合并图
    kg, eng, _ = GS.build_packs_merged()
    report["graphs"].append(audit_graph("knowledge_packs_merged", kg, eng))
    # ④ 合成拓扑（ground truth 全物品）
    for name, fn in GS.GRAPHS.items():
        out = fn()
        kg, eng = out[0], out[1]
        report["graphs"].append(audit_graph("synthetic:" + name, kg, eng))

    with open(os.path.join(OUT, "path_audit_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    for g in report["graphs"]:
        print(f"── {g['graph']}: nodes={g['n_nodes']} edges={g['n_edges']} "
              f"items={g['n_items']} sink={g['item_sink_fraction']}")
        print(f"   状态: {g['statuses']}")
        print(f"   叶子: {g['leaf_why']}  深度: {g['depth_stats']}")
        print(f"   forward2hop(对照): {g['forward2_stats']}  "
              f"耗时ms={g['audit_ms']} errors={len(g['errors'])}")
    print("report ->", os.path.join(OUT, "path_audit_report.json"))


if __name__ == "__main__":
    import logging
    logging.disable(logging.WARNING)
    main()
