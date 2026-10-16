# sandbox_env.py — 房间/单位沙盒（确定性、与 Minecraft 无关）
# 环境只声明规则并校验执行；规划/核验归 taskloop。单位粒度建模
# （一件物品=一个对象），规避计数算子的经典困难；背包容量以 free:1
# 谓词保守表达（take 删 free、put 加回——过保守只会多规划一步，不会
# 把计划做成非法）。谓词：
#   at:agent:<room>  at:<item>:<room>  have:<item>  free:1  exists:<room>
#   linked:<a>:<b>  powered:<fx>  exists_fixture:<fx>
# 故障注入（负面测试）：take_noop（回执成功状态不变）、move_block（一次性
# 拒走）、surprise（执行时非预期环境事件）。
import copy


class RoomWorld:
    def __init__(self, rooms, links, items, start="entry", capacity=2,
                 fixtures=None, faults=None):
        """items: {name: room}。fixtures: {name:{room, power,
        consumes:[in], produces:{out:1}}}（单位模型 produces 只列产物名）。"""
        self.rooms = list(rooms)
        self.links = {}
        for a, bs in links.items():
            for b in bs:
                self.links.setdefault(a, []).append(b)
                self.links.setdefault(b, []).append(a)
        for r in self.rooms:
            self.links.setdefault(r, [])
        self.items = dict(items)          # name -> room
        self.agent = start
        self.capacity = int(capacity)
        self.fixtures = {k: dict(v) for k, v in (fixtures or {}).items()}
        self.faults = copy.deepcopy(faults or {})
        self.log = []
        self._tick = 0

    # ── taskloop 协议 ─────────────────────────────────
    def universe(self):
        return {"room": self.rooms, "item": sorted(self.items),
                "fx": sorted(self.fixtures)}

    def snapshot(self):
        s = {f"at:agent:{self.agent}"}
        held = [n for n, r in self.items.items() if r is None]
        for n, r in self.items.items():
            if r is not None:
                s.add(f"at:{n}:{r}")
        for n in held:
            s.add(f"have:{n}")
        s.add(f"slot:{self.capacity - len(held)}")
        for r in self.rooms:
            s.add(f"exists:{r}")
            for b in self.links[r]:
                s.add(f"linked:{r}:{b}")
        for f, fx in self.fixtures.items():
            s.add(f"exists_fixture:{f}")
            if fx.get("power") == "on":
                s.add(f"powered:{f}")
        return s

    def ops(self):
        """接地 = 全签名空间（动作合法性由前置与 execute 复核决定，
        不随当前状态裁剪——take 之后才可用的 put 必须预先在案）。"""
        out = []
        for a in self.rooms:
            for b in self.links[a]:
                out.append({"name": "move", "args": {"from": a, "to": b},
                            "pre": [f"at:agent:{a}", f"linked:{a}:{b}",
                                    f"exists:{b}"],
                            "add": [f"at:agent:{b}"],
                            "del": [f"at:agent:{a}"], "template": "move"})
        cap = self.capacity
        for it in self.items:
            for r in self.rooms:
                for k in range(1, cap + 1):        # 精确槽位数接地
                    out.append({"name": "take",
                                "args": {"item": it, "room": r},
                                "pre": [f"at:agent:{r}", f"at:{it}:{r}",
                                        f"slot:{k}"],
                                "add": [f"have:{it}", f"slot:{k - 1}"],
                                "del": [f"at:{it}:{r}", f"slot:{k}"],
                                "template": "take"})
                for k in range(0, cap):
                    out.append({"name": "put",
                                "args": {"item": it, "room": r},
                                "pre": [f"at:agent:{r}", f"have:{it}",
                                        f"slot:{k}"],
                                "add": [f"at:{it}:{r}", f"slot:{k + 1}"],
                                "del": [f"have:{it}", f"slot:{k}"],
                                "template": "put"})
        for f, fx in self.fixtures.items():
            for inp in fx.get("consumes", []):
                for prod in fx.get("produces", {}):
                    out.append({"name": "use",
                                "args": {"fx": f, "in": inp,
                                         "out": prod,
                                         "room": fx.get("room")},
                                "pre": [f"at:agent:{fx.get('room')}",
                                        f"exists_fixture:{f}",
                                        f"powered:{f}", f"have:{inp}"],
                                "add": [f"have:{prod}"],
                                "del": [f"have:{inp}"],
                                "template": "use"})
        return out

    # ── 执行（独立复核；规划与事实脱节时以环境为准）─────────
    def execute(self, action):
        self._tick += 1
        name = action["name"]
        args = action["args"]

        def deny(reason):
            self.log.append({"tick": self._tick, "action": name,
                             "args": args, "ok": False, "reason": reason})
            return {"ok": False, "reason": reason}

        if name == "move":
            if args["from"] != self.agent:
                return deny("agent_not_at_from")
            if args["to"] not in self.links[self.agent]:
                return deny("no_link")
            fb = self.faults.get("move_block")
            if fb and fb.get("to") == args["to"] and not fb.get("used"):
                fb["used"] = True
                return deny("path_blocked_temporarily")
            self.agent = args["to"]
            return self._ok(name, args)
        if name == "take":
            if self.items.get(args["item"]) != args["room"]:
                return deny("item_not_here")
            if self.agent != args["room"]:
                return deny("agent_not_here")
            held = sum(1 for r in self.items.values() if r is None)
            if held >= self.capacity:
                return deny("no_capacity")
            spoof = self.faults.get("take_noop")
            if spoof and spoof.get("item") == args["item"] \
                    and (spoof.get("always")
                    or not spoof.get("used")):
                spoof["used"] = True
                self.log.append({"tick": self._tick, "action": name,
                                 "args": args, "ok": True,
                                 "reason": "SPOOFED_NO_STATE"})
                return {"ok": True, "reason": ""}
            self.items[args["item"]] = None
            self._surprise()
            return self._ok(name, args)
        if name == "put":
            if self.agent != args["room"]:
                return deny("agent_not_here")
            if self.items.get(args["item"]) is not None:
                return deny("not_holding")
            self.items[args["item"]] = args["room"]
            self._surprise()
            return self._ok(name, args)
        if name == "use":
            fx = self.fixtures.get(args["fx"])
            if not fx or fx.get("power") != "on":
                return deny("not_powered")
            if self.agent != fx.get("room"):
                return deny("agent_not_at_fixture")
            if self.items.get(args["in"]) is not None:
                return deny("missing_input")
            if args["out"] not in fx.get("produces", {}):
                return deny("bad_recipe")
            self.items[args["in"]] = "__gone__"
            self.items[args["out"]] = None
            self._surprise()
            return self._ok(name, args)
        return deny("unknown_op")

    def _ok(self, name, args):
        self.log.append({"tick": self._tick, "action": name, "args": args,
                         "ok": True, "reason": ""})
        return {"ok": True, "reason": ""}

    def _surprise(self):
        f = self.faults.get("surprise")
        if f and not f.get("used"):
            f["used"] = True
            item, room = f["item"], f["room"]
            if item in self.items:
                self.items[item] = room
                self.log.append({"tick": self._tick, "action": "_event",
                                 "args": {"item": item, "room": room},
                                 "ok": True, "reason": "ENV_SURPRISE"})

    def full_state(self):
        return {"agent": self.agent, "items": dict(self.items),
                "log": list(self.log)}

    # ── 宿主级持久化（阶段 C：进度查询/继续任务跨进程恢复）──
    def state(self):
        return {"agent": self.agent, "items": dict(self.items)}

    @classmethod
    def restore(cls, base_def, st):
        w = cls(rooms=base_def.get("rooms", []),
                links=base_def.get("links", {}),
                items=base_def.get("items", {}),
                capacity=int(base_def.get("capacity", 3)),
                fixtures=base_def.get("fixtures"))
        w.agent = st["agent"]
        w.items = dict(st["items"])
        return w
