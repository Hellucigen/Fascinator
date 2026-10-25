# -*- coding: utf-8 -*-
"""调试下行（2026-10-19 用户需求）：主动表达时 refs.graph 附带"这条话
所用的图谱"，Charon 气泡据此展开。形态钉 + 故障降级钉。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge
from continuous_cognition import ContinuousCognition, ST_READY


class FakeEngine:
    def __init__(self):
        import threading
        self._lock = threading.RLock()
        self.topk = []

    def register_activation_source(self, ids, source_type="external_input"):
        pass

    def get_topk(self, k=15):
        return self.topk[:k], []

    def decay_step(self): pass
    def diffuse_step(self): pass
    def mark_active(self, ids): pass
    def mark_edges_active(self, edges): pass
    def clear_anchors(self): pass


class FakeNLP:
    def __init__(self, out_text):
        self.out = out_text
        self.system_prompt = lambda name: "stub"
        from langchain_core.runnables import RunnableLambda
        self.chat_llm = RunnableLambda(lambda *a, **k: type(
            "R", (), {"content": self.out})())


class FakeBuffer:
    def add_expression(self, e): pass


class FakeChannel:
    name = "fake"

    def __init__(self):
        self.sent = []

    def deliver(self, u):
        self.sent.append(u)
        return True


CFG = {"continuous_cognition": {"tick_seconds": 0.01, "pulse_every_ticks": 1,
                                 "inhibition_cooldown_s": 0.1}}


def _mk(out_text, with_edge=True):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="用户", weight=1.0, graph_space="semantic",
                     activation=2.0))
    kg.add_node(Node(id="恐惧", weight=0.6, graph_space="semantic",
                     activation=1.0,
                     extra_attrs={"type": "emotion", "valence": -0.7}))
    if with_edge:
        kg.add_edge(Edge(src="恐惧", dst="用户", relation="相关", weight=0.4))
    # 不在 basis 里的热节点：视图扩成"basis+全部热节点"后应带 role=hot 出现
    kg.add_node(Node(id="弹丸真人视频", weight=0.5,
                     label="declarative-episodic", graph_space="episodic",
                     activation=0.5,
                     extra_attrs={"type": "activity_experience"}))
    ch = FakeChannel()
    ci = Node(id="CI_dbg", weight=0.5, label="intention", graph_space="self",
              extra_attrs={"type": "communication_intention",
                           "kind": "communication", "status": ST_READY,
                           "activation": 0.9, "basis": ["用户", "恐惧", "失踪节点"],
                           "reply_goal": "share_related_knowledge"})
    kg.add_node(ci)
    cc = ContinuousCognition(kg, FakeEngine(), FakeNLP(out_text),
                             FakeBuffer(), dict(CFG), channels=[ch])
    return kg, cc, ci, ch


def test_debug_graph_shape_and_annotations():
    kg, cc, ci, ch = _mk("新内容一句话，关于恐惧的。")
    g = cc._debug_graph_for(ci)
    assert g["goal"] == "share_related_knowledge"
    by = {n["id"]: n for n in g["nodes"]}
    assert by["用户"]["note"] == "概念"      # 标注与语言层所见一致（同源函数）
    assert by["恐惧"]["act"] == 1.0
    assert by["失踪节点"]["note"] == "已不存在"
    assert ["恐惧", "相关", "用户", 0.4] in g["edges"]
    # 扩展视图：basis+全部热节点（与语言层切片同规则），角色可分辨
    assert by["弹丸真人视频"]["role"] == "hot"
    assert by["用户"]["role"] == "basis"


def test_express_delivers_refs_graph():
    kg, cc, ci, ch = _mk("今天的风很大，和恐惧没关系的新句子。")
    assert cc._express(ci) is True
    u = ch.sent[-1]
    assert u.origin == "proactive"
    assert u.refs["ci_id"] == "CI_dbg"
    gr = u.refs["graph"]
    assert {n["id"] for n in gr["nodes"]} == {
        "用户", "恐惧", "失踪节点", "弹丸真人视频"}
    roles = {n["id"]: n["role"] for n in gr["nodes"]}
    assert roles["弹丸真人视频"] == "hot" and roles["用户"] == "basis"


def test_dirty_basis_degrades_not_crashes():
    """脏 basis → 无 basis 节点，但热节点仍如实呈现（视图=材料全貌，
    不是 basis 的从属品）；话照说、投递照走。"""
    kg, cc, ci, ch = _mk("另一句全新的话，足够长地不复读。", with_edge=False)
    ci.extra_attrs["basis"] = None
    g = cc._debug_graph_for(ci)
    assert isinstance(g, dict)
    assert all(n["role"] == "hot" for n in g["nodes"])
    assert cc._express(ci) is True
    assert ch.sent[-1].refs.get("graph") == g


def test_internal_traces_excluded_from_content_views():
    """内部痕迹（思考/反思/行动记录…）不再占"这次话用的图谱/心里素材"
    热位——10-21 实锤：act=2.35 的 10-14 旧思考常驻气泡与 prompt。
    状态镜像不在此列（保留带注记的状态行）。"""
    kg, cc, ci, ch = _mk("全新的句子，与旧想法无关。")
    kg.add_node(Node(id="思考_999", weight=0.5, label="declarative-episodic",
                     graph_space="cognitive", activation=2.35,
                     extra_attrs={"type": "thought", "content": "旧独白残留"}))
    kg.add_node(Node(id="行动_888", weight=0.5, label="declarative-episodic",
                     graph_space="episodic", activation=1.9,
                     extra_attrs={"type": "action_outcome"}))
    kg.add_node(Node(id="Minecraft会话", weight=0.5,
                     label="declarative-semantic", graph_space="self",
                     activation=1.2,
                     extra_attrs={"type": "mc_session",
                                  "canon": "cognitive_state",
                                  "state": "disconnected"}))
    ids = {n["id"] for n in cc._debug_graph_for(ci)["nodes"]}
    assert "思考_999" not in ids and "行动_888" not in ids
    assert "Minecraft会话" in ids      # 镜像保留（诚实注记的状态行）
    from continuous_cognition import render_cognitive_state
    s = render_cognitive_state(kg, ci=ci)
    seg = s.split("我此刻心里有什么")[1].split("我正在想的事")[0]
    assert "思考_999" not in seg and "行动_888" not in seg
    assert "Minecraft会话" in seg


def test_proactive_output_scrubs_mechanism_names():
    """输出侧清洗（15:22 气泡"说到 CENetwork"实锤）：模型从语料先验自带
    机制名时，投递文本仍不得出现原始名——输入替换表防不住的方向，出口补。"""
    kg, cc, ci, ch = _mk("说到 CENetwork 与 SocialDrive，这次是一句全新的话。")
    assert cc._express(ci) is True
    t = ch.sent[-1].text
    assert "CENetwork" not in t and "SocialDrive" not in t
