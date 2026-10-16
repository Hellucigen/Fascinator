# -*- coding: utf-8 -*-
"""§6.4 闸门：记忆再激活 ≠ 新证据（2026-10-16 统一校准）。

不变量：
  1. Hebbian 共激活强化只触 semantic/emotional 类边；disposition 的
     激活/指向/pair 边（cognitive_relation）运行时永不改写；
  2. 反复"回忆"（memory_recall 激活注入 + 多轮扩散）不增加任何
     evidence_count、不改 disposition strength——同一段记忆被多次
     激活不产生虚假证据累积；
  3. Hebbian 自身有界：单边相对首见基线增幅 ≤ max_gain（可逆不爆炸）。
"""
import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C                                              # noqa: E402
from graph_model import KnowledgeGraph, Node, Edge              # noqa: E402
from diffusion_engine import DiffusionEngine                    # noqa: E402
from disposition_store import DispositionStore                  # noqa: E402


def build_store():
    cfg = copy.deepcopy(C.DEFAULT_CONFIG)
    cfg.setdefault("disposition_store", {})["path"] = os.path.join(
        tempfile.mkdtemp(), "disposition.json")
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    ds = DispositionStore(kg, cfg)
    return kg, ds, cfg


def test_disposition_edges_immunity_and_evidence_stability():
    kg, ds, cfg = build_store()
    kg.add_node(Node(id="C:独处时刻", label="declarative-episodic",
                     graph_space="self", weight=0.5))
    pair = ds.get_or_create("C:独处时刻", "respond",
                            evidence_ref="[positive] 用户反馈好",
                            source="social:positive")
    assert pair is not None
    ev0 = int(pair.extra_attrs.get("evidence_count", 0))
    st0 = float(pair.extra_attrs.get("strength", 0))
    # pair 的图边（cognitive_relation 类）：激活边 + 指向边
    disp_edges = [e for e in kg.edges
                  if (pair.id in (e.src, e.dst)
                      and getattr(e, "relation_category", "")
                      == "cognitive_relation")]
    assert disp_edges, "pair 节点应有 cognitive_relation 边"
    w_snapshot = {(e.src, e.dst, e.relation): float(e.weight)
                  for e in disp_edges}

    eng = DiffusionEngine(kg, dict(cfg))
    # 200 轮"回忆"：把 pair 与其情境邻居反复点亮（memory_recall 注入）
    for _r in range(200):
        with kg._lock:
            pair.activation = 3.0
        eng.mark_active([pair.id])
        eng.register_activation_source([pair.id], "memory_recall")
        eng.diffuse_step()
    pair2 = kg.get_node(pair.id)
    assert int(pair2.extra_attrs.get("evidence_count", 0)) == ev0, \
        "反复回忆不得增加证据计数"
    assert abs(float(pair2.extra_attrs.get("strength", 0)) - st0) < 1e-9, \
        "反复回忆不得改写倾向强度"
    for e in kg.edges:
        key = (e.src, e.dst, e.relation)
        if key in w_snapshot:
            assert abs(float(e.weight) - w_snapshot[key]) < 1e-9, \
                "cognitive_relation 边在运行时被改写（白名单失守）: %s" % (key,)


def test_hebbian_bounded_growth():
    kg, _ds, cfg = build_store()
    a = Node(id="P:堵车", label="declarative-semantic", weight=0.6)
    b = Node(id="P:浪费时间", label="declarative-semantic", weight=0.6)
    kg.add_node(a)
    kg.add_node(b)
    kg.add_edge(Edge(src="P:堵车", dst="P:浪费时间", relation="导致",
                     weight=0.5, relation_category="causal_relation"))
    kg.add_edge(Edge(src="P:堵车", dst="P:浪费时间", relation="相关",
                     weight=0.5, relation_category="semantic_relation"))
    eng = DiffusionEngine(kg, dict(cfg))
    w0 = 0.5
    for _r in range(400):
        with kg._lock:
            kg.nodes["P:堵车"].activation = 3.0
        eng.mark_active(["P:堵车"])
        eng.register_activation_source(["P:堵车"], "memory_recall")
        eng.diffuse_step()
    sem = kg.get_edge("P:堵车", "P:浪费时间", "相关")
    causal = kg.get_edge("P:堵车", "P:浪费时间", "导致")
    hb = (cfg.get("hebbian") or {})
    cap = w0 * (1.0 + float(hb.get("max_gain", 0.5)))
    assert float(sem.weight) <= cap + 1e-6, \
        "semantic 边 Hebbian 增幅越过 max_gain 帽"
    assert float(sem.weight) > w0, "semantic 边应确有共激活强化"
    assert abs(float(causal.weight) - w0) < 1e-9, \
        "causal 类不在白名单，不应被动过"
