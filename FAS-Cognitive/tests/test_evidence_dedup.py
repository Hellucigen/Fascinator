# -*- coding: utf-8 -*-
"""证据去重写回（任务 §五）：同一经历反复被引用不得算多份新证据。

旧缺陷：upsert_belief/upsert_preference 每次强化无条件
evidence_count += len(引用) 且 conf += 0.05——反思窗口重叠、同一经历
经不同节点共激活反复引用时，两次即可把"长期倾向"推到置信饱和。
"""
import pytest

from graph_model import KnowledgeGraph
from self_model import SelfGraphManager, SelfMemoryUpdater


def _mgr():
    return SelfGraphManager(KnowledgeGraph())


def _prov(refs=None, ev=2, conf=0.55):
    p = {"confidence": conf, "source": "llm_inference", "evidence_count": ev,
         "first_observed": "2026-10-18 00:00:00",
         "last_reinforced": "2026-10-18 00:00:00"}
    if refs is not None:
        p["evidence_refs"] = refs
    return p


def test_creation_seeds_refs():
    m = _mgr()
    r = m.upsert_belief("用户把MC视为创造工具", _prov(refs=["经历_a", "经历_b"]))
    assert r["action"] == "created"
    n = m.kg.get_node("信念: 用户把MC视为创造工具")
    assert n.extra_attrs["evidence_count"] == 2
    assert set(n.extra_attrs["evidence_refs"]) == {"经历_a", "经历_b"}


def test_same_refs_second_round_adds_nothing():
    m = _mgr()
    m.upsert_belief("x", _prov(refs=["经历_a", "经历_b"]))
    n = m.kg.get_node("信念: x")
    ev0, conf0 = n.extra_attrs["evidence_count"], n.confidence
    r = m.upsert_belief("x", _prov(refs=["经历_a", "经历_b"]))
    assert r["action"] == "reinforced"
    # 同一锅旧证据：计数与置信都不再涨——这才是"多次有意义的证据"
    assert n.extra_attrs["evidence_count"] == ev0
    assert n.confidence == conf0
    assert n.extra_attrs["last_reinforced"]  # 时刻照常刷新


def test_new_ref_counted_once():
    m = _mgr()
    m.upsert_belief("x", _prov(refs=["经历_a", "经历_b"]))
    n = m.kg.get_node("信念: x")
    conf0 = n.confidence
    m.upsert_belief("x", _prov(refs=["经历_a", "经历_c"]))
    assert n.extra_attrs["evidence_count"] == 3      # 只有 经历_c 是新的
    assert abs(n.confidence - (conf0 + 0.05)) < 1e-9


def test_preference_dedup_same_path():
    m = _mgr()
    m.upsert_preference("Minecraft模组开发", _prov(refs=["对话_1"]))
    n = m.kg.get_node("偏好: Minecraft模组开发")
    ev0, conf0 = n.extra_attrs["evidence_count"], n.confidence
    m.upsert_preference("Minecraft模组开发", _prov(refs=["对话_1"]))
    assert n.extra_attrs["evidence_count"] == ev0
    assert n.confidence == conf0


def test_legacy_callers_without_refs_keep_old_semantics():
    m = _mgr()
    m.upsert_belief("y", _prov(refs=None, ev=1))
    n = m.kg.get_node("信念: y")
    conf0 = n.confidence
    m.upsert_belief("y", _prov(refs=None, ev=1))     # explicit_statement 类调用
    assert n.extra_attrs["evidence_count"] == 2
    assert n.confidence > conf0


def test_reflection_candidates_end_to_end_dedup():
    """真实反思入口跑两遍同一候选（同证据）：第二遍不得注水。"""
    kg = KnowledgeGraph()
    cfg = {}
    upd = SelfMemoryUpdater(kg, cfg)
    cand = [{
        "type": "belief_update", "content": "用户将Minecraft视为创造工具",
        "confidence": 0.8, "source": "explicit_statement",
        "evidence": ["经历_mc创造1", "经历_mc创造2"],
    }]
    r1 = upd.process_reflection_candidates(cand, reflection_id="R1")
    assert r1["approved"] or r1["pending"]          # 真实门槛下至少入选
    n = kg.get_node("信念: 用户将Minecraft视为创造工具")
    assert n is not None
    ev0, conf0 = n.extra_attrs["evidence_count"], n.confidence
    r2 = upd.process_reflection_candidates(cand, reflection_id="R2")
    # 证据一字未变 → 计数与置信不动（旧实现这里会变成 4 / +0.05）
    assert n.extra_attrs["evidence_count"] == ev0
    assert n.confidence == conf0
