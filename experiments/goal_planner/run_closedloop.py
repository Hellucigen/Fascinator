# run_closedloop.py — Phase-4 最小闭环行为实验
# A = 现有基线（反应式 next_step 单步提示派发，生产 obtain 通道离线近似，
#     含 _locally_absent 同款避障）
# B = 目标驱动计划器（goal_planner：计划/闸门/监测/重规划/收束）
# 环境 = SimEnv 确定性测试替身（simenv.py 头注声明；非 Minecraft 真实执行）。
# 配对：同图、同初始库存/方块、同事件脚本；全确定性 n=1/格（小样本，
# 按预注册纪律标注为探索性证据，不做确证性宣称）。
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

from action_system import ActionManager                    # noqa: E402
from self_graph import current_goal                        # noqa: E402
import world_prior as wp                                   # noqa: E402
import goal_planner as gp                                  # noqa: E402
from simenv import SimEnv, build_graph                     # noqa: E402

CFG = {"planner": {"enabled": True}}
OUT = os.path.join(HERE, "campaign_closedloop",
                   "run_" + time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)
MAX_CYCLES = 40
EXPLORE_REASONS = ("no_recipe", "inputs_missing", "tool_missing",
                   "no_table", "no_furnace", "no_fuel", "unknown",
                   "block_not_found", "bench_jam", "no_smelt")


def mk_env(scenario, cond):
    """同场景同初始态（配对）；事件脚本按场景编号确定性给出。"""
    common_blocks = ["oak_log", "birch_log", "iron_ore", "coal_block",
                     "silver_ore"]
    if scenario == "S1_normal":
        return SimEnv(blocks=common_blocks, placed=["furnace",
                                                    "crafting_table"])
    if scenario == "S2_flaky_craft":
        # 第 1 拍后的首个 craft_item 失败一次（台子故障）
        return SimEnv(blocks=common_blocks, placed=["furnace"],
                      fail_at=[(1, "craft_item", None, "bench_jam")])
    if scenario == "S3_env_change":
        # 第 0 拍后橡木消失（计划途中环境变化）→ 应转 birch 备选
        return SimEnv(blocks=common_blocks, placed=["furnace"],
                      blocks_at=[(0, "remove", "oak_log")])
    if scenario == "S4_external_done":
        # 第 1 拍外部送达成品（目标经他途达成）
        return SimEnv(blocks=common_blocks, placed=["furnace"],
                      give_at=[(1, {"oak_planks": 8})])
    if scenario in ("S5_and_missing", "S6_tool_deadend"):
        return SimEnv(blocks=common_blocks, placed=["furnace",
                                                    "crafting_table"])
    raise KeyError(scenario)


def mk_graph(scenario):
    if scenario == "S5_and_missing":
        return build_graph(stick_needs_magic=True)
    if scenario == "S6_tool_deadend":
        g = build_graph(pickaxe_tool=True)
        # 银矿不可采：断白名单边 → 采镐路径死
        g.remove_edges(src="silver_ore", relation="属于")
        return g
    return build_graph(alt_birch=True)


SCENARIOS = {
    "S1_normal": ("oak_planks", 8, "正常两阶段链（采+合成）"),
    "S2_flaky_craft": ("oak_planks", 8, "合成首试失败一次后成功"),
    "S3_env_change": ("oak_planks", 8, "计划途中橡树消失→备选分支"),
    "S4_external_done": ("oak_planks", 8, "中途外部送达=他途达成"),
    "S5_and_missing": ("stick", 4, "AND 前置缺项（stick 需 magic_dust）"),
    "S6_tool_deadend": ("iron_ingot", 1, "工具死链（采铁矿需不可得银镐）"),
}


def drain(am):
    n = 0
    while am.current is not None and n < 6:
        am.tick()
        n += 1


# ── A：反应式基线（生产 obtain 通道离线近似）──────────────────

def run_A(kg, target, env):
    am = ActionManager(embodiment=env, kg=kg)
    absent = set()
    actions = wasted = explores = 0
    achieved = False
    fail_reasons = []
    traj = []
    for cycle in range(MAX_CYCLES):
        env.advance_cycle(cycle)
        step = wp.next_step(kg, target, dict(env.inv), exclude=absent)
        traj.append(dict(env.inv))
        if step.get("done"):
            achieved = True
            break
        act = str(step.get("action") or "")
        if act == "gather":
            blk = str(step.get("block") or step.get("item") or "")
            spec = {"action_type": "gather_resource", "target": blk,
                    "params": {"resource": blk, "quantity": 3},
                    "motivation": "user_goal",
                    "expected_effect": f"采 {blk}"}
        elif act in ("craft", "smelt"):
            item = str(step.get("item") or target)
            spec = {"action_type": "craft_item" if act == "craft"
                    else "smelt_item", "target": item,
                    "params": {"item": item, "count": 1},
                    "motivation": "user_goal",
                    "expected_effect": f"{act} {item}"}
        else:
            explores += 1
            continue
        am.propose(spec, source="experiment")
        actions += 1
        drain(am)
        last = env.history[-1] if env.history else {}
        if last and not last.get("success"):
            r = str(last.get("reason") or "")
            fail_reasons.append(r)
            if r.startswith("block_not_found"):
                absent.add(str(step.get("block") or ""))
            if r in EXPLORE_REASONS:
                wasted += 1
    step = wp.next_step(kg, target, dict(env.inv), exclude=absent)
    achieved = achieved or bool(step.get("done"))
    return {"cond": "A", "achieved": achieved, "actions": actions,
            "wasted": wasted, "explores": explores, "replans": None,
            "goal_state": "n/a(反应式无目标对象)",
            "fail_reasons": fail_reasons, "cycles": len(traj),
            "traj_tail": traj[-3:]}


# ── B：计划器闭环 ──────────────────────────────────────

def run_B(kg, target, count, env):
    am = ActionManager(embodiment=env, kg=kg)
    am.on_settled = lambda a, r, s, n=None: gp.on_settled(
        kg, a, r, s, CFG)
    gp.attach_goal(kg, target, count)
    actions = wasted = 0
    replans = 0
    achieved = terminated = False
    fail_reasons = []
    traj = []
    precond_violations = 0
    for cycle in range(MAX_CYCLES):
        env.advance_cycle(cycle)
        stt = gp.state_view(kg, env.percept())
        t = gp.tick(kg, am, stt, CFG)
        traj.append(dict(env.inv))
        if t.get("revisions"):
            replans = int(t["revisions"])
        if t["status"] == "GOAL_ACHIEVED":
            achieved = True
            break
        if t["status"] in ("NO_FEASIBLE_PLAN", "GOAL_TERMINATED"):
            terminated = True
            break
        if t["status"] == "DISPATCHED":
            actions += 1
            drain(am)
            last = env.history[-1] if env.history else {}
            if last and not last.get("success"):
                r = str(last.get("reason") or "")
                fail_reasons.append(r)
                if r in ("inputs_missing", "tool_missing", "no_table",
                         "no_furnace", "no_fuel", "no_recipe"):
                    precond_violations += 1   # 闸门本应拦住——记录违规
    g = current_goal(kg) or {}
    return {"cond": "B", "achieved": achieved, "actions": actions,
            "wasted": sum(1 for r in fail_reasons
                          if r in EXPLORE_REASONS and r != "block_not_found")
            + 0,
            "explores": None, "replans": replans,
            "precondition_violations": precond_violations,
            "terminated": terminated,
            "goal_state": (g.get("state") if g else
                           "指针已了结(达成或终止)"),
            "fail_reasons": fail_reasons, "cycles": len(traj),
            "traj_tail": traj[-3:]}


def main():
    rows = []
    for name, (target, count, desc) in SCENARIOS.items():
        ra = run_A(mk_graph(name), target, mk_env(name, "A"))
        rb = run_B(mk_graph(name), target, count, mk_env(name, "B"))
        ra["scenario"], rb["scenario"] = name, name
        ra["desc"], rb["desc"] = desc, desc
        rows += [ra, rb]
        print(f"── {name} {desc}")
        for r in (ra, rb):
            print(f"   {r['cond']}: achieved={r['achieved']} "
                  f"actions={r['actions']} wasted={r['wasted']} "
                  f"explores={r.get('explores')} replans={r.get('replans')} "
                  f"cycles={r['cycles']} fails={r['fail_reasons'][:4]}")
    with open(os.path.join(OUT, "closedloop_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("out:", OUT)


if __name__ == "__main__":
    main()
