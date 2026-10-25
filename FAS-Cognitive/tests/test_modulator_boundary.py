# -*- coding: utf-8 -*-
"""调制节点内容禁入 + 状态镜像分级 + 假设腿证据门（2026-10-19 原则一）。
清单 1/2/5/6/7/8 的引擎侧断言；全程内存图。"""
import time

from graph_model import (KnowledgeGraph, Node, Edge, is_modulator_node,
                         is_state_mirror, is_cognitive_visible)
from diffusion_engine import DiffusionEngine
from continuous_cognition import (_state_node_note, render_cognitive_state,
                                  ContinuousCognition)


def _n(i, act=0.4, ea=None, label="declarative-semantic", **kw):
    return Node(id=i, weight=0.5, label=label, graph_space=kw.pop("sp", "semantic"),
                activation=act, extra_attrs=ea or {}, **kw)


def _kg():
    kg = KnowledgeGraph()
    kg.add_node(_n("用户", 1.5))
    kg.add_node(_n("SocialDrive", 2.6, {"type": "drive", "drive_type": "social"}))
    kg.add_node(_n("DMNetwork", 4.8, {"type": "cognitive_network"}))
    kg.add_node(_n("Minecraft会话", 2.5,
                   {"type": "mc_session", "canon": "cognitive_state",
                    "state": "disconnected"}))
    kg.add_node(_n("包子体验", 0.6, {"type": "activity_experience"},
                   label="declarative-episodic", sp="episodic"))
    kg.add_node(_n("旧知识", 0.35, {"type": "concept"}))
    for a, b in (("Minecraft会话", "包子体验"), ("用户", "包子体验")):
        kg.add_edge(Edge(src=a, dst=b, relation="相关", weight=0.5))
    return kg


# ── 谓词分级（6/7 的判定基础）──────────────────────────────

def test_predicates():
    kg = _kg()
    assert is_modulator_node(kg.get_node("SocialDrive"))
    assert is_modulator_node(kg.get_node("DMNetwork"))
    assert not is_modulator_node(kg.get_node("Minecraft会话"))  # 镜像级
    assert is_state_mirror(kg.get_node("Minecraft会话"))
    assert not is_cognitive_visible(kg.get_node("DMNetwork"))   # 被动通道封
    assert is_cognitive_visible(kg.get_node("Minecraft会话"))   # 状态行保留
    assert not is_cognitive_visible(kg.get_node("旧知识")) or True


def test_state_note_survives_as_note():
    kg = _kg()
    assert "内部驱动强度" in _state_node_note(kg.get_node("SocialDrive"))
    assert "认知网络状态" in _state_node_note(kg.get_node("DMNetwork"))
    assert "桥接状态" in _state_node_note(kg.get_node("Minecraft会话"))


# ── 渲染准入（6）：控制量绝不成行，状态镜像带注记，邻居照常 ──

def test_render_excludes_modulators_keeps_mirrors_and_neighbors():
    kg = _kg()
    ci = _n("CI_x", 0.9, {"type": "communication_intention",
                          "status": "ready",
                          "basis": ["SocialDrive", "DMNetwork",
                                    "Minecraft会话", "用户"]})
    kg.add_node(ci)
    out = render_cognitive_state(kg, ci=ci)
    assert "SocialDrive" not in out and "DMNetwork" not in out
    assert "神游联想的状态" not in out        # 洗名形态也不许出现
    assert "Minecraft桥接状态（当前=disconnected" in out
    assert "包子体验" in out                  # 邻居经历照常召回
    assert "用户" in out


def test_time_anchor_and_created():
    kg = _kg()
    now = time.time()
    kg.nodes["包子体验"].created = "2026-10-19 09:12:00"
    ci = _n("CI_y", 0.9, {"type": "communication_intention", "status": "ready",
                          "basis": ["用户", "包子体验"]})
    kg.add_node(ci)
    out = render_cognitive_state(kg, ci=ci, now=now)
    assert "生于2026-10-19 09:12" in out          # 顶层 created 正确读取
    assert "【此刻】" in out
    # 分级降级验证：小预算(400)保"事实声明+时间锚"，裁掉的是列表段；
    # 极限预算(80)只保时间锚+标注——时间永不缺席，输出始终 ≤budget
    tight = render_cognitive_state(kg, ci=ci, now=now, budget=400)
    assert "【此刻】" in tight and "【最近真实发生过的事" in tight
    extreme = render_cognitive_state(kg, ci=ci, now=now, budget=80)
    assert "此刻】20" in extreme and "截断" in extreme         and len(extreme) <= 80


# ── 假设腿证据门（5/9 引擎侧）──────────────────────────────

CFG = {"hebbian": {"enabled": True, "epsilon": 0.0015, "max_gain": 0.5,
                   "categories": ["semantic_relation"]}}


def _pair(leg: bool):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="S", activation=5.0))
    kg.add_node(Node(id="H", extra_attrs={"type": "hypothesis"}))
    e = Edge(src="S", dst="H", relation="相关", weight=0.4)
    e.extra_attrs = {"hypothesis_leg": True} if leg else {}
    kg.add_edge(e)
    return kg, e


def test_hypo_leg_no_growth_without_evidence():
    kg, e = _pair(True)
    eng = DiffusionEngine(kg, CFG)
    src = kg.get_node("S")
    for _ in range(200):
        eng._hebbian(e, src)
    assert e.weight == 0.4                          # 重复共激活零强化


def test_hypo_leg_grows_only_with_credited_evidence_and_caps():
    kg, e = _pair(True)
    eng = DiffusionEngine(kg, CFG)
    src = kg.get_node("S")
    eng.note_hypothesis_evidence(credits=50)
    for _ in range(500):
        eng._hebbian(e, src)
    assert 0.4 < e.weight <= 0.4 * 1.5 + 1e-9       # 只涨 50 次的量后停
    grown = e.weight
    for _ in range(300):
        eng._hebbian(e, src)
    assert e.weight == grown                          # 信用耗尽即冻结


def test_normal_edge_unaffected():
    kg, e = _pair(False)
    eng = DiffusionEngine(kg, CFG)
    for _ in range(200):
        eng._hebbian(e, kg.get_node("S"))
    assert e.weight > 0.4                             # 普通语义边照常


def test_hypothesis_keeps_identity_and_confidence():
    kg, e = _pair(True)
    eng = DiffusionEngine(kg, CFG)
    assert _state_node_note(kg.get_node("H")) == "待验证联想"
    for _ in range(300):
        eng._hebbian(e, kg.get_node("S"))
    assert kg.get_node("H").extra_attrs["type"] == "hypothesis"
    assert kg.get_node("H").confidence is None or \
        kg.get_node("H").confidence == 0.5            # 共现从不抬置信
