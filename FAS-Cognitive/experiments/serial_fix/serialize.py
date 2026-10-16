# serialize.py — 工作集序列化修复（针对 serialization ✗✗ 失败层）
# 三种序列化器（确定性、只读图/经历数据）：
#   serial_ids       现状复刻："- <node_id>"（cross_episode run_llm.py:79 同款）
#   serial_narrative 修复版：事件节点→"主 动作 客"句（action 读节点
#                    extra_attrs.action——表示修复：该属性与 G2 直连边的关系名
#                    同源，来自经历记录，非查询时注入）；时序由 后继 边给
#                    "此后"；负权边给 失败标记（本数据集无，规则预留）；
#                    实体直连边→"A -[关系]-> B"。
#   serial_flat      B2 参照：经历行按问题相似度取 top6（原 B2 用嵌入——
#                    此处为确定性近似，字符重叠，报告披露）。
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CE = os.path.join(HERE, "..", "cross_episode_recomb")


def load_episodes():
    return json.load(open(os.path.join(CE, "episodes.json"),
                          encoding="utf-8"))


def ep_action(episodes, eid):
    for ep in episodes:
        if ep["id"] == eid:
            return ep["action"]
    return None


def _label(nid):
    s = str(nid)
    return s.replace("事件:", "事件", 1) if s.startswith("事件:") else s


def serial_ids(top_nodes, edges, kg=None, episodes=None):
    return "\n".join("- " + str(n.id) for n in top_nodes)


def serial_narrative(top_nodes, edges, kg=None, episodes=None):
    """上下文口径 = Top-k 节点 + 其一跳邻接边（图上有、呈现上补全——
    与 B2 检索行同信息量；不读任何问题/答案数据）。"""
    episodes = episodes if episodes is not None else load_episodes()
    top_ids = {n.id for n in top_nodes}
    act = {n.id: float(n.activation or 0) for n in top_nodes}
    lines = []
    succ = {}   # 后继边：src(更晚) → [更早]
    for e in edges:
        if e.relation == "后继" and (e.src in top_ids or e.dst in top_ids):
            succ.setdefault(e.src, []).append(e.dst)
    ev = [n for n in top_nodes if str(n.id).startswith("事件:")]
    ev.sort(key=lambda n: -act[n.id])
    ev.sort(key=lambda n: (n.extra_attrs or {}).get("seq", 999))
    for n in ev:
        eid = str(n.id).replace("事件:", "", 1)
        ea = n.extra_attrs or {}
        subj = ea.get("subject")
        obj = ea.get("object")
        a = ea.get("action") or ep_action(episodes, eid)
        if subj is not None and obj is not None and a:
            extra = ""
            if succ.get(n.id):
                extra = "（此前：" + "、".join(_label(x)
                                              for x in succ[n.id]) + "）"
            lines.append(f"{_label(n.id)}：{_label(subj)} {a} "
                         f"{_label(obj)}{extra}")
        else:
            lines.append(f"{_label(n.id)}（上下文不完整：主体={subj} "
                         f"客体={obj} 动作={a}）")
    seen_pairs = set()
    for e in edges:
        if e.relation in ("主体", "客体", "后继"):
            continue
        if e.src in top_ids or e.dst in top_ids:
            pair = (e.src, e.relation, e.dst)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if float(e.weight) >= 0:
                lines.append(f"{_label(e.src)} -[{e.relation}]-> "
                             f"{_label(e.dst)}")
            else:
                lines.append(f"（失败证据）{_label(e.src)} -[{e.relation}]"
                             f"(-)]-> {_label(e.dst)}")
    seen = {n.id for n in ev}
    for n in top_nodes:                    # 剩余孤立实体（激活降序）
        if n.id not in seen and not str(n.id).startswith("事件:"):
            lines.append(f"{_label(n.id)}")
    return "\n".join(lines)


def serial_flat(question_text, episodes=None, k=6):
    """B2 参照：经历行按字符重叠相似度取 top-k（确定性近似）。"""
    episodes = episodes if episodes is not None else load_episodes()

    def sim(line):
        return sum(1 for ch in set(question_text) if ch in line)

    rows = ["%s %s %s" % (ep["subject"], ep["action"], ep["object"])
            for ep in episodes]
    rows.sort(key=lambda r: (-sim(r), r))
    return "\n".join("- " + r for r in rows[:k])


# ── 机制指标 ──────────────────────────────────────────────

def fact_completeness(context, question, episodes=None):
    """金色三元组能否从上下文文本重构：(n_ok, n_gold)。
    判定=同一行同时含 subject/action/object。"""
    episodes = episodes if episodes is not None else load_episodes()
    epmap = {ep["id"]: ep for ep in episodes}
    lines = context.splitlines()
    gold = [(epmap[e]["subject"], epmap[e]["action"], epmap[e]["object"])
            for e in question.get("gold_episodes", []) if e in epmap]
    ok = 0
    for subj, act, obj in gold:
        for ln in lines:
            if subj in ln and obj in ln and act in ln:
                ok += 1
                break
    return ok, len(gold)


def gold_visibility(top_nodes, question):
    top = {str(n.id) for n in top_nodes}
    want = set(question.get("gold_chain", [])) | \
        {"事件:" + e for e in question.get("gold_episodes", [])}
    return len(top & want), len(want)
