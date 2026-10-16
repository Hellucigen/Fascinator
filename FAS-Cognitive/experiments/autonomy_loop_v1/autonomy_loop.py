# -*- coding: utf-8 -*-
"""autonomy_loop.py — HARU 自主活动循环 v1（隔离实验实现，非生产部署）。

状态机（语义对应任务定义）：
  IDLE → PROPOSED → SELECTED → RUNNING → VERIFYING → LEARNING
      → DONE | FAILED | DEFERRED（DEFERRED 可回 SELECTED）

设计原则（对照审计结论）：
  - 复用：候选来源只用审计确认的现有产物（活未知标记 / 自由思考节点 /
    挂账好奇问题）；工具只用审计确认安全的 actions.web_search（只读检索）；
    学习写入走 KnowledgeGraph 既有接口（隔离实例，非生产图）。
  - 任务选择 = 最小可解释规则（证据在场/非重复/工具可用/预算内），
    显著性与 LLM 自信不单独决定入选；落选理由全部记录。
  - 验证 = 只看工具实际返回（相关性检查），不信任生成文本。
  - 分享候选 ≠ 发送：SUCCESS 且有新信息才登记 share_candidate，由现有
    表达机制另行评估（本 v1 只产生候选记录）。
  - 账本 JSON 落盘，支持崩溃恢复：RUNNING 任务重启后先 VERIFY（工具结果
    已在账本，无外部副作用，不重放）。
"""
import json
import os
import re
import time
import uuid

# ── 状态 ──────────────────────────────────────────────────────
S_IDLE, S_PROPOSED, S_SELECTED, S_RUNNING, S_VERIFYING, S_LEARNING, \
    S_DONE, S_DEFERRED, S_FAILED = (
        "idle", "proposed", "selected", "running", "verifying",
        "learning", "done", "deferred", "failed")

VERDICT_SUCCESS, VERDICT_FAILED, VERDICT_INCONCLUSIVE = \
    "SUCCESS", "FAILED", "INCONCLUSIVE"

MAX_TOOL_CALLS = 4          # 单任务工具调用预算
TOOL_TIMEOUT_S = 20         # 单次工具超时（web_search 内部有自身超时）
MAX_RETRY = 1               # 失败任务原地重试上限
DEFER_TTL_S = 6 * 3600      # DEFERRED 最长等待，超时转 FAILED(过期)
THOUGHT_FRESH_S = 24 * 3600  # 自由思考候选的新鲜窗口


# ── 工具白名单 ────────────────────────────────────────────────
class Toolbox:
    """工具白名单：只有登记在案的调用可用，其余一律拒绝。"""

    def __init__(self, tools=None):
        self.tools = dict(tools or {})

    def has(self, name):
        return name in self.tools

    def call(self, name, *a, **k):
        if name not in self.tools:
            return {"error": "tool_not_allowed", "tool": name}
        try:
            return {"ok": True, "result": self.tools[name](*a, **k)}
        except Exception as e:                   # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def real_toolbox():
    """生产确认安全的只读工具（审计：actions/web_search.py:84 do_web_search）。"""
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from actions.web_search import do_web_search
    return Toolbox({"web_search": do_web_search})


# ── 候选来源（全部来自审计确认的真实产物） ──────────────────────
def candidates_from_graph(kg, now=None):
    """从隔离图谱收集候选活动。来源（各有证据节点支撑）：
      ① 活未知标记（好奇引擎维护，graph_model.is_live_unknown_id）
      ② 新鲜自由思考节点（self_graph.generate_thought 产物：
         label=declarative-episodic, extra_attrs.type=thought, content=独白）
    返回 [{goal, source, evidence_id}]；无证据 → 空（IDLE 合法）。"""
    from graph_model import is_live_unknown_id
    now = now or time.time()
    out = []
    with kg._lock:
        for nid, n in kg.nodes.items():
            ea = n.extra_attrs or {}
            try:
                if is_live_unknown_id(kg, nid):
                    out.append({"goal": f"搞清楚「{nid.split('_', 1)[-1]}」是什么",
                                "source": "unknown_marker",
                                "evidence_id": nid,
                                "kind": "inquiry"})
            except Exception:                    # noqa: BLE001
                pass
            if (ea.get("type") == "thought"
                    and nid.startswith("思考_")
                    and now - float(ea.get("born_ts") or now) < THOUGHT_FRESH_S):
                content = str(ea.get("content") or "").strip()
                if len(content) >= 8:
                    out.append({"goal": f"查证自己刚才的想法：{content[:60]}",
                                "source": "free_thought",
                                "evidence_id": nid,
                                "kind": "verify_thought"})
    return out


def clean_query(goal_text):
    """目标文本 → 检索词（确定性规则，复用自发检索的清洗思路）。"""
    q = re.sub(r"搞清楚「|」是什么|查证自己刚才的想法：|研究了|想明白", "", goal_text)
    q = re.sub(r"[？?。！!，,、\s]+", " ", q).strip()
    return q[:30]


# ── 账本 ──────────────────────────────────────────────────────
class Ledger:
    def __init__(self, path):
        self.path = path
        self.tasks = {}
        self.share_candidates = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                d = json.load(open(self.path, encoding="utf-8"))
                self.tasks = {t["id"]: t for t in d.get("tasks", [])}
                self.share_candidates = d.get("share_candidates", [])
            except (OSError, ValueError, KeyError):
                self.tasks, self.share_candidates = {}, []   # 损坏→空账本重建

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump({"tasks": list(self.tasks.values()),
                   "share_candidates": self.share_candidates},
                  open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)

    def add(self, task):
        self.tasks[task["id"]] = task
        self.save()

    DEDUP_DONE_TTL_S = 24 * 3600   # 同目标完成后 24h 内视为重复，不重做

    def dup_open(self, goal, now=None):
        """重复创建保护：未完成任务一律重复；已完成任务在 TTL 内也算
        重复（同证据短窗口内重做没有新价值，2026-10-11 S3 场景）。"""
        now = now if now is not None else time.time()
        for t in self.tasks.values():
            if t["goal"] != goal:
                continue
            if t["state"] not in (S_DONE, S_FAILED):
                return True
            if now - float(t.get("created") or 0) < self.DEDUP_DONE_TTL_S:
                return True
        return False

    def dup_learning(self, goal, verdict):
        """同目标同结论的学习记录已存在 → 不重复写。"""
        return any(t["goal"] == goal and t.get("verdict") == verdict
                   and t["state"] == S_DONE for t in self.tasks.values())


# ── 循环本体 ──────────────────────────────────────────────────
class ActivityLoop:
    def __init__(self, kg, ledger_path, toolbox, now=None, defer_ttl=DEFER_TTL_S):
        self.kg = kg                       # 隔离实验图谱（非生产）
        self.tools = toolbox
        self.ledger = Ledger(ledger_path)
        self.defer_ttl = defer_ttl
        self._now = now or time.time
        self.log = []                      # 全程事件流水（可审计）

    def _t(self):
        return self._now()

    def _ev(self, task_id, event, detail=""):
        self.log.append({"t": round(self._t(), 1), "task": task_id,
                         "event": event, "detail": str(detail)[:160]})

    # ── ① 提议 ──
    def propose(self):
        cands = candidates_from_graph(self.kg, self._t())
        fresh = []
        for c in cands:
            if self.ledger.dup_open(c["goal"]):
                self._ev("-", "propose_skip_duplicate", c["goal"])
                continue
            c["id"] = f"act_{uuid.uuid4().hex[:8]}"
            c["state"] = S_PROPOSED
            c["created"] = self._t()
            c["select_reason"] = ""
            self.ledger.add(c)
            fresh.append(c)
            self._ev(c["id"], "proposed", c["goal"])
        return fresh

    # ── ② 选择（最小可解释规则；落选理由记录） ──
    def select(self):
        chosen = []
        for t in [t for t in self.ledger.tasks.values()
                  if t["state"] == S_PROPOSED]:
            reasons = []
            if not self.tools.has("web_search"):
                reasons.append("tool_unavailable")
            if len(t["goal"]) < 6:
                reasons.append("goal_too_vague")
            if t["source"] == "free_thought" and "查证" not in t["goal"]:
                reasons.append("thought_not_verifiable")
            if reasons:
                t["state"] = S_DEFERRED
                t["select_reason"] = ";".join(reasons)
                self._ev(t["id"], "select_reject", t["select_reason"])
            else:
                t["state"] = S_SELECTED
                t["select_reason"] = "evidence_backed+tool_available+not_duplicate"
                chosen.append(t)
                self._ev(t["id"], "selected", t["goal"])
        self.ledger.save()
        return chosen

    # ── ③ 执行（预算内工具调用） ──
    def execute(self, task):
        task["state"] = S_RUNNING
        task["started"] = self._t()
        task["tool_calls"] = task.get("tool_calls") or []
        self.ledger.save()
        q = clean_query(task["goal"])
        calls = len(task["tool_calls"])
        if calls >= MAX_TOOL_CALLS:
            task["state"] = S_VERIFYING
            task["verify_input"] = {"note": "budget_exhausted"}
            self.ledger.save()
            return
        r = self.tools.call("web_search", q, top_n=5) if q else \
            {"ok": False, "error": "empty_query"}
        task["tool_calls"].append({"tool": "web_search", "query": q,
                                   "t": self._t(), **{k: r.get(k) for k in
                                                       ("ok", "error")}})
        self._ev(task["id"], "tool_call", f"web_search({q!r}) ok={r.get('ok')}")
        task["raw_results"] = (r.get("result") or []) if r.get("ok") else []
        task["tool_error"] = r.get("error") if not r.get("ok") else None
        task["state"] = S_VERIFYING
        self.ledger.save()

    # ── ④ 验证（只信工具结果） ──
    def verify(self, task):
        task["state"] = S_VERIFYING
        if task.get("tool_error"):
            verdict, why = VERDICT_FAILED, f"tool_error:{task['tool_error']}"
        else:
            res = task.get("raw_results") or []
            qwords = [w for w in re.split(r"\s+", clean_query(task["goal"]))
                      if len(w) >= 2]
            relevant = [r for r in res
                        if any(w in (r.get("title", "") + r.get("snippet", ""))
                               for w in qwords[:2] or [""])]
            if not res:
                verdict, why = VERDICT_INCONCLUSIVE, "no_results"
            elif relevant:
                verdict, why = VERDICT_SUCCESS, \
                    f"{len(relevant)}/{len(res)} 条结果与目标相关"
                task["relevant_results"] = [
                    {"title": r.get("title", "")[:60],
                     "snippet": r.get("snippet", "")[:100]}
                    for r in relevant[:3]]
            else:
                verdict, why = VERDICT_INCONCLUSIVE, "results_not_relevant"
        task["verdict"] = verdict
        task["verdict_reason"] = why
        task["state"] = S_LEARNING
        self._ev(task["id"], "verified", f"{verdict}/{why}")
        self.ledger.save()
        return verdict, why

    # ── ⑤ 学习（证据制写入隔离图谱） ──
    def learn(self, task):
        from graph_model import Node, Edge
        verdict = task.get("verdict")
        if self.ledger.dup_learning(task["goal"], verdict):
            self._ev(task["id"], "learn_skip_duplicate", "")
            task["state"] = S_DONE
            self.ledger.save()
            return
        nid = f"自主活动_{int(self._t())}"
        with self.kg._lock:
            self.kg.add_node(Node(
                id=nid, weight=0.6, label="declarative-episodic",
                graph_space="episodic",
                extra_attrs={"type": "autonomous_activity",
                             "goal": task["goal"], "verdict": verdict,
                             "evidence": task.get("relevant_results") or [],
                             "source": task["source"],
                             "reason": task.get("verdict_reason")}))
            ev_id = task.get("evidence_id")
            if self.kg.get_node(ev_id):
                self.kg.add_edge(Edge(src=nid, dst=ev_id, relation="基于",
                                      weight=0.7,
                                      relation_category="cognitive_relation"))
        task["learned_id"] = nid
        task["state"] = S_DONE
        self._ev(task["id"], "learned", nid)
        self.ledger.save()

    # ── ⑥ 结束决策（含分享候选，不发送） ──
    def decide_next(self, task):
        if task.get("verdict") == VERDICT_SUCCESS and task.get("relevant_results"):
            if not any(c["goal"] == task["goal"]
                       for c in self.ledger.share_candidates):
                self.ledger.share_candidates.append({
                    "goal": task["goal"], "ci": task["id"],
                    "evidence": task.get("relevant_results", [])[:2],
                    "t": self._t(),
                    "note": "分享候选——交由现有表达机制评估，不直接发送"})
                self._ev(task["id"], "share_candidate", "registered")
        self.ledger.save()

    # ── 恢复（崩溃/重启） ──
    def recover(self):
        for t in self.ledger.tasks.values():
            if t["state"] in (S_RUNNING, S_VERIFYING):
                # 工具调用结果已在账本：无外部副作用，直接进入验证
                t["state"] = S_VERIFYING
                self._ev(t["id"], "recover", "resumed_at_verify")
            elif t["state"] == S_DEFERRED and \
                    self._t() - float(t.get("created") or 0) > self.defer_ttl:
                t["state"] = S_FAILED
                t["verdict_reason"] = "defer_expired"
                self._ev(t["id"], "defer_expired", "")
        self.ledger.save()

    # ── 单步驱动 ──
    def step(self):
        """推进一圈：提议→选择→执行→验证→学习→结束决策。返回处置摘要。"""
        out = {"proposed": 0, "selected": 0, "ran": 0, "done": 0}
        for t in self.propose():
            out["proposed"] += 1
        for t in self.select():
            out["selected"] += 1
            self.execute(t)
            out["ran"] += 1
            v, why = self.verify(t)
            self.learn(t)
            self.decide_next(t)
            out["done"] += 1
        # DEFER 过期巡检
        self.recover()
        return out
