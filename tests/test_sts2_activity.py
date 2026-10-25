# -*- coding: utf-8 -*-
"""STS2 生活活动整合验收（2026-10-16）。
零网络零 LLM：ScriptedTransport 回放真实 mod /state 形状。
验证：注册协议、可用性、appeal 语义、结算唯一写点、期望驱动偏好、
重复读取幂等、unknown 不伪装、预算即停、发现回写生产图。
运行：python tests/test_sts2_activity.py
"""
import os
import sys
import tempfile

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
for p in (_r, _cog):
    if p not in sys.path:
        sys.path.insert(0, p)
import logging
logging.disable(logging.WARNING)

import config as C                                            # noqa: E402
import activities as ACT                                      # noqa: E402
from graph_model import KnowledgeGraph, Node, Edge          # noqa: E402
from sts2_sim.live_session import ScriptedTransport          # noqa: E402

FAILURES = []
N = [0]


def check(name, cond, detail=""):
    N[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" +
          (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def combat_state(turn=1, hp=60, hand=None, enemies=None, run_id="R1"):
    return {"screen": "COMBAT", "run_id": run_id, "turn": turn,
            "in_combat": True,
            "combat": {
                "action_readiness": {"can_use_combat_actions": True},
                "player": {"current_hp": hp, "block": 0, "energy": 3,
                           "max_hp": 75, "stars": 0},
                "hand": hand if hand is not None else [
                    {"index": 0, "name": "打击",
                     "resolved_rules_text": "造成6点伤害。",
                     "energy_cost": 1, "star_cost": 0,
                     "requires_target": True,
                     "valid_target_indices": [0]},
                    {"index": 1, "name": "陨星",
                     "resolved_rules_text":
                     "造成8点伤害。给予1层虚弱。给予1层易伤。",
                     "energy_cost": 0, "star_cost": 2,
                     "requires_target": True,
                     "valid_target_indices": [0]}],
                "enemies": enemies if enemies is not None else [
                    {"index": 0, "name": "绿史莱姆", "current_hp": 10,
                     "max_hp": 10, "block": 0, "is_alive": True,
                     "is_hittable": True, "powers": [],
                     "intents": [{"intent_type": "Attack",
                                  "total_damage": 5, "hits": 1}]}]}}


def gameover_state(victory=True, floor=30, run_id="R1"):
    return {"screen": "GAME_OVER", "run_id": run_id,
            "game_over": {"is_victory": victory, "floor": floor,
                          "character_id": "REGENT"}}


def mk_ctx(transport, reward=None, timeline=None):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self"))
    return {"config": dict(C.DEFAULT_CONFIG), "kg": kg, "engine": None,
            "busy": lambda: False,
            "sts2_transport": transport,
            "reward_fn": (lambda: reward) if reward
            else (lambda: None),
            "timeline_fn": (lambda: timeline)
            if timeline is not None else (lambda: None)}


# ── S1 注册与协议 ──────────────────────────────────────────
row = next((r for r in ACT.ACTIVITIES if r[0] == "sts2"), None)
check("S1a sts2 在 ACTIVITIES 注册表中", row is not None and len(row) == 4)
check("S1b 四元组均 callable", row and all(callable(f) for f in row[1:]))

# ── S2 可用性 × 自主级别（不许愿，但允许自启） ──────────────
off_ctx = mk_ctx(ScriptedTransport([], health_ok=False))
off_ctx["config"] = dict(C.DEFAULT_CONFIG)
off_ctx["config"]["pc_autonomy"] = {"level": "off"}
ok, _ = ACT.sts2_available(off_ctx)
check("S2a level=off：桥不在→自然退出候选（旧语义保留）", not ok)
at_ctx = mk_ctx(ScriptedTransport([], health_ok=False))
at_ctx["config"] = dict(C.DEFAULT_CONFIG)
at_ctx["config"]["pc_autonomy"] = dict(
    C.DEFAULT_CONFIG["pc_autonomy"], level="attended")
at_ctx["pc_present"] = False
ok3, w3 = ACT.sts2_available(at_ctx)
check("S2b attended+无人在场→不可选（不在场不许启动）", not ok3 and "在场" in w3)
ua_ctx = mk_ctx(ScriptedTransport([], health_ok=False))
ua_ctx["config"] = dict(C.DEFAULT_CONFIG)
ua_ctx["config"]["pc_autonomy"] = dict(
    C.DEFAULT_CONFIG["pc_autonomy"], level="unattended")
ok4, _ = ACT.sts2_available(ua_ctx)
check("S2c unattended：桥不在也可开局=候选", ok4)
at_ctx2 = mk_ctx(ScriptedTransport([], health_ok=False))
at_ctx2["config"] = dict(C.DEFAULT_CONFIG)
at_ctx2["config"]["pc_autonomy"] = dict(
    C.DEFAULT_CONFIG["pc_autonomy"], level="attended")
at_ctx2["pc_present"] = True
ok5, _ = ACT.sts2_available(at_ctx2)
check("S2d attended+有人在场→可开局候选", ok5)
ctx = mk_ctx(None)
ctx["config"] = dict(C.DEFAULT_CONFIG)
ctx["config"]["pc_autonomy"] = {"level": "off"}
ctx["config"]["sts2_api"] = "http://127.0.0.1:9"     # 必拒端口
ok2, _why = ACT.sts2_available(ctx)
check("S2e off 级真实探测失败 → False，不启动任何东西", not ok2)
ctx_off = mk_ctx(ScriptedTransport([], health_ok=True))
ctx_off["config"] = dict(C.DEFAULT_CONFIG)
ctx_off["config"]["activity_sts2"] = False
ctx_on = mk_ctx(ScriptedTransport([gameover_state()], health_ok=True))
check("S2f 活动开关一票否决，默认开",
      not ACT.sts2_available(ctx_off)[0]
      and ACT.sts2_available(ctx_on)[0])

# ── S3 appeal 语义 ─────────────────────────────────────────
base_state = {}
a0 = ACT._sts2_appeal(mk_ctx(None), base_state)          # 无边无历史
kg2 = KnowledgeGraph()
kg2.add_node(Node(id="Self"))
kg2.add_node(Node(id="杀戮尖塔"))
kg2.add_edge(Edge(src="Self", dst="杀戮尖塔", relation="喜欢",
                  weight=0.85))
c1 = {"config": dict(C.DEFAULT_CONFIG), "kg": kg2, "engine": None}
a1 = ACT._sts2_appeal(c1, {})
check("S3a 偏好边权重↑ → appeal↑", a1 > a0 > 0, (a0, a1))
import time as _t
st_hot = {"sts2": {"last_ts": _t.time(), "plays_today": 3,
                   "day": _t.strftime("%Y%m%d")}}
check("S3b 刚玩过/当天玩多 → 明显衰减",
      ACT._sts2_appeal(c1, st_hot) < a1 * 0.3)

# ── S4 胜利结算：期望/RPE/偏好/时间轴/幂等 ─────────────────
from internal_state import InternalState                 # noqa: E402
from reward import RewardSystem                          # noqa: E402
st = InternalState(kg=None, config={}, data_dir=tempfile.mkdtemp())
rs = RewardSystem(internal_state=st, config={})
tl = []
ACT._STS2_EXP_PATH = os.path.join(tempfile.mkdtemp(), "exp.json")
tr_win = ScriptedTransport([combat_state(), gameover_state(
    victory=True, floor=30)], health_ok=True)
ctxw = mk_ctx(tr_win, reward=rs, timeline=tl)
state = {}
res = ACT.sts2_beat(ctxw, state)
check("S4a 会话产出 victory", res.get("result") == "victory", res)
check("S4b 结算走通用 reward（期望建立）",
      rs.is_state.expectation("play_sts2@杀戮尖塔") > 0.0)
exp_first = rs.is_state.expectation("play_sts2@杀戮尖塔")
prefs = [(e.weight, e.dst) for e in ctxw["kg"].edges
         if e.relation == "喜欢"]
check("S4c 超预期胜利 → 偏好边生成/上调", bool(prefs), prefs)
check("S4d 时间轴可追溯一条", tl and
      tl[-1]["content"].get("result") == "victory", tl[-1:])
w_after = exp_first
# 重复读取：同一 run 再次到达（transport 只给 gameover）→ 不重复结算
tr_dup = ScriptedTransport([gameover_state(victory=True, floor=30)],
                           health_ok=True)
ctxd = mk_ctx(tr_dup, reward=rs, timeline=tl)
ctxd["kg"] = ctxw["kg"]
res2 = ACT.sts2_beat(ctxd, state)          # 同 state → last_settled_run 命中
check("S4e 同一 run 结果重复读取不再计证据",
      res2.get("settled") is False and
      rs.is_state.expectation("play_sts2@杀戮尖塔") == w_after,
      (res2, w_after))
# 满期望后再胜：RPE≈0 → 偏好边几乎不动（B4.1 符合预期的胜利不满意）
prefs_w = [e.weight for e in ctxw["kg"].edges if e.relation == "喜欢"][0]
for _ in range(25):
    rs.release([__import__("reward").new_event(
        source="self", outcome="goal_success", valence=1.0,
        behavior="play_sts2", context="杀戮尖塔")])
exp_hi = rs.is_state.expectation("play_sts2@杀戮尖塔")
check("S4f 连续胜利 → 期望收敛到高值（下次胜利不再是惊喜）",
      exp_hi > 0.9, exp_hi)

# ── S5 失败与未知 ──────────────────────────────────────────
tr_lose = ScriptedTransport([combat_state(), gameover_state(
    victory=False, floor=3, run_id="R2")], health_ok=True)
ctxl = mk_ctx(tr_lose, reward=rs, timeline=tl)
ctxl["kg"] = KnowledgeGraph()
ctxl["kg"].add_node(Node(id="Self"))
res_l = ACT.sts2_beat(ctxl, {})
ev_l = [e for e in rs._recent if e["context"] == "杀戮尖塔"][-1]
check("S5a 低层失败是负反馈且按进度分级（valence > -0.7）",
      res_l["result"] == "defeat" and -0.75 <= ev_l["valence"] < 0,
      (res_l, ev_l["valence"]))
tr_brk = ScriptedTransport([], health_ok=True)           # 立刻耗尽=断链
ctxb = mk_ctx(tr_brk, reward=rs, timeline=tl)
n_before = len([e for e in rs._recent])
res_b = ACT.sts2_beat(ctxb, {})
check("S5b 结果不可读 → unknown，不写 reward/时间轴（不伪装）",
      res_b["result"] == "unknown" and
      len([e for e in rs._recent]) == n_before and
      res_b.get("settled") is not True, res_b)
tr_ab = ScriptedTransport([combat_state()], health_ok=True)
ctxab = mk_ctx(tr_ab, reward=rs, timeline=tl)
ctxab["config"] = dict(ctxab["config"])
ctxab["config"]["sts2_session_budget_s"] = 0.0
res_ab = ACT.sts2_beat(ctxab, {})
check("S5c 预算尽 → aborted（心跳不被挂起），blocked 轻负",
      res_ab["result"] == "aborted", res_ab)

# ── S6 发现回写生产图（概念+兴趣+扩散） ────────────────────
kgp = KnowledgeGraph()
kgp.add_node(Node(id="Self"))
ctx6 = mk_ctx(ScriptedTransport([], health_ok=True))
ctx6["kg"] = kgp
mech = [{"name": "卡牌:陨星", "text": "造成8点伤害。给予1层虚弱。"},
        {"name": "机制:虚弱", "text": "给予1层虚弱。"}]
res6 = {"result": "victory", "floor": 12, "run_id": "R6",
        "new_mechanics": mech}
s6 = {}
ACT._sts2_settle(ctx6, s6, res6)
n1 = kgp.get_node("概念:陨星")
n2 = kgp.get_node("概念:虚弱")
import curiosity_engine as _ce                           # noqa: E402
check("S6a 新牌/机制成概念节点（带来源与原文证据）",
      n1 is not None and n2 is not None and
      n1.extra_attrs.get("source") == "game:sts2" and
      "造成8点伤害" in str(n1.extra_attrs.get("evidence")),
      n1 and n1.extra_attrs)
check("S6b 兴趣水位已抬升（为后续探索/表达供料）",
      _ce.get_interest(kgp, "概念:虚弱")["level"] > 0.0)

# ── S7 经验宿主文件读写闭环 ────────────────────────────────
from sts2_sim import kb as _kb                           # noqa: E402
p_exp = os.path.join(tempfile.mkdtemp(), "e.json")
kgx = KnowledgeGraph()
_kb.persist_experience(kg2, p_exp)                       # 空图也安全
check("S7a persist 空文件不炸", os.path.exists(p_exp))
kg3 = KnowledgeGraph()
r_in = _kb.load_experience(kg3, p_exp)
check("S7b load 往返无损", r_in["edges"] >= 0)

# ── S8 自启游戏（pc_autonomy 分级闸下的 beat 闭环） ─────────
import json as _json                                       # noqa: E402
from internal_state import InternalState as _IS2          # noqa: E402
from reward import RewardSystem as _RS2                   # noqa: E402
st2 = _IS2(kg=None, config={}, data_dir=tempfile.mkdtemp())
rs2 = _RS2(internal_state=st2, config={})
tl8 = []
td9 = os.path.join(tempfile.mkdtemp(), "state.json")
ACT.reset_state_for_test(td9)


def _ua_cfg():
    c = dict(C.DEFAULT_CONFIG)
    c["pc_autonomy"] = dict(C.DEFAULT_CONFIG["pc_autonomy"],
                            level="unattended", boot_wait_s=3)
    return c


tr8 = ScriptedTransport([gameover_state(victory=True, floor=20,
                                        run_id="RB")], health_ok=False)


def _fake_up(_ctx):
    tr8.health_ok = True                      # 假启动：桥变就绪
    return True


ctx8 = mk_ctx(tr8, reward=rs2, timeline=tl8)
ctx8["config"] = _ua_cfg()
ctx8["sts2_launcher"] = _fake_up
state8 = {}
res8 = ACT.sts2_beat(ctx8, state8)
check("S8a 无人值守档：自己开游戏→跑完→胜利结算",
      res8["result"] == "victory" and res8.get("settled"), res8)
check("S8b 时间轴记录 self_booted 可追溯",
      tl8 and tl8[-1]["content"].get("self_booted") is True, tl8[-1:])
check("S8c 成功后失败计数为 0",
      int(state8.get("sts2", {}).get("launch_fails", 0) or 0) == 0)

tr9 = ScriptedTransport([gameover_state(run_id="RF")], health_ok=False)
ctx9 = mk_ctx(tr9, reward=rs2, timeline=tl8)
ctx9["config"] = _ua_cfg()
ctx9["sts2_launcher"] = lambda c: False
n_tl = len(tl8)
n_ev = len(list(rs2._recent))
state9 = {"sts2": {}}
res9 = ACT.sts2_beat(ctx9, state9)
check("S8d 启动失败 → unavailable：零 reward/零时间轴（不许愿不记账）",
      res9["result"] == "unavailable" and len(tl8) == n_tl
      and len(list(rs2._recent)) == n_ev
      and state9["sts2"]["launch_fails"] == 1, res9)
with ACT._STATE_LOCK:
    ACT._save_state(state9)
ctx9b = mk_ctx(ScriptedTransport([], health_ok=False))
ctx9b["config"] = _ua_cfg()
ok_b, why_b = ACT.sts2_available(ctx9b)
check("S8e 失败退避期内：有权限也不当候选",
      not ok_b and "退避" in str(why_b), (ok_b, why_b))
_j = _json.load(open(td9, encoding="utf-8"))
_j["sts2"]["last_launch_try"] -= 999999
_json.dump(_j, open(td9, "w", encoding="utf-8"), ensure_ascii=False)
ok_c, _ = ACT.sts2_available(ctx9b)
check("S8f 退避期满 → 恢复候选（指数退避不是永久禁令）", ok_c)
ACT.reset_state_for_test(None)

# ── S9 pc_autonomy 单元闸 ──────────────────────────────────
import pc_autonomy as PA                                   # noqa: E402
cfg_att = dict(C.DEFAULT_CONFIG["pc_autonomy"],
                 level="attended")
check("S9a off 级一切免谈",
      PA.can_launch({"pc_autonomy": dict(cfg_att, level="off")},
                    "sts2", present=True)[0] is False)
check("S9b attended：present 决定",
      PA.can_launch({"pc_autonomy": dict(cfg_att)}, "sts2",
                    present=False)[0] is False
      and PA.can_launch({"pc_autonomy": dict(cfg_att)}, "sts2",
                        present=True)[0] is True)
check("S9c 白名单外程序拒",
      PA.can_launch({"pc_autonomy": dict(cfg_att, apps={})},
                    "sts2", present=True)[0] is False)
check("S9d user_present 保守失败（取不到输入=不在场）",
      PA.user_present({"present_idle_s": 900},
                      idle_fn=lambda: None) is False
      and PA.user_present({"present_idle_s": 900},
                          idle_fn=lambda: 30) is True)
launch_rec = []


def _fake_opener(target):
    launch_rec.append(target)


ok_l, _ = PA.launch({"pc_autonomy": cfg_att}, "sts2",
                    opener=_fake_opener)
check("S9e 启动命令走 Steam 官方协议白名单",
      ok_l and launch_rec == ["steam://rungameid/2868840"], launch_rec)

# ── S10 请求→动机翻译（"让她玩她不玩"修复回归） ────────────
td10 = os.path.join(tempfile.mkdtemp(), "state10.json")
ACT.reset_state_for_test(td10)
kg10 = KnowledgeGraph()
kg10.add_node(Node(id="Self"))
ctx10 = {"config": dict(C.DEFAULT_CONFIG), "kg": kg10, "engine": None}
before_appeal = ACT._sts2_appeal(ctx10, {})
hit = ACT.harvest_activity_request(ctx10, "玩会杀戮尖塔2呗")
import curiosity_engine as _ce2                            # noqa: E402
check("S10a 命中活动关键词 → 翻译结果",
      hit and hit["app"] == "sts2" and hit["concept"] == "杀戮尖塔", hit)
check("S10b concept 兴趣被点亮（signal +0.25）",
      _ce2.get_interest(kg10, "杀戮尖塔")["level"] > 0.0)
pref10 = [(e.dst, round(float(e.weight), 2))
          for e in kg10.edges if e.relation == "喜欢"]
check("S10c 无偏好边则补试探边", pref10 == [("杀戮尖塔", 0.25)], pref10)
after_appeal = ACT._sts2_appeal(ctx10, {})
check("S10d appeal 真的因这句话涨了", after_appeal > before_appeal + 0.05,
      (before_appeal, after_appeal))
# 新鲜度通道：直接邀请当次应赢过论坛基线（browse≈0.42 档）
st10 = ACT._load_state()
fresh_appeal = ACT._sts2_appeal(ctx10, st10)
check("S10g 刚被邀请 → appeal 越过论坛水位", fresh_appeal > 0.42,
      fresh_appeal)
import time as _t10                              # noqa: E402
_j10 = _json.load(open(td10, encoding="utf-8"))
_j10["sts2"]["request_ts"] = _t10.time() - 2 * 3600   # 两小时前的话
_j10["sts2"]["last_ts"] = _t10.time() - 4 * 3600      # 上局也久了
_json.dump(_j10, open(td10, "w", encoding="utf-8"), ensure_ascii=False)
stale = ACT._sts2_appeal(ctx10, ACT._load_state())
check("S10h 请求影响力两小时半衰（不永久霸榜）",
      stale < fresh_appeal * 0.75, (fresh_appeal, stale))
for _i in range(8):
    ACT.harvest_activity_request(ctx10, "尖塔 爬塔 sts2 再玩一把")
lvl_capped = _ce2.get_interest(kg10, "杀戮尖塔")["level"]
check("S10e 反复喊话封顶不失控（level≤1.0，涨到顶也只是想玩不是命令）",
      lvl_capped <= 1.0 + 1e-9, lvl_capped)
check("S10f 无关话语零副作用",
      ACT.harvest_activity_request(ctx10, "今天天气不错") is None)
ACT.reset_state_for_test(None)

# ── S11 attended 强制后台（2026-10-16 语义） ───────────────
import pc_autonomy as _PA                               # noqa: E402
_min_calls = []
_orig_min = _PA.minimize_window
_PA.minimize_window = lambda title, **kw: _min_calls.append(title) or True
tr11 = ScriptedTransport([gameover_state(victory=True, floor=5,
                                        run_id="RB11")], health_ok=False)
ctx11 = mk_ctx(tr11, reward=None, timeline=None)
cfg11 = dict(C.DEFAULT_CONFIG)
cfg11["pc_autonomy"] = dict(C.DEFAULT_CONFIG["pc_autonomy"],
                            level="attended", background=False,
                            boot_wait_s=3)
ctx11["config"] = cfg11
ctx11["pc_present"] = True
ctx11["sts2_launcher"] = lambda c: (setattr(tr11, "health_ok", True) or True)
ACT.reset_state_for_test(os.path.join(tempfile.mkdtemp(), "s11.json"))
r11 = ACT.sts2_beat(ctx11, {})
check("S11a attended → 即使 background=false 也被最小化（强制后台）",
      r11["result"] == "victory" and len(_min_calls) == 1,
      (r11["result"], _min_calls))
_min_calls.clear()
cfg11["pc_autonomy"] = dict(cfg11["pc_autonomy"], level="unattended")
tr11b = ScriptedTransport([gameover_state(victory=True, floor=6,
                                          run_id="RB12")], health_ok=False)
ctx11b = mk_ctx(tr11b)
ctx11b["config"] = cfg11
ctx11b["pc_present"] = True
ctx11b["sts2_launcher"] = lambda c: (setattr(tr11b, "health_ok", True) or True)
r11b = ACT.sts2_beat(ctx11b, {})
check("S11b unattended+background=false → 允许前台（不误伤）",
      r11b["result"] == "victory" and not _min_calls, _min_calls)
_PA.minimize_window = _orig_min
ACT.reset_state_for_test(None)

print("── 汇总 ──")
if FAILURES:
    print(f"失败 {len(FAILURES)}/{N[0]}: {FAILURES}")
    sys.exit(1)
print(f"通过 {N[0]} 条，全部通过")
