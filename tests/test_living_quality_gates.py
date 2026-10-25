# -*- coding: utf-8 -*-
"""生活循环质量闸门回归测试（P0-2，2026-10-12）。

复现实锤误报场景并验证修复：
  G1 查询改写无引号残迹（"数熵」"类查询不再产生）
  G2 字典页误报被拒（整词/双碎片相关闸）
  G3 真相关结果 → found 且每日预算计数接线
  G4 页面残片与主题不符 → 不算发现（继续改写而非 DONE）
  G5 耗尽概念水印：同缺口不重开
  G6 waiting 活动新预算日恢复 active
  G7 分享候选消费：deliver_fn True→标记 / False→延后不丢
运行：python tests/test_living_quality_gates.py（脚本式，隔离临时目录）
"""
import json
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

import living_loop as LL

FAILURES = []
TOTAL = [0]


def check(name, cond):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


CFG = {"living_loop_daily_web_budget": 40,
       "living_loop_max_activities_open": 3,
       "living_loop_max_web_per_activity": 8}
CONCEPT = "冯诺依曼代数熵"
CHAT = [{"time": "2026-10-11T21:00:00", "proactive": False,
         "user_input": f"「{CONCEPT}」到底是什么，没看懂",
         "system_response": ""}]


def mk_env():
    d = tempfile.mkdtemp()
    json.dump(CHAT, open(os.path.join(d, "chat_log.json"), "w",
                         encoding="utf-8"))
    return d


def search_dict_page(q, top_n=4):
    """误报复现：《数》字典页——旧宽松闸判相关，新闸必须拒。"""
    return [{"title": "数_百度汉语", "snippet": "数，读音shù，几个：～目。",
             "url": "http://example.com/dict"},
            {"title": "数学简介", "snippet": "数学是研究数量结构的学科",
             "url": "http://example.com/math"}]


def search_real_page(q, top_n=4):
    return [{"title": f"论{CONCEPT}的有限性问题",
             "snippet": f"{CONCEPT}是算子代数中的熵不变量",
             "url": "http://example.com/paper"}]


# ── G1 查询改写无残迹 ──
for attempt in range(6):
    q = LL.query_rewrite(f"搞清楚「{CONCEPT}」", attempt)
    check(f"G1 第{attempt}档查询无括号残迹 [{q}]",
          "「" not in q and "」" not in q and not q.startswith("搞清楚"))
check("G1 清洗后首档=概念本体", LL.query_rewrite(f"搞清楚「{CONCEPT}」", 0) == CONCEPT)

# ── G2 字典页误报被拒（端到端：一拍只开活动，第二拍探索拒字典页） ──
env = mk_env()
r1 = LL.living_tick_once(CFG, search_fn=search_dict_page, data_dir=env)
check("G2a 首拍开出活动", r1["opened"] is not None)
r2 = LL.living_tick_once(CFG, search_fn=search_dict_page, data_dir=env)
check("G2b 字典页结果判不相关（不误报 found）", r2["explored"][0]["result"] == "irrelevant")
led = json.load(open(os.path.join(env, "living_ledger.json"), encoding="utf-8"))
a = led["activities"][0]
check("G2c 无 findings（零污染）", a["findings"] == [] and a["state"] == "active")
check("G2d 概念已存为干净种子", a.get("concept") == CONCEPT)

# 连续拍至策略耗尽 → paused（水印生效的前提）
for _ in range(4):
    LL.living_tick_once(CFG, search_fn=search_dict_page, data_dir=env)
led = json.load(open(os.path.join(env, "living_ledger.json"), encoding="utf-8"))
a = led["activities"][0]
check("G2e 策略耗尽后 paused", a["state"] == "paused"
      and a["end_reason"] == "all_query_strategies_exhausted")
# G5 同缺口不重开
live = sum(1 for x in led["activities"] if x["state"] in ("active", "waiting"))
check("G5a 无活跃活动", live == 0)
r3 = LL.living_tick_once(CFG, search_fn=search_dict_page, data_dir=env)
check("G5b 耗尽概念被水印拒绝，不重开", r3["opened"] is None)

# ── G3 真相关 → found + 预算接线 ──
env2 = mk_env()
LL.living_tick_once(CFG, search_fn=search_real_page, data_dir=env2)
orig_read = LL.read_page
LL.read_page = lambda url, **k: {"ok": True, "source": url, "untrusted": True,
                                 "text": f"本文研究{CONCEPT}的定义与性质……"}
try:
    r = LL.living_tick_once(CFG, search_fn=search_real_page, data_dir=env2)
finally:
    LL.read_page = orig_read
check("G3a 真相关结果判 found", r["explored"][0]["result"] == "found")
led2 = json.load(open(os.path.join(env2, "living_ledger.json"), encoding="utf-8"))
today = list(led2["daily_web_calls"].keys())
check("G3b 每日预算计数已接线（非空）", bool(today) and led2["daily_web_calls"][today[0]] >= 2)

# ── G4 页面内容与主题不符 → 不算发现 ──
env3 = mk_env()
LL.living_tick_once(CFG, search_fn=search_real_page, data_dir=env3)
LL.read_page = lambda url, **k: {"ok": True, "source": url, "untrusted": True,
                                 "text": "今日天气晴，宜出行。无关残片页面。"}
try:
    r = LL.living_tick_once(CFG, search_fn=search_real_page, data_dir=env3)
finally:
    LL.read_page = orig_read
check("G4a 跑题页不放行（非 found）", r["explored"][0]["result"] == "irrelevant")
led3 = json.load(open(os.path.join(env3, "living_ledger.json"), encoding="utf-8"))
a3 = [x for x in led3["activities"] if x["state"] == "done"]
check("G4b 该活动未 DONE 且失败留痕", not a3 and any(
    "页面内容与主题不符" in f for x in led3["activities"] for f in x["known_failures"]))

# ── G6 waiting → 新预算日恢复 active 并被推进 ──
env4 = mk_env()
lp = os.path.join(env4, "living_ledger.json")
led4 = LL.ActivityLedger(lp)
act = {"id": "life_test_wait", "topic": f"搞清楚「{CONCEPT}」",
       "concept": CONCEPT, "source_product": "test", "state": "waiting",
       "created": 0, "updated": 0, "progress": [], "methods_tried": [],
       "known_failures": [], "evidence": [], "findings": [], "web_calls": 0,
       "budget": 8, "next_candidates": [], "end_reason": "activity_web_budget_exhausted"}
led4.activities[act["id"]] = act
led4.save()
r = LL.living_tick_once(CFG, search_fn=search_real_page, data_dir=env4)
led4b = json.load(open(lp, encoding="utf-8"))
check("G6 waiting 在新预算日被恢复并推进", r["explored"]
      and led4b["activities"][0]["state"] != "waiting")

# ── G7 分享候选消费 ──
env5 = tempfile.mkdtemp()
lp5 = os.path.join(env5, "living_ledger.json")
led5 = LL.ActivityLedger(lp5)
led5.share_candidates.append({"topic": "测试话题", "activity": "life_x",
                              "evidence": [], "t": 1})
led5.save()
seen = []
r = LL.living_tick_once(CFG, deliver_fn=lambda c: (seen.append(c), False)[1],
                        data_dir=env5)
led5b = json.load(open(lp5, encoding="utf-8"))
check("G7a deliver_fn 收到候选", seen and seen[0]["topic"] == "测试话题")
check("G7b 返回 False → 不标记不丢", led5b["share_candidates"][0].get("delivered") is None)
seen.clear()
r = LL.living_tick_once(CFG, deliver_fn=lambda c: True, data_dir=env5)
led5c = json.load(open(lp5, encoding="utf-8"))
check("G7c 返回 True → 标记 delivered（幂等，重启不重发）",
      led5c["share_candidates"][0]["delivered"] is True)
seen.clear()
LL.living_tick_once(CFG, deliver_fn=lambda c: seen.append(c), data_dir=env5)
check("G7d 已投递候选不再重复投递", not seen)

print(f"\n生活质量闸门：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
