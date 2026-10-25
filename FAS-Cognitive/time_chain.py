# -*- coding: utf-8 -*-
"""情景时间链（任务书 2026-10-21）：情景记忆产生时锚定一个时点节点；
相邻时点用 早于/晚于 两条方向边互联（权重随时间间隔），取代散在各情景
节点上的时间信息；粗粒度时段边（发生于时段→上午/深夜）随迁到时点上。

时点节点是**纯脚手架**：type=time_node 已注册进 is_content_scaffold 与
is_non_emitting——不进 basis/素材/气泡，不向外泵能量；链只回答"谁先谁后"。

幂等：一个情景节点只锚一次（已有出向"发生于"边即跳过）。
乱序插入（回填/迟到的记忆）：在 prev/nxt 之间切开原有 早于/晚于 对，
接成 prev─早于→cur─早于→nxt（及两条晚于回程），链保持有序单链。
"""
import time

from graph_model import Node, Edge, now_str

_ANCHOR_PREFIX = "时点_"


def gap_weight(gap_s: float) -> float:
    """早于/晚于 边权：同日强连接，随间隔衰减，40h+ 落下限。
    1h≈0.90，6h≈0.88，24h≈0.84，40h→0.80……下限 0.6（跨多日仍是
    真实的先后事实，权只是弱，不是无）。上限 0.9：链边是结构而非
    语义论证，不该在扩散里压过内容边。"""
    g = max(0.0, float(gap_s))
    return round(max(0.6, min(0.9, 0.9 - (g / 86400.0) * 0.06)), 3)


def _anchors(kg):
    out = []
    with kg._lock:
        for n in kg.nodes.values():
            ea = n.extra_attrs or {}
            if str(ea.get("type") or "") == "time_node":
                out.append((n.id, float(ea.get("ts") or 0.0)))
    out.sort(key=lambda x: (x[1], x[0]))
    return out


def _link(kg, a, b, gap):
    """a 早于 b：建两条序边。"""
    w = gap_weight(gap)
    kg.add_edge(Edge(src=a, dst=b, relation="早于", weight=w))
    kg.add_edge(Edge(src=b, dst=a, relation="晚于", weight=w))


def anchor_episode(kg, episode_id, ts=None):
    """给情景记忆锚定时点。返回时点 id；None=跳过（节点不存在/已锚）。"""
    n = kg.get_node(episode_id)
    if n is None:
        return None
    if ts is None:
        cre = str(getattr(n, "created", "") or
                  (n.extra_attrs or {}).get("created") or "")
        ts = _parse_ts(cre) or time.time()
    ts = float(ts)
    with kg._lock:
        if any(e.src == episode_id and str(e.relation) == "发生于"
               for e in kg.edges):
            return None
    aids = _anchors(kg)
    aid = _ANCHOR_PREFIX + str(int(ts * 1000))
    if kg.get_node(aid) is None:
        with kg._lock:
            kg.add_node(Node(id=aid, weight=0.4, label="infrastructure",
                             graph_space="episodic", activation=0.0,
                             extra_attrs={"type": "time_node",
                                          "canon": "time_anchor",
                                          "ts": ts, "created": now_str()}))
        prev = [(i, t) for i, t in aids if t < ts]
        nxt = [(i, t) for i, t in aids if t > ts]
        p = prev[-1] if prev else None
        q = nxt[0] if nxt else None
        if p and q:
            # 切开旧序对，cur 插中间
            kg.remove_edge(p[0], q[0], "早于")
            kg.remove_edge(q[0], p[0], "晚于")
        if p:
            _link(kg, p[0], aid, ts - p[1])
        if q:
            _link(kg, aid, q[0], q[1] - ts)
    kg.add_edge(Edge(src=episode_id, dst=aid, relation="发生于", weight=0.6))
    _migrate_phase_edges(kg, episode_id, aid)
    return aid


def _migrate_phase_edges(kg, episode_id, aid):
    """粗时段边随迁：episode—发生于时段→桶 ⇒ aid—发生于时段→桶。
    时间信息由链承担（任务书第 1 条的"替换"）；桶边保留语义，只是换挂点。"""
    with kg._lock:
        move = [(e.dst) for e in kg.edges
                if e.src == episode_id and str(e.relation) == "发生于时段"]
    for bucket in move:
        kg.add_edge(Edge(src=aid, dst=bucket, relation="发生于时段",
                         weight=0.6))
        kg.remove_edge(episode_id, bucket, "发生于时段")


def _parse_ts(s):
    import datetime as _dt
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
               "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt.datetime.strptime(
                str(s).replace("/", "-"), fmt).timestamp()
        except ValueError:
            continue
    return None


def head_anchor(kg):
    a = _anchors(kg)
    return a[-1] if a else None
