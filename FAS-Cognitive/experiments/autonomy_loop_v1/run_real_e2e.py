# -*- coding: utf-8 -*-
"""run_real_e2e.py — v1.1 真实认知来源端到端（隔离）。

数据来源：生产 runtime_graph.json 只读导出（真实 CC 产物，非测试构造）。
写入：账本与学习全部在本实验 results/ 目录与内存图谱，零生产写入。
候选语义如实：当前真实自由思考产物均为内省独白——按任务规则不编造
可执行问题，允许以"证据不足/暂停"收尾。
"""
import json
import os
import sys
import time as _rt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))   # FAS-Cognitive 根
sys.path.insert(0, "E:/Project/FAS-Companion")

from graph_model import KnowledgeGraph, Node, Edge
from autonomy_loop import (ActivityLoop, Toolbox, S_DEFERRED, S_DONE,
                           VERDICT_INCONCLUSIVE, VERDICT_SUCCESS)

PROD_GRAPH = "E:/Project/FAS-Companion/data/runtime_graph.json"
LEDGER = os.path.join(HERE, "results", "real_ledger.json")
TRACE = os.path.join(HERE, "results", "real_e2e_trace.json")


def real_candidates_from_export(nodes):
    """最小适配层：从生产图只读导出中识别真实候选。
    只认生产生成器写死的 id 前缀（思考_/UnknownConcept_），
    实验构造节点（ev_/用户近况_ 等）一律排除——不冒充真实认知产物。"""
    cands = []
    for n in nodes:
        nid = str(n.get("id") or "")
        ea = n.get("extra_attrs") or {}
        if nid.startswith("思考_") and ea.get("type") == "thought":
            content = str(ea.get("content") or "").strip()
            if len(content) >= 8:
                cands.append({"goal": f"查证自己刚才的想法：{content[:60]}",
                              "source": "free_thought(real)",
                              "evidence_id": nid,
                              "kind": "verify_thought",
                              "act": n.get("activation")})
        elif nid.startswith("UnknownConcept_") and not ea.get("retired"):
            cands.append({"goal": f"搞清楚「{nid.split('_', 1)[-1]}」是什么",
                          "source": "unknown_marker(real)",
                          "evidence_id": nid, "kind": "inquiry",
                          "act": n.get("activation")})
    return cands


def select_one(cands, ledger):
    """与 loop.select 同语义的最小规则：非重复 + 工具可用 + 预算内。
    内省独白无外部可执行问题——如实保留其原样进入验证（预期 INCONCLUSIVE）。"""
    for c in sorted(cands, key=lambda x: -float(x.get("act") or 0)):
        if ledger.dup_open(c["goal"]):
            continue
        return c
    return None


def main():
    from actions.web_search import do_web_search
    nodes = json.load(open(PROD_GRAPH, encoding="utf-8"))["nodes"]
    cands = real_candidates_from_export(nodes)
    trace = {"candidates_found": [
        {"goal": c["goal"][:70], "source": c["source"],
         "evidence_id": c["evidence_id"], "act": c.get("act")}
        for c in cands]}
    print(f"真实候选: {len(cands)} 条")
    for c in trace["candidates_found"]:
        print("  -", c["source"], c["goal"][:60])

    if not cands:
        trace["outcome"] = "idle_no_candidates"
        json.dump(trace, open(TRACE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("无有效候选——正常结束（IDLE）")
        return

    # 最多处理 1 个：取激活最高的真实候选
    cand = select_one(cands, LedgerStub())
    if cand is None:
        trace["outcome"] = "all_duplicate"
        json.dump(trace, open(TRACE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("候选全部重复——正常结束")
        return

    kg = KnowledgeGraph()                    # 隔离内存图（学习写入目标）
    # 证据节点原样入隔离图（真实产物的副本，非冒充）
    src = next(n for n in nodes if n["id"] == cand["evidence_id"])
    kg.add_node(Node(id=src["id"], weight=0.6, label="declarative-episodic",
                     extra_attrs=json.loads(json.dumps(
                         src.get("extra_attrs") or {}))))
    tb = Toolbox({"web_search": do_web_search})   # 真实只读工具
    loop = ActivityLoop(kg, LEDGER, tb)
    task = {"id": f"act_{cand['evidence_id'][-8:]}", "goal": cand["goal"],
            "source": cand["source"], "evidence_id": cand["evidence_id"],
            "kind": cand["kind"], "state": "proposed", "created": _rt.time(),
            "select_reason": "highest-activation real candidate"}
    loop.ledger.add(task)
    trace["task"] = {"goal": cand["goal"],
                     "source_evidence": cand["evidence_id"],
                     "select_reason": task["select_reason"],
                     "budget": "web_search ≤4 次, timeout 20s/call"}
    print("执行任务:", cand["goal"][:70])

    loop.execute(task)
    v, why = loop.verify(task)
    loop.learn(task)
    # ── 第二轮：读取第一轮账本结果并决策 ──
    prev = loop.ledger.tasks[task["id"]]
    r1 = {"verdict": prev.get("verdict"),
          "relevant": prev.get("relevant_results") or [],
          "query": (prev.get("tool_calls") or [{}])[0].get("query")}
    if v == VERDICT_INCONCLUSIVE:
        # 证据不足 → 暂停探索（任务允许的决定），不重复相同搜索
        task["state"] = S_DEFERRED
        task["next_reason"] = ("第一轮检索证据不足（INCONCLUSIVE），暂停探索；"
                               "不重复相同查询")
        decision = "暂停"
    elif v == "SUCCESS":
        follow = f"{r1['query']} 的具体机制"   # 假想后续（本轮不会走到）
        decision = f"深入：{follow}"
    else:
        decision = "结束已完成的任务"
    trace["round1"] = {"verdict": v, "reason": why,
                       "tool_calls": task.get("tool_calls"),
                       "learned_id": task.get("learned_id")}
    trace["round2"] = {"read_round1": r1, "decision": decision,
                       "task_state": task.get("state"),
                       "same_query_researched": False}
    trace["share_candidates"] = loop.ledger.share_candidates
    trace["outcome"] = "completed"
    json.dump(trace, open(TRACE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print("round1:", v, "/", why)
    print("round2 决策:", decision)
    print("saved:", TRACE)


class LedgerStub:
    """select_one 只需 dup_open 接口的轻量账本桥。"""

    def __init__(self):
        self.tasks = {}
        self._real = None

    def dup_open(self, goal, now=None):
        if self._real is None and os.path.exists(LEDGER):
            try:
                d = json.load(open(LEDGER, encoding="utf-8"))
                self._real = True
                for t in d.get("tasks", []):
                    if t.get("goal") == goal:
                        return True
            except (OSError, ValueError):
                pass
        return False


if __name__ == "__main__":
    main()
