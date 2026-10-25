# -*- coding: utf-8 -*-
"""sts2_sim.card_parser — 运行时卡牌文本解析（确定性、零 LLM，2026-10-15）。

纪律（任务书 §三）：
  · 自然语言≠可执行规则：只产出"效果结构假设"；数值/条件/时序不能从文本
    确定 → 进 unknown 显式保留，不静默丢、不猜默认值；
  · 机制匹配用 KB 的 M.id（机制不存在的语义键照记，标 semantic_key）；
  · 匹配逻辑只认效果语言，绝不认卡名（卡名进匹配=作弊）；
  · 分片段处理：每个逗号/句号片段独立判定命中或 unknown。
"""
import re

# (正则, 机制, {参数名: 捕获组号}, 目标, 时序)
_PATTERNS = [
    (r"造成\s*(\d+)\s*点伤害(?:\s*(\d+)\s*次)?", "M.attack_damage",
     {"damage": 1, "hits": 2}, "enemy", "play"),
    (r"对?所有(?:敌人|敌方)[^，。]{0,6}?造成\s*(\d+)\s*点伤害",
     "M.attack_damage", {"damage": 1}, "all_enemies", "play"),
    # 真实游戏语料差异（2026-10-15 /state 对账实证）：格挡=护甲、给予=施加
    (r"获得\s*(\d+)\s*点?(?:护甲|格挡)", "M.block", {"block": 1}, "self",
     "play"),
    (r"(?:施加|给予)\s*(\d+)\s*层(?:脆弱|易伤)", "M.vulnerable",
     {"stacks": 1}, "enemy", "play"),
    (r"(?:施加|给予)\s*(\d+)\s*层虚弱", "M.weak", {"stacks": 1},
     "enemy", "play"),
    (r"(?:获得|增加)\s*(\d+)\s*点力量", "M.strength", {"stacks": 1},
     "self", "play"),
    (r"(?:获得|增加)\s*(\d+)\s*点敏捷", "M.dexterity", {"stacks": 1},
     "self", "play"),
    (r"抽\s*(\d+)\s*张", "M.card_draw", {"n": 1}, "self", "play"),
    (r"失去\s*(\d+)\s*点生命", "M.hp_loss", {"amount": 1}, "self", "play"),
    (r"消耗", "M.exhaust", {}, "self", "on_play"),
    (r"保留", "M.retain", {}, "self", "end_of_turn"),
]
# 英文模式（真实语料驱动：Deal×175/Gain×125/Apply×42/Draw×43 高频句式；
# 机制映射全部指向 KB 的 M.* id；状态名映射不到已知机制→semantic_key 保留）
_EN = [
    (r"Deal(?:s|es)?\s+(?:all enemies?|an? ?(?:enemy|opponent))[^.]*?"
     r"(\d+)(?:\s+(?:damage|Damage))?", "M.attack_damage",
     {"damage": 1}, "all_enemies", "play"),
    (r"Deal(?:s|es)?\s+(\d+)\s*(?:damage|Damage)(?:\s+(\d+)\s*times?)?",
     "M.attack_damage", {"damage": 1, "hits": 2}, "enemy", "play"),
    (r"Gain(?:s)?\s+(\d+)\s*Block", "M.block", {"block": 1}, "self",
     "play"),
    (r"Gain(?:s)?\s+(\d+)\s*Strength", "M.strength", {"stacks": 1},
     "self", "play"),
    (r"Gain(?:s)?\s+(\d+)\s*Dexterity", "M.dexterity", {"stacks": 1},
     "self", "play"),
    (r"Draw(?:s)?\s+(\d+)\s*cards?", "M.card_draw", {"n": 1}, "self",
     "play"),
    (r"Apply(?:s)?\s+(\d+)(?:\s+stacks? of)?\s+(\w+)", "status",
     {"stacks": 1, "which": 2}, "enemy", "play"),
    (r"(?:Lose|lose)\s+(\d+)\s*(?:Max )?(?:Health|HP|Energy)", "M.hp_loss",
     {"amount": 1}, "self", "play"),
    (r"Add(?:s)?\s+(\d+)\s*copies?", "M.deck_add", {"n": 1}, "deck",
     "play"),
]
_EXTRA = [  # 语料驱动补充：25% 零命中的三大类（能量符号/被动修正器/触发子句）
    (r"Gain\s+\[E\]", "M.energy", {}, "self", "play"),
    (r"[Tt]urns?,?\s+(?:you\s+)?(?:gain|draw|deal|apply)\s+(\d+)",
     "trigger", {"n": 1}, None, "trigger"),
    (r"(\w+)\s+deals?\s+\d+\s+additional", "modifier", {"on": 1},
     None, "passive"),
    (r"is triggered\s+\d+\s+additional", "modifier", {"on": 0},
     None, "passive"),
]
_STATUS_MECH = {"vulnerable": "M.vulnerable", "weak": "M.weak",
                "poison": "M.poison", "thorns": "M.thorns",
                "strength": "M.strength", "dexterity": "M.dexterity",
                "frail": "M.frail"}
_KEYWORD_MECH = {"exhaust": "M.exhaust", "retain": "M.retain",
                 "innate": "M.innate", "sly": "M.sly", "ethereal":
                 "M.ethereal", "eternal": "M.eternal", "consume": "M.energy",
                 "upkeep": "M.energy"}
_COND = r"^若(.{2,18}?)[，,](.+)$"
_NUMWORD = re.compile(r"\d")


def _one(frag):
    """单片段 → 效果 or None。"""
    m = re.match(_COND, frag.strip())
    if m:
        then = _one(m.group(2))
        return {"mechanic": "conditional",
                "params": {"condition": m.group(1).strip(),
                           "then": then},
                "target": (then or {}).get("target"),
                "timing": "play",
                "confidence": 0.5 if then else 0.3,
                "unknown": [] if then else [m.group(2)[:40]]}
    kw_mechs = []
    for pat, mech, keys, target, timing in _PATTERNS + _EN + _EXTRA:
        g = re.search(pat, frag, re.I)
        if not g:
            continue
        if mech == "status":
            which = (g.group(2) or "").lower()
            mech = _STATUS_MECH.get(which)
            p = {"stacks": int(g.group(1))}
            if mech is None:
                return {"mechanic": "semantic_key", "params":
                        {"key": which.lower(), **p},
                        "target": target, "timing": timing,
                        "confidence": 0.5}
            return {"mechanic": mech, "params": p, "target": target,
                    "timing": timing, "confidence": 0.85}
        if mech in ("trigger", "modifier"):
            return {"mechanic": mech,
                    "params": {"raw": frag[:120]},
                    "target": target, "timing": timing,
                    "confidence": 0.5}
        p, ok = {}, True
        for k, idx in keys.items():
            try:
                v = g.group(idx)
            except (IndexError, re.error):
                v = None
            if v is None or v == "":
                if idx != 0 and list(keys).index(k) > 0:
                    continue          # hits 等可选尾组缺省
                p[k] = None
                ok = False
            else:
                p[k] = int(v)
        if mech in ("M.attack_damage",) and "damage" not in p:
            continue
        return {"mechanic": mech, "params": p, "target": target,
                "timing": timing, "confidence": 0.85 if ok else 0.5}
    return None


def parse(name, text, cost=1, ctype=None, keywords=None):
    """→ {name,cost,type,effects[],unknown[],confidence,raw}。
    effects[]: {mechanic, params, target, timing, confidence}；
    conditional 嵌 then 子效果（可部分解析：条件明、结论糊 → conf 0.5）。"""
    t = str(text or "")
    frags = [f.strip() for f in re.split(r"[，。;；,]", t) if f.strip()]
    merged, i = [], 0
    while i < len(frags):
        if frags[i].startswith("若") and i + 1 < len(frags):
            merged.append(frags[i] + "，" + frags[i + 1])
            i += 2
            continue
        merged.append(frags[i])
        i += 1
    effects, unknown = [], []
    for kw in (keywords or []):
        mk = _KEYWORD_MECH.get(str(kw).lower())
        if mk:
            effects.append({"mechanic": mk, "params": {},
                            "target": "self", "timing": "keyword",
                            "confidence": 0.95})
    for frag in merged:
        if not frag:
            continue
        e = _one(frag)
        if e is not None:
            effects.append(e)
            for u in e.pop("unknown", []) or []:
                unknown.append(u)
        else:
            unknown.append(frag[:40])
    conf = min((e["confidence"] for e in effects), default=0.0)
    return {"name": name, "cost": cost,
            "type": ctype or ("attack" if any(
                e["mechanic"] == "M.attack_damage" for e in effects)
                else "skill"),
            "effects": effects, "unknown": unknown,
            "confidence": round(conf, 2), "raw": t[:200]}
