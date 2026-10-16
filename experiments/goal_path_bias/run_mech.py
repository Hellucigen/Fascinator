# run_mech.py — 族 M：机制层 A/B/C 配对实验（零 LLM、确定性图、预注册口径）
# 端点（PREREGISTRATION_DRAFT §4，主指标）：正确路径 recall@8。
# 条件：A 原始 FAS；B 路径激活偏置（无前置检查）；C B+可执行性检查。
# 配对：同图同种子（点火序 + 干扰激活抖动由 seed 决定，A/B/C 共享）。
# 统计：配对 sign-flip 精确置换检验（2^n）+ Hodges-Lehmann + bootstrap CI；
#       族内 Holm。停止判据 §2：机制层 B−A recall@8 若全图 CI 含 0 → 不进行为层。
import json
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

import graphset as GS                                    # noqa: E402
import goal_path_bias as gpb                             # noqa: E402
from self_graph import set_current_goal                  # noqa: E402
import world_prior as wp                                 # noqa: E402
import config as _C                                      # noqa: E402

OUT = os.path.join(HERE, "campaign_m", "run_" + time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)
N_SEEDS = 10
K = 8

# (builder, target, ground_truth_fn)
# 真值路径：图构造期即知的最小正确推导（与机制实现无关）
DEEP_CFG = dict(gpb.DEFAULTS, max_hops=14, max_nodes=200)


def truth_mc(target):
    """MC 图真值 = 深搜（hop14/budget200）可落地的推导节点集；
    与条件配置无关，只作为“正确路径应包含哪些节点”的参照。"""
    def fn(kg, eng):
        dv = gpb.search_goal_path(kg, DEEP_CFG, "物品:" + target)
        return set(dv["nodes"])
    return fn


CH5_TRUTH = ["物品:iron_ingot", "配方:iron_ingot:smelt:0", "物品:raw_iron",
             "iron_ore", "物品:stone_pickaxe", "配方:stone_pickaxe:table:0",
             "物品:cobblestone", "stone", "物品:wooden_pickaxe",
             "配方:wooden_pickaxe:table:0", "物品:oak_planks",
             "配方:oak_planks:hand:0", "物品:oak_log", "oak_log"]
STAR_TRUTH = ["物品:iron_ingot", "配方:iron_ingot:smelt:0", "物品:raw_iron",
              "iron_ore"]


def const_truth(t):
    return lambda kg, eng: set(t)


CONDITIONS = {
    "A": {},
    "B": {"enabled": True, "search": True, "bias": True,
          "require_state_anchor": False},
    "C": {"enabled": True, "search": True, "bias": True,
          "require_state_anchor": True},
}

# 点火感知集：玩家"看得见"的状态锚点（不含目标本身——信息不对称口径）
IGNITE = {
    "star1": ["可采资源"],
    "chain5": ["可采资源"],
    "ring": [],
    "unreachable": ["Haru"],
    "distractor": ["可采资源", "Haru"],
    "mc_wooden_pickaxe": ["Haru", "可采资源"],
    "mc_iron_ingot": ["Haru", "可采资源"],
}

CASES = [
    ("star1", "iron_ingot", lambda: GS.build_star1(), const_truth(STAR_TRUTH)),
    ("chain5", "iron_ingot", lambda: GS.build_chain5(),
     const_truth(CH5_TRUTH)),
    ("ring", "a", lambda: GS.build_ring(), const_truth([])),
    ("unreachable", "golden_apple", lambda: GS.build_unreachable(),
     const_truth([])),
    ("distractor", "iron_ingot", lambda: GS.build_distractor(),
     const_truth(CH5_TRUTH)),
    ("mc_wooden_pickaxe", "wooden_pickaxe", lambda: GS.build_mc_production(),
     truth_mc("wooden_pickaxe")),
    ("mc_iron_ingot", "iron_ingot", lambda: GS.build_mc_production(),
     truth_mc("iron_ingot")),
]


def _case_graph(builder):
    # 统一 4 元组 (kg, eng, truth, noise)；mc builder 第 3 项是 cfg dict，忽略
    out = builder()
    kg, eng = out[0], out[1]
    truth = out[2] if len(out) > 2 and isinstance(out[2], (list, set)) else []
    noise = out[3] if len(out) > 3 else []
    return kg, eng, list(truth), list(noise)


def one_run(case, cond, seed):
    name, target, builder, truthfn = case
    kg, eng, truth, noise = _case_graph(builder)
    truth_nodes = truthfn(kg, eng)
    set_current_goal(kg, f"获得 {target}")
    eng.name_to_node = dict(kg.nodes)

    rng = random.Random(seed * 104729 + sum(ord(c) for c in name) * 7919)
    cfg = dict(GS.ENG_CFG)
    ignite = list(IGNITE.get(name, []))
    # 干扰节点注入随机近期激活（seed 配对：三条件同一序列）
    distr = [n for n in kg.nodes if str(n).startswith("经历_")]
    jitter = {d: rng.uniform(0.3, 2.2) for d in distr}
    for d, v in jitter.items():
        kg.nodes[d].activation = v
        kg.nodes[d].touch()
    if ignite:
        eng.activate_from_inputs(ignite, [])
    # 失败证据节点保持 0 激活（诚实呈现：它本来就不亮，rank 如实记录）
    if jitter:
        eng.mark_active(list(jitter))

    tele = {"status": "n/a", "writes": 0, "biased": [],
            "search_ms": 0.0, "bias_ms": 0.0}
    if cond != "A":
        cfg["goal_path"] = dict(gpb.DEFAULTS, **CONDITIONS[cond])
        t0 = time.time()
        tele = gpb.run_goal_path(kg, eng, cfg)
        tele["run_ms"] = (time.time() - t0) * 1000

    pre_w = {(str(e.src), e.relation, str(e.dst)): float(e.weight)
             for e in kg.edges}
    eng.diffuse_round(max_steps=3)
    drift_n, drift_sum = 0, 0.0
    for e in kg.edges:
        k = (str(e.src), e.relation, str(e.dst))
        if k in pre_w and abs(pre_w[k] - float(e.weight)) > 1e-12:
            drift_n += 1
            drift_sum += abs(pre_w[k] - float(e.weight))
    top, _edges = eng.get_topk(k=K)
    top_ids = [n.id for n in top]
    top_set = set(top_ids)

    recall = (len(top_set & truth_nodes) / len(truth_nodes)
              if truth_nodes else None)
    # 错误偏置：被偏置节点中不在真值集的比例（B 会偏置死路/未落地分支）
    biased = {b[0] for b in tele.get("biased", [])}
    wrong_boost = (len(biased - truth_nodes) / len(biased)) if biased else 0.0
    # 挤占度：top-8 中非真值、非点火、非干扰的"其他"数量（预算零和观测）
    ign = set(ignite) | set(jitter)
    squeezed = [t for t in top_ids if t not in truth_nodes and t not in ign]
    # 失败证据可见性（rank in full sorted frontier）
    pool = [kg.nodes[nid] for nid in eng._active_nodes
            if nid in kg.nodes]
    order = sorted(pool, key=lambda n: (-n.activation,))
    fail_rank = None
    fnode = "行动结果:挖oak_log:failed"
    if name == "distractor" and fnode in kg.nodes:
        ids = [n.id for n in order]
        fail_rank = (ids.index(fnode) + 1) if fnode in ids else len(ids) + 1
    return {"case": name, "cond": cond, "seed": seed,
            "recall@8": recall, "n_truth": len(truth_nodes),
            "wrong_boost": wrong_boost, "biased_n": len(biased),
            "status": tele.get("status"), "writes": tele.get("writes"),
            "search_ms": round(float(tele.get("search_ms") or 0), 2),
            "bias_ms": round(float(tele.get("bias_ms") or 0), 2),
            "fail_evidence_rank": fail_rank,
            "top": top_ids, "frontier": len(eng._active_nodes),
            "squeezed_out": squeezed[:],
            "hebb_drift_edges": drift_n, "hebb_drift_sum": round(drift_sum, 5)}


# ── 统计工具 ─────────────────────────────────────────────

def wilcoxon_p(diffs):
    n = len([d for d in diffs if abs(d) > 1e-15])
    if n == 0:
        return 1.0
    rpos = 0.0
    arr = sorted(diffs, key=abs)
    # 秩（含并列均秩）
    absr = [abs(d) for d in arr]
    ranks = []
    i = 0
    while i < len(arr):
        j = i
        while j + 1 < len(arr) and absr[j + 1] == absr[i]:
            j += 1
        ranks.extend([((i + j) / 2.0 + 1)] * (j - i + 1))
        i = j + 1
    W_plus = sum(rk for d, rk in zip(arr, ranks) if d > 0)
    # 精确：枚举符号
    from itertools import product
    nzr = [rk for d, rk in zip(arr, ranks) if abs(d) > 1e-15]
    m = len(nzr)
    if m > 16:
        m = 16  # 本实验 m<=10，防御性上限
    total = 2 ** m
    ge = sum(1 for bits in product([0, 1], repeat=m)
             if sum(rk for rk, b in zip(nzr, bits) if b) >= W_plus - 1e-12)
    le = sum(1 for bits in product([0, 1], repeat=m)
             if sum(rk for rk, b in zip(nzr, bits) if b) <= W_plus + 1e-12)
    return min(1.0, 2 * min(ge / total, le / total))


def hodges_lehmann(diffs):
    pairs = sorted((a + b) / 2 for a in diffs for b in diffs)
    return pairs[len(pairs) // 2] if pairs else 0.0


def boot_ci(diffs, B=2000, alpha=0.05):
    import statistics
    n = len(diffs)
    if n == 0:
        return (0, 0)
    rng = random.Random(20261009)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(B))
    return round(means[int(B * alpha / 2)], 4), \
        round(means[int(B * (1 - alpha / 2))], 4)


def main():
    raw = []
    for case in CASES:
        for cond in ("A", "B", "C"):
            for seed in range(1, N_SEEDS + 1):
                r = one_run(case, cond, seed)
                raw.append(r)
    with open(os.path.join(OUT, "raw_runs.jsonl"), "w", encoding="utf-8") as f:
        for r in raw:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── 配对分析 ──
    summary = []
    by = {}
    for r in raw:
        by[(r["case"], r["cond"], r["seed"])] = r
    holm_family = []
    for case in CASES:
        name = case[0]
        for cond in ("B", "C"):
            da = [by[(name, "A", s)]["recall@8"] for s in range(1, N_SEEDS+1)]
            dc = [by[(name, cond, s)]["recall@8"] for s in range(1, N_SEEDS+1)]
            if any(d is None for d in da + dc):
                holm_family.append({"case": name, "cond": cond,
                                    "note": "n/a (no truth set)"})
                continue
            diffs = [x - y for x, y in zip(dc, da)]
            p = wilcoxon_p(diffs) if any(abs(d) > 1e-15 for d in diffs) \
                else 1.0
            hl = hodges_lehmann(diffs)
            lo, hi = boot_ci(diffs)
            entry = {"case": name, "contrast": f"{cond}-A", "p_raw": p,
                     "HL_shift": round(hl, 4), "boot95": [lo, hi],
                     "mean_diff": round(sum(diffs)/len(diffs), 4),
                     "recallA": round(sum(da)/len(da), 4),
                     "recallX": round(sum(dc)/len(dc), 4),
                     "wrong_boost_X": round(sum(
                         by[(name, cond, s)]["wrong_boost"]
                         for s in range(1, N_SEEDS + 1))/N_SEEDS, 4),
                     "search_ms": round(sum(by[(name, cond, s)]["search_ms"]
                                             for s in range(1, N_SEEDS + 1))
                                        / N_SEEDS, 2)}
            holm_family.append(entry)
            summary.append(entry)
    # Holm（主族：recall 对比，n/a 除外）
    fam = [s for s in summary if "p_raw" in s]
    fam.sort(key=lambda s: s["p_raw"])
    m = len(fam)
    running = 0.0
    for i, s in enumerate(fam):
        adj = min(1.0, (m - i) * s["p_raw"])
        adj = max(adj, running)
        running = adj
        s["p_holm"] = round(adj, 6)

    # 失败证据 rank（distractor 层）
    fr = {}
    for cond in ("A", "B", "C"):
        vals = [by[("distractor", cond, s)]["fail_evidence_rank"]
                for s in range(1, N_SEEDS + 1)]
        fr[cond] = [v for v in vals if v is not None]
    status_by = {}
    for r in raw:
        status_by.setdefault((r["case"], r["cond"]), {})[r["status"]] = \
            status_by.setdefault((r["case"], r["cond"]), {}).get(
                r["status"], 0) + 1
    drift = {}
    for cond in ("A", "B", "C"):
        rs = [r for r in raw if r["cond"] == cond]
        drift[cond] = {"mean_edges": round(sum(
            r["hebb_drift_edges"] for r in rs) / len(rs), 2),
            "mean_sum": round(sum(r["hebb_drift_sum"]
                                  for r in rs) / len(rs), 5)}
    dead_boost = {f"{c}|{cond}": sum(r["biased_n"] for r in raw
                                     if r["case"] == c and r["cond"] == cond)
                  for c in ("ring", "unreachable") for cond in ("B", "C")}

    report = {"date": "2026-10-09", "family": "M (mechanism)",
              "k": K, "n_seeds": N_SEEDS, "conditions": list(CONDITIONS),
              "summary": summary,
              "fail_evidence_ranks_distractor": fr,
              "status_counts": {f"{c}|{d}": v for (c, d), v
                                in status_by.items()},
              "hebb_drift_per_condition": drift,
              "dead_cycle_boost_counts": dead_boost}
    with open(os.path.join(OUT, "mechanism_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("case/contrast          recallA recallX   HL      boot95        "
          "p_raw   p_holm  wrongB%")
    for s in sorted(summary, key=lambda x: str(x.get("p_holm", ""))):
        print(f"{s['case']:>20} {s['contrast']}: {s['recallA']:.3f} "
              f"{s['recallX']:.3f}  {s['HL_shift']:+.3f} "
              f"[{s['boot95'][0]:+.3f},{s['boot95'][1]:+.3f}] "
              f"{s['p_raw']:.4f} {s.get('p_holm','')!s:>7} "
              f"{s['wrong_boost_X']:.2f}  search={s['search_ms']}ms")
    print("\nfail-evidence rank (distractor, lower=更可见):",
          {c: (min(v) if v else None) for c, v in fr.items()})
    print("status counts:", report["status_counts"])
    print("Hebb drift per cond (生产通道，A/B/C 共有):", drift)
    print("死路/环被偏置节点总数 (ring,unreachable)x(B,C):", dead_boost)
    print("out:", OUT)


if __name__ == "__main__":
    main()
