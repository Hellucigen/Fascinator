# -*- coding: utf-8 -*-
"""sts2_sim.brain — 游戏决策的"外挂适配层"（2026-10-15）。

分层纪律（任务书 §六）：
  · 通用决策机制 = 候选打分竞争（本文件）；游戏规则 = 数据表 + 经验统计。
  · knowledge：威胁-应对卡标签的关系先验（**这是领域适配数据，不是硬编码
    决策链**——一张表，卡片和威胁都只经由标签(tag)进入打分）。
  · experience：跨局统计（每局面签名×每张卡的平均血量净变化），由
    play_sts2_sim.py 落盘。冷启动=0，随对局自然生长；经验权重设上限，
    不让小样本统计压过结构知识（防过拟合早期运气）。
  · 决策=对 actions() 给的合法动作打分取最优——天然不产生非法动作，
    即便产生也会被 world.apply 拒绝（双层保险）。
"""
import json
import os

# 威胁标签 → 应对卡标签的先验匹配（+合作 / -无效）
KNOWLEDGE = {
    # 16:5x 死因修正：旧先验"挨打=缩盾"（防御1.2>攻击0.5）在纯图模式下
    # 放大成永不误伤源头——尖塔真实解法是击杀即防御，威胁存续回合越久
    # 总伤越大。攻击/重击下伤害牌先验上调（数值为可解释初值，进化归边权）。
    "攻击":   {"防御": 1.0, "削弱": 0.5, "攻击": 1.0, "强化": 0.3},
    "重击":   {"防御": 1.4, "削弱": 0.6, "反击": 1.3, "攻击": 1.0},
    "防御":   {"攻击": 0.9, "重击": 1.2, "削弱": 0.4},
    "强化":   {"攻击": 1.0, "削弱": 1.4, "群体": 0.6},
    "群体":   {"防御": 1.5, "群体": 1.0},
}
EXP_CAP = 0.8          # 经验权重上限（每标签对）
EXP_SCALE = 0.05       # 统计量(平均血差)→分数的压缩系数


class Brain:
    def __init__(self, experience=None, kg=None, engine=None):
        self.exp = experience or {}
        # 图谱通道（2026-10-15 接大脑）：kg/engine 存在时，意图标签经
        # 真实扩散点亮相关卡——boost 只调"想得起想不起"，好坏仍归知识表
        # 与经验统计；无图谱时行为与纯表版完全一致（基线保持）。
        self.kg = kg
        self.engine = engine
        self._boost = {}
        self._gk = None              # 通用知识层（惰性导入）
        self.use_general = True      # 消融开关：False=不播种通用概念
        self.last_trace = None       # 阶段4：决策激活轨迹可追溯

    def score_action(self, act, snap):
        if act["id"] == "end_turn":
            # 留着能量只有当下回合还会再来收益——无强化牌可用时保守为 0.1
            return 0.10
        if act["id"].startswith("use_potion"):
            # 药水不耗能量不占出牌节奏：血线危机时高分，平时中分
            return 0.90 if snap["hp"] <= 30 else 0.30
        card = act.get("card")
        if not card:
            return 0.0
        tags = act.get("tags") or []
        threat = set()
        for e in snap["enemies"]:
            if e["hp"] > 0 and e.get("intent_tags"):
                threat.update(e["intent_tags"])
        know = 0.0
        for t in threat:
            row = KNOWLEDGE.get(t, {})
            for g in tags:
                know += row.get(g, 0.0)
        exp = 0.0
        sig = ",".join(sorted(threat)) or "无"
        e_row = self.exp.get(sig, {}).get(card)
        if e_row and e_row.get("plays", 0) >= 3:
            avg = e_row.get("hp_delta_sum", 0.0) / max(1, e_row["plays"])
            exp = max(-EXP_CAP, min(EXP_CAP, avg * EXP_SCALE))
        urgency = 0.0
        if snap["hp"] <= 20 and "防御" in tags:
            urgency = 1.0                       # 残血抓防御=通用生存先验
        cost_eff = -0.15 * (act.get("cost", 0) or 0)
        return know + exp + urgency + cost_eff

    def _choose_graph(self, actions, snap):
        """纯图决策模式（kg 在场时启用，2026-10-15 先验下图完成态）：
        KNOWLEDGE 表与 exp 统计**不参与打分**——先验与经验都已住进边权，
        决策=威胁点亮→沿"应对"边一跳扩散→卡节点激活竞争。
        保留的仅有两类非知识项：
          · 生存反射：残血时给"防御"标签额外注入能量（硬底线，可解释）；
          · 能量成本：end_turn 恒 0.05 底线分（费用守恒不靠图）。"""
        from sts2_sim import knowledge_graph as KG
        boost, seed_info = {}, None
        if self.kg is not None:
            # 双域播种（阶段3/4）：意图标签（游戏域）+ 情境命中的通用概念
            # （延迟收益/生存资源/威胁消除…）一起注能，一次扩散共同决定
            # 卡激活——通用知识经 gc→相关→标签→包含→卡 的长路参与排序。
            if self.use_general and self._gk is None:
                self._gk, _ = KG.import_general_knowledge(self.kg)
            snap2 = dict(snap, max_hp=getattr(self, "max_hp", 68))
            lit, used = KG.seed_situation(
                self.kg, self.engine, snap2,
                (self._gk or {}).get("triggers") or {}
                if self.use_general else {})
            raw = {}
            for c in snap.get("hand", []):
                n = self.kg.get_node(c)
                if n is not None and float(n.activation or 0) > 1e-4:
                    raw[c] = float(n.activation)
            for c, v in raw.items():
                boost[c] = round(min(0.5, v * 4.0), 3)
            seed_info = dict(seeds=lit, general=used)
            self.last_trace = {"seeds": lit, "general_concepts": used,
                               "boost": dict(boost)}
        # 能量成本与费用效率：成本模型不是领域知识，任何决策形态都要有
        # （17:2x 对照：表版靠 cost_eff 项存活，纯图版缺此项时高费牌
        # 过度出手）——激活相同量级时，省能量者微加分。
        energy = snap.get("energy", 3)
        best, bs = None, 0.02            # end_turn 底线分（留能量的价值）
        for a in actions:
            if a["id"] == "end_turn" or not a.get("card"):
                continue
            s_ = boost.get(a["card"], 0.0)
            if a.get("cost", 0) > energy:
                continue
            if a.get("cost", 0) > 0 and energy - a["cost"] < 0                     or snap.get("hp", 99) < 20 and "防御" not in (a.get("tags") or []):
                pass
            s_ += 0.02 * (0 if a.get("cost", 0) == 0 else 1)
            if s_ > bs:
                best, bs = a, s_
        return best

    def choose(self, actions, snap):
        """对合法动作打分取最优。空列表=None（无动作可做）。
        kg 在场 → 纯图通道；kg 缺席 → 表+统计基线（旧行为逐位保留）。"""
        if self.kg is not None:
            return self._choose_graph(actions, snap)
        if False and self.kg is not None:
            try:
                from sts2_sim import knowledge_graph as KG
                self._boost = KG.attention_boost(
                    self.kg, self.engine, snap)
            except Exception:                 # noqa: BLE001
                self._boost = {}
        else:
            self._boost = {}
        best, bs = None, 0.0
        for a in actions:
            s = self.score_action(a, snap)
            s += self._boost.get(a.get("card", ""), 0.0)
            if s > bs:
                best, bs = a, s
        return best

    def choose_reward(self, reward_cards, experience=None, snap=None):
        """奖励选卡：经验统计优先，其次先验（费用效率×攻击覆盖）。"""
        if not reward_cards:
            return None
        exp = experience or {}
        def score(c):
            plays = sum(row.get(c, {}).get("plays", 0)
                        for row in exp.values())
            delta = sum(row.get(c, {}).get("hp_delta_sum", 0.0)
                        for row in exp.values())
            prior = 1.0 if c in ("横扫", "顺手牵羊", "活动肌肉") else 0.0
            return delta / 100.0 + prior if plays else prior
        return max(reward_cards, key=score)

    def choose_route(self, route_actions, hp, max_hp=72, deck_n=None):
        """路线选择=风险管理：残血避精英求休整，满血敢打精英（遗物/药水
        期望值高）。宝藏永远优先（免费遗物零风险）。"""
        if not route_actions:
            return None
        ratio = hp / max(1, max_hp)
        def r_score(a):
            d = a["desc"]
            if d.startswith("宝藏"):
                return 3.0
            if d.startswith("精英"):
                # 17:0x 死因修正：首版"满血必挑精英"25 局死 24 局在精英层
                # ——精英奖励期望只在牌组成型后为正（deck≥13 且血线健康）
                if (deck_n or 0) >= 13 and ratio >= 0.7:
                    return 1.15
                return 0.25
            if d.startswith("休整"):
                return 2.2 * (1.0 - ratio)
            if d.startswith("首领"):
                return 0.9
            return 0.6
        return max(route_actions, key=r_score)


def load_experience(path=None):
    if not path:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "exp_stats.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
