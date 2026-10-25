# scripts/ab_interaction_planner.py — A/B 离线对照（结构行为回放，零 LLM）
# ============================================================================
# 环境身份声明：本对照在确定性脚本回放上度量**结构控制行为**（谁在何轮被
# 允许"提议推进"），不产生自然语言、不接真实 LLM。因此这里的差异只证明
# 控制闸门的作用，不得表述为"陪伴更自然/更聪明"（那需要真实 LLM + 盲评）。
#
# 三臂（每臂在同一场景序列上跑，只换"提议推进"的决策策略）：
#   Naive  = 无闸门参照（话题一出现就推进，忽略冷却/满足/负反馈/沉默）——
#            用来暴露已知失败模式（重复跟进、把长期目标当当前行动、被拒仍追问）。
#   B      = interaction_planner 全闸门（本机制）。
#   A      = 现有陪伴层：无结构化跨轮请托记忆 → 机制层"提议"恒为 0。
#            这是"没有这个能力"的定义性事实，**不是质量优势**，如实标注。
# ============================================================================
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import interaction_planner as ip                       # noqa: E402
from graph_model import KnowledgeGraph, Node            # noqa: E402

CFG_B = {"interaction_planner": {"enabled": True,
                                 "advance_min_interval_s": 3600.0,
                                 "expire_after_s": 86400.0,
                                 "strategy_retry_limit": 2,
                                 "pending_grace_turns": 2}}
TOPIC = "画展"


def fresh_kg():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self", label="self", graph_space="self"))
    kg.add_node(Node(id=TOPIC, label="declarative-semantic",
                     graph_space="semantic"))
    kg.add_node(Node(id="猫", label="declarative-semantic",
                      graph_space="semantic"))
    return kg


def dd(silence=False):
    return {"decision": "silence" if silence else "respond",
            "desire": 0.1 if silence else 0.7, "constraints": [],
            "factors": {}, "tendencies": [],
            "exploration": {"candidates": [], "selected": None,
                            "target": None}}


def parsed_of(*ns):
    return {"nodes": [{"id": x} for x in ns], "edges": []}


# ── 场景：每轮 (text, topics_in_turn, fb_legacy, silence) ──────────────
SCENARIOS = {
    # 请托后话题连续复现（考察重复跟进）
    "话题连续复现": [("记得明天问我看画展的事", (TOPIC,), None, False)] +
                 [(f"又聊到{TOPIC}", (TOPIC,), "positive", False)
                  for _ in range(4)],
    # 用户两次明确拒绝后再提起（考察被拒仍追问 / 单次不放弃）
    "负反馈两次": [("记得明天问我看画展的事", (TOPIC,), None, False),
                ("别老提画展了", (TOPIC,), "negative", False),
                ("真的不想聊画展", (TOPIC,), "negative", False),
                ("还是说说画展吧", (TOPIC,), "positive", False),
                ("画展", (TOPIC,), "positive", False)],
    # 话题出现但系统本轮裁决沉默（考察沉默不可推翻）
    "话题在场但沉默": [("记得明天问我看画展的事", (TOPIC,), None, False),
                  ("（系统在忙，未回应）", (TOPIC,), None, True)],
    # 用户转到别的话题（考察旧目标不被强插）
    "转向别话题": [("记得明天问我看画展的事", (TOPIC,), None, False),
                ("聊聊我的猫", ("猫",), "positive", False),
                ("我的猫今天特别粘人", ("猫",), "positive", False)],
}


def run_naive(kg, turns):
    """无闸门参照：话题在场且非首句就提议，不看任何历史/反馈/沉默。"""
    events = []
    for i, (text, topics, fb, sil) in enumerate(turns):
        if i == 0:
            continue
        if TOPIC in topics:                       # Naive 无视 sil
            events.append({"turn": i, "reason": "topic_present",
                           "silence": sil})
    return events


def run_B(kg, turns):
    """轮内顺序与生产接线一致：轮首 observe → 轮中 arbitrate →
    轮尾 create（当轮新建的目标下一轮才可被推进）。"""
    kg = fresh_kg()
    events = []
    now = 1000.0
    for i, (text, topics, fb, sil) in enumerate(turns):
        p = parsed_of(*topics)
        _fb = {"legacy": fb} if fb else None
        ip.observe_turn(kg, parsed=p, fb=_fb, config=CFG_B, now=now)
        if not sil:
            _dd, tele = ip.arbitrate(kg, dd(), p, config=CFG_B, now=now)
            if tele.get("proposed"):
                events.append({"turn": i, "reason": "gated", "silence": sil})
        ip.try_create_from_turn(kg, text=text, parsed=p, config=CFG_B, now=now)
        now += 120.0
    final = {g["ig"]["topic"]: g["ig"]["state"] for g in ip.list_goals(
        kg, states=("active", "suspended", "satisfied", "expired"))}
    return events, final


def run_A(kg, turns):
    # 现有层：无结构化请托记忆，机制层提议恒为 0（能力缺席，非质量优势）
    return []


def metrics(name, events):
    prop = len(events)
    repeat = sum(1 for e in events if e.get("turn", 0) > 0 and
                 any(p.get("turn") == e["turn"] - 1 for p in events))
    forced_silence = sum(1 for e in events if e.get("silence"))
    return {"scenario": name, "proposals": prop,
            "repeat_adjacent": repeat, "propose_during_silence": forced_silence}


rows = []
for name, turns in SCENARIOS.items():
    e_b, final_b = run_B(fresh_kg(), turns)
    mn = metrics(name, run_naive(fresh_kg(), turns))
    mb = metrics(name, e_b)
    ma = metrics(name, run_A(fresh_kg(), turns))
    rows.append({"scenario": name, "A": ma, "Naive": mn, "B": mb,
                 "B_final_states": final_b})
    print(f"场景「{name}」")
    print(f"  Naive 无闸门 : 提议={mn['proposals']} "
          f"连续重复={mn['repeat_adjacent']} 沉默中仍提议={mn['propose_during_silence']}")
    print(f"  B    全闸门  : 提议={mb['proposals']} "
          f"连续重复={mb['repeat_adjacent']} 沉默中仍提议={mb['propose_during_silence']}")
    print(f"  A    现有层  : 提议={ma['proposals']}（无结构化请托记忆，能力缺席非质量优势）")
    print()

out_path = os.path.join(os.path.dirname(__file__), "_ab_interaction_result.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)

print("=== 判读 ===")
for r in rows:
    diff = r["Naive"]["proposals"] - r["B"]["proposals"]
    print(f"{r['scenario']}: 闸门相对无闸门少 {diff} 次提议；"
          f"B 沉默中提议={r['B']['propose_during_silence']}（须为0）；"
          f"B 连续重复={r['B']['repeat_adjacent']}（期望0）；"
          f"B 终态={r['B_final_states']}")
print("\n限制：A 臂提议恒 0 是机制缺席的定义性事实，不用于质量对比；自然度"
      "未评估（需真实 LLM+盲评）；Naive 为刻意不设限参照，非现有 LLM 实测行为。")
