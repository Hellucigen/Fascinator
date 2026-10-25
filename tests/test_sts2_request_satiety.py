# -*- coding: utf-8 -*-
"""饱腹=念头被兑现消耗（2026-10-17 用户设计，替换 plays_today 计数器）。
语义：想玩是一个念头——兴趣水位；每满足一把按结果衰减（输的凉得快，
再乘负效价微调），跌破阈值念头自然停止；时间与新经历让水位回涨。
事故钉：旧公式把 21 局计数当饱腹乘在当面请求头上，0.11 输给 browse
0.42——"她答应再开一局却去逛了B站"。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "FAS-Cognitive"))
import logging                                  # noqa: E402
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node    # noqa: E402
import activities                               # noqa: E402
import curiosity_engine as ce                   # noqa: E402
import pytest                                   # noqa: E402

CFG = {"activity_sts2": True, "curiosity": {}}


def mk_world(level=1.0):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="杀戮尖塔", weight=0.5, graph_space="semantic",
                     extra_attrs={"type": "concept",
                                  "interest": {"level": level}}))
    return {"kg": kg, "config": CFG}


def test_fresh_request_beats_routine_even_after_many_plays():
    ctx = mk_world(level=0.3)                    # 念头已被消耗过
    st = {"sts2": {"request_ts": time.time(), "plays_today": 21,
                   "last_ts": time.time() - 3 * 3600}}
    assert activities._sts2_appeal(ctx, st) > 0.42   # 当面请求赢过浏览


def test_repeated_defeats_extinguish_the_thought():
    ctx = mk_world(level=1.0)
    st = {"sts2": {"request_ts": 0, "plays_today": 3,
                   "last_ts": time.time() - 3 * 3600}}
    for _ in range(3):                           # 三局皆墨：念头自然凉透
        ce.note_interest(ctx["kg"], "杀戮尖塔", "sated", CFG, mult=0.45)
    lvl = ce.get_interest(ctx["kg"], "杀戮尖塔")["level"]
    assert lvl < 0.1 and lvl > 0                 # 衰减有痕、不清零
    assert ce.get_interest(ctx["kg"], "杀戮尖塔")["acted_count"] == 3
    assert activities._sts2_appeal(ctx, st) < activities.THRESHOLD


def test_victory_sips_instead_of_slamming():
    ctx = mk_world(level=0.9)
    st = {"sts2": {"request_ts": 0, "plays_today": 1,
                   "last_ts": time.time() - 3 * 3600}}
    ce.note_interest(ctx["kg"], "杀戮尖塔", "sated", CFG, mult=0.78)
    lvl = ce.get_interest(ctx["kg"], "杀戮尖塔")["level"]
    assert lvl == pytest.approx(0.702, abs=1e-3)  # 赢一把只是小酌
    assert activities._sts2_appeal(ctx, st) > activities.THRESHOLD  # 还想玩


def test_never_played_keeps_probing_floor():
    kg = KnowledgeGraph()                        # 没有"杀戮尖塔"节点=没玩过
    ctx = {"kg": kg, "config": CFG}
    st = {"sts2": {"request_ts": 0, "plays_today": 0,
                   "last_ts": time.time() - 4 * 3600}}
    a = activities._sts2_appeal(ctx, st)
    assert a > 0.15, a                           # 试探入口保留（0.30 底）


def test_budget_exit_does_not_sate_the_thought():
    """局未终（预算尽离场）≠ 念头被兑现：2026-10-17 f15 实锤——离场被
    当 aborted×0.6 消耗，下一拍输给 research，半局永远晾在桌上。"""
    ctx = mk_world(level=1.0)
    st = {"sts2": {"request_ts": 0, "plays_today": 3,
                   "last_ts": time.time() - 4 * 3600}}
    res_budget = {"result": "aborted", "exit": "budget", "floor": 15,
                  "run_id": "R9", "self_booted": False,
                  "new_mechanics": [], "steps": 400}
    out = activities._sts2_settle(ctx, st, res_budget)
    assert out.get("settled")                       # 战报记（打到15层）
    lvl = ce.get_interest(ctx["kg"], "杀戮尖塔")
    assert lvl["level"] == pytest.approx(1.0)       # 但念头不降温
    assert lvl["acted_count"] == 0
    # 真打完才消耗：同一个局若败北，则必须消耗
    res_defeat = {"result": "defeat", "floor": 17, "run_id": "R9",
                  "self_booted": False, "new_mechanics": []}
    st2 = {"sts2": dict(st["sts2"], last_settled_run=None)}
    activities._sts2_settle(ctx, st2, res_defeat)
    assert ce.get_interest(ctx["kg"], "杀戮尖塔")["level"] < 0.5


def test_record_section_says_records_are_complete():
    from continuous_cognition import render_cognitive_state
    kg = KnowledgeGraph()
    kg.add_node(Node(id="x", weight=0.5, graph_space="cognitive"))
    s = render_cognitive_state(
        kg, life_events=["- 22:29 我玩了杀戮尖塔2：输了，打到第 8 层"])
    assert "没写在这里的事就没有发生" in s       # 已完成/承诺必须有据


class FakeTr:
    def __init__(self, alive=True):
        self.alive = alive; self.calls = []
    def health(self): return self.alive
    def state(self): return {"available_actions": ["save_and_quit", "choose_map_node"]}
    def action(self, b): self.calls.append(b); return {"ok": True}


def _mk_warm_kg(level):
    from graph_model import KnowledgeGraph, Node
    kg = KnowledgeGraph()
    kg.add_node(Node(id="杀戮尖塔", weight=0.5,
                     label="declarative-semantic"))
    kg.nodes["杀戮尖塔"].extra_attrs = {
        "type": "concept",
        "interest": {"level": level, "acted_count": 3}}
    return kg


def test_cold_thought_saves_and_quits_app():
    """不想打了→保存退出 + 关进程释放运存（2026-10-17 用户规则）。"""
    cfg = dict(CFG); cfg["pc_autonomy"] = {"level": "attended",
        "apps": {"sts2": {"window_title": "Slay the Spire 2"}}}
    ctx = {"kg": _mk_warm_kg(0.02), "config": cfg}
    tr = FakeTr(); killed = []
    st = {"sts2": {"request_ts": 0, "plays_today": 4,
                  "last_ts": time.time() - 5 * 3600}}
    ctx["sts2_transport"] = tr
    ctx["app_killer"] = lambda cmd: killed.append(cmd) or 0
    activities._sts2_put_down_if_unwanted(ctx, st)      # 第 1 拍：只计数
    assert tr.calls == [] and killed == []
    assert st["sts2"]["unwanted_streak"] == 1
    activities._sts2_put_down_if_unwanted(ctx, st)      # 第 2 拍：确认凉透
    assert {"action": "save_and_quit"} in tr.calls       # 局内先存档
    assert any("taskkill" in str(k) for k in killed)      # 再关进程释放运存
    assert st["sts2"]["last_quit_ts"] > 0
    killed.clear(); tr.calls.clear()
    activities._sts2_put_down_if_unwanted(ctx, st)
    assert tr.calls == [] and killed == []               # 冷却窗不轰击


def test_warm_thought_leaves_game_running():
    ctx = {"kg": _mk_warm_kg(0.9), "config": CFG}   # 念头还热
    tr = FakeTr()
    st = {"sts2": {"request_ts": 0, "plays_today": 2,
                  "last_ts": time.time() - 5 * 3600}}
    ctx["sts2_transport"] = tr
    activities._sts2_put_down_if_unwanted(ctx, st)
    assert tr.calls == []                            # 别碰


def test_fresh_request_survives_post_game_cooldown():
    """刚打完一局（fresh≈0.15）用户又说"继续打"：请求满值必须存活，
    不能被 冷却×水位 双重压没（17:30 实锤：答应了却没接上，f15 晾着）。"""
    ctx = mk_world(level=0.05)          # 水位被上一轮消耗后偏低
    st = {"sts2": {"request_ts": time.time(),        # 刚说的请求
                   "plays_today": 5,
                   "last_ts": time.time() - 40 * 60}}  # 40min 前刚打完
    a = activities._sts2_appeal(ctx, st)
    assert a > 0.53                       # 赢过 browse 常态 0.53


class FakeTrGameOver(FakeTr):
    def state(self):
        return {"screen": "GAME_OVER",
                "available_actions": ["continue_game_over"]}


def test_put_down_dismisses_game_over_result_screen():
    """打完停在结算屏且不想玩了：收掉结果页而非找 save_and_quit。"""
    ctx = {"kg": _mk_warm_kg(0.02), "config": CFG}
    tr = FakeTrGameOver()
    st = {"sts2": {"request_ts": 0, "plays_today": 6,
                  "last_ts": time.time() - 5 * 3600}}
    ctx["sts2_transport"] = tr
    activities._sts2_put_down_if_unwanted(ctx, st)      # 第 1 拍计数
    activities._sts2_put_down_if_unwanted(ctx, st)      # 第 2 拍执行
    assert {"action": "continue_game_over"} in tr.calls
    assert {"action": "save_and_quit"} not in tr.calls
    assert st["sts2"]["last_quit_ts"] > 0


# ── 收桌双拍确认 & 实例所有权（2026-10-18 规范修订）──────────
def _gcfg():
    return {"activity_sts2": True,
            "pc_autonomy": {"level": "attended", "steamapps_dir": "",
                            "apps": {"sts2": {
                                "window_title": "Slay the Spire 2"}}}}


def test_put_down_needs_two_beats():
    """一拍的欲望下探不触发退出；连续两拍凉透才收桌。"""
    ctx = {"kg": _mk_warm_kg(0.02), "config": _gcfg()}
    tr = FakeTr()
    killed = []
    ctx["sts2_transport"] = tr
    ctx["app_killer"] = lambda cmd: killed.append(cmd) or 0
    st = {"sts2": {"request_ts": 0, "plays_today": 4,
                   "last_ts": time.time() - 5 * 3600}}
    activities._sts2_put_down_if_unwanted(ctx, st)      # 第 1 拍
    assert killed == [] and tr.calls == []
    assert st["sts2"]["unwanted_streak"] == 1
    activities._sts2_put_down_if_unwanted(ctx, st)      # 第 2 拍 → 收
    assert {"action": "save_and_quit"} in tr.calls
    assert killed and st["sts2"]["unwanted_streak"] == 0


def test_put_down_aborts_on_desire_bounce():
    """两拍之间欲望回弹 → 计数清零，不收桌。"""
    kg = _mk_warm_kg(0.02)
    ctx = {"kg": kg, "config": _gcfg()}
    tr = FakeTr()
    ctx["sts2_transport"] = tr
    ctx["app_killer"] = lambda cmd: 0
    st = {"sts2": {"request_ts": 0, "plays_today": 4,
                   "last_ts": time.time() - 5 * 3600}}
    activities._sts2_put_down_if_unwanted(ctx, st)      # 凉第 1 拍
    assert st["sts2"]["unwanted_streak"] == 1
    kg.nodes["杀戮尖塔"].extra_attrs["interest"]["level"] = 0.95   # 回弹
    activities._sts2_put_down_if_unwanted(ctx, st)
    assert st["sts2"]["unwanted_streak"] == 0
    assert tr.calls == [] and "last_quit_ts" not in st["sts2"]


def test_yield_marks_user_ownership_and_blocks_retake():
    """让渡后所有权翻转：人在场时她不再接管；她自己开的局照常。"""
    import pc_autonomy
    orig = pc_autonomy.user_present
    orig_fg = pc_autonomy.foreground_title
    pc_autonomy.user_present = lambda cfg, idle_fn=None: True
    pc_autonomy.foreground_title = lambda: ""      # 隔离真实前台窗口
    try:
        class Alive:
            def health(self): return True
            def state(self):
                return {"screen": "MAIN_MENU", "available_actions": [],
                        "run": None}
        def _gate(st_s2):
            ctx = {"config": _gcfg(), "sts2_transport": Alive(),
                   "kg": _mk_warm_kg(0.9), "curiosity": None,
                   "engine": None}
            return activities.sts2_beat(ctx, {"sts2": dict(
                st_s2, request_ts=0, plays_today=4,
                last_ts=time.time() - 5 * 3600)})
        # 用户开的局（无她的启动戳）+ 人在场 + 无邀请 → 让位
        assert _gate({}).get("why") == "user_playing"
        # 她自己开的（启动戳更新）→ 可以后台接管
        r = _gate({"self_opened_ts": time.time() - 300})
        assert r.get("why") != "user_playing"
        # 之后发生让渡（用户上手）→ 所有权翻回用户，她不再抢
        r2 = _gate({"self_opened_ts": time.time() - 300,
                    "user_owns_ts": time.time() - 60})
        assert r2.get("why") == "user_playing"
        # 用户当面邀请（request 新鲜）→ 邀请即授权，恢复接管
        r3 = activities.sts2_beat(
            {"config": _gcfg(), "sts2_transport": Alive(),
             "kg": _mk_warm_kg(0.9), "curiosity": None, "engine": None},
            {"sts2": {"request_ts": time.time(), "plays_today": 4,
                      "last_ts": time.time() - 5 * 3600,
                      "self_opened_ts": 0, "user_owns_ts": time.time()}})
        assert r3.get("why") != "user_playing"
    finally:
        pc_autonomy.user_present = orig
        pc_autonomy.foreground_title = orig_fg


# ── 抢控事故补账（2026-10-18 晚：用户在玩，她六连拍进场代打）──────────

def test_bridge_down_while_window_running_is_not_ownership(monkeypatch):
    """用户刚开游戏、mod 桥还没就绪的间隙：她不得按启动键，更不得把
    这个实例登记成自己的（事故里 self_opened_ts 就是这么误盖的）。"""
    import pc_autonomy
    monkeypatch.setattr(pc_autonomy, "window_exists", lambda t: True)
    monkeypatch.setattr(pc_autonomy, "user_present",
                        lambda cfg, idle_fn=None: True)
    launches = []

    class Dead:
        def health(self): return False
        def state(self): return {}
        def action(self, b): return {"ok": False}

    ctx = {"config": _gcfg(), "sts2_transport": Dead(),
           "kg": _mk_warm_kg(0.9), "curiosity": None, "engine": None,
           "sts2_launcher": lambda c: (launches.append(1), True)[1]}
    st = {"sts2": {"request_ts": 0, "plays_today": 0,
                   "last_ts": time.time() - 5 * 3600}}
    r = activities.sts2_beat(ctx, st)
    assert r.get("why") == "bridge_down"
    assert not launches                       # 没启动
    assert "self_opened_ts" not in st["sts2"]  # 没盖所有权戳


def test_state_advanced_without_her_flips_ownership_and_defers(monkeypatch):
    """逐拍签名观察器：板子在她没动手时自己动了=有人在玩——即时过户，
    本拍让路；且**邀请豁免失效**（他邀请了你却还占着鼠标，不授权抢控）。"""
    import pc_autonomy
    monkeypatch.setattr(pc_autonomy, "user_present",
                        lambda cfg, idle_fn=None: True)
    monkeypatch.setattr(pc_autonomy, "foreground_title", lambda: "")

    class Adv:
        def health(self): return True
        def state(self):
            return {"screen": "MAP", "run": {"floor": 7},
                    "player": {"current_hp": 55}, "available_actions": []}

    st_s2 = {"request_ts": time.time(),        # 邀请新鲜也拦
             "plays_today": 0, "last_ts": time.time() - 5 * 3600,
             "self_opened_ts": time.time() - 60,
             "last_sig": "MAP|5|60"}
    ctx = {"config": _gcfg(), "sts2_transport": Adv(),
           "kg": _mk_warm_kg(0.9), "curiosity": None, "engine": None}
    r = activities.sts2_beat(ctx, {"sts2": st_s2})
    assert r.get("why") == "user_playing"
    assert st_s2["user_owns_ts"] >= time.time() - 5   # 事实过户
    assert st_s2["last_sig"] == "MAP|7|55"            # 基线重定


def test_foreground_player_blocks_even_her_owned_game(monkeypatch):
    """用户正在游戏窗口前操作：哪怕所有权戳显示是她的局，也不进场。"""
    import pc_autonomy
    monkeypatch.setattr(pc_autonomy, "user_present",
                        lambda cfg, idle_fn=None: True)
    monkeypatch.setattr(pc_autonomy, "foreground_title",
                        lambda: "Slay the Spire 2")

    class Same:
        def health(self): return True
        def state(self):
            return {"screen": "MAP", "run": {"floor": 7},
                    "player": {"current_hp": 55}, "available_actions": []}

    st_s2 = {"request_ts": 0, "plays_today": 0,
             "last_ts": time.time() - 5 * 3600,
             "self_opened_ts": time.time() - 60,
             "last_sig": "MAP|7|55"}          # 局面没动，单靠前台事实拦
    ctx = {"config": _gcfg(), "sts2_transport": Same(),
           "kg": _mk_warm_kg(0.9), "curiosity": None, "engine": None}
    r = activities.sts2_beat(ctx, {"sts2": st_s2})
    assert r.get("why") == "user_playing"


def test_hand_back_then_she_may_resume_when_user_steps_away(monkeypatch):
    """过户之后不是永久禁区：用户离场（前台非游戏窗口+签名稳定）时，
    她仍可恢复自己的生活——观察器只拦"正在发生"的抢控，不建死锁。"""
    import pc_autonomy
    monkeypatch.setattr(pc_autonomy, "user_present",
                        lambda cfg, idle_fn=None: False)   # 人已离开
    monkeypatch.setattr(pc_autonomy, "foreground_title",
                        lambda: "Code - Insiders")

    class Still:
        def health(self): return True
        def state(self):
            return {"screen": "MAIN_MENU", "run": None,
                    "player": {}, "available_actions": []}

    st_s2 = {"request_ts": 0, "plays_today": 0,
             "last_ts": time.time() - 5 * 3600,
             "self_opened_ts": time.time() - 3600,
             "user_owns_ts": time.time() - 120,
             "last_sig": "MAIN_MENU|None|None"}
    ctx = {"config": _gcfg(), "sts2_transport": Still(),
           "kg": _mk_warm_kg(0.9), "curiosity": None, "engine": None}
    r = activities.sts2_beat(ctx, {"sts2": st_s2})
    assert r.get("why") != "user_playing"
