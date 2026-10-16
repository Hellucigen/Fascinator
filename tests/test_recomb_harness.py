# test_recomb_harness.py — Phase-3 harness 验收测试（纯本地；假调用器；零 LLM 预算）
# 覆盖：臂配置一致性、R2 无泄漏、A4 哈希断言、预算/重试、错误分类、
# 多数票/不可判定、Δ/C/N、联合信号、符号检验/Holm/CP/Wilson、日志可追溯。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 -m pytest tests/test_recomb_harness.py -q

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "experiments",
    "cross_episode_recomb_memrep_replication_v1"))

import pytest

import harness as H
import stats as ST
from scoring import check_answer

QUESTIONS = H.QUESTIONS


# ── 臂配置与锁定一致性 ──────────────────────────────────

def test_verify_arms_passes_on_locked_spec():
    assert H.verify_arms() is True


def test_verify_arms_hard_fails_on_mutation():
    arms = [dict(a) for a in H.LOCKED_ARMS]
    arms[4]["repfix"] = False              # A5 被暗中改成旧表示
    with pytest.raises(H.ArmConfigError):
        H.verify_arms(arms)


def test_seven_arms_match_locked_table():
    assert [a["arm"] for a in H.LOCKED_ARMS] == \
        ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
    assert H.LOCKED_ARMS[3]["role"] == "确定性检验臂"
    assert H.LOCKED_ARMS[4]["serializer"] == "memrep"
    assert H.LOCKED_ARMS[6]["regime"] == "embedding"


# ── R2 激活域：无 gold 泄漏 ─────────────────────────────

def test_r2_ignition_is_full_event_set_and_question_independent():
    kg, eng = H.build_kg("eventframe", repfix=True)
    ig = H.r2_ignition_ids(kg)
    all_events = sorted(str(n) for n in kg.nodes
                        if str(n).startswith("事件:"))
    assert ig == all_events and len(ig) == 13   # 固定全集，非按 gold 选取
    import inspect
    assert "q" not in inspect.signature(H.r2_ignition_ids).parameters


def test_r2_builders_take_no_gold_arguments():
    import inspect
    for fn in (H.build_context, H.activate, H.serial_ids_original,
               H.serial_memrep):
        params = inspect.signature(fn).parameters
        assert not any("gold" in p.lower() for p in params), fn


# ── A4 确定性检验臂：输入逐字节相同 ─────────────────────

def test_a2_a4_context_bytes_identical_all_questions():
    for q in QUESTIONS:
        kg2, eng2 = H.build_kg("eventframe", repfix=False)
        ctx2, _ = H.build_context(H.ARMS[1], q, kg=kg2, eng=eng2)
        kg4, eng4 = H.build_kg("eventframe", repfix=True)
        ctx4, _ = H.build_context(H.ARMS[3], q, kg=kg4, eng=eng4)
        assert ctx2 == ctx4, q["id"]


def test_a4_hash_mismatch_raises():
    kg, eng = H.build_kg("eventframe", repfix=True)
    q = QUESTIONS[0]
    arm = dict(H.ARMS[3])
    with pytest.raises(H.ContextMismatchError):
        H.run_single(arm, q, 0, H.BudgetTracker(), _Fake([]),
                     lambda row: None, {}, a2_ctx_hash="deadbeef")


# ── 预算与重试 ──────────────────────────────────────────

def test_budget_cap_blocks_and_raises():
    b = H.BudgetTracker(success_cap=2)
    assert b.can_call()
    b.register_success(); b.register_success()
    assert not b.can_call()
    with pytest.raises(H.BudgetExhausted):
        b.register_success()


def test_run_all_budget_exhaustion_stops_everything():
    calls = {"n": 0}

    class AlwaysRight:
        def call(self, prompt, max_tokens=400, temperature=0):
            calls["n"] += 1
            return "苹果 被放入 篮子，篮子 位于 厨房。", {
                "prompt_tokens": 1, "completion_tokens": 1}
    with pytest.raises(H.BudgetExhausted):
        H.run_all(caller=AlwaysRight(), log=lambda row: None,
                  success_cap=5)
    assert calls["n"] == 5                      # 恰好在预算处停止


def test_retry_then_success_counts_attempts():
    b = H.BudgetTracker()
    seq = [Exception("timeout"), Exception("net"), ("答", {})]

    class Flaky:
        def call(self, prompt, max_tokens=400, temperature=0):
            x = seq.pop(0)
            if isinstance(x, Exception):
                raise x
            return x

    ans, usage, attempts, retries, err = H.call_with_retry(
        Flaky(), "p", b, sleep=lambda s: None)
    assert ans == "答" and attempts == 3 and retries == 2 and err is None


def test_retry_exhausted_is_infra_failure():
    b = H.BudgetTracker()

    class Dead:
        def call(self, prompt, max_tokens=400, temperature=0):
            raise TimeoutError("网络超时")

    ans, usage, attempts, retries, err = H.call_with_retry(
        Dead(), "p", b, sleep=lambda s: None)
    assert ans == "" and attempts == 4 and retries == 3
    assert err and "TimeoutError" in err


# ── 三分类：基础设施失败 / 答错 / 答对 ──────────────────

class ScriptCaller:
    def __init__(self, script):
        self.script = list(script)

    def call(self, prompt, max_tokens=400, temperature=0):
        x = self.script.pop(0)
        if isinstance(x, Exception):
            raise x
        return x, {}


class _Fake:
    def __init__(self, script):
        self.script = list(script)

    def call(self, prompt, max_tokens=400, temperature=0):
        return self.script.pop(0), {}


GOOD = "苹果 被放入 篮子，篮子 位于 厨房。"
WRONG = "苹果 位于 树 上。"


def _rows_for(arm, script, qidx=0, seed=0):
    rows = []
    H.run_single(dict(H.ARMS[[a["arm"] for a in H.ARMS].index(arm)]),
                 QUESTIONS[qidx], seed, H.BudgetTracker(),
                 ScriptCaller(script), rows.append, {}, sleep=lambda s: None)
    return rows[-1]


def test_correct_answer_classified():
    row = _rows_for("A5", [GOOD])
    assert row["final_status"] == "success" and not row["infra_failure"]
    assert row["exact_success"] == 1


def test_wrong_answer_is_not_infra():
    row = _rows_for("A5", [WRONG])
    assert not row["infra_failure"] and row["error"] == ""
    assert row["exact_success"] == 0


def test_infra_failure_classified_and_not_D_inference():
    row = _rows_for("A5", [TimeoutError("x"), TimeoutError("x"),
                           TimeoutError("x"), TimeoutError("x")])
    assert row["infra_failure"] and row["final_status"] == "infra_failed"
    assert row["exact_success"] == 0
    assert row["d_stage"] == "not_applicable_infra"


def test_empty_answer_without_exception_is_not_infra():
    row = _rows_for("A5", [""])
    assert row["empty_answer"] and not row["infra_failure"]
    assert row["exact_success"] == 0


# ── 评分器二元性（逐字移植行为）─────────────────────────

def test_check_answer_binary_and_verbatim():
    q = QUESTIONS[0]      # gold_chain 苹果,篮子,厨房 actions 放入,位于
    r = check_answer(GOOD, q)
    assert r["exact_success"] in (0, 1) and r["exact_success"] == 1
    assert check_answer("完全无关", q)["exact_success"] == 0
    assert isinstance(check_answer(GOOD, q)["exact_success"], int)


# ── 多数票 / 不可判定 ──────────────────────────────────

def _mk_rows(arm, qid, exacts, infra_flags=None):
    n = len(exacts)
    infra = infra_flags or [False] * n
    return [{"arm": arm, "qid": qid, "seed": i,
             "exact_success": e, "infra_failure": f}
            for i, (e, f) in enumerate(zip(exacts, infra))]


def test_majority_strict_and_undecidable_rules():
    rows = (_mk_rows("A2", "Q1", [1, 1, 1, 0, 0])
            + _mk_rows("A2", "Q2", [1, 0, 0, 0, 0], [True, False, False,
                                                     False, False])
            + _mk_rows("A2", "Q3", [0, 0, 0, 0, 0])
            + _mk_rows("A2", "Q4", [1, 1, 0, 0], [False] * 4))
    ql = ST.question_level(rows, "A2")
    assert ql["Q1"]["result"] == 1              # 有效 3/3 全对
    assert ql["Q2"]["result"] == 0              # 有效 1 票=0
    assert ql["Q3"]["result"] == 0
    assert ql["Q4"]["result"] == "undecidable"  # 有效 2:2 平票


def test_zero_valid_votes_is_undecidable():
    rows = _mk_rows("A3", "Q1", [0, 0, 0, 0, 0], [True] * 5)
    assert ST.question_level(rows, "A3")["Q1"]["result"] == "undecidable"


# ── Δ/C/N 与联合探索性信号 ─────────────────────────────

def _synth_pair(new_results, old_results):
    rows = []
    for arm, res in (("A5", new_results), ("A2", old_results)):
        for qid, r in res.items():
            for s in range(5):
                val = {"1": 1, "0": 0, "undecidable": 0}[str(r)]
                rows.append({"arm": arm, "qid": qid, "seed": s,
                             "exact_success": val,
                             "infra_failure": r == "undecidable"})
    return rows


def test_delta_c_with_N_and_exclusion():
    # Q1-Q5 可判定：新胜 4、旧胜 1；Q6 一侧不可判定 → 剔除，N=5
    new = {f"Q{i}": ("1" if i <= 4 else "0") for i in range(1, 7)}
    old = {f"Q{i}": ("0" if i <= 4 else "1") for i in range(1, 7)}
    old["Q6"] = "undecidable"
    rows = _synth_pair(new, old)
    c = ST.comparison(rows, "A5", "A2", QUESTIONS)
    assert c["N"] == 5 and c["wins_new"] == 4 and c["wins_old"] == 1
    assert c["delta_pp"] == 60.0 and c["c"] == 0.8
    assert len(c["excluded"]) == 1
    assert "A2不可判定" in c["excluded"][0]["reason"]
    # Δ 达标但 C=0.8<5/6 → 未达联合信号（门槛按有效集合计算）
    assert c["joint_exploratory_signal"] is False


def test_delta_c_ties_count_in_denominator():
    # 4 题两臂相同 + 新胜 1 + 旧胜 1 → N=6, Δ=0, C=1/6
    new = {"Q1": "1", "Q2": "0", "Q3": "1", "Q4": "1",
           "Q5": "0", "Q6": "0"}
    old = {"Q1": "1", "Q2": "0", "Q3": "0", "Q4": "1",
           "Q5": "1", "Q6": "1"}
    c = ST.comparison(_synth_pair(new, old), "A5", "A2", QUESTIONS)
    assert c["N"] == 6 and c["delta_pp"] == -16.67
    assert c["c"] == pytest.approx(1 / 6, abs=1e-3)
    assert c["joint_exploratory_signal"] is False


def test_N0_signal_not_computable():
    new = {f"Q{i}": "undecidable" for i in range(1, 7)}
    old = {f"Q{i}": "undecidable" for i in range(1, 7)}
    c = ST.comparison(_synth_pair(new, old), "A5", "A2", QUESTIONS)
    assert c["N"] == 0 and c["delta_pp"] is None and c["c"] is None
    assert c["joint_exploratory_signal"] is False


def test_joint_signal_requires_both_conditions():
    # Δ 达标（50pp）但方向一致性不足（C=3/6）
    new = {"Q1": "1", "Q2": "1", "Q3": "1", "Q4": "0",
           "Q5": "0", "Q6": "0"}
    old = {"Q1": "0", "Q2": "0", "Q3": "0", "Q4": "0",
           "Q5": "0", "Q6": "0"}
    c = ST.comparison(_synth_pair(new, old), "A5", "A2", QUESTIONS)
    assert c["delta_pp"] == 50.0 and c["c"] == 0.5
    assert c["joint_exploratory_signal"] is False


# ── 符号检验 / Holm / 区间 ──────────────────────────────

def test_sign_test_exact_values():
    assert ST.sign_test_p([1] * 6) == pytest.approx(0.03125)
    assert ST.sign_test_p([1] * 5 + [-1]) == pytest.approx(0.21875)
    assert ST.sign_test_p([]) == 1.0


def test_holm_attached_report_never_rejects_at_n6():
    adj = ST.holm([0.03125] * 4)
    assert all(a >= 0.125 for a in adj)         # 最优情形也不可拒绝


def test_cp_interval_is_direction_proportion():
    lo, hi = ST.cp_interval(5, 6)
    assert 0 <= lo <= 5 / 6 <= hi <= 1
    lo0, hi0 = ST.cp_interval(0, 6)
    assert lo0 == 0 and hi0 < 0.5


def test_wilson_descriptive_only():
    lo, hi = ST.wilson(0, 30)
    assert lo == 0 and hi < 0.2


def test_arm_summary_rates_and_inconsistency():
    rows = (_mk_rows("A2", "Q1", [1, 1, 1, 0, 0])
            + _mk_rows("A2", "Q2", [0, 0, 0, 0, 0],
                       [True, False, False, False, False]))
    s = ST.arm_summary(rows, "A2", QUESTIONS)
    assert s["n_runs"] == 10 and s["exact"] == 3
    assert s["infra_failures"] == 1 and s["infra_rate"] == 0.1
    assert s["seed_inconsistency_questions"] == 1   # 仅 Q1 内部分歧


# ── 日志可追溯性与门控 ─────────────────────────────────

def test_row_traceability_fields():
    row = _rows_for("A5", [GOOD])
    for key in ("arm", "qid", "seed", "attempts", "retries", "answer",
                "error", "exact_success", "topk", "activations", "context",
                "prompt", "graph_hash", "arm_config", "code_commit",
                "memrep_switch", "facts_in_graph", "retrieved_gold",
                "serialized_facts", "d_stage"):
        assert key in row, key


def test_memrep_switch_recorded_matches_config():
    """锁定语义=run 记录的开关值必须与当时配置一致（快照可审计）；
    不断定具体 True/False（2026-10-12 启用批次后该值允许为 True）。"""
    import config as _C
    cur = bool((_C.DEFAULT_CONFIG.get("memrep") or {}).get("enabled"))
    q = QUESTIONS[0]
    row = H.run_single(dict(H.ARMS[4]), q, 0, H.BudgetTracker(),
                       ScriptCaller([GOOD]), lambda r: None, {},
                       a2_ctx_hash=None, sleep=lambda s: None)
    assert row["memrep_switch"] == cur


def test_log_write_failure_propagates():
    def bad_log(row):
        raise OSError("磁盘写入失败")
    with pytest.raises(OSError):
        H.run_single(dict(H.ARMS[4]), QUESTIONS[0], 0, H.BudgetTracker(),
                     ScriptCaller([GOOD]), bad_log, {},
                     a2_ctx_hash=None, sleep=lambda s: None)


def test_d_stage_representation_not_applicable():
    row = _rows_for("A2", [GOOD])       # A2 = G3 原样（动作不可表达）
    assert row["facts_in_graph"] == 0
    assert row["d_stage"] == "not_applicable_representation"


# ── A7（描述性锚）与全流程编排 ─────────────────────────

def test_a7_context_format(monkeypatch):
    monkeypatch.setattr(H, "retrieval_lines_for_a7",
                        lambda q: "Relevant experiences:\n- E4: 苹果 放入 篮子")
    ctx, meta = H.build_context(dict(H.ARMS[6]), QUESTIONS[0])
    assert ctx.startswith("Relevant experiences:")


def test_full_orchestration_with_fake_caller(monkeypatch):
    monkeypatch.setattr(H, "retrieval_lines_for_a7",
                        lambda q: "Relevant experiences:\n- E4: 苹果 放入 篮子")
    rows, budget, cfg = H.run_all(caller=ScriptCaller([GOOD] * 300),
                                  log=lambda row: None, success_cap=210)
    assert len(rows) == 210 and budget.successes == 210
    assert {r["arm"] for r in rows} == {"A1", "A2", "A3", "A4", "A5",
                                        "A6", "A7"}
    a2 = {(r["qid"], r["seed"]): r["context_hash"] for r in rows
          if r["arm"] == "A2"}
    a4 = {(r["qid"], r["seed"]): r["context_hash"] for r in rows
          if r["arm"] == "A4"}
    assert a2 == a4                             # A4 确定性（全 30 对）
    rep = ST.generate_report(rows, QUESTIONS)
    assert "探索性" in rep["positioning"]
    assert set(rep["comparisons"]) == {"H1", "H2", "H3", "H4"}
    assert "holm_note" in rep
