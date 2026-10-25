# -*- coding: utf-8 -*-
"""情境输入层测试（P3 屏幕/Steam + §5 预算闸）。全离线：观察/网络均注入假件。
运行：python tests/test_context_io.py
"""
import os
import sys
import tempfile

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import screen_watch as SW
import steam_status as ST
import usage_ledger as UL

FAILURES = []
TOTAL = [0]


def check(name, cond):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


# ══ S1 屏幕观察：默认关、显式开、限频、去重、重启回关 ══
tmp = tempfile.mkdtemp()
SW._STATE_PATH_DEFAULT = os.path.join(tmp, "sw.json")
cfg = {"screen_observe_enabled": False, "screen_observe_max_per_hour": 3}

calls = []


def fake_observe():
    calls.append(1)
    return {"items": [{"text": "创建模组的十个步骤"}],
            "full_text": "创建模组的十个步骤", "count": 1}


r = SW.observe_once(cfg)
check("S1a 默认关闭：拒绝观察", not r["ok"] and "not_enabled" in r["reason"])
check("S1b 默认关时零采集", not calls)
cfg["screen_observe_enabled"] = True
r1 = SW.observe_once(cfg, observe_fn=fake_observe)
check("S1c 显式开启后观察成功", r1["ok"] and r1["n_texts"] == 1)
check("S1d 首次非重复", not r1["duplicate"])
r2 = SW.observe_once(cfg, observe_fn=fake_observe)
check("S1e 同屏内容判重复（幂等闸）", r2["ok"] and r2["duplicate"])
r3 = SW.observe_once(cfg, observe_fn=fake_observe)
r4 = SW.observe_once(cfg, observe_fn=fake_observe)
check("S1f 小时上限生效（max=3 → 第4次拒）",
      not r4["ok"] and "rate_limited" in r4["reason"])
st = SW.status(cfg)
check("S1g status 计数可见", st["observations"] >= 3)
check("S1h 状态文件已持久化", os.path.isfile(SW._STATE_PATH_DEFAULT))
SW.apply_runtime_toggle(False)
check("S1i 一键停止：running_since 归零", SW.status()["running_since"] == 0.0)
# 重启回关 = 出厂默认 False + 键在 PRIVACY_EPHEMERAL_KEYS（不落盘），
# 后者由 test_config_store 的 ephemeral 用例覆盖；此处验证门本身默认拒


# ══ S2 Steam：门控/缺密钥/状态变化事件/去抖 ══
st_path = os.path.join(tmp, "steam_last.json")
ST._state_path = st_path
cfg2 = {"steam_poll_enabled": False, "steam_id": ""}
r = ST.tick_once(cfg2)
check("S2a 未启用直接跳过", r["reason"] == "disabled")
cfg2["steam_poll_enabled"] = True
os.environ.pop("STEAM_API_KEY", None)
_orig_secret = ST._SECRET_PATH
ST._SECRET_PATH = os.path.join(tmp, "no_such_secret.json")   # 隔离真实 key 文件
r = ST.tick_once(cfg2)
check("S2b 缺密钥如实报因（env+secret 双源都空才放行失败）",
      "STEAM_API_KEY" in r["reason"])
os.environ["STEAM_API_KEY"] = "fake"
cfg2["steam_id"] = "76561198000000000"

_seq = [{"response": {"players": [{"personastate": 1,
                                   "gameextrainfo": "Fallout 4"}]}},
        {"response": {"players": [{"personastate": 1,
                                   "gameextrainfo": "Fallout 4"}]}},
        {"response": {"players": [{"personastate": 1}]}},
        {"response": {"players": []}}]
_idx = [0]


def fake_get(path, params):
    v = _seq[_idx[0]]
    _idx[0] += 1
    return v


ST._get = fake_get
e1 = ST.tick_once(cfg2)
check("S2c 开始玩 → game_started 事件",
      e1["ok"] and e1["changed"] and e1["event"]["kind"] == "game_started"
      and e1["event"]["game"] == "Fallout 4")
e2 = ST.tick_once(cfg2)
check("S2d 同状态去抖（不重复事件）", e2["ok"] and not e2["changed"])
e3 = ST.tick_once(cfg2)
check("S2e 退出游戏 → game_stopped",
      e3["changed"] and e3["event"]["kind"] == "game_stopped")
e4 = ST.tick_once(cfg2)
check("S2f steamid 无返回（私密资料）→ 如实报因",
      not e4["ok"] and "公开" in e4["reason"])
os.environ.pop("STEAM_API_KEY", None)


# ══ S3 预算闸 ══
t2 = tempfile.mkdtemp()
UL._PATH = os.path.join(t2, "u.jsonl")
UL.configure({"llm_monthly_budget_cny": 1.0,
              "llm_price_table": {"m": {"in": 1.0, "out": 0}}})
check("S3a 未超预算放行", not UL.over_budget())
UL.record(provider="p", model="m", purpose="x", latency_ms=10,
          prompt_tokens=1, completion_tokens=0, ok=True)  # ¥0.001
check("S3b 小额仍在线内", not UL.over_budget())
UL.record(provider="p", model="m", purpose="x", latency_ms=10,
          prompt_tokens=1000, completion_tokens=0, ok=True)  # ¥1 → 超
check("S3c 超阈值触发", UL.over_budget())
try:
    UL.guard()
    check("S3d guard 抛 BudgetExhausted", False)
except UL.BudgetExhausted:
    check("S3d guard 抛 BudgetExhausted", True)
UL.configure({"llm_monthly_budget_cny": 0})
check("S3e 阈值 0=不限（默认零行为变化）", not UL.over_budget())
s = UL.month_summary()
check("S3f 月度统计含按模型分组", s["calls"] == 2 and "p/m" in s["by_model"])

print(f"\n情境输入层：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
