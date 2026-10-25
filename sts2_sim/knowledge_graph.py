# -*- coding: utf-8 -*-
"""sts2_sim.knowledge_graph — 把尖塔知识装进她真实的图谱结构（2026-10-15）。

语义分工（刻意设计，不混）：
  · **图谱=注意与联想**：卡/标签/威胁作为真实节点，意图标签被点亮后，
    扩散让相关卡"回到脑里"——boost 只决定"她想不想得起这张牌"，
    不决定"这张牌好不好"；
  · **经验统计=规避**：哪手牌亏血由 brain 的 exp 通道负责负向权重。
  · 局末记忆写 episodic 节点（"那次战败我最后在用 X"），供下局联想。
全部走 DiffusionEngine 合法接口（mark_active/diffuse_step），不直写内部字段。
"""
import os
import time


def _node(kg, nid, label="declarative-semantic", space="semantic",
          type_="concept", weight=0.45):
    if kg.get_node(nid) is not None:
        return False
    from graph_model import Node, Edge
    kg.add_node(Node(id=nid, weight=weight, label=label, graph_space=space,
                     extra_attrs={"type": type_}))
    return True


def import_sts_knowledge(kg, data):
    """幂等导入：卡-有->标签、卡-是->类型、敌人招式-带->标签。"""
    from graph_model import Edge
    made = 0
    for card, c in data["cards"].items():
        if _node(kg, card, type_="sts_card"):
            made += 1
        for tag in c["tags"]:
            _node(kg, f"标签:{tag}", type_="sts_tag")
            # 方向=能量可通行：标签-包含->卡（意图点亮标签后，扩散顺边
            # 流到卡——反向"卡具有标签"在正向语义关系下走不通，15:5x 诊断）
            if not kg.get_edge(f"标签:{tag}", card, "包含"):
                kg.add_edge(Edge(src=f"标签:{tag}", dst=card,
                                 relation="包含", weight=0.6))
        if not kg.get_edge(card, f"类型:{c['type']}", "是"):
            _node(kg, f"类型:{c['type']}", type_="sts_type")
            kg.add_edge(Edge(src=card, dst=f"类型:{c['type']}",
                             relation="是", weight=0.5))
    # 先验下图（2026-10-15 最终步）：威胁标签→卡片的"应对"直连边，
    # 初始权重=旧知识表的折算值——从此表只是**出生证**，后续演化由
    # 每手牌的即时血差归因改写边权（update_response_weights）。
    # 决策不再有"查表"，只有意图点亮→一跳扩散→激活竞争。
    from sts2_sim.brain import KNOWLEDGE as _PRIOR
    for threat, row in _PRIOR.items():
        tnode = f"标签:{threat}"
        _node(kg, tnode, type_="sts_tag")
        for card, c in data["cards"].items():
            w = sum(v for tag, v in row.items() if tag in c["tags"])
            if w > 0:
                if kg.get_edge(tnode, card, "针对") is None:
                    # 16:4x 诊断：非本体词（"应对"）会被 schema 静默
                    # 归一成"关联"——必须用本体内的"针对"，响应语义放
                    # extra 标记。
                    kg.add_edge(Edge(src=tnode, dst=card, relation="针对",
                                     weight=min(1.5, w),
                                     extra_attrs={"kind": "response"}))
    for en, proto in data["enemies"].items():
        _node(kg, en, type_="sts_enemy")
        for mv in proto["moves"]:
            mid = f"招式:{mv['name']}"
            _node(kg, mid, type_="sts_move")
            if not kg.get_edge(en, mid, "会"):
                kg.add_edge(Edge(src=en, dst=mid, relation="会",
                                 weight=0.5))
            for tag in mv.get("tags", []):
                _node(kg, f"标签:{tag}", type_="sts_tag")
                if not kg.get_edge(f"标签:{tag}", mid, "包含"):
                    kg.add_edge(Edge(src=f"标签:{tag}", dst=mid,
                                     relation="包含", weight=0.6))
    return made


_GK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "general_knowledge.json")


def import_general_knowledge(kg, game_data=None):
    """阶段2/3：通用客观知识层 + 跨域连接（概念-相关->游戏标签，
    证据标 derivation=可解释推导而非实测事实，置信0.5起步）。幂等。"""
    import json as _j
    from graph_model import Edge
    gk = _j.load(open(_GK_PATH, encoding="utf-8"))
    made = 0
    for cname, spec in gk["concepts"].items():
        nid = f"GC:{cname}"
        if kg.get_node(nid) is None:
            _node(kg, nid, type_=str(spec.get("kind") or "causal_concept"))
            made += 1
        for tgt_c in (gk.get("suppresses") or {}).get(cname, []):
            gid = f"GC:{tgt_c}"
            _node(kg, gid, type_="causal_concept")
            if kg.get_edge(nid, gid, "抑制") is None:
                kg.add_edge(Edge(src=nid, dst=gid, relation="抑制",
                                 weight=-0.85,
                                 extra_attrs={"kind": "concept_conflict",
                                              "evidence": "derivation"}))
        for tgt, w in (gk["applies_to"].get(cname) or []):
            _node(kg, tgt, type_="sts_tag")
            if kg.get_edge(nid, tgt, "相关") is None:
                kg.add_edge(Edge(src=nid, dst=tgt, relation="相关",
                                 weight=float(w) * 0.75,
                                 extra_attrs={"kind": "response",
                                              "evidence": "derivation",
                                              "confidence": 0.5}))
                made += 1
    return gk, made


def _ev(expr, snap):
    """情境触发器求值（感知层：环境状态→抽象概念的安全映射，
    表达式来自 JSON 数据、白名单变量，非策略代码）。"""
    if not expr:
        return False
    enemies = [e for e in snap.get("enemies", []) if e.get("hp", 0) > 0]
    ctx = {
        "hp_ratio": snap.get("hp", 0) / max(1, snap.get("max_hp", 68)),
        "max_intent_damage": max([e.get("intent_damage") or 0
                                  for e in enemies] or [0]),
        "enemy_hp_min": min([e["hp"] for e in enemies] or [999]),
        "block_planted": 0,
        "turn": snap.get("turn", 1), "hand_n": len(snap.get("hand", [])),
        "energy": snap.get("energy", 0),
    }
    try:
        return bool(eval(expr, {"__builtins__": {}}, ctx))
    except Exception:
        return False


def seed_situation(kg, engine, snap, gk_triggers):
    """阶段4核心：情境同时播种 意图标签（游戏域）与 命中触发器的通用概念
    （通用域）→ 一次扩散 → 返回 {card: boost} + 激活轨迹 trace。
    延迟收益类概念从此真实参与排序（gc→相关→防御标签→包含→卡 长链）。"""
    lit, used = [], []
    tags = set()
    for e in snap.get("enemies", []):
        if e.get("hp", 0) > 0:
            tags.update(e.get("intent_tags") or [])
    for t in tags:
        nid = f"标签:{t}"
        if kg.get_node(nid) is not None:
            lit.append(nid)
    for cname, trig in (gk_triggers or {}).items():
        if trig and _ev(trig, snap):
            gid = f"GC:{cname}"
            if kg.get_node(gid) is not None:
                lit.append(gid)
                used.append(cname)
    if not lit:
        return {}, []
    with kg._lock:
        for nid in lit:
            n = kg.nodes.get(nid)
            if n is not None:
                n.activation = max(float(n.activation or 0.0),
                                   3.0 if nid.startswith("标签:") else 2.0)
    engine.mark_active(lit)
    # 2 步：GC→游戏标签→卡 的跨域链恰为两跳（1 步只能到标签=通用知识
    # 空转，17:5x 诊断实证）；意图→卡的一跳直连边在第 1 步即生效。
    engine.diffuse_step()
    engine.diffuse_step()
    return lit, used


def update_response_weights(kg, threat_tags, card, hp_delta, lr=0.35):
    """一手牌的即时血差 → 该局面下各威胁→该卡 应对边权 的奖惩。
    正血差(这手赚了)加固，负血差削弱；权重钳 [0.05, 2.0]。
    这就是"经验改写图、图决定行为"的闭环，取代整局均摊的粗归因。"""
    from graph_model import Edge
    made = 0
    with kg._lock:
        for t in threat_tags:
            tnode = f"标签:{t}"
            if kg.get_node(tnode) is None:
                continue
            e = kg.get_edge(tnode, card, "针对")
            if e is None:
                kg.add_edge(Edge(src=tnode, dst=card, relation="针对",
                                 weight=max(0.05, min(2.0, 0.5 + lr * hp_delta / 5.0)),
                                 extra_attrs={"kind": "response"}))
                made += 1
                continue
            if not isinstance(e.extra_attrs, dict):
                e.extra_attrs = {}
            # 只进化 response 标记边；其他"针对"边不动
            if (e.extra_attrs or {}).get("kind") != "response":
                continue
            e.weight = max(0.05, min(2.0, float(e.weight) + lr * hp_delta / 5.0))
            made += 1
    return made


def attention_boost(kg, engine, snap, diffuse_steps=2):
    """当前敌人意图 → 点亮标签 → 扩散 2 步 → 读手牌节点的激活。
    返回 {card_name: boost∈[0,0.5]}——注意增益上限 0.5，压过但不碾压
    知识/经验通道（防扩散噪声绑架牌风）。"""
    if engine is None:
        return {}
    tags = set()
    for e in snap.get("enemies", []):
        if e.get("hp", 0) > 0:
            tags.update(e.get("intent_tags") or [])
    if not tags:
        return {}
    lit = [f"标签:{t}" for t in tags if kg.get_node(f"标签:{t}")]
    if not lit:
        return {}
    # 能量源（15:5x 解剖实锤修复：此前只 mark_active 不注能，扩散空转、
    # boost 恒 0——仓库规范本就是"写 activation → mark_active 同步前沿"
    # 成对出现（drive/vision 注入同套路），此处按规范补上能量注入）。
    with kg._lock:
        for nid in lit:
            n = kg.nodes.get(nid)
            if n is not None:
                # 源能量=3.0：与生产图谱的激活量纲一致（此前 0.8 经
                # 衰减链到卡只剩 0.03，低于决策阈值=信号自杀）
                n.activation = max(float(n.activation or 0.0), 3.0)
    engine.mark_active(lit)
    for _ in range(diffuse_steps):
        engine.diffuse_step()
    raw = {}
    for c in snap.get("hand", []):
        n = kg.get_node(c)
        if n is not None and float(n.activation or 0.0) > 1e-4:
            raw[c] = float(n.activation)
    out = {}
    if raw:
        # 绝对能量通道（17:4x 修正：相对归一 v/mx 把边权演化的绝对幅度
        # 全部抹平——1.0 的边和 5.0 的边同样吃满 0.5，进化被决策静音）。
        # 卡节点能量本就按边权×源能量衰减而来，直接线性映射+上限。
        for c, v in raw.items():
            out[c] = round(min(0.5, v * 4.0), 3)
    with kg._lock:
        # 读走即冷却（含标签源）：能量滞留会跨拍滚雪球
        for nid in lit:
            n = kg.nodes.get(nid)
            if n is not None:
                n.activation = float(n.activation) * 0.25
        for c in raw:
            n = kg.nodes.get(c)
            if n is not None:
                n.activation = float(n.activation) * 0.25
    return out


def write_battle_memory(kg, engine, battle, run, won):
    """局末 episodic 记忆：赢了记"什么牌陪我打赢了谁"，输了记"败局里
    我反复抓的是什么牌"（供下局联想，不直接改权重——权重由统计通道管）。"""
    from graph_model import Node, Edge
    if not battle or not battle.log:
        return None
    counts = {}
    for step in battle.log:
        counts[step.get("play")] = counts.get(step.get("play"), 0) + 1
    top = max(counts, key=lambda k: counts.get(k, 0)) if counts else "?"
    nid = (f"Activity_sts_{'胜' if won else '败'}_{run.floor}"
           f"_{int(time.time() * 1000)}")
    kg.add_node(Node(id=nid, weight=0.5, label="declarative-episodic",
                     graph_space="episodic",
                     extra_attrs={"type": "activity_experience",
                                  "kind": "sts_battle",
                                  "text": f"{'打赢' if won else '战败于'}"
                                          f"{run.last_enemy}，用得最多的是"
                                          f"{top}（{counts.get(top, 0)}次）",
                                  "value": "medium" if won else "high",
                                  "trust": "observed",
                                  "created": time.strftime(
                                      "%Y-%m-%d %H:%M:%S")}))
    if top and kg.get_node(top) is not None:
        kg.add_edge(Edge(src=nid, dst=top, relation="关于", weight=0.55))
    engine.mark_active(nid)
    return nid
