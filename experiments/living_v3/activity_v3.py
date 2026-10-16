# -*- coding: utf-8 -*-
"""living_v3/activity_v3.py — 统一自主活动循环 v3。

继承 autonomy_loop_v1.ActivityLoop（状态机/账本/预算/恢复全部复用），
增量：
  1. 候选来源接入统一认知产物（open_question/goal_candidate → 任务）
  2. goal_candidate 经 GoalBridge 写入既有目标系统（Self-[当前目标]）
  3. 分享候选登记前必须通过 SocialDecider（"值得打扰"判断落地）
  4. 学习节点带 goal 关联（延迟信用分配的追踪基础）
历史失败映射：
  - goal_path_bias 负效应（高激活被读成行动建议）→ v3 产物自带类型与
    verify_hint，下游按类型消费，不再从激活强度猜语义。
  - S5/S8 价值丢失 → SocialDecider 独立价值轴（不依赖显著性）。
"""
import time

import sys
import os as _os_mod
sys.path.insert(0, _os_mod.path.join(_os_mod.path.dirname(_os_mod.path.dirname(_os_mod.path.abspath(__file__))), "autonomy_loop_v1"))   # v1 循环复用（experiments/ 下）
from autonomy_loop import ActivityLoop, Toolbox, S_PROPOSED
from social_decider import SocialContext, decide_share


class ActivityLoopV3(ActivityLoop):
    def __init__(self, kg, ledger_path, toolbox, goals_api=None,
                 social_ctx=None, now=None, defer_ttl=6 * 3600):
        super().__init__(kg, ledger_path, toolbox, now=now, defer_ttl=defer_ttl)
        self.goals_api = goals_api            # self_graph 模块（可选）
        self.social_ctx = social_ctx or SocialContext(now=self._t())
        self.products = []                    # 本循环消费的认知产物留痕

    def ingest_products(self, products):
        """统一认知产物进入循环：open_question/goal_candidate 变成任务候选。"""
        self.products.extend(products)
        added = 0
        for p in products:
            if p.type not in ("open_question", "goal_candidate"):
                continue
            goal = f"搞清楚「{p.entities[0]}」" if p.entities and \
                p.type == "open_question" else p.text[:60]
            if self.ledger.dup_open(goal):
                self._ev("-", "propose_skip_duplicate", goal)
                continue
            tid = f"act_{abs(hash(p.id)) % 10**8:08x}"
            self.ledger.tasks[tid] = {
                "id": tid, "goal": goal, "state": S_PROPOSED,
                "source": f"product:{p.type}", "evidence_id":
                    (p.evidence_ids or [""])[0],
                "created": self._t(), "select_reason": "",
                "product_id": p.id}
            self._ev(tid, "proposed_from_product", p.type)
            added += 1
        # goal_candidate 同步进既有目标系统（GoalBridge）
        if self.goals_api is not None:
            from goal_bridge import GoalBridge
            bridge = GoalBridge(self.kg, self.goals_api)
            for p in products:
                if p.type == "goal_candidate":
                    bridge.from_product(p)
        self.ledger.save()
        return added

    def decide_share(self, product):
        """分享候选登记前过社交决策（v2 实验缺失项的落地）。"""
        d = decide_share(product, self.social_ctx)
        self._ev("-", f"social_{d.verdict}", f"{d.reason} nov={d.novelty:.2f}")
        return d

    def register_share(self, task, product=None):
        """SUCCESS 任务的分享候选——必须过 SocialDecider，不直接登记。"""
        text = f"自主活动发现：{task['goal']}（结果见 {task.get('learned_id')}）"
        prod = product
        if prod is None:
            from cognitive_product import CognitiveProduct
            prod = CognitiveProduct(
                type="social_material", text=text,
                evidence_ids=[task.get("evidence_id", "")],
                source="activity", confidence=0.6)
        d = self.decide_share(prod)
        if d.verdict == "share":
            if not any(c["goal"] == task["goal"]
                       for c in self.ledger.share_candidates):
                self.ledger.share_candidates.append({
                    "goal": task["goal"], "ci": task["id"],
                    "evidence": task.get("relevant_results", [])[:2],
                    "t": self._t(),
                    "social_reason": d.reason,
                    "note": "分享候选——交由现有表达机制评估，不直接发送"})
                self.ledger.save()
        return d
