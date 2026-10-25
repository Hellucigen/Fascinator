# -*- coding: utf-8 -*-
"""sts2_sim.world v2 — 更像样的杀戮尖塔沙盒（2026-10-15）。

对齐真实尖塔机制（一代稳定版语义，E3 级——STS2 v0.103 细节接真桥时逐项
对账）：
  · 伤害 = (基础+力量) × 脆弱1.5 × 虚弱0.75，多段逐段算，护甲先吸收；
  · 护甲 = 牌值 ×（有脆弱则 0.75），玩家回合结束清零（敌方保留节奏简化）；
  · debuff 有持续时间（回合数递减），力量/能力永久；
  · 牌类型 attack/skill/power + 关键词 exhaust（消耗）；power 驻留生效；
  · 敌人按**行为循环**（cycle 索引表）出招，意图预告；elite/boss 分层；
  · 遗物（被动）与药水（一次性主动 use_potion——动作面与真 mod 的
    play_card/end_turn/use_potion 三件套对齐，netcan 契约形状不变）；
  · 地图=分层分叉：每层有若干可达节点（route 动作），像真游戏一样
    "路线选择"也是环境动作集的一部分。
模拟≠真实：这是 T2 沙盒，卡池为 20 张精选，不代表全卡池。
"""
import json
import os
import random

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "cards_enemies.json")


def _st(ent, key):
    """统一状态读取：ent 可为玩家 S / 敌人 dict（都带 "status"）。"""
    status = ent.get("status") or {}
    e = status.get(key)
    return e["n"] if e else 0


def _st_add(S, key, n, turns=None):
    ent = S["status"].setdefault(key, {"n": 0, "turns": None})
    ent["n"] += n
    if turns is not None:
        ent["turns"] = max(ent["turns"] or 0, turns)


def _draw(S, n):
    got = 0
    for _ in range(n):
        if not S["draw_pile"]:
            S["draw_pile"] = [c for c in S["discard_pile"]
                              if c not in ("泥", "灼伤")]
            S["discard_pile"] = []
            S["reshuffle"] += 1
        if not S["draw_pile"]:
            break
        S["hand"].append(S["draw_pile"].pop(0))
        got += 1
    return got


class Battle:
    def __init__(self, data, player_hp, deck, enemy_names, rng,
                 relics=(), first_turn=True):
        self.d = data
        self.rng = rng
        self.S = {"hp": player_hp, "block": 0,
                  "energy": data["energy"] + (1 if "奶茶" in relics
                                              and first_turn else 0),
                  "status": {}, "hand": [], "draw_pile": [],
                  "discard_pile": [], "turn": 1, "reshuffle": 0,
                  "powers": {}}
        self.relics = set(relics)
        if "船锚" in relics and first_turn:
            self.S["block"] += self.d["relics"]["船锚"]["n"]
        self.deck = list(deck)
        rng.shuffle(self.deck)
        self.S["draw_pile"] = self.deck[:]
        self.enemies = []
        for i, en in enumerate(enemy_names):
            proto = self.d["enemies"][en]
            self.enemies.append({
                "slot": i, "name": en, "hp": proto["hp"], "block": 0,
                "status": {}, "moves": proto["moves"],
                "cycle": proto.get("cycle", list(range(len(proto["moves"])))),
                "ci": 0, "intent": None})
        self._roll_intents()
        _draw(self.S, self.d["hand_size"])
        self.over = None
        self.log = []

    # ── 伤害/护甲结算（一代公式）──────────────────────────
    def _out_dmg(self, base):
        d = base + _st(self.S, "力量")
        if _st(self.S, "虚弱"):
            d = int(d * 0.75)
        return d

    def _hit(self, e, dmg):
        real = int(dmg * 1.5) if _st(e, "脆弱") else dmg
        blk = min(e["block"], real)
        e["block"] -= blk
        e["hp"] -= (real - blk)

    def _deal(self, fx):
        base = fx["n"]
        hits = fx.get("hits", 1)
        if fx["op"] == "damage":
            tgt = self._target(fx)
            if tgt is None:
                return []
            for _ in range(hits):
                self._hit(tgt, self._out_dmg(base))
            return [("伤害", base * hits, tgt["name"])]
        d = self._out_dmg(base)
        for e in self.alive():
            for _ in range(hits):
                self._hit(e, d)
        return [("群伤", d * hits)]

    def _target(self, fx):
        al = self.alive()
        forced = getattr(self, "_forced_target", None)
        if forced is not None and forced["hp"] > 0:
            return forced
        if not al:
            # 多段效果卡把最后一只怪打死后续段目标=无（world 自身
            # 18:5x 崩溃修正：旧版 al[0] 对空列表取下标 IndexError）
            return None
        return min(al, key=lambda e: e["hp"])

    def alive(self):
        return [e for e in self.enemies if e["hp"] > 0]

    # ── 接口：snapshot / actions / apply ──────────────────
    def snapshot(self):
        S = self.S
        return {"turn": S["turn"], "hp": S["hp"], "block": S["block"],
                "energy": S["energy"],
                "status": {k: v["n"] for k, v in S["status"].items()},
                "powers": dict(S["powers"]),
                "hand": list(S["hand"]), "hand_idx": list(range(len(S["hand"]))),
                "draw_pile": len(S["draw_pile"]),
                "discard_pile": len(S["discard_pile"]),
                "enemies": [{"name": e["name"], "hp": e["hp"],
                             "block": e["block"],
                             "status": {k: v["n"] for k, v in
                                        e["status"].items()},
                             "intent": (e["intent"] or {}).get("name"),
                             "intent_tags": (e["intent"] or {}).get("tags"),
                             "intent_damage": (e["intent"] or {}).get(
                                 "damage"),
                             "intent_hits": (e["intent"] or {}).get("hits", 1)}
                            for e in self.enemies],
                "over": self.over}

    def situation_signature(self):
        tags = set()
        for e in self.enemies:
            if e["hp"] > 0 and e["intent"]:
                tags.update(e["intent"].get("tags", []))
        return ",".join(sorted(tags)) or "无"

    def actions(self):
        if self.over:
            return []
        S = self.S
        acts = [{"id": "end_turn", "desc": "结束回合"}]
        if S.get("potion") and S["potion"] != "-":
            acts.append({"id": f"use_potion:{S['potion']}",
                         "tags": ["药水"], "cost": 0})
        targets = self.alive()
        for i, cname in enumerate(S["hand"]):
            c = self.d["cards"][cname]
            if c["cost"] > S["energy"]:
                continue
            base = {"card": cname, "tags": c["tags"],
                    "cost": c["cost"], "ctype": c["type"]}
            multi = any(f["op"] == "damage" for f in c["fx"]) \
                and len(targets) > 1
            if multi:
                for t in targets:
                    acts.append(dict(base, id=f"play:{i}:{t['name']}",
                                     target=t["name"]))
            else:
                acts.append(dict(base, id=f"play:{i}"))
        return acts

    def apply(self, action_id):
        if self.over:
            return {"ok": False, "reason": "battle_over"}
        legal = {a["id"]: a for a in self.actions()}
        if action_id not in legal:
            return {"ok": False, "reason": "illegal_action",
                    "legal_subset": list(legal)[:10]}
        a = legal[action_id]
        S = self.S
        if action_id == "end_turn":
            self._end_turn()
            return {"ok": True, "effects": [("回合", S["turn"])],
                    "state_after": self.snapshot()}
        if action_id.startswith("use_potion"):
            pid = a["id"].split(":")[1]
            fx_list = self.d["potions"][pid]["fx"]
            effs = self._run_fx(fx_list, None)
            S["potion"] = "-"
            return {"ok": True, "effects": effs,
                    "state_after": self.snapshot()}
        idx = int(a["id"].split(":")[1])
        cname = a["card"]
        c = self.d["cards"][cname]
        S["energy"] -= c["cost"]
        if "target" in a:
            self._forced_target = next(
                e for e in self.enemies if e["name"] == a["target"])
        effs = self._run_fx(c["fx"], c)
        self._forced_target = None
        S["hand"].pop(idx)
        if "exhaust" in (c.get("keywords") or []):
            effs.append(("消耗", cname))
        else:
            S["discard_pile"].append(cname)
        if not self.alive():
            self.over = "won"
        if S["hp"] <= 0:
            self.over = "lost"
        self.log.append({"turn": S["turn"], "play": cname,
                         "sig": self.situation_signature()})
        return {"ok": True, "effects": effs, "state_after": self.snapshot()}

    def _run_fx(self, fx_list, card):
        S = self.S
        effs = []
        for fx in fx_list:
            op = fx["op"]
            if op in ("damage", "damage_all"):
                effs += self._deal(fx)
            elif op == "block":
                b = fx["n"]
                if _st(S, "脆弱"):
                    b = int(b * 0.75)
                S["block"] += b
                effs.append(("护甲", b))
            elif op == "self_buff":
                _st_add(S, fx["key"], fx["n"])
                effs.append(("强化", fx["key"], fx["n"]))
            elif op == "debuff":
                tgt = self._target(fx)
                if tgt is None:
                    effs.append(("无目标", fx["key"], fx["n"]))
                    continue
                ent = tgt["status"].setdefault(
                    fx["key"], {"n": 0, "turns": None})
                ent["n"] += fx["n"]
                ent["turns"] = fx["n"] + 1
                effs.append(("施加", fx["key"], fx["n"]))
            elif op == "draw":
                effs.append(("抽牌", _draw(S, fx["n"])))
            elif op == "hp_loss":
                S["hp"] -= fx["n"]
                effs.append(("自伤", fx["n"]))
            elif op == "power":
                S["powers"][fx["key"]] = S["powers"].get(
                    fx["key"], 0) + fx["n"]
                effs.append(("能力", fx["key"], fx["n"]))
        return effs

    # ── 回合推进 ────────────────────────────────────────
    def _end_turn(self):
        S = self.S
        # 能力驻留：恶魔=每回合+力量；铁皮=回合末自动获得并保留护甲
        if "恶魔" in S["powers"]:
            _st_add(S, "力量", S["powers"]["恶魔"])
        for e in self.enemies:
            if e["hp"] <= 0 or not e["intent"]:
                continue
            mv = e["intent"]
            if mv.get("damage"):
                d = mv["damage"] + _st(e, "力量")
                if _st(e, "虚弱"):
                    d = int(d * 0.75)
                for _ in range(mv.get("hits", 1)):
                    real = d
                    if _st(S, "脆弱"):
                        real = int(d * 1.5)
                    blk = min(S["block"], real)
                    S["block"] -= blk
                    S["hp"] -= (real - blk)
            if mv.get("block"):
                e["block"] += mv["block"]
            for k, n in (mv.get("self_buff") or {}).items():
                ent = e["status"].setdefault(k, {"n": 0, "turns": None})
                ent["n"] += n
            for k, n in (mv.get("debuff") or {}).items():
                ent = S["status"].setdefault(k, {"n": 0, "turns": None})
                ent["n"] += n
                ent["turns"] = n + 1
        # 铁甲：保留护甲基础值
        keep = S["powers"].get("铁皮", 0)
        S["block"] = keep
        S["discard_pile"] += S["hand"]
        S["hand"] = []
        _tick(S["status"])
        for e in self.enemies:
            _tick(e["status"])
        if S["hp"] <= 0:
            self.over = "lost"
            return
        S["turn"] += 1
        S["energy"] = self.d["energy"]
        _draw(S, self.d["hand_size"])
        self._advance_enemies()

    def _advance_enemies(self):
        for e in self.enemies:
            if e["hp"] <= 0:
                continue
            e["ci"] = (e["ci"] + 1) % len(e["cycle"])
            e["intent"] = e["moves"][e["cycle"][e["ci"]]]

    def _roll_intents(self):
        for e in self.enemies:
            e["ci"] = 0
            e["intent"] = e["moves"][e["cycle"][0]]


def _tick(status):
    """debuff 时长递减：到期移除（力量等 turns=None 永久项不动）。"""
    for k in list(status):
        ent = status[k]
        if ent.get("turns") is not None:
            ent["turns"] -= 1
            if ent["turns"] <= 0:
                del status[k]


class Run:
    """整局：地图分层分叉 + 精英 + 遗物 + 药水 + 奖励。"""

    def __init__(self, seed=0):
        self.d = json.load(open(_DATA_PATH, encoding="utf-8"))
        self.rng = random.Random(seed)
        self.hp = self.d["player_hp"]
        self.deck = (["打击"] * 5 + ["防御"] * 4 + ["抖肩", "怒吼"])
        self.floor = 0
        self.status = "map"
        self.battle = None
        self.rewards = None
        self.relics = ["燃烧之血"]
        self.potion = "-"
        self.last_enemy = None

    def _open_node(self, node):
        kind, _, en = node.partition(":")
        if kind == "休整":
            self.hp = min(self.d["player_hp"], self.hp + 18)
            self.status = ("victory" if self.floor >= len(
                self.d["map"]) else "map")
            return
        if kind == "宝藏":
            got = ("船锚" if "船锚" not in self.relics else "奶茶")
            self.relics.append(got)
            self.status = ("victory" if self.floor >= len(
                self.d["map"]) else "map")
            return
        self.battle = Battle(self.d, self.hp, self.deck, [en], self.rng,
                             relics=self.relics)
        self.battle.S["potion"] = self.potion
        self.status = "running"
        self.last_enemy = en

    def _routes(self):
        return self.d["map"][self.floor] if self.floor < len(
            self.d["map"]) else []

    def snapshot(self):
        base = {"floor": self.floor, "hp": self.hp,
                "deck_n": len(self.deck), "status": self.status,
                "relics": list(self.relics), "potion": self.potion,
                "routes": self._routes(), "rewards": self.rewards}
        if self.battle and self.status == "running":
            base.update(self.battle.snapshot())
        return base

    def actions(self):
        if self.status == "map":
            return [{"id": f"route:{i}", "desc": r}
                    for i, r in enumerate(self._routes())]
        if self.status == "reward":
            return ([{"id": f"pick:{c}", "desc": f"奖励 {c}"}
                     for c in self.rewards]
                    + [{"id": "skip", "desc": "跳过"}])
        if self.battle and self.status == "running":
            return self.battle.actions()
        return []

    def apply(self, action_id):
        if self.status == "map":
            routes = self._routes()
            if action_id.startswith("route:") and                     int(action_id[6:]) < len(routes):
                self.floor += 1
                self._open_node(routes[int(action_id[6:])])
                return {"ok": True, "effects": [("路线", action_id)]}
            return {"ok": False, "reason": "illegal_action"}
        if self.status == "reward":
            if action_id == "skip":
                self.status = "map"
                return {"ok": True, "effects": [("跳过奖励",)]}
            if action_id.startswith("pick:"):
                card = action_id[5:]
                if card in self.rewards:
                    self.deck.append(card)
                    self.status = "map"
                    return {"ok": True, "effects": [("获得", card)]}
            return {"ok": False, "reason": "illegal_action"}
        r = self.battle.apply(action_id) if self.battle else             {"ok": False, "reason": "no_battle"}
        if self.battle and self.battle.over == "won":
            self.hp = self.battle.S["hp"]
            self.potion = self.battle.S.get("potion", "-")
            if "燃烧之血" in self.relics:
                self.hp = min(self.d["player_hp"],
                              self.hp + self.d["relics"]["燃烧之血"]["n"])
            proto = self.d["enemies"][self.last_enemy]
            if proto.get("elite") or proto.get("boss"):
                if self.potion == "-":
                    self.potion = self.rng.choice(list(self.d["potions"]))
                if proto.get("elite") and "船锚" not in self.relics:
                    self.relics.append("船锚")
            self.battle = None
            if self.floor >= len(self.d["map"]):
                self.status = "victory"
            else:
                self.rewards = self._roll_reward()
                self.status = "reward"
            r["battle_result"] = "won"
        elif self.battle and self.battle.over == "lost":
            self.status = "dead"
            r["battle_result"] = "lost"
        return r

    def _roll_reward(self):
        pool = [c for c in self.d["cards"] if c not in self.deck
                or self.d["cards"][c]["type"] == "attack"]
        pool = [c for c in pool if self.deck.count(c) < 3] or ["打击"]
        return self.rng.sample(pool, min(3, len(pool)))
