# -*- coding: utf-8 -*-
"""sts2_sim.kb — 机制知识库接入：导入、卡牌解析结果实例化、扩散决策、
预测-实际学习闭环（2026-10-15 任务书）。

三层分离（任务书 §二）：
  1 通用机制知识：files/*.json（37 机制+41 关系+状态变量），kind="kb"，
    学习只写 kind="response" 边，**永不改写 kb 语义**；
  2 卡牌机制实例：card→(使用)→M.mech 边，参数在边属性，卡牌重解析可更新；
  3 当前情境：临时情境节点（S.前缀，run 间可整体清理），播种扩散。
"""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_FILES = os.path.join(_DIR, "files")

_REL_SAFE = {  # KB 类型 → 本体安全词（落不进就退回"关联"+extra 存原类型）
    "requires": "需要", "triggers": "导致", "modifies": "影响",
    "prevents": "抑制", "consumes": "消耗", "produces": "产生",
    "occurs_before": "先于", "depends_on": "依赖",
}


def _load_kb():
    def rd(n):
        p = os.path.join(_FILES, n)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return (rd("mechanics.json"), rd("mechanic_relations.json"),
            rd("state_variables.json"), rd("inference_patterns.json"))


def import_kb(kg):
    """幂等导入机制/关系/状态变量。返回统计。confidence 与关系强度分离：
    confidence 进节点/边属性，边 weight 只表达关联强度的先验。"""
    from graph_model import Node, Edge
    mechs, rels, sv, _p = _load_kb()
    stats = {"mech": 0, "var": 0, "rel": 0, "skipped": 0}
    ms = mechs.get("mechanics") or []
    for m in (ms if isinstance(ms, list) else ms.values()):
        mid = str(m.get("id", ""))
        if not mid:
            continue
        if kg.get_node(mid) is None:
            kg.add_node(Node(id=mid, weight=0.5,
                             label="declarative-semantic",
                             extra_attrs={"type": "mechanism",
                                          "cat": m.get("category"),
                                          "desc": str(m.get("description"))[:
                                                                           220],
                                          "pre": m.get("preconditions"),
                                          "inputs": m.get("inputs"),
                                          "eff": m.get("effects"),
                                          "timing": m.get("timing"),
                                          "confidence": m.get("confidence"),
                                          "kind": "kb"}))
            stats["mech"] += 1
    vs = sv.get("variables") or []
    for v in vs:
        vid = str(v.get("id", ""))
        if vid and kg.get_node(vid) is None:
            kg.add_node(Node(id=vid, weight=0.5,
                             label="declarative-semantic",
                             extra_attrs={"type": "state_var",
                                          "meaning": str(v.get("meaning"))[:
                                                                          160],
                                          "scope": v.get("scope"),
                                          "kind": "kb"}))
            stats["var"] += 1
    # 机制↔状态变量连接（从 KB 自身 inputs/effects 文本抽取，不发明关系）
    vid_set = {str(v.get("id")) for v in vs}
    def _vname(tok):
        s0 = str(tok).strip().replace("[", " ").replace("]", " ")
        s0 = s0.replace("enemies", "enemy")
        parts = [x for x in __import__("re").split(r"[.\s]+", s0) if x][:2]
        cand = "V." + ".".join(parts)
        return cand if cand in vid_set else None
    for m in (ms if isinstance(ms, list) else ms.values()):
        mid = str(m.get("id", ""))
        for tok in (m.get("inputs") or []):
            vid = _vname(str(tok))
            if vid and kg.get_edge(mid, vid, "需要") is None:
                kg.add_edge(Edge(src=mid, dst=vid, relation="需要",
                                 weight=0.6,
                                 extra_attrs={"kind": "kb",
                                              "kb_type": "reads",
                                              "confidence": "derived"}))
                stats["rel"] += 1
        for tok in (m.get("effects") or []):
            t2 = str(tok)
            lhs = t2.split("-=")[0].split("=")[0].split("->")[0].strip()
            vid = _vname(lhs)
            if vid and kg.get_edge(mid, vid, "影响") is None:
                kg.add_edge(Edge(src=mid, dst=vid, relation="影响",
                                 weight=0.6,
                                 extra_attrs={"kind": "kb",
                                              "kb_type": "modifies",
                                              "confidence": "derived",
                                              "raw": t2[:120]}))
                stats["rel"] += 1
    for r in (rels.get("relations") or []):
        src, tgt = str(r.get("source")), str(r.get("target"))
        if kg.get_node(src) is None or kg.get_node(tgt) is None:
            stats["skipped"] += 1
            continue
        rt = r.get("type")
        rel = _REL_SAFE.get(rt, "关联")
        if kg.get_edge(src, tgt, rel) is not None:
            continue
        ok = kg.add_edge(Edge(src=src, dst=tgt, relation=rel, weight=0.7,
                              extra_attrs={"kind": "kb", "kb_type": rt,
                                           "semantics": str(
                                               r.get("semantics"))[:160],
                                           "confidence": r.get(
                                               "confidence")}))
        if ok:
            stats["rel"] += 1
        else:
            stats["skipped"] += 1
    return stats


def instantiate_card(kg, parsed, name):
    """卡牌解析结果 → 图谱实例：Card 节点 + 使用->机制边（参数在边），
    未解析片段挂 unknown 标记（不静默、不猜）。可重复调用=更新。"""
    from graph_model import Node, Edge
    cid = f"Card:{name}"
    if kg.get_node(cid) is None:
        kg.add_node(Node(id=cid, weight=0.5, label="declarative-semantic",
                         extra_attrs={"type": "card_instance",
                                      "kind": "kb"}))
    # 重解析=原地更新参数，不删重建（K3b 实锤：删后同节点对会被
    # "使用"占位拒绝重建，效果边净丢失）
    for eff in parsed["effects"]:
        if eff["mechanic"] and kg.get_node(eff["mechanic"]) is not None:
            # "使用"方向记录 + "相关"双向传播边（semantic 关联本对称；
            # 机制被情境点亮时能量要能回流到卡——18:4x 扩散方向诊断）
            if kg.get_edge(cid, eff["mechanic"], "使用") is None:
                kg.add_edge(Edge(src=cid, dst=eff["mechanic"],
                                 relation="使用", weight=0.7,
                                 extra_attrs={"kind": "effect_direction",
                                              "params": eff.get("params"),
                                              "target": eff.get("target"),
                                              "timing": eff.get("timing"),
                                              "conf": eff.get("confidence")}))
            ex = kg.get_edge(cid, eff["mechanic"], "相关")
            if ex is None:
                kg.add_edge(Edge(src=cid, dst=eff["mechanic"],
                                 relation="相关", weight=0.7,
                                 extra_attrs={"kind": "effect",
                                              "params": eff.get("params")}))
            else:
                ex.extra_attrs["params"] = eff.get("params")
    if parsed.get("unknown"):
        kg.add_edge(Edge(src=cid, dst="M.未解明效果" if kg.get_node(
            "M.未解明效果") else cid, relation="关联", weight=0.3,
            extra_attrs={"kind": "effect", "unknown": parsed["unknown"]}))
    return cid


# ── 连通性外扩（用户补充需求 18:0x）：机制层不孤岛。桥规则：向下接
# 沙盒游戏标签语义（让情境标签扩散能穿透机制层），向上接通用概念层
# （GC:风险/机会成本/延迟收益…，原子、单义、跨游戏可复用）。
# 全部 kind="kb_bridge" + evidence="derivation" + 弱权重 0.45，
# 与机制/策略边分层，不冒充规则。 ─────────────────────────────
_TAG_BRIDGES = {
    "M.attack_damage": "标签:攻击", "M.block": "标签:防御",
    "M.vulnerable": "标签:削弱", "M.weak": "标签:削弱",
    "M.strength": "标签:强化", "M.dexterity": "标签:强化",
    "M.exhaust": "标签:消耗", "M.card_draw": "标签:抽",
}
_GC_BRIDGES = {
    "M.enemy_intent": "GC:风险", "M.attack_damage": "GC:威胁消除",
    "M.block": "GC:延迟收益", "M.energy": "GC:机会成本",
    "M.exhaust": "GC:资源保留", "M.deck_building": "GC:期望收益",
    "M.rest_site": "GC:生存资源", "M.gold_economy": "GC:机会成本",
    "M.ascension": "GC:小样本噪声", "M.hp_loss": "GC:生存资源",
}


def import_powers(kg):
    """真实引擎的 241 个状态/被动定义并入机制层（M.pow.* 幂等）。"""
    from graph_model import Node, Edge
    d = os.path.join(_FILES, "..", "spire-archive-main", "spire-archive-main",
                     "data", "sts2")
    try:
        powers = json.load(open(os.path.join(d, "powers.json"),
                                encoding="utf-8"))
    except OSError:
        return 0
    made = 0
    for pw in powers:
        mid = f"M.pow.{pw.get('name','')}"
        if not pw.get("name") or kg.get_node(mid) is not None:
            continue
        kg.add_node(Node(id=mid, weight=0.45, label="declarative-semantic",
                         extra_attrs={"type": "power_def", "kind": "kb",
                                      "desc": str(pw.get("description"))[:
                                                                       200],
                                      "stackable": pw.get("stackable"),
                                      "conf": "verified_engine"}))
        made += 1
    return made


def bind_card_powers(kg, card_name):
    """卡→其引擎状态真值直连（比文本解析可靠：结构化 ground truth）。"""
    from graph_model import Edge
    d = os.path.join(_FILES, "..", "spire-archive-main", "spire-archive-main",
                     "data", "sts2")
    try:
        cp = json.load(open(os.path.join(d, "card_powers.json"),
                            encoding="utf-8"))
    except OSError:
        return 0
    cid = f"Card:{card_name}"
    n = 0
    for pw in cp.get(str(card_name).upper(), []) or []:
        pid = f"M.pow.{pw.get('name','')}"
        if kg.get_node(pid) is None:
            continue
        if kg.get_edge(cid, pid, "使用") is None:
            if kg.add_edge(Edge(src=cid, dst=pid, relation="使用",
                                weight=0.8,
                                extra_attrs={"kind": "effect_direction",
                                             "source": "card_powers.json",
                                             "evidence": "struct"})):
                n += 1
    return n


def link_to_general(kg):
    """幂等建桥。返回 (tag边数, gc边数)。GC 节点不存在则先建原子概念节点。"""
    from graph_model import Node, Edge
    n_t = n_g = 0
    for mid, tag in _TAG_BRIDGES.items():
        if kg.get_node(mid) is None:
            continue
        if kg.get_node(tag) is None:
            kg.add_node(Node(id=tag, weight=0.45,
                             label="declarative-semantic",
                             extra_attrs={"type": "sts_tag",
                                          "kind": "kb_bridge_seed"}))
        if kg.get_edge(mid, tag, "相关") is None:
            kg.add_edge(Edge(src=mid, dst=tag, relation="相关",
                             weight=0.45,
                             extra_attrs={"kind": "kb_bridge",
                                          "evidence": "derivation"}))
            n_t += 1
    for mid, gc in _GC_BRIDGES.items():
        if kg.get_node(mid) is None:
            continue
        if kg.get_node(gc) is None:
            kg.add_node(Node(id=gc, weight=0.5,
                             label="declarative-semantic",
                             extra_attrs={"type": "strategic_concept",
                                          "kind": "kb_bridge_seed"}))
        if kg.get_edge(mid, gc, "相关") is None:
            kg.add_edge(Edge(src=mid, dst=gc, relation="相关",
                             weight=0.45,
                             extra_attrs={"kind": "kb_bridge",
                                          "evidence": "derivation"}))
            n_g += 1
    return n_t, n_g


def situation_seed(kg, snap):
    """当前情境 → 应激活的机制/状态节点（感知层映射，读 KB 字段而非策略表）。
    返回 [(node_id, energy, why)]。"""
    seeds = []
    enemies = [e for e in snap.get("enemies", []) if e.get("hp", 0) > 0]
    max_dmg = max([(e.get("intent_damage") or 0) *
                   (e.get("intent_hits") or 1) for e in enemies] or [0])
    if max_dmg >= 10 and kg.get_node("M.enemy_intent"):
        seeds.append(("M.enemy_intent", 3.0, f"敌方高额伤害意图{max_dmg}"))
        if kg.get_node("M.block"):
            seeds.append(("M.block", 2.2, "高额伤害在际→格挡机制被调用"))
        if kg.get_node("V.player.hp"):
            seeds.append(("V.player.hp", 2.0, "生命资源受威胁"))
    low_kp = any(e["hp"] <= 18 for e in enemies)
    if low_kp and kg.get_node("M.attack_damage"):
        seeds.append(("M.attack_damage", 2.6, "存在可击杀目标→伤害机制优先"))
    if snap.get("hp", 99) <= 24 and kg.get_node("V.player.hp"):
        seeds.append(("V.player.hp", 3.0, "生命告急"))
    if snap.get("energy", 3) <= 1 and kg.get_node("M.energy"):
        seeds.append(("M.energy", 2.4, "能量稀缺→成本敏感"))
    vuln_targets = [e for e in enemies if (e.get("status") or {}).get("脆弱")]
    if vuln_targets and kg.get_node("M.vulnerable"):
        seeds.append(("M.vulnerable", 2.4, "敌已易伤→放大收益在场"))
    st = snap.get("status") or {}
    # 自身状态属性进扩散源头（声明式表：状态→机制节点→强度公式→理由；
    # 正资产点亮增益机制，存量资产**抑制**对应机制的边际价值）
    _STATUS_SEEDS = [
        ("力量", 2, lambda n: 1.6 + 0.5 * n, "M.strength",
         "自身力量{n}→攻击机制增益在场"),
        ("敏捷", 2, lambda n: 1.4 + 0.4 * n, "M.dexterity",
         "自身敏捷{n}→格挡收益放大"),
        ("脆弱", 1, lambda n: 1.8 + 0.6 * n, "M.frail",
         "自身易损{n}→护甲效率受损，风险↑"),
        ("中毒", 1, lambda n: 1.5 + 0.5 * n, "M.poison",
         "自身中毒{n}→回合数即伤害，速杀优先"),
    ]
    for key, lo, efn, mnode, why in _STATUS_SEEDS:
        n_st = int(st.get(key) or 0)
        if n_st >= lo and kg.get_node(mnode):
            seeds.append((mnode, min(3.0, efn(n_st)), why.format(n=n_st)))
    blk = int(snap.get("block") or 0)
    if blk > 0 and kg.get_node("V.player.block"):
        seeds.append(("V.player.block", min(2.6, 1.2 + 0.06 * blk),
                      f"已有护甲{blk}→格挡边际价值下降（存量事实）"))
    # ── 威胁情势规则（声明式表：条件→机制/概念→能量→理由）──
    # 护甲与来袭的对比是最典型的"可计算情势"：三种结局各有通路，
    # 全部由数字驱动，不含任何卡名/敌名特判。
    hp = int(snap.get("hp") or 0)
    max_hp = int(snap.get("max_hp") or 68)
    total_e = sum(int(e.get("intent_damage") or 0) *
                  int(e.get("intent_hits") or 1) for e in enemies)
    def _threat_rules():
        R = []
        if total_e == 0:
            return R
        surplus = blk - total_e
        if total_e >= hp:
            # 挡不下的致死量：生存压倒一切，攻击换血通道也打开
            R.append(("V.player.hp", 3.5,
                      f"来袭{total_e}≥生命{hp}：致命威胁（全挡也濒死）"))
            R.append(("M.attack_damage", 2.8,
                      "濒死时击杀源头是唯一可靠防御"))
        elif surplus < 0:
            need = -surplus
            R.append(("M.block", 2.2 + min(1.2, 0.10 * need),
                      f"护甲{blk}<来袭{total_e}：缺口{need}，格挡有明确价值"))
        elif surplus <= 6:
            R.append(("M.block", 1.4,
                      f"护甲勉强够挡（余量{surplus}）：低优先维持"))
        else:
            R.append(("GC:机会成本", 2.2,
                      f"护甲{blk}已过剩（余量{surplus}）：能量转攻/投资"))
            if kg.get_node("GC:机会成本") is None:
                from graph_model import Node
                kg.add_node(Node(id="GC:机会成本", weight=0.5,
                                 label="declarative-semantic",
                                 extra_attrs={"type": "strategic_concept",
                                              "kind": "kb_bridge_seed"}))
        if total_e >= 14 and hp <= 0.5 * max_hp:
            R.append(("GC:风险", 2.6,
                      f"高伤来袭{total_e}×残血{hp}：风险敏感"))
        return R
    for node, e, why in _threat_rules():
        if kg.get_node(node) is not None or node.startswith("GC:"):
            if kg.get_node(node) is not None:
                seeds.append((node, e, why))
    # 敌方意图标签点亮（2026-10-15 学习断路修复）：经验边
    # 标签:X -针对-> Card 只有 X 被点亮才向卡牌输送能量——不点标签，
    # 输赢奖惩就是空转（旧管线靠 attention_boost 点亮，图一元 v2 漏接）。
    from graph_model import Node as _N
    tag_dmg = {}
    for e0 in enemies:
        d0 = int(e0.get("intent_damage") or 0) * \
            int(e0.get("intent_hits") or 1)
        for t0 in (e0.get("intent_tags") or []):
            tag_dmg[t0] = max(tag_dmg.get(t0, 0), d0)
    for t0, d0 in tag_dmg.items():
        tid = f"标签:{t0}"
        if kg.get_node(tid) is None:
            kg.add_node(_N(id=tid, weight=0.45,
                           label="declarative-semantic",
                           extra_attrs={"type": "sts_tag",
                                        "kind": "kb_bridge_seed"}))
        seeds.append((tid, min(3.0, 1.5 + 0.06 * d0),
                      f"敌方意图含'{t0}'(伤害{d0})→应对经验被调用"))
    return seeds


# ── 激素调制层（2026-10-16，用户批准接入；对齐生产 modulator_subgraph 的
# 范式："边是系数真源"——激素→调制目标 的带符号边，改边即改效力）。
# 只接生理站得住的三条映射：
#   肾上腺素（急性战斗/逃跑）：来袭≥血量的濒死窗 → 激增；效应=放大
#     "威胁消除"（先解决眼前这只），压制"机会成本"（急性应激下人不权衡）。
#   皮质醇（慢性压力）：血线持续低位+高来袭 → 抬升；效应=放大"生存资源"
#     （警觉偏向保命），压制"延迟收益/期望收益"（压力损害前额叶长期
#     规划与冒险 appetite——Haldon 等应激认知研究的经典结论）。
#   多巴胺（奖励趋近）：健康+无致死威胁+钱包/血量宽裕 → 抬升；效应=
#     放大"期望收益/延迟收益"（奖赏预期驱动趋近与投资），微抑制"生存
#     资源"的过度保守。
# 不接的：血清素/催产素（游戏情境无对应社会/地位刺激源）、褪黑素
# （无昼夜节律输入）——牵强映射比不接更糟。
HORMONES = ("激素:肾上腺素", "激素:皮质醇", "激素:多巴胺")
_HORMONE_EDGES = [
    # (激素, 关系词, 目标, 系数, 生理注脚)
    ("激素:肾上腺素", "影响", "GC:威胁消除", 0.55, "急性应急→先灭当前威胁"),
    ("激素:肾上腺素", "抑制", "GC:机会成本", -0.40, "战逃窗口不权衡"),
    ("激素:皮质醇", "影响", "GC:生存资源", 0.50, "慢性压力→保命警觉"),
    ("激素:皮质醇", "抑制", "GC:延迟收益", -0.45, "压力压制长期规划"),
    ("激素:皮质醇", "抑制", "GC:期望收益", -0.30, "压力削弱冒险趋近"),
    ("激素:多巴胺", "影响", "GC:期望收益", 0.50, "奖赏预期→趋近削血收益"),
    ("激素:多巴胺", "影响", "GC:延迟收益", 0.40, "多巴胺支持对未来价值的投资"),
    ("激素:多巴胺", "抑制", "GC:生存资源", -0.20, "安全态降低过度保守"),
]


def ensure_hormone_subgraph(kg):
    """幂等种激素节点与调制边（relation_category 由本体归一；系数在边上）。"""
    from graph_model import Node, Edge
    for h in HORMONES:
        if kg.get_node(h) is None:
            kg.add_node(Node(id=h, weight=0.5, label="declarative-semantic",
                             extra_attrs={"type": "modulator",
                                          "canon": "sts2_hormone"}))
    for h, rel, tgt, w, note in _HORMONE_EDGES:
        if kg.get_node(tgt) is None:
            continue
        if kg.get_edge(h, tgt, rel) is None:
            kg.add_edge(Edge(src=h, dst=tgt, relation=rel, weight=w,
                             extra_attrs={"kind": "hormone_mod",
                                          "physiology": note}))


def hormone_levels(ctx):
    """由客观局面算激素水平∈[0,1]（生理合理，非策略）：
    ctx = {hp_r: 血量比, lethal: 来袭≥血, inc: 来袭量, rich: 金币宽裕度}"""
    hp_r = max(0.0, min(1.0, float(ctx.get("hp_r", 1.0))))
    lethal = bool(ctx.get("lethal"))
    inc = float(ctx.get("inc", 0))
    rich = max(0.0, min(1.0, float(ctx.get("rich", 0))))
    stress = (1.0 - hp_r) * min(1.0, 0.35 + inc / 30.0)
    adren = 1.0 if lethal else (0.5 if stress > 0.6 else 0.08)
    cort = max(0.0, min(1.0, stress * 0.9 + (0.15 if hp_r < 0.45 else 0)))
    dopa = max(0.0, min(1.0, 0.55 * hp_r + 0.30 * rich + 0.15
                        - (0.35 if lethal else 0)))
    return {"激素:肾上腺素": adren, "激素:皮质醇": cort, "激素:多巴胺": dopa}


def hormone_bias(kg, eng, ctx, se):
    """激素水平入图 → 沿"影响/抑制"边扩散一步 → 读回被调制后的
    GC 能量（乘法系数由边的累积push折算成 1+push/原能量 并钳 ±40%，
    防激素绑架算术——调制是音量旋钮不是新事实）。返回调整后的 se。"""
    lv = hormone_levels(ctx)
    out = dict(se)
    for gid in se:
        n = kg.get_node(gid)
        base = float(se[gid])
        if n is None or base <= 0:
            continue
        push = 0.0
        for e in kg.edges:
            if e.dst == gid and isinstance(e.extra_attrs, dict) \
                    and e.extra_attrs.get("kind") == "hormone_mod":
                w = float(e.weight or 0.0)
                if w == 0:
                    continue
                push += lv.get(e.src, 0.0) * w
        k = max(0.6, min(1.4, 1.0 + push / max(base, 0.5) * 0.45))
        out[gid] = base * k
    # 同步把水平写回激素节点激活（图上可见、可被观战层读出）
    with kg._lock:
        for h, v in lv.items():
            n = kg.get_node(h)
            if n is not None:
                n.activation = v * 2.0     # 沙盒量纲（与种子能量同尺度）
    return out


def _kb_expected_damage(kg, eng, card_eff, snap, target):
    """确定性后果计算（KB 的 P.expected_damage 语义：base+力量，
    ×易伤1.5 ×虚弱0.75，护甲吸收）——扩散不猜数字，模拟器算数。"""
    base = int(card_eff.get("damage", 0))
    hits = int(card_eff.get("hits", 1))
    strv = (snap.get("status") or {}).get("力量", 0)
    weak = (snap.get("status") or {}).get("虚弱", 0)
    vuln = (target.get("status") or {}).get("脆弱", 0)
    per = max(0, int((base + strv) * (0.75 if weak else 1.0)
                      * (1.5 if vuln else 1.0)))
    total = 0
    hp = target["hp"]
    blk = target.get("block", 0)
    for _ in range(hits):
        d = per
        a = min(blk, d)
        blk -= a
        hp -= (d - a)
    return max(0, target["hp"] - max(0, hp)), hp <= 0


def decide(kg, eng, snap, legal_actions, card_index):
    """扩散决策：情境播种机制 → 2 跳扩散（机制←使用←卡；机制→影响→机制）
    → 卡激活 + 确定性后果 → 候选打分。
    返回 (best_action, trace dict)。扩散管"谁与当前局势相关"，
    后果算术管"做了值多少"，两者相乘，不互相冒充。"""
    from sts2_sim import card_parser as CP
    seeds = situation_seed(kg, snap)
    with kg._lock:
        for nid, e, _why in seeds:
            n = kg.nodes.get(nid)
            if n is not None:
                n.activation = max(float(n.activation or 0.0), e)
    eng.mark_active([s[0] for s in seeds])
    eng.diffuse_step()
    eng.diffuse_step()
    cand, trace_rows = [], []
    # 注意力余光衰减：本拍点亮过的机制/状态节点在读走激活后大幅回落
    # （上一拍的能量不该跨拍白拿——否则机制一旦点亮就永亮，
    # 决策吃老本，18:5x 测试残留能量实锤）
    with kg._lock:
        for n in kg.nodes.values():
            if (n.id.startswith(("M.", "V.", "Card:")) and float(
                    n.activation or 0.0) > 0.05):
                n.activation = float(n.activation) * 0.30
    enemies_alive = [x for x in snap.get("enemies", []) if x.get("hp", 0) > 0]
    for a in legal_actions:
        card = a.get("card")
        if not card:
            continue
        if a.get("cost", 0) > snap.get("energy", 0):
            trace_rows.append({"card": card, "legal": False,
                               "why": "能量不足"})
            continue
        n = kg.get_node(f"Card:{card}")
        act = float(n.activation or 0.0) if n else 0.0
        eff = card_index.get(card, {})
        tgt = None
        if "target" in a and enemies_alive:
            tgt = next((x for x in enemies_alive
                        if x["name"] == a["target"]), enemies_alive[0])
        elif enemies_alive:
            tgt = min(enemies_alive, key=lambda x: x["hp"])
        gain, kill = (0, False)
        if tgt is not None:
            gain, kill = _kb_expected_damage(kg, eng, eff, snap, tgt)
        # 格挡价值=被它实际挡掉的来袭（现有护甲先抵扣——过剩盾不计价值）；
        # 防止掉血按生存资源原则权重高于等量造成伤害（1.7 vs 1.4）
        blk_gain = max(0, min(int(eff.get("block", 0) or 0),
                              _incoming(snap)
                              - int(snap.get("block") or 0)))
        risk = eff.get("hp_cost", 0)
        outcome = 1.4 * gain + (25 if kill else 0) + 1.7 * blk_gain - 1.5 \
            * risk - 0.4 * a.get("cost", 0)
        score = (0.35 + act) * max(0.05, outcome / 30.0)
        cand.append((score, a))
        trace_rows.append({"card": card, "legal": True,
                           "activation": round(act, 3),
                           "expected": {"伤害": gain, "击杀": kill,
                                        "有效格挡": blk_gain,
                                        "自损": risk},
                           "outcome": round(outcome, 1),
                           "score": round(score, 3)})
    cand.sort(key=lambda x: -x[0])
    best = cand[0][1] if cand and cand[0][0] > 0.02 else None
    trace = {"seeds": [{"node": x, "e": e, "why": w} for x, e, w in seeds],
             "candidates": trace_rows,
             "chosen": (best or {}).get("id"),
             "reason": ("候选空/均低分→结束回合" if best is None
                        else "激活×后果")}
    return best, trace


def _incoming(snap):
    return sum((e.get("intent_damage") or 0) * (e.get("intent_hits") or 1)
               for e in snap.get("enemies", []) if e.get("hp", 0) > 0)


OUT_PREFIX = "Outcome:"


def _clear_outcomes(kg):
    """上拍的临时评估节点回收（图一元论：outcome 是每拍的草稿，不留永久垃圾）。"""
    with kg._lock:
        for nid in [n.id for n in kg.nodes.values()
                    if n.id.startswith(OUT_PREFIX)]:
            kg.nodes.pop(nid, None)
        kg.edges[:] = [e for e in kg.edges
                       if not (e.src.startswith(OUT_PREFIX)
                               or (e.dst.startswith(OUT_PREFIX)
                                   and (e.extra_attrs or {}).get(
                                       "kind") == "support"))]
        if hasattr(kg, "rebuild_indexes"):
            try:
                kg.rebuild_indexes()
            except Exception:
                pass


def decide_graph(kg, eng, snap, legal_actions, card_index):
    """图一元决策 v2（首版方向错误已修：能量必须从"被情势点亮的价值源"
    流向 Outcome 汇点——边方向 源→支持/抑制→outcome；算术只决定边的
    流量大小，排序完全由图扩散产生）。"""
    from graph_model import Node, Edge
    _clear_outcomes(kg)
    # 场清零（2026-10-15 共振积欠修复）：级联物理"源不损耗、无衰减"，
    # 上一拍点亮的能量不会自己消散——不清零则每出牌全图积欠复利，
    # 经验项越滚越响（48 局曲线 4→1→0 的元凶之一）。每拍决策自包含，
    # 学习的持久性在边权，不在激活。
    with kg._lock:
        for n in kg.nodes.values():
            n.activation = 0.0
    eng._active_nodes.clear()
    seeds = situation_seed(kg, snap)
    # 价值源播种（GC 概念：情势把哪个价值喊响）
    enemies_alive = [x for x in snap.get("enemies", [])
                     if x.get("hp", 0) > 0]
    hp = int(snap.get("hp") or 0)
    max_hp = int(snap.get("max_hp") or 68)
    min_e = min([e["hp"] for e in enemies_alive] or [999])
    incoming = _incoming(snap)
    srcs = {}

    def _gc(name, e, why):
        gid = f"GC:{name}"
        if kg.get_node(gid) is None:
            from graph_model import Node as _N
            kg.add_node(_N(id=gid, weight=0.5,
                           label="declarative-semantic",
                           extra_attrs={"type": "strategic_concept",
                                        "kind": "kb_bridge_seed"}))
        n = kg.get_node(gid)
        if n is not None:
            with kg._lock:
                n.activation = max(float(n.activation or 0.0), e)
            seeds.append((gid, e, why))
        srcs.setdefault(name, gid)

    if min_e <= 14:
        _gc("威胁消除", 3.2, f"敌最低血{min_e}可消灭→击杀价值高")
    _gc("期望收益", 1.4 + (1.0 if min_e <= 24 else 0),
        "削减敌方血量恒有正价值（越近斩杀线越响）")
    # 感知层修正（2026-10-15）：本拍能打死 = 来袭根本不会发生——
    # 存活威胁清零，"生存资源/延迟收益"的情势估值随之自然缩水。
    # 这不是策略特判，是"敌方剩余出手次数"这一客观事实的翻译。
    big_hit = max([int(eff0.get("damage", 0)) * int(eff0.get("hits", 1))
                   for eff0 in card_index.values()] or [0])         if snap.get("hand") else 0
    incoming_eff = 0 if min_e <= big_hit else incoming
    if hp <= 0.5 * max_hp or incoming_eff >= 12:
        _gc("生存资源", 1.5 + 1.5 * min(1.0, incoming_eff / 24.0)
            + (1.0 if hp <= 0.5 * max_hp else 0.0),
            f"来袭{incoming_eff}×血量{hp}/{max_hp}→保命价值")
    if incoming_eff >= 10:
        _gc("延迟收益", 2.4, "格挡的价值在下回合兑现")
    if int(snap.get("energy") or 0) <= 1:
        _gc("机会成本", 2.4, "能量将尽→保存与取舍价值")
    if incoming >= 14 and hp <= 0.5 * max_hp:
        _gc("风险", 2.6, "高伤×残血")
    energy = int(snap.get("energy") or 0)
    src_e0 = {gid: float((kg.get_node(gid).activation if kg.get_node(gid)
                           else 0) or 0.0)
              for gid in ("GC:威胁消除", "GC:生存资源", "GC:延迟收益",
                          "GC:机会成本", "GC:风险", "GC:期望收益")}
    # 激素调制：水平由客观局面算，系数在图上（边是系数真源），沿边折算
    # 成对 GC 能量的有界音量旋钮（±40% 钳位，防激素绑架算术事实）
    ensure_hormone_subgraph(kg)
    src_e0 = hormone_bias(kg, eng, {
        "hp_r": hp / max(max_hp, 1), "lethal": incoming_eff >= hp > 0,
        "inc": incoming_eff, "rich": min(1.0, energy / 3.0)}, src_e0)

    def _se(name):
        return src_e0.get(name, 0.0)

    # 先点亮情境（含意图标签）并扩散一步：能量沿知识边（M-相关-Card）
    # 和经验边（标签-针对-Card）流进卡节点——下面 flows 读到的
    # cn.activation 是图点出来的，不是硬编码加成（图一元）。
    for nid, e0, _why in seeds:
        n0 = kg.get_node(nid)
        if n0 is not None:
            with kg._lock:
                n0.activation = max(float(n0.activation or 0.0), e0)
    eng.mark_active([nid for nid, _e, _w in seeds
                     if not str(nid).startswith("GC:")])
    eng.diffuse_step()

    made = []
    flows = {}
    preds = {}   # 算术→节点能量的流水账（节点是决策介质，边是永久记录）
    for a in legal_actions:
        aid = a["id"]
        if a.get("cost", 0) > energy:
            continue
        oid = f"{OUT_PREFIX}{aid}"
        kg.add_node(Node(id=oid, weight=0.3, label="declarative-episodic",
                         graph_space="self",
                         extra_attrs={"type": "action_outcome",
                                      "action": aid}))
        made.append((a, oid))
        if aid == "end_turn":
            if kg.get_node("GC:机会成本") and                     kg.get_edge("GC:机会成本", oid, "相关") is None:
                kg.add_edge(Edge(src="GC:机会成本", dst=oid,
                                 relation="相关", weight=0.9,
                                 extra_attrs={"kind": "support",
                                              "fact": "保存能量"}))
            flows[oid] = flows.get(oid, 0.0) +                 0.5 * 0.9 * _se("GC:机会成本")
            continue
        eff = card_index.get(a.get("card"), {})
        tgt = min(enemies_alive, key=lambda x: x["hp"])             if enemies_alive else None
        gain, kill = (0, False)
        if tgt is not None:
            gain, kill = _kb_expected_damage(kg, eng, eff, snap, tgt)
        blocked = max(0, min(int(eff.get("block", 0) or 0),
                             incoming - int(snap.get("block") or 0)))
        selfloss = int(eff.get("hp_cost", 0) or 0)
        # —— 算术到此为止；下面把客观量写成"价值源→流量→行动"的图边 ——
        preds[aid] = {"伤害": gain, "击杀": kill, "格挡": blocked,
                      "自损": selfloss}
        if gain and kill and kg.get_node("GC:威胁消除") and                 kg.get_edge("GC:威胁消除", oid, "相关") is None:
            kg.add_edge(Edge(src="GC:威胁消除", dst=oid, relation="相关",
                             weight=2.2, extra_attrs={"kind": "support",
                                                      "fact": "击杀"}))
            flows[oid] = flows.get(oid, 0.0) + 0.5 * 2.2 *                 _se("GC:威胁消除")
        elif gain and kg.get_node("GC:期望收益") and                 kg.get_edge("GC:期望收益", oid, "相关") is None:
            kg.add_edge(Edge(src="GC:期望收益", dst=oid, relation="相关",
                             weight=min(1.1, 0.15 + gain / 14.0),
                             extra_attrs={"kind": "support",
                                          "fact": f"削血{gain}"}))
            flows[oid] = flows.get(oid, 0.0) + 0.5 *                 min(1.1, 0.15 + gain / 14.0) * _se("GC:期望收益")
        if blocked:
            for gname, wgt in (("生存资源", 0.35 + 0.09 * blocked),
                               ("延迟收益", 0.30 + 0.08 * blocked)):
                if kg.get_node(f"GC:{gname}") and                         kg.get_edge(f"GC:{gname}", oid, "相关") is None:
                    kg.add_edge(Edge(src=f"GC:{gname}", dst=oid,
                                     relation="相关",
                                     weight=min(1.2, wgt),
                                     extra_attrs={"kind": "support",
                                                  "fact": f"有效格挡{blocked}"}))
                    flows[oid] = flows.get(oid, 0.0) + 0.5 *                         min(1.2, wgt) * _se(f"GC:{gname}")
        if selfloss and kg.get_node("GC:风险") and                 kg.get_edge("GC:风险", oid, "抑制") is None:
            kg.add_edge(Edge(src="GC:风险", dst=oid, relation="抑制",
                             weight=-min(1.0, 0.4 + 0.15 * selfloss),
                             extra_attrs={"kind": "support",
                                          "fact": f"自损{selfloss}"}))
            flows[oid] = flows.get(oid, 0.0) - 0.4 * min(1.0,
                            0.4 + 0.15 * selfloss) * _se("GC:风险")
        if a.get("cost", 0) >= 2 and kg.get_node("GC:机会成本") and                 kg.get_edge("GC:机会成本", oid, "抑制") is None:
            kg.add_edge(Edge(src="GC:机会成本", dst=oid, relation="抑制",
                             weight=-0.25 * a["cost"],
                             extra_attrs={"kind": "support"}))
        cn = kg.get_node(f"Card:{a.get('card')}")
        if cn is not None:
            calib = float((cn.extra_attrs or {}).get("calib") or 0.7)
            # 经验通道增益：48 局×4 臂消融定标（0=纯知识 4%、0.20=8%、
            # 0.45=17%、0.70=17% 但边权提前饱和）→ 取 0.45
            exp_gain = float(os.environ.get("STS2_EXP_GAIN", "0.45"))
            flows[oid] = flows.get(oid, 0.0) + 0.04 + 0.06 * calib                 + exp_gain * float(cn.activation or 0.0)
    with kg._lock:
        for oid, v in flows.items():
            nn = kg.nodes.get(oid)
            if nn is not None:
                nn.activation = max(0.0, float(v))
    # GC 能量拉回决策时快照：第 1 步扩散经 M→GC 桥回流进过价值源，
    # 不拉回同一源会在第 2 步被二次放大
    with kg._lock:
        for name0, gid0 in srcs.items():
            nn0 = kg.nodes.get(gid0)
            if nn0 is not None:
                nn0.activation = src_e0.get(gid0, 0.0)
    # 第 2 步扩散：价值源→账本的边把 outcome 真正点亮——排序由扩散
    # 产生，算术只写流量大小（图一元）。
    eng.mark_active([oid for _a, oid in made])
    eng.diffuse_step()
    with kg._lock:
        scored = [(float(kg.nodes[o].activation or 0.0) if o in kg.nodes
                   else 0.0, a, o) for a, o in made]
    scored.sort(key=lambda x: -x[0])
    best_score, best_a, best_oid = (scored[0] if scored and scored[0][0]
                                    > 0.08 else (0, None, None))
    trace = {"seeds": [{"node": x, "e": round(e, 2), "why": w}
                       for x, e, w in seeds],
             "outcomes": [{"action": a["id"], "activation": round(sc, 3)}
                          for sc, a, _o in scored],
             "chosen": (best_a or {}).get("id"),
             "preds": preds,
             "mode": "graph_monism_v2"}
    with kg._lock:
        for _a, o in made:
            nn = kg.nodes.get(o)
            if nn is not None:
                nn.activation = 0.0
    return best_a, trace


def observe_outcome(kg, cid, predicted, actual):
    """学习闭环：预测 vs 实际的差 → 只写 kind=response 的经验边，
    不改 kb 语义边（任务书 §七：学习不能改写已确认的规则）。
    小幅、限幅、单次证据有限（防一次偶然永久强化）。"""
    from graph_model import Edge
    err = float(actual.get("dealt", 0)) - float(predicted.get("伤害", 0))
    good = abs(err) <= 1 and (actual.get("kill") == predicted.get("击杀"))
    # 在卡实例上累计校准分（0.9 保留 + 0.1 新证据），供后续降置信
    n = kg.get_node(cid)
    if n is None:
        return
    ea = n.extra_attrs if isinstance(n.extra_attrs, dict) else {}
    cal = float(ea.get("calib", 0.7))
    ea["calib"] = round(max(0.2, min(0.95,
                                     cal * 0.9 + (0.95 if good
                                                  else 0.3) * 0.1)), 3)
    n.extra_attrs = ea
    if not good:
        for e in kg.edges:
            if e.src == cid and isinstance(e.extra_attrs, dict) \
                    and e.extra_attrs.get("kind") == "response_doubt":
                return
        kg.add_edge(Edge(src=cid, dst=ea.get("last_mech", cid),
                         relation="影响", weight=-0.2,
                         extra_attrs={"kind": "response_doubt",
                                      "evidence": "prediction_mismatch"}))


# ── 商店图一元决策（2026-10-16，用户追问"买不买是不是硬逻辑"后改造）：
# 与战斗同款模式——商品文本解析成语义项，写成"价值源→行动账本"的流量边；
# "离开"也是账本节点；出分由节点能量排序，阈值只做物理事实过滤（够金）。
# 唯一先验是声明式的语义映射表（同 _TAG_BRIDGES 性质），不是策略 if。
_SHOP_TAGS = [                      # 关键词 → 价值源 → 支持边基权
    (("回复", "治疗", "生命", "护甲", "格挡"), "生存资源", 0.30),
    (("升级", "抽", "牌", "金币", "能量", "获得", "随机"), "延迟收益", 0.32),
    (("伤害", "脆弱", "虚弱", "易伤"), "期望收益", 0.30),
]


def decide_shop(kg, eng, gold, hp, max_hp, items):
    """items: [{"key","kind","index","name","price","text"}]（调用方已按
    enough_gold 物理过滤）。返回 (chosen_item|None, trace)。None=离开。"""
    from graph_model import Node, Edge
    import re as _re
    _clear_outcomes(kg)
    with kg._lock:
        for n in kg.nodes.values():
            n.activation = 0.0
    eng._active_nodes.clear()
    # 价值源能量：全部由数字算出（血量比、钱包紧度），无商品特判
    hp_r = max(0.0, min(1.0, float(hp) / max(1, max_hp)))
    se = {
        "GC:生存资源": 1.5 + 1.6 * (1.0 - hp_r),
        "GC:延迟收益": 1.6,
        "GC:机会成本": 1.2 + 1.4 * min(1.0, 60.0 / max(gold, 1)),
        "GC:期望收益": 1.1,
    }
    for gid, e in se.items():
        n = kg.get_node(gid)
        if n is not None:
            with kg._lock:
                n.activation = e
    # 激素调制（商店情境：无即时威胁→肾上腺素≈基线；rich=钱包宽裕度）
    ensure_hormone_subgraph(kg)
    se = hormone_bias(kg, eng, {"hp_r": hp_r, "lethal": False,
                                "inc": 0.0,
                                "rich": min(1.0, gold / 200.0)}, se)
    # 购物经验通道：商品是节点（ShopItem:名），历史"买过→结果"写在
    # 标签:购物-针对->ShopItem 的 response 边上；点亮购物情境后扩散一步，
    # 让经验沿边流进商品节点（与战斗侧经验通道同构，不是查表加分）
    if kg.get_node("标签:购物") is None:
        from graph_model import Node as _N
        kg.add_node(_N(id="标签:购物", weight=0.45,
                       label="declarative-semantic",
                       extra_attrs={"type": "sts_tag",
                                    "kind": "kb_bridge_seed"}))
    for it in items:
        sid = "ShopItem:%s" % it["name"]
        if kg.get_node(sid) is None:
            from graph_model import Node as _N
            kg.add_node(_N(id=sid, weight=0.5,
                           label="declarative-semantic",
                           extra_attrs={"type": "card_instance",
                                        "kind": "kb"}))
    ntag = kg.get_node("标签:购物")
    with kg._lock:
        ntag.activation = 1.8
    eng.mark_active(["标签:购物"])
    eng.diffuse_step()
    made = []
    flows = {}
    for it in list(items) + [{"key": "leave", "kind": "leave",
                              "index": None, "name": "空手离开",
                              "price": 0, "text": ""}]:
        oid = OUT_PREFIX + "shop_" + str(it["key"])
        kg.add_node(Node(id=oid, weight=0.3, label="declarative-episodic",
                         graph_space="self",
                         extra_attrs={"type": "action_outcome",
                                      "action": oid}))
        made.append((it, oid))
        f = 0.02
        if it["kind"] == "leave":
            # 省钱本身就是机会成本的兑现：离开节点吃机会成本支持边。
            # 支持强度随健康调制——残血时"留着钱"的兑现价值低（钱要
            # 花在能救命的东西上），由 hp 比算出，非策略 if。
            lw = 0.25 + 0.5 * hp_r
            if kg.get_edge("GC:机会成本", oid, "相关") is None:
                kg.add_edge(Edge(src="GC:机会成本", dst=oid,
                                 relation="相关", weight=lw,
                                 extra_attrs={"kind": "support",
                                              "fact": "保存金币"}))
            f += 0.5 * lw * se["GC:机会成本"]
        else:
            txt = it.get("text") or ""
            hit_any = False
            for kws, gname, base in _SHOP_TAGS:
                n_hit = sum(txt.count(k) > 0 for k in kws)
                if not n_hit:
                    continue
                hit_any = True
                w = base + 0.08 * n_hit
                if gname == "生存资源":
                    # 需求越高（血越少），生存类商品支持边越强——
                    # 连续函数调制，替代旧版"≤60%家当就买"的硬阈值
                    w += 0.5 * (1.0 - hp_r)
                w = min(1.2, w)
                gid = "GC:" + gname
                if kg.get_node(gid) is not None and \
                        kg.get_edge(gid, oid, "相关") is None:
                    kg.add_edge(Edge(src=gid, dst=oid, relation="相关",
                                     weight=w,
                                     extra_attrs={"kind": "support",
                                                  "fact": "%s×%d" %
                                                  (gname, n_hit)}))
                f += 0.5 * w * se[gid]
            if not hit_any:
                # 解析不出语义的遗物按期权价值给弱支持（声明式先验，
                # 与 kb_bridge 的 derivation 边同性质）
                gid = "GC:延迟收益"
                if kg.get_node(gid) and kg.get_edge(gid, oid, "相关") is None:
                    kg.add_edge(Edge(src=gid, dst=oid, relation="相关",
                                     weight=0.3,
                                     extra_attrs={"kind": "support",
                                                  "fact": "未知期权"}))
                f += 0.5 * 0.3 * se[gid]
            m0 = _re.search(r"(\d+)", txt)
            dmg = int(m0.group(1)) if "伤害" in txt and m0 else 0
            if dmg:
                f += 0.5 * min(1.0, 0.2 + dmg / 10.0) * se["GC:期望收益"]
            price = int(it.get("price") or 0)
            iw = min(1.0, 0.2 + 0.9 * price / max(gold, 1))
            gid = "GC:机会成本"
            if kg.get_node(gid) and kg.get_edge(gid, oid, "抑制") is None:
                kg.add_edge(Edge(src=gid, dst=oid, relation="抑制",
                                 weight=-iw,
                                 extra_attrs={"kind": "support",
                                              "fact": "价%d/钱包%d" %
                                              (price, gold)}))
            f -= 0.4 * iw * se[gid]
            # 经验通道：该商品历史"买了→局终结果"的 response 边权重
            # 经"标签:购物→ShopItem"扩散点亮后的激活值参与出分（图一元，
            # 非查表加分——上面已 mark_active+diffuse_step 把经验流进来）
            sn = kg.get_node("ShopItem:%s" % it["name"])
            if sn is not None:
                f += 0.45 * float(sn.activation or 0.0)
        flows[oid] = f
    with kg._lock:
        for oid, v in flows.items():
            nn = kg.nodes.get(oid)
            if nn is not None:
                nn.activation = max(0.0, v)
    scored = sorted(((max(0.0, flows[oid]), it) for it, oid in made),
                    key=lambda x: -x[0])
    best_v, best_it = scored[0]
    with kg._lock:
        for _i, o in made:
            nn = kg.nodes.get(o)
            if nn is not None:
                nn.activation = 0.0
    trace = {"board": [(it["name"], round(max(0.0, flows[OUT_PREFIX +
                  "shop_" + str(it["key"])]), 2))
                  for (it, _o) in made],
             "se": {k: round(v, 2) for k, v in se.items()}}
    if best_it["kind"] == "leave":
        return None, trace
    return best_it, trace


# ── 通用图选择器（2026-10-16 用户"全搞定"：事件/奖励/篝火/地图/宝箱/
# 角色/用药全部接进同一条图一元流水线）。特征→价值源带符号边（权重是
# 算术算出来的流量系数），历史选择在 标签:场景-针对->Choice:场景:名 的
# response 边上，经扩散流入出分——和战斗出牌、商店购物同构。
def ensure_choice_tag(kg, scenario):
    from graph_model import Node as _N
    tid = "标签:" + scenario
    if kg.get_node(tid) is None:
        kg.add_node(_N(id=tid, weight=0.45, label="declarative-semantic",
                       extra_attrs={"type": "sts_tag",
                                    "kind": "kb_bridge_seed"}))
    return tid


def choice_node_id(scenario, name):
    return "Choice:%s:%s" % (scenario, name)


def choice_credit(kg, scenario, name, credit):
    """选择→局果的经验写回（复用 update_response_weights 的钳位与
    kind=response 纪律）；节点/标签缺失则补建，保证回流不丢。"""
    from sts2_sim import knowledge_graph as _KG
    from graph_model import Node as _N
    ensure_choice_tag(kg, scenario)
    nid = choice_node_id(scenario, name)
    if kg.get_node(nid) is None:
        kg.add_node(_N(id=nid, weight=0.5, label="declarative-semantic",
                       extra_attrs={"type": "card_instance", "kind": "kb"}))
    return _KG.update_response_weights(kg, [scenario], nid, credit)


def gc_base_energies(ctx):
    """六个价值源的基础能量：全部由客观数字算出（血比/来袭/钱包）。"""
    hp_r = max(0.0, min(1.0, float(ctx.get("hp_r", 1.0))))
    inc = float(ctx.get("inc", 0))
    gold = ctx.get("gold")
    return {
        "GC:生存资源": 1.5 + 1.6 * (1.0 - hp_r),
        "GC:威胁消除": 1.2 + 0.6 * min(1.0, inc / 20.0),
        "GC:期望收益": 1.1,
        "GC:延迟收益": 1.5,
        "GC:机会成本": (1.2 + 1.4 * min(1.0, 60.0 / max(int(gold), 1)))
        if gold is not None else 1.5,
        "GC:风险": 0.6 + 1.8 * (1.0 - hp_r),
    }


def decide_choice(kg, eng, scenario, options, ctx):
    """options: [{"key","name","feats":[(GC名, w)],"inhib":[(GC名, w)]}]
    返回 (best_option|None, trace)。ctx 见 gc_base_energies + lethal/rich。"""
    from graph_model import Node, Edge
    _clear_outcomes(kg)
    with kg._lock:
        for n in kg.nodes.values():
            n.activation = 0.0
    eng._active_nodes.clear()
    se = gc_base_energies(ctx)
    ensure_hormone_subgraph(kg)
    for gid, e in se.items():
        n = kg.get_node(gid)
        if n is not None:
            with kg._lock:
                n.activation = e
    se = hormone_bias(kg, eng, {
        "hp_r": ctx.get("hp_r", 1.0), "lethal": ctx.get("lethal", False),
        "inc": ctx.get("inc", 0.0),
        "rich": ctx.get("rich", 0.5)}, se)
    tid = ensure_choice_tag(kg, scenario)
    for o in options:
        nid = choice_node_id(scenario, o["name"])
        if kg.get_node(nid) is None:
            kg.add_node(Node(id=nid, weight=0.5,
                             label="declarative-semantic",
                             extra_attrs={"type": "card_instance",
                                          "kind": "kb"}))
    tn = kg.get_node(tid)
    with kg._lock:
        tn.activation = 1.8
    eng.mark_active([tid])
    eng.diffuse_step()
    made = []
    flows = {}
    for o in options:
        oid = OUT_PREFIX + "ch_" + str(o["key"])
        kg.add_node(Node(id=oid, weight=0.3, label="declarative-episodic",
                         graph_space="self",
                         extra_attrs={"type": "action_outcome",
                                      "action": oid}))
        made.append((o, oid))
        f = 0.02
        for g, w in o.get("feats") or []:
            gid = g if str(g).startswith("GC:") else "GC:" + g
            if kg.get_node(gid) is None or w <= 0:
                continue
            if kg.get_edge(gid, oid, "相关") is None:
                kg.add_edge(Edge(src=gid, dst=oid, relation="相关",
                                 weight=min(1.2, w),
                                 extra_attrs={"kind": "support",
                                              "fact": o.get("why", "")}))
            f += 0.5 * min(1.2, w) * se[gid]
        for g, w in o.get("inhib") or []:
            gid = g if str(g).startswith("GC:") else "GC:" + g
            if kg.get_node(gid) is None or w <= 0:
                continue
            if kg.get_edge(gid, oid, "抑制") is None:
                kg.add_edge(Edge(src=gid, dst=oid, relation="抑制",
                                 weight=-min(1.2, w),
                                 extra_attrs={"kind": "support",
                                              "fact": o.get("why", "")}))
            f -= 0.4 * min(1.2, w) * se[gid]
        sn = kg.get_node(choice_node_id(scenario, o["name"]))
        if sn is not None:
            f += 0.45 * float(sn.activation or 0.0)
        flows[oid] = f
    with kg._lock:
        for oid, v in flows.items():
            nn = kg.nodes.get(oid)
            if nn is not None:
                nn.activation = max(0.0, v)
    scored = sorted(((max(0.0, flows[oid]), o) for o, oid in made),
                    key=lambda x: -x[0])
    board = [(o["name"], round(flows[oid], 2)) for o, oid in made]
    with kg._lock:
        for _o, oid in made:
            nn = kg.nodes.get(oid)
            if nn is not None:
                nn.activation = 0.0
    if not scored or scored[0][0] <= 0.03:
        return None, {"board": board, "se": {k: round(v, 2)
                                             for k, v in se.items()}}
    return scored[0][1], {"board": board, "se": {k: round(v, 2)
                                                for k, v in se.items()}}


def parse_features(text, hp_r=1.0):
    """把选项文本翻成价值源特征（声明式关键词表，和 _SHOP_TAGS 同族）。
    返回 (feats, inhib)；负面词进 inhib（风险/生存损失）。"""
    import re as _re
    feats = []
    inhib = []
    # 真实语料清洗：内联图标路径 res://...、富文本标记 [blue]/[/gold]/
    # [center]（2026-10-16 /state 实测泄漏进规则文本）
    text = _re.sub(r"res://\S+", "", text or "")
    text = _re.sub(r"\[/?[a-zA-Z]+\]", "", text)
    if not text:
        return [("延迟收益", 0.25)], []        # 空文本=未知期权先验
    m = _re.search(r"回复\s*(\d+)\s*点?生命|回复最大生命值的?\d+%?[（(]?(\d+)?",
                   text)
    heal = max(int(g or 0) for g in (m.groups() if m else (0,))) if m else 0
    if heal:
        feats.append(("生存资源",
                      (0.30 + 0.02 * heal) * (1.4 - hp_r)))
    if any(k in text for k in ("升级", "锻造", "永久", "每场", "每3")):
        feats.append(("延迟收益", 0.35 + 0.25 * hp_r))
    if any(k in text for k in ("获得", "加入", "添加", "随机稀有", "复制")):
        feats.append(("延迟收益", 0.30))
        feats.append(("期望收益", 0.20))
    m2 = _re.search(r"造成\s*(\d+)\s*点?伤害", text)
    if m2:
        d = int(m2.group(1))
        feats.append(("期望收益", min(0.8, 0.2 + d / 12.0)))
    if any(k in text for k in ("虚弱", "易伤", "脆弱", "削弱")):
        feats.append(("期望收益", 0.25))
    if any(k in text for k in ("金币", "钱")):
        feats.append(("延迟收益", 0.2))
    m3 = _re.search(r"(?:失去|受到)\s*(\d+)", text)
    if m3:
        loss = int(m3.group(1))
        inhib.append(("生存资源", 0.0))
        inhib.pop()
        inhib.append(("风险", (0.35 + 0.05 * loss) * (1.4 - hp_r)))
    if any(k in text for k in ("移除", "消耗", "丢弃", "不能获得")):
        inhib.append(("风险", 0.4))
    if any(k in text for k in ("战斗", "精英")):
        inhib.append(("风险", 0.5 * (1.0 - hp_r)))
        feats.append(("期望收益", 0.25))
    return feats, inhib


def load_experience(kg, path):
    """跨会话经验装载（宿主 JSON → 图）：response 边 + 卡校准。
    端点缺失即补建（不补则整批边被 add_edge 丢弃）。"""
    import json
    import os as _os
    from graph_model import Node, Edge
    if not path or not _os.path.exists(path):
        return {"edges": 0, "calib": 0}
    data = json.load(open(path, encoding="utf-8"))
    n_e = 0
    for rec in data.get("response_edges") or []:
        for nid in (rec["src"], rec["dst"]):
            if kg.get_node(nid) is None:
                tag = str(nid).startswith("标签:")
                kg.add_node(Node(id=nid, weight=0.45 if tag else 0.5,
                                 label="declarative-semantic",
                                 extra_attrs={"type": "sts_tag" if tag
                                              else "card_instance",
                                             "kind": "kb"}))
        if kg.get_edge(rec["src"], rec["dst"], "针对") is None:
            kg.add_edge(Edge(src=rec["src"], dst=rec["dst"],
                             relation="针对", weight=float(rec["weight"]),
                             extra_attrs={"kind": "response",
                                          "evidence": "live"}))
            n_e += 1
    n_c = 0
    for cid, cal in (data.get("calib") or {}).items():
        if kg.get_node(cid) is None:
            kg.add_node(Node(id=cid, weight=0.5,
                             label="declarative-semantic",
                             extra_attrs={"type": "card_instance",
                                          "kind": "kb"}))
        n = kg.get_node(cid)
        ea = n.extra_attrs or {}
        ea["calib"] = float(cal)
        n.extra_attrs = ea
        n_c += 1
    return {"edges": n_e, "calib": n_c}


def persist_experience(kg, path):
    """经验落盘（宿主数据文件，非生产图谱）。"""
    import json
    import os as _os
    resp = [{"src": e.src, "dst": e.dst, "weight": float(e.weight)}
            for e in kg.edges
            if isinstance(e.extra_attrs, dict)
            and e.extra_attrs.get("kind") == "response"]
    cal = {nid: float((n.extra_attrs or {}).get("calib") or 0.7)
           for nid, n in kg.nodes.items()
           if str((n.extra_attrs or {}).get("type") or "") == "card_instance"}
    if path:
        d = _os.path.dirname(path)
        if d:
            _os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"response_edges": resp, "calib": cal}, f,
                      ensure_ascii=False)
    return {"edges": len(resp), "calib": len(cal)}
