# -*- coding: utf-8 -*-
"""认知状态切片 → 被动回复（2026-10-16）：被问"在想什么/在干嘛"时，
回复上下文里必须有念头内容本身，而不是只有数值读数。零 LLM：只测
内容生成与传递，不测措辞。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node          # noqa: E402
from continuous_cognition import (render_cognitive_state,  # noqa: E402
                                  ST_READY, ST_FORMING)
from cognitive_context import (build_cognitive_context,     # noqa: E402
                               compile_for_language)
import pytest


def mk_kg():
    kg = KnowledgeGraph()
    t = Node(id="思考_100", weight=0.4, graph_space="cognitive",
             label="declarative-episodic",
             extra_attrs={"type": "thought",
                          "content": "在想中午算不算白天的一部分",
                          "created": "2026-10-16 14:54:56"})
    t.activation = 0.05                     # 衰减到热线以下也必须在场
    kg.add_node(t)
    ci = Node(id="CI_1", weight=0.5, graph_space="self", label="intention",
              extra_attrs={"type": "communication_intention",
                           "status": ST_READY, "kind": "communication",
                           "activation": 0.42, "basis": ["Minecraft会话"],
                           "born_pulse": -99})
    kg.add_node(ci)
    hot = Node(id="焦点X", weight=0.6, graph_space="semantic",
               label="declarative-semantic",
               extra_attrs={"text": "关于时间概念的观察"})
    hot.activation = 0.80
    kg.add_node(hot)
    return kg


def test_slice_carries_thought_content_and_pending():
    s = render_cognitive_state(mk_kg())
    assert "在想中午算不算白天的一部分" in s      # content 字段直通
    assert "想开口的冲动" in s                    # 酝酿中的沟通意图（措辞去自白化 2026-10-17）
    assert "关于时间概念的观察" in s              # text 字段直通
    assert "别说第二遍" not in s                  # 被动通道不复述抑制


def test_slice_reaches_both_reply_paths():
    s = render_cognitive_state(mk_kg())
    ctx = build_cognitive_context(text="你在干嘛", parsed={},
                                  cognitive_state=s)
    l2 = compile_for_language(ctx, path="L2")
    assert l2.get("cognitive_state") == s          # 原样抵达语言层
    l1 = compile_for_language(ctx, path="L1")
    # 2026-10-16 修订：L1 短回应也是用户看到的第一人称回应，同样必须在场
    assert l1.get("cognitive_state") == s


def test_absent_slice_is_clean():
    ctx = build_cognitive_context(text="hi", parsed={})
    assert "cognitive_state" not in ctx["state"]
    assert compile_for_language(ctx, path="L2").get("cognitive_state") == ""
