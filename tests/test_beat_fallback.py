# -*- coding: utf-8 -*-
"""beat() 分级尝试（2026-10-19 用户设计）：首选活动被环境挡住
（result=unavailable：user_playing/桥不通/预算…）→ 同拍让位次优，
而不是白站十分钟重播"想做→让路"。纯内存活动桩，presence 打桩。"""
import os
import sys
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))
import logging                                   # noqa: E402
logging.disable(logging.WARNING)

import activities                                # noqa: E402

REAL = list(activities.ACTIVITIES)


def _act(name, appeal, out):
    return (name, lambda ctx: (True, ""),
            lambda ctx, st: appeal,
            lambda ctx, st: dict(out))


def _run(monkeypatch_rows):
    tmp = os.path.join(tempfile.gettempdir(), "fb_state.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    activities.reset_state_for_test(tmp)
    activities.ACTIVITIES[:] = monkeypatch_rows
    activities._set_presence = lambda a: None
    try:
        return activities.beat({"config": {}, "busy": lambda: False,
                                "kg": None}, trigger="sweep")
    finally:
        activities.ACTIVITIES[:] = REAL
        activities.reset_state_for_test(None)


def test_blocked_falls_through_to_next():
    res = _run([
        _act("sts2", 0.9, {"done": True, "activity": "sts2",
                           "result": "unavailable", "why": "user_playing"}),
        _act("browse", 0.5, {"done": True, "activity": "browse"}),
    ])
    assert res.get("activity") == "browse", res
    assert res.get("appeal") == 0.5


def test_unblocked_top_runs_alone():
    calls = {"browse": 0}
    def browse_beat(ctx, st):
        calls["browse"] += 1
        return {"done": True, "activity": "browse"}
    rows = [_act("sts2", 0.9, {"done": True, "activity": "sts2"}),
            ("browse", lambda ctx: (True, ""), lambda ctx, st: 0.5,
             browse_beat)]
    res = _run(rows)
    assert res.get("activity") == "sts2"
    assert calls["browse"] == 0                      # 没挡就不落次优


def test_all_blocked_reports_first_and_next_sweep_can_move():
    res = _run([
        _act("sts2", 0.9, {"done": True, "activity": "sts2",
                           "result": "unavailable", "why": "bridge_down"}),
        _act("browse", 0.5, {"done": True, "activity": "browse",
                              "result": "unavailable",
                              "why": "budget"}),
    ])
    assert res.get("result") == "unavailable"
    assert res.get("activity") == "browse"          # 最后一个尝试的结果
    assert res.get("appeal") == 0.9                  # 让路台账仍记首选愿望


def test_failed_not_treated_as_blocked():
    """done=False（真失败/中止）≠环境挡路：不无限 fallthrough。"""
    res = _run([
        _act("sts2", 0.9, {"done": False, "why": "crashed"}),
        _act("browse", 0.5, {"done": True, "activity": "browse"}),
    ])
    assert res.get("done") is False


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
    print(f"分级尝试：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
