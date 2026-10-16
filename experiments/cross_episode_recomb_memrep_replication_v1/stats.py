# stats.py — 锁定预注册 v3.1 §3 的统计实现（探索性；与锁定文本逐条对应）
# 多数票/不可判定 → 有效题目集合 N → Δ/C → 联合探索性信号 →
# 符号检验(参考)/Holm(附报)/CP 方向比例区间/各臂 run 级 Wilson(描述) →
# 种子不一致率与基础设施失败率。纯确定性，无 LLM。
import hashlib
import json
import math
import os
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODES = json.load(open(os.path.join(
    HERE, "..", "cross_episode_recomb", "episodes.json"),
    encoding="utf-8"))


def gold_triples(q, epmap=None):
    epmap = epmap or {ep["id"]: ep for ep in EPISODES}
    return [(epmap[e]["subject"], epmap[e]["action"], epmap[e]["object"])
            for e in q.get("gold_episodes", []) if e in epmap]


def question_level(rows, arm):
    """臂级题结果：{(qid): {"votes":[0/1...], "valid":[...],
    "result": 1|0|"undecidable"}}。
    规则（v3.1 §3.1）：无效调用（error≠空）记 0 票但不计有效票；
    有效票严格多数（≥⌈valid/2⌉+…即 >valid/2）→ 1/0；有效票偶数平票
    或无有效票 → "undecidable"。"""
    out = {}
    for r in rows:
        if r["arm"] != arm:
            continue
        v = out.setdefault(r["qid"], {"votes": [], "valid": []})
        v["votes"].append(int(r["exact_success"]))
        if not r["infra_failure"]:
            v["valid"].append(int(r["exact_success"]))
    for qid, v in out.items():
        valid = v["valid"]
        if not valid or (len(valid) % 2 == 0
                         and sum(valid) == len(valid) / 2):
            v["result"] = "undecidable"
        else:
            v["result"] = 1 if sum(valid) * 2 > len(valid) else 0
    return out


def comparison(rows, arm_new, arm_old, questions):
    """一项主对比：N（两臂均可判定的题）、获胜数、Δ、C、逐题表、剔除数。
    返回 dict；N=0 时 delta/c 为 None（不可计算）。"""
    new = question_level(rows, arm_new)
    old = question_level(rows, arm_old)
    qids = [q["id"] for q in questions]
    table, excluded = [], []
    wins_new = wins_old = 0
    N = 0
    for qid in qids:
        rn, ro = new.get(qid, {}).get("result"), old.get(qid, {}).get("result")
        if rn == "undecidable" or ro == "undecidable" or rn is None \
                or ro is None:
            reason = []
            if rn == "undecidable" or rn is None:
                reason.append(f"{arm_new}不可判定")
            if ro == "undecidable" or ro is None:
                reason.append(f"{arm_old}不可判定")
            excluded.append({"qid": qid, "reason": "；".join(reason)})
            table.append({"qid": qid, "new": rn, "old": ro,
                          "direction": "excluded_undecidable"})
            continue
        N += 1
        if rn > ro:
            direction = "new"
            wins_new += 1
        elif ro > rn:
            direction = "old"
            wins_old += 1
        else:
            direction = "tie"
        table.append({"qid": qid, "new": rn, "old": ro,
                      "direction": direction})
    delta = (wins_new - wins_old) / N * 100 if N > 0 else None
    c = wins_new / N if N > 0 else None
    signal = (delta is not None and delta >= 20.0
              and c is not None and c >= 5 / 6)
    discordant = [t for t in table if t["direction"] in ("new", "old")]
    favorable = sum(1 for t in discordant if t["direction"] == "new")
    return {"arm_new": arm_new, "arm_old": arm_old, "N": N,
            "wins_new": wins_new, "wins_old": wins_old,
            "delta_pp": round(delta, 2) if delta is not None else None,
            "c": round(c, 4) if c is not None else None,
            "joint_exploratory_signal": bool(signal),
            "excluded": excluded, "table": table,
            "discordant": len(discordant), "favorable": favorable,
            "note": "联合探索性信号是探索性指标，不是统计显著性或机制有效性证明"}


def sign_test_p(diffs):
    """双侧精确符号检验。diffs=问题级配对差（0=平局剔除）。"""
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    x = sum(1 for d in nz if d > 0)
    tail = sum(comb(n, k) for k in range(x, n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def holm(ps, alpha=0.05):
    """Holm step-down 附报（v3.1：仅附报，n=6 下恒不可拒绝）。"""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj = [0.0] * m
    run = 0.0
    prev_idx = []
    for i, idx in enumerate(order):
        a = min(1.0, (m - i) * ps[idx])
        run = max(run, a)
        adj[idx] = round(run, 6)
    return adj


def cp_interval(k, n, alpha=0.05):
    """非平局题中方向比例的精确（Clopper–Pearson）区间。
    标注：描述"信息题中的方向比例"，不是准确率差的置信区间。"""
    if n == 0:
        return None
    import scipy.stats as st
    lo = 0.0 if k == 0 else st.beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else st.beta.ppf(1 - alpha / 2, k + 1, n - k)
    return (round(lo, 4), round(hi, 4))


def wilson(k, n, alpha=0.05):
    """单比例 Wilson 区间（仅各臂 run 级描述用）。"""
    if n == 0:
        return None
    z = 1.959963984540054
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, ctr - half), 4), round(min(1.0, ctr + half), 4))


def arm_summary(rows, arm, questions):
    rs = [r for r in rows if r["arm"] == arm]
    n_runs = len(rs)
    exact = sum(int(r["exact_success"]) for r in rs)
    infra = sum(1 for r in rs if r["infra_failure"])
    wrong = n_runs - infra - exact          # 正常返回但答错
    # 种子不一致率：同题内 exact 的分歧比例（按题聚合）
    per_q = {}
    for r in rs:
        per_q.setdefault(r["qid"], []).append(int(r["exact_success"]))
    q_dis = [1 for v in per_q.values() if len(set(v)) > 1]
    ql = question_level(rows, arm)
    undec = sum(1 for v in ql.values() if v["result"] == "undecidable")
    wl = wilson(exact, n_runs)
    return {"arm": arm, "n_runs": n_runs, "exact": exact,
            "run_rate": round(exact / n_runs, 4) if n_runs else None,
            "run_rate_wilson95": wl,
            "infra_failures": infra,
            "infra_rate": round(infra / n_runs, 4) if n_runs else None,
            "model_wrong": wrong,
            "seed_inconsistency_questions": len(q_dis),
            "questions": len(per_q), "undecidable_questions": undec}


def stage_diagnostics(rows, questions):
    """A/B/C/D 四阶段计数（互斥分类；基础设施错误不进 D 推理失败，
    记 not_applicable；A 不可表达的 run 记 A 并跳过后续）。"""
    epmap = {ep["id"]: ep for ep in EPISODES}
    qmap = {q["id"]: q for q in questions}
    out = {"A_not_expressible": 0, "B_retrieval_miss": 0,
           "C_serialization_loss": 0, "D_evaluated": 0,
           "D_evaluated_correct": 0, "D_evaluated_wrong": 0,
           "D_not_applicable_infra": 0,
           "D_not_applicable_representation": 0}
    for r in rows:
        st = r.get("d_stage") or "n/a"
        if st == "not_applicable_infra":
            out["D_not_applicable_infra"] += 1
            continue
        if st == "not_applicable_representation":
            out["A_not_expressible"] += 1
            out["D_not_applicable_representation"] += 1
            continue
        q = qmap[r["qid"]]
        n_gold = len(gold_triples(q, epmap))
        if r.get("facts_in_graph") == 0:
            out["A_not_expressible"] += 1
            continue
        if not r.get("retrieved_gold") and r.get("topk") is not None:
            out["B_retrieval_miss"] += 1
            continue
        if r.get("serialized_facts", 0) < n_gold:
            out["C_serialization_loss"] += 1
            continue
        out["D_evaluated"] += 1
        out["D_evaluated_correct" if r["exact_success"]
            else "D_evaluated_wrong"] += 1
    return out


def generate_report(rows, questions):
    """锁定预注册 §3 的全部报告物（探索性；不含任何确认性宣称）。"""
    arms = sorted({r["arm"] for r in rows})
    report = {"positioning": "探索性机制实验（预注册 v3.1）；"
                             "结果不构成确认性证据",
              "arms": {a: arm_summary(rows, a, questions) for a in arms},
              "comparisons": {}, "per_question_tables": {},
              "sign_tests": {}, "holm_note": "n=6 下最小双侧 p=0.03125 > "
                             "Holm 首门槛 0.0125，校正后 p 恒不可拒绝——"
                             "仅附报，不作成败判据"}
    for h, new, old in (("H1", "A2", "A3"), ("H2", "A3", "A5"),
                        ("H3", "A4", "A5"), ("H4", "A2", "A5")):
        cmp_ = comparison(rows, new, old, questions)
        report["comparisons"][h] = cmp_
        diffs = []
        for t in cmp_["table"]:
            if t["direction"] == "new":
                diffs.append(+1)
            elif t["direction"] == "old":
                diffs.append(-1)
        p = sign_test_p(diffs)
        report["sign_tests"][h] = {"p_two_sided_exact": round(p, 6),
                                   "note": "参考描述；非成败判据"}
        if cmp_["discordant"] > 0:
            report["comparisons"][h]["favorable_cp95"] = cp_interval(
                cmp_["favorable"], cmp_["discordant"])
    report["per_question_tables"] = {
        h: report["comparisons"][h]["table"]
        for h in report["comparisons"]}
    report["stage_diagnostics"] = stage_diagnostics(rows, questions)
    report["hash"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, ensure_ascii=False,
                   default=str).encode()).hexdigest()[:16]
    return report
