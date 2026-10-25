# -*- coding: utf-8 -*-
"""表达去重的内容身份判定 + 合账修正（2026-10-18 规范修订版）。
驱动真实 _is_duplicate_recent / _express 戳记 / note_spoken 路径。
零 LLM。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node          # noqa: E402
from continuous_cognition import (ContinuousCognition,  # noqa: E402
                                  ST_READY, ST_EXPRESSED)
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
    cfg = {"continuous_cognition": {}, "expression_decision_v2": True,
           "expression_dedup_window_s": 1800}
    kg = KnowledgeGraph()
    cc = ContinuousCognition(kg, StubEngine(), StubNLP(), None, cfg)
    cc.drive_evaluator = None
    return kg, cc


def spoken_ci(kg, nid, basis, goal, ago):
    kg.add_node(Node(id=nid, weight=0.5, label="intention",
                     graph_space="self",
                     extra_attrs={"type": "intention", "kind": "exploration",
                                  "status": ST_EXPRESSED, "basis": basis,
                                  "reply_goal": goal,
                                  "activation": 0.3,
                                  "expressed_at_ts": time.time() - ago}))
    return kg.nodes[nid]


def think_ci(kg, nid, basis, goal, born_ago=5.0):
    kg.add_node(Node(id=nid, weight=0.5, label="intention",
                     graph_space="self",
                     extra_attrs={"type": "intention", "kind": "exploration",
                                  "status": ST_READY, "basis": basis,
                                  "reply_goal": goal, "activation": 0.8,
                                  "born_ts": time.time() - born_ago}))
    return kg.nodes[nid]


def mat(kg, nid, born_ago=9999.0):
    kg.add_node(Node(id=nid, weight=0.5, label="declarative-episodic",
                     graph_space="episodic",
                     created=time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(time.time() - born_ago))))
    return kg.nodes[nid]


# ── 内容身份去重 ───────────────────────────────────────────
def test_pure_revival_is_repeat_no_window_needed():
    """19:08 事故形态：旧材料原班复活（哪怕隔 6h）= 复读。"""
    kg, cc = mk_cc()
    a = mat(kg, "假设：MC与联结", born_ago=10 * 3600)   # 10h 前入图
    # 6h 前以同 goal 同配方讲过（戳记=家族锚定）
    a.extra_attrs.update({"last_shared_ts": time.time() - 6 * 3600,
                          "last_shared_goal": "follow_up",
                          "last_shared_basis": ["假设：MC与联结"]})
    spoken_ci(kg, "CI_old", ["假设：MC与联结"], "follow_up", ago=6 * 3600 + 10)
    new = think_ci(kg, "CI_new", ["假设：MC与联结"], "follow_up")
    assert cc._is_duplicate_recent(new, time.time(), 1800) is True


def test_genuinely_new_material_passes_immediately():
    """上次分享之后诞生的新经历进 basis → 延伸，不等任何窗。"""
    kg, cc = mk_cc()
    old = mat(kg, "假设：MC与联结", born_ago=10 * 3600)
    old.extra_attrs.update({"last_shared_ts": time.time() - 6 * 3600,
                            "last_shared_goal": "follow_up",
                            "last_shared_basis": ["假设：MC与联结"]})
    fresh = mat(kg, "经历_刚逛到", born_ago=60.0)     # 1min 前才入图
    spoken_ci(kg, "CI_old", ["假设：MC与联结"], "follow_up", ago=6 * 3600 + 10)
    new = think_ci(kg, "CI_new", ["假设：MC与联结", "经历_刚逛到"],
                   "follow_up")
    assert cc._is_duplicate_recent(new, time.time(), 1800) is False


def test_never_shared_material_not_repeat():
    """材料从未被分享过 → 不是复读（第一次讲）。"""
    kg, cc = mk_cc()
    mat(kg, "假设：新题")
    new = think_ci(kg, "CI_x", ["假设：新题"], "share_related_knowledge")
    assert cc._is_duplicate_recent(new, time.time(), 1800) is False


def test_same_material_different_goal_is_new_act():
    """同一块材料、不同交流目的（共鸣→追问）= 新的言语行为，不按复读杀。
    （家族锚定含 goal：上次讲它的"讲法"不同，这次是延伸不是重播；
    v2 的证据/动机/近窗闸仍各自把关。）"""
    kg, cc = mk_cc()
    m = mat(kg, "经历_发烧")
    m.extra_attrs.update({"last_shared_ts": time.time() - 2 * 3600,
                          "last_shared_goal": "empathize",
                          "last_shared_basis": ["经历_发烧"]})  # 2h 前讲过
    spoken_ci(kg, "CI_s", ["经历_发烧"], "empathize", ago=2 * 3600 + 60)
    new = think_ci(kg, "CI_n", ["经历_发烧"], "ask_followup")
    assert cc._is_duplicate_recent(new, time.time(), 1800) is False


# ── 戳记随表达落下 ────────────────────────────────────────
def test_stamp_shared_marks_material_nodes():
    kg, cc = mk_cc()
    mat(kg, "经历_甲")
    ci = think_ci(kg, "CI_t", ["经历_甲"], "share_related_knowledge")
    cc._stamp_shared(ci, 12345.0)
    assert kg.nodes["经历_甲"].extra_attrs["last_shared_ts"] == 12345.0


# ── note_spoken：占冷却、不占限额 ──────────────────────────
def test_note_spoken_cools_proactive_but_keeps_quota():
    kg, cc = mk_cc()
    cc.note_spoken()
    assert cc._last_express_ts > time.time() - 2       # 冷却被占用
    assert len(cc._express_count_hour) == 0            # 不消耗主动分享配额


# ── 审问疲劳闸已拆除：问号数量不再否决询问 ─────────────────
def test_no_question_count_gate_anywhere():
    import continuous_cognition as _c
    assert not hasattr(_c.ContinuousCognition, "_interrogation_pressure")


# ── 近窗节流仍在工作（同族 30min 内的新料快打） ───────────
def test_near_window_throttle_survives_for_fresh_material():
    kg, cc = mk_cc()
    mat(kg, "经历_a")
    m2 = mat(kg, "经历_b", born_ago=30.0)
    spoken_ci(kg, "CI_w", ["经历_a", "经历_b"], "follow_up", ago=300)
    # 材料 b 诞生(30s前)晚于…… spoken 300s 前表达；b 未带戳 → fresh；
    # 但同 goal 同族（overlap=1.0≥0.5）300s<1800s → 近窗节流判重
    new = think_ci(kg, "CI_n", ["经历_a", "经历_b"], "follow_up")
    assert cc._is_duplicate_recent(new, time.time(), 1800) is True
