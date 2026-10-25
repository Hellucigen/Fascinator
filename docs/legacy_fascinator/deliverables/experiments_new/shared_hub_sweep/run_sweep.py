# -*- coding: utf-8 -*-
# run_sweep.py — shared-hub 参数扫描(设计冻结于 DESIGN.md,2026-10-01)
# 确定性、零 LLM、单实例锁。复用已归档 core_incremental_value 的
# generator.Graph / methods / metrics,不修改归档代码。
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
CIV = os.path.join(ROOT, "experiments", "core_incremental_value")
sys.path.insert(0, CIV)
sys.path.insert(0, os.path.join(CIV, "runners"))

import generator  # noqa: E402
import methods  # noqa: E402
import metrics  # noqa: E402

OUT = HERE
SEEDS = list(range(1, 31))
WS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
KS = [2, 3, 4, 6]
DS = [0, 1, 2]
SINGLE_W = 0.8
DIST_W = 0.3


def hub_task(seed, k, d, w, o3_replication=False):
    """参数化共享枢纽拓扑(DESIGN.md §2)。结构由 (k,d,w) 决定;种子仅用于
    tie-break 与行标识(与 CIV 的 per-seed tie-break 惯例一致)。"""
    g = generator.Graph()
    inputs = ["I%d" % i for i in range(k)]
    for i in inputs:
        g.add_node(i)
    joint_hops = d + 2
    # 枢纽路径: I -> m_{i,1..d} -> H -> T (每跳 w)
    g.add_node("H")
    for i in inputs:
        prev = i
        for j in range(d):
            m = "m%d_%d" % (i_index(i), j)
            g.add_node(m)
            g.add_edge(prev, m, w)
            prev = m
        g.add_edge(prev, "H", w)
    g.add_edge("H", "T", w)
    # singles: I -> s_i -> S_i, 2 hops @0.8
    singles = []
    for i in inputs:
        s = "s%d" % i_index(i)
        g.add_node(s)
        g.add_edge(i, s, SINGLE_W)
        g.add_edge(s, "S%d" % i_index(i), SINGLE_W)
        singles.append("S%d" % i_index(i))
    cands = ["T"] + singles
    if not o3_replication:
        # 干扰: 每输入 4 个 2 跳干扰候选 @0.3,其中 2 个进候选域
        dists = []
        for i in inputs:
            for j in range(4):
                dn = "d%d_%d" % (i_index(i), j)
                mid = "dm%d_%d" % (i_index(i), j)
                g.add_node(mid)
                g.add_node(dn)
                g.add_edge(i, mid, DIST_W)
                g.add_edge(mid, dn, DIST_W)
                if j < 2:
                    continue
                dists.append(dn)
        cands += dists
    return g, {
        "inputs": inputs, "joint": "T", "singles": singles,
        "candidates": cands, "joint_hops": joint_hops,
        "w": w, "k": k, "d": d,
        "o3_replication": bool(o3_replication),
        "total_nodes": len(g.nodes),
        "total_edges_fwd": sum(len(v) for v in g.out.values()),
    }


def i_index(i):
    return int(i[1:])


def run_cell(tag, k, d, w, o3=False, log=None):
    rows = []
    for seed in SEEDS:
        g, task = hub_task(seed, k, d, w, o3_replication=o3)
        probs = generator.check_graph_integrity(g, task)
        if probs:
            raise RuntimeError("graph integrity: %r" % probs)
        steps = task["joint_hops"] + 2
        tb = methods.tie_break_for(seed, task["candidates"])
        subsets = [("multi", task["inputs"])] + [
            ("single_%d" % i_index(i), [i]) for i in task["inputs"]]
        scores_all = {}
        for sub_name, sub in subsets:
            sf = methods.score_fas(g, task, sub, steps)
            sb = methods.score_b2(g, task, sub, task["joint_hops"] + 2)
            sb1 = methods.score_b1(g, task, sub)
            scores_all[sub_name] = (sf, sb, sb1)
        mf, mb, mb1 = scores_all["multi"]
        rf = methods.rank_candidates(mf, task["candidates"], tb)
        rb = methods.rank_candidates(mb, task["candidates"], tb)
        r1 = methods.rank_candidates(mb1, task["candidates"], tb)
        metf = metrics.run_metrics(mf, rf, task, seed)
        metb = metrics.run_metrics(mb, rb, task, seed)
        met1 = metrics.run_metrics(mb1, r1, task, seed)
        jcgf = metrics.jcg_value(mf.get("T"), [scores_all[s][0].get("T", 0.0) for s, _ in subsets[1:]])
        jcgb = metrics.jcg_value(mb.get("T"), [scores_all[s][1].get("T", 0.0) for s, _ in subsets[1:]])
        row = {
            "type": "run", "cell": tag, "seed": seed, "w": w, "k": k, "d": d,
            "o3_replication": int(o3),
            "fas": metf, "b2": metb, "b1": met1,
            "jcg_fas": jcgf, "jcg_b2": jcgb,
            "steps": steps, "n_nodes": task["total_nodes"],
        }
        rows.append(row)
        if log:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def mcnemar_exact(b, c):
    """双侧精确二项 McNemar(paired 0/1)。b,c = discordant counts。"""
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    p = sum(comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2
    return min(1.0, p)


def wilcoxon_p_two_sided(diffs):
    """小样本精确 Wilcoxon 符号秩(双侧,零差剔除)。"""
    ds = [x for x in diffs if abs(x) > 1e-12]
    n = len(ds)
    if n == 0:
        return 1.0
    ranks = sorted(range(n), key=lambda i: abs(ds[i]))
    w = sum(i + 1 for pos, i in enumerate(ranks) if ds[i] > 0)
    # 精确分布枚举(n<=30)
    from itertools import product
    total = 2 ** n
    cnt = 0
    for bits in product((0, 1), repeat=n):
        s = sum((pos + 1) for pos, b in enumerate(bits) if b)
        if abs(2 * s - n * (n + 1) / 2 - (2 * w - n * (n + 1) / 2)) < 1e-9:
            cnt += 1
    return min(1.0, cnt / total)


def analyze(all_rows):
    from collections import defaultdict
    cells = defaultdict(list)
    for r in all_rows:
        cells[r["cell"]].append(r)
    summary = []
    for tag, rows in sorted(cells.items()):
        n = len(rows)
        sf1 = [r["fas"]["recall@1"] for r in rows]
        sb1 = [r["b2"]["recall@1"] for r in rows]
        b01 = sum(1 for a, b in zip(sf1, sb1) if a == 0 and b == 1)
        b10 = sum(1 for a, b in zip(sf1, sb1) if a == 1 and b == 0)
        p_mcn = mcnemar_exact(b10, b01)
        mrr_d = [r["fas"]["mrr"] - r["b2"]["mrr"] for r in rows]
        p_wil = wilcoxon_p_two_sided(mrr_d)
        jcg_d = [r["jcg_fas"] - r["jcg_b2"] for r in rows]
        summary.append({
            "cell": tag, "w": rows[0]["w"], "k": rows[0]["k"], "d": rows[0]["d"],
            "o3_replication": rows[0]["o3_replication"], "n": n,
            "fas_success": sum(sf1), "b2_success": sum(sb1),
            "discordant_fas_only": b10, "discordant_b2_only": b01,
            "mcnemar_p": round(p_mcn, 6),
            "fas_mrr_median": _median([r["fas"]["mrr"] for r in rows]),
            "b2_mrr_median": _median([r["b2"]["mrr"] for r in rows]),
            "wilcoxon_p_mrr": round(p_wil, 6),
            "jcg_fas_median": _median([r["jcg_fas"] for r in rows]),
            "jcg_b2_median": _median([r["jcg_b2"] for r in rows]),
        })
    return summary


def _median(v):
    v = sorted(v)
    n = len(v)
    if n == 0:
        return None
    return round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2, 6)


def main():
    lock = open(os.path.join(OUT, ".sweep.lock"), "a+")
    try:
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("[sweep] already running in this directory")
        return 1
    t0 = time.time()
    # preflight: B4-style oracle 由 generator 语义保证;此处跑 O3 复现格
    o3_rows = run_cell("O3-replication", 2, 0, 0.5, o3=True)
    o3_succ = sum(r["fas"]["recall@1"] for r in o3_rows)
    print("[preflight] O3-replication FAS success %d/30" % o3_succ, flush=True)
    if o3_succ < 30:
        print("[preflight] FAIL — O3 复现格未达 30/30,整批中止(fail-fast)")
        return 2
    log = open(os.path.join(OUT, "raw_results.jsonl"), "w", encoding="utf-8")
    for r in o3_rows:
        log.write(json.dumps(r, ensure_ascii=False) + "\n")
    all_rows = list(o3_rows)
    cells = 0
    for d in DS:
        for k in KS:
            for w in WS:
                tag = "k%dd%dw%03d" % (k, d, int(round(w * 100)))
                all_rows += run_cell(tag, k, d, w, log=log)
                cells += 1
                print("[cell] %s done (%d cells, %.0fs)"
                      % (tag, cells, time.time() - t0), flush=True)
    log.close()
    summary = analyze(all_rows)
    with open(os.path.join(OUT, "sweep_summary.csv"), "w", encoding="utf-8", newline="") as f:
        import csv
        wtr = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        wtr.writeheader()
        for s in summary:
            wtr.writerow(s)
    with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump({"n_cells": len(summary), "n_runs": len(all_rows),
                   "o3_replication_success": o3_succ, "summary": summary},
                  f, ensure_ascii=False, indent=1)
    print("done: %d runs, %d cells -> %s (%.0fs)"
          % (len(all_rows), len(summary), OUT, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
