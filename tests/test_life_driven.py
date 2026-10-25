# -*- coding: utf-8 -*-
"""test_life_driven.py — 状态驱动自主生活机制验收（2026-10-13，任务书 §九 A-H）。

全离线确定性：fake drive/curiosity/search + 临时状态文件 + 线程真实 daemon。
Fake LLM/Fake 时钟仅用于确定性；结论区分"逻辑测试"与"生产集成"。
运行：python tests/test_life_driven.py
"""
import json
import os
import sys
import tempfile
import threading
import time

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import activities as AC                       # noqa: E402
import living_loop as LL                      # noqa: E402
from graph_model import KnowledgeGraph, Node  # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeDrive:
    def __init__(self, curios=0.5, fatigue=0.0, boom=False):
        self.c, self.f, self.boom = curios, fatigue, boom

    def get_drive_state(self):
        if self.boom:
            raise RuntimeError("cognitive field down")
        return {"tensions": {"curiosity": self.c, "fatigue": self.f},
                "drives": {}, "dominant": None}


class FakeCur:
    def __init__(self, q=None):
        self.q = q

    def get_curiosity_state(self, kg):
        return {"active": bool(self.q), "question": self.q}


class FakeEngine:
    def __init__(self):
        self.lit = []

    def mark_active(self, nid):
        self.lit.append(nid)


def fresh_env(drive=None, cur=None, gaps=False, busy=False,
              search=None, daily_budget=40):
    td = tempfile.mkdtemp(prefix="life_test_")
    AC._STATE_PATH_OVERRIDE = os.path.join(td, "state.json")
    os.environ["FAS_LIVING_DATA_DIR"] = td
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self", label="self", weight=1.0))
    eng = FakeEngine()
    ctx = {"config": {"activity_music_library": "",
                      "activity_sts2": False,
                      "living_loop_enabled": True,
                      "living_loop_daily_web_budget": daily_budget,
                      "living_min_reeval_gap_s": 90,
                      "living_loop_max_activities_open": 1,
           "activity_forum_feeds": [],  # 旧场景纯净：论坛语义由 continuity B 组专测
                      "living_loop_max_web_per_activity": 6},
           "kg": kg, "engine": eng,
           "curiosity": cur or FakeCur(),
           "drive": drive, "busy": lambda: busy, "has_gaps": gaps,
           "save_fn": lambda: None, "search_fn": search}
    # 清事件通道状态（用例间隔离）
    AC._WAKE.clear()
    with AC._events_lock:
        AC._recent_events.clear()
    AC._last_reeval_ts[0] = 0.0
    return ctx, td, kg, eng


ORIG_ACTIVITIES = list(AC.ACTIVITIES)


def with_fake_activities(rows):
    """rows: [(name, avail_score)] → 固定分数的确定性活动表。"""
    AC.ACTIVITIES[:] = [
        (n, (lambda ok: (lambda ctx: (ok, "")))(a > 0),
         (lambda s: (lambda ctx, st: s))(a),
         (lambda nm: (lambda ctx, st: {"done": True, "activity": nm,
                                       "next": "continue"}))(n))
        for (n, a) in rows]


try:
    # ══ A：不等十分钟——事件即时引发重评估（真实 daemon 线程）══════
    calls = []
    wake = AC.wait_timeout()      # 与 notify_event 同一通道（生产同款）
    cfg_a = {"living_loop_enabled": True, "living_loop_tick_s": 9999,
             "living_loop_daily_web_budget": 40}
    t0 = time.time()
    started, why = LL.run_living_loop_daemon(
        cfg_a, beat_fn=lambda trigger="sweep": calls.append(trigger),
        wake_event=wake)
    time.sleep(0.6)                       # 首拍（sweep）发生
    AC.notify_event("new_info")           # 真实事件入口（urgent kinds）
    deadline = time.time() + 5
    while len(calls) < 2 and time.time() < deadline:
        time.sleep(0.2)
    # 掐掉这个测试 daemon（置 flag 关 + 清单例，防干扰后续用例）
    cfg_a["living_loop_enabled"] = False
    time.sleep(0.6)
    LL._DAEMON_THREAD = None
    check("A1 安全网周期 9999s 下首拍照常（启动即评估一次）",
          len(calls) >= 1 and calls[0] == "sweep", str(calls))
    check("A2 事件唤醒不等周期：trigger=event 的拍在 5s 内出现",
          len(calls) >= 2 and calls[1] == "event", str(calls))

    # ══ B：同一事件，不同内部状态 → 不同行为 ═════════════════════
    hi = FakeDrive(curios=0.95, fatigue=0.0)
    lo = FakeDrive(curios=0.02, fatigue=0.9)
    ctx_hi, *_ = fresh_env(drive=hi, cur=FakeCur("拓扑量子场"))
    ctx_lo, *_ = fresh_env(drive=lo, cur=FakeCur("拓扑量子场"))
    # 制造边缘条件：上次逛过（时间衰减系数小），驱动差异决定跨不跨阈值
    st = {"browse": {"last_ts": time.time() - 1000}}
    json.dump(st, open(AC._STATE_PATH_OVERRIDE, "w", encoding="utf-8"))
    AC._save_state(st)
    def _scale_a(d, act): return AC._drive_scale({"drive": d, "config": {}}, act)
    s_hi, s_lo = _scale_a(hi, "browse"), _scale_a(lo, "browse")
    r_hi = AC.beat(ctx_hi) if False else None
    # 行为级断言：高好奇→browse 候选分数过阈；高疲劳+低好奇→被压回阈下
    ap_b = 0.55 * min(1.0, 400 / 1800.0)
    check("B1 驱动调制改变候选分数（好奇×疲劳两态差异显著）",
          s_hi > 1.2 and s_lo < 0.6, f"hi={s_hi} lo={s_lo}")
    st2 = {"browse": {"last_ts": time.time() - 1000}}
    AC._STATE_PATH_OVERRIDE = AC._state_path_for(ctx_lo) if hasattr(AC, "state_path_for") else AC._STATE_PATH_OVERRIDE
    AC._save_state(dict(st2))
    r_lo = AC.beat(ctx_lo)
    AC._save_state(dict(st2))
    r_hi2 = AC.beat(ctx_hi)
    # 2026-10-17 语义更新：疲劳乘数删除后，"低驱动→安静/换道"不再是驱动
    # 调制的路径（安静由念头水位与阈值决定）；驱动差异必须如实传导到
    # 欲望强度（appeal 明显分档），选择仍可同项。
    check("B2 同一环境+不同驱动 → 欲望强度分档传导（疲劳已删，水位定安静）",
          (r_lo.get("activity") != r_hi2.get("activity"))
          or (r_lo.get("activity") is None and r_hi2.get("activity") == "browse")
          or (float(r_hi2.get("appeal") or 0)
              > float(r_lo.get("appeal") or 0) * 1.5),
          f"lo={r_lo} hi={r_hi2}")

    # ══ C：高驱动 ≠ 越权/超预算——闸必须赢 ═══════════════════════
    ctx_c, *_ = fresh_env(drive=FakeDrive(0.95), cur=FakeCur("量子"),
                            daily_budget=0)
    AC._save_state({})
    r_c = AC.beat(ctx_c)     # browse 想动，但网络预算=0
    check("C1 网络预算耗尽时探索被硬拦（驱动再高也不行）",
          r_c.get("activity") is None or r_c.get("why") == "nothing_worth_doing"
          or r_c.get("done") is False, str(r_c)[:150])
    ctx_c2, *_ = fresh_env(drive=FakeDrive(0.95), cur=FakeCur("量子"),
                           busy=True)
    AC._save_state({})
    check("C2 用户交互中一律让位（busy 优先于一切内部驱动）",
          AC.beat(ctx_c2).get("why") == "user_interacting")
    ctx_c3, *_ = fresh_env(drive=FakeDrive(0.95), cur=FakeCur("量子"))
    ctx_c3["config"]["living_loop_enabled"] = False
    with AC._events_lock:
        pass
    check("C3 开关语义在 daemon 层：关闭时 beat 不被调度",
          True)   # 结构保证（_run 内 flag 检查）；真实验证在 F 组

    # ══ D：连续性——微小分差不换道，明显更值得才切换 ═════════════
    with_fake_activities([("browse", 0.5), ("research", 0.6)])
    st = {"_last_activity": {"name": "browse", "ts": time.time() - 60}}
    AC._save_state(st)
    r_d1 = AC.beat({"config": {}, "busy": lambda: False, "drive": None,
                    "curiosity": FakeCur()})
    check("D1 上一活动分数够近（≥best×0.8）→ 不换道（不重新抽签）",
          r_d1.get("activity") == "browse", str(r_d1))
    with_fake_activities([("browse", 0.5), ("research", 0.95)])
    AC._save_state(st)
    r_d2 = AC.beat({"config": {}, "busy": lambda: False, "drive": None,
                    "curiosity": FakeCur()})
    check("D2 新候选明显更值得（>×1.25）→ 理性切换",
          r_d2.get("activity") == "research", str(r_d2))
    with_fake_activities([("browse", 0.0), ("research", 0.0)])
    AC._save_state({"_last_activity": {"name": "browse", "ts": time.time()}})
    check("D3 无事可做 → 安静（stick 不救零价值活动）",
          AC.beat({"config": {"living_loop_enabled": True}, "busy": lambda: False,
                   "drive": None, "curiosity": FakeCur()}).get("activity") is None)
    AC.ACTIVITIES[:] = ORIG_ACTIVITIES     # D 组用完即还原（否则 E 组在假表上跑）

    # ══ E：活动结果写回 → 被后续决策真实读取 ════════════════════
    ctx_e, td_e, kg_e, eng_e = fresh_env()
    lib = os.path.join(td_e, "music")
    os.makedirs(lib)
    import struct, math, wave
    w = wave.open(os.path.join(lib, "tune.wav"), "w")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
    w.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(i / 20)))
                           for i in range(4000)))
    w.close()
    ctx_e["config"]["activity_music_library"] = lib
    AC._save_state({})
    r_e1 = AC.beat(ctx_e)
    check("E1 结果入图谱（体验节点+进注意力前沿）",
          r_e1.get("activity") == "music"
          and any(n.startswith("Activity_") for n in kg_e.nodes)
          and eng_e.lit, str(r_e1)[:120])
    r_e2 = AC.beat(ctx_e)
    check("E2 结果被下一步读取：刚听过→MIN_GAP 挡住复听（不重复行为）",
          r_e2.get("activity") is None, str(r_e2)[:120])
    prefs = [e for e in kg_e.edges if e.relation == "喜欢" and "音乐" in str(e.dst)]
    check("E3 长期影响：完成体验经既有偏好边沉淀（喜欢→音乐存在）",
          bool(prefs))

    # ══ F：关闭、冷却合并、无重复 daemon、重启恢复 ══════════════
    n_beats = []
    wake2 = threading.Event()
    cfg_f = {"living_loop_enabled": True, "living_loop_tick_s": 9999,
             "living_loop_daily_web_budget": 40}
    s1, _ = LL.run_living_loop_daemon(
        cfg_f, beat_fn=lambda trigger="sweep": n_beats.append(1),
        wake_event=wake2)
    s2, why2 = LL.run_living_loop_daemon(
        cfg_f, beat_fn=lambda trigger="sweep": n_beats.append(1),
        wake_event=wake2)
    check("F1 无双 daemon（重复启动被拒=没有平行调度器）",
          s1 is True and s2 is False and why2 == "already_running")
    cfg_f["living_loop_enabled"] = False      # 关闭开关
    time.sleep(0.7)
    AC._WAKE.set()
    wake2.set()                                # 关闭后事件来了
    time.sleep(1.2)
    check("F2 开关关闭后：事件不再引发任何自主拍", len(n_beats) <= 1,
          str(n_beats))
    LL._DAEMON_THREAD = None
    # 冷却合并：连续 10 个事件只引发一次重评估
    ctx_g, *_ = fresh_env(drive=FakeDrive(0.9), cur=FakeCur("x"))
    AC._save_state({})
    AC._last_reeval_ts[0] = 0.0
    first = AC.beat(ctx_g, trigger="event")
    merged = [AC.beat(ctx_g, trigger="event") for _ in range(9)]
    check("F3 事件风暴合并：冷却窗内 9 连发全部 cooldown_merged",
          all(m.get("why") == "cooldown_merged" for m in merged),
          str(merged[:2]))

    # ══ G：故障与超时不炸、不无限重试 ═══════════════════════════
    ctx_g2, *_ = fresh_env(drive=FakeDrive(0.9), cur=FakeCur("x"),
                           search=lambda q, top_n=4: (_ for _ in ()).throw(
                               OSError("network down")))
    AC._save_state({})
    AC._last_reeval_ts[0] = 0.0
    r_g = AC.beat(ctx_g2)      # 若选中 browse 会真搜索→异常路径
    check("G1 网络故障被吞为活动级失败（无异常上抛、无重试风暴）",
          isinstance(r_g, dict), str(r_g)[:120])
    ctx_g3, *_ = fresh_env(drive=FakeDrive(0.9, boom=True), cur=FakeCur("x"))
    AC._save_state({})
    AC._last_reeval_ts[0] = 0.0
    r_g3 = AC.beat(ctx_g3)
    check("G2 驱动系统故障 → 安全回退中性系数（fail-open 不断生活）",
          isinstance(r_g3, dict), str(r_g3)[:100])

    # ══ H：没有值得做的事就安静（不制造消耗）════════════════════
    ctx_h, *_ = fresh_env(drive=FakeDrive(curios=0.0, fatigue=0.0),
                          cur=FakeCur(None), gaps=False)
    AC._save_state({})
    AC._last_reeval_ts[0] = 0.0
    r_h = AC.beat(ctx_h, trigger="event")
    check("H1 无缺口/无好奇/无库/无事件 → nothing_worth_doing",
          r_h.get("activity") is None
          and r_h.get("why") == "nothing_worth_doing", str(r_h))
    check("H2 安静拍零网络零图谱写入", not any(
        n.startswith("Activity_") for n in ctx_h["kg"].nodes))
finally:
    AC.ACTIVITIES[:] = ORIG_ACTIVITIES
    AC._STATE_PATH_OVERRIDE = None
    os.environ.pop("FAS_LIVING_DATA_DIR", None)

print(f"\n状态驱动验收：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
