# -*- coding: utf-8 -*-
"""情景时间链（任务书 2026-10-21 第 1 条）：锚点生成、序边与权重、乱序
插入切开重连、时段边随迁、幂等、脚手架谓词（不可见/不发射）。全内存。"""
from graph_model import (KnowledgeGraph, Node, Edge, is_content_scaffold,
                         is_non_emitting)
from time_chain import anchor_episode, gap_weight
from config import DEFAULT_CONFIG
from diffusion_engine import DiffusionEngine


def _ep(kg, nid, ts, created="2026-10-21 10:00:00"):
    kg.add_node(Node(id=nid, weight=0.5, label="declarative-episodic",
                     graph_space="episodic", activation=0.4, created=created,
                     extra_attrs={"type": "activity_experience"}))
    return nid


def test_anchor_creation_and_phase_move():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="上午", weight=0.5, label="declarative-semantic",
                     extra_attrs={"type": "day_phase"}))
    _ep(kg, "Activity_x", 100.0)
    kg.add_edge(Edge(src="Activity_x", dst="上午", relation="发生于时段",
                     weight=0.6))
    aid = anchor_episode(kg, "Activity_x", ts=100.0)
    assert aid == "时点_100000"
    n = kg.get_node(aid)
    assert (n.extra_attrs or {}).get("type") == "time_node"
    assert is_content_scaffold(n) and is_non_emitting(n)
    rels = {(e.src, e.relation, e.dst) for e in kg.edges}
    assert ("Activity_x", "发生于", aid) in rels
    # 时段边随迁（时间信息由链承担）
    assert (aid, "发生于时段", "上午") in rels
    assert ("Activity_x", "发生于时段", "上午") not in rels
    # 幂等
    assert anchor_episode(kg, "Activity_x", ts=100.0) is None


def test_chain_ordering_and_weights():
    kg = KnowledgeGraph()
    _ep(kg, "E1", 100.0)
    _ep(kg, "E2", 100.0 + 6 * 3600)
    anchor_episode(kg, "E1", ts=100.0)
    anchor_episode(kg, "E2", ts=100.0 + 6 * 3600)
    a1, a2 = "时点_100000", "时点_21700000"
    e = next(x for x in kg.edges if x.src == a1 and x.dst == a2)
    assert e.relation == "早于"
    assert abs(e.weight - gap_weight(6 * 3600)) < 1e-6
    assert any(x.src == a2 and x.dst == a1 and x.relation == "晚于"
               for x in kg.edges)
    assert e.weight >= 0.6 and e.weight <= 0.9


def test_out_of_order_insertion_splits_pair():
    kg = KnowledgeGraph()
    _ep(kg, "E1", 100.0)
    _ep(kg, "E3", 100.0 + 10 * 3600)
    _ep(kg, "E2", 100.0 + 5 * 3600)
    anchor_episode(kg, "E1", ts=100.0)
    anchor_episode(kg, "E3", ts=100.0 + 10 * 3600)
    a1, a2, a3 = "时点_100000", "时点_18100000", "时点_36100000"
    # 先成对
    assert any(x.src == a1 and x.dst == a3 and x.relation == "早于"
               for x in kg.edges)
    anchor_episode(kg, "E2", ts=100.0 + 5 * 3600)   # 迟到者插中间
    triples = {(e.src, e.relation, e.dst) for e in kg.edges}
    assert (a1, "早于", a3) not in triples      # 旧序对切开
    assert (a1, "早于", a2) in triples and (a2, "早于", a3) in triples
    assert (a3, "晚于", a2) in triples and (a2, "晚于", a1) in triples


def test_add_edge_rejects_self_loops():
    """自环=坏抽取形态（种子自映射/抽取漏斗 src==dst）。唯一主写入口拒收。"""
    kg = KnowledgeGraph()
    _ep(kg, "X", 1.0)
    assert kg.add_edge(Edge(src="X", dst="X", relation="产生", weight=0.7)) \
        is False
    assert not any(e.src == e.dst for e in kg.edges)


def test_anchor_never_emits():
    """锚点只进不出：episode 泵锚点可以，锚点不得泵邻居。"""
    kg = KnowledgeGraph()
    _ep(kg, "E1", 100.0)
    _ep(kg, "E2", 200.0)
    anchor_episode(kg, "E1", ts=100.0)
    anchor_episode(kg, "E2", ts=200.0)
    kg.get_node("E1").activation = 2.0
    kg.get_node("E2").activation = 0.0     # E2 零能量：a2 若变亮只能来自 a1
    eng = DiffusionEngine(kg, dict(DEFAULT_CONFIG, diffusion_mode="cascade"))
    eng.mark_active([n.id for n in kg.nodes.values()
                     if float(n.activation or 0) > 0])
    eng.diffuse_step()
    assert kg.get_node("时点_100000").activation > 0      # 接收合法
    assert kg.get_node("时点_200000").activation == 0.0   # a1 未沿 早于 泵出
    assert kg.get_node("E2").activation == 0.0            # 锚点没回灌情景
