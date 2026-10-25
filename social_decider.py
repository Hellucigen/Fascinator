# -*- coding: utf-8 -*-
"""social_decider.py — 社交参与决策器（生产模块，2026-10-11 提升）。

来源：experiments/living_v3/social_decider.py（v3 隔离验收 23 场景 +
v3.1 真实上下文影子评估：02:08 背景素材→silent、S5 线索→share 双向验证）。
自主生活循环（living_loop）的分享决策依赖本模块。

规则全部可解释；显著性不参与（它已在意图形成时消费）。
"""
import time
from dataclasses import dataclass, field

VERDICTS = ("share", "defer", "silent")


@dataclass
class SocialContext:
    user_recent_ts: float = 0.0      # 用户最近一次实际发言（0=未知）
    user_recent_text: str = ""       # 最近发言摘要（脱敏由调用方负责）
    conversation_open: bool = False  # 对话当前是否进行中
    recent_expressed: list = field(default_factory=list)  # 近期已表达文本
    recent_express_ts: float = 0.0   # 最近一次主动表达时间
    negative_feedback: bool = False  # 用户最近的纠正/抵触
    now: float = 0.0                 # 可控时钟


@dataclass
class ShareDecision:
    verdict: str
    reason: str
    cost: float = 0.0
    novelty: float = 0.0
    grounded: bool = True


def _novelty(product_text, ctx: SocialContext):
    """与近期已表达的重复度（子串级保守估计；1=全新）。"""
    best = 0.0
    probe = product_text[:60]
    for prev in ctx.recent_expressed or []:
        p = str(prev)[:60]
        if not p:
            continue
        overlap = len(set(probe) & set(p)) / max(len(set(probe) | set(p)), 1)
        best = max(best, overlap)
    return 1.0 - best


def decide_share(product, ctx: SocialContext, min_novelty=0.45) -> ShareDecision:
    """社交参与决策。product 需带 evidence_ids 与 type。
    规则（按序短路，每步留 reason）：
      1. 负反馈未消退 → silent（不叠加惩罚，只看标志位）
      2. 证据缺失 → silent（无据可依的素材不进入社交）
      3. 重复度高 → silent（最近说过实质相同内容）
      4. 打扰成本高（用户刚说话/对话进行中+非延续）→ defer
      5. 其余 → share（有证据、有新意、时机合适）"""
    now = ctx.now or time.time()
    text = str(product.text or "")
    cost = 0.0
    # 0. 素材类型/置信：背景观察（如静态清单快照）不是社交素材——
    #    02:08 真实案例逼出：有证据≠值得主动说，静态快照应保持安静
    if getattr(product, "type", "") == "observation" and             getattr(product, "confidence", 1.0) < 0.55:
        return ShareDecision("silent", "background_material_not_shareable",
                             cost)
    # 1. 负反馈
    if ctx.negative_feedback:
        return ShareDecision("silent", "negative_feedback_recent", cost)
    # 2. 证据
    if not (product.evidence_ids or []):
        return ShareDecision("silent", "no_evidence_grounding", cost)
    # 3. 重复
    nov = _novelty(text, ctx)
    if nov < min_novelty:
        return ShareDecision("silent",
                             f"low_novelty({nov:.2f}<{min_novelty})", cost)
    # 4. 打扰成本
    reasons = []
    if ctx.user_recent_ts and now - ctx.user_recent_ts < 600:
        cost += 0.3                       # 用户 10 分钟内说过话：刚互动过
        reasons.append("user_recent<600s")
    if ctx.conversation_open:
        cost += 0.3                       # 对话进行中
        reasons.append("conversation_open")
    if now - ctx.recent_express_ts < 1800 and ctx.recent_express_ts:
        cost += 0.2                       # 自己 30 分钟内已主动表达过
        reasons.append("self_express<1800s")
    if len(reasons) >= 2:
        return ShareDecision("defer", "high_disturbance_cost(" +
                             "+".join(reasons) + ")", cost, nov)
    # 5. 通过
    return ShareDecision("share",
                         "grounded+novel+timing_ok"
                         + (f"[cost:{'+'.join(reasons)}]" if reasons else ""),
                         cost, nov)
