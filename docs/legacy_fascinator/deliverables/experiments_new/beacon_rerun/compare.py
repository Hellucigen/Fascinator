# -*- coding: utf-8 -*-
# compare.py — 重跑 vs 归档战役逐行对比(determinism check)。
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

FIELDS = ("success", "decisions", "steps_to_craft", "first_action", "acts")


def load_archived():
    """归档战役 raw_results_final80.jsonl 的 task_result 行。"""
    p = os.path.join(ROOT, "experiments", "beacon_v1", "raw_results_final80.jsonl")
    out = {}
    for line in open(p, encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "task_result":
            out[(r["condition"], r["seed"])] = r
    return out


def main():
    arch = load_archived()
    rerun = {}
    for line in open(os.path.join(HERE, "raw_results.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "task_result":
            rerun[(r["condition"], r["seed"])] = r
    rows = []
    n_match = 0
    for key in sorted(rerun, key=lambda k: (k[1], k[0])):
        a = arch.get(key)
        m = rerun[key]
        if a is None:
            rows.append({"key": str(key), "match": None, "note": "not in archive"})
            continue
        diffs = [f for f in FIELDS if a.get(f) != m.get(f)]
        ok = not diffs
        n_match += int(ok)
        rows.append({"condition": key[0], "seed": key[1], "match": ok,
                     "diff_fields": diffs,
                     "archived": {f: a.get(f) for f in FIELDS},
                     "rerun": {f: m.get(f) for f in FIELDS}})
        print(("OK  " if ok else "DIFF") , key, diffs if diffs else "")
    res = {"n_compared": len(rows), "n_match": n_match,
           "all_match": n_match == len(rows), "rows": rows}
    with open(os.path.join(HERE, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("matched %d/%d" % (n_match, len(rows)))


if __name__ == "__main__":
    main()
