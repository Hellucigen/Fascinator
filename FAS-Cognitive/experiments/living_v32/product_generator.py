# -*- coding: utf-8 -*-
"""living_v32/product_generator.py — 多来源认知产物生成器（v3.2）。

来源（全部只读、可追溯）：
  chat_log      用户真实发言 → open_question（用户明确说没看懂的概念）
  failed_search 生产检索失败自述 → reflection（换查询策略的修正产物）
  graph         已有记忆与用户概念的共现 → relation_finding
  thoughts      自由思考节点 → introspection（如实，不产任务）

关键约束（任务 §3）：
  - 每产物带 source_refs/evidence_summary/novelty/potential_value/
    estimated_cost/next_action/status
  - 区分 用户说过的事实 / 图内记录 / 推断 / 未验证假设
  - 证据不足允许空集——不产任务不是失败
"""
import json
import re
import time
import uuid

TYPES = ("open_question", "knowledge_gap", "relation_finding",
         "action_candidate", "user_lead", "reflection", "no_action",
         "introspection")

FACT = "fact"            # 用户明确说过 / 图内已有记录
INFERENCE = "inference"  # 根据证据作出的推断
HYPOTHESIS = "hypothesis"  # 未验证假设


class ProductV32:
    def __init__(self, product_type, content, source_refs,
                 evidence_summary, confidence, novelty, potential_value,
                 estimated_cost, next_action="", status="candidate",
                 epistemic=INFERENCE, pid=None):
        self.product_type = product_type
        self.content = content
        self.source_refs = source_refs          # 可追溯真实来源
        self.evidence_summary = evidence_summary
        self.confidence = confidence
        self.novelty = novelty
        self.potential_value = potential_value
        self.estimated_cost = estimated_cost
        self.next_action = next_action
        self.status = status                    # candidate|pending|resolved|abandoned|deferred
        self.epistemic = epistemic              # fact|inference|hypothesis
        self.pid = pid or f"p32_{uuid.uuid4().hex[:8]}"

    def to_dict(self):
        return self.__dict__.copy()


def _novelty_vs(text, existing_texts):
    """与已有产物的字符集重复度 → novelty（1=全新）。"""
    best = 0.0
    probe = set(text[:80])
    for t in existing_texts:
        p = set(str(t)[:80])
        if p:
            best = max(best, len(probe & p) / max(len(probe | p), 1))
    return round(1.0 - best, 2)


def from_chat_log(chat_entries, existing_texts=(), now=None):
    """来源①：用户真实发言中的未知概念 → open_question（epistemic=fact：
    用户确实说了没看懂——这是外部事实，不是推断）。"""
    now = now or time.time()
    out = []
    seen = []
    for x in chat_entries:
        ui = str(x.get("user_input") or "")
        if x.get("proactive") in (True, "True") or "没看懂" not in ui \
                and "不懂" not in ui:
            continue
        for concept in re.findall(r"「([^」]{3,20})」", ui):
            if concept in seen:
                continue
            seen.append(concept)
            nov = _novelty_vs(f"研究概念{concept}", existing_texts)
            out.append(ProductV32(
                product_type="open_question",
                content=f"用户在 {x.get('time','')} 明确表示没看懂「{concept}」"
                        f"——这个概念还没有被解释或检索过。",
                source_refs=[f"chat_log@{x.get('time','')}",
                             f"user_input:{ui[:50]}"],
                evidence_summary=f"用户原话：{ui[:60]}",
                confidence=0.9,              # 用户亲口说的外部事实
                novelty=nov,
                potential_value="用户当场表达的困惑，跟进有直接关系价值",
                estimated_cost="web_search 1-2 次",
                next_action=f"web_search(「{concept}」 含义/背景)",
                status="candidate" if nov >= 0.45 else "duplicate",
                epistemic=FACT))
    return out


def from_failed_searches(failed, existing_texts=(), now=None):
    """来源②：真实检索失败 → reflection（修正产物：换查询策略）。"""
    now = now or time.time()
    out = []
    for f in failed:
        concept = f.get("concept") or ""
        if not concept:
            continue
        out.append(ProductV32(
            product_type="reflection",
            content=f"对「{concept}」的检索失败（{f.get('evidence','')[:50]}）。"
                    f"原始查询把整个生造词当作关键词——修正策略：拆分词素、"
                    f"检索相邻概念或向用户确认来源。",
            source_refs=[f"chat_log:{f.get('evidence','')[:40]}"],
            evidence_summary=f"系统真实检索自述失败：{f.get('evidence','')[:60]}",
            confidence=0.8, novelty=_novelty_vs(f"反思{concept}",
                                                existing_texts),
            potential_value="失败原因指向查询构造问题，修正后可能产出结果",
            estimated_cost="web_search 1 次（改写查询）",
            next_action=f"改写查询：拆分「{concept}」词素或检索相近概念",
            status="candidate", epistemic=FACT))
    return out


def from_graph_relations(user_concepts, kg_nodes, existing_texts=(), now=None):
    """来源③：用户概念 × 已有记忆的共现 → relation_finding（epistemic=
    hypothesis：共现是事实，"值得验证的联系"是推断）。"""
    now = now or time.time()
    out = []
    for concept in user_concepts:
        related = []
        for n in kg_nodes:
            nid = str(n.get("id") or "")
            label = str(n.get("label") or "")
            ea = n.get("extra_attrs") or {}
            if nid.startswith(("用户近况", "思考_", "探针", "噪声", "CI_")):
                continue
            blob = nid + str(ea.get("content") or "") + str(ea.get("text") or "")
            if concept[:2] in blob or any(
                    w in blob for w in ("学习", "模组", "笔记")) and concept:
                related.append({"id": nid, "what": str(
                    ea.get("text") or ea.get("content") or nid)[:40]})
            if len(related) >= 2:
                break
        if related:
            out.append(ProductV32(
                product_type="relation_finding",
                content=f"用户概念「{concept}」与记忆中的 {[(r['id'], r['what']) for r in related]} "
                        f"存在潜在联系——值得验证是否同一话题。",
                source_refs=[f"graph:{r['id']}" for r in related],
                evidence_summary=f"图内共现：{len(related)} 个节点",
                confidence=0.4, novelty=_novelty_vs(f"关系{concept}",
                                                    existing_texts),
                potential_value="把用户困惑接到已有记忆上，可能形成跟进话题",
                estimated_cost="对话 1 轮",
                next_action=f"向用户确认「{concept}」与已有经历的关系",
                status="candidate", epistemic=HYPOTHESIS))
    return out


def from_thoughts(thought_nodes, existing_texts=(), now=None):
    """来源④：自由思考节点 → introspection（如实，不产任务）。"""
    now = now or time.time()
    out = []
    for n in thought_nodes:
        ea = n.get("extra_attrs") or {}
        content = str(ea.get("content") or "").strip()
        if content:
            out.append(ProductV32(
                product_type="introspection", content=content[:200],
                source_refs=[f"graph:{n.get('id')}"],
                evidence_summary="自我认知状态的 LLM 独白（无外部证据）",
                confidence=0.3, novelty=_novelty_vs(content, existing_texts),
                potential_value="低——除非能导出具体问题",
                estimated_cost="—",
                next_action="",
                status="background", epistemic=INFERENCE))
    return out


def filter_actionable(products, min_confidence=0.6, min_novelty=0.45):
    """任务资格筛选（任务质量与执行能力分离的第一道门）。"""
    ok, rejected = [], []
    for p in products:
        if p.product_type in ("open_question", "user_lead") and \
                p.confidence >= min_confidence and p.novelty >= min_novelty \
                and p.next_action:
            ok.append(p)
        else:
            rejected.append({"pid": p.pid, "type": p.product_type,
                             "why": f"conf={p.confidence} nov={p.novelty} "
                                    f"next={p.next_action or '无'}"})
    return ok, rejected
