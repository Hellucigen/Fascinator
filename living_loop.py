# -*- coding: utf-8 -*-
"""living_loop.py — HARU 自主生活循环（生产模块，2026-10-11 提升）。

来源：experiments/living_v3/living_loop.py（隔离验收 21 场景 + 真实网络
验收：失败→改写→相关→网页读取→账本恢复→分享判定，全程可复核）。
相对实验版新增：每日网络预算（账本内日计数）；守护线程入口
run_living_loop_daemon（单例守卫 + flag 门控 + 真实 chat_log 缺口来源）。

安全边界：网页内容=不可信输入（剥标签、untrusted 标记、永不执行）；
只读探索；分享只登记候选不发送；状态持久化 data/living_ledger.json。
"""
import html
import json
import logging
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
        self.concept = None          # 干净查询概念（P0；旧账本无此键→回退清洗 topic）

    def to_dict(self):
        return self.__dict__.copy()


class ActivityLedger:
    def __init__(self, path):
        self.path = path
        self.activities = {}
        self.experiences = []
        self.share_candidates = []
        self.daily = {}                  # {"YYYY-MM-DD": 网络调用次数}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                d = json.load(open(self.path, encoding="utf-8"))
                self.activities = {a["id"]: a for a in d.get("activities", [])}
                self.experiences = d.get("experiences", [])
                self.share_candidates = d.get("share_candidates", [])
                self.daily = d.get("daily_web_calls", {})
            except (OSError, ValueError, KeyError):
                self.activities, self.experiences = {}, []
                self.share_candidates = []

    def web_budget_left(self, daily_budget):
        import datetime
        today = datetime.date.today().isoformat()
        return max(0, int(daily_budget) - int(self.daily.get(today, 0)))

    def count_web_call(self, daily_budget):
        import datetime
        today = datetime.date.today().isoformat()
        self.daily[today] = int(self.daily.get(today, 0)) + 1
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump({"activities": [a for a in self.activities.values()],
                   "experiences": self.experiences,
                   "share_candidates": self.share_candidates,
                   "daily_web_calls": self.daily},
                  open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)


# ── 探索器（网页=不可信输入） ─────────────────────────────────
UA = "Mozilla/5.0 (compatible; HARU-living/0.1; read-only research)"


def web_search_fn():
    """生产 web_search：认知仓 actions 包（app.py bootstrap 已入 sys.path）。"""
    from actions.web_search import do_web_search
    return do_web_search


def extract_readable(raw):
    """从 HTML 提取"页面真正在说什么"（16:0x 质量修正：整页剥标签会把
    导航/推荐位当正文——B站摘要全是"首页 番剧 直播"即为此）：
    meta description（站点自述的摘要，最干净）优先，随后取最长的几个
    <p> 正文段落；纯函数便于测试。"""
    metas = re.findall(
        r'<meta[^>]+(?:property|name)="(?:og:description|description)"'
        r'[^>]+content="([^"]{10,500})"', raw, re.I)
    if not metas:
        metas = re.findall(
            r'<meta[^>]+content="([^"]{10,500})"[^>]+(?:property|name)='
            r'"(?:og:description|description)"', raw, re.I)
    paras = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S | re.I):
        t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", p)).split())
        if len(t) >= 24 and not t.startswith(
                ("首页", "登录", "注册", "Copyright", "版权所有")):
            paras.append(t)
    meta_txt = " ".join(" ".join(html.unescape(m).split())
                        for m in metas[:2])[:500]
    body = " ".join(paras[:5])
    text = (meta_txt + " " + body).strip() if (meta_txt or body) else \
        " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())
    return text[:1200]


def read_page(url, max_bytes=60000, timeout=12):
    """只读网页：限长、解压、剥标签（含 script/style）、乱码防护、标记
    untrusted。返回 {ok, text, source}。
    15:0x 生产实锤：4KB 截断 + 不解压 → B站页存进记忆的是二进制乱码。"""
    try:
        safe = urllib.parse.quote(url, safe=":/?&=%+#")
        req = urllib.request.Request(
            safe, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes)
            enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip" or data[:2] == b"\x1f\x8b":
            import gzip as _gz
            data = _gz.decompress(data)
        elif data[:1] == b"\x78":
            import zlib
            data = zlib.decompress(data)
        raw = data.decode("utf-8", "ignore")
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        text = extract_readable(raw)
        probe = text[:400]
        vis = sum(1 for ch in probe
                  if (ch.isascii() and ch.isprintable())
                  or 0x4E00 <= ord(ch) <= 0x9FFF)
        if len(probe) >= 20 and vis / len(probe) < 0.7:
            text = ""                              # 乱码页=没有内容，宁缺毋滥
        return {"ok": True, "text": text[:1200], "source": url,
                "untrusted": True}
    except Exception as e:                        # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "source": url, "untrusted": True}


import math


def _fresh(iso_ts):
    """证据新鲜度：72h 半衰的连续函数（用户求助与新念头共用同一语义）。"""
    try:
        import datetime
        t = time.mktime(datetime.datetime.fromisoformat(
            str(iso_ts)).timetuple())
    except (ValueError, TypeError, OSError):
        return 0.2                              # 没时间戳：低但非零
    age_h = max(0.0, (time.time() - t) / 3600.0)
    return math.exp(-age_h / 72.0 * math.log(2))


def _clean_topic(q):
    """剥掉展示用散文前缀与书名/弯引号（P0 质量修复）。

    实锤教训（2026-10-12 监测）：topic "搞清楚「冯诺依曼代数熵」" 经
    [-3:] 切片产出残迹查询 "数熵」"，命中《数》字典页→误报"学到了"。
    """
    q = str(q or "").strip()
    q = re.sub(r"^(搞清楚|了解一下|弄明白|研究一下|查一下)[：:，,]?", "", q)
    q = q.strip("「」『』《》“”\"'【】（）() 　")
    return q.strip()


# 可搜索性门（2026-10-24 实锤：探索器把图谱节点 ID 字面当查询
# （"搜索记录_1792765023"→bing）、拿单独常用词（"假设"）反复白搜）。
# 原则：query 必须是可能存在于公网的实体/术语——内部 ID 形态、单独
# 日常概念词都不配。不合格 → 探索如实搁置，绝不烧搜索预算。
_INTERNAL_ID_RE = re.compile(r"_[0-9]{6,}")
_NOT_ENTITY_WORDS = ("假设", "东西", "事情", "问题", "感觉", "想法",
                     "关系", "心情", "生活", "世界")


def valid_search_topic(q):
    q = _clean_topic(q)
    if not q or len(q) < 2:
        return False
    if _INTERNAL_ID_RE.search(q):
        return False
    if q in _NOT_ENTITY_WORDS:
        return False
    return True


def _concept_match(concept, blob):
    """确定性相关判定（无 LLM）：整词命中，或（长度≥4 时）首二字+末二字
    同时命中且两个碎片不同。只含单字/碎片段的 blob 不算相关。"""
    c = _clean_topic(concept)
    if not c:
        return False
    if c in blob:
        return True
    if len(c) >= 4:
        first, last = c[:2], c[-2:]
        if first != last and first in blob and last in blob:
            return True
    return False


def query_rewrite(query, attempt):
    """失败驱动的查询改写策略（确定性序列，至少 4 档）：
    原样 → 去前缀修饰 → 末段+是什么 → 首二字词根。

    P0 修复：先清洗引号残迹/散文前缀再改写；末段档不再产生带「」的查询，
    且末段+是什么档必须保持概念尾部词元完整（取末 2-4 字，不切破词）。"""
    base = _clean_topic(query)
    tail = base[-4:] if len(base) >= 4 else base
    strategies = [
        base,
        _split_compound(base),
        # 末段档只对真正的长复合术语有意义：短概念被切出"户与深夜"这种
        # 残迹查询（2026-10-24 实锤"用户与深夜"），≥6 字才允许切。
        (tail + " 是什么") if (tail != base and len(base) >= 6) else None,
        _root_word(base),
    ]
    # 去重保序：相同策略跳过（由调用方 methods_tried 兜底）；
    # 同时过可搜索性门——内部 ID 形态/单独常用词不是策略，是浪费
    seen, out = set(), []
    for s in strategies:
        if s and s not in seen and valid_search_topic(s):
            seen.add(s)
            out.append(s)
    if not out:
        return None
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
    def open_activity(self, topic, source_product, concept=None):
        # max_activities_open 上限
        open_n = sum(1 for a in self.ledger.activities.values()
                     if a["state"] in (A_ACTIVE, A_WAITING))
        if open_n >= self.budget["max_activities_open"]:
            self._ev("activity_rejected", f"open_activities_full({open_n})")
            return None
        seed = _clean_topic(concept or topic)
        # 同主题去重 + 搁置恢复（2026-10-14 深化：72h 时锁与次数硬顶**已删**）。
        # 恢复与否不再看时钟/计数器，看**提名本身**：候选侧（activities.
        # _graph_strength）只在"暂停之后出现、且未被消费过的新证据"存在时才
        # 提名搁置概念——没被提名=没有新信息=不动手；被提名=条件真的变了。
        # 本函数职责回退为纯工程闸：active/waiting 占用去重。
        for a in self.ledger.activities.values():
            akey = _clean_topic(a.get("concept") or a["topic"])
            same = (a["topic"] == topic) or (akey and akey == seed)
            if not same:
                continue
            if a["state"] in (A_ACTIVE, A_WAITING):
                self._ev("activity_rejected", f"duplicate:{topic[:30]}")
                return None
            if a["state"] in (A_PAUSED, A_ABANDONED):
                # 提名即新条件：候选侧只在"有未被消费的新证据/用户重问"时
                # 才会提名搁置概念（_graph_strength 证据消费模型），此处
                # 不再叠加时间锁或次数硬顶。resume_count 累积=成本因子，
                # 在强度分母里自然降低反复失败者的竞争力。
                a["state"] = A_ACTIVE
                a["end_reason"] = None
                a["methods_tried"] = []
                a["web_calls"] = 0
                a["resume_count"] = int(a.get("resume_count") or 0) + 1
                a["updated"] = self._t()
                self._ev("activity_resumed", topic, a["id"])
                self.ledger.save()
                return a["id"]
            if a["state"] == A_DONE:
                # 已完成的问题被再次提名=出现了新问题面（假设/矛盾证据），
                # 开新活动而不是复活旧档（旧证据链保留为知识）
                break
        aid = f"life_{int(self._t())}"
        a = Activity(aid, topic, source_product, self._t(),
                     self.budget["max_web_calls_per_activity"])
        a.concept = seed        # 查询/相关判定用干净概念，展示仍用原 topic
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
            a["updated"] = self._t()
            self._ev("budget_exhausted", aid)
            self._save_activity(a)
            return None
        if self._tick_web_used >= self.budget["per_tick_web_calls"]:
            self._ev("tick_budget_pause", aid)
            return None
        # 查询改写：失败驱动的策略序列。P0：种子=干净概念（不喂展示用散文 topic）
        seed = a.get("concept") or _clean_topic(a["topic"])
        # 可搜索性门：种子不是公网实体（内部 ID 形态/单独常用词）→ 如实
        # 搁置不烧预算（重提名仍由证据消费模型把关，与策略耗尽同语义）
        if not valid_search_topic(seed):
            a["state"] = A_PAUSED
            a["end_reason"] = "seed_not_searchable"
            a["updated"] = self._t()
            self._ev("seed_not_searchable", seed, aid)
            self._save_activity(a)
            return None
        attempt = len(a["methods_tried"])
        q = query_rewrite(seed, attempt)
        if not q or q in a["methods_tried"]:
            # 全部策略已试过且无有效结果 → 搁置（2026-10-14 深化：不再
            # "二次失败即永久放弃"的次数硬顶——那是人为规则。搁置就是搁置：
            # 记忆保留、end_reason 记录失败形状；重提名由证据消费模型把关，
            # 反复失败的惩罚体现在强度分母 penalty 里）。
            a["state"] = A_PAUSED
            a["end_reason"] = "all_query_strategies_exhausted"
            a["updated"] = self._t()
            self._ev("strategies_exhausted", aid)
            self._save_activity(a)
            return None
        a["methods_tried"].append(q)
        a["web_calls"] += 1
        self._tick_web_used += 1
        self.ledger.count_web_call(0)      # P0：每日预算计数真正接线
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
        # 相关性判断（P0 收紧）：对**概念整体**判定——整词命中，或
        # 首二字+末二字双碎片命中。旧逻辑（单碎片/含长度≥2 填充词的
        # token）曾把《数》字典页判相关→误报"学到了"（2026-10-12 实锤）。
        relevant = [r for r in results
                    if _concept_match(seed,
                                      (r.get("title", "") or "") + " " +
                                      (r.get("snippet", "") or ""))]
        if relevant:
            # 读取第一条相关网页（只读、限长、untrusted 标记）
            url = relevant[0].get("url", "")
            page = {}
            if url:
                page = read_page(url)
                self._tick_web_used += 1
                a["web_calls"] += 1
                self.ledger.count_web_call(0)
            if page.get("ok"):
                # P0：页面内容也要过同一道相关闸——残片/跑题页不放行
                page["content_relevant"] = _concept_match(seed, page["text"])
            page_mismatch = bool(page.get("ok")) and not page.get("content_relevant")
            if page_mismatch:
                a["known_failures"].append(
                    f"页面内容与主题不符（未算发现）：{url[:80]}")
                self._save_activity(a)
                self._ev("page_offtopic", url[:80], aid)
                return "irrelevant"
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
            a["updated"] = self._t()
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
            # 被拒不永久封箱、被差不无脑重试（2026-10-14 深化）：每个发现
            # 最多复审 2 次。首拒可能是"对话正热不宜插话"这类**情境性**拒绝，
            # 下一拍情境变了值得再看；两次都拒=时机确实不对，安静。
            if a["state"] == A_DONE and a["findings"] and \
                    not a.get("share_decided") and \
                    int(a.get("share_reviews") or 0) < 2:
                prod = _ShareProd(a)
                d = decide_share(prod, self.social_ctx)
                a["share_reviews"] = int(a.get("share_reviews") or 0) + 1
                if d.verdict == "share":
                    a["share_decided"] = True
                    a["share_verdict"] = d.verdict
                    a["share_reason"] = d.reason
                    if not any(
                            c["goal"] == a["topic"]
                            for c in self.ledger.share_candidates):
                        self.ledger.share_candidates.append({
                            "topic": a["topic"], "activity": a["id"],
                            "evidence": a["findings"][:1],
                            "t": self._t(),
                            "note": "分享候选——交由现有表达机制评估，不直接发送"})
                elif int(a.get("share_reviews") or 0) >= 2:
                    a["share_decided"] = True     # 两次拒绝=时机确实不对
                    a["share_verdict"] = d.verdict
                    a["share_reason"] = d.reason
                decided.append({"topic": a["topic"][:30],
                                "verdict": d.verdict, "reason": d.reason})
        if decided:
            self.ledger.save()
        return decided

    # ── 恢复 ──
    def recover(self):
        # [Living][recover] 可观测（任务书 §7）：只在真有恢复动作时记一行，
        # 无事时不产日志；"无须恢复"与"恢复失败"因此可与普通空转区分。
        n_rec = 0
        for a in self.ledger.activities.values():
            if a["state"] == A_ACTIVE:
                # 网络读取是幂等只读——恢复后继续，无需重放副作用
                self._ev("recovered", a["id"])
                n_rec += 1
        self.ledger.save()
        if n_rec:
            logging.getLogger("living_loop").info(
                "[Living][recover] %d 个进行中活动已对账恢复", n_rec)
        return n_rec

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
        _pg = (finding.get("page_read") or {})
        _digest = str(_pg.get("text") or "").strip()
        _digest = " ".join(_digest.split())[:80]
        self.text = (f"我自己查了「{a.get('topic','')}」——找到了："
                     f"{ev.get('title','')[:50]}"
                     + (f"。里面说：{_digest}" if _digest else ""))
        self.evidence_ids = [f.get("url", "web") for f in a.get("findings", [])
                             if f.get("evidence")] or ["web_search"]
        self.confidence = 0.6


# ── 生产守护入口（v3.4：受控接入） ─────────────────────────────
_DAEMON_THREAD = None                    # 单例守卫（进程内唯一）


def build_social_context(chat_entries, now=None):
    """真实对话上下文 → SocialContext（只读 chat_log，时间语义如实）。"""
    import datetime
    user_turns = [x for x in chat_entries
                  if x.get("proactive") in (False, "False", None)]
    proac = [x for x in chat_entries if x.get("proactive") in (True, "True")]
    now = now or time.time()

    def ts(s):
        try:
            return time.mktime(datetime.datetime.fromisoformat(
                s).timetuple()) if s else 0.0
        except (ValueError, TypeError):
            return 0.0
    last_user = user_turns[-1] if user_turns else None
    last_pro = proac[-1] if proac else None
    return SocialContext(
        user_recent_ts=ts(last_user.get("time")) if last_user else 0.0,
        user_recent_text=str(last_user.get("user_input") or "")[:80]
        if last_user else "",
        conversation_open=bool(last_user and
                               now - ts(last_user.get("time")) < 1800),
        recent_expressed=[str(x.get("system_response") or "")[:60]
                          for x in proac[-5:]],
        recent_express_ts=ts(last_pro.get("time")) if last_pro else 0.0,
        now=now)


def real_knowledge_gap(chat_entries, acted_goals):
    """真实知识缺口：用户明确说没看懂、且未被生产 SelfSearch/影子处理过的概念。"""
    gaps, seen = [], set()
    for x in chat_entries:
        ui = str(x.get("user_input") or "")
        if x.get("proactive") in (True, "True"):
            continue
        for m in re.findall(r"「([^」]{3,20})」", ui):
            if m in seen or any(m in g for g in acted_goals):
                continue
            seen.add(m)
            gaps.append({"concept": m, "ts": x.get("time", ""),
                         "evidence": ui[:60]})
    return gaps


def living_tick_once(config, logger=None, deliver_fn=None, search_fn=None,
                     data_dir=None, extra_gaps=None):
    """一拍完整生活管线（P0-2 抽出为模块级：可同步测试，无需守护线程/网络）。

    恢复→预算恢复日→推进活跃活动→社交决策→分享消费→开新活动。
    data_dir 默认 FAS_LIVING_DATA_DIR 或仓内 data/；search_fn 默认真实网络。
    """
    import datetime
    lg = logger or logging.getLogger("living_loop")
    daily_budget = int(config.get("living_loop_daily_web_budget", 40))
    data_dir = data_dir or os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data")
    ledger_path = os.path.join(data_dir, "living_ledger.json")
    ledger = ActivityLedger(ledger_path)
    if ledger.web_budget_left(daily_budget) <= 0:
        lg.info("[Living] 今日网络预算耗尽 → 休眠")
        return {}
    try:
        entries = json.load(open(os.path.join(
            data_dir, "chat_log.json"), encoding="utf-8"))
    except (OSError, ValueError):
        entries = []
    social = build_social_context(entries)
    loop = LivingLoop(ledger_path,
                      search_fn=search_fn or web_search_fn(), social_ctx=social,
                      budget={"max_activities_open": int(config.get(
                          "living_loop_max_activities_open", 1)),
                          "max_web_calls_per_activity": int(config.get(
                              "living_loop_max_web_per_activity", 6))})
    loop.recover()
    # ⓪ 预算恢复日：waiting（旧日预算耗尽）在新一天回到 active。
    # 注意：必须改 loop.ledger 同一实例（曾误改先加载的旧快照→恢复不生效）
    today = datetime.date.today().isoformat()
    if int(loop.ledger.daily.get(today, 0)) < daily_budget:
        for a in loop.ledger.activities.values():
            if a.get("state") == A_WAITING:
                a["state"] = A_ACTIVE
                a["end_reason"] = None
                lg.info("[Living] 预算新日恢复 %s", a["id"])
        loop.ledger.save()
    # ① 推进活跃活动（探索一步：搜索/改写/读取/判定）
    acted = False
    explored = []
    for aid in list(loop.ledger.activities.keys()):
        a = loop.ledger.activities.get(aid)
        if a and a.get("state") == "active":
            r = loop.explore_step(aid)
            acted = True
            explored.append({"aid": aid, "result": r})
            lg.info("[Living] 探索 %s → %s", aid, r)
    social_out = loop.social_step()
    # ② 分享候选消费（P5）：SocialDecider 已判 share 的候选投递给表达层
    delivered = []
    if deliver_fn:
        for c in loop.ledger.share_candidates:
            if c.get("delivered"):
                continue
            try:
                res = deliver_fn(c)
            except Exception as e:            # noqa: BLE001
                lg.warning("[Living] 分享投递异常（保留候选）: %r", e)
                res = False
            if res is False:
                lg.info("[Living] 分享候选延后（投递方忙/条件不满足）")
                break                          # 一拍一次，不排队轰炸
            c["delivered"] = True
            c["delivered_at"] = loop._t()
            loop.ledger.save()
            delivered.append(c.get("topic"))
            lg.info("[Living] 分享候选已投递: %s", str(c.get("topic"))[:40])
            break
    # ③ 无活跃活动且缺口未处理 → 开新活动。
    # P0：acted 集取自账本（含耗尽概念），不再传空集（曾致同概念无限重开）
    live = sum(1 for a in loop.ledger.activities.values()
               if a.get("state") in ("active", "waiting"))
    acted_set = set()
    for a in loop.ledger.activities.values():
        for k in (a.get("concept"), _clean_topic(a.get("topic", "")),
                  a.get("topic")):
            if k:
                acted_set.add(k)
    gaps = [g for g in real_knowledge_gap(entries, acted_set)]
    for g in gaps:
        # 用户求助的竞争力=证据新鲜度（72h 半衰，与陪伴层同一连续函数）：
        # 刚提出的自然占先，过时的让位——不是"永久高分规则压制一切"。
        g.setdefault("priority", round(0.9 * _fresh(
            g.get("ts")), 4))
    # 图谱自然念头（陪伴层 _graph_strength 按强度排序注入）：与用户缺口
    # **同池竞争**，谁强做谁——排序依据是各自的图谱量，不是来源档位。
    for g in (extra_gaps or []):
        c = str(g.get("concept") or "")
        if c and not any(c in str(x.get("concept") or "") or
                         str(x.get("concept") or "") in c for x in gaps):
            gaps.append(g)
    opened = None
    if not acted and not live and gaps:
        g0 = max(gaps, key=lambda g: float(g.get("priority") or 0.0))
        opened = loop.open_activity(f"搞清楚「{g0['concept']}」",
                                    str(g0.get("evidence") or
                                        f"chat_log@{g0.get('ts','')}"),
                                    concept=g0["concept"])
        if opened:
            lg.info("[Living] 活动开启: %s (念头=%s, 强度=%.2f)", opened,
                    g0["concept"], float(g0.get("priority") or 0))
    return {"explored": explored, "social": social_out,
            "delivered": delivered, "opened": opened,
            "gaps_remaining": len(gaps)}


def run_living_loop_daemon(config, logger=None, deliver_fn=None,
                           beat_fn=None, wake_event=None):
    """启动生活循环守护线程（单例）。返回 (started, reason)。
    flag: config["living_loop_enabled"]；预算: config["living_loop_daily_web_budget"]。
    学习/账本全部写 data/living_ledger.json（隔离于生产图谱）。
    deliver_fn（P5 消费接线）：分享候选 → 既有表达投递口；返回 False=延后，
    True/None=已消化。每拍最多投递 1 条（防刷屏），投递后候选标记 delivered
    （幂等，重启不会重发同一条）。
    beat_fn（2026-10-13 "自己的日常"）：接管每拍的选择权——注入后由
    activities.beat 决定这拍听歌/逛逛/调研/什么都不做（research 分支内部
    仍调用 living_tick_once，原调研链零改动）；不注入=纯调研旧行为。"""
    global _DAEMON_THREAD
    if _DAEMON_THREAD is not None and _DAEMON_THREAD.is_alive():
        return False, "already_running"
    import threading

    lg = logger or logging.getLogger("living_loop")
    tick_s = max(60, int(config.get("living_loop_tick_s", 600)))
    daily_budget = int(config.get("living_loop_daily_web_budget", 40))
    # 测试隔离口：FAS_LIVING_DATA_DIR 指到临时目录（T5 曾两次污染生产账本，
    # 2026-10-12 实锤教训）。生产不设此环境变量=路径照旧。

    woke_by_event = [False]        # 下一拍的唤醒原因：事件 or 巡检到期

    def _run():
        while True:
            trig = "event" if woke_by_event[0] else "sweep"
            woke_by_event[0] = False
            try:
                if config.get("living_loop_enabled", False):
                    if beat_fn is not None:
                        try:
                            beat_fn(trigger=trig)
                        except TypeError:      # 旧签名 beat_fn 兼容
                            beat_fn()
                    else:
                        living_tick_once(config, lg, deliver_fn)
                # flag 热停：false → 本拍跳过（不执行任何网络调用）
            except Exception as e:                # noqa: BLE001
                lg.warning("[Living] tick 异常（忽略）: %r", e)
            # 状态驱动改造（2026-10-13）：wake_event 给定 → 事件可提前唤醒
            # 重评估；tick_s 退化为安全网巡检上限（恢复/超时/事件丢失兜底）。
            if wake_event is not None:
                woke_by_event[0] = bool(wake_event.wait(timeout=tick_s))
                wake_event.clear()
            else:
                time.sleep(tick_s)

    _DAEMON_THREAD = threading.Thread(target=_run, daemon=True,
                                      name="living-loop")
    _DAEMON_THREAD.start()
    lg.info("[Living] 生活循环守护线程已启动（tick=%ss, 日预算=%s）",
            tick_s, daily_budget)
    return True, "started"
