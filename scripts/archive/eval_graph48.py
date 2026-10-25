# -*- coding: utf-8 -*-
"""图一元大脑 48 局真实难度评测（2026-10-15）。

三处学习断路的总修复验证：
  1 预测同源：观察用决策时 preds，不用名义伤害（护甲中毒修复）；
  2 场清零：级联无衰减 → 每拍自包含（共振积欠修复，decide_graph 内置）；
  3 经验边接线：situation_seed 点亮意图标签 → 标签-针对->Card 的
    response 边真正进图（赢了加固 / 输了 -3.0 扣分，用户指正）。
"""
import sys
import os
import json
import statistics as st

sys.path.insert(0, ".")
sys.path.insert(0, "../FAS-Cognitive")
from graph_model import KnowledgeGraph                                # noqa
from diffusion_engine import DiffusionEngine                          # noqa
from sts2_sim import kb, card_parser as CP, bridge as BR              # noqa
from sts2_sim import knowledge_graph as KG                            # noqa
import config as CF                                                   # noqa

data = json.load(open("sts2_sim/cards_enemies.json", encoding="utf-8"))
kg = KnowledgeGraph()
kg.save = lambda *a, **k: None
cfgd = dict(CF.DEFAULT_CONFIG)
cfgd["diffusion_mode"] = "cascade"
eng = DiffusionEngine(kg, cfgd)
kb.import_kb(kg)
kb.link_to_general(kg)
kb.import_powers(kg)

GAMMA = 0.6


def card_text(c):
    outs = []
    for fx in c["fx"]:
        o = fx["op"]
        if o == "damage":
            outs.append(f"造成 {fx['n']} 点伤害" +
                        (f" {fx['hits']} 次" if fx.get("hits") else ""))
        elif o == "damage_all":
            outs.append(f"对所有敌人造成 {fx['n']} 点伤害")
        elif o == "block":
            outs.append(f"获得 {fx['n']} 点护甲")
        elif o == "self_buff":
            outs.append(f"获得 {fx['n']} 点{fx['key']}")
        elif o == "debuff":
            outs.append(f"施加 {fx['n']} 层{fx['key']}")
        elif o == "draw":
            outs.append(f"抽 {fx['n']} 张")
        elif o == "hp_loss":
            outs.append(f"失去 {fx['n']} 点生命")
        elif o == "power":
            outs.append(f"获得 {fx['n']} 点能力")
    return "，".join(x for x in outs if x)


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


def play(seed):
    b = BR.MockBridge(seed=seed)
    steps = 0
    used = []
    played = []            # (threat_tags, card_name) 败局反灌用
    turn_block = []        # 延迟格挡分账
    while steps < 600:
        steps += 1
        s0 = b.run.status
        if s0 == "running":
            snap = b.snapshot()
            threat = set()
            for e0 in snap["enemies"]:
                if e0.get("hp", 0) > 0:
                    threat.update(e0.get("intent_tags") or [])
            acts = [dict(a, cost=data["cards"][a["card"]]["cost"])
                    for a in b.actions() if a.get("card")]
            best, tr = kb.decide_graph(kg, eng, snap, acts, idx)
            if best is None or best.get("id") == "end_turn" or \
                    not best.get("card"):
                sa = None
                hb = snap["hp"]
                raw = sum((e0.get("intent_damage") or 0) *
                          int(e0.get("intent_hits") or 1)
                          for e0 in snap["enemies"] if e0.get("hp", 0) > 0)
                r = b.apply("end_turn")
                sa = (r.get("state_after") or {}) if r.get("ok") else {}
                if turn_block and sa:
                    lost = max(0, hb - int(sa.get("hp") or hb))
                    absorbed = min(snap.get("block", 0), max(0, raw - lost))
                    if absorbed > 0:
                        share = GAMMA * absorbed / max(1, len(turn_block))
                        for bc in turn_block:
                            KG.update_response_weights(
                                kg, threat or {"防御"}, f"Card:{bc}", share)
                turn_block.clear()
                continue
            hb = snap["hp"]
            pred = (tr.get("preds") or {}).get(best["id"], {})
            r = b.apply(best["id"])
            if not r.get("ok"):
                continue
            sa = r.get("state_after") or {}
            dealt = sum(x0["hp"] for x0 in snap["enemies"]) - \
                sum(x0["hp"] for x0 in sa.get("enemies", []))
            kill = any(x["hp"] > 0 >= y["hp"] for x, y in
                       zip(snap["enemies"], sa.get("enemies", [])))
            kb.observe_outcome(kg, f"Card:{best['card']}",
                               {"伤害": pred.get("伤害", dealt)},
                               {"dealt": dealt, "kill": kill})
            credit = (sa.get("hp", hb) - hb) + 0.8 * dealt + 12 * kill
            KG.update_response_weights(kg, threat, f"Card:{best['card']}",
                                       credit)
            used.append(best["card"])
            played.append((sorted(threat), f"Card:{best['card']}"))
            gained = max(0, int(sa.get("block") or 0) -
                         int(snap.get("block") or 0))
            if gained > 0:
                turn_block.append(best["card"])
        elif s0 == "reward":
            pick = max(b.run.rewards, key=lambda c: idx[c]["damage"],
                       default=None)
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
            b.apply(sorted(rts, key=keyf)[0]["id"])
        else:
            break
    win = b.run.status == "victory"
    if not win:
        # 用户指正 2026-10-15：打输了要扣权重——结局反灌，
        # 败局每手牌按其局面固定负 credit，压制"打得热闹最后死了"。
        for sig_list, card_id in played:
            KG.update_response_weights(kg, sig_list or ["无"], card_id,
                                       -3.0)
    return win, b.run.floor


wins = []
for i in range(48):
    w, fl = play(7000 + i)
    wins.append(1 if w else 0)
    print(f"局 {i + 1:2d} 层 {fl:2d} {'胜' if w else '负'}", flush=True)

resp = [float(e.weight) for e in kg.edges
        if isinstance(e.extra_attrs, dict)
        and e.extra_attrs.get("kind") == "response"]
cvals = [float((n.extra_attrs or {}).get("calib") or 0.7)
         for n in kg.nodes.values()
         if str((n.extra_attrs or {}).get("type") or "") == "card_instance"]
print(f"图一元 48 局（三修复齐上）：通关 {sum(wins)}/48 = "
      f"{100 * sum(wins) / 48:.0f}%")
print(f"学习曲线：前16胜 {sum(wins[0:16])} → 中16胜 {sum(wins[16:32])} → "
      f"后16胜 {sum(wins[32:48])}")
if resp:
    print(f"经验边 {len(resp)} 条：中位权 {st.median(resp):.2f} "
          f"上限饱和 {sum(1 for v in resp if v >= 1.99)} 条 "
          f"地板 {sum(1 for v in resp if v <= 0.06)} 条")
print(f"卡校准分中位 {st.median(cvals):.2f}（中毒版收在 0.30）")
