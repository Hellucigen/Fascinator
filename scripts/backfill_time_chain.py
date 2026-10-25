# -*- coding: utf-8 -*-
"""存量情景记忆回填时间链（任务书 2026-10-21 第 1 条，一次性迁移）。

策略：离线把（快照里已有的锚点 ∪ 待建锚点）按 ts 排序算出**目标邻接**，
再经 API 应用到运行实例——直播期间新产生的锚点也在快照里，一并归位；
非邻接的旧 早于/晚于 捷径边删除，保证链是严格的单链。发生于 0.6、
时段边（发生于时段）随迁到时点上。幂等：已有出向"发生于"的情节跳过。

用法：python scripts/backfill_time_chain.py [--dry]
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:5000"
ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "data" / "runtime_graph.json"
EPISODE_PREFIX = ("Activity_", "话语_", "剧情_", "eye_text_", "eye_pose_",
                  "Steam_")


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                time.sleep(0.08)   # 节流：werkzeug 每请求起线程，全速打满过
            return r.status        # 线程句柄上限（10-21 实锤崩服）
        except Exception:
            time.sleep(20 * (attempt + 1))   # 服务端在喘/重启：退避重试
    return -1


def del_edge(src, dst, rel):
    req = urllib.request.Request(BASE + "/api/edges",
                                 data=json.dumps({"src": src, "dst": dst,
                                                  "relation": rel}).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="DELETE")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                time.sleep(0.08)
            return r.status
        except Exception:
            time.sleep(20 * (attempt + 1))
    return -1


def gap_weight(g):
    return round(max(0.6, min(0.9, 0.9 - (max(0.0, g) / 86400.0) * 0.06)), 3)


def parse_ts(node):
    import datetime as _dt
    s = str(node.get("created") or
            (node.get("extra_attrs") or {}).get("created") or "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _dt.datetime.strptime(s.replace("/", "-"),
                                         fmt).timestamp()
        except ValueError:
            pass
    nid = str(node.get("id", ""))
    m = re.search(r"_(\d{13})$", nid)
    if m:
        return int(m.group(1)) / 1000.0
    m = re.search(r"_(\d{8})_(\d{6})_", nid)
    if m:
        try:
            return _dt.datetime.strptime(m.group(1) + m.group(2),
                                         "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            pass
    m = re.search(r"(\d{10})$", nid)
    if m:
        return float(m.group(1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    d = json.load(open(GRAPH, encoding="utf-8"))
    N = d["nodes"]
    nodes = list(N.values()) if isinstance(N, dict) else N
    E = d["edges"]
    edges = list(E.values()) if isinstance(E, dict) else E

    anchored = {e["src"] for e in edges
                if str(e.get("relation")) == "发生于"}
    old_order = {(e["src"], e["dst"], str(e.get("relation")))
                 for e in edges if str(e.get("relation")) in ("早于", "晚于")}

    # 目标锚集合：已有 time_node ∪ 每条待锚情景一个
    want = {}   # aid -> ts
    for n in nodes:
        ea = n.get("extra_attrs") or {}
        if str(ea.get("type") or "") == "time_node":
            want[n["id"]] = float(ea.get("ts") or 0.0)
    existing_ids = {str(n.get("id")) for n in nodes}

    eps = []
    skip_t = {"time_node", "mc_session", "thought", "reflection",
              "communication_intention", "intention", "expression_event",
              "feedback_pending", "action_outcome", "drive",
              "cognitive_network", "modulator", "modulator_target",
              "prior_concept", "speech_act_concept", "time_of_day",
              "day_phase", "trait", "dynamic_state", "inventory_item",
              "reply_goal", "hypothesis"}
    for n in nodes:
        nid = str(n.get("id", ""))
        if (str(n.get("label") or "").startswith("declarative-episodic")
                and str((n.get("extra_attrs") or {}).get("type") or "")
                not in skip_t
                and nid not in anchored):
            ts = parse_ts(n)
            if ts:
                aid = f"时点_{int(ts * 1000)}"
                eps.append((ts, nid, aid))
                if aid not in want and aid not in existing_ids:
                    want[aid] = ts
                elif aid not in want:
                    want.setdefault(aid, ts)
    eps.sort()

    order = sorted(want.items(), key=lambda x: (x[1], x[0]))
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    want_pairs = set()
    for (a1, t1), (a2, t2) in zip(order, order[1:]):
        w = gap_weight(t2 - t1)
        want_pairs.add((a1, a2, "早于", w))
        want_pairs.add((a2, a1, "晚于", w))

    # 时段边迁移表
    phase = {}
    for e in edges:
        if str(e.get("relation")) == "发生于时段":
            phase.setdefault(e["src"], []).append(e["dst"])

    print(f"待锚情景 {len(eps)}；目标锚点 {len(order)}；目标序边 {len(want_pairs)}；"
          f"存量序边 {len(old_order)}")
    if args.dry:
        return

    made = 0
    for aid, ts in order:
        if aid not in existing_ids:
            st = post("/api/nodes", {
                "id": aid, "weight": 0.4, "label": "infrastructure",
                "graph_space": "episodic",
                "extra_attrs": {"type": "time_node", "canon": "time_anchor",
                                "ts": ts, "created": now_str}})
            if st == 200:
                made += 1
            else:
                print(" 建锚失败", aid, st)
    print(f"新建锚点 {made}")

    for src, dst, rel in old_order:
        if not any(s == src and dd == dst and r == rel
                   for s, dd, r, _ in want_pairs):
            del_edge(src, dst, rel)

    for s, dd, rel, w in want_pairs:
        post("/api/edges", {"src": s, "dst": dd, "relation": rel,
                            "weight": w})

    linked = migrated = 0
    for ts, nid, aid in eps:
        post("/api/edges", {"src": nid, "dst": aid, "relation": "发生于",
                            "weight": 0.6})
        linked += 1
        for bucket in phase.get(nid, []):
            post("/api/edges", {"src": aid, "dst": bucket,
                                "relation": "发生于时段", "weight": 0.6})
            del_edge(nid, bucket, "发生于时段")
            migrated += 1
    print(f"挂接情景 {linked}；时段随迁 {migrated}")


if __name__ == "__main__":
    main()
