# -*- coding: utf-8 -*-
"""枢纽背景激活 + 疾病·关怀种子包（2026-10-17 用户设计）。零 LLM。
核心契约：① 种子包幂等且把 发烧→疾病→病人→关心→社交需求 接通；
② 地板=每拍衰减后恰好补回（钳下界不钳上界 → 有界，不 runaway）；
③ 易失产物/自维护节点不给地板。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import Edge, KnowledgeGraph, Node   # noqa: E402
import self_graph                                     # noqa: E402
import disease_care_pack                              # noqa: E402
import pytest                                         # noqa: E402


class StubEngine:
    def __init__(self):
        self.marked = []
    def mark_active(self, ids):
        self.marked.append(list(ids))


def nd(kg, nid, label="declarative-semantic", typ=None, act=0.0):
    kg.add_node(Node(id=nid, weight=0.5, label=label,
                     graph_space="semantic",
                     extra_attrs={"type": typ} if typ else None))
    n = kg.nodes[nid]
    n.activation = act
    return n


def hub_kg():
    kg = KnowledgeGraph()
    nd(kg, "Self", label="self")
    nd(kg, "用户")
    nd(kg, "能力:聊天", act=0.0)                      # Self 事实
    nd(kg, "社交需求", act=0.0)                       # 用户事实
    nd(kg, "CI_1", typ="communication_intention")     # 产物：排除
    nd(kg, "思考_9", label="declarative-episodic", typ="thought")
    nd(kg, "SocialDrive", typ="drive", act=0.9)       # 场维护：排除
    kg.edges += [
        Edge(src="Self", dst="能力:聊天", relation="能", weight=0.8),
        Edge(src="Self", dst="CI_1", relation="意图", weight=0.5),
        Edge(src="Self", dst="思考_9", relation="经历", weight=0.5),
        Edge(src="Self", dst="SocialDrive", relation="处于", weight=0.5),
        Edge(src="用户", dst="社交需求", relation="相关", weight=0.7),
    ]
    kg.rebuild_indexes()
    return kg


def test_targets_pick_facts_exclude_artifacts():
    t = self_graph.hub_floor_targets(hub_kg())
    assert t.get("能力:聊天") == pytest.approx(0.35)
    assert t.get("社交需求") == pytest.approx(self_graph.HUB_FLOORS["用户"])
    assert "CI_1" not in t and "思考_9" not in t and "SocialDrive" not in t


def test_floor_is_bounded_equilibrium():
    kg = hub_kg()
    eng = StubEngine()
    t = self_graph.hub_floor_targets(kg, {})
    self_graph.apply_hub_floors(kg, eng, t)
    assert kg.nodes["能力:聊天"].activation == pytest.approx(0.35)
    # 每拍模拟"衰减 0.9 后钳位"：值稳定在地板，不随次数增长（平衡）
    for _ in range(50):
        for n in kg.nodes.values():
            n.activation *= 0.9
        self_graph.apply_hub_floors(kg, eng, t)
    assert kg.nodes["能力:聊天"].activation == pytest.approx(0.35)
    # 高于地板的不许被抬高（只钳下界）
    kg.nodes["能力:聊天"].activation = 5.0
    self_graph.apply_hub_floors(kg, eng, t)
    assert kg.nodes["能力:聊天"].activation == 5.0
    assert eng.marked                        # 驻前沿参与联想


def test_care_pack_idempotent_and_chained():
    kg = KnowledgeGraph()
    nd(kg, "Self", label="self")
    nd(kg, "用户")
    nd(kg, "发烧"); nd(kg, "身体不适"); nd(kg, "喝水"); nd(kg, "休息")
    nd(kg, "社交需求"); nd(kg, "行为:共情")
    r1 = disease_care_pack.ensure(kg)
    assert r1["nodes"] == 4 and r1["edges"] > 10
    r2 = disease_care_pack.ensure(kg)
    assert r2 == {"nodes": 0, "edges": 0}              # 幂等
    assert kg.get_edge("发烧", "疾病", "属于") is not None
    assert any(e.src == "病人" and e.dst == "关心" for e in kg.edges)
    # 关系名过 graph_schema 受控词表归一（满足→导致等）：按归一后的
    # 真实词表断言——连通性在，词表收敛也是纪律。
    assert any(e.src == "关心" and e.dst == "社交需求" for e in kg.edges)
    assert kg.get_edge("Self", "关心", "相关") is not None
    # 降级调制器镜像（"X样"命名约定）不得常驻她心里
    nd(kg, "组胺样", typ="prior_concept", act=0.0)
    kg.edges.append(Edge(src="Self", dst="组胺样", relation="处于",
                         weight=0.7, relation_category="cognitive_relation"))
    kg.rebuild_indexes()
    # 关怀进入枢纽背景集（关心经 Self 直连 → 有地板）
    t = self_graph.hub_floor_targets(kg)
    assert t.get("组胺样") is None                    # 已删生理不复活
    assert t.get("关心") is not None


def test_care_counts_as_user_relevant_bridge():
    """念头→动作的桥（2026-10-17 用户设计：关心的念头要促进主动开口）。
    沟通意图里"用户相关性"的判据=用户有出边指向焦点节点
    （continuous_cognition 以 get_out_edges("用户") 计 user_relevant）。
    种子包必须让 关心 经这条桥被认出。"""
    kg = KnowledgeGraph()
    for n in ("Self", "用户", "发烧"):
        nd(kg, n)
    disease_care_pack.ensure(kg)
    user_edges = {e.dst: float(e.weight or 0)
                  for e in kg.get_out_edges("用户")}
    assert user_edges.get("关心", 0) > 0.2      # 关心=用户相关事实
    basis_pool = [kg.nodes["发烧"], kg.nodes["关心"]]
    user_relevant = sum(1 for n in basis_pool
                        if user_edges.get(n.id, 0) > 0.2)
    assert user_relevant >= 1                   # 焦点含关心→计入相关性
    # 与 CC 同一公式：social_relevance 由 user_relevant 抬升
    social_relevance = min(1.0, 0.0 + 0.15 * min(user_relevant, 3))
    assert social_relevance > 0
