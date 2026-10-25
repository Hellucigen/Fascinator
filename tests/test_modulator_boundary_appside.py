# -*- coding: utf-8 -*-
"""调制禁入的陪伴侧验证（2026-10-19）：假设生成前端、证据消费接线、
渲染热扫描排除、_life_events 台账并流。内存图+临时目录，不触生产。"""
import json
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))
import logging                                   # noqa: E402
logging.disable(logging.CRITICAL)

from graph_model import KnowledgeGraph, Node, Edge   # noqa: E402
import activities                                  # noqa: E402


def _kg():
    kg = KnowledgeGraph()
    def n(i, act, ea=None, label="declarative-semantic"):
        kg.add_node(Node(id=i, weight=0.5, label=label,
                         graph_space="semantic", activation=act,
                         extra_attrs=ea or {}))
    n("SocialDrive", 2.6, {"type": "drive"})
    n("Minecraft会话", 2.5, {"type": "mc_session",
                             "canon": "cognitive_state",
                             "state": "disconnected"})
    n("概念甲", 1.4); n("概念乙", 1.3)
    n("共同证据", 1.0)
    kg.add_edge(Edge(src="概念甲", dst="共同证据", relation="支撑", weight=0.5))
    kg.add_edge(Edge(src="概念乙", dst="共同证据", relation="支撑", weight=0.5))
    # 仅有调制共享源的坏对：甲—相关—SocialDrive 与 乙—相关—SocialDrive
    kg.add_edge(Edge(src="概念甲", dst="SocialDrive", relation="相关", weight=0.4))
    kg.add_edge(Edge(src="概念乙", dst="SocialDrive", relation="相关", weight=0.4))
    return kg


def test_emerge_front_end_excludes_modulators():
    kg = _kg()
    activities._emerge_hypotheses({"kg": kg})
    hyps = [n for n in kg.nodes.values()
            if (n.extra_attrs or {}).get("type") == "hypothesis"]
    assert hyps, "正常语义对应当产假设（前端过滤不误伤）"
    for h in hyps:
        pair = (h.extra_attrs or {}).get("pair") or []
        assert "SocialDrive" not in pair and "Minecraft会话" not in pair
    # 假设腿边必须带标记
    for e in kg.edges:
        hid = str(e.dst)
        if any(h.id == hid for h in hyps):
            assert (e.extra_attrs or {}).get("hypothesis_leg") is True


def test_semantic_anchor_rejects_modulators():
    kg = _kg()
    assert activities._semantic_anchor_ok(kg, "共同证据")
    assert not activities._semantic_anchor_ok(kg, "SocialDrive")
    assert not activities._semantic_anchor_ok(kg, "Minecraft会话")


def test_consume_evidence_grants_credit():
    td = os.path.abspath(os.path.join(_ROOT, "data"))   # 只读语义：本测试
    #  不写它，改用临时目录注入
    tmp = os.path.join(os.path.dirname(__file__), "_tmp_ledger")
    os.makedirs(tmp, exist_ok=True)
    ledger = {"activities": [{"id": "life_t1", "topic": "搞清楚「假设：X」",
                              "concept": "假设：X", "state": "paused",
                              "updated": time.time(), "created": time.time(),
                              "consumed_evidence": [], "methods_tried": []}],
              "experiences": [], "share_candidates": [], "daily_web_calls": {}}
    with open(os.path.join(tmp, "living_ledger.json"), "w",
              encoding="utf-8") as f:
        json.dump(ledger, f)
    old = os.environ.get("FAS_LIVING_DATA_DIR")
    os.environ["FAS_LIVING_DATA_DIR"] = tmp
    try:
        class Eng:
            _hypo_ev_credit = 0

            def note_hypothesis_evidence(self, credits=40):
                self._hypo_ev_credit += credits
        eng = Eng()
        activities._consume_evidence(
            {"engine": eng}, {"opened": "life_t1"},
            [("假设：X", 0.4, "paused_rekindle", ["新证据节点1"])])
        assert eng._hypo_ev_credit > 0        # 消费=指认=发信用
        eng2 = Eng()
        activities._consume_evidence({"engine": eng2}, None, [])
        assert eng2._hypo_ev_credit == 0      # 未消费不发
    finally:
        if old is None:
            os.environ.pop("FAS_LIVING_DATA_DIR", None)
        else:
            os.environ["FAS_LIVING_DATA_DIR"] = old
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_life_events_merges_ledger_titles():
    from continuous_cognition import ContinuousCognition
    tmp = os.path.join(os.path.dirname(__file__), "_tmp_ledger2")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "living_ledger.json"), "w",
              encoding="utf-8") as f:
        json.dump({"activities": [{"id": "a1",
                                   "topic": "在B站逛到「一锅开水进肉馅」",
                                   "state": "completed",
                                   "updated": time.time() - 1800,
                                   "created": time.time() - 1800}],
                   "experiences": [], "share_candidates": [],
                   "daily_web_calls": {}}, f)
    try:
        cc = ContinuousCognition.__new__(ContinuousCognition)
        cc.timeline = None                    # 时间轴缺位也要并台账
        cc.config = {}
        cc.kg = KnowledgeGraph()
        cc._SELF_ACTORS = ("self", "haru")
        cc.ledger_path = os.path.join(tmp, "living_ledger.json")
        lines = cc._life_events()
        assert lines and any("台账" in l and "一锅开水" in l for l in lines)
        cc.ledger_path = None                 # 未注入=不并（隔离保证）
        assert cc._life_events() is None
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_renderer_hot_excludes_modulators():
    from continuous_cognition import render_cognitive_state
    kg = _kg()
    kg.add_node(Node(id="高亮驱动", activation=0.0))   # 占位无害
    kg.get_node("SocialDrive").activation = 3.0
    out = render_cognitive_state(kg, ci=None)
    assert "SocialDrive" not in out
    assert "Minecraft桥接状态" in out              # 状态镜像保留注记行
    assert "概念甲" in out


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
    print(f"调制边界(应用侧)：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
