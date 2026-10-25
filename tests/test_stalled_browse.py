# -*- coding: utf-8 -*-
"""设计2：研究撞墙 → browse 获得环境顺风（beat 真实选择路径）。
零网络零 LLM：ACTIVITIES 换成确定性假表，只验证选择数学与硬闸。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "FAS-Cognitive"))
import logging                                    # noqa: E402
logging.disable(logging.WARNING)

import activities as AC                            # noqa: E402
import pytest                                      # noqa: E402


class _KG:
    def get_node(self, nid):
        return None


def mk_ctx():
    td = tempfile.mkdtemp(prefix="stalled_browse_")
    AC._STATE_PATH_OVERRIDE = os.path.join(td, "state.json")
    os.environ["FAS_LIVING_DATA_DIR"] = td
    ctx = {"config": {"activity_music_library": "",
                      "living_loop_enabled": True,
                      "living_loop_daily_web_budget": 40,
                      "living_min_reeval_gap_s": 90,
                      "living_loop_max_activities_open": 1,
                      "activity_forum_feeds": True,
                      "living_loop_max_web_per_activity": 6},
           "kg": _KG(), "engine": None, "curiosity": None,
           "drive": None, "busy": lambda: False, "has_gaps": False,
           "save_fn": lambda: None, "search_fn": None}
    AC._WAKE.clear()
    with AC._events_lock:
        AC._recent_events.clear()
    AC._last_reeval_ts[0] = 0.0
    return ctx


@pytest.fixture()
def fake_table():
    orig = list(AC.ACTIVITIES)
    yield AC.ACTIVITIES
    AC.ACTIVITIES[:] = orig


def _rows(table, pairs):
    table[:] = [
        (n, (lambda ok: (lambda ctx: (ok, "")))(a > 0),
         (lambda s: (lambda ctx, st: s))(a),
         (lambda nm: (lambda ctx, st: {"done": True, "activity": nm,
                                       "next": "continue"}))(n))
        for (n, a) in pairs]


def _fire(kind, age_s=0.0):
    with AC._events_lock:
        AC._recent_events.append((kind, time.time() - age_s))


def test_no_event_research_wins(fake_table):
    ctx = mk_ctx()
    _rows(fake_table, [("research", 0.60), ("browse", 0.50)])
    assert AC.beat(ctx)["activity"] == "research"


def test_stalled_flips_choice_to_browse(fake_table):
    ctx = mk_ctx()
    _rows(fake_table, [("research", 0.60), ("browse", 0.50)])
    _fire("research_stalled")           # 0.50×1.25=0.625 > 0.60
    assert AC.beat(ctx)["activity"] == "browse"


def test_new_info_still_works(fake_table):
    ctx = mk_ctx()
    _rows(fake_table, [("research", 0.60), ("browse", 0.50)])
    _fire("new_info")
    assert AC.beat(ctx)["activity"] == "browse"


def test_boost_expires(fake_table):
    ctx = mk_ctx()
    _rows(fake_table, [("research", 0.60), ("browse", 0.50)])
    _fire("research_stalled", age_s=3600.0)     # 远超 15min 窗口
    assert AC.beat(ctx)["activity"] == "research"


def test_min_gap_hard_gate_survives_boost(fake_table):
    """顺风不穿透硬约束：刚逛过（MIN_GAP 内）事件再吵也不选 browse。"""
    ctx = mk_ctx()
    _rows(fake_table, [("research", 0.60), ("browse", 0.50)])
    st = {"browse": {"last_ts": time.time() - 60.0}}
    AC._save_state(st)
    _fire("research_stalled")
    assert AC.beat(ctx)["activity"] == "research"


def test_zero_desire_not_inflated(fake_table):
    """raw=0 的 browse 不被加成凭空抬起（avail 门+raw>0 双保险）。"""
    ctx = mk_ctx()
    _rows(fake_table, [("research", 0.60), ("browse", 0.0)])
    _fire("research_stalled")
    assert AC.beat(ctx)["activity"] == "research"


# ── browse 扫兴折扣时间衰减（修"一次扫兴永久焊死出门通道"）──────────
def _bctx():
    return {"config": {"activity_forum_feeds": True},
            "curiosity": None, "engine": None}


def test_fresh_stall_keeps_browse_low():
    """刚扫兴（ts=now）→ browse 欲望仍被压到 ~0.1。"""
    st = {"browse": {"novelty_discount": 0.25,
                     "novelty_discount_ts": time.time()}}
    assert AC._browse_appeal(_bctx(), st) == pytest.approx(0.42 * 0.25, abs=1e-3)


def test_old_stall_self_heals_to_full():
    """扫兴已是 6h+ 旧事 → 折扣回到基线，出门重新拿回入场券。"""
    st = {"browse": {"novelty_discount": 0.25,
                     "novelty_discount_ts": time.time() - 8 * 3600}}
    assert AC._browse_appeal(_bctx(), st) == pytest.approx(0.42, abs=1e-3)


def test_legacy_state_recovers_via_last_ts():
    """无 novelty_discount_ts 的旧 state：回退用 last_ts 作锚。"""
    st = {"browse": {"novelty_discount": 0.25,
                     "last_ts": time.time() - 22 * 3600}}   # 22h 前逛过
    assert AC._browse_appeal(_bctx(), st) == pytest.approx(0.42, abs=1e-3)


def test_mid_age_partial_recovery():
    """3h（半程）→ 折扣从 0.25 回升约一半向基线靠拢。"""
    st = {"browse": {"novelty_discount": 0.25,
                     "novelty_discount_ts": time.time() - 3 * 3600}}
    v = AC._browse_appeal(_bctx(), st)
    assert 0.42 * 0.25 < v < 0.42 * 0.85
