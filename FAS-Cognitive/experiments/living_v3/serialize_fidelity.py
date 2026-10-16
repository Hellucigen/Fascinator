# -*- coding: utf-8 -*-
"""living_v3/serialize_fidelity.py — 历史 D（图谱→文本信息丢失）的结构保真探针。

历史证据（cross_episode_recomb/analyze.py:164）："3 跳链在 Top-8 预算下
全条件失败 → 工作集容量"；GOAL_PATH_AUDIT 元结论："负结果主发生部位在
扩散下游（Top-k 预算截断、序列化/消费者接口）"。

本探针不改生产序列化器，而是定义**下游可用信息**的验收口径：
构造一个含 步骤/前置条件/反例/正向证据 的结构化子图，分别经
  (a) 模拟旧路径：topk 截断 → 文本化（只保留激活最高节点的一跳邻居）
  (b) v3 路径：CognitiveProduct 直接引用证据节点（relation_finding）
对比两条路径下游可恢复的结构字段（步骤数/条件/反例标记/正向证据）。
结论以"字段存活数"计，不以文本相似度计。
"""
from dataclasses import dataclass, field


@dataclass
class StructureProbe:
    """构造的可验证结构：配方 + 步骤 + 前置 + 反例 + 正向证据。"""
    goal: str
    steps: list                    # ["采集A", "合成B", "使用C"]
    preconditions: list            # ["需要工具:镐", "燃料≥1"]
    counter_evidence: list         # ["配方B曾失败：缺燃料"]
    positive_evidence: list        # ["配方B有一次成功记录"]
    node_ids: list = field(default_factory=list)


def build_probe(kg):
    """在给定（隔离）图中构造探针结构，返回 StructureProbe。"""
    from graph_model import Node, Edge
    ids = []
    spec = StructureProbe(
        goal="合成B",
        steps=["采集A", "合成B", "使用C"],
        preconditions=["需要工具:镐", "燃料≥1"],
        counter_evidence=["配方B曾失败：缺燃料"],
        positive_evidence=["配方B有一次成功记录"])
    prev = None
    for i, step in enumerate(spec.steps):
        nid = f"探针步骤{i}"
        kg.add_node(Node(id=nid, weight=0.7, graph_space="episodic",
                         extra_attrs={"type": "probe_step",
                                      "step": step, "order": i}))
        ids.append(nid)
        if prev:
            kg.add_edge(Edge(src=prev, dst=nid, relation="时间顺序",
                             weight=0.8, relation_category="temporal"))
        prev = nid
    for i, pre in enumerate(spec.preconditions):
        nid = f"探针前置{i}"
        kg.add_node(Node(id=nid, weight=0.6, graph_space="semantic",
                         extra_attrs={"type": "probe_pre", "cond": pre}))
        ids.append(nid)
        kg.add_edge(Edge(src=nid, dst="探针步骤1", relation="前置",
                         weight=0.7, relation_category="cognitive_relation"))
    for i, ce in enumerate(spec.counter_evidence):
        nid = f"探针反例{i}"
        kg.add_node(Node(id=nid, weight=0.5, graph_space="episodic",
                         extra_attrs={"type": "probe_counter", "fact": ce}))
        ids.append(nid)
        kg.add_edge(Edge(src=nid, dst="探针步骤1", relation="反例",
                         weight=0.6, relation_category="evidence"))
    for i, pe in enumerate(spec.positive_evidence):
        nid = f"探针正例{i}"
        kg.add_node(Node(id=nid, weight=0.5, graph_space="episodic",
                         extra_attrs={"type": "probe_positive", "fact": pe}))
        ids.append(nid)
    spec.node_ids = ids
    return spec


def old_path_recover(spec, topk_ids, kg, k=8):
    """模拟旧路径：topk 截断（只保留 topk_ids 前 k 个节点）→ 一跳文本化。
    返回下游可恢复的字段集合。"""
    kept = set(topk_ids[:k])
    recovered = {"steps": [], "preconditions": [], "counter": [],
                 "positive": []}
    for nid in spec.node_ids:
        if nid not in kept:
            continue
        probe = kg.nodes[nid].extra_attrs or {}
        if probe.get("type") == "probe_step":
            recovered["steps"].append(probe["step"])
        elif probe.get("type") == "probe_pre":
            recovered["preconditions"].append(probe["cond"])
        elif probe.get("type") == "probe_counter":
            recovered["counter"].append(probe["fact"])
        elif probe.get("type") == "probe_positive":
            recovered["positive"].append(probe["fact"])
    return recovered


def v3_path_recover(spec, products, kg):
    """v3 路径：relation_finding 产物直接携带证据引用，无 topk 截断。
    返回下游可恢复的字段集合。"""
    recovered = {"steps": [], "preconditions": [], "counter": [],
                 "positive": []}
    for p in products:
        for nid in p.evidence_ids:
            if nid not in kg.nodes:
                continue
            probe = kg.nodes[nid].extra_attrs or {}
            if probe.get("type") == "probe_step":
                recovered["steps"].append(probe["step"])
            elif probe.get("type") == "probe_pre":
                recovered["preconditions"].append(probe["cond"])
            elif probe.get("type") == "probe_counter":
                recovered["counter"].append(probe["fact"])
            elif probe.get("type") == "probe_positive":
                recovered["positive"].append(probe["fact"])
    return recovered
