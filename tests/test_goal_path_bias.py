# test_goal_path_bias.py — 目标导向路径强化机制：单元/机制级测试
# 离线、临时图、无 LLM。对应 experiments/goal_path_bias/TEST_PLAN.md §1。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 tests/test_goal_path_bias.py

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge
from diffusion_engine import DiffusionEngine
from self_graph import bootstrap_self, set_current_goal
import goal_path_bias as gpb

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


CFG = {
    "lambda_decay": 0.05, "beta_spread": 1.0, "max_depth": 3,
    "theta_threshold": 0.01, "activation_max": 5.0,
    "min_spread_threshold": 0.01, "activation_epsilon": 1e-4,
    "input_similarity_floor": 0.5, "input_default_bonus": 0.5,
    "emission_transfer": 1.0, "emission_ratio": 0.5,
}


def gp(**kw):
    c = {"enabled": True, "search": True, "bias": False,
         "require_state_anchor": False, "max_hops": 8, "max_paths": 3,
         "max_nodes": 12, "bias_floor": 0.9, "bias_gamma": 0.6,
         "min_confidence": 0.5}
    c.update(kw)
    cfg = dict(CFG)
    cfg["goal_path"] = c
    return cfg


def _prov(conf=0.9):
    return {"confidence": conf, "knowledge_type": "prior",
            "source": "minecraft-data:runtime", "version_verified": True}


def build_plank_graph(with_fail=False, extra_noise=0):
    """planks ← 配方(hand) ← oak_log ← 掉落(可采方块)。生产命名/属性口径。"""
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    bootstrap_self(kg)
    kg.add_node(Node(id="Haru", graph_space="self"))  # 具身身份（拥有边主语）
    kg.add_node(Node(id="配方:oak_planks:hand:0",
                     extra_attrs={"type": "recipe", "kind": "craft"}))
    kg.add_node(Node(id="物品:oak_planks"))
    kg.add_node(Node(id="oak_log", extra_attrs={"type": "mc_species"}))
    kg.add_node(Node(id="物品:oak_log"))
    kg.add_node(Node(id="可采资源"))
    kg.add_edge(Edge(src="配方:oak_planks:hand:0", dst="物品:oak_planks",
                     relation="产生", weight=0.6, extra_attrs=_prov()))
    kg.add_edge(Edge(src="配方:oak_planks:hand:0", dst="物品:oak_log",
                     relation="需要", weight=0.6,
                     extra_attrs={**_prov(), "count": 1}))
    kg.add_edge(Edge(src="oak_log", dst="物品:oak_log",
                     relation="掉落", weight=0.6, extra_attrs=_prov()))
    kg.add_edge(Edge(src="oak_log", dst="可采资源",
                     relation="属于", weight=0.8))
    if with_fail:
        kg.add_node(Node(id="行动结果:挖oak_log:failed"))
        kg.add_edge(Edge(src="oak_log", dst="行动结果:挖oak_log:failed",
                         relation="结果", weight=-0.8))
    for i in range(extra_noise):
        kg.add_node(Node(id=f"噪声{i}"))
        kg.add_edge(Edge(src="Haru", dst=f"噪声{i}",
                         relation="关联", weight=0.5))
    return kg


def act_state(kg):
    return {nid: float(n.activation or 0.0) for nid, n in kg.nodes.items()}


def edge_state(kg):
    return [(str(e.src), e.relation, str(e.dst), float(e.weight),
             float(e.activation),
             json.dumps(e.extra_attrs or {}, sort_keys=True,
                        ensure_ascii=False, default=str))
            for e in kg.edges]


eng = lambda kg: DiffusionEngine(kg, dict(CFG))

# ── 1.1 无目标：启用机制但零写入 ──────────────────────────
kg = build_plank_graph()
e = eng(kg)
before = act_state(kg)
t = gpb.run_goal_path(kg, e, gp(bias=True))
check("1.1 无目标 → NO_TARGET 且零写入",
      t["status"] == "NO_TARGET" and t["writes"] == 0
      and act_state(kg) == before, str(t))
t2 = gpb.maybe_run(kg, e, {"goal_path": {"enabled": False}})
check("1.1b 总开关关 → disabled 零触碰", t2 == {"status": "disabled",
                                                 "writes": 0})

# ── 1.2 目标不可达：不伪造路径 ────────────────────────────
kg = build_plank_graph()
set_current_goal(kg, "获得 golden_apple")
e = eng(kg)
kg.add_node(Node(id="物品:golden_apple"))   # 孤立汇点，无任何入边
before = act_state(kg)
t = gpb.run_goal_path(kg, e, gp(bias=True))
check("1.2 不可达目标 → NO_PATH、零写入、不伪造",
      t["status"] == "NO_PATH" and t["writes"] == 0
      and act_state(kg) == before, str(t))

# ── 1.3 循环图：有界收敛 ─────────────────────────────────
kg = KnowledgeGraph(); kg.save = lambda *a, **k: None
bootstrap_self(kg)
kg.add_node(Node(id="物品:a")); kg.add_node(Node(id="物品:b"))
kg.add_node(Node(id="配方:a:x:0", extra_attrs={"type": "recipe"}))
kg.add_node(Node(id="配方:b:x:0", extra_attrs={"type": "recipe"}))
kg.add_edge(Edge(src="配方:a:x:0", dst="物品:a", relation="产生",
                 extra_attrs=_prov()))
kg.add_edge(Edge(src="配方:a:x:0", dst="物品:b", relation="需要",
                 extra_attrs=_prov()))
kg.add_edge(Edge(src="配方:b:x:0", dst="物品:b", relation="产生",
                 extra_attrs=_prov()))
kg.add_edge(Edge(src="配方:b:x:0", dst="物品:a", relation="需要",
                 extra_attrs=_prov()))
set_current_goal(kg, "获得 a")
e = eng(kg)
t0 = time.time()
t = gpb.run_goal_path(kg, e, gp(bias=True))
dt = time.time() - t0
cyc = any(l["why"] == "CYCLE" for l in t["derivation"]["leaves"])
check("1.3 环 → 有限时间返回、CYCLE 如实 unresolved、不无限搜索",
      dt < 1.0 and cyc and t["status"] in ("PARTIAL_PATH", "NO_PATH"),
      f"dt={dt:.3f} {t['status']} {t['derivation']['leaves']}")

# ── 1.4 方向与语义：白名单、非配方 需要 边不入路径 ───────
kg = build_plank_graph()
kg.add_node(Node(id="某种语义物"))
# 非 recipe 节点的 需要 边（producers_of 按 type=recipe 过滤）
kg.add_edge(Edge(src="某种语义物", dst="物品:oak_planks",
                 relation="需要", weight=0.9))
kg.add_edge(Edge(src="某种语义物", dst="物品:oak_planks",
                 relation="关联", weight=0.9))
set_current_goal(kg, "获得 oak_planks")
e = eng(kg)
t = gpb.run_goal_path(kg, e, gp())     # search only
hops = t["derivation"]["hops"]
check("1.4 路径只含状态转换推导（配方/物品/方块），语义关联不入路径",
      "某种语义物" not in hops and "配方:oak_planks:hand:0" in hops
      and "物品:oak_log" in hops and "oak_log" in hops, str(hops))
check("1.4b 与 world_prior.next_step 交叉一致（同源动作）",
      t["status"] == "PATH" and t["quality"]["resolved_fraction"] >= 1.0)
import world_prior as wp
ns = wp.next_step(kg, "oak_planks", {})
check("1.4c next_step 同图给 craft/gather 链含 oak_log",
      ns.get("action") in ("craft", "gather", "done")
      and "oak_log" in json.dumps(ns, ensure_ascii=False), str(ns))

# ── 1.5 开关与清除 ───────────────────────────────────────
kg = build_plank_graph()
set_current_goal(kg, "获得 oak_planks")
e = eng(kg)
before = act_state(kg)
t = gpb.run_goal_path(kg, e, gp(bias=True))
check("1.5 bias on → 有写入", t["writes"] > 0 and t["biased"], str(t))
n = gpb.clear_bias(kg, e)
after = act_state(kg)
check("1.5b clear_bias 完全回滚到写前值",
      n == t["writes"] and after == before,
      f"restored={n}/{t['writes']} diff="
      f"{ {k:(before[k],after[k]) for k in before if abs(before[k]-after[k])>1e-12} }")
try:
    gpb.run_goal_path(kg, e, gp(bias=True, search=False))
    ok = False
except gpb.ConfigError:
    ok = True
check("1.5c search=off & bias=on 是非法组合，显式报错", ok)
try:
    gpb.run_goal_path(kg, e, gp(bias=False, require_state_anchor=True))
    ok2 = False
except gpb.ConfigError:
    ok2 = True
check("1.5d require_state_anchor 无 bias 也报错", ok2)

# ── 1.6 长期权不变式：偏置不动边、节点写入 ≤ 预算 ────────
kg = build_plank_graph()
set_current_goal(kg, "获得 oak_planks")
e = eng(kg)
eb, ea = edge_state(kg), None
nb, na = act_state(kg), None
t = gpb.run_goal_path(kg, e, gp(bias=True, max_nodes=4))
ea, na = edge_state(kg), act_state(kg)
check("1.6 偏置期间 edge.weight/activation/extra 逐字段不变",
      eb == ea, "边被改动！")
changed = {k for k in na if abs(na[k] - nb.get(k, 0.0)) > 1e-12}
check("1.6b 节点写入数 ≤ max_nodes 预算且只增不减（偏置语义）",
      len(changed) <= 4 and all(na[k] >= nb.get(k, 0.0) for k in changed),
      str(changed))

# ── 1.7 Top-k 可见性（可达≠可见 的对照）+ 预算截断 ───────
def recall8(kg, e, cfg):
    for nid in cfg["biased"]:
        pass
    top, _ = e.get_topk(k=8)
    return top

kgA = build_plank_graph(extra_noise=12)
kgB = build_plank_graph(extra_noise=12)
set_current_goal(kgA, "获得 oak_planks")
set_current_goal(kgB, "获得 oak_planks")
eA, eB = eng(kgA), eng(kgB)
# 点火：给噪声与状态锚普通激活（同种子强度），B 条件加路径偏置
noise_ids = [f"噪声{i}" for i in range(12)]
for nid in noise_ids:
    for kgx in (kgA, kgB):
        kgx.nodes[nid].activation = 0.5
        kgx.nodes[nid].touch()
    eA.mark_active(noise_ids); eB.mark_active(noise_ids)
kgB.nodes["物品:oak_planks"].activation = 0.8; kgB.nodes["物品:oak_planks"].touch()
t = gpb.run_goal_path(kgB, eB, gp(bias=True))
check("1.7 偏置后路径节点进入 Top-8（基线不可见→可见）",
      any("配方:oak_planks:hand:0" in str(n.id) for n in eB.get_topk(8)[0]))
topA = {n.id for n in eA.get_topk(8)[0]}
topB = {n.id for n in eB.get_topk(8)[0]}
path_nodes = {"配方:oak_planks:hand:0", "物品:oak_log", "oak_log",
              "物品:oak_planks"}
rA = len(topA & path_nodes) / len(path_nodes)
rB = len(topB & path_nodes) / len(path_nodes)
check("1.7b recall@8: bias 条件 > 基线条件", rB > rA, f"A={rA} B={rB}")

# ── 1.8 失败证据冲突遥测（记录、不屏蔽）──────────────────
kg = build_plank_graph(with_fail=True)
set_current_goal(kg, "获得 oak_planks")
e = eng(kg)
t = gpb.run_goal_path(kg, e, gp(bias=True))
conf = t["conflicts"]
check("1.8 路径节点邻接负权结果边 → 冲突被记录",
      any(c["node"] == "oak_log" for c in conf), str(conf))
check("1.8b 失败信息未被屏蔽（行动结果节点仍在图中、边权不变）",
      "行动结果:挖oak_log:failed" in kg.nodes
      and kg.get_edge("oak_log", "行动结果:挖oak_log:failed", "结果").weight == -0.8)

# ── 1.9 B/C 差别：未落地路径 C 拒绝偏置、B 仍偏置 ─────────
kg = build_plank_graph()
kg.nodes.pop("可采资源", None)              # 破坏 gatherable 叶子
kg.remove_edges(src="oak_log", relation="属于")
set_current_goal(kg, "获得 oak_planks")
e = eng(kg)
tB = gpb.run_goal_path(kg, e, gp(bias=True))
n = gpb.clear_bias(kg, e)
tC = gpb.run_goal_path(kg, e,
                       gp(bias=True, require_state_anchor=True))
check("1.9 B：部分路径也被偏置（无前置检查）", tB["writes"] > 0, str(tB))
check("1.9b C：叶子不可落地 → 零偏置", tC["writes"] == 0, str(tC))

# ── 1.10 目标已达成（背包已有）：ALREADY_OWNED 零写入 ─────
kg = build_plank_graph()
kg.add_edge(Edge(src="Haru", dst="物品:oak_planks", relation="拥有",
                 weight=0.8))
set_current_goal(kg, "获得 oak_planks")
e = eng(kg)
before = act_state(kg)
t = gpb.run_goal_path(kg, e, gp(bias=True))
check("1.10 已拥有目标 → ALREADY_OWNED 且零写入",
      t["status"] == "ALREADY_OWNED" and act_state(kg) == before, str(t))

print("\n" + ("ALL PASS" if not FAILURES else f"FAILED: {FAILURES}"))
sys.exit(1 if FAILURES else 0)
