# memrep.py — 统一记忆表示：事实（时间有效+来源）、经历事件、个体实例、
#              同指消解、工作集序列化
# ============================================================================
# 设计：docs/MEMREP_DESIGN_2026-10-09.md；审计：docs/audits/MEMREP_AUDIT_2026-10-09.md
#
# 表示原则（通用，非按对象类型）：
#   1. 图 = 当前认知为真的东西（概念/实例/当前有效关系）。唯一三元组不变量、
#      归一漏斗、扩散、遗忘机制全部不动。
#   2. 时间轴 = 复用 ExperienceTimeline（唯一持久、有界、可查 since 的事件流）。
#      关系变更的**历史**以 FACT_CHANGE 事件记录（valid_from→valid_until 区间
#      + 来源），图边只保留当前值——旧状态不留在图上参与扩散/判断，
#      "过去在哪"走 fact_history 查询。图↔轴双向回链（节点 attrs.ev ↔ 事件 meta.kg_node）。
#   3. 事件节点仅在需要保留"动作+参与者+结果"时创建（record_episode），
#      槽位放节点属性（归一漏斗会吸收结构角色词——主体/客体/后继 入引擎
#      即变"关联"，serial_fix 实测），图边只连已注册词表的关系（涉及/发生于）。
#   4. 个体实例 = `个体:{概念}:{区分符}` 节点 + `实例属于` 边（新词已注册
#      config.relation_ontology）。同概念多实例不合并；同指消解只提供显式
#      link_mentions（`同一` 边+provenance），证据不足不建边、不自动合并。
#   5. 序列化 = 图有据补全的紧凑工作集（身份/方向/时间/来源不丢，非裸 id，
#      不写散文）。
#
# 来源枚举（不伪装）：observed / user_stated / inferred / action_result。
# 兼容：全部 additive（extra_attrs / timeline 追加），旧数据缺字段=如实降级
# （"来源未记录"），不回填不伪造。回滚 = 不调用（本模块无生产自动接线，
# 试点写点见 action_system._write_action_memory 的 memrep 门控）。
# ============================================================================

import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)

SOURCES = ("observed", "user_stated", "inferred", "action_result",
           "text_stated")   # 阅读/文档证据（reading.py 2026-10-12，additive）
FACT_CHANGE = "FACT_CHANGE"       # timeline 事件类型（additive 常量）
EPISODE = "EPISODE"

_TL = {}                          # path → ExperienceTimeline 单例
_TL_LOCK = threading.Lock()


def _cfg(config):
    return (config or {}).get("memrep") or {}


def get_timeline(config=None):
    """时间轴单例（按 path）。app 已注入的 timeline 优先（外部赋值方
    可直接传 tl 参数绕过本单例）。"""
    path = str(_cfg(config).get("timeline_path")
               or "data/experience_timeline.json")
    with _TL_LOCK:
        tl = _TL.get(path)
        if tl is None:
            from experience import ExperienceTimeline
            tl = ExperienceTimeline(path=path)
            _TL[path] = tl
        return tl


def now_iso(ts=None):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(ts if ts is not None else time.time()))


def _norm_source(source):
    s = str(source or "").strip()
    return s if s in SOURCES else "未记录"


# ── 事实：当前有效关系 + 历史区间（图=现在，轴=历史）────────────────

def record_fact(kg, src, rel, dst, *, source="observed", confidence=1.0,
                tl=None, config=None, actor="self"):
    """断言 (src, rel, dst) 现在成立。边不存在则建（attrs 带
    valid_from/source/ev 回链）并写 FACT_CHANGE(add)；已存在则视为重复
    断言，不重复记流水。不改既有边权（调用方语义优先）。"""
    from graph_model import Edge
    old = kg.get_edge(src, dst, rel)
    if old is not None:
        return {"status": "exists", "edge": old}
    ts = time.time()
    e = Edge(src=src, dst=dst, relation=rel,
             extra_attrs={"source": _norm_source(source),
                          "valid_from": now_iso(ts), "confidence": confidence})
    if not kg.add_edge(e):
        return {"status": "rejected", "reason": "add_edge_rejected"}
    ev = None
    if tl is not None:
        ev = tl.append({
            "id": "ev_" + uuid.uuid4().hex[:10], "ts": ts,
            "ts_str": time.strftime("%H:%M:%S", time.localtime(ts)),
            "event_type": FACT_CHANGE, "actor": str(actor),
            "subject": f"{src}",
            "content": {"relation": rel, "object": dst, "change": "add",
                        "valid_from": now_iso(ts)},
            "source": _norm_source(source), "confidence": confidence,
            "meta": {"kg_nodes": [src, dst], "ts_iso": now_iso(ts)}},
            merge_window_s=0.0)
        try:
            e.extra_attrs["ev"] = (ev or {}).get("id")
        except Exception:
            pass
    return {"status": "added", "edge": e, "ev": (ev or {}).get("id")}


def supersede_fact(kg, src, rel, dst_old, dst_new=None, *, source="observed",
                   confidence=1.0, tl=None, config=None, actor="self"):
    """关系真值变化：旧边**摘除**（历史进时间轴，不留在图上参与判断），
    新边可选建立。同三元组唯一不变量不破坏。"""
    ts = time.time()
    old = kg.get_edge(src, dst_old, rel)
    old_from = (old.extra_attrs or {}).get("valid_from") if old else None
    old_src = (old.extra_attrs or {}).get("source") if old else None
    ev_id = None
    if tl is not None:
        ev = tl.append({
            "id": "ev_" + uuid.uuid4().hex[:10], "ts": ts,
            "ts_str": time.strftime("%H:%M:%S", time.localtime(ts)),
            "event_type": FACT_CHANGE, "actor": str(actor), "subject": src,
            "content": {"relation": rel, "object": dst_old,
                        "change": "supersede",
                        "valid_from": old_from or "未记录",
                        "valid_until": now_iso(ts),
                        "superseded_by": dst_new},
            "source": _norm_source(source), "confidence": confidence,
            "meta": {"kg_nodes": [src, dst_old]
                     + ([dst_new] if dst_new else []),
                     "ts_iso": now_iso(ts)}},
            merge_window_s=0.0)
        ev_id = (ev or {}).get("id")
    if old is not None:
        kg.remove_edges(src=src, dst=dst_old, relation=rel)
    if dst_new is not None:
        record_fact(kg, src, rel, dst_new, source=source,
                    confidence=confidence, tl=tl, config=config, actor=actor)
    return {"status": "superseded", "closed": bool(old is not None),
            "old_valid_from": old_from, "old_source": old_src,
            "ev": ev_id}


def fact_history(tl, subject, relation=None):
    """历史查询：某主体（可选限定关系）的**每对象一个区间**，按对象名排序。
    区间 = 该对象事实的首次生效到最近一次失效；valid_until 为空 = 当前有效。
    事件本身时间升序消费（tl.recent 是新序，先反转）。"""
    evs = [e for e in (tl.recent(100000) if tl else [])
           if e.get("event_type") == FACT_CHANGE
           and str(e.get("subject")) == str(subject)]
    evs.sort(key=lambda e: e.get("ts", 0))
    iv = {}
    for e in evs:
        c = e.get("content") or {}
        if relation is not None and c.get("relation") != relation:
            continue
        obj = c.get("object")
        cur = iv.setdefault(obj, {"object": obj,
                                  "relation": c.get("relation"),
                                  "valid_from": c.get("valid_from"),
                                  "valid_until": None,
                                  "source": e.get("source"),
                                  "changes": 0})
        cur["changes"] += 1
        if c.get("change") == "supersede":
            cur["valid_until"] = c.get("valid_until")
            cur["valid_from"] = cur["valid_from"] or c.get("valid_from")
        else:
            cur["valid_until"] = None      # 重新生效 = 开区间
            cur["valid_from"] = cur["valid_from"] or c.get("valid_from")
    return sorted(iv.values(), key=lambda x: str(x["object"]))


# ── 经历事件（动作+参与者需要保留时才建节点）────────────────────

def record_episode(kg, tl, action, subject, obj, *, source="action_result",
                   ts=None, extra=None, actor="self"):
    """创建经历事件节点（槽位在 attrs——归一漏斗不碰属性），图边只连
    已注册关系（涉及）。timeline 同步记 EPISODE 事件，双向回链。"""
    from graph_model import Node, Edge
    ts = time.time() if ts is None else float(ts)
    nid = f"事件:{action}@{int(ts * 1000) % 10 ** 9}"
    if kg.get_node(nid) is not None:
        nid = f"{nid}#{int(ts * 1e6) % 1000}"
    attrs = {"type": "episode", "action": str(action),
             "subject": str(subject), "object": str(obj),
             "source": _norm_source(source), "ts_iso": now_iso(ts)}
    if extra:
        attrs.update({k: v for k, v in extra.items()
                      if k not in attrs})
    kg.add_node(Node(id=nid, label="declarative-episodic",
                     graph_space="episodic", extra_attrs=attrs))
    ev = None
    if tl is not None:
        ev = tl.append({
            "id": "ev_" + uuid.uuid4().hex[:10], "ts": ts,
            "ts_str": time.strftime("%H:%M:%S", time.localtime(ts)),
            "event_type": EPISODE, "actor": str(actor),
            "subject": f"{subject} {action} {obj}",
            "content": {"action": action, "subject": subject,
                        "object": obj},
            "source": _norm_source(source), "confidence": 1.0,
            "meta": {"kg_node": nid, "ts_iso": now_iso(ts)}},
            merge_window_s=0.0)
        attrs["ev"] = (ev or {}).get("id")
    for role, target in (("subject", subject), ("object", obj)):
        if target and kg.get_node(str(target)) is not None:
            kg.add_edge(Edge(src=nid, dst=str(target), relation="涉及",
                             weight=0.6,
                             extra_attrs={"role": role,
                                          "source": _norm_source(source)}))
    return {"node": nid, "ev": (ev or {}).get("id")}


def enrich_action_node(kg, tl, node, *, action_type, target, source,
                       actor="self", ts=None):
    """给既有行动留痕节点补结构槽位（action/object/ts_iso）+ timeline
    EPISODE 回链（ev ↔ meta.kg_node）。试点通道：action_system，
    config.memrep.enabled 门控。不改变节点 id/类型/边结构。"""
    ts = time.time() if ts is None else float(ts)
    if node is None:
        return None
    if not isinstance(node.extra_attrs, dict):
        node.extra_attrs = {}
    node.extra_attrs.update({"action": str(action_type),
                             "object": str(target or ""),
                             "ts_iso": now_iso(ts)})
    ev_id = None
    if tl is not None:
        ev = tl.append({
            "id": "ev_" + uuid.uuid4().hex[:10], "ts": ts,
            "ts_str": time.strftime("%H:%M:%S", time.localtime(ts)),
            "event_type": EPISODE, "actor": str(actor),
            "subject": f"self {action_type} {target or ''}".strip(),
            "content": {"action": str(action_type), "object": str(target or "")},
            "source": _norm_source(source), "confidence": 1.0,
            "meta": {"kg_node": node.id, "ts_iso": now_iso(ts)}},
            merge_window_s=0.0)
        ev_id = (ev or {}).get("id")
        node.extra_attrs["ev"] = ev_id
    return ev_id


# ── 个体实例与同指 ────────────────────────────────────────

def instance_id(concept, disc):
    return f"个体:{concept}:{disc}"


def get_or_create_instance(kg, concept, disc, *, source="observed"):
    """取/建某概念的一个具体个体。同概念多实例=不同 disc=不同节点，
    绝不因同名合并。个体与概念间用已注册的 实例属于 边。"""
    from graph_model import Node, Edge
    iid = instance_id(concept, disc)
    if kg.get_node(iid) is None:
        kg.add_node(Node(id=iid, extra_attrs={
            "type": "instance", "instance_of": str(concept),
            "discriminator": str(disc), "source": _norm_source(source),
            "created": now_iso()}))
    if kg.get_node(str(concept)) is None:
        kg.add_node(Node(id=str(concept), extra_attrs={"type": "concept"}))
    if kg.get_edge(iid, str(concept), "实例属于") is None:
        kg.add_edge(Edge(src=iid, dst=str(concept), relation="实例属于",
                         weight=0.9,
                         extra_attrs={"source": _norm_source(source)}))
    return kg.get_node(iid)


def link_mentions(kg, a, b, confidence=0.6, *, source="inferred"):
    """显式同指：两个提及（节点）写 `同一` 边（词表已有、双向）。证据
    不足由调用方不调用——本函数不做自动判定、不合并节点。"""
    from graph_model import Edge
    if kg.get_node(a) is None or kg.get_node(b) is None or a == b:
        return None
    e = Edge(src=a, dst=b, relation="同一", weight=float(confidence),
             extra_attrs={"source": _norm_source(source)})
    if kg.add_edge(e):
        return e
    return kg.get_edge(a, b, "同一")


def co_referents(kg, nid):
    """同一 的显式同指集合（含自身）。"""
    out = {nid}
    for e in kg.get_out_edges(nid) + kg.get_in_edges(nid):
        if e.relation == "同一":
            out.add(e.dst if str(e.src) == nid else e.src)
    return out


# ── 工作集序列化（图有据补全，紧凑、保语义）────────────────────

def _fmt_validity(ea):
    vf, vu = ea.get("valid_from"), ea.get("valid_until")
    if vu:
        return f"[{vf or '未记录'}~{vu}，已失效]"
    if vf:
        return f"[自{vf}]"
    return "[时间未记录]"


def serialize_working_set(top_nodes, edges, kg, tl=None):
    """Top-k 节点 + 一跳邻接边 → 紧凑有语义文本：
      事件节点 → "事件 {action}: {subject} {action} {object} @ts（来源）"
      实例节点 → "个体:{概念}:{disc}（{concept} 的个体）"
      关系边   → "A -[rel]-> B [有效期, 来源]"（历史失效边如实标注）
      其余     → id + 类型
    不读任何问题/答案数据；1-hop 补全同 serial_fix 口径。"""
    top_ids = {n.id for n in top_nodes}
    act = {n.id: float(n.activation or 0) for n in top_nodes}
    lines = []
    evs = sorted((n for n in top_nodes
                  if (n.extra_attrs or {}).get("type") == "episode"),
                 key=lambda n: -act.get(n.id, 0))
    for n in evs:
        ea = n.extra_attrs or {}
        lines.append(f"事件 {ea.get('action')}：{ea.get('subject')} "
                     f"{ea.get('action')} {ea.get('object')} "
                     f"@{ea.get('ts_iso') or '时间未记录'}"
                     f"（来源:{ea.get('source', '未记录')}）")
    seen = set()
    for e in edges:
        if e.relation == "实例属于":
            continue                     # 已渲染为个体描述行
        if e.src in top_ids and (kg.nodes.get(e.src).extra_attrs or {}).get(
                "type") == "episode":
            continue                     # 已渲染为经历句
        if e.src in top_ids or e.dst in top_ids:
            key = (e.src, e.relation, e.dst)
            if key in seen:
                continue
            seen.add(key)
            ea = e.extra_attrs or {}
            if ea.get("type") == "episode":
                continue
            mark = _fmt_validity(ea) if (ea.get("valid_from")
                                         or ea.get("valid_until")) else ""
            neg = "（失效/负权）" if float(e.weight) < 0 else ""
            lines.append(f"{e.src} -[{e.relation}]-> {e.dst} {mark}{neg}"
                         + (f"（来源:{ea.get('source', '未记录')}）"
                            if ea.get("source") else ""))
    for n in top_nodes:
        ea = n.extra_attrs or {}
        if ea.get("type") == "episode":
            continue
        if ea.get("type") == "instance":
            lines.append(f"{n.id}（{ea.get('instance_of')} 的个体）")
        elif n.id not in {str(e.src) for e in edges} | \
                {str(e.dst) for e in edges}:
            lines.append(f"{n.id}")
    return "\n".join(lines)
