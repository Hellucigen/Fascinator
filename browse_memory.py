# -*- coding: utf-8 -*-
"""browse_memory — 浏览记忆结构化与跨经历知识复用（2026-10-14 任务书）。

在现有统一图谱上做**分层**，不建平行系统：

  情景层（现有节点，保持边界）：一次浏览一条经历，保留来源 URL、标题、
        原始正文片段、提取阶段标记；不同经历绝不合并。
  实体层：经 app 的 _fuzzy_match_node 对齐已有节点；新建实体低置信、
        带来源；模糊不强制合并（消歧安全由 matcher 的边界规则保证）。
  事实层：事实=边，证据=Edge.extra_attrs（2026-09-25 既有 provenance
        约定，无需扩 schema）。字段：fact/excerpt/evidence(经历id列表)
        /method/confidence/verified/conflict。
  追溯：recall_about(实体)→事实+支持经历+URL；facts_of_experience(经历)
        反查；withdraw_experience_support(经历)→逐出证据、其余证据独立
        存活、无来源事实降置信（不删除）。

抽取两级：规则级（本模块默认，确定性、零成本、只表达原文明说的事）
+ deep_extractor 注入位（生产中挂既有 LLM 抽取器；本轮测试一律 stub，
不发起真实 LLM 调用）。

幂等：经历节点打 consolidated 标记；同类事实边存在 → 只追加证据与小幅
置信提升，不新建边。
"""
import re

# 提取阶段（互斥递进；"看过"≠"读过"≠"已抽取"≠"已整合"）
STAGE_SEEN = "seen_title_only"          # 只有标题（页面没打开/正文没抓到）
STAGE_SNIPPET = "snippet_captured"      # 抓到正文片段
STAGE_EXTRACTED = "facts_extracted"     # 已产出结构化事实
STAGE_FAILED = "extraction_failed"      # 尝试抽取但输入不合法/不可用

# 规则级模式：只提取**原文明确陈述**的关系，词表限 graph_schema 本体成员。
# (主体取标题第一个《》；需要类型宾语的模式用"X 的续作/类型"式短语)
_PATTERNS = [
    (r"正式上线|正式发售|上线|发售", "具有", "已上线"),
    (r"停运|终止运营|停服", "具有", "已停运"),
    (r"公布|公开|首发|首曝", "具有", "已公布"),
]

_CONFLICT = {"已上线": "已停运", "已停运": "已上线"}


def detect_stage(title, page_ok, digest):
    """按真实证据分级，前一阶段成功不冒充后一阶段。"""
    if not page_ok:
        return STAGE_SEEN
    # 正文判定要算上标题（真实标题常自带完整事实句）；导航碎语不算正文
    probe = ((digest or "") + " " + (title or "")).strip()
    if len(probe) < 6:
        return STAGE_SEEN
    _nav = ("首页", "登录", "注册", "会员购", "番剧", "直播", "搜索",
            "广告", "下载客户端", "网站地图")
    nav_hits = sum(1 for w in _nav if w in probe)
    has_fact_word = bool(re.search(r"[《「].{2,20}[》」]|上线|发售|公布|停运|续作|发布",
                                   probe))
    if nav_hits >= 3 and not has_fact_word:
        return STAGE_SEEN
    return STAGE_SNIPPET


def _subject(title, snippet):
    m = re.search(r"《([^》]{2,24})》", str(title) or "")
    if m:
        return m.group(1).strip()
    m = re.search(r"「([^」]{2,24})」", str(title) or "")
    return m.group(1).strip() if m else ""


# ── 规则级护栏（2026-10-19 任务书§六）：作用域判断，不是固定字符窗 ──
# 命中的谓词短语必须先过三关：名词化复合词（"发售预告片"≠发售发生了）、
# 小句内否定（"并未采用/尚未发售"）、未然/历史态标记（"计划/即将/曾"）。
# 无法可靠判定时**拒绝该条规则事实**——空手后自然升级深度通道（既有
# LLM 路径，零新增调用），不确定性绝不转成肯定事实。
_CLAUSE_DELIMS = "。！？!?；;，,、\n"
_NOMINAL_TAILS = ("预告片", "预告", "PV", "pv", "宣传片", "企划", "计划",
                  "发布会", "日期", "消息")
_NEG_MARKS = ("尚未", "并未", "未采用", "未公布", "未上线", "未发售",
              "没有", "不曾", "并非", "而非", "不再", "拒绝", "否认")
_NOT_YET_MARKS = ("即将", "计划", "预计", "拟", "定于", "明年", "下周", "待")
_HISTORICAL_MARKS = ("曾经", "曾", "此前", "以前", "旧版")


def _clause_of(text, a, b):
    """包含匹配点的最小句/读单位。"""
    lo = max((text.rfind(c, 0, a) for c in _CLAUSE_DELIMS), default=-1)
    his = [text.find(c, b) for c in _CLAUSE_DELIMS if text.find(c, b) != -1]
    hi = min(his, default=len(text))
    return text[lo + 1:hi]


def _fact_guard(text, a, b):
    """返回拒绝原因或 None（通过）。"""
    tail = text[b:b + 5].lstrip()
    for t in _NOMINAL_TAILS:
        if tail.startswith(t):
            return "nominalized"
    cl = _clause_of(text, a, b)
    for mk in _NEG_MARKS:
        if mk in cl:
            return "negated"
    for mk in _NOT_YET_MARKS:
        if mk in cl:
            return "not_yet"
    for mk in _HISTORICAL_MARKS:
        if mk in cl:
            return "historical"
    return None


def extract_facts_rules(title, snippet, rejects=None):
    """规则级抽取 → [{s, rel, o, excerpt}]。
    只产出原文明确表达的事实；宣传修辞（'广袤保护区放归生灵'）不外推
    为机制断言（任务书 §4.3）：模式命中时 excerpt 必须含该短语，
    找不到原文即不产出。rejects（可选 list）收集被护栏拒绝的候选
    (o, 原因, 原文片段)——拒绝是显式决定，不是静默丢弃。"""
    s = _subject(title, snippet)
    # 标题本身也是原文明确陈述的一部分（"《X》正式上线"常在标题）
    text = (str(title or "") + " " + str(snippet or "")).strip()
    if not s:
        return [], []
    facts, entities = [], []
    # 其他《》实体（不建事实，进实体清单供"涉及"连接）
    for alt in re.findall(r"《([^》]{2,24})》", text):
        if alt != s:
            entities.append(alt.strip())
    for rx, rel, o in _PATTERNS:
        for m in re.finditer(rx, text):
            why = _fact_guard(text, m.start(), m.end())
            if why:
                if rejects is not None:
                    rejects.append((o, why,
                                    _clause_of(text, m.start(), m.end())[:80]))
                continue           # 换个命中点再试（同模式的其它出现处）
            facts.append({"s": s, "rel": rel, "o": o, "excerpt":
                          _clause_of(text, m.start(), m.end())[:120]})
            break                  # 每模式一条事实即可（原行为）
    # "X模拟游戏正统续作《Y》"式类型陈述 → Y 类型 X
    m = re.search(r"([^，。；,;\s]{2,20}?)(?:的正统续作|正统续作)", text)
    if m:
        typ = m.group(1).strip()
        typ = re.sub(r"^(人气|知名|爆款)", "", typ).strip() or typ
        if len(typ) >= 3 and typ != s and typ not in ("", "游戏"):
            facts.append({"s": s, "rel": "类型", "o": typ,
                          "excerpt": m.group(0)[:120]})
            entities.append(typ)
    return facts, ([s] + entities)


def _upsert_entity(kg, engine, name, url, fuzzy_match, seen_ids):
    """实体对齐：先过 fuzzy_match（完全/别名/边界安全档），未命中才新建。
    新建：declarative-semantic、低权重、低置信、带来源。"""
    if not name or len(seen_ids) > 40:
        return None
    mapped = fuzzy_match(name) if fuzzy_match else name
    if kg.get_node(mapped) is not None:
        return mapped
    from graph_model import Node
    if kg.get_node(name) is None:
        ok = kg.add_node(Node(
            id=name, weight=0.35, label="declarative-semantic",
            graph_space="semantic", confidence=0.4,
            extra_attrs={"type": "概念", "source": "browse:%s" % (url or "")[:
                                                                    120],
                         "extraction": "rule", "verified": False}))
        if ok and engine is not None:
            try:
                engine.name_to_node.setdefault(name, kg.nodes[name])
            except Exception:
                pass
        return name if ok else None
    return name


def _fact_edge_key(kg, s, rel, o):
    return kg.get_edge(s, o, rel)


def consolidate_browse_memory(kg, engine, exp_id, url, title, snippet,
                              page_ok, fuzzy_match=None,
                              deep_extractor=None):
    """一条浏览经历的结构化整合（幂等）。
    返回 {"stage","facts":[...],"entities":[...],"skipped":[原因...]}。"""
    exp = kg.get_node(exp_id)
    if exp is None:
        return {"stage": STAGE_FAILED, "facts": [], "entities": [],
                "skipped": ["experience node not found"]}
    ea = exp.extra_attrs if isinstance(exp.extra_attrs, dict) else {}
    if ea.get("consolidated"):
        return {"stage": ea.get("extraction_stage") or STAGE_SNIPPET,
                "facts": [], "entities": [], "skipped": ["already done"]}
    skipped = []
    stage = detect_stage(title, page_ok, snippet)
    if stage == STAGE_SEEN:
        ea.update({"consolidated": True, "extraction_stage": stage,
                   "extraction_note": "只有标题/无正文，不产出正文事实"})
        exp.extra_attrs = ea
        return {"stage": stage, "facts": [], "entities": [], "skipped": skipped}

    rejects = []
    facts, entities = extract_facts_rules(title, snippet, rejects=rejects)
    for o_, why_, quote_ in rejects:
        skipped.append("规则级拒绝[%s]: %s「%s」" % (why_, o_, quote_[:40]))
    method = "rule"
    if not facts and deep_extractor is not None:
        # 阶梯（18:4x 生产实锤：真实 B站标题多无《》，规则常空手）：
        # 规则级先试；落空才升级注入的深度抽取器（生产中=既有断言抽取）。
        try:
            facts, entities = deep_extractor(title, snippet)
            method = "deep"
        except Exception:
            pass
    if not facts:
        skipped.append("规则未找到明确陈述（不代表原文没有）")
    from graph_model import Edge
    from graph_schema import HUB_ENTITY_NAMES, normalize_verbose
    made, seen_ids = [], set()
    for name in entities:
        e = _upsert_entity(kg, engine, str(name)[:24], url, fuzzy_match,
                           seen_ids)
        if e:
            seen_ids.add(e)
            # 代词映射不认人：第三方文本里的"我们/我"不是我们的用户/自我
            # （2026-10-19 弹丸论破视频抽取伪造"涉及→用户"实锤）——枢纽
            # 端点一律不建"涉及"边。想表达"值得聊给用户"走 value→相关 通道。
            if str(e) in HUB_ENTITY_NAMES:
                skipped.append("枢纽端点拒绝涉及边: %s" % e)
                continue
            if kg.get_edge(exp_id, e, "涉及") is None:
                kg.add_edge(Edge(src=exp_id, dst=e, relation="涉及",
                                 weight=0.45))
    for f in facts:
        s = _upsert_entity(kg, engine, f["s"][:24], url, fuzzy_match,
                           seen_ids)
        o = _upsert_entity(kg, engine, f["o"][:24] if f["rel"] in
                           ("类型",) else f["o"], url, fuzzy_match, seen_ids)
        o = o or (f["o"] if kg.get_node(f["o"]) is None else f["o"])
        if not s:
            skipped.append("主体无法对齐: %s" % f["s"])
            continue
        if str(s) in HUB_ENTITY_NAMES or str(o or "") in HUB_ENTITY_NAMES:
            skipped.append("枢纽端点拒绝事实边: %s-%s->%s" % (s, f["rel"], o))
            continue
        f_method = f.get("method") or method
        ex = _fact_edge_key(kg, s, f["rel"], o)
        if ex is not None:
            xa = ex.extra_attrs if isinstance(ex.extra_attrs, dict) else {}
            ev = set(xa.get("evidence") or []) | {exp_id}
            xa["evidence"] = sorted(ev)
            if xa.get("url") and url and xa["url"] != url:
                xa["multi_source"] = True
            xa["confidence"] = round(
                min(0.6, 0.3 + 0.15 * len(ev)), 2)
            ex.extra_attrs = xa
            made.append({"s": s, "rel": f["rel"], "o": o, "reused": True})
            continue
        # 矛盾共存：同 s→(冲突 o) 已有事实边 ⇒ 保留双方并标冲突
        conflict = None
        opp = _CONFLICT.get(f["o"])
        if opp:
            for e2 in kg.edges:
                xa2 = e2.extra_attrs if isinstance(e2.extra_attrs, dict) else {}
                if (e2.src == s and e2.dst == opp
                        and xa2.get("fact") and not xa2.get("withdrawn")):
                    conflict = opp
                    xa2.setdefault("conflict", []).append(o)
                    e2.extra_attrs = xa2
        # 状态词（已上线等）只作事实宾语字符串，不建独立实体节点
        w = 0.4 if method == "rule" else 0.55
        _rel_in = str(f["rel"] or "").strip()
        _canon, _kind = normalize_verbose(_rel_in)
        if _kind == "empty":
            skipped.append("事实关系为空，不猜填: %s->%s" % (s, o))
            continue
        _attrs = {"fact": True, "excerpt": f["excerpt"],
                  "evidence": [exp_id], "url": (url or "")[:160],
                  "method": f_method, "confidence": w, "verified": False,
                  **({"conflict": [conflict]} if conflict else {})}
        if _kind == "fallback":
            # 词表表达不了、但原文有证据的具体谓词：**保留原词入图**，
            # 标未归一化待审计（传播按共现类走）。绝不压平成 关联/具有/
            # 使用——语义保真优先于词表整齐。
            _attrs.update({"relation_raw": _rel_in[:24],
                           "relation_status": "unnormalized"})
            ok = kg.add_edge(Edge(
                src=s, dst=o or "未知", relation=_rel_in[:12], weight=w,
                relation_category="cognitive_relation",
                extra_attrs=_attrs), keep_relation=True)
        else:
            ok = kg.add_edge(Edge(
                src=s, dst=o or "未知", relation=_rel_in, weight=w,
                extra_attrs=_attrs))
        if ok:
            made.append({"s": s, "rel": f["rel"], "o": o,
                         "conflict": bool(conflict), "rel_kind": _kind})
        else:
            skipped.append("边被拒: %s-[%s]->%s" % (s, f["rel"], o))
    stage = STAGE_EXTRACTED if made else STAGE_FAILED
    ea.update({"consolidated": True, "extraction_stage": stage,
               "fact_count": len(made), "method": method})
    exp.extra_attrs = ea
    if engine is not None and made:
        try:
            engine.mark_active(exp_id)
        except Exception:
            pass
    return {"stage": stage, "facts": made,
            "entities": sorted(seen_ids), "skipped": skipped}


def facts_of_experience(kg, exp_id):
    """由一条经历支持的全部事实（任务书测试 #10）。"""
    out = []
    for e in kg.edges:
        xa = e.extra_attrs if isinstance(e.extra_attrs, dict) else {}
        if xa.get("fact") and exp_id in (xa.get("evidence") or []):
            out.append(e)
    return out


def recall_about(kg, entity):
    """实体 → 直接事实、支持经历、来源 URL（测试 #9/#12 的读侧）。"""
    facts, exps, urls = [], set(), set()
    for e in kg.edges:
        xa = e.extra_attrs if isinstance(e.extra_attrs, dict) else {}
        if not xa.get("fact"):
            continue
        if e.src == entity or e.dst == entity:
            facts.append(e)
            for ev in xa.get("evidence") or []:
                exps.add(ev)
            if xa.get("url"):
                urls.add(xa["url"])
    return {"entity": entity, "facts": facts, "experiences": sorted(exps),
            "sources": sorted(urls)}


def withdraw_experience_support(kg, exp_id):
    """某经历被纠正/撤销：从各事实的证据里逐出它；仍有其他证据的事实
    **原样存活**；失去全部来源的事实标 withdrawn 降置信（不删除——
    记忆不无理由消失，只如实降级）。"""
    demoted = []
    for e in facts_of_experience(kg, exp_id):
        xa = e.extra_attrs
        ev = [x for x in xa.get("evidence") or [] if x != exp_id]
        xa["evidence"] = ev
        if not ev:
            xa["withdrawn"] = True
            xa["confidence"] = 0.2
            demoted.append("%s-[%s]->%s" % (e.src, e.relation, e.dst))
        e.extra_attrs = xa
    return demoted
