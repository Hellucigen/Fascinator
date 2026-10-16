# -*- coding: utf-8 -*-
"""run_shadow_v31.py — v3.1 真实数据驱动的影子活动循环（全隔离）。

真实数据源（全部只读）：
  data/chat_log.json          用户真实发言/系统回复（真实知识缺口与失败案例）
  data/runtime_graph.json     真实认知产物（思考_/感知节点）
  logs/runtime.log            生产 SelfSearch 历史（重复执行去重）
写入：results/shadow_v31_ledger.json / shadow_v31_trace.json（隔离）。
零生产写入/零投递/零重启。生产代码零修改。
"""
import json
import os
import re
import sys
import time as _rt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, "E:/Project/FAS-Companion")

from graph_model import KnowledgeGraph, Node, Edge
sys.path.insert(0, os.path.join(HERE, "..", "autonomy_loop_v1"))   # v1 复用
from autonomy_loop import Toolbox, S_DONE, S_FAILED
from activity_v3 import ActivityLoopV3
from cognitive_product import CognitiveProduct, products_from_graph_state
from goal_bridge import GoalBridge
from social_decider import SocialContext, decide_share
from cognitive_product import products_from_graph_state as pfg
from cognitive_product import CognitiveProduct as CP

COMPANION = "E:/Project/FAS-Companion"
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
TRACE_PATH = os.path.join(RESULTS, "shadow_v31_trace.json")
LEDGER_PATH = os.path.join(RESULTS, "shadow_v31_ledger.json")
NOW = _rt.time()


# ── 真实数据适配器（全部只读） ────────────────────────────────
def real_chat_context():
    """chat_log → 真实社交上下文 + 真实知识缺口。"""
    d = json.load(open(os.path.join(COMPANION, "data", "chat_log.json"),
                       encoding="utf-8"))
    user_turns = [x for x in d if x.get("proactive") in (False, "False", None)]
    proac = [x for x in d if x.get("proactive") in (True, "True")]
    import datetime
    def ts(s):
        return _rt.mktime(datetime.datetime.fromisoformat(
            s).timetuple()) if s else 0.0
    last_user = user_turns[-1] if user_turns else None
    ctx = {
        "user_recent_ts": ts(last_user.get("time")) if last_user else 0.0,
        "user_recent_text": str(last_user.get("user_input") or "")[:80]
        if last_user else "",
        "conversation_open": bool(last_user and
                                  NOW - ts(last_user.get("time")) < 1800),
        "recent_expressed": [str(x.get("system_response") or "")[:60]
                             for x in proac[-5:]],
        "recent_express_ts": ts(proac[-1].get("time")) if proac else 0.0,
        "user_unknown_concepts": [],     # 用户真实说过的未知概念（知识缺口）
        "failed_searches": [],           # 系统真实检索失败案例
    }
    for x in user_turns:
        for m in re.findall(r"「([^」]{3,20})」", str(x.get("user_input") or "")):
            if m not in ctx["user_unknown_concepts"]:
                ctx["user_unknown_concepts"].append(m)
    # 真实检索失败：系统回复自述检索无用
    for x in d:
        resp = str(x.get("system_response") or "")
        if "没什么用" in resp or "字典条目" in resp:
            q = re.findall(r"「([^」]{3,20})」", str(x.get("user_input") or ""))
            ctx["failed_searches"].append({"concept": q[-1] if q else "",
                                           "evidence": resp[:80]})
    return ctx


def real_products_from_graph():
    g = json.load(open(os.path.join(COMPANION, "data",
                                    "runtime_graph.json"), encoding="utf-8"))
    return g["nodes"], [n for n in g["nodes"]
                        if str(n.get("id", "")).startswith("思考_")]


def production_selfsearch_queries():
    """生产已自发检索过的 query（影子循环重复执行去重）。"""
    log = open(os.path.join(COMPANION, "logs", "runtime.log"),
               encoding="utf-8", errors="replace").read()
    return set(re.findall(r"自发检索「([^」]+)」", log))


# ── 影子任务执行（真实工具） ──────────────────────────────────
def shadow_task(loop, goal, evidence_id, source, note=""):
    tid = f"shadow_{abs(hash(goal + str(note))) % 10**8:08x}"
    loop.ledger.tasks[tid] = {
        "id": tid, "goal": goal, "state": "proposed",
        "source": source, "evidence_id": evidence_id,
        "created": NOW, "select_reason": note or "real knowledge gap",
        "shadow": True}
    loop.select()
    t = loop.ledger.tasks[tid]
    loop.execute(t)
    v, why = loop.verify(t)
    loop.learn(t)
    return t, v, why


def main():
    trace = {"model": "mimo-v2.6-flash(仅生成，本轮决策层无 LLM)",
             "started": NOW, "stages": {}}
    # ── 阶段2：真实数据适配 ──
    ctx = real_chat_context()
    nodes, thoughts = real_products_from_graph()
    prod_searched = production_selfsearch_queries()
    trace["stages"]["真实数据适配"] = {
        "chat_log 条目": 12,
        "用户真实发言": len([x for x in real_chat_context()
                        ["recent_expressed"]] or []) and "见 recent",
        "真实知识缺口(用户口述未知概念)": ctx["user_unknown_concepts"],
        "真实检索失败案例": ctx["failed_searches"],
        "思考节点(全部内省)": len(thoughts),
        "生产已自发检索": sorted(prod_searched),
    }
    print("真实知识缺口:", ctx["user_unknown_concepts"])
    print("真实检索失败:", ctx["failed_searches"])
    print("生产已自发检索:", sorted(prod_searched))

    # ── 阶段3：影子任务（真实知识缺口 → 真实检索） ──
    kg = KnowledgeGraph()
    # 真实证据节点入隔离图（副本，标注来源）
    for concept in ctx["user_unknown_concepts"]:
        nid = f"UnknownConcept_{concept}"
        kg.add_node(Node(id=nid, weight=0.6,
                         extra_attrs={"type": "unknown",
                                      "source": "user_stated_2026-10-09"}))
    loop = ActivityLoopV3(kg, LEDGER_PATH,
                          Toolbox({"web_search": __import__(
                              "actions.web_search", fromlist=[
                                  "do_web_search"]).do_web_search}),
                          social_ctx=SocialContext(
                              user_recent_ts=ctx["user_recent_ts"],
                              user_recent_text=ctx["user_recent_text"],
                              conversation_open=ctx["conversation_open"],
                              recent_expressed=ctx["recent_expressed"],
                              recent_express_ts=ctx["recent_express_ts"],
                              now=NOW))
    bridge = GoalBridge(kg, self_graph_bridge_stub())
    _bridge_for_revise = bridge          # 同一实例：注册与修订共享 store
    task_results = []
    executed_queries = []
    # 去重：生产已自发检索的 + 影子已执行的 query 不重复
    for concept in ctx["user_unknown_concepts"]:
        goal = f"搞清楚「{concept}」是什么"
        if any(concept in q for q in prod_searched) or \
                any(concept in q for q in executed_queries):
            trace["stages"].setdefault("重复跳过", []).append(concept)
            continue
        t, v, why = shadow_task(loop, goal, f"UnknownConcept_{concept}",
                                "user_stated", note="real knowledge gap")
        # 目标注册进 bridge（修订语义要求目标先存在）
        from cognitive_product import CognitiveProduct as _CP
        bridge.from_product(_CP(
            type="open_question", text=goal,
            evidence_ids=[f"UnknownConcept_{concept}"], confidence=0.7))
        executed_queries.append((t.get("tool_calls") or [{}])[0]
                                .get("query", ""))
        task_results.append({"goal": goal, "verdict": v, "reason": why,
                             "learned": t.get("learned_id"),
                             "relevant": t.get("relevant_results") or []})
    trace["stages"]["影子任务"] = task_results
    for r in task_results:
        print(f"  影子任务: {r['goal'][:30]} → {r['verdict']} ({r['reason'][:40]})")

    # ── 阶段4-A：跨轮学习（第二轮读第一轮结果改变决策） ──
    round2_decisions = []
    for r in task_results:
        if r["verdict"] == "SUCCESS" and r["relevant"]:
            # 第一轮相关 → 第二轮基于发现细化（从 relevant 标题提炼后续问题）
            kw = r["relevant"][0].get("title", "")[:20]
            round2_decisions.append({
                "based_on": r["goal"], "round1_verdict": "SUCCESS",
                "decision": f"第一轮发现「{kw}」相关资料，目标收敛为该方向",
                "same_query_retried": False})
        elif r["verdict"] == "INCONCLUSIVE":
            round2_decisions.append({
                "based_on": r["goal"], "round1_verdict": "INCONCLUSIVE",
                "decision": "暂停探索（换查询策略需要新证据，不重复相同查询）",
                "same_query_retried": False})
    trace["stages"]["跨轮学习"] = round2_decisions

    # ── 阶段4-C：反证修订（真实工具结果作为反证） ──
    revisions = []
    for concept in ctx["user_unknown_concepts"][:2]:
        q = concept
        r = __import__("actions.web_search", fromlist=["do_web_search"]
                       ).do_web_search(q, top_n=3)
        blob = json.dumps(r, ensure_ascii=False)
        if concept not in blob and len(r) > 0:
            new_goal = f"确认「{concept}」是否为标准术语（检索未见该词）"
            ok = bridge.revise(f"搞清楚「{concept}」是什么", new_goal,
                               [f"web_search({q}) 结果不含该概念"],
                               "检索反证：结果中未出现该概念")
            revisions.append({"concept": concept, "revised": ok,
                              "new_goal": new_goal})
    trace["stages"]["反证修订"] = revisions
    for r in revisions:
        print("  反证修订:", r["concept"], "→", r["revised"], r["new_goal"][:40])

    # ── 阶段5：真实社交上下文的影子评估 ──
    social_evals = []
    eval_set = []
    # 真实产物 1：影子任务的学习结果（真实发现）
    for r in task_results:
        if r["verdict"] == "SUCCESS" and r["learned"]:
            eval_set.append(("影子学习: " + r["goal"][:30],
                             CP(type="social_material",
                                text=f"我自己查了「{r['goal']}」——找到相关资料了。",
                                evidence_ids=[r["learned"]], confidence=0.6)))
    # 历史案例回归：02:08 digest（生产原文，边界措辞后）
    eval_set.append(("历史02:08 digest(边界措辞)",
                     CP(type="observation",
                        text="用户工作区快照 — 最近笔记：日記；リーディングリスト；"
                             "Movie List；AI学習計画（以上只是清单快照，不代表"
                             "用户正在打开或操作它们）",
                        evidence_ids=["用户近况_1791655680"], confidence=0.5)))
    # 历史 S5 线索（有价值应表达）+ 历史 S7（低价值不表达）
    eval_set.append(("历史S5 线索",
                     CP(type="social_material",
                        text="对话里用户提到但没解释的'转码偏差'概念，"
                             "我刚查到了相关资料", evidence_ids=["s5"],
                        confidence=0.6)))
    for label, prod in eval_set:
        d = decide_share(prod, SocialContext(
            user_recent_ts=ctx["user_recent_ts"],
            user_recent_text=ctx["user_recent_text"],
            conversation_open=ctx["conversation_open"],
            recent_expressed=ctx["recent_expressed"],
            recent_express_ts=ctx["recent_express_ts"], now=NOW))
        social_evals.append({"case": label, "verdict": d.verdict,
                             "reason": d.reason, "novelty": round(d.novelty, 2)})
        print(f"  社交影子: {label[:28]} → {d.verdict} ({d.reason[:40]})")
    trace["stages"]["社交影子评估"] = social_evals

    trace["finished"] = NOW
    json.dump(trace, open(TRACE_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print("saved:", TRACE_PATH)


def self_graph_bridge_stub():
    """self_graph 语义的最小替身（修订只发生在隔离层）。"""
    class SG:
        store = []

        def set_goal(self, kg, desc, parent_goal=None):
            SG.store.append({"goal": desc, "parent": parent_goal})
            return desc

        def get_goals(self):
            return [{"goal": g["goal"]} for g in SG.store]

        def remove_goal(self, kg, gid):
            pass
    return SG()


if __name__ == "__main__":
    main()
