# simenv.py — 确定性测试替身（SimEnv）：闭环实验专用，非 Minecraft/生产环境
# ============================================================================
# 身份声明（硬约束）：本文件是**明确标记的模拟执行环境**，用于验证计划器的
# 控制闭环（派发闸门/监测/重规划/收束），不验证真实 Minecraft 行为。
# 世界物理按图语义实现：
#   gather_resource(resource,quantity)：resource 必须①在 env.blocks
#     ②空手或有工具 → +quantity×drop；否则 failed(block_not_found /
#     tool_missing)。
#   craft_item(item,count)：配方输入×count 齐备（needs_table 时背包有
#     crafting_table——简化：放置步不建模，如实披露）→ 消耗并 +yield×count；
#     否则 failed(inputs_missing / no_table)。
#   smelt_item(item,count)：炉子（背包或 env.placed）+ 燃料 + 输入齐备。
# 注入脚本（全确定性）：fail_at（指定次序动作强制失败）、
#   give_at（外部送达物品=目标经他途达成）、blocks_at（方块消失=环境变化）。
# ============================================================================
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from graph_model import KnowledgeGraph, Node, Edge        # noqa: E402
from self_graph import bootstrap_self                     # noqa: E402


def prov(conf=0.9, verified=True):
    return {"confidence": conf, "knowledge_type": "prior",
            "source": "simenv", "version_verified": verified}


def build_graph(stick_needs_magic=False, alt_birch=False,
                smelt_target=False, pickaxe_tool=False):
    """生产命名口径的配方图（与 tests/test_goal_planner.mk_world 同族）。
    smelt_target: iron_ingot ← smelt(raw_iron)，炉+燃料；raw_iron ←
      iron_ore 需 silver_pickaxe（银镐=虚构规则，空手采银矿）。
    pickaxe_tool: iron_ore 需要 silver_pickaxe；silver_pickaxe ←
      smelt 银锭链（闭环实验的深链场景用）。"""
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    bootstrap_self(kg)
    kg.add_node(Node(id="Haru", graph_space="self"))

    def N(i, **kw):
        if kg.get_node(i) is None:
            kg.add_node(Node(id=i, **kw))

    def E(s, r, d, w=0.6, ea=None):
        kg.add_edge(Edge(s, d, r, w, extra_attrs=ea or prov()))

    N("可采资源"); N("Haru"); N("furnace"); N("crafting_table")
    N("物品:oak_planks", extra_attrs={"count": 0})
    N("配方:oak_planks:hand:0",
      extra_attrs={"type": "recipe", "kind": "craft", "yield": 4})
    N("oak_log", extra_attrs={"type": "mc_species"})
    N("物品:oak_log", extra_attrs={"count": 0})
    N("物品:stick", extra_attrs={"count": 0})
    N("配方:stick:hand:0",
      extra_attrs={"type": "recipe", "kind": "craft", "yield": 4})
    N("物品:crafting_table")

    E("配方:oak_planks:hand:0", "产生", "物品:oak_planks")
    E("配方:oak_planks:hand:0", "需要", "物品:oak_log",
      ea={**prov(), "count": 1})
    E("oak_log", "属于", "可采资源", 0.8)
    E("oak_log", "掉落", "物品:oak_log")
    stick_out = "物品:magic_dust" if stick_needs_magic else "物品:oak_planks"
    if stick_needs_magic:
        N("物品:magic_dust", extra_attrs={"count": 0})   # 无生产者
    E("配方:stick:hand:0", "产生", "物品:stick")
    E("配方:stick:hand:0", "需要", stick_out, ea={**prov(), "count": 2})
    E("配方:crafting_table:hand:0", "产生", "物品:crafting_table")
    N("配方:crafting_table:hand:0",
      extra_attrs={"type": "recipe", "kind": "craft", "yield": 1})
    E("配方:crafting_table:hand:0", "需要", "物品:oak_planks",
      ea={**prov(), "count": 4})

    if alt_birch:
        N("birch_log", extra_attrs={"type": "mc_species"})
        N("物品:birch_log", extra_attrs={"count": 0})
        N("配方:oak_planks:birch:0",
          extra_attrs={"type": "recipe", "kind": "craft", "yield": 4})
        E("birch_log", "属于", "可采资源", 0.8,
          ea=prov(conf=0.4, verified=False))
        E("birch_log", "掉落", "物品:birch_log",
          ea=prov(conf=0.4, verified=False))
        E("配方:oak_planks:birch:0", "产生", "物品:oak_planks",
          ea=prov(conf=0.4, verified=False))
        E("配方:oak_planks:birch:0", "需要", "物品:birch_log",
          ea={**prov(conf=0.4, verified=False), "count": 1})

    if smelt_target:
        N("物品:iron_ingot")
        N("配方:iron_ingot:smelt:0",
          extra_attrs={"type": "recipe", "kind": "smelt", "tool": "furnace",
                       "yield": 1})
        N("物品:raw_iron")
        N("iron_ore", extra_attrs={"type": "mc_species"})
        N("物品:coal", extra_attrs={"count": 0})
        N("coal_block", extra_attrs={"type": "mc_species"})
        E("配方:iron_ingot:smelt:0", "产生", "物品:iron_ingot")
        E("配方:iron_ingot:smelt:0", "需要", "物品:raw_iron",
          ea={**prov(), "count": 1})
        E("iron_ore", "属于", "可采资源", 0.8)
        E("iron_ore", "掉落", "物品:raw_iron")
        E("coal_block", "属于", "可采资源", 0.8)
        E("coal_block", "掉落", "物品:coal")
        if pickaxe_tool:
            N("物品:silver_pickaxe")
            N("配方:silver_pickaxe:table:0",
              extra_attrs={"type": "recipe", "kind": "craft",
                           "needs_table": True, "yield": 1})
            N("物品:silver_ingot")
            N("配方:silver_ingot:smelt:0",
              extra_attrs={"type": "recipe", "kind": "smelt",
                           "tool": "furnace", "yield": 1})
            N("物品:raw_silver")
            N("silver_ore", extra_attrs={"type": "mc_species"})
            E("iron_ore", "需要工具", "silver_pickaxe", 0.6)
            E("配方:silver_pickaxe:table:0", "产生",
              "物品:silver_pickaxe")
            E("配方:silver_pickaxe:table:0", "需要", "物品:silver_ingot",
              ea={**prov(), "count": 2})
            E("配方:silver_pickaxe:table:0", "需要", "物品:stick",
              ea={**prov(), "count": 2})
            E("配方:silver_ingot:smelt:0", "产生", "物品:silver_ingot")
            E("配方:silver_ingot:smelt:0", "需要", "物品:raw_silver",
              ea={**prov(), "count": 1})
            E("silver_ore", "属于", "可采资源", 0.8)
            E("silver_ore", "掉落", "物品:raw_silver")
    return kg


class SimEnv:
    """确定性世界 + ActionManager 具身替身。"""

    DROPS = {"oak_log": "oak_log", "birch_log": "birch_log",
             "iron_ore": "raw_iron", "coal_block": "coal",
             "silver_ore": "raw_silver"}
    TOOLS = {"iron_ore": "silver_pickaxe"}      # 虚构规则（空手采煤/木/银矿）
    FUELS = {"coal": 80.0}

    def __init__(self, blocks=None, placed=(), inv=None,
                 fail_at=None, give_at=None, blocks_at=None):
        self.inv = dict(inv or {})
        self.blocks = set(blocks if blocks is not None
                          else ["oak_log", "birch_log", "iron_ore",
                                "coal_block", "silver_ore"])
        self.placed = set(placed)
        self.fail_at = list(fail_at or [])      # [cycle_idx, reason] 队列
        self.give_at = list(give_at or [])      # [(cycle, {item:count})]
        self.blocks_at = list(blocks_at or [])  # [(cycle, "remove", block)]
        self.pending = None
        self.history = []                       # 执行账（含失败）
        self.cycle = 0

    # ── 每拍先应用世界事件 ──
    def advance_cycle(self, cycle):
        self.cycle = cycle
        while self.give_at and self.give_at[0][0] == cycle:
            for item, c in self.give_at.pop(0)[1].items():
                self.inv[item] = self.inv.get(item, 0) + c
        while self.blocks_at and self.blocks_at[0][0] == cycle:
            _, op, blk = self.blocks_at.pop(0)
            if op == "remove":
                self.blocks.discard(blk)

    # ── ActionManager 具身协议 ──
    def execute(self, action):
        at = str(action.get("action_type") or "")
        p = action.get("params") or {}
        out = self._run(at, p)
        self.history.append({"cycle": self.cycle, "action": at,
                             "target": action.get("target"), **out})
        self.pending = out
        return {"success": True, "pending": True, "action": at}

    def poll_action(self):
        if self.pending is None:
            return {"status": "running"}
        r, self.pending = self.pending, None
        if r["success"]:
            return {"status": "done",
                    "detail": {"ok": True, "success": True,
                               **r.get("detail", {})}}
        return {"status": "failed", "reason": r["reason"]}

    def raw_state(self):
        return {}

    def skill_catalog(self):
        return []

    def _run(self, at, p):
        # 失败注入：脚本命中当前动作即失败一次（模拟台子故障等）
        for i, (c, want_at, want_t, reason) in enumerate(self.fail_at):
            if c == self.cycle and want_at == at and (
                    want_t in (None, p.get("item"), p.get("resource"),
                               None)):
                self.fail_at.pop(i)
                return {"success": False, "reason": reason}
        if at == "gather_resource":
            blk = str(p.get("resource") or "")
            q = int(p.get("quantity") or 1)
            if blk not in self.blocks:
                return {"success": False, "reason": "block_not_found"}
            need_tool = self.TOOLS.get(blk)
            if need_tool and self.inv.get(need_tool, 0) <= 0:
                return {"success": False, "reason": "tool_missing"}
            item = self.DROPS[blk]
            self.inv[item] = self.inv.get(item, 0) + q
            return {"success": True, "reason": "", "detail":
                    {"gained": {item: q}}}
        if at == "craft_item":
            item = str(p.get("item") or "")
            n = int(p.get("count") or 1)
            recipe = _RECIPES.get(item)
            if recipe is None:
                return {"success": False, "reason": "no_recipe"}
            inputs_alt, yld, needs_table = recipe
            if needs_table and "crafting_table" not in self.inv \
                    and "crafting_table" not in self.placed:
                return {"success": False, "reason": "no_table"}
            picked = None
            for inputs in inputs_alt:
                if all(self.inv.get(m, 0) >= c * n
                       for m, c in inputs.items()):
                    picked = inputs
                    break
            if picked is None:
                return {"success": False, "reason": "inputs_missing"}
            for m, c in picked.items():
                self.inv[m] -= c * n
            self.inv[item] = self.inv.get(item, 0) + yld * n
            return {"success": True, "reason": "",
                    "detail": {"gained": {item: yld * n}}}
        if at == "smelt_item":
            item = str(p.get("item") or "")
            n = int(p.get("count") or 1)
            recipe = _SMELT.get(item)
            if recipe is None:
                return {"success": False, "reason": "no_smelt"}
            inputs, yld = recipe[0], recipe[1]
            if "furnace" not in self.inv and "furnace" not in self.placed:
                return {"success": False, "reason": "no_furnace"}
            if not any(self.inv.get(f, 0) > 0 for f in self.FUELS):
                return {"success": False, "reason": "no_fuel"}
            for m, c in inputs.items():
                if self.inv.get(m, 0) < c * n:
                    return {"success": False, "reason": "inputs_missing"}
            fuel = next(f for f in self.FUELS if self.inv.get(f, 0) > 0)
            self.inv[fuel] -= 1
            for m, c in inputs.items():
                self.inv[m] -= c * n
            self.inv[item] = self.inv.get(item, 0) + yld * n
            return {"success": True, "reason": "",
                    "detail": {"gained": {item: yld * n}}}
        return {"success": False, "reason": f"unknown:{at}"}

    # ── 感知 ──
    def percept(self):
        return {"inventory_items": [{"name": k, "count": v}
                                    for k, v in self.inv.items() if v > 0],
                "blocks": [{"name": b} for b in sorted(self.blocks)]}


# 世界物理的配方表（与图内容一致——物理是"世界"，图是其知识镜像）。
# 每项 = (可选输入组列表, 产出, needs_table)：多组=同一产物的并列配方。
_RECIPES = {
    "oak_planks": ([{"oak_log": 1}, {"birch_log": 1}], 4, False),
    "stick": ([{"oak_planks": 2}], 4, False),
    "crafting_table": ([{"oak_planks": 4}], 1, False),
    "silver_pickaxe": ([{"silver_ingot": 2, "stick": 2}], 1, True),
}
_SMELT = {
    "iron_ingot": ([{"raw_iron": 1}], 1),
    "silver_ingot": ([{"raw_silver": 1}], 1),
}
