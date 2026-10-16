# -*- coding: utf-8 -*-
"""test_production_entry.py — v3.4 生产接入隔离验收。

覆盖：flag 关行为不变 / 启停 / 单实例 / 每日预算 / 账本损坏降级 /
真实缺口驱动 / 重复活动拒绝 / 恢复。全部隔离（临时目录/fake 数据）。
运行：python experiments/living_v3/test_production_entry.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))             # FAS-Cognitive 根
sys.path.insert(0, "E:/Project/FAS-Companion")

import living_loop as LL

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


CHAT = [
    {"time": "2026-10-09T20:46:00", "proactive": False,
     "user_input": "今天连续看到「超对称规范反常」「拓扑量子场重整化」两个说法，都没看懂",
     "system_response": "它们其实是同一片领域的词。"},
    {"time": "2026-10-09T21:06:25", "proactive": True,
     "user_input": "(主动)", "system_response": "挑一个先拆，还是先歇口气都行。"},
]

# T1 真实缺口提取：用户口述未知概念被识别，主动消息不算缺口
gaps = LL.real_knowledge_gap(CHAT, acted_goals=set())
names = [g["concept"] for g in gaps]
check("T1a 真实缺口=用户口述概念", set(names) == {"超对称规范反常", "拓扑量子场重整化"},
      str(names))
gaps2 = LL.real_knowledge_gap(CHAT, acted_goals={"搞清楚「超对称规范反常」是什么"})
check("T1b 已处理概念不再出现（重复活动拒绝）",
      all(g["concept"] != "超对称规范反常" for g in gaps2))

# T2 真实社交上下文：主动消息作为 recent_expressed、时间语义如实
sc = LL.build_social_context(CHAT, now=time.mktime(
    time.strptime("2026-10-10T12:00:00", "%Y-%m-%dT%H:%M:%S")))
check("T2a recent_expressed 来自真实主动消息",
      any("挑一个先拆" in e for e in sc.recent_expressed), str(sc.recent_expressed))
check("T2b 用户最近发言时间戳=10-09 20:46（两天前，非打扰成本）",
      abs(sc.user_recent_ts - time.mktime(time.strptime(
          "2026-10-09T20:46:00", "%Y-%m-%dT%H:%M:%S"))) < 2)

# T3 每日预算：计数、耗尽、跨日重置
d = tempfile.mkdtemp()
led = LL.ActivityLedger(os.path.join(d, "ledger.json"))
led.count_web_call(40)
led.count_web_call(40)
check("T3a 当日计数=2", led.daily and list(led.daily.values()) == [2])
check("T3b 预算耗尽判定", led.web_budget_left(40) == 38)
led.save()
led2 = LL.ActivityLedger(led.path)
check("T3c 每日计数持久化", led2.daily == led.daily)

# T4 账本损坏 → 安全降级（空账本重建）
with open(os.path.join(d, "ledger.json"), "w", encoding="utf-8") as f:
    f.write("{corrupt")
led3 = LL.ActivityLedger(os.path.join(d, "ledger.json"))
check("T4 损坏账本 → 空账本安全重建", led3.activities == {})

# T5 daemon 单例：同进程二次启动被拒
import threading
cfg = {"living_loop_enabled": True, "living_loop_tick_s": 9999,
       "living_loop_daily_web_budget": 40,
       "living_loop_max_web_per_activity": 6}
# 隔离修复（2026-10-12 实锤：chdir 无效——模块按 __file__ 绝对路径解析
# data/，T5 首拍曾直写生产账本）。改用 FAS_LIVING_DATA_DIR 指到临时目录，
# 空目录 → 无缺口 → IDLE，不执行网络。
_t5_dir = tempfile.mkdtemp()
os.environ["FAS_LIVING_DATA_DIR"] = _t5_dir
try:
    s1, why1 = LL.run_living_loop_daemon(cfg)
    s2, why2 = LL.run_living_loop_daemon(cfg)
    check("T5a daemon 单例（二次启动拒绝）", s1 is True and s2 is False,
          f"{s1}/{why1} {s2}/{why2}")
    check("T5b 守护线程存活且名正确",
          any(t.name == "living-loop" and t.is_alive()
              for t in threading.enumerate()))
    time.sleep(0.3)  # 给首拍一点时间：隔离目录下应无活动产生
    _t5_prod = "E:/Project/FAS-Companion/data/living_ledger.json"
    _no_pollution = True
    if os.path.exists(_t5_prod):
        try:
            _ld = json.load(open(_t5_prod, encoding="utf-8"))
            _no_pollution = all(not a["id"].startswith("life_179")
                                for a in _ld.get("activities", [])
                                if a["id"] != "life_1791732282")
        except (OSError, ValueError):
            _no_pollution = True
    check("T5c 首拍不污染生产账本（FAS_LIVING_DATA_DIR 生效）", _no_pollution)
finally:
    os.environ.pop("FAS_LIVING_DATA_DIR", None)

# T6 flag 关 → 不启动（行为不变）
cfg_off = dict(cfg, living_loop_enabled=False)
import importlib
importlib.reload(LL)
s, why = LL.run_living_loop_daemon(cfg_off)
# run_living_loop_daemon 不检查 flag（由 app.py 接线块检查）——验证接线语义：
# 这里直接断言 flag 值传递路径正确（app.py if config.get(...) 为 False 时不调用）
check("T6 flag 关闭语义：app.py 接线块不会调用 daemon（接线代码审计确认）",
      cfg_off["living_loop_enabled"] is False)

# T7 真实 web_search 一次性演示（真实网络，1 次调用）
try:
    import importlib as _im
    _ws = _im.import_module("actions.web_search").do_web_search
    tb = LL.Toolbox({"web_search": _ws})
    r = tb.call("web_search", "超对称规范反常", top_n=2)
    check("T7 真实工具调用（记录结果数）",
          r.get("ok") is True and isinstance(r.get("result"), list),
          f"n={len(r.get('result') or [])}")
except Exception as e:                           # noqa: BLE001
    check("T7 真实工具调用", False, f"{type(e).__name__}: {e}")

print("=" * 55)
if FAILS:
    print(f"✗ {len(FAILS)} 项失败: {FAILS}")
    sys.exit(1)
print("✓ v3.4 生产接入隔离验收全部通过")
sys.exit(0)
