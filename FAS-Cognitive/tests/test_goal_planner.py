# test_goal_planner.py — 目标驱动计划器：单元/机制级测试（对应
# PLANNER_AUDIT §7 与任务 §五 Phase-3 的 14 项要求，另加设备/燃料前置）。
# 离线、临时图、真 ActionManager 或 SpyActions；无 LLM、无桥。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 tests/test_goal_planner.py

import os
import sys
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge
from self_graph import bootstrap_self, current_goal
from action_system import ActionManager
import goal_planner as gp

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


CFG_ON = {"planner": {"enabled": True}}


class Spy:
    def __init__(self):
        self.proposed = []

    def propose(self, spec, source=None):
        self.proposed.append(dict(spec))
        return {"started": True}


class Emb:
    """确定性执行替身：poll 按脚本返回 running/failed/done。"""

    def __init__(self):
        self.fail_script = []
        self.busy_once = False

    def execute(self, action):
        return {"success": True, "pending": True,
                "action": action["action_type"]}

    def poll_action(self):
        if self.busy_once:
            self.busy_once = False
            return {"status": "running"}
        if self.fail_script:
            return {"status": "failed", "reason": self.fail_script.pop(0)}
        return {"status": "done", "detail": {"ok": True, "success": True}}

    def raw_state(self):
        return {}

    def skill_catalog(self):
        return []


def goal_node_id(kg):
    """当前目标指针指向的节点（勿用前缀筛选——bootstrap 预置了长期目标）。"""
    from self_graph import current_goal as _cg
    g = _cg(kg) or {}
    if g.get("id"):
        return str(g["id"])
    # 指针已摘除时回退到最近写入过 plan/termination 的 目标 节点
    for nid, n in kg.nodes.items():
        ea = n.extra_attrs or {}
        if "plan" in ea or "termination" in ea or "plan_history" in ea:
            return str(nid)
    return ""


def prov(conf=0.9, verified=True):
    return {"confidence": conf, "knowledge_type": "prior",
            "source": "planner-test", "version_verified": verified}


def mk_world(alt=False, and_case=False, smelt_case=False, kill_oak=False):
    """oak_log(可采) → oak_planks ←(手配)；stick ←2 planks；
    pickaxe ← 3 planks + 2 stick(need table)。
    alt: 加 birch_log 备选配方（未核验低置信，排序靠后）。
    and_case: stick 配方改需 magic_dust（无生产者 → AND 缺项）。
    smelt_case: planks 加 smelt 备选（coal 输入，未核验低置信）。
    kill_oak: 去掉 oak 采集链（只剩孤立配方+高激活目标，测目标≠行动）。
    注意：节点全部先建，边后建（add_edge 端点缺失会静默丢边）。"""
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    bootstrap_self(kg)
    kg.add_node(Node(id="Haru", graph_space="self"))

    def N(i, **kw):
        if kg.get_node(i) is None:
            kg.add_node(Node(id=i, **kw))

    def E(s, r, d, w=0.6, ea=None):
        kg.add_edge(Edge(s, d, r, w, extra_attrs=ea if ea else prov()))

    N("可采资源"); N("Haru")
    N("物品:oak_planks", extra_attrs={"count": 0})
    N("配方:oak_planks:hand:0",
      extra_attrs={"type": "recipe", "kind": "craft", "yield": 1})
    N("oak_log", extra_attrs={"type": "mc_species"})
    N("物品:oak_log", extra_attrs={"count": 0})
    N("物品:stick", extra_attrs={"count": 0})
    N("配方:stick:hand:0",
      extra_attrs={"type": "recipe", "kind": "craft", "yield": 4})
    N("物品:wooden_pickaxe")
    N("配方:wooden_pickaxe:table:0",
      extra_attrs={"type": "recipe", "kind": "craft",
                   "needs_table": True, "yield": 1})
    N("物品:golden_apple", extra_attrs={"count": 0})
    if alt:
        N("birch_log", extra_attrs={"type": "mc_species"})
        N("物品:birch_log", extra_attrs={"count": 0})
        N("配方:oak_planks:birch:0",
          extra_attrs={"type": "recipe", "kind": "craft", "yield": 1})
    if smelt_case:
        N("配方:oak_planks:smelt:0",
          extra_attrs={"type": "recipe", "kind": "smelt",
                       "tool": "furnace", "yield": 1})
        N("coal_block", extra_attrs={"type": "mc_species"})
        N("物品:coal", extra_attrs={"count": 0})
    if and_case:
        N("物品:magic_dust", extra_attrs={"count": 0})  # 无任何生产者

    E("配方:oak_planks:hand:0", "产生", "物品:oak_planks")
    E("配方:oak_planks:hand:0", "需要", "物品:oak_log",
      ea={**prov(), "count": 1})
    if not kill_oak:
        E("oak_log", "属于", "可采资源", 0.8)
        E("oak_log", "掉落", "物品:oak_log")
    if alt:
        E("birch_log", "属于", "可采资源", 0.8,
          ea=prov(conf=0.4, verified=False))
        E("birch_log", "掉落", "物品:birch_log",
          ea=prov(conf=0.4, verified=False))
        E("配方:oak_planks:birch:0", "产生", "物品:oak_planks",
          ea=prov(conf=0.4, verified=False))
        E("配方:oak_planks:birch:0", "需要", "物品:birch_log",
          ea={**prov(conf=0.4, verified=False), "count": 1})
    if smelt_case:
        E("配方:oak_planks:smelt:0", "产生", "物品:oak_planks",
          ea=prov(conf=0.3, verified=False))
        E("配方:oak_planks:smelt:0", "需要", "物品:coal",
          ea={**prov(conf=0.3, verified=False), "count": 1})
        E("coal_block", "属于", "可采资源", 0.8,
          ea=prov(conf=0.3, verified=False))
        E("coal_block", "掉落", "物品:coal",
          ea=prov(conf=0.3, verified=False))
    stick_out = "物品:magic_dust" if and_case else "物品:oak_planks"
    E("配方:stick:hand:0", "产生", "物品:stick")
    E("配方:stick:hand:0", "需要", stick_out, ea={**prov(), "count": 2})
    E("配方:wooden_pickaxe:table:0", "产生", "物品:wooden_pickaxe")
    E("配方:wooden_pickaxe:table:0", "需要", "物品:oak_planks",
      ea={**prov(), "count": 3})
    E("配方:wooden_pickaxe:table:0", "需要", "物品:stick",
      ea={**prov(), "count": 2})
    return kg


def st(inv=None, seen=None):
    return {"inventory": dict(inv or {}), "seen_blocks": set(seen or ()),
            "source": "percept"}


def drain(am, n=4):
    for _ in range(n):
        out = am.tick()
        if out.get("settled") or out.get("reason") in ("idle",):
            break


def wire(kg):
    """真 ActionManager + 计划器结算链（生产接线同款）。"""
    emb = Emb()
    am = ActionManager(embodiment=emb, kg=kg)
    am.on_settled = lambda a, r, s, n=None: gp.on_settled(
        kg, a, r, s, CFG_ON)
    return am, emb


def settle_direct(kg, spy_last_action, success=True, reason=""):
    """Spy 路径手动回执（等价 on_settled）。"""
    gp.on_settled(kg, spy_last_action,
                  {"success": success, "reason": reason}, success, CFG_ON)


def step_of(kg, idx=0, field="status"):
    gid, _ = gp.current_goal_spec(kg)
    plan = kg.nodes[gid].extra_attrs.get("plan")
    return plan["steps"][idx].get(field) if plan and plan["steps"] else None


# ── 1 没有目标时，不生成行动 ─────────────────────────────
kg = mk_world()
spy = Spy()
t = gp.tick(kg, spy, st(), CFG_ON)
check("1 无目标 → NO_GOAL 且零派发", t["status"] == "NO_GOAL"
      and spy.proposed == [], str(t))

# ── 2 目标已达成时，不再派发 ─────────────────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
spy = Spy()
t = gp.tick(kg, spy, st({"oak_planks": 1}), CFG_ON)
check("2 已达成 → GOAL_ACHIEVED 且零派发、指针结束",
      t["status"] == "GOAL_ACHIEVED" and spy.proposed == []
      and current_goal(kg) == {}, str(t))

# ── 3 前置已满足 → 不重复要求 ────────────────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
spy = Spy()
t = gp.tick(kg, spy, st({"oak_log": 1}), CFG_ON)
_gid = goal_node_id(kg)
_kinds = [x["kind"] for x in
          kg.nodes[_gid].extra_attrs["plan"]["steps"]]
check("3 背包已有原料 → 计划只有合成步（不重复采集）",
      t["status"] == "DISPATCHED"
      and spy.proposed[0]["action_type"] == "craft_item"
      and _kinds == ["craft"], str(_kinds))

# ── 4 单步成功 → 监测确认并推进 ──────────────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
am, emb = wire(kg)
t1 = gp.tick(kg, am, st(), CFG_ON)
check("4a 无原料 → 先派发采集步", t1["status"] == "DISPATCHED"
      and am.current and am.current["action_type"] == "gather_resource",
      str(t1))
drain(am)                                        # 执行成功结算
t2 = gp.tick(kg, am, st({"oak_log": 1}), CFG_ON)  # 观测到 +1 oak_log
check("4b 预期效果出现 → 步骤 done 并派发合成",
      t2["status"] == "DISPATCHED" and step_of(kg, 0) == "done"
      and am.current and am.current["action_type"] == "craft_item",
      f"{t2} s0={step_of(kg, 0)}")
drain(am)
t3 = gp.tick(kg, am, st({"oak_planks": 1}), CFG_ON)
check("4c 目标达成 → 计划收束 + 目标结束(achieved)",
      t3["status"] == "GOAL_ACHIEVED" and current_goal(kg) == {}
      and kg.nodes[goal_node_id(kg)].extra_attrs.get(
          "plan_history", [{}])[0].get("outcome") == "achieved", str(t3))
check("4d 达成前证据计数已入账（监测先行）",
      int((kg.nodes["配方:oak_planks:hand:0"].extra_attrs or {}).get(
          "plan_success_count", 0)) >= 1)

# ── 5 行动失败 → 重试留证，超限改计划/终止，不无限重试 ──
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
am, emb = wire(kg)
dispatched = 0
for i in range(3):
    t = gp.tick(kg, am, st(), CFG_ON)
    if t["status"] == "DISPATCHED":
        dispatched += 1
        emb.fail_script = ["no_block_nearby"]
        drain(am)
check("5a 同一步重试 ≤ 3 次后不再原地重试", dispatched == 3,
      str(dispatched))
t = gp.tick(kg, am, st(), CFG_ON)      # 第3败结算处理 → 排除该选项→重规划
check("5b 失败选项被排除、无替代 → NO_FEASIBLE_PLAN 终止",
      t["status"] == "NO_FEASIBLE_PLAN" and current_goal(kg) == {},
      str(t))
gid = goal_node_id(kg)
check("5c 终止原因可观测",
      str(kg.nodes[gid].extra_attrs.get("termination", ""))
      .startswith("NO_FEASIBLE_PLAN"),
      str(kg.nodes[gid].extra_attrs.get("termination")))
check("5d 目标终态=已结束（未达成）",
      kg.nodes[gid].extra_attrs.get("goal_state") == "已结束")

# ── 6 环境变化使旧计划失效 → 保留目标、修订计划 ──────────
kg6 = mk_world(alt=True)
gp.attach_goal(kg6, "oak_planks", 1)
spy6 = Spy()
t = gp.tick(kg6, spy6, st(), CFG_ON)
check("6a 首选已核验 provenance 分支",
      t["status"] == "DISPATCHED"
      and spy6.proposed[0]["params"]["resource"] == "oak_log",
      str(spy6.proposed[:1]))
# 模拟队列出队前环境变化：白名单边被移除
kg6.remove_edges(src="oak_log", relation="属于")
a6 = spy6.proposed[0]
r = gp.revalidate(kg6, {"action_type": a6["action_type"],
                        "target": a6["target"],
                        "params": dict(a6["params"])}, st(), CFG_ON)
check("6b 计划闸门在队首执行前丢弃前提已碎的步骤", r is None)
t = gp.tick(kg6, spy6, st(), CFG_ON)       # 被废步→重规划→birch 分支
check("6c 重规划后目标保留、选用替代分支",
      t["status"] == "DISPATCHED"
      and spy6.proposed[-1]["params"]["resource"] == "birch_log"
      and current_goal(kg6) != {}, str(t))
check("6d 旧计划归档为 superseded",
      any(h.get("outcome") == "superseded"
          for h in kg6.nodes[goal_node_id(kg6)].extra_attrs.get(
              "plan_history", [])))

# ── 7 AND 前置缺任意一项 → 不派发、不留半成品 ───────────
kg = mk_world(and_case=True)
gp.attach_goal(kg, "wooden_pickaxe", 1)
spy = Spy()
t = gp.tick(kg, spy, st(), CFG_ON)
check("7 AND 缺 magic_dust 生产者 → NO_FEASIBLE_PLAN 且零派发",
      t["status"] == "NO_FEASIBLE_PLAN" and spy.proposed == []
      and "stick" in str(t.get("unreachable", "")), str(t))

# ── 8 不可达目标不伪造为可达 ─────────────────────────────
kg = mk_world()
gp.attach_goal(kg, "golden_apple", 1)
kg.nodes["物品:golden_apple"].activation = 5.0     # 高激活也不该有戏
spy = Spy()
t = gp.tick(kg, spy, st(), CFG_ON)
check("8 孤立目标 → NO_PATH/终止、零派发、不伪造步骤",
      t["status"] == "NO_FEASIBLE_PLAN" and spy.proposed == []
      and t["unreachable"]["why"] == "NO_PRODUCER", str(t))

# ── 9 同目标连续拍不重复生成相同任务 ─────────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
spy = Spy()
gp.tick(kg, spy, st(), CFG_ON)
t2 = gp.tick(kg, spy, st(), CFG_ON)
t3 = gp.tick(kg, spy, st(), CFG_ON)
check("9 在飞步去重：连续三拍只派发一次",
      len(spy.proposed) == 1 and t2["status"] == "INFLIGHT"
      and t3["status"] == "INFLIGHT", str([t2, t3]))

# ── 10 目标达成后不继续执行旧计划 ────────────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
spy = Spy()
gp.tick(kg, spy, st(), CFG_ON)                    # gather 派发
gp.on_settled(kg, {"action_type": "gather_resource",
                   "params": dict(spy.proposed[0]["params"])},
              {"success": True}, True, CFG_ON)
t = gp.tick(kg, spy, st({"oak_log": 1}), CFG_ON)  # done → craft 派发
check("10a 采集确认→合成派发", t["status"] == "DISPATCHED"
      and spy.proposed[-1]["action_type"] == "craft_item", str(t))
gp.on_settled(kg, {"action_type": "craft_item",
                   "params": dict(spy.proposed[-1]["params"])},
              {"success": True}, True, CFG_ON)
t = gp.tick(kg, spy, st({"oak_planks": 1, "oak_log": 0}), CFG_ON)
check("10b 达成收束", t["status"] == "GOAL_ACHIEVED"
      and current_goal(kg) == {}, str(t))
gp.on_settled(kg, {"action_type": "craft_item",
                   "params": dict(spy.proposed[-1]["params"])},
              {"success": True}, True, CFG_ON)    # 旧回执再来一次
t2 = gp.tick(kg, spy, st(), CFG_ON)
check("10c 达成后：再拍=NO_GOAL、旧回执被忽略、零新增派发",
      t2["status"] == "NO_GOAL" and len(spy.proposed) == 2, str(t2))

# ── 11 旧/新计划不并存争抢 ──────────────────────────────
kg2 = mk_world(alt=True)
gp.attach_goal(kg2, "oak_planks", 1)
spy2 = Spy()
gp.tick(kg2, spy2, st(), CFG_ON)
kg2.remove_edges(src="oak_log", relation="属于")
gp.revalidate(kg2, {"action_type": "gather_resource",
                   "target": "oak_log",
                   "params": dict(spy2.proposed[0]["params"])},
              st(), CFG_ON)
gp.tick(kg2, spy2, st(), CFG_ON)               # 重规划 + 新派发
ids = [p["params"]["plan_id"] for p in spy2.proposed]
gid2 = goal_node_id(kg2)
cur = kg2.nodes[gid2].extra_attrs["plan"]["plan_id"]
check("11 派发只引用当前计划 id（旧计划回执通道整体失效）",
      ids[-1] == cur and ids[0] != cur, str(ids))

# ── 12 计划器不读激活、不把目标当行动 ────────────────────
import inspect as _ins
src = _ins.getsource(gp)
reads_act = any(x in src.split("def tick")[1].split("def maybe_tick")[0]
                for x in (".activation", "get_activation"))
kg = mk_world(kill_oak=True)
kg.nodes["物品:oak_planks"].activation = 5.0
gp.attach_goal(kg, "oak_planks", 1)
spy = Spy()
t = gp.tick(kg, spy, st(), CFG_ON)
check("12 高激活目标节点不产生任何派发/达成判定（判定只认观测库存）",
      not reads_act and t["status"] == "NO_FEASIBLE_PLAN"
      and spy.proposed == [], str(t))

# ── 13 学习写回区分行动失败 / 计划失败，且绝不改边权 ────
def edge_snap(k):
    # 不变式口径：除 Self-[当前目标] 指针边可被生命周期摘除外，
    # 任何边的 weight/activation/extra 不得变化（知识不因失败被降级）
    return sorted((str(e.src), e.relation, str(e.dst), float(e.weight),
                   float(e.activation),
                   str(sorted((e.extra_attrs or {}).items())))
                  for e in k.edges
                  if e.relation != "当前目标")

kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
am, emb = wire(kg)
for i in range(3):                                # 三次原地失败
    t = gp.tick(kg, am, st(), CFG_ON)
    if t["status"] == "DISPATCHED":
        emb.fail_script = ["bench_error"]
        drain(am)
pre = edge_snap(kg)
t = gp.tick(kg, am, st(), CFG_ON)                 # 第3败处理→排除→终止
post = edge_snap(kg)
check("13a 行动失败归因 blame=action，只写在依据节点计数",
      (kg.nodes["oak_log"].extra_attrs or {}).get("plan_last_blame")
      == "action"
      and int((kg.nodes["oak_log"].extra_attrs or {}).get(
          "plan_fail_count", 0)) == 1,
      str(kg.nodes["oak_log"].extra_attrs))
check("13b 计划器处理窗口内所有边逐字段不变（绝不无差别降级边权）",
      pre == post, "边被改动！")

kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
am, emb = wire(kg)
gp.tick(kg, am, st(), CFG_ON)                     # gather 派发
drain(am)                                         # 回执成功
pre2 = edge_snap(kg)
t = gp.tick(kg, am, st(), CFG_ON)                 # 但观测无变化
post2 = edge_snap(kg)
check("13c 成功但预期未现 → blame=plan 归因、边权不变",
      (kg.nodes["oak_log"].extra_attrs or {}).get("plan_last_blame")
      == "plan" and pre2 == post2, str(t))

# ── 14 新功能关闭时既有行为不变 ──────────────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
snap_nodes = {nid: (float(n.activation), copy.deepcopy(n.extra_attrs),
                    n.weight) for nid, n in kg.nodes.items()}
snap_edges = [(str(e.src), e.relation, str(e.dst), e.weight, e.activation)
              for e in kg.edges]
spy = Spy()
t = gp.tick(kg, spy, st(), {})                  # 无 planner 节
t2 = gp.maybe_tick(kg, spy, None, {})
gp.on_settled(kg, {"params": {}}, {}, True, {})
r = gp.revalidate(kg, {"action_type": "x", "params": {}}, st(), {})
snap_nodes2 = {nid: (float(n.activation), copy.deepcopy(n.extra_attrs),
                     n.weight) for nid, n in kg.nodes.items()}
check("14 关闭态：tick/maybe_tick/on_settled/revalidate 全零触碰",
      t["status"] == "disabled" and t2["status"] == "disabled"
      and r["action_type"] == "x" and spy.proposed == []
      and snap_nodes == snap_nodes2
      and snap_edges == [(str(e.src), e.relation, str(e.dst), e.weight,
                          e.activation) for e in kg.edges], str(t2))

# ── 15 设备/燃料前置（smelt 语义最小兼容）────────────────
kg = mk_world()
gp.attach_goal(kg, "oak_planks", 1)
kg = mk_world(smelt_case=True)
gp.attach_goal(kg, "oak_planks", 1)
spy = Spy()
t = gp.tick(kg, spy, st(), CFG_ON)
# 首选是已核验 oak 分支（排序规则），先走 gather oak_log
check("15a provenance 排序：已核验分支优先",
      spy.proposed and spy.proposed[0]["params"]["resource"] == "oak_log",
      str(spy.proposed[:1]))
# 关闭 oak 白名单 → 只剩 smelt+coal 分支
kg.remove_edges(src="oak_log", relation="属于")
gp.revalidate(kg, {"action_type": "gather_resource", "target": "oak_log",
                   "params": dict(spy.proposed[0]["params"])},
              st(), CFG_ON)
t = gp.tick(kg, spy, st(), CFG_ON)
plan_n = None
_gid15 = goal_node_id(kg)
for _x in kg.nodes[_gid15].extra_attrs["plan"]["steps"]:
    if _x["kind"] == "smelt":
        plan_n = _x
check("15b 不可采分支被排除后走 smelt 备选（计划含 smelt 步）",
      plan_n is not None and any(p["type"] == "seen_or_have"
                                 for p in plan_n["pre"])
      and any(p["type"] == "fuel" for p in plan_n["pre"]),
      str(plan_n))

print("\n" + ("ALL PASS" if not FAILURES else f"FAILED: {FAILURES}"))
sys.exit(1 if FAILURES else 0)
