# -*- coding: utf-8 -*-
# extract.py — 从 raw_results.jsonl 程序化生成 sweep_summary.csv / analysis.json /
# 论文引用数字(paper_numbers.json)。只读取原始运行行,不做任何手填。
import json
import os
import sys
from collections import defaultdict
from math import comb
from itertools import product

HERE = os.path.dirname(os.path.abspath(__file__))


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    p = sum(comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2
    return min(1.0, p)


def wilcoxon_p_two_sided(diffs):
    """双侧 Wilcoxon 符号秩(scipy,exact 优先,大样本渐近)。零差剔除。"""
    from scipy.stats import wilcoxon
    ds = [x for x in diffs if abs(x) > 1e-12]
    n = len(ds)
    if n == 0:
        return 1.0
    if n <= 25:
        stat, p = wilcoxon(ds, alternative="two-sided", method="exact")
    else:
        stat, p = wilcoxon(ds, alternative="two-sided",
                           method="approx", correction=True)
    return float(p)


def median(v):
    v = sorted(v)
    n = len(v)
    if n == 0:
        return None
    return round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2, 6)


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "raw_results.jsonl"),
                                        encoding="utf-8") if l.strip()]
    cells = defaultdict(list)
    for r in rows:
        if r.get("type") != "run":
            continue
        cells[r["cell"]].append(r)
    summary = []
    for tag, rs in sorted(cells.items()):
        sf1 = [r["fas"]["recall@1"] for r in rs]
        sb1 = [r["b2"]["recall@1"] for r in rs]
        b10 = sum(1 for a, b in zip(sf1, sb1) if a == 1 and b == 0)
        b01 = sum(1 for a, b in zip(sf1, sb1) if a == 0 and b == 1)
        mrr_d = [r["fas"]["mrr"] - r["b2"]["mrr"] for r in rs]
        summary.append({
            "cell": tag, "w": rs[0]["w"], "k": rs[0]["k"], "d": rs[0]["d"],
            "o3_replication": rs[0]["o3_replication"], "n": len(rs),
            "fas_success": sum(sf1), "b2_success": sum(sb1),
            "discordant_fas_only": b10, "discordant_b2_only": b01,
            "mcnemar_p": round(mcnemar_exact(b10, b01), 6),
            "fas_mrr_median": median([r["fas"]["mrr"] for r in rs]),
            "b2_mrr_median": median([r["b2"]["mrr"] for r in rs]),
            "wilcoxon_p_mrr": round(wilcoxon_p_two_sided(mrr_d), 6),
            "jcg_fas_median": median([r["jcg_fas"] for r in rs]),
            "jcg_b2_median": median([r["jcg_b2"] for r in rs]),
        })
    with open(os.path.join(HERE, "sweep_summary.csv"), "w", encoding="utf-8", newline="") as f:
        import csv
        wtr = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        wtr.writeheader()
        for s in summary:
            wtr.writerow(s)

    grid = [s for s in summary if not s["o3_replication"]]
    o3 = [s for s in summary if s["o3_replication"]][0]
    wins = [s for s in grid if s["fas_success"] > s["b2_success"]]
    losses = [s for s in grid if s["fas_success"] < s["b2_success"]]
    ties = [s for s in grid if s["fas_success"] == s["b2_success"]]
    w_axis_d0k2 = sorted([s for s in grid if s["d"] == 0 and s["k"] == 2],
                         key=lambda s: s["w"])
    paper = {
        "n_cells_grid": len(grid), "n_seeds_per_cell": 30,
        "n_runs_total": len(rows),
        "o3_replication": {"fas": o3["fas_success"], "b2": o3["b2_success"],
                           "mcnemar_p": o3["mcnemar_p"]},
        "grid_fas_strictly_better_cells": len(wins),
        "grid_fas_worse_cells": len(losses),
        "grid_tie_cells": len(ties),
        "win_cells_detail": [
            {"k": s["k"], "d": s["d"], "w": s["w"],
             "fas": s["fas_success"], "b2": s["b2_success"],
             "mcnemar_p": s["mcnemar_p"]} for s in sorted(
                wins, key=lambda s: (s["d"], s["k"], s["w"]))],
        "w_axis_d0_k2": [
            {"w": s["w"], "fas": s["fas_success"], "b2": s["b2_success"],
             "fas_mrr": s["fas_mrr_median"], "b2_mrr": s["b2_mrr_median"]}
            for s in w_axis_d0k2],
        "k_margin_median_diff": {
            k: median([s["fas_mrr_median"] - s["b2_mrr_median"]
                       for s in grid if s["k"] == k and s["fas_mrr_median"] is not None])
            for k in (2, 3, 4, 6)},
        "d_margin_median_diff": {
            d: median([s["fas_mrr_median"] - s["b2_mrr_median"]
                       for s in grid if s["d"] == d and s["fas_mrr_median"] is not None])
            for d in (0, 1, 2)},
    }
    with open(os.path.join(HERE, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "paper_numbers.json"), "w", encoding="utf-8") as f:
        json.dump(paper, f, ensure_ascii=False, indent=1)
    print(json.dumps(paper, ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
