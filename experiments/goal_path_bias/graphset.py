# graphset.py — 固定图集构造器（Phase-0 审计与族 M 实验共用，确定性）
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graph_model import KnowledgeGraph, Node, Edge      # noqa: E402
from diffusion_engine import DiffusionEngine            # noqa: E402
from self_graph import bootstrap_self                   # noqa: E402
import world_prior as wp                                # noqa: E402
import mc_knowledge as mck                              # noqa: E402
import config as _C                                     # noqa: E402

from sandbox_bridge import (                             # noqa: E402
    BRIDGE, mc_world_config, all_targets)

ENG_CFG = {"beta_spread": 1.0, "activation_epsilon": 1e-4,
           "min_spread_threshold": 0.01, "activation_max": 5.0,
           "lambda_decay": 0.05, "max_depth": 3, "theta_threshold": 0.01,
           "input_similarity_floor": 0.5, "input_default_bonus": 0.5,
           "emission_transfer": 1.0, "emission_ratio": 0.5}


def fresh_kg_engine():
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    bootstrap_self(kg)
    kg.add_node(Node(id="Haru", graph_space="self"))
    eng = DiffusionEngine(kg, dict(ENG_CFG))
    eng.name_to_node = dict(kg.nodes)
    return kg, eng


def _prov(conf=0.9):
    return {"confidence": conf, "knowledge_type": "prior",
            "source": "goalpath-sandbox", "version_verified": True}


# ── 真实生产路径图：mc_world + 配方闭包（沙箱桥）───────────────

def build_mc_production():
    cfgd = mc_world_config(dict(_C.DEFAULT_CONFIG))
    wp.bind_config(cfgd)
    wp._RUNTIME["queried"].clear()          # 图间缓存隔离（实验卫生）
    kg, eng = fresh_kg_engine()
    mck.ensure_mc_world(kg, cfgd)
    for tgt in all_targets():
        wp.build_recipe_closure(kg, eng, tgt, bridge=BRIDGE)
    eng.name_to_node = dict(kg.nodes)
    return kg, eng, cfgd


def build_baseline_snapshot(path):
    raw = json.load(open(path, encoding="utf-8"))
    kg, eng = fresh_kg_engine()
    for nd in raw["nodes"]:
        if kg.get_node(nd["id"]) is None:
            kg.add_node(Node(id=nd["id"], weight=nd.get("weight", 0.0),
                             activation=0.0, label=nd.get(
                                 "label", "declarative-semantic"),
                             graph_space=nd.get("graph_space", "semantic"),
                             execution=nd.get("execution"),
                             confidence=nd.get("confidence", 0.5),
                             extra_attrs=nd.get("extra_attrs")))
    for ed in raw["edges"]:
        try:
            kg.add_edge(Edge(src=ed["src"], dst=ed["dst"],
                             relation=ed["relation"],
                             weight=ed.get("weight", 0.5),
                             relation_category=ed.get(
                                 "relation_category", "semantic_relation"),
                             extra_attrs=ed.get("extra_attrs")))
        except Exception:
            pass
    eng.kg = kg
    eng.name_to_node = dict(kg.nodes)
    return kg, eng, {}


def build_packs_merged():
    kg, eng, _ = build_baseline_snapshot(
        os.path.join(ROOT, "knowledge_packs", "minecraft",
                     "knowledge_graph.json"))
    for pack in ("common", "computer"):
        raw = json.load(open(os.path.join(ROOT, "knowledge_packs", pack,
                                          "knowledge_graph.json"),
                             encoding="utf-8"))
        for nd in raw["nodes"]:
            if kg.get_node(nd["id"]) is None:
                kg.add_node(Node(id=nd["id"]))
        for ed in raw["edges"]:
            try:
                kg.add_edge(Edge(src=ed["src"], dst=ed["dst"],
                                 relation=ed["relation"],
                                 weight=ed.get("weight", 0.5)))
            except Exception:
                pass
    eng.name_to_node = dict(kg.nodes)
    return kg, eng, {}


# ── 合成拓扑（生产命名口径；ground-truth 路径由构造给定）────────

def _n(kg, i, **kw):
    if kg.get_node(i) is None:
        kg.add_node(Node(id=i, **kw))


def build_star1():
    """深度1星形：物品:iron_ingot ← 配方 ← raw_iron ← iron_ore(可采)。"""
    kg, eng = fresh_kg_engine()
    _n(kg, "物品:iron_ingot")
    _n(kg, "配方:iron_ingot:smelt:0", extra_attrs={"type": "recipe",
                                                   "kind": "smelt"})
    _n(kg, "物品:raw_iron")
    _n(kg, "iron_ore", extra_attrs={"type": "mc_species"})
    _n(kg, "可采资源")
    kg.add_edge(Edge("配方:iron_ingot:smelt:0", "物品:iron_ingot", "产生",
                     0.6, extra_attrs=_prov()))
    kg.add_edge(Edge("配方:iron_ingot:smelt:0", "物品:raw_iron", "需要",
                     0.6, extra_attrs={**_prov(), "count": 1}))
    kg.add_edge(Edge("iron_ore", "物品:raw_iron", "掉落", 0.6,
                     extra_attrs=_prov()))
    kg.add_edge(Edge("iron_ore", "可采资源", "属于", 0.8))
    truth = ["物品:iron_ingot", "配方:iron_ingot:smelt:0", "物品:raw_iron",
             "iron_ore"]
    return kg, eng, truth, []


def build_chain5():
    """深度链：iron_ingot ← smelt ← raw_iron ←(工具)stone_pickaxe ←
    craft ← cobblestone ←(工具)wooden_pickaxe ← craft ← oak_planks ← oak_log。
    （10 跳形状，对应 world_prior 头注释的真机链条例。）"""
    kg, eng = fresh_kg_engine()
    ids = ["物品:iron_ingot", "配方:iron_ingot:smelt:0", "物品:raw_iron",
           "iron_ore", "可采资源",
           "物品:stone_pickaxe", "配方:stone_pickaxe:table:0",
           "物品:cobblestone", "stone",
           "物品:wooden_pickaxe", "配方:wooden_pickaxe:table:0",
           "物品:oak_planks", "配方:oak_planks:hand:0", "物品:oak_log",
           "oak_log"]
    for i in ids:
        extra = {}
        if i.startswith("配方:"):
            extra = {"type": "recipe", "kind": "craft"}
        elif i in ("iron_ore", "stone", "oak_log"):
            extra = {"type": "mc_species"}
        _n(kg, i, extra_attrs=extra)
    E = [
        ("配方:iron_ingot:smelt:0", "物品:iron_ingot", "产生"),
        ("配方:iron_ingot:smelt:0", "物品:raw_iron", "需要"),
        ("iron_ore", "物品:raw_iron", "掉落"),
        ("iron_ore", "可采资源", "属于"),
        ("iron_ore", "物品:stone_pickaxe", "需要工具"),
        ("配方:stone_pickaxe:table:0", "物品:stone_pickaxe", "产生"),
        ("配方:stone_pickaxe:table:0", "物品:cobblestone", "需要"),
        ("stone", "物品:cobblestone", "掉落"),
        ("stone", "可采资源", "属于"),
        ("stone", "物品:wooden_pickaxe", "需要工具"),
        ("配方:wooden_pickaxe:table:0", "物品:wooden_pickaxe", "产生"),
        ("配方:wooden_pickaxe:table:0", "物品:oak_planks", "需要"),
        ("配方:oak_planks:hand:0", "物品:oak_planks", "产生"),
        ("配方:oak_planks:hand:0", "物品:oak_log", "需要"),
        ("oak_log", "物品:oak_log", "掉落"),
        ("oak_log", "可采资源", "属于"),
    ]
    for s, d, r in E:
        kg.add_edge(Edge(s, d, r, 0.6, extra_attrs=_prov()))
    truth = [i for i in ids if i != "可采资源"]
    return kg, eng, truth, []


def build_ring():
    """配方环：a←配方a需b；b←配方b需a（不可满足环，不得伪造落地）。"""
    kg, eng = fresh_kg_engine()
    for i, x in (("物品:a", "配方:a:x:0"), ("物品:b", "配方:b:x:0")):
        _n(kg, i)
        _n(kg, x, extra_attrs={"type": "recipe", "kind": "craft"})
    kg.add_edge(Edge("配方:a:x:0", "物品:a", "产生", 0.6, extra_attrs=_prov()))
    kg.add_edge(Edge("配方:a:x:0", "物品:b", "需要", 0.6, extra_attrs=_prov()))
    kg.add_edge(Edge("配方:b:x:0", "物品:b", "产生", 0.6, extra_attrs=_prov()))
    kg.add_edge(Edge("配方:b:x:0", "物品:a", "需要", 0.6, extra_attrs=_prov()))
    return kg, eng, ["物品:a", "配方:a:x:0", "物品:b", "配方:b:x:0"], []


def build_unreachable():
    kg, eng = fresh_kg_engine()
    _n(kg, "物品:golden_apple")
    return kg, eng, ["物品:golden_apple"], []


def build_distractor(noise_frac=0.4, seed=7):
    """chain5 + 高激活语义 fabric 干扰（共现边 40% 口径）。"""
    import random
    rng = random.Random(seed)
    kg, eng, truth, _ = build_chain5()
    noise = []
    for i in range(14):
        nid = f"经历_{i}"
        _n(kg, nid)
        kg.add_edge(Edge("Haru", nid, "涉及", 0.5))
        kg.add_edge(Edge(nid, "物品:cobblestone", "关联", 0.5))
        noise.append(nid)
    # 失败证据锚点：与路径节点 oak_log 邻接的负权 结果 边
    _n(kg, "行动结果:挖oak_log:failed")
    kg.add_edge(Edge("oak_log", "行动结果:挖oak_log:failed", "结果", -0.8))
    noise.append("行动结果:挖oak_log:failed")
    return kg, eng, truth, noise


GRAPHS = {
    "star1": build_star1,
    "chain5": build_chain5,
    "ring": build_ring,
    "unreachable": build_unreachable,
    "distractor": build_distractor,
}
