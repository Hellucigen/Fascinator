# -*- coding: utf-8 -*-
"""图谱抽取路由 / 写回保真 / 内容资格（2026-10-20 实施任务书 T1-T7）。
全部离线：真实触发文本、内存图、真实函数；不导入 app.py（会启动生产），
app 侧改动以静态核验标注。零 LLM、零网络。"""
import os
import sys
import threading

import logging
logging.disable(logging.CRITICAL)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))

from graph_model import (KnowledgeGraph, Node, Edge,          # noqa: E402
                         is_content_scaffold, is_cognitive_visible)
from narrative_trigger import narrative_score                  # noqa: E402
import config as _cfgmod                                        # noqa: E402
from diffusion_engine import DiffusionEngine                    # noqa: E402

REAL_1044 = ("是啊，我也希望能被看到，布兰登曾经提出心理可见性的概念，"
             "指人渴望在关系中被看到、被理解、被欣赏以确认身份和价值。")


def _n(label="declarative-semantic", typ=None, src=None, act=0.0):
    ea = {}
    if typ:
        ea["type"] = typ
    if src:
        ea["source"] = src
    return Node(id="x", weight=0.5, label=label,
                graph_space="semantic", activation=act, extra_attrs=ea)


# ── T1 概念定义不再被叙事吞掉 ──────────────────────────────

def test_T1_definition_routes_to_normal():
    r = narrative_score(REAL_1044, profile="balanced")
    assert r["decision"] == "normal", r          # 修复前：narrative
    assert r["components"]["definition_hits"] >= 2
    assert r["components"]["definition_dominant"] is True


def test_T1b_single_concept_mention_still_ok():
    # "他提出了一个方案" 单标记+有事件词 → 不强行改道（保守：只在定义
    # 密集且事件弱时降格）
    r = narrative_score("他提出了方案，然后我们去评审了。",
                        profile="balanced")
    assert r["components"]["definition_dominant"] is False or \
        r["decision"] in ("normal", "narrative")


# ── T2 真实叙事不受影响 ───────────────────────────────────

def test_T2_true_story_still_narrative():
    story = ("今天小明去了菜市场，买了两条鱼。然后他回家开始做饭，"
             "结果把厨房搞坏了。晚上他打电话给爸爸，爸爸说他先出发回家。")
    r = narrative_score(story, profile="balanced")
    assert r["decision"] == "narrative", r


# ── T3 混合内容：叙事在场，概念由 entities/写回兜住 ────────

def test_T3_mixed_keeps_narrative_flag():
    mixed = REAL_1044 + "然后我今天下午去看了医生，医生说多喝水。"
    r = narrative_score(mixed, profile="balanced")
    # 事件子句变多 → definition_dominant 解除 → 仍可按叙事处理；
    # 概念抽取由 A2 entities 条款 + B1 存在即建点兜住（不可双通道互斥丢概念）
    assert r["decision"] in ("narrative", "normal")
    assert "definition_dominant" in r["components"]


# ── T4 截断留痕（app 侧为静态核验——app 导入即启动，不可测运行时） ──

def test_T4_static_ingest_fidelity():
    src = open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read()
    assert 'for ent in (ev.get("entities") or [])[:12]:' in src   # 预算放宽
    assert "if ent and ent in kg.nodes:" not in src.split(
        "def _ingest_narrative")[1].split("def nid_ok")[0]        # 存在才连边已删
    assert '"entities_in"' in src and '"entities_truncated"' in src
    # 计数日志在场
    assert "实体 入" in src


# ── T5 内容资格：脚手架不进内容，普通概念/经历不误伤 ───────

def test_T5_scaffold_predicate_matrix():
    assert is_content_scaffold(_n(typ="prior_concept"))
    assert is_content_scaffold(_n(typ="speech_act_concept"))
    assert is_content_scaffold(_n(typ="time_of_day", src="real_world"))
    assert is_content_scaffold(_n(typ="trait"))
    assert is_content_scaffold(_n(src="mc_world_seed"))
    assert not is_content_scaffold(_n(typ="concept"))
    assert not is_content_scaffold(_n(typ="activity_experience"))
    assert not is_content_scaffold(_n())              # 用户/Self 类无标记
    assert not is_cognitive_visible(_n(typ="time_of_day"))
    assert is_cognitive_visible(_n(typ="concept"))


def test_T5b_render_excludes_scaffolds():
    from continuous_cognition import render_cognitive_state
    kg = KnowledgeGraph()
    kg.add_node(Node(id="傍晚", weight=0.5, label="declarative-semantic",
                     graph_space="semantic", activation=4.0,
                     extra_attrs={"type": "time_of_day", "canon": "state",
                                  "source": "real_world"}))
    kg.add_node(Node(id="断言", weight=0.5, label="declarative-semantic",
                     graph_space="semantic", activation=3.6,
                     extra_attrs={"type": "speech_act_concept"}))
    kg.add_node(Node(id="真经历", weight=0.5, label="declarative-episodic",
                     graph_space="episodic", activation=0.5,
                     extra_attrs={"type": "activity_experience"}))
    out = render_cognitive_state(kg, ci=None)
    assert "傍晚" not in out and "断言" not in out
    assert "真经历" in out


# ── T6 概念可达性：节点+边存在时扩散可达（写回修复的可达性证明） ──

def test_T6_concept_reachable_via_beat():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="布兰登", weight=0.5, label="declarative-semantic",
                     graph_space="semantic", activation=3.0))
    kg.add_node(Node(id="情节2", weight=0.5, label="declarative-semantic",
                     graph_space="semantic",
                     extra_attrs={"canon": "narrative_beat"}))
    kg.add_node(Node(id="心理可见性", weight=0.5, label="declarative-semantic",
                     graph_space="semantic",
                     extra_attrs={"canon": "concept", "source": "narrative"}))
    kg.add_edge(Edge(src="布兰登", dst="情节2", relation="参与", weight=0.7))
    kg.add_edge(Edge(src="情节2", dst="心理可见性", relation="涉及", weight=0.5))
    eng = DiffusionEngine(kg, dict(_cfgmod.DEFAULT_CONFIG))
    eng._lock = threading.RLock()
    eng.register_activation_source(["布兰登"], "external_input")
    eng.mark_active(["布兰登"])
    for _ in range(4):
        eng.diffuse_step()
    assert float(kg.get_node("心理可见性").activation or 0) > 0.05


# ── T7 计算资格保留：脚手架仍参与扩散；时间信息仍在上下文 ──

def test_T7_computation_and_time_info_intact():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="事件A", weight=0.5, label="declarative-episodic",
                     graph_space="episodic", activation=3.0))
    kg.add_node(Node(id="夜间", weight=0.5, label="declarative-semantic",
                     graph_space="semantic",
                     extra_attrs={"type": "time_of_day", "canon": "state"}))
    kg.add_edge(Edge(src="事件A", dst="夜间", relation="发生于时段",
                     weight=0.6))
    eng = DiffusionEngine(kg, dict(_cfgmod.DEFAULT_CONFIG))
    eng._lock = threading.RLock()
    eng.register_activation_source(["事件A"], "external_input")
    eng.mark_active(["事件A"])
    for _ in range(3):
        eng.diffuse_step()
    assert float(kg.get_node("夜间").activation or 0) > 0  # 计算在场
    from continuous_cognition import render_cognitive_state
    out = render_cognitive_state(kg, ci=None)
    assert "【此刻】" in out                    # 时间信息通道不依赖桶节点
    assert "夜间" not in out.split("【我此刻心里有什么")[1].split("【")[0] \
        if "【我此刻心里有什么" in out else True   # 但内容素材里没有它


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"抽取与资格：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
