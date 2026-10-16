# -*- coding: utf-8 -*-
"""living_loop.py — HARU 自主生活循环（v3.3 最小完整闭环，隔离实现）。

职责（对应架构设计 A-D/F/G）：
  协调器  tick() 决定本轮活动状态（探索/反思/社交/休眠/恢复）
  活动管理  Activity 账本：跨重启的长活动记录（进展/已试方法/失败/下一步）
  探索器  网络搜索 + 网页读取（只读、限长、来源记录；网页内容=不可信输入）
  经历记录  Experience：观察/推断/假设分开，证据带来源
  社交  活动完成 → SocialDecider 决定是否值得分享（不直接发送）

预算与边界：
  每 tick 网络调用 ≤ per_tick_web_budget；每活动 ≤ max_web_calls
  网页读取上限 4KB、剥标签、标记 untrusted；同 query 不重试
  零生产写入：账本/学习全部在实验目录
"""
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

from social_decider import SocialContext, decide_share

# 状态
A_CANDIDATE = "candidate"
A_ACTIVE = "active"
A_WAITING = "waiting"
A_PAUSED = "paused"
A_DONE = "done"
A_ABANDONED = "abandoned"

DEFAULT_BUDGET = {
    "per_tick_web_calls": 2,
    "max_web_calls_per_activity": 6,
    "tool_timeout_s": 12,
    "tick_interval_s": 600,          # 生活循环节拍（独立于认知脉冲）
    "max_activities_open": 3,
}


class Experience:
    """一条经历：观察/推断/假设分开，证据带来源。"""

    def __init__(self, kind, content, source_refs, ts,
                 epistemic="observation", activity_id=None):
        assert kind in ("observation", "inference", "hypothesis", "failure")
        self.kind = kind                  # observation=实际观察到的
        self.content = content
        self.source_refs = source_refs    # url/节点 id/工具调用号
        self.ts = ts
        self.epistemic = epistemic        # 与 kind 冗余校验
        self.activity_id = activity_id

    def to_dict(self):
        return self.__dict__.copy()


class Activity:
    def __init__(self, aid, topic, source_product, ts, budget):
        self.id = aid
        self.topic = topic
        self.source_product = source_product
        self.state = A_ACTIVE
        self.created = ts
        self.updated = ts
        self.progress = []                # [{ts, method, query/url, verdict, note}]
        self.methods_tried = []           # 已试过的查询/URL（重复控制）
        self.known_failures = []
        self.evidence = []                # 观察到的来源引用（url 等）
        self.findings = []                # 验证过的发现（可进学习/分享）
        self.web_calls = 0
        self.budget = budget
        self.next_candidates = []
        self.end_reason = None

    def to_dict(self):
        return self.__dict__.copy()


class ActivityLedger:
    def __init__(self, path):
        self.path = path
        self.activities = {}
        self.experiences = []
        self.share_candidates = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                d = json.load(open(self.path, encoding="utf-8"))
                self.activities = {a["id"]: a for a in d.get("activities", [])}
                self.experiences = d.get("experiences", [])
                self.share_candidates = d.get("share_candidates", [])
            except (OSError, ValueError, KeyError):
                self.activities, self.experiences = {}, []
                self.share_candidates = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump({"activities": [a for a in self.activities.values()],
                   "experiences": self.experiences,
                   "share_candidates": self.share_candidates},
                  open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)


# ── 探索器（网页=不可信输入） ─────────────────────────────────
UA = "Mozilla/5.0 (compatible; HARU-living/0.1; read-only research)"


def web_search_fn():
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from actions.web_search import do_web_search
    return do_web_search


def read_page(url, max_bytes=4096, timeout=12):
    """只读网页：限长、剥标签、标记 untrusted。返回 {ok, text, source}。"""
    try:
        safe = urllib.parse.quote(url, safe=":/?&=%+#")
        req = urllib.request.Request(safe, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes).decode("utf-8", "ignore")
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        text = re.sub(r"\s+", " ", text).strip()
        return {"ok": True, "text": text[:1200], "source": url,
                "untrusted": True}
    except Exception as e:                        # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "source": url, "untrusted": True}


def query_rewrite(query, attempt):
    """失败驱动的查询改写策略（确定性序列，至少 4 档）：
    原样 → 去前缀修饰 → 末段+是什么 → 首二字词根。"""
    strategies = [
        query,
        _split_compound(query),
        (_split_compound(query)[-3:] + " 是什么"),
        _root_word(query),
    ]
    # 去重保序：相同策略跳过（由调用方 methods_tried 兜底）
    seen, out = set(), []
    for s in strategies:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    idx = min(attempt, len(out) - 1)
    return out[idx]


def _split_compound(q):
    """复合术语拆分：去掉前缀修饰，保留核心词（如 超对称规范反常→规范反常）。"""
    for w in ("超对称", "拓扑", "量子", "冯诺依曼"):
        if q.startswith(w) and len(q) > len(w) + 1:
            return q[len(w):]
    return q


def _root_word(q):
    return q[:2] if len(q) > 2 else q


# ── 生活循环协调器 ────────────────────────────────────────────
class LivingLoop:
    def __init__(self, ledger_path, search_fn=None, products=None,
                 social_ctx=None, budget=None, now=None):
        self.ledger = ActivityLedger(ledger_path)
        self.search = search_fn or web_search_fn()
        self.products = products or []     # 本轮可用认知产物（v3.2 生成器输出）
        self._now = now or time.time
        self.social_ctx = social_ctx or SocialContext(now=self._now())
        self.budget = {**DEFAULT_BUDGET, **(budget or {})}
        self.log = []
        self._tick_web_used = 0

    def _t(self):
        return self._now()

    def _ev(self, event, detail="", aid=None):
        self.log.append({"t": round(self._t(), 1), "event": event,
                         "aid": aid, "detail": str(detail)[:160]})

    # ── 活动管理 ──
    def open_activity(self, topic, source_product):
        # max_activities_open 上限
        open_n = sum(1 for a in self.ledger.activities.values()
                     if a["state"] in (A_ACTIVE, A_WAITING))
        if open_n >= self.budget["max_activities_open"]:
            self._ev("activity_rejected", f"open_activities_full({open_n})")
            return None
        # 同主题去重
        for a in self.ledger.activities.values():
            if a["topic"] == topic and a["state"] != A_ABANDONED:
                self._ev("activity_rejected", f"duplicate:{topic[:30]}")
                return None
        aid = f"life_{int(self._t())}"
        a = Activity(aid, topic, source_product, self._t(),
                     self.budget["max_web_calls_per_activity"])
        self.ledger.activities[aid] = a.to_dict()
        self._ev("activity_opened", topic, aid)
        self.ledger.save()
        return aid

    def _activity(self, aid):
        return self.ledger.activities.get(aid)

    def _save_activity(self, a):
        self.ledger.activities[a["id"]] = a        # a 即账本内 dict 引用
        self.ledger.save()

    # ── 探索一步（含预算/改写/不可信处理） ──
    def explore_step(self, aid):
        a = self._activity(aid)
        if a is None or a["state"] != A_ACTIVE:
            return None
        if a["web_calls"] >= a["budget"]:
            a["state"] = A_WAITING
            a["end_reason"] = "activity_web_budget_exhausted"
            self._ev("budget_exhausted", aid)
            self._save_activity(a)
            return None
        if self._tick_web_used >= self.budget["per_tick_web_calls"]:
            self._ev("tick_budget_pause", aid)
            return None
        # 查询改写：失败驱动的策略序列
        attempt = len(a["methods_tried"])
        q = query_rewrite(a["topic"], attempt)
        if q in a["methods_tried"]:
            # 全部策略已试过且无有效结果 → 结束活动
            a["state"] = A_PAUSED
            a["end_reason"] = "all_query_strategies_exhausted"
            self._ev("strategies_exhausted", aid)
            self._save_activity(a)
            return None
        a["methods_tried"].append(q)
        a["web_calls"] += 1
        self._tick_web_used += 1
        # 真实搜索（只读）
        try:
            results = self.search(q, top_n=4)
        except Exception as e:                    # noqa: BLE001
            results = []
            a["known_failures"].append(f"search_error:{e}")
        obs = Experience(
            kind="observation",
            content=f"搜索「{q}」返回 {len(results)} 条结果",
            source_refs=[f"web_search:{q}"], ts=self._t(),
            epistemic="observation", activity_id=aid)
        self.ledger.experiences.append(obs.to_dict())
        a["progress"].append({"t": self._t(), "method": "search",
                              "query": q, "results": len(results)})
        # 相关性判断：结果标题/摘要含主题核心词（≥2 字词根）
        core = re.sub(r"\s+", "", a["topic"])[:4]
        relevant = [r for r in results
                    if core[:2] in (r.get("title", "") + r.get("snippet", ""))
                    or any(w in (r.get("title", "") + r.get("snippet", ""))
                           for w in q.split() if len(w) >= 2)]
        if relevant:
            # 读取第一条相关网页（只读、限长、untrusted 标记）
            url = relevant[0].get("url", "")
            page = {}
            if url:
                page = read_page(url)
                self._tick_web_used += 1
                a["web_calls"] += 1
            finding = {
                "query": q,
                "evidence": [{"title": r.get("title", "")[:60],
                              "snippet": r.get("snippet", "")[:100],
                              "url": r.get("url", "")[:120]}
                             for r in relevant[:2]],
                "page_read": page if page.get("ok") else None,
            }
            a["findings"].append(finding)
            a["evidence"].extend([f["url"] for f in finding["evidence"]])
            self.ledger.experiences.append(Experience(
                kind="observation",
                content=f"活动「{a['topic'][:30]}」找到相关资料："
                        f"{finding['evidence'][0]['title'][:50]}",
                source_refs=[f["url"] for f in finding["evidence"]],
                ts=self._t(), activity_id=aid).to_dict())
            a["state"] = A_DONE
            a["end_reason"] = "found_relevant_evidence"
            self._ev("found", f"{len(relevant)} 条相关", aid)
            self._save_activity(a)
            return "found"
        # 无相关 → 记录失败，下一拍改写查询
        a["known_failures"].append(f"query「{q}」结果不相关")
        self.ledger.experiences.append(Experience(
            kind="failure",
            content=f"查询「{q}」结果不相关",
            source_refs=[f"web_search:{q}"], ts=self._t(),
            epistemic="observation", activity_id=aid).to_dict())
        self._save_activity(a)
        self._ev("query_irrelevant", q, aid)
        return "irrelevant"

    # ── 社交（活动完成 → SocialDecider） ──
    def social_step(self):
        decided = []
        for a in self.ledger.activities.values():
            if a["state"] == A_DONE and a["findings"] and \
                    not a.get("share_decided"):
                prod = _ShareProd(a)
                d = decide_share(prod, self.social_ctx)
                a["share_decided"] = True
                a["share_verdict"] = d.verdict
                a["share_reason"] = d.reason
                if d.verdict == "share" and not any(
                        c["goal"] == a["topic"]
                        for c in self.ledger.share_candidates):
                    self.ledger.share_candidates.append({
                        "topic": a["topic"], "activity": a["id"],
                        "evidence": a["findings"][:1],
                        "t": self._t(),
                        "note": "分享候选——交由现有表达机制评估，不直接发送"})
                decided.append({"topic": a["topic"][:30],
                                "verdict": d.verdict, "reason": d.reason})
        if decided:
            self.ledger.save()
        return decided

    # ── 恢复 ──
    def recover(self):
        for a in self.ledger.activities.values():
            if a["state"] == A_ACTIVE:
                # 网络读取是幂等只读——恢复后继续，无需重放副作用
                self._ev("recovered", a["id"])
        self.ledger.save()

    def tick(self):
        """协调器一拍：恢复→逐活动探索一步→社交→（外层控制节拍/休眠）。"""
        self._tick_web_used = 0
        self.recover()
        out = {"explored": 0, "found": 0, "paused": 0, "social": []}
        for aid in list(self.ledger.activities.keys()):
            a = self._activity(aid)
            if a and a["state"] == A_ACTIVE:
                r = self.explore_step(aid)
                if r == "found":
                    out["found"] += 1
                elif r is None:
                    out["paused"] += 1
                else:
                    out["explored"] += 1
        out["social"] = self.social_step()
        return out


class _ShareProd:
    """活动 → SocialDecider 输入适配（带证据与类型）。"""

    def __init__(self, a):
        self.type = "social_material"
        finding = (a.get("findings") or [{}])[0]
        ev = (finding.get("evidence") or [{}])[0]
        self.text = (f"我自己查了「{a.get('topic','')}」——找到了："
                     f"{ev.get('title','')[:50]}")
        self.evidence_ids = [f.get("url", "web") for f in a.get("findings", [])
                             if f.get("evidence")] or ["web_search"]
        self.confidence = 0.6
