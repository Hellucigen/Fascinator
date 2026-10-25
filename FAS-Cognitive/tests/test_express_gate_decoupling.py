# -*- coding: utf-8 -*-
"""解除意图分类对表达资格的硬门控（2026-10-17 任务）。
驱动真实路径：_expression_candidates → _evaluate_expression_v2。
零 LLM（drive_evaluator 缺位 → _motivation_present fail-open；
_evaluate_expression_v2 本身不碰 LLM）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node          # noqa: E402
from continuous_cognition import (ContinuousCognition,  # noqa: E402
                                  ST_READY, ST_EXPRESSED, ST_DISCARDED)
import pytest                                         # noqa: E402


class StubEngine:
    _running = False
    def get_topk(self, k=15): return [], []
    def decay_step(self): pass
    def diffuse_step(self): pass
    def mark_active(self, ids): pass
    def register_activation_source(self, ids, source_type=None): pass
    def clear_anchors(self): pass


class StubNLP:
    def system_prompt(self, task): return "SYS"


def mk_cc():
    cfg = {"continuous_cognition": {},
           "expression_decision_v2": True,
           "expression_dedup_window_s": 1800,
           "expression_defer_max_s": 1800}
    kg = KnowledgeGraph()
    cc = ContinuousCognition(kg, StubEngine(), StubNLP(), None, cfg)
    cc.drive_evaluator = None          # fail-open：不拦动机轴
    return kg, cc


def ep_node(kg, nid, kind, basis, explain, status=ST_READY, act=0.9,
            tp="intention"):
    ea = {"type": tp, "kind": kind, "status": status, "basis": basis,
          "activation": act, "score": act, "explain": explain,
          "born_ts": time.time(), "last_change_ts": time.time(),
          "illocutionary_act": None, "reply_goal": None,
          "affinity": 0.4}
    kg.add_node(Node(id=nid, weight=0.5, label="intention",
                     graph_space="self", extra_attrs=ea))
    return kg.nodes[nid]


def episodic(kg, nid):
    kg.add_node(Node(id=nid, weight=0.5, label="declarative-episodic",
                     graph_space="episodic", extra_attrs={}))


def concept(kg, nid):
    kg.add_node(Node(id=nid, weight=0.5, label="declarative-semantic",
                     graph_space="semantic", extra_attrs={}))


SOC_EXPL = {"user_relevance": 0.33, "social_relevance": 0.15,
            "emotion_present": 0.0, "novelty": 0.8}


def test_exploration_specific_finding_reaches_expression():
    """#1 被分类为 exploration 的具体新发现仍能进表达评估。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_新卡")
    ep_node(kg, "CI_e1", "exploration", ["经历_新卡"], dict(SOC_EXPL))
    assert "CI_e1" in {n.id for n in cc._expression_candidates()}
    # 进入后被 _promote_goal 补上表达家族（图谱规则，非新机制）：含经历的
    # 具体发现归到分享/延续家族（follow_up），只要非空即证明家族已推导。
    assert kg.nodes["CI_e1"].extra_attrs.get("reply_goal") in (
        "follow_up", "share_related_knowledge", "empathize",
        "information_seeking")


def test_reflection_user_relevant_not_blocked_by_label():
    """#2 reflection 但用户高相关 → 不因标签被拒。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_用户近况")
    ex = {"user_relevance": 0.66, "social_relevance": 0.5,
          "emotion_present": 1.0}
    ep_node(kg, "CI_r1", "reflection", ["经历_用户近况"], ex)
    assert "CI_r1" in {n.id for n in cc._expression_candidates()}


def test_vague_communication_still_rejected():
    """#3 空泛 communication（概念 basis 无证据）在 v2 证据闸前 defer。"""
    kg, cc = mk_cc()
    concept(kg, "CuriosityDrive")
    ci = ep_node(kg, "CI_c1", "communication", ["CuriosityDrive"],
                 {"user_relevance": 0.0, "social_relevance": 0.0},
                 tp="communication_intention")
    ci.extra_attrs["illocutionary_act"] = "assertive"
    ci.extra_attrs["reply_goal"] = "share_related_knowledge"
    best, _v = cc._evaluate_expression_v2(time.time(), True, 0)
    assert best is not ci
    assert ci.extra_attrs["expression_eval"]["verdict"] in ("defer", "suppress")


def test_socially_relevant_thin_evidence_gets_evaluation_not_free_pass():
    """规范修订（2026-10-18）：用户相关（user_relevance 过线）但事实细节
    还薄的念头，**获得被评估的资格**（旧 AND 门槛直接拒之门外=另一种
    垄断）；但 v2 的证据闸保证它不白送——结果是 defer，不是 express。"""
    kg, cc = mk_cc()
    concept(kg, "抽象概念")
    ep_node(kg, "CI_e2", "exploration", ["抽象概念"], dict(SOC_EXPL))
    cand_ids = {n.id for n in cc._expression_candidates()}
    assert "CI_e2" in cand_ids                  # 有评估机会（路径 b）
    # 但纯概念、无交流语境的空泛念头（user_relevance=0）三路径全不沾：
    concept(kg, "又一无关概念")
    ep_node(kg, "CI_e3", "exploration", ["又一无关概念"],
            {"user_relevance": 0.0, "social_relevance": 0.0})
    assert "CI_e3" not in {n.id for n in cc._expression_candidates()}


def test_multi_beat_no_duplicate_no_evidence_farm():
    """#4 同一念头连续多拍评估：不重复发送、不伪造新证据计数。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_分享")
    n = ep_node(kg, "CI_d1", "exploration", ["经历_分享"], dict(SOC_EXPL))
    ts = time.time()
    cc._evaluate_expression_v2(ts, True, 0)
    cc._evaluate_expression_v2(ts + 1, True, 0)
    assert n.extra_attrs.get("defer_count") is None       # 快照覆盖，不累加
    assert int(n.extra_attrs.get("reinforced", 0) or 0) == 0
    n.extra_attrs["status"] = ST_EXPRESSED
    n.extra_attrs["expressed_at_ts"] = ts
    assert "CI_d1" not in {x.id for x in cc._expression_candidates()}


def test_expressed_then_same_content_suppressed():
    """#5 已表达过同类内容 → 新念头被 duplicate_recent 抑制。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_同一事")
    done = ep_node(kg, "CI_done", "exploration", ["经历_同一事"],
                   dict(SOC_EXPL))
    done.extra_attrs.update({"status": ST_EXPRESSED,
                             "illocutionary_act": "assertive",
                             "reply_goal": "share_related_knowledge",
                             "expressed_at_ts": time.time()})
    fresh = ep_node(kg, "CI_new", "exploration", ["经历_同一事"],
                    dict(SOC_EXPL))
    fresh.extra_attrs.update({"illocutionary_act": "assertive",
                              "reply_goal": "share_related_knowledge"})
    best, _ = cc._evaluate_expression_v2(time.time(), True, 0)
    assert best is not fresh
    assert fresh.extra_attrs["expression_eval"]["reason"] == "duplicate_recent"


def test_cooldown_and_rate_limit_apply_across_types():
    """#6 冷却/小时限额是跨类型共享闸。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_x")
    ep_node(kg, "CI_g1", "exploration", ["经历_x"], dict(SOC_EXPL))
    assert cc._evaluate_expression_v2(time.time(), False, 0)[0] is None
    assert cc._evaluate_expression_v2(time.time(), True, 99)[0] is None


def test_low_strength_high_value_is_evaluated_not_forced():
    """#7 低强度高价值：进候选被评估，但未达线 → defer（不必然说）。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_低强")
    n = ep_node(kg, "CI_low", "exploration", ["经历_低强"], dict(SOC_EXPL),
                act=0.2)
    assert "CI_low" in {x.id for x in cc._expression_candidates()}
    cc._evaluate_expression_v2(time.time(), True, 0)
    ev = n.extra_attrs["expression_eval"]
    assert ev["verdict"] == "defer" and ev["reason"] == "below_bar"


def test_fadeout_leaves_no_permanent_backlog():
    """#8 自然衰减淡出，不留永久积压候选。"""
    kg, cc = mk_cc()
    episodic(kg, "经历_淡")
    n = ep_node(kg, "CI_fade", "exploration", ["经历_淡"], dict(SOC_EXPL),
                act=0.11)
    cc._decay_intentions()
    assert n.extra_attrs["status"] == ST_DISCARDED
    assert "CI_fade" not in {x.id for x in cc._expression_candidates()}
