# -*- coding: utf-8 -*-
"""主动表达落地（2026-10-16 规范）：原始事实层与主体归属。
真实故障钉：①"看你又在 STS2 里反复败北"——她自己的战绩被讲成用户经历
（写入层 actor='haru' 与全仓 'self' 不同源 + 上下文无原始记录）；
② 把用户"发烧"写成她的身体感受（图谱概念节点无反猜主体）；
③ CuriosityDrive/DMNetwork 机制名念给用户。零 LLM，纯离线。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node               # noqa: E402
from continuous_cognition import (ContinuousCognition,     # noqa: E402
                                  render_cognitive_state, ST_READY)
import pytest


class StubEngine:
    _running = False
    def get_topk(self, k=15): return [], []
    def decay_step(self): pass
    def diffuse_step(self): pass
    def mark_active(self, ids): pass
    def register_activation_source(self, ids, source_type="external_input"): pass
    def clear_anchors(self): pass


class StubNLP:
    def system_prompt(self, task): return "SYS"


class FakeTimeline:
    def __init__(self, events): self._e = events
    def recent(self, n=30, event_type=None, actor=None, since=None):
        return self._e[:n]


class FakeChatLog:
    def __init__(self, entries): self._e = entries
    def recent(self, n=50): return self._e[-n:]


def mk_cc(timeline=None, chat_log=None):
    cfg = {"continuous_cognition": {}}
    kg = KnowledgeGraph()
    cc = ContinuousCognition(kg, StubEngine(), StubNLP(), None, cfg,
                             chat_log=chat_log)
    if timeline is not None:
        cc.timeline = timeline
    return kg, cc


RUN_SELF = {"event_type": "ACTION", "actor": "self", "subject": "sts2_run",
            "ts_str": "14:23", "content": {"result": "defeat", "floor": 13,
                                           "self_booted": True}}
RUN_LEGACY_HARU = dict(RUN_SELF, actor="haru")   # 历史条目兼容
SAID = {"event_type": "ACTION", "actor": "self", "subject": "communicate",
        "ts_str": "19:57", "content": {"params": {"text": "层15。"}}}
USER_UTT = {"event_type": "OBSERVATION", "actor": "user",
            "subject": "utterance", "ts_str": "19:34",
            "content": {"text": "今天发烧了"}}


def test_life_events_actor_attribution():
    _, cc = mk_cc(timeline=FakeTimeline([RUN_SELF, SAID, USER_UTT]))
    lines = cc._life_events()
    assert lines and lines[0].startswith("- 14:23 我玩了杀戮尖塔2")
    assert "输了，打到第 13 层" in lines[0]
    assert "我自己决定开的" in lines[0]          # self_booted 语义在
    assert len(lines) == 1                       # say/communicate 跳过

def test_legacy_haru_actor_maps_to_self():
    _, cc = mk_cc(timeline=FakeTimeline([RUN_LEGACY_HARU]))
    assert "我玩了杀戮尖塔2" in cc._life_events()[0]

def test_raw_dialog_keeps_speaker_and_words():
    log = FakeChatLog([
        {"time": "2026-10-16T19:34:24", "user_input": "今天发烧了，身体好不舒服",
         "system_response": "听到你发烧了真让人担心"},
        {"time": "2026-10-16T19:35:29", "user_input": "(主动)",
         "system_response": "话到嘴边…", "proactive": True}])
    _, cc = mk_cc(chat_log=log)
    lines = cc._raw_dialog()
    assert any("用户说：今天发烧了" in l for l in lines)
    assert any("我答：" in l for l in lines)
    # 10-21 契约变更：主动话在 raw 窗只留大意占位（全文由防复述专段负责），
    # 但说话人标记必须在，且不得再把 90 字独白全文带进窗（自我回灌实锤）。
    _pr = [l for l in lines if "我主动" in l]
    assert _pr, lines
    assert not any("我主动说：" in l and len(l) > 60 for l in _pr)
    assert not any(l.startswith("- 19:34 用户说：(主动)") for l in lines)

def test_render_facts_layer_first():
    _, cc = mk_cc(timeline=FakeTimeline([RUN_SELF]), chat_log=FakeChatLog(
        [{"time": "2026-10-16T19:34:24", "user_input": "今天发烧了"}]))
    s = render_cognitive_state(cc.kg, ci=None,
                               raw_dialog=cc._raw_dialog(),
                               life_events=cc._life_events())
    assert s.index("最近真实发生过的事") < s.index("我此刻心里有什么")
    assert "19:34 用户说：今天发烧了" in s

def test_proactive_user_prompt_has_no_mechanics_labels():
    _, cc = mk_cc()
    ci = Node(id="CI_t", weight=0.5, graph_space="self", label="intention",
              extra_attrs={"type": "communication_intention",
                           "status": ST_READY, "reply_goal": "follow_up",
                           "activation": 0.7, "dialogue_act": "sharing",
                           "illocutionary_act": "assertive", "basis": []})
    u = cc.build_proactive_user(ci, "CTX")
    assert "激活" not in u and "言外行为" not in u and "对话行为" not in u
    assert "sharing" not in u and "assertive" not in u
    assert "我想接着之前聊的事再说两句" in u      # goal 自然语言化
    assert "NO_SPEAK" in u


def test_mechanism_raw_names_never_reach_the_model():
    """2026-10-17：图谱 id 与激素英文键在 prompt 出口换成自然语言——
    模型没见过原始名，就没有"念给用户"的可能（18:34/19:35 泄漏实锤）。"""
    from continuous_cognition import redact_internal_state_names as red
    s = ("- CuriosityDrive〔概念〕 激活2.9\n"
         "- CENetwork -关联-> SocialDrive（权重 0.8）\n"
         " 化学背景：cortisol=0.33、dopamine=0.5。drive.SocialDrive 0.5\n")
    out = red(s)
    for raw in ("CuriosityDrive", "CENetwork", "SocialDrive",
                "cortisol", "dopamine", "drive."):
        assert raw not in out, raw
    assert "好奇" in out and "专注执行的状态" in out and "对联结的渴望" in out
    assert "皮质醇=0.33" in out                  # 读数保留，只换名
    # 节点与边引用同词替换，指称一致性不破
    assert out.count("对联结的渴望") == 2
