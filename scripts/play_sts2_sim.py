# -*- coding: utf-8 -*-
"""scripts/play_sts2_sim.py — 沙盒批量对局驱动器 v2（2026-10-15）。

用法：python scripts/play_sts2_sim.py [局数=20] [--fresh]
  · 每局：map 路线选择 → 战斗（brain 打分）→ 奖励/休整/宝藏 → 终结；
  · 跨局经验：(局面签名,卡)→均摊终局血差，写 sts2_sim/exp_stats.json；
  · 确定性：seed 递增可复现；--fresh 清空经验（对照冷启动）。
"""
import json
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
from sts2_sim import world as W                    # noqa: E402
from sts2_sim import brain as B                    # noqa: E402

EXP_PATH = os.path.join(_root, "sts2_sim", "exp_stats.json")
MAX_STEPS = 600


def load():
    try:
        with open(EXP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(exp):
    with open(EXP_PATH, "w", encoding="utf-8") as f:
        json.dump(exp, f, ensure_ascii=False, indent=1)


def _make_graph():
    _cog = os.path.join(os.path.dirname(_root), "FAS-Cognitive")
    if _cog not in sys.path:
        sys.path.insert(0, _cog)
    from graph_model import KnowledgeGraph
    from diffusion_engine import DiffusionEngine
    from sts2_sim import knowledge_graph as KG
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    # 17:5x 终层修正：沙盒引擎曾传自造小配置——发射预算/衰减等
    # 全缺省成 0，扩散物理常数与生产不同。改用生产同一份 DEFAULT_CONFIG。
    from config import DEFAULT_CONFIG as _DC
    engine = DiffusionEngine(kg, _DC)
    KG.import_sts_knowledge(kg, json.load(open(os.path.join(
        _root, "sts2_sim", "cards_enemies.json"), encoding="utf-8")))
    return kg, engine


_SHARED_GRAPH = {}


def play_one(seed, exp, graph=False, shared_graph=None,
            general=True, delay=True):
    kg = engine = None
    if graph:
        # 跨局共享的脑（17:1x 关键修正：此前每局新建图，边权进化
        # 随局销毁——扩散决策版永远新手）。shared_graph 传入则复用。
        kg, engine = shared_graph if shared_graph else _make_graph()
    brain = B.Brain(experience=exp, kg=kg, engine=engine)
    brain.max_hp = run.d["player_hp"]
    run = W.Run(seed=seed)
    last_battle = None
    plays = []
    steps = 0
    start_hp = run.d["player_hp"]
    γ_DELAY = 0.6          # 一回合折扣的延迟信用（有界前瞻，非无限归因）
    turn_block = []        # 本回合种下的格挡牌（延迟信用的受体）
    block_val = {}         # 牌名→本回合提供格挡值合计
    while run.status in ("running", "reward", "map") and steps < MAX_STEPS:
        steps += 1
        try:
            if run.status == "running":
                snap = run.snapshot()
                sig = run.battle.situation_signature()
                act = brain.choose(run.actions(), snap) or {"id": "end_turn"}
                hp_before = snap["hp"]
                last_battle = run.battle
                r = run.apply(act["id"])
                if (act.get("id") == "end_turn" and r.get("ok")
                        and turn_block and delay):
                    # 阶段5核心：本回合敌方意图的原始伤害 vs 实际掉血，
                    # 差值=格挡吸收=防御牌的延迟价值（γ 折扣分牌）。
                    sa = r.get("state_after") or {}
                    raw_in = sum((e.get("intent_damage") or 0)
                                 * (e.get("intent_hits") or 1)
                                 for e in snap.get("enemies", [])
                                 if e.get("hp", 0) > 0)
                    lost = max(0, snap.get("hp", 0) - sa.get("hp", 0))
                    # 吸收量 = min(本回合种的格挡总量, 原始伤害-实际掉血)
                    planted = snap.get("block", 0)
                    absorbed = min(planted, max(0, raw_in - lost))
                    if absorbed > 0:
                        share = γ_DELAY * absorbed / max(1, len(turn_block))
                        threat2 = set()
                        for e0 in snap.get("enemies", []):
                            if e0.get("hp", 0) > 0:
                                threat2.update(e0.get("intent_tags") or [])
                        for bc in turn_block:
                            try:
                                KG.update_response_weights(
                                    kg, threat2 or {"防御"}, bc, share)
                            except Exception:      # noqa: BLE001
                                pass
                    turn_block.clear()
                    block_val.clear()
                if r.get("ok") and act.get("card"):
                    plays.append((sig, act["card"], hp_before))
                    if kg is not None:
                        try:
                            from sts2_sim import knowledge_graph as KG
                            threat = set()
                            for e in snap["enemies"]:
                                if e.get("hp", 0) > 0:
                                    threat.update(e.get("intent_tags") or [])
                            sa = r["state_after"]
                            my = sa.get("hp", hp_before) - hp_before
                            fb = sum(e0["hp"] for e0 in snap["enemies"])
                            fa = sum(e0["hp"] for e0 in sa["enemies"])
                            kills = sum(
                                1 for x, y in zip(snap["enemies"],
                                                  sa["enemies"])
                                if x["hp"] > 0 >= y["hp"])
                            KG.update_response_weights(
                                kg, threat, act["card"],
                                my + 0.8 * (fb - fa) + 12 * kills)
                            blk_after = sa.get("block", 0)
                            blk_gain = max(0, blk_after - snap.get(
                                "block", 0))
                            if blk_gain > 0:
                                turn_block.append(act["card"])
                                block_val[act["card"]] = (
                                    block_val.get(act["card"], 0)
                                    + blk_gain)
                        except Exception:          # noqa: BLE001
                            pass
            elif run.status == "reward":
                pick = brain.choose_reward(run.rewards, exp, run.snapshot())
                run.apply(f"pick:{pick}" if pick else "skip")
            elif run.status == "map":
                rts = run.actions()
                if not rts:
                    break               # 无可达路线=地图尽头（防死循环兜底）
                route = brain.choose_route(
                    rts, run.hp, max_hp=run.d["player_hp"],
                    deck_n=len(run.deck))
                run.apply(route["id"] if route else "route:0")
        except Exception as e:                    # noqa: BLE001
            return f"crash:{type(e).__name__}:{str(e)[:40]}", len(plays), steps
    outcome = (run.status if run.status in ("victory", "dead")
               else "stuck")
    if graph:
        try:
            from sts2_sim import knowledge_graph as KG
            KG.write_battle_memory(kg, engine, last_battle, run,
                                   outcome == "victory")
            _SHARED_GRAPH["kg"], _SHARED_GRAPH["eng"] = kg, engine
        except Exception:                       # noqa: BLE001
            pass
    delta = run.hp - start_hp if outcome != "dead" else -start_hp
    per = delta / max(1, len(plays))
    for sig, card, _hb in plays:
        row = exp.setdefault(sig, {}).setdefault(
            card, {"plays": 0, "hp_delta_sum": 0.0})
        row["plays"] += 1
        row["hp_delta_sum"] = round(row["hp_delta_sum"] + per, 2)
    return outcome, len(plays), steps


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith(
        "-") else 20
    if "--fresh" in sys.argv and os.path.exists(EXP_PATH):
        os.remove(EXP_PATH)
    exp = load()
    res = {}
    win_first = win_last = 0
    shared = _make_graph() if "--graph" in sys.argv else None
    for i in range(n):
        out, _p, _s = play_one(1000 + i, exp,
                               graph=shared is not None,
                               shared_graph=shared,
                               general="--no-general" not in sys.argv,
                               delay="--no-delay" not in sys.argv)
        if shared and n >= 8:
            half = n // 4
            if i < half and out == "victory":
                win_first += 1
            if i >= n - half and out == "victory":
                win_last += 1
        key = out if out in ("victory", "dead") else (
            "crash" if str(out).startswith("crash") else "stuck")
        res[key] = res.get(key, 0) + 1
        if key == "crash":
            print("  crash 详情:", out)
    save(exp)
    win = res.get("victory", 0)
    lose = res.get("dead", 0)
    if shared and n >= 8:
        h = n // 4
        print(f"学习曲线：前{h}局胜率 {100.0*win_first/h:.0f}% → "
              f"后{h}局 {100.0*win_last/h:.0f}%（同脑跨局进化）")
    print(f"沙盒 {n} 局：通关 {win} | 阵亡 {lose}"
          f" | 卡住 {res.get('stuck', 0)} | 崩溃 {res.get('crash', 0)}"
          + (f" | 胜率 {100.0 * win / max(1, win + lose):.0f}%"
             if win + lose else ""))


if __name__ == "__main__":
    main()
