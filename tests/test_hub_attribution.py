# -*- coding: utf-8 -*-
"""枢纽误归属防再发（2026-10-19 三连事故修复钉）：
① 第三方文本（逛到的视频/读到的网页）的代词映射不得伪造"涉及→用户/Self"；
② 桥接状态镜像不再吃 hub 背景激活地板；
③ minecraft 会话节点不再被种 Self-[意图] 直连边。
纯内存图，无 LLM、无生产数据。"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))
import logging                                   # noqa: E402
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge   # noqa: E402
import browse_memory                                  # noqa: E402


class Eng:
    def mark_active(self, ids): pass
    def register_activation_source(self, ids, source_type="external_input"):
        pass
    def get_topk(self, k=15): return [], []


def _exp(kg, exp_id="表達体験_t"):
    kg.add_node(Node(id=exp_id, label="declarative-episodic",
                     graph_space="episodic",
                     extra_attrs={"type": "activity_experience",
                                  "text": "在B站逛到…"}))
    return exp_id


def _hub_in_edges(kg, hub):
    return [e for e in kg.edges if e.dst == hub or e.src == hub]


def test_browse_entities_never_touch_hub():
    """深度抽取器（代词映射"我→用户"）递来的枢纽名端点：拒建涉及边。"""
    kg = KnowledgeGraph()
    kg.add_node(Node(id="用户", weight=1.0, graph_space="semantic"))
    _exp(kg)
    out = browse_memory.consolidate_browse_memory(
        kg, Eng(), "表達体験_t", "https://b/1",
        "花费上万！真人版弹丸论破开庭", "评论区这么多人想看，那就继续做一些吧",
        page_ok=True,
        deep_extractor=lambda t, s: (
            [], ["用户", "Haru", "真人版弹丸论破开庭视频"]))
    assert kg.get_edge("表達体験_t", "用户", "涉及") is None
    assert kg.get_edge("表達体験_t", "Haru", "涉及") is None
    assert kg.get_edge("表達体験_t", "真人版弹丸论破开庭视频", "涉及") is not None
    assert any("枢纽" in x for x in out["skipped"]), out["skipped"]


def test_browse_facts_never_touch_hub():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="用户", weight=1.0, graph_space="semantic"))
    _exp(kg)
    out = browse_memory.consolidate_browse_memory(
        kg, Eng(), "表達体験_t", "https://b/2",
        "「弹丸论破」真人版上线", "「弹丸论破」喜欢真人演绎",
        page_ok=True)
    # 规则/深度两条抽取路径的端点都要过枢纽过滤：体验节点不得直连"用户"
    for e in kg.edges:
        if str(e.src).startswith("表達体験") and e.dst == "用户":
            raise AssertionError("体验节点直连用户：" + e.relation)
    assert out is not None


def test_reading_entity_filter_wired():
    """reading 通道的同纪律：静态核验（其管线构造需要会话状态，行为面
    由 browse 侧同一常量保证，这里钉引用存在与一致）。"""
    src = open(os.path.join(_ROOT, "FAS-Cognitive", "reading.py"),
               encoding="utf-8").read()
    assert "HUB_ENTITY_NAMES" in src
    from graph_schema import HUB_ENTITY_NAMES
    assert {"用户", "Self", "Haru", "Fascinator"} <= set(HUB_ENTITY_NAMES)


def test_session_no_longer_seeds_intent_edge():
    from minecraft.session import MinecraftSession
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self", weight=1.0, graph_space="self"))
    MinecraftSession(kg)
    assert kg.get_node("Minecraft会话") is not None
    assert kg.get_edge("Self", "Minecraft会话", "意图") is None
    assert not [e for e in kg.edges
                if "Minecraft会话" in (e.src, e.dst) and e.relation == "意图"]


def test_hub_floor_skips_state_mirrors():
    from self_graph import hub_floor_targets
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self", weight=1.0, graph_space="self"))
    kg.add_node(Node(id="北京大学", label="declarative-semantic",
                     graph_space="semantic"))            # 正常自我事实
    kg.add_node(Node(id="Minecraft会话", label="declarative-semantic",
                     graph_space="self",
                     extra_attrs={"type": "mc_session",
                                  "canon": "cognitive_state",
                                  "state": "disconnected"}))
    kg.add_node(Node(id="桥X", label="declarative-semantic",
                     graph_space="self",
                     extra_attrs={"type": "other_state",
                                  "canon": "cognitive_state"}))
    kg.add_edge(Edge(src="Self", dst="北京大学", relation="就读", weight=0.9))
    kg.add_edge(Edge(src="Self", dst="Minecraft会话", relation="意图", weight=0.5))
    kg.add_edge(Edge(src="Self", dst="桥X", relation="相关", weight=0.5))
    floors = hub_floor_targets(kg, {})
    assert "北京大学" in floors
    assert "Minecraft会话" not in floors      # type 名单挡住
    assert "桥X" not in floors                # canon 兜住未来同类镜像


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
    print(f"枢纽归属防护：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
