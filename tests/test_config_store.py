# -*- coding: utf-8 -*-
"""config_store 单元测试（P0 配置持久化）。脚本式，按仓内约定退出码=结果。

覆盖：bool 强转 bug 修复 / 未知键拒绝 / 段浅合并 / 覆盖文件重放 /
隐私 ephemeral 键不持久化 / 坏文件不阻断启动 / 原子写。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# split_repos bootstrap: FAS-Cognitive sibling
_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

from config_store import (load_overlay, save_overlay, merge_overlay,
                          coerce_value, apply_updates)

FAILURES = []
TOTAL = [0]


def check(name, cond):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


# 1) coerce：历史 bug——"false" 变 True
check("bool 字符串 false → False", coerce_value(True, "false") is False)
check("bool 真值 true → True", coerce_value(False, "true") is True)
check("bool 原生 True → True", coerce_value(False, True) is True)
check("bool 数字 0 → False", coerce_value(True, 0) is False)
try:
    coerce_value(True, "也许")
    check("bool 垃圾输入抛错", False)
except ValueError:
    check("bool 垃圾输入抛错", True)

# 2) int/float/dict/str
check("int 数字串可转", coerce_value(600, "120") == 120)
check("dict 段浅合并保留未提键",
      coerce_value({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3})
check("list 原样替换", coerce_value([1], [2, 3]) == [2, 3])
check("str 保留字符串", coerce_value("x", "y") == "y")

# 3) overlay 合并语义
cfg = {"living_loop_enabled": False, "planner": {"enabled": False, "x": 1}}
merge_overlay(cfg, {"living_loop_enabled": True,
                    "planner": {"enabled": True}})
check("overlay 覆盖标量", cfg["living_loop_enabled"] is True)
check("段浅合并不丢出厂键", cfg["planner"] == {"enabled": True, "x": 1})

# 4) apply_updates：落盘 + no_persist + 拒绝
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "overlay.json")
    cfg = {"voice_enabled": False, "voice_listen_enabled": False, "n": 5}
    r = apply_updates(cfg, {"voice_enabled": "true",
                            "voice_listen_enabled": "true",
                            "n": "7", "ghost_key": 1}, path,
                      no_persist=frozenset({"voice_listen_enabled"}))
    check("更新生效", cfg["voice_enabled"] is True and cfg["n"] == 7)
    check("监听开关也即时生效", cfg["voice_listen_enabled"] is True)
    check("未知键被拒", r["rejected"].get("ghost_key") == "unknown_key")
    ov = load_overlay(path)
    check("普通键持久化", ov.get("voice_enabled") is True and ov.get("n") == 7)
    check("隐私 ephemeral 键不落盘", "voice_listen_enabled" not in ov)
    # 重启重放：fresh config + overlay → 只恢复持久化的
    fresh = {"voice_enabled": False, "voice_listen_enabled": False, "n": 5}
    merge_overlay(fresh, load_overlay(path))
    check("重启后 voice 恢复", fresh["voice_enabled"] is True and fresh["n"] == 7)
    check("重启后麦克风回到出厂关", fresh["voice_listen_enabled"] is False)
    # 坏文件不炸
    with open(path, "w", encoding="utf-8") as f:
        f.write("{broken")
    check("损坏覆盖文件 → 空 dict", load_overlay(path) == {})
    check("覆盖文件目录不存在也能写", save_overlay(
        os.path.join(td, "sub", "o.json"), {"a": 1}))
    check("原子写无残留 tmp 文件",
          not [x for x in os.listdir(os.path.join(td, "sub")) if x.startswith(".cfg_overlay")])

# 5) 认知仓 config 声明了新段（PUT 只认已有键的前置条件）
from config import DEFAULT_CONFIG
check("DEFAULT_CONFIG 有 interaction_planner 段",
      isinstance(DEFAULT_CONFIG.get("interaction_planner"), dict)
      and DEFAULT_CONFIG["interaction_planner"]["enabled"] is False)
for k in ("voice_enabled", "voice_listen_enabled", "voice_tts_backend",
          "screen_observe_enabled", "steam_poll_enabled",
          "llm_monthly_budget_cny"):
    check(f"DEFAULT_CONFIG 有 {k}", k in DEFAULT_CONFIG)
check("screen 出厂默认关", DEFAULT_CONFIG["screen_observe_enabled"] is False)
check("语音出厂默认关", DEFAULT_CONFIG["voice_enabled"] is False)

print(f"\nconfig_store：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
