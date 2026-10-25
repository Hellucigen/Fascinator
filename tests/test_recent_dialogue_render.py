# -*- coding: utf-8 -*-
"""事项A：近期对话渲染必须带上她自己的被动答话（L1/L2 共用纯函数）。
旧缺口：常规轮每行只渲染 user_input——她的答话文本从不进她自己的上下文，
上一轮"我刚说了什么"只能从用户的半句反猜。"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))

from nlp_processor import render_recent_dialogue


def test_qa_pair_renders_both_sides():
    out = render_recent_dialogue(
        [{"user_input": "多巴胺是奖励预测误差吗",
          "system_response": "对，更准确说是预期被打破那一刻的信号。"}],
        limit=6, max_chars=80)
    assert out == ("用户：多巴胺是奖励预测误差吗\n"
                   "FAS（我刚答的）：对，更准确说是预期被打破那一刻的信号。")


def test_proactive_line_not_double_injected():
    """主动行的行体本来就是她的文本——不得再叠一条答话行（任务书明令
    防止主动表达重复注入）。"""
    out = render_recent_dialogue(
        [{"user_input": "(主动)", "system_response": "我刚才逛到一个有意思的东西",
          "proactive": True}], limit=6, max_chars=80)
    assert out == "FAS（我主动说的）：我刚才逛到一个有意思的东西"
    assert "我刚答的" not in out


def test_legacy_placeholder_rows_keep_shape():
    """"(FAS…"内部占位行维持旧单行形态（用户视角看是 FAS 的独白）。"""
    out = render_recent_dialogue(
        [{"user_input": "(FAS 主动表达）", "system_response": "旧格式回答"}],
        limit=6, max_chars=80)
    assert out == "FAS：(FAS 主动表达）"


def test_answerless_turn_renders_single_user_line():
    out = render_recent_dialogue(
        [{"user_input": "在吗", "system_response": None}], limit=6,
        max_chars=80)
    assert out == "用户：在吗"


def test_both_channels_share_one_renderer():
    """L1/L2 调用点不得再各自内嵌角色判断（回归钉：删掉 _who/_who2）。"""
    src = open(os.path.join(_ROOT, "nlp_processor.py"),
               encoding="utf-8").read()
    assert "def _who(x)" not in src and "def _who2(x)" not in src
    assert src.count("render_recent_dialogue(") >= 3   # 定义 + 两处调用


def test_truncation_and_limit():
    entries = [{"user_input": "问" * 120, "system_response": "答" * 120}
               for _ in range(9)]
    out = render_recent_dialogue(entries, limit=3, max_chars=60)
    lines = out.split("\n")
    assert len(lines) == 6                    # 3 轮 ×（问+答）
    assert all(len(l) <= 60 + len("FAS（我刚答的）：") for l in lines)


# ── 时间归属（2026-10-24 取证修复：1 小时前的回答曾被渲染成"我刚答的"）──
import datetime as _dt                                    # noqa: E402
from nlp_processor import _rel_time                       # noqa: E402


def _ago(**kw):
    return (_dt.datetime.now() - _dt.timedelta(**kw)).isoformat(
        timespec="seconds")


def test_fresh_answer_marked_recent():
    out = render_recent_dialogue(
        [{"time": _ago(seconds=10), "user_input": "在吗",
          "system_response": "在的"}], limit=6, max_chars=80)
    assert out == ("用户（刚刚说）：在吗\n"
                   "FAS（刚刚答的）：在的")


def test_one_hour_old_answer_not_rendered_as_just_now():
    out = render_recent_dialogue(
        [{"time": _ago(hours=1, minutes=5), "user_input": "你最近没上网转转吗",
          "system_response": "刚才帮你搜了一下"}], limit=6, max_chars=80)
    assert "约1小时前答的" in out
    assert "我刚答的" not in out
    assert "刚刚" not in out


def test_day_old_entry_shows_absolute_time():
    out = render_recent_dialogue(
        [{"time": _ago(days=2), "user_input": "早", "system_response": "早"}],
        limit=6, max_chars=80)
    assert "说）：" in out and "-" in out        # 绝对时间 MM-DD HH:MM
    assert "刚刚" not in out


def test_missing_or_invalid_time_keeps_legacy_label_no_fabrication():
    for bad in (None, "", "not-a-time"):
        out = render_recent_dialogue(
            [{"time": bad, "user_input": "在吗", "system_response": "嗯"}],
            limit=6, max_chars=80)
        assert out == ("用户：在吗\nFAS（我刚答的）：嗯"), (bad, out)


def test_rel_time_boundaries():
    now = _dt.datetime(2026, 10, 24, 12, 0, 0)

    def _fixed_ago(**kw):
        return (now - _dt.timedelta(**kw)).isoformat(timespec="seconds")

    assert _rel_time("", now=now) is None            # 缺失不编造
    assert _rel_time("garbage", now=now) is None
    assert _rel_time(_fixed_ago(seconds=30), now=now) == "刚刚"
    assert _rel_time(_fixed_ago(minutes=5), now=now) == "5分钟前"
    assert _rel_time(_fixed_ago(hours=3), now=now) == "约3小时前"
    assert _rel_time(_fixed_ago(days=2), now=now).startswith("10-22 ")


def test_attribution_not_swapped_with_time():
    """带时间标注后，用户行与 FAS 行的归属仍不得混淆。"""
    out = render_recent_dialogue(
        [{"time": _ago(seconds=30), "user_input": "帮我查天气",
          "system_response": "今天晴"}], limit=6, max_chars=80)
    assert out.startswith("用户（刚刚说）：帮我查天气")
    assert "\nFAS（刚刚答的）：今天晴" in out


if __name__ == "__main__":
    fails = 0
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"近期对话渲染：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
