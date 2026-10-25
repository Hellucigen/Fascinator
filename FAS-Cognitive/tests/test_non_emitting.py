# -*- coding: utf-8 -*-
"""不发射能量节点闸（2026-10-20）：状态镜像/思考/反思类节点接收激活但不外泼。
根因场景：Minecraft会话 ↔ 思考 双向 关于 边在非消耗级联里自激到封顶 5.0，
把调试气泡和基底长期占住。标准路与级联路都必须封。全程内存图。"""
from graph_model import (KnowledgeGraph, Node, Edge, is_non_emitting,
                         is_state_mirror)
from diffusion_engine import DiffusionEngine
from config import DEFAULT_CONFIG


def _n(i, act=0.0, ea=None, sp="semantic"):
    return Node(id=i, weight=0.5, label="declarative-semantic", graph_space=sp,
                activation=act, extra_attrs=ea or {})


def _cavity_kg():
    kg = KnowledgeGraph()
    # 腔体：镜像与思考互相 关于，双双封顶
    kg.add_node(_n("Minecraft会话", 5.0, {"type": "mc_session", "canon": "cognitive_state"}))
    kg.add_node(_n("思考_1", 5.0, {"type": "thought"}))
    kg.add_node(_n("正常概念", 0.5, {"type": "concept"}))
    # 正常链：X → Y，证明闸没有把普通扩散一起封掉
    kg.add_node(_n("X", 1.5, {"type": "concept"}))
    kg.add_node(_n("Y", 0.0, {"type": "concept"}))
    kg.add_edge(Edge(src="Minecraft会话", dst="思考_1", relation="关于", weight=0.6))
    kg.add_edge(Edge(src="思考_1", dst="Minecraft会话", relation="关于", weight=0.6))
    kg.add_edge(Edge(src="思考_1", dst="正常概念", relation="关于", weight=0.6))
    kg.add_edge(Edge(src="X", dst="Y", relation="相关", weight=0.6))
    return kg


def _engine(mode=None):
    cfg = dict(DEFAULT_CONFIG)
    if mode:
        cfg["diffusion_mode"] = mode
    return cfg


def test_predicate():
    kg = _cavity_kg()
    assert is_non_emitting(kg.get_node("Minecraft会话"))   # 状态镜像并入不发射
    assert is_non_emitting(kg.get_node("思考_1"))
    assert is_state_mirror(kg.get_node("Minecraft会话"))
    assert not is_non_emitting(kg.get_node("正常概念"))
    assert not is_non_emitting(kg.get_node("X"))


def _run(kg, cfg, steps=12):
    eng = DiffusionEngine(kg, cfg)
    ids = list(kg.nodes.keys())
    eng.mark_active(ids)
    for _ in range(steps):
        eng.decay_step()
        eng.diffuse_step()
    return eng


def test_standard_path_no_refill():
    kg = _cavity_kg()
    _run(kg, _engine())
    # 思考不再外泼：正常概念只吃初始值/衰减，绝不被腔体灌回
    assert kg.get_node("正常概念").activation < 0.5
    # MC 的唯一邻居是同样不发射的思考_1——腔死则 MC 只能单调衰减
    assert kg.get_node("Minecraft会话").activation < 5.0
    assert kg.get_node("思考_1").activation < 5.0
    # 普通扩散仍然活着
    assert kg.get_node("Y").activation > 0.0


def test_cascade_path_no_refill():
    cfg = _engine("cascade")
    kg = _cavity_kg()
    _run(kg, cfg)
    assert kg.get_node("正常概念").activation < 0.5
    # 级联路同样封死：MC 无任何可发射的能量来源，必须往下掉
    assert kg.get_node("Minecraft会话").activation < 5.0
    # 思考_1 允许从"正常概念"合法接收（双向 关于），但腔体不再自放大：
    # 增益上限 = 正常概念 的若干步 push，远小于腔体活着时的封顶钉死
    assert kg.get_node("思考_1").activation < 5.0 + 12 * 0.5 * 0.6
    assert kg.get_node("Y").activation > 0.0


def test_incoming_activation_still_allowed():
    """闸只禁外泼，不禁接收：X(高能)→思考_1(零能) 的能量照常进来。"""
    kg = KnowledgeGraph()
    kg.add_node(_n("思考_1", 0.0, {"type": "thought"}))
    kg.add_node(_n("X", 1.5, {"type": "concept"}))
    kg.add_edge(Edge(src="X", dst="思考_1", relation="相关", weight=0.8))
    eng = DiffusionEngine(kg, _engine())
    eng.mark_active(["X", "思考_1"])
    eng.decay_step()
    eng.diffuse_step()
    assert kg.get_node("思考_1").activation > 0.1


def _mirror_pump_kg():
    """复发链的压缩版：能力链(Self 地板→实现于)合法地把能量送到镜像。"""
    kg = KnowledgeGraph()
    kg.add_node(_n("Minecraft会话", 0.0,
                   {"type": "mc_session", "canon": "cognitive_state"},
                   sp="self"))
    kg.add_node(_n("进入Minecraft世界", 1.42, {"category": "cognitive_action"}))
    kg.add_edge(Edge(src="进入Minecraft世界", dst="Minecraft会话",
                     relation="实现于", weight=0.8))
    return kg


def test_mirror_receives_no_diffusion_standard():
    kg = _mirror_pump_kg()
    _run(kg, _engine(), steps=6)
    assert kg.get_node("Minecraft会话").activation == 0.0


def test_mirror_receives_no_diffusion_cascade():
    kg = _mirror_pump_kg()
    _run(kg, _engine("cascade"), steps=6)
    assert kg.get_node("Minecraft会话").activation == 0.0
