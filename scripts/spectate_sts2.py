# -*- coding: utf-8 -*-
"""图一元大脑观战模式：一局一打，每回合带解说（2026-10-15）。

用法：python scripts/spectate_sts2.py [种子]
边打边出分：选了什么、为什么（情势种子）、账本激活对比。
"""
import sys
import os
import json

sys.path.insert(0, ".")
sys.path.insert(0, "../FAS-Cognitive")
from graph_model import KnowledgeGraph                                # noqa
from diffusion_engine import DiffusionEngine                          # noqa
from sts2_sim import kb, card_parser as CP, bridge as BR              # noqa
import config as CF                                                   # noqa

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7000
data = json.load(open("sts2_sim/cards_enemies.json", encoding="utf-8"))
kg = KnowledgeGraph()
kg.save = lambda *a, **k: None
cfgd = dict(CF.DEFAULT_CONFIG)
cfgd["diffusion_mode"] = "cascade"
eng = DiffusionEngine(kg, cfgd)
kb.import_kb(kg)
kb.link_to_general(kg)
kb.import_powers(kg)


def card_text(c):
    outs = []
    for fx in c["fx"]:
        o = fx["op"]
        if o == "damage":
            outs.append(f"造成 {fx['n']} 伤害" +
                        (f"×{fx['hits']}" if fx.get("hits") else ""))
        elif o == "damage_all":
            outs.append(f"全体 {fx['n']} 伤害")
        elif o == "block":
            outs.append(f"{fx['n']} 护甲")
        elif o == "self_buff":
            outs.append(f"+{fx['n']} {fx['key']}")
        elif o == "debuff":
            outs.append(f"{fx['n']} 层{fx['key']}")
        elif o == "draw":
            outs.append(f"抽 {fx['n']}")
        elif o == "hp_loss":
            outs.append(f"自伤 {fx['n']}")
        elif o == "power":
            outs.append(f"{fx['n']} 能力")
    return "、".join(x for x in outs if x)


idx = {}
for nm, c in data["cards"].items():
    kb.instantiate_card(kg, CP.parse(nm, card_text(c), cost=c["cost"]), nm)
    e = {"damage": 0, "hits": 1, "block": 0, "hp_cost": 0}
    for fx in c["fx"]:
        if fx["op"] == "damage":
            e["damage"] = max(e["damage"], fx["n"])
            e["hits"] = fx.get("hits", 1)
        elif fx["op"] == "damage_all":
            e["damage"] = max(e["damage"], fx["n"])
        elif fx["op"] == "block":
            e["block"] += fx["n"]
        elif fx["op"] == "hp_loss":
            e["hp_cost"] += fx["n"]
    idx[nm] = e

b = BR.MockBridge(seed=seed)
steps = 0
print(f"══ 观战开始 种子 {seed} ══")
while steps < 600:
    steps += 1
    s0 = b.run.status
    if s0 == "running":
        snap = b.snapshot()
        acts = [dict(a, cost=data["cards"][a["card"]]["cost"])
                for a in b.actions() if a.get("card")]
        best, tr = kb.decide_graph(kg, eng, snap, acts, idx)
        if best is None or not best.get("card"):
            intent = "、".join(f"{e['name']}[{e.get('intent')}×"
                               f"{e.get('intent_hits', 1)}]"
                               for e in snap["enemies"] if e["hp"] > 0)
            print(f"  回合{snap.get('turn', '?')} "
                  f"hp{snap['hp']}甲{snap['block']}能{snap['energy']} "
                  f"| {intent} → 结束回合（无可行/无增益行动）")
            r = b.apply("end_turn")
            continue
        pred = (tr.get("preds") or {}).get(best["id"], {})
        score = {o["action"]: o["activation"] for o in tr["outcomes"]}
        why = "；".join(f"{s['node'].split(':')[-1]}{s['e']}"
                        for s in tr["seeds"][:3])
        hb = snap["hp"]
        r = b.apply(best["id"])
        sa = (r.get("state_after") or {}) if r.get("ok") else {}
        dealt = pred.get("伤害", 0)
        kill = pred.get("击杀", False)
        board = "，".join(
            "%s:%.1f" % (a["card"], score.get(a["id"], 0))
            for a in acts[:5])
        print(f"  回合{snap.get('turn', '?')} hp{snap['hp']}甲{snap['block']}"
              f"能{snap['energy']} → 出「{best['card']}」"
              f"[{board}] 因[{why}]")
        if kill:
            print("      └─ 预计击杀！")
    elif s0 == "reward":
        pick = max(b.run.rewards, key=lambda c: idx[c]["damage"],
                   default=None)
        print(f"  ◆ 层{b.run.floor} 奖励：{b.run.rewards} → 拿「{pick}」")
        b.apply(f"pick:{pick}" if pick else "skip")
    elif s0 == "map":
        rts = b.actions()
        if not rts:
            break

        def keyf(x):
            d = x["desc"]
            if "宝藏" in d:
                return 0
            if "休整" in d and b.run.hp < 40:
                return 0.5
            if "精英" in d:
                return 1 if b.run.hp >= 55 else 3
            return 1.5
        go = sorted(rts, key=keyf)[0]
        print(f"  ▸ 层{b.run.floor + 1} 选路：{go['desc']}")
        b.apply(go["id"])
    elif s0 == "battle_won":
        print(f"  ✔ 打赢 层{b.run.floor}（hp {b.run.hp}）")
        b.apply("continue")
    else:
        break
res = {"victory": "通关", "dead": "阵亡", "running": "步数耗尽"}.get(
    b.run.status, b.run.status)
print(f"══ 结果：{res}，到达 层{b.run.floor}，血量 {b.run.hp} ══")
