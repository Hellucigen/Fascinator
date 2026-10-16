# sandbox_bridge.py — 实验沙箱桥（零 LLM、确定性、离线）
# 拆仓后 sandbox_lab.py 未随认知核心进入本仓库（scripts/run_exp_reldir.py 等
# 历史脚本的 import 在本仓不可满足——可复现性缺口，已在最终报告如实记录）。
# 本文件按 world_prior 期望的桥协议自实现一个**最小确定性 MC 类世界**：
#   bridge.recipe_for(item) -> {"ok","mc_version","recipes":[{result,
#       needs_table, yield, ingredients{mat:count}}]}
#   bridge.block_meta(block) -> {"ok","block","drops","harvest_tools"}
# 它是实验事实源，不是生产知识：生产侧仍是运行时 minecraft-data 查证。
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

MC_VERSION = "1.21.0-goalpath-sandbox"

BLOCKS = {           # 方块: 掉落 + 采集工具（[] = 空手）
    "oak_log":     {"drops": ["oak_log"],     "harvest_tools": []},
    "stone":       {"drops": ["cobblestone"], "harvest_tools": ["wooden_pickaxe"]},
    "coal_ore":    {"drops": ["coal"],        "harvest_tools": ["wooden_pickaxe"]},
    "iron_ore":    {"drops": ["raw_iron"],    "harvest_tools": ["stone_pickaxe"]},
}
RECIPES = {          # 产物: (needs_table, ingredients)
    "oak_planks":     (False, {"oak_log": 1}),
    "stick":          (False, {"oak_planks": 2}),
    "crafting_table": (False, {"oak_planks": 4}),
    "wooden_pickaxe": (True,  {"oak_planks": 3, "stick": 2}),
    "stone_pickaxe":  (True,  {"cobblestone": 3, "stick": 2}),
    "furnace":        (True,  {"cobblestone": 8}),
}
# 熔炼走人工先验通道（与生产 experiment.prior_extra 同构，version_verified=False）
SMELT = [{"result": "iron_ingot", "kind": "smelt", "inputs": {"raw_iron": 1},
          "tool": "furnace", "fuel": True,
          "provenance": {"knowledge_type": "prior",
                         "source": "sandbox-manual",
                         "version_verified": False, "confidence": 0.6}}]


class Bridge:
    def recipe_for(self, item):
        item = str(item).lower()
        if item not in RECIPES:
            return {"ok": False}
        table, ing = RECIPES[item]
        return {"ok": True, "mc_version": MC_VERSION,
                "recipes": [{"result": item, "needs_table": table,
                             "yield": 1,
                             "ingredients": {k: v for k, v in ing.items()}}]}

    def block_meta(self, block):
        block = str(block).lower()
        if block not in BLOCKS:
            return {"ok": False}
        m = BLOCKS[block]
        return {"ok": True, "mc_version": MC_VERSION, "block": block,
                "drops": list(m["drops"]),
                "harvest_tools": list(m["harvest_tools"])}


BRIDGE = Bridge()


def mc_world_config(cfgd):
    """按 mc_knowledge/world_prior 消费口径注入沙箱世界（同 topology_scout 形）。"""
    cfgd = dict(cfgd)
    cfgd["mc_world"] = {
        "gatherable": sorted(BLOCKS),
        "tool_required": {b: m["harvest_tools"][0] for b, m in BLOCKS.items()
                          if m["harvest_tools"]},
        "produces": {b: m["drops"][0] for b, m in BLOCKS.items()},
        "block_meta": {b: dict(m) for b, m in BLOCKS.items()},
    }
    cfgd["experiment"] = dict(cfgd.get("experiment") or {})
    cfgd["experiment"]["prior_extra"] = list(SMELT)
    return cfgd


def all_targets():
    ts = sorted(set(RECIPES) | {d for m in BLOCKS.values()
                                for d in m["drops"]}
                | {s["result"] for s in SMELT})
    return ts
