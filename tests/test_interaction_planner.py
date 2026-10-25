# tests/test_interaction_planner.py — 交流目标闭环确定性测试（脚本式，零 LLM）
# 十项对应任务书 Phase-4 验证条款。运行：python tests/test_interaction_planner.py
# 退出码 0=全过。离线小图，无真实图谱/网络/LLM。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import interaction_planner as ip                                # noqa: E402
from graph_model import KnowledgeGraph, Node, Edge              # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


CFG = {"interaction_planner": {"enabled": True,
                               "advance_min_interval_s": 60.0,
                               "expire_after_s": 3600.0,
                               "strategy_retry_limit": 2,
                               "pending_grace_turns": 2}}
CFG_OFF = {}   # 缺节=默认关


def fresh_kg():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self", label="self", graph_space="self"))
    for t in ("画展", "猫", "新游戏", "爬山"):
        kg.add_node(Node(id=t, label="declarative-semantic",
                         graph_space="semantic"))
    return kg


def dd_respond():
    return {"decision": "respond", "desire": 0.7, "constraints": [],
            "factors": {}, "tendencies": [],
            "exploration": {"candidates": [], "selected": None, "target": None}}


def parsed_of(*nodes):
    return {"nodes": [{"id": n} for n in nodes], "edges": [],
            "dialogue_act": "information_statement"}


NOW0 = 1_000_000.0

# ═══ 1 无活跃目标：自然回应当前消息（dd 不被改动）═══
print("\n── 1 无活跃目标──")
kg = fresh_kg()
dd = dd_respond()
out, tele = ip.arbitrate(kg, dd, parsed_of("猫"), config=CFG, now=NOW0)
check("1 无目标时 dd 对象恒等且 constraints 不变",
      out is dd and tele["status"] == "no_advance_needed"
      and dd["constraints"] == [])

# ═══ 2 已有目标不逐轮重复推进（冷却闸门）═══
print("\n── 2 重复跟进防御──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
p = parsed_of("画展")
_, t1 = ip.arbitrate(kg, dd_respond(), p, config=CFG, now=NOW0)
check("2a 首次满足可观察条件时提议", t1["status"] == "proposed")
_, t2 = ip.arbitrate(kg, dd_respond(), p, config=CFG, now=NOW0 + 1)
check("2b 冷却期内不再提议（同目标不逐轮推进）",
      t2["status"] == "no_advance_needed")
# 在飞 pending 先结算（两轮无反馈 → unanswered），闸门释放
ip.observe_turn(kg, parsed=p, fb=None, config=CFG, now=NOW0 + 2)
ip.observe_turn(kg, parsed=p, fb=None, config=CFG, now=NOW0 + 3)
_, t2d = ip.arbitrate(kg, dd_respond(), p, config=CFG, now=NOW0 + 4)
check("2b2 pending 结算但冷却未过 → 仍不推进",
      t2d["status"] == "no_advance_needed")
_, t3 = ip.arbitrate(kg, dd_respond(), p, config=CFG, now=NOW0 + 3600)
check("2c 冷却过后可再提议", t3["status"] == "proposed")

# ═══ 3 目标节点再显著也不推进（判定不读激活）═══
print("\n── 3 显著≠行动──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
kg.nodes[gid].activation = 4.9          # 人为高激活
_, tele = ip.arbitrate(kg, dd_respond(), parsed_of("猫"),
                       config=CFG, now=NOW0 + 7200)
check("3 高激活+话题未出现 → 不推进、不伪造",
      tele["status"] == "no_advance_needed" and tele["proposed"] is None)

# ═══ 4 用户转换话题：先响应当前话题，旧目标不强塞 ═══
print("\n── 4 话题转换──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
kg.nodes[gid].activation = 3.0
dd = dd_respond()
_, tele = ip.arbitrate(kg, dd, parsed_of("新游戏"), config=CFG,
                       now=NOW0 + 7200)
check("4 用户谈新话题时旧目标不进 constraints，且不因此判负",
      tele["proposed"] is None and
      ip.list_goals(kg)[0]["ig"]["state"] == "active" and
      not ip.list_goals(kg)[0]["ig"]["outcomes"])

# ═══ 5 明确纠正/负反馈：证据入账；连续负向才 suspended（单次不放弃）═══
print("\n── 5 负反馈落账──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
p = parsed_of("画展")
ip.arbitrate(kg, dd_respond(), p, config=CFG, now=NOW0)
tel = ip.observe_turn(kg, parsed=p,
                      fb={"legacy": "negative"}, config=CFG, now=NOW0 + 5)
g = ip.list_goals(kg)[0]["ig"]
check("5a 单次负反馈：declined 入账，目标不放弃（仍 active）",
      g["outcomes"][-1]["outcome"] == "declined" and g["state"] == "active")
ip.arbitrate(kg, dd_respond(), p, config=CFG, now=NOW0 + 400)
tel = ip.observe_turn(kg, parsed=p, fb={"legacy": "negative"},
                      config=CFG, now=NOW0 + 405)
g = ip.list_goals(kg, states=("active", "suspended"))[0]["ig"]
check("5b 第二次 declined → suspended 且策略进排除（不删除）",
      g["state"] == "suspended")
check("5c suspended 后不再被提议",
      ip.arbitrate(kg, dd_respond(), p, config=CFG,
                   now=NOW0 + 900)[1]["proposed"] is None)

# ═══ 6 信息不足：不伪造情绪/意图（模糊=保持不确定）═══
print("\n── 6 模糊信号──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
ip.arbitrate(kg, dd_respond(), parsed_of("画展"), config=CFG, now=NOW0)
tel = ip.observe_turn(kg, parsed=parsed_of("画展"), fb=None,
                      config=CFG, now=NOW0 + 1)
g = ip.list_goals(kg)[0]["ig"]
check("6a 无反馈首轮：保持不确定（pending 未强制落账）",
      isinstance(g["pending"], dict) and not g["outcomes"])
# 请托未带来≠完成；用户话短也不得标 declined
check("6b 无推断性终态", g["state"] == "active")

# ═══ 7 跨轮保留 + 允许放弃/到期（重启后节点仍在）═══
print("\n── 7 跨轮与到期──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
kg2 = kg                     # 同进程模拟"跨轮"：直接换时间再仲裁/观察
check("7a 目标作为图谱节点跨轮保留",
      len(ip.list_goals(kg2)) == 1)
ip.observe_turn(kg2, parsed=parsed_of("猫"), fb=None, config=CFG,
                now=NOW0 + 100000)
states = [g["ig"]["state"] for g in ip.list_goals(kg2, states=("active",))]
check("7b 超期未推进 → expired（无活跃遗留）", states == [])
gone = ip.list_goals(kg2, states=("expired",))
check("7c 终态留痕不删节点", len(gone) == 1)

# ═══ 8 无需推进时不为完成计划而提问（沉默不可推翻）═══
print("\n── 8 沉默与零推进──")
kg = fresh_kg()
ip.create_goal(kg, desc="记得问画展", topic="画展",
               evidence="explicit_commitment", config=CFG, now=NOW0)
dd_sil = {"decision": "silence", "desire": 0.1, "constraints": [],
          "factors": {}}
out, tele = ip.arbitrate(kg, dd_sil, parsed_of("画展"), config=CFG,
                         now=NOW0 + 7200)
check("8a 沉默裁决原样返回（话题在场也不注入姿态）",
      out is dd_sil and tele["status"] == "respects_silence")
_, tele = ip.arbitrate(kg, dd_respond(), parsed_of("爬山"), config=CFG,
                       now=NOW0 + 7200)
check("8b 话题不在场 → 不推进也不提问（no_advance_needed）",
      tele["status"] == "no_advance_needed")

# ═══ 9 策略耗尽后不机械重试（exclude 防复发）═══
print("\n── 9 策略调整──")
kg = fresh_kg()
gid = ip.create_goal(kg, desc="记得问画展", topic="画展",
                     evidence="explicit_commitment", config=CFG, now=NOW0)
p = parsed_of("画展")
# 两轮 declined 触发 suspended（9 用另一目标走 strategy 排除路径）
ip.create_goal(kg, desc="跟进猫", topic="猫",
               evidence="explicit_commitment", config=CFG, now=NOW0)
# 手工把第一个目标的策略全部标耗尽，验证无提议而非死循环重试
g = ip.list_goals(kg, states=("active",))[0]
g["ig"]["outcomes"] = [{"ts": NOW0, "strategy": "light_follow_up",
                        "outcome": "declined"},
                       {"ts": NOW0, "strategy": "offer_help",
                        "outcome": "declined"}]
g["ig"]["excluded_strategies"] = ["light_follow_up", "offer_help"]
ip._store(g["node"], g["ig"])
_, tele = ip.arbitrate(kg, dd_respond(),
                       parsed_of(g["ig"]["topic"]), config=CFG,
                       now=NOW0 + 3600)
check("9 策略全部排除后不重试（允许'无需推进'结论）",
      tele["proposed"] is None)

# ═══ 10 关闭态：三入口零触碰，dd 恒等 ═══
print("\n── 10 关闭态回归──")
kg = fresh_kg()
dd = dd_respond()
out, tele = ip.arbitrate(kg, dd, parsed_of("画展"), config=CFG_OFF)
check("10a arbitrate 关闭恒等", out is dd and tele["status"] == "disabled")
t = ip.observe_turn(kg, parsed=parsed_of("画展"), fb={"legacy": "positive"},
                    config=CFG_OFF)
check("10b observe_turn 关闭空转", t == [])
gid = ip.try_create_from_turn(kg, text="记得明天问我画展的事",
                              parsed=parsed_of("画展"), config=CFG_OFF)
check("10c 关闭时零建目标", gid == "" and len(kg.nodes) == 5)
# 显式开启但无请托句：不建（隐式不升级）
kg = fresh_kg()
gid = ip.try_create_from_turn(kg, text="我今天去了趟超市",
                              parsed=parsed_of("猫"), config=CFG,
                              now=NOW0)
check("10d 普通消息不自动生成目标", gid == "")
gid = ip.try_create_from_turn(kg, text="记得明天问我画展开幕的事",
                              parsed=parsed_of("画展"), config=CFG,
                              now=NOW0)
check("10e 显式请托才建目标", gid != "" and len(ip.list_goals(kg)) == 1)

print("\n" + "=" * 60)
if FAILURES:
    print(f"✗ {len(FAILURES)} 项失败: {FAILURES}")
else:
    print("交流目标闭环确定性测试全部通过（10 组）")
print("=" * 60)
sys.exit(1 if FAILURES else 0)
