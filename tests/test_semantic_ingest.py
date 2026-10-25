# -*- coding: utf-8 -*-
"""摄取语义边界（任务 §二.1/§三.1）：用户提问 ≠ 用户断言了问题中的事实。

旧断点：主对话路由的记忆抽取闸门里 `or memory_type in (episodic, semantic)`
这一 OR 分支实际架空了 _NON_TEACHING_DAS 名单——疑问句解析也带
memory_type（模板示例甚至教 question→semantic），于是"阿司匹林是什么药"
这类问句照样走 MEMORY_EXTRACT，把问的对象当断言知识写进图谱。
决策逻辑已收进 nlp_processor.should_extract_memory 纯函数，本测试走真实函数。
"""
import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))

from nlp_processor import should_extract_memory


def test_pure_semantic_question_not_extracted():
    # 模板示例3 的真实解析产物：question + semantic → 不再跑知识抽取
    parsed = {"dialogue_act": "question", "memory_type": "semantic",
              "illocutionary_act": "directive"}
    assert should_extract_memory(parsed) is False


def test_curiosity_expression_semantic_also_blocked():
    assert should_extract_memory(
        {"dialogue_act": "curiosity_expression", "memory_type": "semantic"}
    ) is False


def test_question_with_self_disclosure_still_extracted():
    # "我膝盖疼了两周了，怎么办？"→ episodic：抽取的是自述部分
    assert should_extract_memory(
        {"dialogue_act": "question", "memory_type": "episodic"}
    ) is True


def test_assertive_sharing_extracted():
    assert should_extract_memory(
        {"dialogue_act": "sharing", "memory_type": "episodic"}
    ) is True


def test_opinion_episodic_keeps_legacy_behavior():
    # 旧代码里非教学 da + episodic/semantic 经 OR 分支放行——保持不变
    assert should_extract_memory(
        {"dialogue_act": "opinion", "memory_type": "semantic"}
    ) is True


def test_no_dialogue_act_falls_back_to_memory_type():
    assert should_extract_memory({"memory_type": "semantic"}) is True
    assert should_extract_memory({}) is False


def test_narrative_skip_flag():
    assert should_extract_memory(
        {"dialogue_act": "sharing", "memory_type": "episodic"},
        skip_regular_extract=True) is False


def test_request_semantic_still_extracted_by_legacy_or_branch():
    # request 不在本次降级名单（用户在请求里确有可入库的自我意图/情境），
    # 行为与旧闸门一致：
    assert should_extract_memory(
        {"dialogue_act": "request", "memory_type": "episodic"}
    ) is True


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
    print(f"语义摄取闸门：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
