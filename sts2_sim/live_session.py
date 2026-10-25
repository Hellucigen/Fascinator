# -*- coding: utf-8 -*-
"""sts2_sim.live_session — 把一局 STS2 作为"一次活动"跑完的可重入会话层。

（2026-10-16 生活整合）scripts/live_sts2_play.py 是独立驱动进程；本模块把
同一决策链收进函数：transport 抽象（真实 mod HTTP / 测试脚本回放），
预算内运行，产出结构化结果供 activities 结算走**通用**反馈通道。

边界（诚实纪律）：
  · game_kg 是私有决策图（机制知识+当局经验），不碰生产图谱；生产图
    只由调用方在结算时写回结论（概念节点/兴趣/偏好边/时间轴）。
  · 未知/不可读结果一律 result="unknown"，不伪装胜负。
"""
import json
import time
import urllib.error
import urllib.request

KB_ROOT = None  # 延迟 import 防循环


class ModTransport:
    """真实链路：STS2 AI Agent mod REST（127.0.0.1:8080，v0.16.2 实测）。
    生活拍纪律：读 409/超时只短重试 3×0.7s（与独立驱动的 30s 长等待不同，
    活动会话不能把心跳挂起）。"""

    def __init__(self, base="http://127.0.0.1:8080", timeout=3.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _req(self, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data,
            method="POST" if data else "GET",
            headers={"Content-Type": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code in (409, 500, 502, 503) and attempt < 2:
                    time.sleep(0.7)
                    continue
                raise
            except urllib.error.URLError:
                if attempt < 2:
                    time.sleep(0.7)
                    continue
                raise
        return {"ok": False}

    def health(self):
        try:
            r = self._req("/health")
            return bool((r.get("data") or {}).get(
                "status") == "ready") if r else False
        except Exception:                                # noqa: BLE001
            return False

    def state(self):
        return self._req("/state")["data"]

    def action(self, body):
        return self._req("/action", body)


class ScriptedTransport:
    """测试回放：states 依次弹出；actions 按 (state 序号, body) 由脚本判定。
    脚本表 rules: {步序号: {"actions": [期望动作...], "states": [注入状态]}}
    简化：每拍先弹一个预置 state；post 恒 ok 并记录。"""

    def __init__(self, states, health_ok=True):
        self.states = list(states)
        self.calls = []
        self.health_ok = health_ok

    def health(self):
        return self.health_ok

    def state(self):
        if not self.states:
            raise urllib.error.URLError("script exhausted")
        return self.states.pop(0)

    def action(self, body):
        self.calls.append(body)
        return {"ok": True, "data": {"status": "completed"}}


_INTENT_TAG = {"Attack": "攻击", "Buff": "强化", "Debuff": "削弱",
               "Defend": "防御", "Escape": "移动"}


def _map_state(d, game_kg):
    """真实 /state → kb 的 snap 形状（与 live_sts2_play 同一映射，
    单一口径在此实现；驱动脚本后续可收敛到这里）。"""
    from sts2_sim import kb, card_parser as CP
    c = d.get("combat") or {}
    p = c.get("player") or {}
    enemies = []
    for e in c.get("enemies") or []:
        if not e.get("is_alive"):
            continue
        ints = e.get("intents") or []
        dmg = max([int(i.get("total_damage") or 0) for i in ints] or [0])
        hits = max([int(i.get("hits") or 1) for i in ints] or [1])
        tags = sorted({_INTENT_TAG.get(i.get("intent_type"),
                                       str(i.get("intent_type")))
                       for i in ints if i.get("intent_type")})
        enemies.append({"name": e.get("name"), "hp": e.get("current_hp"),
                        "block": e.get("block") or 0, "status": {},
                        "intent": str(ints[0].get("intent_type"))
                        if ints else None,
                        "intent_tags": tags, "intent_damage": dmg,
                        "intent_hits": hits})
    snap = {"hp": p.get("current_hp"), "block": p.get("block") or 0,
            "energy": p.get("energy") or 0, "max_hp": p.get("max_hp") or 75,
            "hand": [], "hand_idx": [], "status": {}, "enemies": enemies,
            "turn": d.get("turn")}
    idx = {}
    for h in c.get("hand") or []:
        name = h.get("name") or "?"
        text = h.get("resolved_rules_text") or ""
        parsed = CP.parse(name, text, cost=h.get("energy_cost") or 0)
        kb.instantiate_card(game_kg, parsed, name)
        eff = {"damage": 0, "hits": 1, "block": 0, "hp_cost": 0}
        for m in parsed.get("effects") or []:
            mech, prm = m.get("mechanic") or "", m.get("params") or {}
            if mech == "M.attack_damage" and prm.get("damage"):
                if prm["damage"] > eff["damage"]:
                    eff["damage"] = prm["damage"]
                    eff["hits"] = prm.get("hits", 1)
            elif mech == "M.block" and prm.get("block"):
                eff["block"] += prm["block"]
            elif mech == "M.hp_loss" and prm.get("amount"):
                eff["hp_cost"] += prm["amount"]
        snap["hand"].append(name)
        snap["hand_idx"].append(h["index"])
        idx[name] = eff
    return snap, idx, {h["index"]: h for h in (c.get("hand") or [])}


def play_session(transport, game_kg, game_eng, budget_s=300.0,
                 max_steps=400, config=None, log=None,
                 allow_embark=True, gaming_probe=None):
    """跑一段活动：可选登船开局 → 决策出牌 → 直到 胜/败/预算尽/连接断。
    返回 {result, floor, turns, run_id, new_mechanics, steps}。
    result ∈ victory | defeat | aborted | yielded | unknown。"""
    from sts2_sim import kb

    class _Counted:
        """动作计数代理：让渡检测要区分屏幕变化是"她的动作驱动的"还是
        "别人在上手"（2026-10-16 用户规则：用户中途玩游戏时她保存退出，
        不抢运存与屏幕；她的每个动作都当步发出，quiet 会被清零）。
        被拒动作温和化（2026-10-17 floor14 实锤）：mod 对"领不了的奖励"
        （药水库满的 Potion）返回 HTTP 异常而非 ok:false，异常穿透会
        炸掉整个会话、绕过所有"不判死"分支——在这里收敛为 ok False，
        让逐件试领的逻辑真正跑到。"""
        def __init__(self, t): self.t, self.n = t, 0
        def action(self, b):
            self.n += 1
            try:
                return self.t.action(b)
            except Exception as _e:               # noqa: BLE001
                return {"ok": False, "error": str(_e)[:80]}
        def state(self): return self.t.state()
        def health(self): return self.t.health()
    transport = _Counted(transport)
    t0 = time.time()
    steps = 0
    run_id = None
    seen_mech = set()
    new_mech = []
    cur = None
    quiet, last_n, prev_screen = 0, 0, None
    _seen_screens = set()      # 观测（2026-10-17）：会话全程零日志=卡住只能猜
    if log:
        log("[sts2] 会话开始 budget=%.0fs max_steps=%d probe=%s"
            % (budget_s, max_steps, gaming_probe is not None))
    try:
        while steps < max_steps and time.time() - t0 < budget_s:
            steps += 1
            n_now = transport.n
            quiet = quiet + 1 if n_now == last_n else 0
            last_n = n_now
            # 用户在玩别的游戏（探针由陪伴侧注入，读 Steam 库进程）：
            # 保存退出，让出运存（2026-10-16 用户规则）。
            if gaming_probe is not None and steps % 2 == 0:
                try:
                    _other = gaming_probe()
                except Exception:                   # noqa: BLE001
                    _other = None
                if _other:
                    if "save_and_quit" in (
                            (transport.state().get("available_actions")
                             or [])):
                        transport.action({"action": "save_and_quit"})
                    if log:
                        log("[sts2] 用户在玩别的游戏 → 保存退出让渡")
                    return {"result": "yielded", "floor": None,
                            "turns": None, "run_id": run_id,
                            "new_mechanics": new_mech, "steps": steps}
            d = transport.state()
            cur = d
            run_id = d.get("run_id") or run_id
            screen = d.get("screen")
            if (prev_screen is not None and screen != prev_screen
                    and quiet >= 3):
                # 她连发三步没动手、画面却换了 → 有人在直接玩游戏：
                # 保存并退出，把这局让给用户（save_and_quit 有存档语义，
                # 不可用就体面离开，不硬抢）。
                if "save_and_quit" in (d.get("available_actions") or []):
                    transport.action({"action": "save_and_quit"})
                if log:
                    log("[sts2] 检测到用户在操作游戏 → 保存退出，让渡对局")
                return {"result": "yielded",
                        "floor": (d.get("run") or {}).get("floor"),
                        "turns": None, "run_id": run_id,
                        "new_mechanics": new_mech, "steps": steps}
            prev_screen = screen
            if log and screen not in _seen_screens:
                _seen_screens.add(screen)
                log("[sts2] 第%d步 屏幕=%s floor=%s" % (
                    steps, screen,
                    (d.get("run") or {}).get("floor")))
            if screen == "COMBAT":
                c = d.get("combat") or {}
                ar = c.get("action_readiness") or {}
                if not ar.get("can_use_combat_actions"):
                    time.sleep(0.5)
                    continue
                snap, idx, handby = _map_state(d, game_kg)
                for o in (c.get("hand") or []):
                    txt = o.get("resolved_rules_text") or ""
                    for k in ("脆弱", "易伤", "虚弱"):
                        if k in txt and ("机制:" + k) not in seen_mech:
                            seen_mech.add("机制:" + k)
                            new_mech.append({"name": "机制:" + k,
                                             "text": txt[:80]})
                    nm = o.get("name")
                    if nm and ("卡牌:" + nm) not in seen_mech:
                        seen_mech.add("卡牌:" + nm)
                        new_mech.append({"name": "卡牌:" + nm,
                                         "text": txt[:80]})
                acts = [{"id": "play_%d" % o["index"],
                         "card": o.get("name") or "?",
                         "cost": int(o.get("energy_cost") or 0)}
                        for o in (c.get("hand") or [])
                        if int(o.get("energy_cost") or 0)
                        <= int(snap["energy"])
                        and int(o.get("star_cost") or 0)
                        <= int((c.get("player") or {}).get("stars") or 0)]
                best, tr = kb.decide_graph(game_kg, game_eng, snap, acts,
                                           idx)
                if best is None:
                    r = transport.action({"action": "end_turn"})
                else:
                    body = {"action": "play_card",
                            "card_index": int(best["id"].split("_")[1])}
                    h = handby.get(body["card_index"]) or {}
                    if h.get("requires_target"):
                        vi = h.get("valid_target_indices") or []
                        if vi:
                            body["target_index"] = min(
                                vi, key=lambda t: next(
                                    (int(e.get("current_hp") or 999)
                                     for e in (c.get("enemies") or [])
                                     if e.get("index") == t), 999))
                    r = transport.action(body)
                    if not r.get("ok"):
                        r = transport.action({"action": "end_turn"})
                continue
            if screen == "GAME_OVER":
                go = d.get("game_over") or {}
                res = "victory" if go.get("is_victory") else \
                    ("defeat" if "character_id" in go else "unknown")
                # 收桌（2026-10-17）：结算后确认掉死亡画面，否则下一轮
                # 会话读到 GAME_OVER 又秒退，局永远晾在结算屏。
                if "continue_game_over" in (d.get("available_actions") or []):
                    transport.action({"action": "continue_game_over"})
                return {"result": res, "floor": go.get("floor"),
                        "turns": d.get("turn"), "run_id": run_id,
                        "new_mechanics": new_mech, "steps": steps}
            if screen in ("REWARD", "MAP", "REST", "CHEST", "EVENT",
                          "CARD_SELECTION", "MAIN_MENU", "CHARACTER_SELECT",
                          "SHOP", "BUNDLE_SELECTION", "MODAL"):
                if not _advance_screen(transport, d, game_kg, game_eng,
                                       config or {}, log):
                    if log:
                        log("[sts2] 会话弃权：%s 推进失败（第%d步）"
                            % (screen, steps))
                    return {"result": "unknown", "exit": "stuck", "floor": (
                        (d.get("run") or {}).get("floor")),
                        "turns": None, "run_id": run_id,
                        "new_mechanics": new_mech, "steps": steps}
                continue
            time.sleep(0.4)
        if log:
            log("[sts2] 会话预算尽（steps=%d, %.0fs）主动离场，局面保留续玩"
                % (steps, time.time() - t0))
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError,
            IndexError, TimeoutError, OSError) as e:
        if log:
            log("session 断链: %s" % str(e)[:80])
        return {"result": "unknown", "floor": (
            (cur or {}).get("run") or {}).get("floor"),
            "turns": None, "run_id": run_id,
            "new_mechanics": new_mech, "steps": steps}
    # exit=budget：预算尽、局未终——结算不得按"念头已兑现"消耗欲望
    # （2026-10-17 语义修正：f15 离场被当 aborted 打 0.6 折，"没做完"
    # 反而让念头变凉，下一拍就撂挑子；没做完的事张力应保留）。
    return {"result": "aborted", "exit": "budget", "floor": (
        (cur or {}).get("run") or {}).get("floor"),
        "turns": (cur or {}).get("turn"), "run_id": run_id,
        "new_mechanics": new_mech, "steps": steps}


def _advance_screen(transport, d, kg, eng, config, log):
    """非战斗屏推进：复用 kb.decide_choice 语义通道。返回 False=走不下去。"""
    screen = d.get("screen")
    avail = d.get("available_actions") or []
    run = d.get("run") or {}
    hp = int(run.get("current_hp") or 0)
    mx = int(run.get("max_hp") or 75)
    gold = int(run.get("gold") or 0)
    ctx = {"hp_r": (hp / mx if mx else 1.0), "rich": min(1.0, gold / 200.0),
           "gold": gold}

    def opts_from(items, text_key=("resolved_rules_text", "description")):
        from sts2_sim import kb as _kb2
        out = []
        for o in items:
            txt = ""
            for k in text_key:
                txt = txt or (o.get(k) or "")
            feats, inh = _kb2.parse_features(txt or "", ctx["hp_r"])
            out.append({"key": o.get("index"), "name": o.get("name") or "?",
                        "feats": feats, "inhib": inh})
        return out

    def pick_or_none(options):
        if not options:
            return None
        from sts2_sim import kb as _kb
        pk, _tr = _kb.decide_choice(kg, eng, "sts2活动", options, ctx)
        return pk

    try:
        if screen == "MAIN_MENU":
            # 主菜单有两种态：可直接去选角（新开一局）；或存在未完成
            # 旧局（动作表只有 continue_run/abandon_run）——续上旧局
            # 也是玩，abandon 有确认语义不自动碰（2026-10-16 实测）。
            if "open_character_select" in avail:
                return transport.action(
                    {"action": "open_character_select"}).get("ok", False)
            if "continue_run" in avail:
                return transport.action(
                    {"action": "continue_run"}).get("ok", False)
            return False
        if screen == "MODAL":
            # 弹窗遮挡（2026-10-16 探针实锤：开选角后 MODAL 挡住
            # character_select 载荷，会话误判"无人可选"而弃权）。只
            # dismiss（无害关闭）；confirm 有确认语义（如 abandon_run
            # 走的就是 modal），与旧局确认规则一致——绝不自动碰。
            if "dismiss_modal" in avail:
                return transport.action({"action": "dismiss_modal"}).get(
                    "ok", False)
            return False
        if screen == "CHARACTER_SELECT":
            cs = d.get("character_select") or {}
            if "characters" not in cs:
                # 载荷缺失=弹窗遮挡/界面过渡中的空帧：不是"没角色可选"，
                # 等下一步（MODAL 分支会处理遮挡）。真无人可选由下面
                # 空列表分支判定。
                return True
            ch = [x for x in (cs.get("characters") or [])
                  if not x.get("is_locked")]
            if not cs.get("can_embark"):
                if not ch:
                    return False
                import sts2_sim.kb as _kb
                opts = []
                for x in ch:
                    f = [("延迟收益", 0.25)]
                    if x.get("name") == "储君":
                        f.append(("期望收益", 0.15))
                    opts.append({"key": x["index"],
                                 "name": x.get("name") or "?",
                                 "feats": f, "inhib": []})
                pk, _t = _kb.decide_choice(kg, eng, "角色", opts,
                                           {"hp_r": 1.0, "rich": 0.5})
                return transport.action({"action": "select_character",
                                         "option_index": (pk or
                                                          opts[0])["key"]
                                         }).get("ok", False)
            if not config.get("sts2_embark", True):
                return False
            return transport.action({"action": "embark"}).get("ok", False)
        if screen == "BUNDLE_SELECTION":
            # 开局礼包（2026-10-16 卡死根因）：play_session 主循环与
            # 本状态机此前都没有 BUNDLE_SELECTION 分支，会话在兜底
            # sleep 上空烧满 400 步 budget 后 aborted（战报实锤：
            # steps=400/floor=1）。卡组是真实可判信息：走统一语义
            # 管线（decide_choice），不是拍脑袋固定选 0。
            bundles = d.get("bundles") or []
            # 两种真实形态（2026-10-17 实测定格）：①未领——bundles 有
            # 列表，choose_bundle 选一个；②已领——卡组已入手、bundles
            # 空、界面等 confirm_modal 确认（01:30 失败即此态被误判死）。
            if not bundles:
                # 实测动作名是 confirm_bundle（01:44 二次失败教训：
                # 先写死 confirm_modal 又扑空）。按 avail 匹配，兼容
                # 通用 confirm_modal 形态。
                for _a in ("confirm_bundle", "confirm_modal"):
                    if _a in avail:
                        return transport.action({"action": _a}).get(
                            "ok", False)
                return False
            if "choose_bundle" not in avail:
                return False
            import sts2_sim.kb as _kb
            opts = []
            for b in bundles:
                txt = " ".join(
                    (c.get("resolved_rules_text") or c.get("rules_text")
                     or "") + " " + str(c.get("name") or "")
                    for c in (b.get("cards") or []))
                f, i = _kb.parse_features(txt, ctx["hp_r"])
                opts.append({"key": b.get("index"),
                             "name": "+".join(str(c.get("name") or "?")
                                              for c in (b.get("cards") or [])),
                             "feats": f, "inhib": i})
            pk = pick_or_none(opts)
            return transport.action({"action": "choose_bundle",
                                     "option_index": (pk or opts[0])["key"]
                                     }).get("ok", False)
        if screen == "MAP":
            nodes = (d.get("map") or {}).get("available_nodes") or []
            if not nodes:
                return False
            _TXT = {"Treasure": "获得一个遗物 永久", "Rest": "回复 休息",
                    "Shop": "获得 金币 永久", "Monster": "战斗",
                    "Elite": "战斗 精英 获得 升级", "Boss": "战斗 精英 获得",
                    "Unknown": "", "Event": ""}
            import sts2_sim.kb as _kb
            opts = []
            for n0 in nodes:
                f, i = _kb.parse_features(
                    _TXT.get(n0.get("node_type"), ""), ctx["hp_r"])
                opts.append({"key": n0["index"],
                             "name": str(n0.get("node_type")),
                             "feats": f, "inhib": i})
            pk = pick_or_none(opts)
            return transport.action({"action": "choose_map_node",
                                     "option_index": (pk or
                                                      opts[0])["key"]
                                     }).get("ok", False)
        if screen == "REWARD":
            rw = d.get("reward") or {}
            if rw.get("pending_card_choice"):
                opts = opts_from(rw.get("card_options") or [])
                opts.append({"key": "skip", "name": "不拿卡",
                             "feats": [("风险", 0.18)], "inhib": []})
                pk = pick_or_none(opts)
                if pk and pk["key"] != "skip":
                    return transport.action({"action": "choose_reward_card",
                                             "option_index": pk["key"]
                                             }).get("ok", False)
                return transport.action(
                    {"action": "skip_reward_cards"}).get("ok", True)
            claims = [x for x in (rw.get("rewards") or [])
                      if x.get("claimable")]
            if claims:
                # 领取被拒（药水库满时 Potion 奖励仍标 claimable；或动作
                # 撞上转场动画 409）——逐件试，全拒则尝试离开。**离开被拒
                # 也不判死**（2026-10-17 floor14 实锤：领取动画期间的瞬时
                # 拒绝让 return False 杀会话，奖励屏又卡住）：返回 True
                # 等下一拍，动画几秒即完，会话预算自然兜底上限。
                for x in claims:
                    if transport.action({"action": "claim_reward",
                                         "option_index": x["index"]}).get("ok"):
                        return True
                transport.action({"action": "collect_rewards_and_proceed"})
                return True
            transport.action({"action": "collect_rewards_and_proceed"})
            return True
        if screen == "REST":
            en = [o for o in (d.get("rest") or {}).get("options") or []
                  if o.get("is_enabled")]
            if not en:
                step = next((a for a in avail if a in
                             ("proceed", "leave_rest", "confirm")), None)
                return bool(step) and transport.action(
                    {"action": step}).get("ok", False)
            opts = opts_from(en, ("description", "title"))
            pk = pick_or_none(opts)
            return transport.action({"action": "choose_rest_option",
                                     "option_index": (pk or
                                                      opts[0])["key"]
                                     }).get("ok", False)
        if screen == "EVENT":
            opts = opts_from((d.get("event") or {}).get("options") or [],
                             ("description", "title"))
            pk = pick_or_none(opts)
            return transport.action({"action": "choose_event_option",
                                     "option_index": (pk or
                                                      opts[0])["key"]
                                     }).get("ok", False)
        if screen == "CARD_SELECTION":
            sel = d.get("selection") or {}
            cards = [c for c in (sel.get("cards") or [])
                     if not c.get("selected")]
            maxn = int(sel.get("max_select") or 1)
            seln = int(sel.get("selected_count") or 0)
            if cards and seln < maxn:
                opts = opts_from(cards)
                pk = pick_or_none(opts)
                return transport.action({"action": "select_deck_card",
                                         "option_index": (pk or
                                                          opts[0])["key"]
                                         }).get("ok", False)
            if "confirm_selection" in avail:
                return transport.action(
                    {"action": "confirm_selection"}).get("ok", False)
            return False
        if screen == "CHEST":
            ch = d.get("chest") or {}
            if not ch.get("is_opened"):
                return transport.action({"action": "open_chest"}).get(
                    "ok", False)
            if not ch.get("has_relic_been_claimed"):
                rels = ch.get("relic_options") or []
                if not rels:
                    return False
                import sts2_sim.kb as _kb
                _RAR = {"Common": 0.22, "Uncommon": 0.30,
                        "Rare": 0.40, "Boss": 0.45}
                lopts = []
                for rel in rels:
                    f, i = _kb.parse_features(rel.get("name") or "", 1.0)
                    f = f + [("延迟收益", _RAR.get(rel.get("rarity"), 0.25))]
                    lopts.append({"key": rel.get("index"),
                                  "name": rel.get("name") or "?",
                                  "feats": f, "inhib": i})
                pk, _t = _kb.decide_choice(kg, eng, "遗物", lopts,
                                           {"hp_r": 1.0, "rich": 0.5})
                pick0 = pk or lopts[0]
                return transport.action(
                    {"action": "choose_treasure_relic",
                     "option_index": pick0["key"]}).get("ok", False)
            return transport.action({"action": "proceed"}).get("ok", False)
        if screen == "SHOP":
            return transport.action({"action": "proceed"}).get("ok", False)
        if screen == "GAME_OVER":
            for step in ("continue_game_over", "return_to_main_menu"):
                if step in avail:
                    return transport.action({"action": step}).get(
                        "ok", False)
            return False
    except Exception:                                   # noqa: BLE001
        if log:
            log("advance 失败 %s" % screen)
    return False
