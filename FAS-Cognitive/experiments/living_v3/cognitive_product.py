# -*- coding: utf-8 -*-
"""living_v3/cognitive_product.py — 统一认知产物（v3 架构核心数据模型）。

背景（证据链）：
  - 三轮实验证明自由思考产物是内省独白（02:08 报告/v1.1 端到端），
    无法转化为任务或表达（S5/S8 价值丢失）。
  - goal_path_bias FINAL_REPORT：高激活节点被序列化模板读成行动建议
    ——根因是产物无类型，下游只能瞎猜。

本模型把认知状态输出为**带类型、带证据、带验证方式**的结构化产物。
不是新的知识图谱——产物的证据仍以节点 id 挂在现有图上。

类型（开放集合，非固定话术）：
  introspection     内省：我在关注什么、为什么
  observation       观察：发生了什么，证据是什么
  open_question     未解决问题：什么还不知道
  hypothesis        假设：可能是什么，支持/反对证据
  relation_finding  关系发现：几个记忆/概念之间可能的联系
  goal_candidate    目标候选：什么值得继续弄清楚或完成
  revision          修订意见：为什么旧目标不再合适
  social_material   社交素材：什么值得与用户分享（共同经历/话题/发现）
  no_action         无行动结论：当前没有值得继续做的事
"""
import time
import uuid
from dataclasses import dataclass, field

TYPES = ("introspection", "observation", "open_question", "hypothesis",
         "relation_finding", "goal_candidate", "revision",
         "social_material", "no_action")


@dataclass
class CognitiveProduct:
    type: str                            # TYPES 之一
    text: str                            # 产物正文（人类可读）
    evidence_ids: list = field(default_factory=list)   # 图上证据节点 id
    entities: list = field(default_factory=list)       # 涉及实体/概念
    confidence: float = 0.5              # 0-1；证据在场性加权，非语义置信
    unresolved: str = ""                 # 尚未解决的部分
    verify_hint: str = ""                # 预期验证方式（检索/实验/询问用户）
    source: str = "unknown"              # 产物来源（free_thought/poller/…）
    source_node: str = ""                # 产生的图节点 id
    ts: float = field(default_factory=lambda: time.time())
    id: str = field(default_factory=lambda: f"cp_{uuid.uuid4().hex[:8]}")

    def __post_init__(self):
        if self.type not in TYPES:
            raise ValueError(f"unknown product type: {self.type}")

    def to_dict(self):
        d = self.__dict__.copy()
        return d


# ── 从真实图状态生成产物（只读输入；规则可解释，无 LLM） ──────────

def product_from_thought(node_id, content, ts=None):
    """自由思考节点 → introspection 产物（如实：内省不伪装成问题）。"""
    return CognitiveProduct(
        type="introspection", text=str(content)[:300],
        evidence_ids=[node_id], source="free_thought",
        source_node=node_id,
        confidence=0.4,                      # 内省无外部证据，置信上限低
        ts=ts if ts is not None else time.time())


def products_from_graph_state(kg_view, now=None):
    """从图状态视图（只读 dict 列表：{id, extra_attrs, graph_space,
    activation}）生成认知产物集合。规则全部可解释：
      ① 活未知标记 → open_question + goal_candidate（好奇引擎语义）
      ② 自由思考节点 → introspection
      ③ 新增背景资料（baseline 快照）→ observation（不是事件）
      ④ 无产物 → no_action 由调用方合成（空集本身合法）
    """
    now = now or time.time()
    out = []
    for n in kg_view:
        nid = str(n.get("id") or "")
        ea = n.get("extra_attrs") or {}
        act = float(n.get("activation") or 0)
        if nid.startswith("UnknownConcept_") and not ea.get("retired"):
            name = nid.split("_", 1)[-1]
            out.append(CognitiveProduct(
                type="open_question",
                text=f"「{name}」是什么？还没有任何图内证据解释它。",
                evidence_ids=[nid], entities=[name],
                confidence=0.7, unresolved=f"{name} 的定义与机制",
                verify_hint="web_search",
                source="unknown_marker", source_node=nid, ts=now))
            out.append(CognitiveProduct(
                type="goal_candidate",
                text=f"弄清楚「{name}」——它是用户工作中遇到的未知概念。",
                evidence_ids=[nid], entities=[name],
                confidence=0.6, unresolved="尚未检索任何资料",
                verify_hint="web_search 后以结果相关性验证",
                source="unknown_marker", source_node=nid, ts=now))
        elif ea.get("type") == "thought":
            content = str(ea.get("content") or "").strip()
            if content:
                p = product_from_thought(nid, content, ts=now)
                p.confidence = min(0.5, 0.3 + act / 10.0)
                out.append(p)
        elif (ea.get("type") == "perception"
              and ea.get("source") == "charon_workspace"
              and ea.get("baseline")):
            out.append(CognitiveProduct(
                type="observation",
                text=str(ea.get("text") or "")[:300],
                evidence_ids=[nid],
                confidence=0.5,
                unresolved="",
                verify_hint="无（背景资料，不触发行动）",
                source="charon_workspace", source_node=nid, ts=now))
    return out


def worth_goal(p: CognitiveProduct) -> bool:
    """产物 → 目标候选的最小资格规则（可解释；显著性不参与）。"""
    if p.type == "goal_candidate":
        return True
    if p.type == "open_question" and p.verify_hint == "web_search":
        return True
    return False
