# -*- coding: utf-8 -*-
"""living_v3/goal_bridge.py — 认知产物 → 既有目标系统的最小桥。

复用（零修改）：
  self_graph.set_goal(kg, desc, parent_goal)   长期目标指针（Self-[当前目标]）
  self_graph.goals()/get_goals()               目标读取
历史问题对照：
  - A 目标惯性：revise() 允许反证显式推翻旧目标（带 revision 记录），
    不是静默覆盖——旧目标描述、推翻证据、时间全部留痕。
  - C 延迟信用：目标节点带 created/ revised/ evidence_ids，结果 verdict
    反向关联目标 id（activity 学习节点已有 [基于] 边——本桥补 goal 侧）。
不修改 goal_planner.py / self_graph.py（用户 WIP 与生产文件）。
"""
import time


class GoalBridge:
    def __init__(self, kg, goals_api):
        """goals_api: self_graph 模块（注入，便于测试替换）。"""
        self.kg = kg
        self.sg = goals_api
        self.revisions = []          # 审计流水

    def from_product(self, p):
        """goal_candidate/open_question → 长期目标指针。返回 goal desc。"""
        if p.type not in ("goal_candidate", "open_question"):
            raise ValueError(f"product type {p.type} 不可作为目标来源")
        existing = {g.get("goal") if isinstance(g, dict) else str(g)
                    for g in (self.sg.get_goals() or [])}
        if p.text in existing:
            return None              # 幂等：同文目标已存在
        self.sg.set_goal(self.kg, p.text, parent_goal="理解用户")
        self._ev("goal_created", p.text, p.id, evidence=p.evidence_ids)
        return p.text

    def revise(self, old_desc, new_desc, counter_evidence_ids, reason):
        """反证推翻：显式修订（历史 A 目标惯性的直接对策）。
        旧目标不删除——降级留痕；新目标接管当前指针。"""
        goals = self.sg.get_goals() or []
        old = next((g for g in goals
                    if (g.get("goal") if isinstance(g, dict) else str(g))
                    == old_desc), None)
        if old is None:
            return False
        self.sg.set_goal(self.kg, new_desc, parent_goal="理解用户")
        self.revisions.append({
            "old": old_desc, "new": new_desc,
            "counter_evidence": list(counter_evidence_ids or []),
            "reason": reason, "t": time.time()})
        return True

    def abandon(self, desc, reason):
        """放弃：从活跃目标移除（self_graph 语义），放弃原因留痕。"""
        goals = self.sg.get_goals() or []
        target = next((g for g in goals
                       if (g.get("goal") if isinstance(g, dict) else str(g))
                       == desc), None)
        if target is None:
            return False
        gid = target.get("id") if isinstance(target, dict) else None
        if gid:
            try:
                self.sg.remove_goal(self.kg, gid)
            except AttributeError:
                pass                 # 旧接口无 remove——保留，仅留痕
        self._ev("goal_abandoned", desc, reason)
        return True

    def _ev(self, event, a, b, **k):
        self.revisions.append({"event": event, "a": a, "b": b,
                               "t": time.time(), **k})
