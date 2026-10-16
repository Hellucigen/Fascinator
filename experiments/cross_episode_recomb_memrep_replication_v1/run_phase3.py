# run_phase3.py — Cross-Episode MEMREP 复验 Phase-3 正式运行驱动（v2）
# 预注册：PREREGISTRATION.md v3.1（ADDENDUM-4 千问）。预算 210 成功调用。
# 续跑语义：自动找最新的 phase3_* 目录并追加；从已落盘行重建 skip 集与
# A2 上下文哈希参照表（A4 断言跨续跑仍成立）。统计从盘上重建并按键去重。
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.basicConfig(level=logging.WARNING)

import harness as H          # noqa: E402
import stats as ST           # noqa: E402

CAMPAIGN = os.path.join(HERE, "campaign_l")


def find_or_make_out():
    cands = sorted(glob.glob(os.path.join(CAMPAIGN, "phase3_*")))
    for d in reversed(cands):
        raw = os.path.join(d, "raw_runs.jsonl")
        if os.path.exists(raw) and os.path.getsize(raw) > 0:
            return d, raw
    d = os.path.join(CAMPAIGN, "phase3_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d, os.path.join(d, "raw_runs.jsonl")


def load_rows(raw):
    seen, rows = set(), []
    if not os.path.exists(raw):
        return rows
    for line in open(raw, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        k = (r["arm"], r["qid"], r["seed"])
        if k not in seen:
            seen.add(k)
            rows.append(r)
    return rows


def main():
    OUT, RAW = find_or_make_out()
    existing = load_rows(RAW)
    skip = {(r["arm"], r["qid"], r["seed"]) for r in existing}
    a2_seed = {(r["qid"], r["seed"]): r["context_hash"]
               for r in existing if r["arm"] == "A2"}
    print(f"resume: {len(skip)} runs on disk in "
          f"{os.path.basename(OUT)}, a2 refs={len(a2_seed)}", flush=True)

    f = open(RAW, "a", encoding="utf-8")

    def log(row):
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()

    caller = H.OpenAICaller()
    stopped = None
    try:
        H.run_all(caller=caller, log=log, out_dir=OUT,
                  success_cap=210, skip=skip, a2_seed=a2_seed)
    except H.BudgetExhausted as e:
        stopped = str(e)
    finally:
        f.close()
    rows = load_rows(RAW)
    rep = ST.generate_report(rows, H.QUESTIONS)
    json.dump({"stopped": stopped, "n_runs": len(rows),
               "out": os.path.basename(OUT)},
              open(os.path.join(OUT, "run_meta.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(rep, open(os.path.join(OUT, "stats_report.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print("stopped:", stopped, "| runs:", len(rows), flush=True)
    for h, c in sorted(rep["comparisons"].items()):
        print(h, c["arm_new"], "-", c["arm_old"], "N=", c["N"],
              "Δ=", c["delta_pp"], "C=", c["c"], "signal=",
              c["joint_exploratory_signal"], flush=True)
    for a, d in sorted(rep["arms"].items()):
        print(a, "rate=", d["run_rate"], "infra=", d["infra_failures"],
              "undec=", d["undecidable_questions"],
              "seeds分歧=", d["seed_inconsistency_questions"], flush=True)
    print("out:", OUT, flush=True)


if __name__ == "__main__":
    main()
