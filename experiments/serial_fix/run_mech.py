# run_mech.py — serial_fix 机制层实验（零 LLM、确定性）
# 条件（同一激活路径，仅呈现/表示不同）：
#   G3-ids        G3 图 + ids 序列化（现状复刻，预期复现 serialization ✗✗）
#   G3-narr-nofix G3 图 + 叙事序列化，但事件节点不带 action（表示未修复
#                 → 句子残缺，证明"只修呈现不修表示"不够）
#   G3-narr-fix   G3 图 + 事件节点补 action 属性（表示修复：属性与 G2 直连
#                 边关系名同源，来自经历记录）+ 叙事序列化
#   G2-narr       G2 共享实体直连图（动作在边关系名上）+ 叙事序列化（参照）
# 指标：gold_visibility（金链实体+金事件进 Top-k）、
#       fact_completeness（金三元组可从上下文重构）、chars。
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge       # noqa: E402
from diffusion_engine import DiffusionEngine             # noqa: E402
import serialize as S                                    # noqa: E402

CE = os.path.join(HERE, "..", "cross_episode_recomb")
CFG = json.load(open(os.path.join(CE, "experiment_config.json"),
                     encoding="utf-8"))
EPISODES = json.load(open(os.path.join(CE, "episodes.json"),
                          encoding="utf-8"))
QUESTIONS = CFG["questions"]
OUT = os.path.join(HERE, "artifacts")
os.makedirs(OUT, exist_ok=True)


def build_kg(gname, rep_fix=False):
    g = CFG["graphs"][gname]
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    for n in g["nodes"]:
        kg.add_node(Node(id=n["id"], weight=1.0, label=n["label"],
                         graph_space=n.get("graph_space", "semantic")))
    for e in g["edges"]:
        kg.add_edge(Edge(src=e["src"], dst=e["dst"], relation=e["relation"],
                         weight=e["weight"],
                         relation_category=e["relation_category"]))
    if rep_fix:
        # 表示修复：事件节点属性化 {action, subject, object, seq}——信息与
        # G2 直连边同源（经历记录），绕开归一词表对结构角色词的吸收
        # （主体/客体/后继 入引擎即被归一为 关联，实测）。
        epmap = {ep["id"]: ep for ep in EPISODES}
        for nid, n in kg.nodes.items():
            t = str(nid)
            if t.startswith("事件:") and t[3:] in epmap:
                ep = epmap[t[3:]]
                n.extra_attrs.update({"action": ep["action"],
                                      "subject": ep["subject"],
                                      "object": ep["object"],
                                      "seq": int(t[3:][1:])})
    eng = DiffusionEngine(kg, {"beta_spread": 1.0, "activation_epsilon": 1e-4,
                               "min_spread_threshold": 0.01,
                               "activation_max": 5.0})
    eng.name_to_node = dict(kg.nodes)
    return kg, eng


def run():
    rows = []
    for q in QUESTIONS:
        for regime in ("R1", "R2"):
            for gname, rep_fix, ser in (
                    ("eventframe", False, "ids"),
                    ("eventframe", False, "narr"),
                    ("eventframe", True, "narr"),
                    ("shared", False, "narr")):
                kg, eng = build_kg(gname, rep_fix=rep_fix)
                eng.activate_from_inputs(list(q["seeds"]), [])
                if regime == "R2" and gname == "eventframe":
                    # 情节新近性：全部 事件 节点均匀点火（与问题无关、
                    # 无泄漏——模拟"刚经历过、都还活跃"的情景记忆）
                    ev = [nid for nid in kg.nodes
                          if str(nid).startswith("事件:")]
                    eng.activate_from_inputs(ev, [])
                r = eng.diffuse_round()
                for k in (8, 16):
                    top, edges = eng.get_topk(k=k)
                    if ser == "ids":
                        ctx = S.serial_ids(top, edges)
                    else:
                        ctx = S.serial_narrative(top, edges, kg=kg,
                                                 episodes=EPISODES)
                    v_ok, v_n = S.gold_visibility(top, q)
                    f_ok, f_n = S.fact_completeness(ctx, q, EPISODES)
                    rows.append({
                        "qid": q["id"],
                        "cond": f"{regime}-{gname}-{ser}"
                                + ("+repfix" if rep_fix else ""),
                        "k": k, "vis": v_ok, "vis_n": v_n,
                        "facts": f_ok, "facts_n": f_n,
                        "chars": len(ctx),
                        "frontier": len(eng._active_nodes)})
    with open(os.path.join(OUT, "mech_serial.json"), "w",
              encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    agg = {}
    for r in rows:
        key = (r["cond"], r["k"])
        a = agg.setdefault(key, {"vis": 0, "vis_n": 0, "facts": 0,
                                 "facts_n": 0, "chars": 0, "n": 0})
        for m in ("vis", "vis_n", "facts", "facts_n", "chars"):
            a[m] += r[m]
        a["n"] += 1
    print(f"{'cond':<26}{'k':>3} {'vis@k':>7} {'facts@k':>8} {'chars':>7}")
    for (cond, k), a in sorted(agg.items()):
        n = a["n"]
        print(f"{cond:<26}{k:>3} {a['vis']/max(1,a['vis_n']):>6.1%} "
              f"{a['facts']/max(1,a['facts_n']):>7.1%} {a['chars']//n:>7}")
    print("out:", OUT)


if __name__ == "__main__":
    run()
