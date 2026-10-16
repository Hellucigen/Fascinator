# mc_env.py — Minecraft 域作为 TaskLoop 第四环境适配器（阶段 F）
# 世界模型（图配方知识 + SimEnv 物理）保持 MC 专用并**留在环境侧**；
# 目标管理/核验/台账/结束判定由 taskloop 通用核承担。规划词表用**单位
# 粒度**（have:i#k = 至少持有第 k 件），规避单调计数谓词与删除语义的
# 经典冲突；execute 以物理真实校验（不信任规划）。
# 物理复用 experiments/goal_planner/simenv.SimEnv（既有确定性替身，
# 与真实 Minecraft 无关——本适配器全部验证均为离线沙盒级）。
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))       # FAS-Cognitive
_EXP = os.path.dirname(_HERE)                         # experiments
for _p in (_ROOT, os.path.join(_EXP, "goal_planner"),
         os.path.join(_EXP, "goal_path_bias")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sandbox_bridge import BRIDGE, mc_world_config          # noqa: E402
import config as _C                                         # noqa: E402
import world_prior as wp                                    # noqa: E402
import mc_knowledge as mck                                  # noqa: E402
from graph_model import KnowledgeGraph                      # noqa: E402
from simenv import SimEnv                                   # noqa: E402

CAP = 8            # 单位建模上限（超出诚实拒绝构建）


class McTaskEnv:
    def __init__(self, target=None, seed_items=(), blocks=None,
                 max_craft=4):
        cfgd = mc_world_config(dict(_C.DEFAULT_CONFIG))
        wp.bind_config(cfgd)
        wp._RUNTIME["queried"].clear()
        self.kg = KnowledgeGraph()
        self.kg.save = lambda *a, **k: None
        mck.ensure_mc_world(self.kg, cfgd)
        self.targets = [target] if target else []
        for s in list(self.targets) + list(seed_items):
            wp.build_recipe_closure(self.kg, None, s, bridge=BRIDGE)
        self.world = SimEnv(blocks=list(blocks or []),
                            placed=["furnace", "crafting_table"])
        self.max_craft = int(max_craft)
        self.log = []

    def universe(self):
        items = {str(n)[3:] for n in self.kg.nodes
                 if str(n).startswith("物品:")}
        return {"item": sorted(items)}

    def snapshot(self):
        s = set()
        inv = self.world.inv
        for name, cnt in inv.items():
            for k in range(1, min(int(cnt), CAP) + 1):
                s.add(f"have:{name}#{k}")
        for b in self.world.blocks:
            s.add(f"block:{b}")
        if inv.get("crafting_table"):
            s.add("table:have")
        return s

    def ops(self):
        """单位粒度接地（have:x#k=至少持有 k 件）。单调 add-only 是**规划期
        高估近似**（可能低估材料消耗），execute 以物理真实校验兜底：
        预支失败→环境拒绝记账；超发失败→verify-miss→拉黑→重规划。
        这是离线适配层的显式妥协，不是隐藏缺陷。"""
        out = []
        uni = self.universe()["item"]
        for item in uni:
            for blk in wp.drop_sources(self.kg, item):
                if not self._gatherable(blk):
                    continue
                tools = wp.tool_required(self.kg, blk)
                for k in range(1, CAP + 1):
                    pre = ([f"block:{blk}"] + [f"have:{t}#1" for t in tools]
                           + ([f"have:{item}#{k - 1}"] if k > 1 else []))
                    out.append({"name": "gather",
                                "args": {"item": item, "blk": blk,
                                         "unit": k},
                                "pre": pre, "add": [f"have:{item}#{k}"],
                                "del": [], "template": "gather",
                                "cost": 2})
        for rid, pr in self._all_recipes().items():
            o_, inputs, y = pr["out"], pr["inputs"], pr["yield"]
            if o_ not in uni:
                continue
            for k in range(1, CAP + 1):
                import math as _m
                pre = []
                bad = False
                for mat, cnt in inputs.items():
                    need = _m.ceil(k / y) * cnt
                    if need > CAP:
                        bad = True
                        break
                    if need >= 1:
                        pre.append(f"have:{mat}#{need}")
                if bad:
                    continue
                if k > 1:
                    pre.append(f"have:{o_}#{k - 1}")
                if pr["needs_table"]:
                    pre.append("table:have")
                if pr["kind"] == "smelt":
                    pre.append("block:coal_block")
                out.append({"name": "craft" if pr["kind"] != "smelt"
                            else "smelt",
                            "args": {"out": o_, "unit": k},
                            "pre": sorted(set(pre)),
                            "add": [f"have:{o_}#{k}"], "del": [],
                            "template": pr["kind"], "cost": 3})
        return out

    def _all_recipes(self):
        seen = {}
        for item in self.universe()["item"]:
            for pr in wp.producers_of(self.kg, item):
                if not pr["inputs"]:
                    continue
                seen[pr["recipe"]] = {"out": item,
                                      "inputs": dict(pr["inputs"]),
                                      "kind": pr["kind"],
                                      "needs_table": pr.get(
                                          "needs_table", False),
                                      "yield": self._yield(
                                          pr["recipe"])}
        return seen

    def _yield(self, rid):
        n = self.kg.nodes.get(rid)
        try:
            return max(1, int((n.extra_attrs or {}).get("yield", 1)))
        except Exception:
            return 1

    def _gatherable(self, blk):
        try:
            return self.kg.get_edge(str(blk), "可采资源", "属于") is not None
        except Exception:
            return False

    def execute(self, action):
        name, args = action["name"], action["args"]
        if name == "gather":
            r = self.world.execute(
                {"action_type": "gather_resource",
                 "target": args["blk"],
                 "params": {"resource": args["blk"],
                            "quantity": 1}})
            if r.get("pending"):
                r = self.world.poll_action()
                r = {"ok": r.get("status") == "done",
                     "reason": str(r.get("reason", ""))}
            self.log.append(("gather", args, dict(r)))
            return {"ok": bool(r.get("ok")), "reason": r.get("reason", "")}
        if name in ("craft", "smelt"):
            atype = "craft_item" if name == "craft" else "smelt_item"
            r = self.world.execute(
                {"action_type": atype, "target": args["out"],
                 "params": {"item": args["out"], "count": 1}})
            if r.get("pending"):
                r = self.world.poll_action()
                r = {"ok": r.get("status") == "done",
                     "reason": str(r.get("reason", ""))}
            self.log.append((name, args, dict(r)))
            return {"ok": bool(r.get("ok")), "reason": r.get("reason", "")}
        return {"ok": False, "reason": "unknown_op"}

    def state(self):
        return {"inv": dict(self.world.inv),
                "blocks": list(self.world.blocks)}

    @classmethod
    def restore(cls, kw, st):
        e = cls(**kw)
        e.world.inv = dict(st["inv"])
        e.world.blocks = set(st["blocks"])
        return e
