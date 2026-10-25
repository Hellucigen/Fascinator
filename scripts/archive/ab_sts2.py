# -*- coding: utf-8 -*-
"""scripts/ab_sts2.py — 双领域消融对照（阶段6，方案先冻结后执行）。

冻结记录（先写死后跑，跑完不改标准）：
  · 条件：A 表驱动 / B 纯图现状（无通用层无延迟）/ C 双域无延迟 / D 双域+延迟
  · 种子 7000-7015 共 16 局/条件（同列表可比）；条件内共享脑跨局进化，
    条件间完全隔离；单遍采集全部指标（不重放——重放脑已变，轨迹不可比）
  · 指标：通关率(Wilson CI)、平均到达层、终局HP、总出牌
  · n=16 为探索性；停止条件：跑完即止。
"""
import sys
import os

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.argv = [sys.argv[0]]
import importlib.util                                  # noqa: E402

spec = importlib.util.spec_from_file_location("ps", os.path.join(
    _root, "scripts", "play_sts2_sim.py"))
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)
from sts2_sim import world as W, brain as B            # noqa: E402
from sts2_sim import knowledge_graph as KG            # noqa: E402

SEEDS = list(range(7000, 7016))
CONDS = {
    "A 表驱动":      dict(graph=False, general=False, delay=False),
    "B 纯图现状":    dict(graph=True,  general=False, delay=False),
    "C 双域无延迟":  dict(graph=True,  general=True,  delay=False),
    "D 双域+延迟":   dict(graph=True,  general=True,  delay=True),
}
GAMMA = 0.6


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def one_game(seed, kg, eng, cfg, exp_stats):
    run = W.Run(seed=seed)
    played = []                       # 本局 [(sig_tokens, card)]（结局反灌用）
    brain = B.Brain(experience={}, kg=kg, engine=eng)
    brain.max_hp = run.d["player_hp"]
    brain.use_general = cfg["general"]
    steps, plays = 0, 0
    turn_block = []
    while run.status in ("running", "reward", "map") and steps < 600:
        steps += 1
        if run.status == "running":
            snap = run.snapshot()
            threat = set()
            for e in snap["enemies"]:
                if e.get("hp", 0) > 0:
                    threat.update(e.get("intent_tags") or [])
            acts = run.actions()
            a = brain.choose(acts, snap)
            if a is None:
                run.apply("end_turn")
                continue
            hb = snap["hp"]
            r = run.apply(a["id"])
            if a.get("card") and r.get("ok"):
                plays += 1
                if kg is not None:
                    sa = r.get("state_after") or {}
                    my = sa.get("hp", hb) - hb
                    fb = sum(e["hp"] for e in snap["enemies"])
                    fa = sum(e["hp"] for e in sa.get("enemies", []))
                    kills = sum(1 for x, y in zip(snap["enemies"],
                                                  sa.get("enemies", []))
                                if x["hp"] > 0 >= y["hp"])
                    KG.update_response_weights(
                        kg, threat, a["card"],
                        my + 0.8 * (fb - fa) + 12 * kills)
                    if max(0, sa.get("block", 0)
                           - snap.get("block", 0)) > 0:
                        turn_block.append(a["card"])
                    played.append((sorted(threat), a["card"]))
            if a["id"] == "end_turn" and turn_block and cfg["delay"]:
                sa = r.get("state_after") or {}
                raw = sum((e.get("intent_damage") or 0)
                          * (e.get("intent_hits") or 1)
                          for e in snap["enemies"] if e.get("hp", 0) > 0)
                lost = max(0, snap.get("hp", 0) - sa.get("hp", 0))
                absorbed = min(snap.get("block", 0), max(0, raw - lost))
                if absorbed > 0:
                    share = GAMMA * absorbed / max(1, len(turn_block))
                    for bc in turn_block:      # 平分给全体本回合格挡牌
                        KG.update_response_weights(
                            kg, threat or {"防御"}, bc, share)
                turn_block.clear()
        elif run.status == "reward":
            pick = brain.choose_reward(run.rewards) if run.rewards else None
            run.apply(f"pick:{pick}" if pick else "skip")
        elif run.status == "map":
            rts = run.actions()
            if not rts:
                break
            run.apply(rts[0]["id"])
    win = run.status == "victory"
    if kg is not None and not win and plays:
        # 结局反灌（2026-10-15 用户指正：输=扣分，过程分不能凌驾结局）：
        # 败局中每手牌按其局面记固定负 credit，压制"打得热闹最后死了"
        # 的伪好牌；胜局不加码（逐手即时归因已给足正证据）。
        for sig_list, card in played:
            try:
                KG.update_response_weights(kg, sig_list or ["无"],
                                           card, -3.0)
            except Exception:
                pass
    return win, run.floor, (run.hp if win else 0), plays


def run_cond(name, cfg):
    shared = ps._make_graph() if cfg["graph"] else None
    if shared and cfg["general"]:
        KG.import_general_knowledge(shared[0])
    wins = floors = hp = plays = 0
    for sd in SEEDS:
        if cfg["graph"]:
            kg, eng = shared
        else:
            kg = eng = None
        w, f, h, p = one_game(sd, kg, eng, cfg, {})
        wins += w; floors += f; hp += h; plays += p
    n = len(SEEDS)
    lo, hi = wilson(wins, n)
    print(f"{name:8s} 通关 {wins:2d}/{n} = {100.0*wins/n:3.0f}% "
          f"CI[{100*lo:2.0f},{100*hi:2.0f}] | 均层 {floors/n:3.1f} "
          f"| 终局HP {hp/n:4.1f} | 出手 {plays/n:4.1f}/局")


print("== 消融对照（种子 7000-7015，n=16/条件，探索性）==")
for nm, cfg in CONDS.items():
    run_cond(nm, cfg)
