# -*- coding: utf-8 -*-
"""真实游戏只读演练（2026-10-15）：拉真实 /state → 映射沙盒形状 →
图一元决策 → 打印建议。绝不 POST，不碰用户的游戏。"""
import sys
import json
import urllib.request

sys.path.insert(0, ".")
sys.path.insert(0, "../FAS-Cognitive")
from graph_model import KnowledgeGraph                                # noqa
from diffusion_engine import DiffusionEngine                          # noqa
from sts2_sim import kb, card_parser as CP                            # noqa
import config as CF                                                   # noqa

BASE = "http://127.0.0.1:8080"


def get_state():
    req = urllib.request.Request(BASE + "/state",
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))["data"]


d = get_state()
c = d.get("combat") or {}
p = c.get("player") or {}
if not d.get("in_combat"):
    print("当前不在战斗（screen=%s），演练需要一个战斗中的局面" % d.get("screen"))
    sys.exit(0)

# ── 真实形状 → 沙盒 snap 映射（对账：逐字段来源注释）──
_INTENT_TAG = {"Attack": "攻击", "Buff": "强化", "Debuff": "削弱",
               "Defend": "防御", "Escape": "移动"}
enemies = []
for e in c.get("enemies") or []:
    if not e.get("is_alive"):
        continue
    ints = e.get("intents") or []
    dmg = max([int(i.get("total_damage") or 0) for i in ints] or [0])
    hits = max([int(i.get("hits") or 1) for i in ints] or [1])
    kinds = [i.get("intent_type") for i in ints if i.get("intent_type")]
    tags = sorted({_INTENT_TAG.get(k, k) for k in kinds})
    powers = {x.get("name"): x.get("stacks") or 1
              for x in (e.get("powers") or [])}
    enemies.append({"name": e.get("name"), "hp": e.get("current_hp"),
                    "block": e.get("block") or 0,
                    "status": {"脆弱": 1} if "脆弱" in powers else {},
                    "intent": ints[0]["intent_type"] if ints else None,
                    "intent_tags": tags, "intent_damage": dmg,
                    "intent_hits": hits})

hand, idx, fx_table = [], {}, {}
for h in (c.get("hand") or []):
    nm = h.get("name") or "?"
    text = h.get("resolved_rules_text") or ""
    parsed = CP.parse(nm, text, cost=h.get("energy_cost") or 0)
    eff = {"damage": 0, "hits": 1, "block": 0, "hp_cost": 0}
    for m in parsed.get("effects") or []:
        mech = m.get("mechanic") or ""
        prm = m.get("params") or {}
        if mech == "M.attack_damage" and prm.get("damage"):
            if prm["damage"] > eff["damage"]:
                eff["damage"] = prm["damage"]
                eff["hits"] = prm.get("hits", 1)
        elif mech == "M.block" and prm.get("block"):
            eff["block"] += prm["block"]
    key = "%s#%d" % (nm, h["index"])     # 重名卡按手牌位区分
    hand.append(nm)
    idx[key] = eff
    fx_table[key] = (h["index"], text, parsed)

kg = KnowledgeGraph()
kg.save = lambda *a, **k: None
cfgd = dict(CF.DEFAULT_CONFIG)
cfgd["diffusion_mode"] = "cascade"
eng = DiffusionEngine(kg, cfgd)
kb.import_kb(kg)
kb.link_to_general(kg)
kb.import_powers(kg)

energy = int(p.get("energy") or 0)
stars = int(p.get("stars") or 0)
acts = []
for h in (c.get("hand") or []):
    key = "%s#%d" % (h["name"], h["index"])
    cost_e = int(h.get("energy_cost") or 0)
    cost_s = int(h.get("star_cost") or 0)
    if cost_e <= energy:
        acts.append({"id": "play_%d" % h["index"], "card": key,
                     "cost": cost_e})

snap = {"hp": p.get("current_hp"), "block": p.get("block") or 0,
        "energy": energy, "max_hp": p.get("max_hp") or 75,
        "hand": hand, "hand_idx": [h["index"] for h in (c.get("hand") or [])],
        "status": {x.get("name"): x.get("stacks") or 1
                   for x in (p.get("powers") or [])},
        "enemies": enemies, "turn": d.get("turn"), "stars": stars}

print("══ 真实局面 ══")
print("hp %s/%s 甲 %s 能 %s 星 %s | 敌方: %s" % (
    snap["hp"], snap["max_hp"], snap["block"], energy, stars,
    "; ".join("%s %s血 意图%s×%s(%s)" % (
        e["name"], e["hp"], e["intent"], e["intent_hits"],
        "/".join(e["intent_tags"])) for e in enemies)))
print("手牌实时解析：")
for key, (i, text, parsed) in fx_table.items():
    mechs = [m["mechanic"].replace("M.", "") for m in parsed.get("effects")
             or []]
    print("  [%d] %s｜%s｜解出: %s｜置信 %s" % (
        i, key.split("#")[0], text[:42] or "无文本",
        ",".join(mechs) or "无语义", parsed.get("confidence")))

best, tr = kb.decide_graph(kg, eng, snap, acts, idx)
print("══ 图一元建议（不执行）══")
for o in sorted(tr["outcomes"], key=lambda x: -x["activation"]):
    who = o["action"].replace("play_", "手牌位")
    print("   %s → %.2f" % (who, o["activation"]))
if best is None:
    print("   结论：结束回合")
else:
    nm = best["card"].split("#")[0]
    print("   结论：出 [%s] %s（预计伤害 %s，击杀 %s）" % (
        best["card"].split("#")[1], nm,
        (tr["preds"].get(best["id"]) or {}).get("伤害"),
        (tr["preds"].get(best["id"]) or {}).get("击杀")))
print("对账缺口（沙盒未建模的真实概念）：星能(stars)不建模——陨星"
      "这类星费卡按能量 0 免费处理，真实成本被低估；重名卡按手牌位区分"
      "（沙盒按卡名全局归一）。")
