# test_reading.py — 通用阅读闭环控制流测试（假抽取器，零 LLM、零网络）
# 覆盖：目标形成/计划、dispatched≠confirmed、崩溃恢复、源完整性、
# 来源分级（text_stated/inferred）、未知缺口、重复引用、矛盾扫描、
# 跨语料泛化（同一代码路径跑两份语料，证明无任务专用分支）。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 -m pytest tests/test_reading.py -q
import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph
from experience import ExperienceTimeline
import reading as RD

CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "experiments", "reading_loop", "corpus")


def fresh(path=None):
    src = RD.load_source(os.path.join(
        CORPUS, path or "inferno_c1.json"))
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    tmp = tempfile.mkdtemp()
    led = RD.ReadingLedger(src, os.path.join(tmp, "ledger.json"))
    return src, kg, led, os.path.join(tmp, "ledger.json")


# 合成抽取器（脚本化的"假 LLM"）：按文本关键词产出实体/三元组
def fake_extractor(text):
    low = text.lower()
    ents, rels = [], []
    if "wood" in low or "woods" in low:
        ents.append("dark_wood")
        rels.append({"src": "Dante", "rel": "位于", "dst": "dark_wood",
                     "kind": "text", "quote": "darksome wood"})
    if "virgil" in low or "shade" in low:
        ents.append("Virgil")
        rels.append({"src": "Dante", "rel": "涉及", "dst": "Virgil",
                     "kind": "text", "quote": "Virgil shewed"})
    if "hill" in low or "sun" in low:
        ents.append("hill")
        rels.append({"src": "Dante", "rel": "位于", "dst": "hill",
                     "kind": "text", "quote": "hill"})
    if "she-wolf" in low or "wolf" in low:
        ents.append("she-wolf")
        rels.append({"src": "Dante", "rel": "需要", "dst": "Veltro",
                     "kind": "inference", "quote": ""})
    return {"entities": ents or ["unnamed_scene"], "relations": rels}


def test_goal_and_plan_formed():
    src, kg, led, _ = fresh()
    g = led.data[src["source_id"]]
    assert g["goal"]["condition"] == "all_units_confirmed"
    assert led.next_unit() == 1 and not led.goal_satisfied()
    assert led.progress() == {"confirmed": 0, "total": 8,
                              "failed": 0, "dispatched": 0}


def test_read_confirms_with_evidence_and_sources():
    src, kg, led, _ = fresh()
    tl = ExperienceTimeline(path=os.path.join(tempfile.mkdtemp(), "tl.json"))
    r = led.read_unit(1, fake_extractor, kg, tl=tl)
    assert r["status"] == "confirmed"
    u = led.data[src["source_id"]]["units"]["1"]
    assert u["status"] == "confirmed" and u["written"]["unit_node"]
    node = kg.get_node(u["written"]["unit_node"])
    assert node.extra_attrs["source"] == "text_stated"
    kinds = {f["kind"] for f in led.data[src["source_id"]]["facts"]}
    assert "text_stated" in kinds        # 规范化来源标签（inference→inferred）
    import memrep
    assert memrep._norm_source("text_stated") == "text_stated"


def test_dispatched_not_confirmed_is_unread_on_resume():
    """崩溃恢复：dispatched 未确认的单元重启后回到待读，不虚报进度。"""
    src, kg, led, path = fresh()
    led.set_status(1, "dispatched", attempts=1)
    led2 = RD.ReadingLedger(src, path)          # 新进程语义 = 重新 load
    assert led2.next_unit() == 1                # 不跳过 dispatched
    assert led2.progress()["confirmed"] == 0
    cv = led2.claims_vs_evidence()
    assert cv["claims_done"] is False and cv["evidence_done"] is False


def test_full_coverage_completion_only_with_evidence():
    src, kg, led, _ = fresh()
    for n in range(1, src["total_units"] + 1):
        assert led.read_unit(n, fake_extractor, kg)["status"] == "confirmed"
    assert led.goal_satisfied() and led.next_unit() is None
    cv = led.claims_vs_evidence()
    assert cv["claims_done"] == cv["evidence_done"] is True


def test_source_hash_guard_no_silent_reread():
    src, kg, led, _ = fresh()
    bad = copy.deepcopy(src)
    bad["units"][0]["text"] += " TAMPERED"
    led2 = RD.ReadingLedger(bad, led.path)      # 总单元数一致则进入
    r = led2.read_unit(1, fake_extractor, kg)   # hash 校验拒写
    assert r["status"] == "failed" and "hash" in r["reason"]


def test_unit_count_drift_rejected():
    src, kg, led, path = fresh()
    bad = copy.deepcopy(src)
    bad["total_units"] = 99
    try:
        RD.ReadingLedger(bad, path)
        assert False, "应拒绝源漂移"
    except ValueError:
        pass


def test_unknown_question_becomes_gap_not_fabrication():
    src, kg, led, _ = fresh()
    led.read_unit(1, fake_extractor, kg)
    a = led.ask("Cato 在 Purgatorio 里说了什么?")
    assert a["status"] == "no_evidence"
    gaps = led.data[src["source_id"]]["gaps"]
    assert gaps and gaps[-1]["unread_pending"]      # 指向未读单元=下一步候选
    b = led.ask("where is Dante located?")
    assert b["status"] == "evidence" and b["facts"]


def test_duplicate_fact_citations_across_units():
    src, kg, led, _ = fresh()
    # 语料核实：units 1/2 均含 "wood"（同段三行组），读两段
    assert "wood" in src["units"][0]["text"].lower()
    assert "wood" in src["units"][1]["text"].lower()
    led.read_unit(1, fake_extractor, kg)          # Dante 位于 dark_wood
    led.read_unit(2, fake_extractor, kg)          # 同三元组再现
    facts = led.data[src["source_id"]]["facts"]
    dup = [f for f in facts if f["s"] == "Dante" and f["p"] == "位于"
           and f["o"] == "dark_wood"]
    assert dup and dup[0]["citations"] >= 2 and len(dup[0]["units"]) >= 2


def test_conflict_scan_lists_not_resolves():
    src, kg, led, _ = fresh()
    assert "hill" in src["units"][4]["text"].lower()
    led.read_unit(1, fake_extractor, kg)          # 位于 dark_wood (text)
    led.read_unit(5, fake_extractor, kg)          # 位于 hill (text)
    conflicts = led.scan_conflicts()
    dante_loc = [c for c in conflicts if c["s"] == "Dante"
                 and c["p"] == "位于"]
    assert dante_loc and len(dante_loc[0]["objects"]) > 1
    assert len(led.data[src["source_id"]]["facts"]) >= 2   # 诊断不裁决


def test_cross_corpus_generalization_same_path():
    """同一段代码跑第二份语料（Alice）——无任务专用分支。"""
    src, kg, led, _ = fresh("alice_ch1.json")
    assert led.next_unit() == 1

    def alice_x(text):
        low = text.lower()
        ents, rels = [], []
        if "alice" in low:
            ents.append("Alice")
        if "bank" in low:
            ents.append("bank")
            rels.append({"src": "Alice", "rel": "位于", "dst": "bank",
                         "kind": "text", "quote": "on the bank"})
        if "daughter" in low or "sister" in low:
            ents.append("sister")
            rels.append({"src": "Alice", "rel": "涉及", "dst": "sister",
                         "kind": "text", "quote": "her sister"})
        if "rabbit" in low:
            ents.append("White Rabbit")
            rels.append({"src": "Alice", "rel": "涉及",
                         "dst": "White Rabbit", "kind": "text",
                         "quote": "White Rabbit"})
        return {"entities": ents, "relations": rels}
    r = led.read_unit(1, alice_x, kg)             # unit1: bank+sister
    assert r["status"] == "confirmed" and r["relations"] >= 1
    led.read_unit(2, alice_x, kg)                 # unit2: rabbit
    a = led.ask("Where is Alice?")
    assert a["status"] == "evidence"
    b = led.ask("Mock Turtle 是谁?")              # ch1 未出现 → 缺口
    assert b["status"] == "no_evidence"


def test_dropped_relations_recorded_not_swallowed():
    src, kg, led, _ = fresh()

    def odd(text):
        return {"entities": ["X"], "relations": [
            {"src": "X", "rel": "热爱", "dst": "Y", "kind": "text"}]}
    led.read_unit(1, odd, kg)
    dr = led.data[src["source_id"]].get("dropped_relations", [])
    assert dr and dr[0]["rel"] == "热爱"           # 词表外关系记录而非静默


def test_matcher_no_stopword_false_hits():
    """真跑教训回归：短 stopword 子串不得把未涉及实体判成"有证据"。
    旧版 `t in name or name in t` 会因 "to"∈"Veltro" 命中；新版要求
    实体名完整出现在问题中，或问题中 ≥5 字母的词落在实体名内。"""
    src, kg, led, _ = fresh()

    def vx(text):
        return {"entities": ["Veltro"], "relations": [
            {"src": "Dante", "rel": "需要", "dst": "Veltro",
             "kind": "inference"}]}
    led.read_unit(1, vx, kg)
    a = led.ask("What do I owe you today?")     # owe/to 都可能误配 Veltro
    assert a["status"] == "no_evidence"
    b = led.ask("Who is Veltro?")               # 实体名完整出现 → 命中
    assert b["status"] == "evidence"


# ── P2-3 抽取可靠性（salvage/重试/partial；真实样本回放，零 API）──

def test_salvage_recovers_complete_entries_from_real_truncations():
    import json as _json
    art = os.path.join(os.path.dirname(CORPUS), "artifacts_20261012_151130",
                       "llm_calls.json")
    if not os.path.exists(art):
        import pytest
        pytest.skip("真实 artifacts 不在（仅本地复现用）")
    raws = [r["answer"] for r in _json.load(open(art, encoding="utf-8"))["log"]
            if r["purpose"] == "extract"]
    ok = refused = partial = 0
    for raw in raws:
        try:
            obj, p = RD.salvage_extract_json(raw)
            ok += 1
            partial += 1 if p else 0
            assert isinstance(obj, dict)
            for r_ in obj.get("relations", []):
                assert set(r_) >= {"src", "rel", "dst"}   # 只留完整元素
        except Exception:
            refused += 1
    assert ok == 5 and refused == 1      # 全空输出必须拒收，不得伪造
    assert partial == 2                  # 截断样本报 partial


def test_extractor_factory_retry_and_attempt_count():
    seq = ["not json at all", '{"entities": ["a"], "relations": []}']
    ex = RD.make_llm_extractor(lambda p: seq.pop(0), max_retries=1)
    out = ex("text")
    assert out["_attempts"] == 2 and out["_partial"] is False


def test_extractor_partial_baked_into_unit_ledger():
    src, kg, led, _ = fresh()

    def trunc_call(prompt):
        return ('{"entities": ["Dante", "dark_wood"], "relations": '
                '[{"src": "Dante", "rel": "位于", "dst": "dark_wood", '
                '"kind": "text", "quote": "wood"}, {"src": "unf')
    ex = RD.make_llm_extractor(trunc_call, max_retries=0)
    r = led.read_unit(1, ex, kg)
    assert r["status"] == "confirmed" and r["partial"] is True
    assert led.data[src["source_id"]]["units"]["1"]["partial"] is True
    facts = led.data[src["source_id"]]["facts"]
    assert len(facts) == 1 and facts[0]["o"] == "dark_wood"


def test_extractor_total_failure_records_failed_not_fake():
    src, kg, led, _ = fresh()
    ex = RD.make_llm_extractor(lambda p: "prose only", max_retries=1)
    r = led.read_unit(2, ex, kg)
    assert r["status"] == "failed"
    assert led.data[src["source_id"]]["units"]["2"]["status"] == "failed"


# ── P2-4 匹配器正反例（精度/召回对照）───────────────────

def _led_with_facts():
    src, kg, led, _ = fresh()

    def ex(text):
        return {"entities": ["Dante", "dark wood", "Virgil"],
                "relations": [
                    {"src": "Dante", "rel": "位于", "dst": "dark wood",
                     "kind": "text", "quote": "darksome wood"},
                    {"src": "Virgil", "rel": "涉及", "dst": "Dante",
                     "kind": "text", "quote": "who followeth"}]}
    led.read_unit(1, ex, kg)
    return src, kg, led


def test_matcher_recall_plural_case_and_alias():
    src, kg, led = _led_with_facts()
    assert led.ask("who found the woods dangerous?")["status"] == "evidence"
    assert led.ask("WHERE IS DANTE?")["status"] == "evidence"
    from graph_model import Edge, Node
    if kg.get_node("曼托") is None:
        kg.add_node(Node(id="曼托"))          # 端点必须存在（add_edge 语义）
    kg.add_edge(Edge(src="Virgil", dst="曼托", relation="名字叫",
                     weight=0.6))
    assert led.ask("曼托 说了什么?", kg=kg)["status"] == "evidence"


def test_matcher_precision_stopwords_no_hit():
    src, kg, led = _led_with_facts()
    for q in ("What do I owe you today?",
              "Is it warm in here or is it me?",
              "who am I?"):
        assert led.ask(q)["status"] == "no_evidence", q


def test_failed_units_never_source_facts():
    src, kg, led, _ = fresh()
    led.set_status(1, "dispatched", attempts=1)
    assert led.ask("Where is Dante?")["status"] == "no_evidence"


def test_inference_never_disguised_as_text_stated():
    src, kg, led, _ = fresh()

    def ex(text):
        return {"entities": ["Veltro"], "relations": [
            {"src": "Dante", "rel": "需要", "dst": "Veltro",
             "kind": "inference", "quote": ""}]}
    led.read_unit(1, ex, kg)
    f = led.data[src["source_id"]]["facts"][0]
    assert f["kind"] == "inferred"
    pk = led.evidence_pack("Does Dante need the Veltro?")
    assert pk["state"] == "sufficient" and "inferred" in pk["pack"]


def test_evidence_pack_three_states_conflict():
    src, kg, led, _ = fresh()

    def ex_pos(text):
        return {"entities": ["Dante"],
                "relations": [{"src": "Dante", "rel": "位于",
                               "dst": "dark wood", "kind": "text",
                               "quote": "wood"}]}

    def ex_hill(text):
        return {"entities": ["Dante"],
                "relations": [{"src": "Dante", "rel": "位于",
                               "dst": "hill", "kind": "text",
                               "quote": "hill"}]}
    led.read_unit(1, ex_pos, kg)
    led.read_unit(5, ex_hill, kg)
    pk = led.evidence_pack("Where is Dante?")
    assert pk["state"] == "conflict"
    assert "dark wood" in pk["pack"] and "hill" in pk["pack"]


def test_sources_not_stitched_into_single_fact():
    src1, kg1, led1, _ = fresh()
    src2, kg2, led2, _ = fresh("alice_ch1.json")

    def exa(t):
        return {"entities": ["Dante"], "relations": [
            {"src": "Dante", "rel": "位于", "dst": "dark wood",
             "kind": "text"}]}

    def exb(t):
        return {"entities": ["Alice"], "relations": [
            {"src": "Alice", "rel": "位于", "dst": "dark wood",
             "kind": "text"}]}
    led1.read_unit(1, exa, kg1)
    led2.read_unit(1, exb, kg2)
    p1 = led1.evidence_pack("who is in dark wood?")
    p2 = led2.evidence_pack("who is in dark wood?")
    assert p1["facts"][0]["s"] == "Dante"
    assert p2["facts"][0]["s"] == "Alice"
    assert src1["source_id"] in p1["pack"] and "alice" in p2["pack"]


# ── P2-5 生产接口 ───────────────────────────────────────

def test_begin_source_text_splits_with_integrity():
    text = ("Para one.\n\n" + "x" * 1200 + "\n\n" + "Para three.")
    src, kg, led, _ = fresh()
    src_new = led.begin_source_text(text, "adhoc_file",
                                    uri="file:///tmp/t.txt",
                                    unit_chars=600)
    assert src_new["total_units"] >= 2
    assert all(u["sha256"] == RD.unit_sha(u["text"])
               for u in src_new["units"])


def test_progress_report_is_evidence_bound_and_truthful():
    src, kg, led, _ = fresh()
    assert "0/8" in led.progress_report()
    led.read_unit(1, fake_extractor, kg)
    r = led.progress_report()
    assert "1/8" in r and "第 2 单元" in r
    for n in range(2, 9):
        led.read_unit(n, fake_extractor, kg)
    assert "全部完成" in led.progress_report()


def test_register_gap_enters_shared_hub_with_read_label():
    from diffusion_engine import DiffusionEngine
    src, kg, led, _ = fresh()
    eng = DiffusionEngine(kg, {"beta_spread": 1.0})
    assert led.register_gap(kg, eng, "Veltro 是什么", config=None)
    import prior_knowledge as pk
    gaps = pk.open_gaps(kg)
    read = [g for g in gaps if g.get("label") == "阅读"]
    assert read and read[0].get("kind") == "read_gap"


def test_open_ledger_persistence_and_resume(tmp_path=None):
    import tempfile as _tf
    d = _tf.mkdtemp()
    lp = os.path.join(d, "ledger.json")
    text = ("Alpha alpha." + chr(10) + chr(10) + "b" * 400
            + chr(10) + chr(10) + "Gamma gamma tail.")
    probe = RD.ReadingLedger(
        {"source_id": "x", "total_units": 0, "units": []},
        os.path.join(d, "scratch.json"))
    src = probe.begin_source_text(text, "file:test.txt",
                                  uri="file://t", unit_chars=200)
    led = RD.open_ledger(lp, src)
    assert led is not None
    assert RD.any_active_reading(lp)
    r1 = led.read_unit(1, fake_extractor, KnowledgeGraph())
    assert r1["status"] == "confirmed"
    # 重启语义：新进程只能从 sidecar 恢复同一 source 与进度
    led2 = RD.open_ledger(lp)
    assert led2.sid == "file:test.txt"
    assert led2.progress()["confirmed"] == 1
    assert led2.next_unit() == 2
    assert led2.source["units"][1]["text"] == src["units"][1]["text"]
    # 全部确认 → 不再有"进行中的阅读"
    for n in range(2, src["total_units"] + 1):
        led2.read_unit(n, fake_extractor, KnowledgeGraph())
    assert not RD.any_active_reading(lp)
