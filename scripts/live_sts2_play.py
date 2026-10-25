# -*- coding: utf-8 -*-
"""图一元大脑真实游戏驱动（2026-10-15 用户批准"打"）。

安全边界：只向 127.0.0.1 的 mod API 出手；每步动作都打印依据；
snapshot 不稳定就等；失败动作不重试第二次（防卡循环）；游戏结束/
连不上即停。经验持久化在 sts2_sim/live_experience.json（跨进程积累）。
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error

sys.path.insert(0, ".")
sys.path.insert(0, "../FAS-Cognitive")
from graph_model import KnowledgeGraph, Edge, Node                    # noqa
from diffusion_engine import DiffusionEngine                          # noqa
from sts2_sim import kb, card_parser as CP                            # noqa
from sts2_sim import knowledge_graph as KG                            # noqa
import config as CF                                                   # noqa

BASE = "http://127.0.0.1:8080"
EXP = os.path.join("sts2_sim", "live_experience.json")
MAX_STEPS = 3000

# ── Charon 可视化分接（2026-10-15）：模块内 print 即全量事件流，
# topic=fas.sts2 供前端 EventsOn；同文 60s 去抖；Charon 挂了不影响驱动。
# 里程碑（启动/登船/局终）另投 /api/fleeting 便签流，肉眼可扫。──
try:
    from fas.companion.charon_bridge import CharonBridgeChannel
    _CHARON = CharonBridgeChannel()
    if not _CHARON._ensure_config():
        _CHARON = None
except Exception:
    _CHARON = None
_prt = print
_last = {"line": None, "ts": 0.0}
_CTX = {"floor": None, "turn": None, "hp": None, "run": 1}
_EMO = [("出分", "⚔️"), ("结束回合", "⏭️"), ("被拒", "⚠️"),
        ("局结束", "💀"), ("败局反灌", "📉"), ("经验", "🧠"),
        ("登船", "🚢"), ("选角色", "🎭"), ("奖励", "🎁"), ("选卡", "🃏"),
        ("地图", "🗺️"), ("篝火", "🔥"), ("宝箱", "📦"), ("事件", "🎭"),
        ("结算", "🔄"), ("主菜单", "🏠"), ("驱动启动", "🚀"),
        ("界面", "⏳"), ("回合", "🂠")]
_MILE = ("驱动启动", "登船", "局结束")


def print(*a, flush=True, **k):            # 模块级 tee
    _prt(*a, **k)
    if _CHARON is None:
        return
    line = " ".join(str(x) for x in a)
    now = time.time()
    if _last["line"] == line and now - _last["ts"] < 60:
        return
    _last["line"], _last["ts"] = line, now
    text = line.replace("[live]", "").strip()
    emo = next((e for kw, e in _EMO if kw in line), "·")
    _CHARON._post("/api/events", {"topic": "fas.sts2", "payload": {
        "kind": "sts2log", "emoji": emo, "text": text,
        "floor": _CTX["floor"], "turn": _CTX["turn"],
        "hp": _CTX["hp"], "run": _CTX["run"], "ts": int(now)}})
    if any(m in line for m in _MILE):
        _CHARON._post("/api/fleeting", {
            "body": "%s STS2｜%s" % (emo, text),
            "tags": ["sts2", "第%s局" % _CTX["run"],
                     "层%s" % (_CTX["floor"] if _CTX["floor"] is not None
                               else "?")]})
    # 战报里程碑借道 fas.utterance：Charon 现装二进制已订阅此 topic
    # （说话面板+FAS 记忆都会显示），逐手出牌不进（防气泡刷屏），
    # 全量流水仍在 fas.sts2 账本可回读。origin=sts2 前端只做标签。
    if any(m in line for m in ("驱动启动", "登船", "局结束", "败局反灌",
                               "药水 →", "宝箱 → 拿遗物", "篝火(",
                               "事件[", "商店(", "商店买", "选卡 →")):
        _CHARON._post("/api/events", {"topic": "fas.utterance", "payload": {
            "text": "🎮 %s｜%s" % (emo, text), "origin": "sts2"}})


def api(path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"})
    # 转场/结算瞬间 mod 会以 409 拒读拒写（实测 2026-10-15）：
    # 这不是断连，等它稳定后重试，最多 10 次。
    for attempt in range(30):
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            # 409 只重试读（转场拒读；实测动画期可超过 7s，放宽到 30s）；
            # 写的 409 是语义拒绝（实测 2026-10-15：需目标卡不带
            # target_index 直接 409），重试同一请求永远不会成功——
            # 立即上抛交给 do_action
            if e.code == 409 and data is not None:
                raise        # 写拒绝交给 do_action 补目标重试
            if e.code in (409, 500, 502, 503) and attempt < 29:
                time.sleep(1.0)
                continue
            return {"ok": False, "error": {"code": "http_%d" % e.code}}
        except (urllib.error.URLError, TimeoutError, OSError):
            # 裸 TimeoutError（recv 超时不包 URLError，2026-10-15 实测）
            if attempt < 29:
                time.sleep(1.0)
                continue
            return {"ok": False, "error": {"code": "conn_exhausted"}}


def get_state():
    r = api("/state")
    if not r.get("ok", True) and "data" not in r:
        # 转场/断连读失败：等一拍返回上一秒形状的可能没有，交回主循环
        # 用 screen=None 走 else 等待分支（不抛、不退出）
        time.sleep(1.0)
        return {"screen": None, "available_actions": []}
    return r["data"]


kg = KnowledgeGraph()
kg.save = lambda *a, **k: None
cfgd = dict(CF.DEFAULT_CONFIG)
cfgd["diffusion_mode"] = "cascade"
eng = DiffusionEngine(kg, cfgd)
kb.import_kb(kg)
kb.link_to_general(kg)
kb.import_powers(kg)

# 跨进程经验加载：response 边 + 卡校准分（存 JSON，重启不丢学习）
if os.path.exists(EXP):
    try:
        old = json.load(open(EXP, encoding="utf-8"))

        def _stub(nid):
            # 经验先于卡面存在：加载时补端点节点，否则上一局的教训
            # 全部被 add_edge 丢弃（2026-10-15 实测 8 条边全丢）。
            if kg.get_node(nid) is None:
                tag = str(nid).startswith("标签:")
                kg.add_node(Node(id=nid, weight=0.45 if tag else 0.5,
                                 label="declarative-semantic",
                                 extra_attrs={"type": "sts_tag" if tag
                                              else "card_instance",
                                              "kind": "kb"}))
        for rec in old.get("response_edges", []):
            _stub(rec["src"])
            _stub(rec["dst"])
            if kg.get_edge(rec["src"], rec["dst"], "针对") is None:
                kg.add_edge(Edge(src=rec["src"], dst=rec["dst"],
                                 relation="针对", weight=rec["weight"],
                                 extra_attrs={"kind": "response",
                                              "evidence": "live"}))
        for cid, cal in (old.get("calib") or {}).items():
            _stub(cid)
            n = kg.get_node(cid)
            if n is not None:
                ea = n.extra_attrs or {}
                ea["calib"] = cal
                n.extra_attrs = ea
        print("[live] 跨局经验加载：边 %d 条｜卡校准 %d 张"
              % (len(old.get("response_edges") or []),
                 len(old.get("calib") or {})), flush=True)
    except Exception as e:
        print("经验加载失败（继续，从零学）:", str(e)[:80])


def persist_exp():
    resp = [{"src": e.src, "dst": e.dst, "weight": float(e.weight)}
            for e in kg.edges
            if isinstance(e.extra_attrs, dict)
            and e.extra_attrs.get("kind") == "response"]
    cal = {nid: float((n.extra_attrs or {}).get("calib") or 0.7)
           for nid, n in kg.nodes.items()
           if str((n.extra_attrs or {}).get("type") or "") == "card_instance"}
    json.dump({"response_edges": resp, "calib": cal},
              open(EXP, "w", encoding="utf-8"), ensure_ascii=False)


_INTENT_TAG = {"Attack": "攻击", "Buff": "强化", "Debuff": "削弱",
               "Defend": "防御", "Escape": "移动"}


def map_state(d):
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
        # 卡的学习身份=卡名（同名卡共享节点，重复由 action 位区分）。
        # 曾用 "%s#%d" 带手牌位做 id，导致经验边(Card:打击)找不到
        # 节点(Card:打击#1)被丢弃——2026-10-15 修回。
        key = h.get("name") or "?"
        text = h.get("resolved_rules_text") or ""
        parsed = CP.parse(key, text, cost=h.get("energy_cost") or 0)
        kb.instantiate_card(kg, parsed, key)
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
        snap["hand"].append(key)
        snap["hand_idx"].append(h["index"])
        idx[key] = eff
    return snap, idx, {h["index"]: h for h in (c.get("hand") or [])}


def pick_target(h, enemies_raw):
    """需目标卡：合法索引内选最低血敌人（斩杀优先，客观规则非策略）。"""
    vi = h.get("valid_target_indices") or []
    if not vi:
        return None
    by_idx = {e.get("index"): e for e in enemies_raw or []}
    cand = [t for t in vi if t in by_idx and by_idx[t].get("is_alive")]
    if not cand:
        cand = list(vi)
    return min(cand, key=lambda t: by_idx[t].get("current_hp", 999)
               if t in by_idx else 999)


def do_action(body, log, handby=None, enemies_raw=None):
    """POST /action。需目标的卡预先补 target_index（409 教训 2026-10-15）；
    若仍 409 且带卡动作，补一次合法目标重试。"""
    if body.get("action") == "play_card" and handby:
        h = handby.get(body.get("card_index")) or {}
        if h.get("requires_target"):
            t = pick_target(h, enemies_raw)
            if t is not None:
                body = dict(body, target_index=t)
    try:
        return api("/action", body)
    except urllib.error.HTTPError as e:
        if e.code == 409 and body.get("action") == "play_card" \
                and handby and "target_index" not in body:
            h = handby.get(body.get("card_index")) or {}
            t = pick_target(h, enemies_raw)
            if t is not None:
                log("      └─ 409 补目标 target_index=%s" % t)
                try:
                    return api("/action", dict(body, target_index=t))
                except urllib.error.HTTPError as e2:
                    return _http_err(e2)
        return _http_err(e)


def _http_err(e):
    try:
        return json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return {"ok": False, "error": {"code": "http_%d" % e.code}}


steps = 0
played_log = []      # (threat_tags, card_key) 败局反灌用
shop_purchases = []  # (item_name, floor_at_buy) 购物经验回流用
potion_uses = []     # (potion_name, floor_at_use) 用药经验回流用
reward_picks = []    # (card_name, floor_at_pick) 奖励选卡经验回流用
char_pick = [None]   # 本局角色名（局终按层数回灌 标签:角色）
pending_event = [None]  # (选项名, hp前, 金币前, 牌库数前) 事件结果归因
shop_state = {"at": None}   # 已开过库存的店（run_id, floor），防开合死循环
t0 = time.time()
runs = 1
settled_runs = set()   # 已记账的 run_id，防结算页每圈重复计数
print("[live] 驱动启动 %s，多局自开模式，Ctrl+C 随时接管" % BASE, flush=True)
try:
    while steps < 30000 and time.time() - t0 < 14400:
        steps += 1
        d = get_state()
        screen = d.get("screen")
        avail = d.get("available_actions") or []
        r0 = d.get("run") or {}
        _CTX["floor"] = r0.get("floor")
        _CTX["run"] = runs
        _CTX["turn"] = d.get("turn")
        pp0 = (d.get("combat") or {}).get("player") or {}
        if pp0.get("current_hp") is not None:
            _CTX["hp"] = pp0.get("current_hp")
        elif r0.get("current_hp") is not None:
            _CTX["hp"] = r0.get("current_hp")
        # 事件归因：离店式差分记账（hp/金币/牌库三读数 = 世界的回答）
        if pending_event[0] and screen != "EVENT":
            name0, hp0, g0, dk0 = pending_event[0]
            hp1 = int(r0.get("current_hp") if r0.get("current_hp")
                      is not None else hp0)
            g1 = int(r0.get("gold") if r0.get("gold") is not None else g0)
            dk1 = len(r0.get("deck") or [])
            cr = 0.0
            loss = hp0 - hp1
            if loss > 0:
                cr -= 1.5 + 0.15 * loss
            elif hp1 > hp0:
                cr += 1.0
            if dk1 > dk0:
                cr += 2.0
            cr += max(-2.0, min(2.0, (g1 - g0) * 0.04))
            if abs(cr) >= 0.5:
                kb.choice_credit(kg, "事件", name0, cr)
                print("[live] 事件归因 %s → %+.1f（血%+d 金%+d 牌%+d）"
                      % (name0, cr, hp1 - hp0, g1 - g0, dk1 - dk0),
                      flush=True)
            pending_event[0] = None
        if screen == "COMBAT":
            c = d.get("combat") or {}
            ready = (c.get("action_readiness") or {})
            if not ready.get("can_use_combat_actions"):
                time.sleep(0.8)
                continue
            snap, idx, handby = map_state(d)
            stars_now = int((c.get("player") or {}).get("stars") or 0)
            snap["stars"] = stars_now
            acts = []
            for h in (c.get("hand") or []):
                ce = int(h.get("energy_cost") or 0)
                cs = int(h.get("star_cost") or 0)
                key = h.get("name") or "?"     # 卡名，不带手牌位（同上）
                # 真实星经济硬门槛（沙盒未建模，游戏会拒：实测被拒
                # 多次后于 2026-10-15 补上）：星不够的卡根本不进候选
                if ce <= snap["energy"] and cs <= stars_now:
                    acts.append({"id": "play_%d" % h["index"],
                                 "card": key, "cost": ce})
            best, tr = kb.decide_graph(kg, eng, snap, acts, idx)
            threat = sorted({t for e in snap["enemies"]
                             for t in e["intent_tags"]})
            # ── 用药决策图一元化（2026-10-16）：每瓶可用药水 + "保留"
            # 同为账本选项，文本经 parse_features 成语义流量；血线低时
            # 生存资源能量自动抬高治疗系出分（激素/压力同场调制），
            # 替代旧版 45%/60% 硬阈值。经验：局终按层差回灌 标签:用药。
            used_pot = False
            if "use_potion" in avail:
                mxp = int(snap.get("max_hp") or 75)
                hp_now = int(snap.get("hp") or 0)
                inc = sum(int(e.get("intent_damage") or 0) *
                          max(1, int(e.get("intent_hits") or 1))
                          for e in snap["enemies"])
                lethal = inc >= hp_now or bool(
                    c.get("end_turn_will_kill_player"))
                hp_r0 = hp_now / max(mxp, 1)
                popts = []
                pmap = {}
                for pot in ((d.get("run") or {}).get("potions") or []):
                    if not pot.get("can_use"):
                        continue
                    fts, inh = kb.parse_features(
                        (pot.get("description") or "") +
                        (pot.get("name") or ""), hp_r0)
                    popts.append({"key": pot["index"],
                                  "name": pot.get("name") or "?",
                                  "feats": fts, "inhib": inh})
                    pmap[pot["index"]] = pot
                if popts:
                    popts.append({"key": "keep", "name": "保留药水",
                                  "feats": [("延迟收益", 0.45),
                                            ("机会成本", 0.35)],
                                  "inhib": []})
                    pk, trp = kb.decide_choice(kg, eng, "用药", popts,
                                               {"hp_r": hp_r0,
                                                "lethal": lethal,
                                                "inc": inc, "rich": 0.4})
                    if pk and pk["key"] != "keep":
                        pot = pmap[pk["key"]]
                        body = {"action": "use_potion",
                                "option_index": pk["key"]}
                        if pot.get("requires_target"):
                            vi = pot.get("valid_target_indices") or []
                            if vi:
                                body["target_index"] = min(vi)
                        r = api("/action", body)
                        print("[live] 用药图决策 出分 %s → 用 %s (ok=%s)"
                              % (trp["board"], pk["name"], r.get("ok")),
                              flush=True)
                        if r.get("ok"):
                            potion_uses.append(
                                (pk["name"],
                                 int((d.get("run") or {}).get("floor")
                                     or 0)))
                            used_pot = True
            if used_pot:
                continue
            if best is None:
                r = do_action({"action": "end_turn"}, print)
                print("[live] 回合%s → 结束回合（%s｜建议分最高也≤阈值）"
                      % (snap.get("turn"), "、".join(threat) or "无威胁"),
                      flush=True)
                continue
            ci = int(best["id"].split("_")[1])
            card_key = best["card"]
            pred = (tr.get("preds") or {}).get(best["id"], {})
            top2 = sorted(tr["outcomes"],
                          key=lambda x: -x["activation"])[:2]
            print("[live] 回合%s hp%s甲%s能%s｜%s｜出[%d]%s 预伤%s 预计杀%s｜出分%s"
                  % (snap.get("turn"), snap["hp"], snap["block"],
                     snap["energy"], "、".join(threat) or "无威胁",
                     ci, card_key, pred.get("伤害"), pred.get("击杀"),
                     " vs ".join("%.2f" % x["activation"] for x in top2)),
                  flush=True)
            hb = snap["hp"]
            r = do_action({"action": "play_card", "card_index": ci},
                          print, handby, c.get("enemies"))
            if not r.get("ok"):
                print("      └─ 被拒:", str(r.get("error"))[:160], flush=True)
                # 同一失败动作不再重试：直接记黑名单本轮跳过
                acts2 = [a for a in acts if a["id"] != best["id"]]
                if acts2:
                    best2, tr2 = kb.decide_graph(kg, eng, snap, acts2, idx)
                    if best2:
                        ci2 = int(best2["id"].split("_")[1])
                        r = do_action({"action": "play_card",
                                       "card_index": ci2},
                                      print, handby, c.get("enemies"))
                        if r.get("ok"):
                            card_key = best2["card"]
                if not r.get("ok"):
                    do_action({"action": "end_turn"}, print)
                    continue
            played_log.append((threat, card_key))
            time.sleep(0.5)
            d2 = get_state()
            c2 = d2.get("combat") or d2
            dealt = 0
            kill = False
            if d2.get("in_combat") and c2.get("enemies"):
                before = {e["name"]: e["hp"] for e in snap["enemies"]}
                after = [(e.get("name"), e.get("current_hp"),
                          e.get("is_alive")) for e in c2.get("enemies") or []]
                for nm, hp2, alive in after:
                    if nm in before:
                        dealt += max(0, before[nm] - hp2)
                        if before[nm] > 0 and not alive:
                            kill = True
            kb_base = "Card:%s" % card_key.split("#")[0]
            kb.observe_outcome(kg, kb_base,
                               {"伤害": pred.get("伤害", dealt),
                                "击杀": bool(pred.get("击杀"))},
                               {"dealt": dealt, "kill": kill})
            credit = dealt * 0.8 + (12 if kill else 0)
            if credit > 0:
                KG.update_response_weights(kg, threat or ["无"],
                                           kb_base, credit)
        elif screen == "REWARD":
            rw = d.get("reward") or {}
            if rw.get("pending_card_choice"):
                # 奖励选卡进图（2026-10-16）：卡面文本→语义特征，
                # "不拿"（保牌组纯净）同为候选；经验按局终层差回灌
                opts = rw.get("card_options") or []
                rux = d.get("run") or {}
                hr_r = int(rux.get("current_hp") or 60) / max(
                    int(rux.get("max_hp") or 75), 1)
                copts = []
                for o in opts:
                    fts, inh = kb.parse_features(
                        o.get("resolved_rules_text") or
                        o.get("description") or "", hr_r)
                    copts.append({"key": o["index"],
                                  "name": o.get("name") or "?",
                                  "feats": fts, "inhib": inh})
                copts.append({"key": "skip", "name": "不拿卡",
                              "feats": [("风险", 0.18)], "inhib": []})
                pk, trw = kb.decide_choice(kg, eng, "奖励", copts,
                                           {"hp_r": hr_r, "rich": 0.4})
                if pk and pk["key"] != "skip":
                    r = api("/action", {"action": "choose_reward_card",
                                        "option_index": pk["key"]})
                    print("[live] 奖励图决策 %s → 拿「%s」(ok=%s)"
                          % (trw["board"], pk["name"],
                             r.get("ok")), flush=True)
                    if r.get("ok"):
                        reward_picks.append(
                            (pk["name"], int(rux.get("floor") or 0)))
                else:
                    r = api("/action", {"action": "skip_reward_cards"})
                    if not r.get("ok"):
                        r = api("/action",
                                {"action": "collect_rewards_and_proceed"})
                    print("[live] 奖励图决策 %s → 不拿 (ok=%s)"
                          % (trw["board"], r.get("ok")), flush=True)
            else:
                claims = [x for x in (rw.get("rewards") or [])
                          if x.get("claimable")]
                if claims:
                    r = api("/action", {"action": "claim_reward",
                                        "option_index": claims[0]["index"]})
                    print("[live] 领奖励 %s (ok=%s)"
                          % (claims[0].get("reward_type"),
                             r.get("ok")), flush=True)
                else:
                    r = api("/action",
                            {"action": "collect_rewards_and_proceed"})
                    print("[live] 离开奖励 (ok=%s)" % r.get("ok"), flush=True)
        elif screen == "MAP":
            m = d.get("map") or {}
            nodes = m.get("available_nodes") or []
            if not nodes:
                print("[live] 无可走节点", flush=True)
                break
            run = d.get("run") or {}
            hp_now, mx = (int(run.get("current_hp") or 75),
                          int(run.get("max_hp") or 75))
            # 选路进图（2026-10-16）：节点类型翻成价值特征——
            # 宝藏/商店=延迟收益+期望收益，篝火=生存资源，
            # 战斗/精英/首领=期望收益但风险随血低放大，未知=期权。
            _NODE_TEXT = {
                "Treasure": "获得一个遗物 永久",
                "Rest": "回复 休息",
                "Shop": "获得 金币 永久",
                "Monster": "战斗",
                "Elite": "战斗 精英 获得 升级",
                "Boss": "战斗 精英 获得",
                "Unknown": "",
                "Event": "",
            }
            mopts = []
            for n0 in nodes:
                fts, inh = kb.parse_features(
                    _NODE_TEXT.get(n0.get("node_type"), ""),
                    hp_now / max(mx, 1))
                mopts.append({"key": n0["index"],
                              "name": str(n0.get("node_type")),
                              "feats": fts, "inhib": inh})
            pk, trm = kb.decide_choice(kg, eng, "路径", mopts,
                                       {"hp_r": hp_now / max(mx, 1),
                                        "rich": 0.4})
            go = pk or mopts[0]
            r = api("/action", {"action": "choose_map_node",
                                "option_index": go["key"]})
            print("[live] 地图(%s血)图决策 %s → %s (ok=%s)"
                  % (hp_now, trm["board"], go["name"], r.get("ok")),
                  flush=True)
            if not r.get("ok"):
                break
        elif screen == "CARD_SELECTION":
            # 2026-10-16 修复：deck_card_select 这类子界面是
            # "选N张→确认"两段式（只 select 不 confirm 会无限原地选）。
            # 先按 max_select 填满（每拍一张，图决策排序），够数/无牌
            # 可选即 confirm_selection。
            sel = d.get("selection") or {}
            cards = sel.get("cards") or []
            maxn = int(sel.get("max_select") or 1)
            seln = int(sel.get("selected_count") or 0)
            unsel = [c for c in cards if not c.get("selected")]
            if unsel and seln < maxn:
                rux = d.get("run") or {}
                hr_r = int(rux.get("current_hp") or 60) / max(
                    int(rux.get("max_hp") or 75), 1)
                copts = []
                for o in unsel:
                    fts, inh = kb.parse_features(
                        o.get("resolved_rules_text") or "", hr_r)
                    copts.append({"key": o["index"],
                                  "name": o.get("name") or "?",
                                  "feats": fts, "inhib": inh})
                pk, tcs = kb.decide_choice(
                    kg, eng, "选卡", copts,
                    {"hp_r": hr_r, "rich": 0.4})
                if pk is None:
                    pk = copts[0]
                r = api("/action", {"action": "select_deck_card",
                                    "option_index": pk["key"]})
                print("[live] 选卡图决策(第%d/%d张) → %s (ok=%s)"
                      % (seln + 1, maxn, pk["name"], r.get("ok")),
                      flush=True)
                if not r.get("ok"):
                    break
            elif "confirm_selection" in avail:
                r = api("/action", {"action": "confirm_selection"})
                print("[live] 选卡确认 (已选%d, ok=%s)"
                      % (seln, r.get("ok")), flush=True)
                if not r.get("ok"):
                    break
            else:
                print("[live] 选卡页无候选也无确认钮 (selected=%d/%d)"
                      % (seln, maxn), flush=True)
                break
        elif screen == "REST":
            opts = (d.get("rest") or {}).get("options") or []
            run = d.get("run") or {}
            hp_r, mx_r = int(run.get("current_hp") or 0), int(
                run.get("max_hp") or 75)
            en = [o for o in opts if o.get("is_enabled")]
            if not en:
                # 篝火用过 → 同屏只剩离开按钮（实测 2026-10-15）
                step = next((a for a in avail if a in
                             ("proceed", "leave_rest", "confirm",
                              "continue_game")), None)
                if not step:
                    break
                r = api("/action", {"action": step})
                print("[live] 篝火离开 → %s (ok=%s)"
                      % (step, r.get("ok")), flush=True)
                continue
            # 睡/炼/走 全部进图（2026-10-16）：选项文本→语义特征，
            # 生存资源能量随血线自动涨落，经验边记"上次睡/炼之后"
            ropts = []
            for o0 in en:
                fts, inh = kb.parse_features(
                    (o0.get("title") or "") + (o0.get("description")
                                               or ""),
                    hp_r / max(mx_r, 1))
                ropts.append({"key": o0["index"],
                              "name": o0.get("title") or "?",
                              "feats": fts, "inhib": inh})
            ropts.append({"key": "skip", "name": "离开篝火",
                          "feats": [("延迟收益", 0.25)], "inhib": []})
            pk, trr = kb.decide_choice(kg, eng, "篝火", ropts,
                                       {"hp_r": hp_r / max(mx_r, 1),
                                        "rich": 0.4})
            if pk is None or pk["key"] == "skip":
                step = next((a for a in avail if a in
                             ("proceed", "leave_rest", "confirm")), None)
                if step:
                    r = api("/action", {"action": step})
                    print("[live] 篝火图决策 %s → 离开 (ok=%s)"
                          % (trr["board"], r.get("ok")), flush=True)
                continue
            r = api("/action", {"action": "choose_rest_option",
                                "option_index": pk["key"]})
            print("[live] 篝火图决策 %s → %s (ok=%s)"
                  % (trr["board"], pk["name"], r.get("ok")), flush=True)
        elif screen == "CHEST":
            ch = d.get("chest") or {}
            if not ch.get("is_opened"):
                r = api("/action", {"action": "open_chest"})
                print("[live] 宝箱 → 开箱 (ok=%s)" % r.get("ok"), flush=True)
            elif not ch.get("has_relic_been_claimed"):
                rels = ch.get("relic_options") or []
                if not rels:
                    break
                # 宝箱选遗物进图（2026-10-16）：稀有度→延迟收益权重，
                # 名称文本→parse 语义；免费拿不灌经验（无对照基线）
                _RAR = {"Common": 0.22, "Uncommon": 0.30,
                        "Rare": 0.40, "Boss": 0.45}
                lopts = []
                for rel in rels:
                    fts, inh = kb.parse_features(rel.get("name") or "",
                                                 1.0)
                    fts = fts + [("延迟收益",
                                  _RAR.get(rel.get("rarity"), 0.25))]
                    lopts.append({"key": rel.get("index"),
                                  "name": rel.get("name") or "?",
                                  "feats": fts, "inhib": inh})
                pk, trl = kb.decide_choice(kg, eng, "遗物", lopts,
                                           {"hp_r": 1.0, "rich": 0.5})
                pick0 = pk or lopts[0]
                r = api("/action", {"action": "choose_treasure_relic",
                                    "option_index": pick0["key"]})
                print("[live] 宝箱图决策 %s → 拿 %s (ok=%s)"
                      % (trl["board"], pick0["name"], r.get("ok")),
                      flush=True)
            else:
                step = next((a for a in avail if a in
                             ("proceed", "leave_chest", "confirm")), None)
                if not step:
                    break
                r = api("/action", {"action": step})
                print("[live] 宝箱离开 → %s (ok=%s)"
                      % (step, r.get("ok")), flush=True)
        elif screen == "SHOP":
            # 商店语义已从 mod 官方源码确认（client_actions.py：
            # buy_relic/buy_card/buy_potion 均只带 option_index；
            # 内层先 open_shop_inventory、离开内层先 close_shop_inventory）。
            sh = d.get("shop") or {}
            gold = int((d.get("run") or {}).get("gold") or 0)
            # 内层库存页（动作表含 buy_*）→ 图一元商店决策（kb.decide_shop：
            # 商品语义写成价值源→账本流量边，"离开"同为节点；
            # 买不买由扩散出分排序，不再用价格阈值硬规则）
            if {"buy_relic", "buy_card", "buy_potion"} & set(avail):
                room = 3 - len((d.get("run") or {}).get("potions") or [])
                items = []
                for rel in (sh.get("relics") or []):
                    if rel.get("enough_gold") and rel.get("is_stocked",
                                                           True):
                        items.append({
                            "key": "relic_%s" % rel["index"],
                            "kind": "relic", "index": rel["index"],
                            "name": rel.get("name") or "?",
                            "price": int(rel.get("price") or 0),
                            "text": (rel.get("description") or "")})
                for pt in (sh.get("potions") or []):
                    if room > 0 and pt.get("enough_gold"):
                        items.append({
                            "key": "potion_%s" % pt["index"],
                            "kind": "potion", "index": pt["index"],
                            "name": pt.get("name") or "?",
                            "price": int(pt.get("price") or 0),
                            "text": (pt.get("description") or "")})
                # 商店卡也进候选（撤销"卡一律不买"硬偏见）——"污染牌组"
                # 是不是真的差，交给 ShopItem 经验边自己学
                for cd in (sh.get("cards") or [])[:4]:
                    if cd.get("enough_gold"):
                        items.append({
                            "key": "card_%s" % cd["index"],
                            "kind": "card", "index": cd["index"],
                            "name": cd.get("name") or "?",
                            "price": int(cd.get("price") or 0),
                            "text": (cd.get("resolved_rules_text") or
                                     cd.get("description") or "")})
                run0 = d.get("run") or {}
                hp0 = int(run0.get("current_hp") or 0)
                mx0 = int(run0.get("max_hp") or 75)
                pick, trs = kb.decide_shop(kg, eng, gold, hp0, mx0, items)
                print("[live] 商店图决策(金%d血%d/%d) 出分 %s"
                      % (gold, hp0, mx0, trs["board"]), flush=True)
                if pick:
                    act = {"relic": "buy_relic", "potion": "buy_potion",
                           "card": "buy_card"}.get(pick["kind"],
                                                   "buy_potion")
                    r = api("/action", {"action": act,
                                        "option_index": pick["index"]})
                    print("[live] 商店买%s %s（%s金，ok=%s）"
                          % ({"relic": "遗物", "potion": "药水",
                              "card": "卡"}.get(pick["kind"], "?"),
                             pick["name"], pick["price"], r.get("ok")),
                          flush=True)
                    if r.get("ok"):
                        shop_purchases.append(
                            (pick["name"],
                             int((d.get("run") or {}).get("floor") or 0)))
                r = api("/action", {"action": "close_shop_inventory"})
                print("[live] 商店内层 → 关门 (ok=%s)" % r.get("ok"),
                      flush=True)
                continue
            # 外层大厅页：先开内层逛一次（图决策），逛过/已展开则 proceed 离店
            key = (d.get("run_id"), (d.get("run") or {}).get("floor"))
            if sh.get("is_open") or shop_state["at"] == key:
                r = api("/action", {"action": "proceed"})
                print("[live] 商店(%d金) → 离店 (ok=%s)"
                      % (gold, r.get("ok")), flush=True)
                if shop_state["at"] == key:
                    shop_state["at"] = None
                continue
            act = next((a for a in avail if a in
                        ("open_shop", "open_shop_inventory")), None)
            if act is None:
                r = api("/action", {"action": "proceed"})
                print("[live] 商店 → 离店(无开店动作) (ok=%s)"
                      % r.get("ok"), flush=True)
                continue
            r = api("/action", {"action": act})
            if r.get("ok"):
                shop_state["at"] = key
            print("[live] 商店(%d金) → 开库存 (%s, ok=%s)"
                  % (gold, act, r.get("ok")), flush=True)
        elif screen == "GAME_OVER":
            go = d.get("game_over") or {}
            rid = d.get("run_id")
            won = bool(go.get("is_victory"))
            # 只在真正打完一局（played_log 非空）且该局未记账时结算——
            # 修此前每圈 runs+=1 飙到上千、且反复空反灌的 bug
            if played_log and rid not in settled_runs:
                print("[live] 第%d局结束：%s（层%s）"
                      % (runs, "通关" if won else "败北", go.get("floor")),
                      flush=True)
                if not won:
                    for threat, key in played_log:
                        KG.update_response_weights(
                            kg, threat or ["无"],
                            "Card:%s" % key.split("#")[0], -3.0)
                    print("[live] 败局反灌 %d 手" % len(played_log),
                          flush=True)
                settled_runs.add(rid)
                runs += 1
                played_log = []
                # 购物经验回流：商品节点 response 边按"买后的局果"奖惩
                # （通关 +8；买完 ≤1 层就死 -5（糟糕投资强信号）；
                # 推进 ≥6 层 +3；其余 -1 弱负）——相关非因果，
                # 但和败局反灌同理：让"买了它之后的世界"教它
                final_fl = int(go.get("floor") or 0)
                for name, buy_fl in shop_purchases:
                    if won:
                        cr = 8.0
                    else:
                        df = final_fl - buy_fl
                        cr = 3.0 if df >= 6 else (-5.0 if df <= 1 else -1.0)
                    KG.update_response_weights(kg, ["购物"],
                                               "ShopItem:%s" % name, cr)
                if shop_purchases:
                    print("[live] 购物经验回流 %d 件" % len(shop_purchases),
                          flush=True)
                shop_purchases = []
                # 用药/奖励/角色同型回流（归因同样粗但诚实：
                # "带着它打进/速死"就是世界给的答案）
                for name, ufl in potion_uses:
                    df = final_fl - ufl
                    cr = 8.0 if won else (3.0 if df >= 6 else
                                          (-5.0 if df <= 1 else -1.0))
                    kb.choice_credit(kg, "用药", name, cr)
                for name, rfl in reward_picks:
                    df = final_fl - rfl
                    cr = 6.0 if won else (2.5 if df >= 6 else -2.0)
                    kb.choice_credit(kg, "奖励", name, cr)
                if go.get("character_id"):
                    kb.choice_credit(kg, "角色", str(go["character_id"]),
                                     6.0 if won else
                                     max(-3.0, final_fl * 0.35 - 3.0))
                if potion_uses or reward_picks:
                    print("[live] 用药/奖励回流 %d+%d 项"
                          % (len(potion_uses), len(reward_picks)),
                          flush=True)
                potion_uses = []
                reward_picks = []
                char_pick[0] = None
                persist_exp()
            # 按屏幕实际给的按钮走：先收结算摘要，再回主菜单
            if "continue_game_over" in avail:
                r = api("/action", {"action": "continue_game_over"})
            elif "return_to_main_menu" in avail:
                r = api("/action", {"action": "return_to_main_menu"})
            else:
                r = {"ok": False, "error": avail[:4]}
            print("[live] 结算页推进 (ok=%s)" % r.get("ok"), flush=True)
        elif screen == "MAIN_MENU":
            r = api("/action", {"action": "open_character_select"})
            print("[live] 主菜单 → 角色选择 (ok=%s)" % r.get("ok"), flush=True)
        elif screen == "CHARACTER_SELECT":
            cs = d.get("character_select") or {}
            chars = cs.get("characters") or []
            if not cs.get("can_embark"):
                # 角色选择进图（2026-10-16）：先验全同，储君 +0.15 身份
                # 锚（"她想玩这个"是偏好不是策略），真正的分化来自
                # 标签:角色→Choice:角色:名 的局果经验边
                copts = []
                for x in chars:
                    if x.get("is_locked"):
                        continue
                    f = [("延迟收益", 0.25)]
                    if x.get("name") == "储君":
                        f.append(("期望收益", 0.15))
                    copts.append({"key": x["index"],
                                  "name": x.get("name") or "?",
                                  "feats": f, "inhib": []})
                if not copts:
                    break
                pk, tch = kb.decide_choice(kg, eng, "角色", copts,
                                           {"hp_r": 1.0, "rich": 0.5})
                pick = pk or copts[0]
                r = api("/action", {"action": "select_character",
                                    "option_index": pick["key"]})
                char_pick[0] = pick["name"]
                print("[live] 选角色图决策 %s → %s (ok=%s)"
                      % (tch["board"], pick["name"], r.get("ok")),
                      flush=True)
            else:
                r = api("/action", {"action": "embark"})
                print("[live] 登船，开第%d局 (ok=%s)" % (runs, r.get("ok")),
                      flush=True)
        elif screen == "EVENT":
            ev = d.get("event") or {}
            opts = ev.get("options") or []
            if not opts:
                step = next((a for a in avail if a in
                             ("proceed", "leave_event", "confirm",
                              "continue_game")), None)
                if not step:
                    break
                r = api("/action", {"action": step})
                print("[live] 事件离开 → %s (ok=%s)"
                      % (step, r.get("ok")), flush=True)
                continue

            # 事件选项进图（2026-10-16）：文本→特征/抑制（失去生命=风险
            # 边，且残血时风险能量天然更高→自动更怕痛）；选择结果下一拍
            # 用 hp/金币/牌库三差分归因回灌经验
            rux = d.get("run") or {}
            hr_r = int(rux.get("current_hp") or 60) / max(
                int(rux.get("max_hp") or 75), 1)
            eopts = []
            for o0 in opts:
                if o0.get("is_locked"):
                    continue
                fts, inh = kb.parse_features(
                    (o0.get("title") or "") + (o0.get("description") or ""),
                    hr_r)
                eopts.append({"key": o0["index"],
                              "name": o0.get("title") or "?",
                              "feats": fts, "inhib": inh})
            if not eopts:
                eopts = [{"key": opts[0]["index"], "name": "未解锁项",
                          "feats": [("延迟收益", 0.25)], "inhib": []}]
            pk, tre = kb.decide_choice(kg, eng, "事件", eopts,
                                       {"hp_r": hr_r, "rich": 0.4})
            if pk is None:
                pk = eopts[0]
            r = api("/action", {"action": "choose_event_option",
                                "option_index": pk["key"]})
            print("[live] 事件图决策[%s] %s → %s (ok=%s)"
                  % (ev.get("title"), tre["board"], pk["name"],
                     r.get("ok")), flush=True)
            if r.get("ok"):
                pending_event[0] = (pk["name"],
                                    int(rux.get("current_hp") or 0),
                                    int(rux.get("gold") or 0),
                                    len(rux.get("deck") or []))
        else:
            print("[live] 界面 %s 动作 %s（等人工/未建模，5s）"
                  % (screen, [a for a in avail if a != "save_and_quit"][:6]),
                  flush=True)
            time.sleep(5)
except KeyboardInterrupt:
    print("[live] 手动接管，驱动退出", flush=True)
except urllib.error.URLError as e:
    print("[live] API 连接断开:", str(e)[:120], flush=True)

# 败局反灌（沙盒同款规则：输=每手 -3.0）
last = None
try:
    last = get_state()
except Exception:
    pass
if last and last.get("screen") in ("GAME_OVER",):
    for threat, key in played_log:
        KG.update_response_weights(kg, threat or ["无"],
                                   "Card:%s" % key.split("#")[0], -3.0)
    print("[live] 败局反灌 %d 手" % len(played_log), flush=True)
persist_exp()
print("[live] 经验已持久化（response 边 %d 条）。步数 %d" % (
    sum(1 for e in kg.edges if isinstance(e.extra_attrs, dict)
        and e.extra_attrs.get("kind") == "response"), steps), flush=True)
