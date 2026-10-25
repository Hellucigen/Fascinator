# -*- coding: utf-8 -*-
"""Prompt 语义约束的静态核验（辅助检查；行为核验见 test_semantic_ingest）。

钉住本轮修复的语义要点，并确认解析器依赖的 schema 面没有被改动破坏。"""
import sys
import os
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import prompt_templates as pt


def test_no_quantity_quota_in_concept_expand():
    assert "8~12" not in pt.CONCEPT_EXPAND
    assert "10~18" not in pt.CONCEPT_EXPAND
    assert "按实际把握输出" in pt.CONCEPT_EXPAND
    assert "宁可不写" in pt.CONCEPT_EXPAND


def test_identity_is_not_dogma():
    assert "万物皆图" not in pt.FAS_IDENTITY
    # 普通程序状态归程序——正是任务里"别把一切都塞进图"的原则
    assert "不需要也不应该被硬塞进图里" in pt.FAS_IDENTITY
    assert "LLM 是你的语言接口，不是你的大脑" in pt.FAS_IDENTITY


def test_nlp_parse_question_rule_and_example():
    assert "问句预设不是断言" in pt.NLP_PARSE
    # 示例3 不再教断言边
    m = re.search(r'【示例3.*?memory_type":"semantic"\}', pt.NLP_PARSE, re.S)
    assert m is not None and '"edges":[]' in m.group(0)


def test_memory_extract_modality_and_question_boundary():
    assert "当下意愿：" in pt.MEMORY_EXTRACT
    assert "一次性的" in pt.MEMORY_EXTRACT
    assert "问句预设不是断言" in pt.MEMORY_EXTRACT
    # 元对话指令规则（7）仍在
    assert "元对话指令" in pt.MEMORY_EXTRACT


def test_answer_generate_allows_short_forms():
    assert "不要强迫每段回复以问题收尾" in pt.ANSWER_GENERATE
    assert "不必覆盖全部焦点节点" in pt.ANSWER_GENERATE


def test_reflection_summary_no_forced_failure():
    assert "最大的失败" not in pt.REFLECTION_SUMMARY
    assert "没有根据的内容宁可不写" in pt.REFLECTION_SUMMARY


def test_json_schema_surface_unchanged():
    """解析器依赖的字段面不得被 prompt 编辑破坏。"""
    for name in ("nodes", "edges", "illocutionary_act", "dialogue_act",
                 "response_expectation", "suggested_reply_goals", "memory_type"):
        assert f'"{name}"' in pt.NLP_PARSE, name
    for name in ("assertion_type", "event", "nodes", "edges", "src", "dst",
                 "type", "weight", "reason"):
        assert f'"{name}"' in pt.MEMORY_EXTRACT, name
    for name in ("intentions", "speech_act", "nodes"):
        assert f'"{name}"' in pt.INTENTION_EXTRACT, name
    # NLP_PARSE 各示例仍是合法 JSON 行（防止编辑打穿引号/花括号）
    for m in re.finditer(r'输出: (\{.*\})', pt.NLP_PARSE):
        json.loads(m.group(1))
    # MEMORY_EXTRACT 正例 JSON 同样可解析（带省略号的示意行除外）
    for m in re.finditer(r'输出: (\{"assertion_type".*\})\s*$',
                        pt.MEMORY_EXTRACT, re.M):
        row = m.group(1)
        if "..." in row or "…" in row:
            continue
        json.loads(row)


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
    print(f"prompt 语义核验：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)


def test_evidence_time_rules_present_in_both_answer_paths():
    """时间与证据边界必须同时存在于 L2(ANSWER_GENERATE) 与 L1(ANSWER_SHORT)
    ——取证实锤：L1 短回应复诵 1 小时前的旧回答、凭 bilibili 页面存在
    推断"最近又上线"。两条路径共用 _EVIDENCE_TIME_RULES。"""
    for name, tpl in (("ANSWER_GENERATE", pt.ANSWER_GENERATE),
                      ("ANSWER_SHORT", pt.ANSWER_SHORT)):
        assert "【时间与证据边界】" in tpl, name
        assert "页面存在≠现在能看" in tpl, name
        assert "页面日期≠作品上线时间" in tpl, name
        assert "当前能看≠最近重新上线" in tpl, name
        assert "我之前回答过" in tpl and "我刚才回答过" in tpl, name
        assert "不得把以前的回答、搜索、思考说成本轮刚发生的事" in tpl, name
        assert "好像/听说" in tpl, name
