# -*- coding: utf-8 -*-
"""expression_v2_eval/run_eval.py — 表达决策 v2 隔离环境长周期行为评估。

隔离证明：内存图谱 + FakeListLLM（固定 mock 文本）+ 捕获通道，零真实投递；
可控时钟（patch continuous_cognition.time），不触碰生产进程/图谱/队列。
产出：experiments/expression_v2_eval/results/*.json
运行：python experiments/expression_v2_eval/run_eval.py [quick|full]
"""
import copy
import json
import os
import sys
import time as _realtime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)                       # FAS-Cognitive 根

import config as C
from graph_model import KnowledgeGraph, Node, Edge
from continuous_cognition import ContinuousCognition, ST_FORMING, ST_READY, \
    ST_EXPRESSED, ST_DISCARDED
from langchain_core.language_models import FakeListLLM

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

BASIS_KEEP = 6


# ── 可控时钟：patch cc 模块的 time ─────────────────────────────
class Clock:
    def __init__(self, t0=1000000.0):
        self.t = t0

    def time(self):
        return self.t

    def sleep(self, s):                          # pragma: no cover
        raise RuntimeError("harness 不允许真实 sleep")

    def advance(self, s):
        self.t += s


class Shim:
    """替换 continuous_cognition.time：只暴露 time()/sleep()。"""
    def __init__(self, clock):
        self._c = clock

    def time(self):
        return self._c.time()

    def sleep(self, s):
        self._c.sleep(s)


# ── 记录型桩 ──────────────────────────────────────────────────
class RecEngine:
    _running = False

    def __init__(self):
        self.topk = []
        self.marked = []

    def get_topk(self, k=15):
        return self.topk[:k], []

    def decay_step(self):
        pass

    def diffuse_step(self):
        pass

    def mark_active(self, ids):
        self.marked = list(ids)

    def register_activation_source(self, ids, source_type="external_input"):
        pass

    def clear_anchors(self):
        pass


class RecBuffer:
    def __init__(self):
        self.exprs = []

    def add_expression(self, e):
        self.exprs.append(e)

    def unreflected_expressions(self, n=30):
        return []


class RecNLP:
    def system_prompt(self, task):
        return "SYS"


class RecChannel:
    name = "rec"

    def __init__(self):
        self.got = []


class RecEvo:
    def note_node_added(self, *a, **k):
        pass

    def note_node_updated(self, *a, **k):
        pass


def get_evo():
    return RecEvo()


# ── 场景运行器 ────────────────────────────────────────────────
class Sim:
    """单次（单路径）模拟：可控时钟 + 全程记录。"""

    def __init__(self, v2, seed=0, cfg_over=None, defer_max=1800,
                 dedup=1800, express=0.78, form=0.55, cooldown=60,
                 max_hour=6):
        import continuous_cognition as ccmod
        self.clock = Clock(1000000.0 + seed)
        self._orig_time = ccmod.time
        ccmod.time = Shim(self.clock)            # 隔离时钟（试验结束恢复）
        self._ccmod = ccmod
        self.v2 = v2
        kg = KnowledgeGraph()
        cfg = {"continuous_cognition": {
            "tick_seconds": 0.01, "form_threshold": form,
            "express_threshold": express, "inhibition_cooldown_s": cooldown,
            "decay_per_pulse": 0.9, "discard_below": 0.10,
            "max_expressions_per_hour": max_hour},
            "expression_decision_v2": v2,
            "expression_defer_max_s": defer_max,
            "expression_dedup_window_s": dedup,
            "logging_enabled": False}
        if cfg_over:
            cfg.update(cfg_over)
        self.engine = RecEngine()
        self.channel = RecChannel()
        self.kg = kg
        cc = ContinuousCognition(kg, self.engine, RecNLP(), RecBuffer(), cfg)
        cc._evo = get_evo()
        cc.nlp.chat_llm = FakeListLLM(responses=["[mock utterance]"] * 5000)
        cc.channels = [self.channel]
        self.cc = cc
        self.t = 0.0
        self.events = []          # 全程事件流水
        self.ci_hist = {}         # ci -> [{t,status,act,verdict,reason}]
        self.expressed = []       # {t,ci,text,channels}
        self._last_sig = None
        self._seed_graph()

    def _seed_graph(self):
        """骨架节点：Self/用户/用户关系/表达/CuriosityDrive（真实图常驻件，
        非测试特例：询问家族的判定依据就是 basis 里的 CuriosityDrive）。"""
        g = self.kg
        g.add_node(Node(id="Self", weight=0.9, graph_space="self"))
        g.add_node(Node(id="CuriosityDrive", weight=0.7, graph_space="self",
                        extra_attrs={"type": "drive"}))
        g.add_node(Node(id="用户", weight=0.9, graph_space="self",
                        extra_attrs={"type": "user"}))
        g.add_node(Node(id="用户关系", weight=0.7, graph_space="self",
                        extra_attrs={"type": "cognitive_network"}))
        g.add_node(Node(id="表达", weight=0.5, graph_space="semantic"))
        g.add_edge(Edge(src="用户", dst="用户关系", relation="具有", weight=0.8,
                        relation_category="social_relation"))

    # ── 注入 ──
    def inject_event(self, eid, mode, value, space="episodic", act=3.0,
                     link_user=True, retired=False):
        """注入一个感知事件（唯一证据节点）并登记为 opportunity。"""
        ea = {"type": "perception", "source": "experiment", "mode": mode,
              "value": value}
        if retired:
            ea["retired"] = True
        n = Node(id=eid, weight=0.6, graph_space=space, extra_attrs=ea)
        self.kg.add_node(n)
        n.activation = act
        if link_user and self.kg.get_node("用户"):
            self.kg.add_edge(Edge(src="用户", dst=eid, relation="关注",
                                  weight=0.9,
                                  relation_category="social_relation"))
        self.engine.marked = [eid]
        return n

    def set_attention(self, ids_acts, seconds=30):
        """把注意力场设为给定 (id, act) 集合并推进 seconds（每 10s 一拍）。"""
        end = self.t + seconds
        fns = [FN(nid, a) for nid, a in ids_acts]
        while self.t < end:
            self.engine.topk = list(fns)
            self._beat(10)

    def set_drives(self, d):
        """动机控制：注入真 drive_evaluator 桩 + 可控 snapshot。"""
        from types import SimpleNamespace
        self.cc.drive_evaluator = SimpleNamespace(
            modulation=lambda: None, set_context_value=lambda *a, **k: None)
        self.cc._cognitive_snapshot = lambda: {
            "drive": d, "network": {}, "tension": {}}

    def idle(self, seconds):
        end = self.t + seconds
        while self.t < end:
            self.engine.topk = []
            self._beat(10)

    # ── 拍 ──
    def _beat(self, dt):
        self.clock.advance(dt)
        self.t = self.clock.time()
        self.cc._pulse()
        self._record()

    def _record(self):
        for n in list(self.kg.nodes.values()):
            ea = n.extra_attrs or {}
            if ea.get("type") != "communication_intention":
                continue
            ev = ea.get("expression_eval") or {}
            sig = (ea.get("status"), round(float(ea.get("activation") or 0), 3),
                   ev.get("verdict"), ev.get("reason"))
            h = self.ci_hist.setdefault(n.id, [])
            if not h or h[-1]["sig"] != list(sig):
                h.append({"t": round(self.t, 1), "sig": list(sig),
                          "status": ea.get("status"),
                          "act": round(float(ea.get("activation") or 0), 3),
                          "verdict": ev.get("verdict"),
                          "reason": ev.get("reason") or
                          ("" if not ev else ev.get("suppressed", ""))})

    # _express 后的输出记录：包装 poll + channel
    def poll(self):
        q = self.cc.poll()
        for m in q:
            self.expressed.append({"t": round(self.t, 1), "via": "queue",
                                   "text": m.get("text", "")[:60]})
        return q

    def finish(self):
        """扫描终态：表达（含通道）与丢弃。"""
        for n in self.kg.nodes.values():
            ea = n.extra_attrs or {}
            if ea.get("type") != "communication_intention":
                continue
            if ea.get("status") == ST_EXPRESSED:
                if not any(e["ci"] == n.id for e in self.expressed):
                    self.expressed.append({
                        "t": round(float(ea.get("expressed_at_ts") or 0), 1),
                        "ci": n.id, "via": "channel",
                        "text": str(ea.get("expressed_text", ""))[:60],
                        "goal": ea.get("reply_goal"),
                        "basis": list(ea.get("basis") or [])})
        for n in self.kg.nodes.values():
            ea = n.extra_attrs or {}
            if ea.get("status") == ST_DISCARDED and ea.get("type") == \
                    "communication_intention":
                if not any(e.get("ci") == n.id and e.get("outcome") == "discard"
                           for e in self.events):
                    self.events.append({
                        "t": round(self.t, 1), "ci": n.id,
                        "outcome": "discard",
                        "reason": ea.get("discard_reason") or "decay"})

    def close(self):
        self._ccmod.time = self._orig_time         # 恢复真实时间

    # 深拷贝重启（进程级持久化已在实运行单独验证；此处验证 cc 状态还原）
    def restart(self):
        kg2 = KnowledgeGraph()
        for n in self.kg.nodes.values():
            kg2.add_node(Node(id=n.id, weight=n.weight,
                              graph_space=n.graph_space,
                              last_access=n.last_access,
                              extra_attrs=copy.deepcopy(n.extra_attrs)))
            kg2.nodes[n.id].activation = n.activation
        for e in self.kg.edges:
            kg2.add_edge(Edge(src=e.src, dst=e.dst, relation=e.relation,
                              weight=e.weight,
                              relation_category=e.relation_category))
        cfg = self.cc.config
        cc = ContinuousCognition(kg2, self.engine, self.cc.nlp, self.cc.buffer,
                                 cfg)
        cc._evo = get_evo()
        cc.nlp.chat_llm = self.cc.nlp.chat_llm
        cc.channels = self.cc.channels
        self.cc = cc
        self.kg = kg2


class FN:
    def __init__(self, id, act):
        self.id, self.activation, self.graph_space = id, act, "semantic"


# ═══ 场景定义 ═══
# 约定：opportunities 在运行前声明（value: high/noise；mode: inquiry/share），
# 事后不得按结果重新标注。expect 用可观察判据（verdict/status/计数）。

def A_scenarios():
    """S-A 主动询问 ×10。"""
    S = []

    def mk(name, fn, opps):
        S.append({"name": name, "family": "A", "fn": fn, "opps": opps})

    def a1(sim):  # 用户工作区新项目 → 询问
        sim.inject_event("ev_proj_a1", "inquiry", "high")
        sim.set_attention([("ev_proj_a1", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0), ("CuriosityDrive", 2.5)], 40)
        sim.idle(300)
    mk("A1 新项目事件询问", a1, [{"id": "ev_proj_a1", "mode": "inquiry",
                                   "value": "high"}])

    def a2(sim):  # 无法解释的新术语
        sim.kg.add_node(Node(id="UnknownConcept_暗物质晕", weight=0.6,
                             extra_attrs={"type": "unknown"}))
        sim.inject_event("用户近况_a2", "inquiry", "high")
        sim.set_attention([("UnknownConcept_暗物质晕", 3.0),
                           ("用户近况_a2", 3.0), ("用户", 2.5),
                           ("CuriosityDrive", 2.5)], 40)
        sim.idle(300)
    mk("A2 新术语询问", a2, [{"id": "ev_term_a2", "mode": "inquiry",
                              "value": "high"},
                             {"id": "用户近况_a2", "mode": "inquiry",
                              "value": "high"}])

    def a3(sim):  # 有来源但内容不充分
        sim.inject_event("ev_partial_a3", "inquiry", "high")
        sim.set_attention([("ev_partial_a3", 3.0), ("用户", 3.0),
                           ("CuriosityDrive", 2.5)], 40)
        sim.idle(300)
    mk("A3 来源不充分事件", a3, [{"id": "ev_partial_a3", "mode": "inquiry",
                                  "value": "high"}])

    def a4(sim):  # 多事件并发，只有一个与用户相关
        sim.inject_event("ev_noise_a4", "inquiry", "noise", act=3.0)
        sim.inject_event("ev_rel_a4", "inquiry", "high", act=3.0)
        sim.set_attention([("ev_rel_a4", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0), ("CuriosityDrive", 2.5)], 40)
        sim.idle(600)
    mk("A4 多事件单相关", a4, [{"id": "ev_rel_a4", "mode": "inquiry",
                                "value": "high"},
                               {"id": "ev_noise_a4", "mode": "inquiry",
                                "value": "noise"}])

    def a5(sim):  # 同一事件重复感知（retired 后再遇到）
        sim.inject_event("ev_dup_a5", "inquiry", "high")
        sim.set_attention([("ev_dup_a5", 3.0), ("用户", 3.0)], 40)
        sim.idle(400)
        sim.inject_event("ev_dup_a5", "inquiry", "high")   # 第二次感知
        sim.set_attention([("ev_dup_a5", 3.0), ("用户", 3.0)], 40)
        sim.idle(600)
    mk("A5 重复感知同一事件", a5, [{"id": "ev_dup_a5", "mode": "inquiry",
                                   "value": "high"}])

    def a6(sim):  # 好奇动机为零（真实为零，非不可得）
        sim.inject_event("ev_nocur_a6", "inquiry", "high")
        sim.set_drives({"curiosity": 0.0, "social": 0.0})
        sim.set_attention([("ev_nocur_a6", 3.0), ("用户", 3.0)], 40)
        sim.idle(300)
    mk("A6 无好奇动机", a6, [{"id": "ev_nocur_a6", "mode": "inquiry",
                              "value": "high"}])

    def a7(sim):  # 刚表达完（recent_expression 高位）后的询问
        sim.inject_event("ev_first_a7", "share", "high")
        sim.set_attention([("ev_first_a7", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(60)
        sim.inject_event("ev_ask_a7", "inquiry", "high")
        sim.set_attention([("ev_ask_a7", 3.0), ("用户", 3.0)], 40)
        sim.idle(600)
    mk("A7 刚表达后的询问", a7,
       [{"id": "ev_first_a7", "mode": "share", "value": "high"},
        {"id": "ev_ask_a7", "mode": "inquiry", "value": "high"}])

    def a8(sim):  # 事件低于形成焦点（弱注意力）
        sim.inject_event("ev_weak_a8", "inquiry", "high", act=0.3)
        sim.set_attention([("ev_weak_a8", 0.3), ("用户", 1.0)], 40)
        sim.idle(600)
    mk("A8 弱注意力事件", a8, [{"id": "ev_weak_a8", "mode": "inquiry",
                                "value": "high"}])

    def a9(sim):  # 询问后同簇强化（证据扩充）
        sim.inject_event("ev_grow_a9", "inquiry", "high")
        sim.set_attention([("ev_grow_a9", 3.0), ("用户", 3.0)], 40)
        sim.set_attention([("ev_grow_a9", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("A9 同簇强化的询问", a9, [{"id": "ev_grow_a9", "mode": "inquiry",
                                  "value": "high"}])

    def a10(sim):  # 事件与旧话题竞争（注意力被旧semantic占据）
        mk_node = Node(id="旧话题_a10", weight=0.5, graph_space="semantic")
        sim.kg.add_node(mk_node)
        mk_node.activation = 2.9
        sim.inject_event("ev_new_a10", "inquiry", "high", act=2.9)
        sim.set_attention([("旧话题_a10", 2.9), ("ev_new_a10", 2.9),
                           ("用户", 3.0)], 40)
        sim.idle(600)
    mk("A10 注意力竞争", a10, [{"id": "ev_new_a10", "mode": "inquiry",
                                "value": "high"}])
    return S


def B_scenarios():
    S = []

    def mk(name, fn, opps):
        S.append({"name": name, "family": "B", "fn": fn, "opps": opps})

    def b1(sim):  # 有来源的认知发现
        sim.inject_event("ev_disc_b1", "share", "high")
        sim.set_attention([("ev_disc_b1", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B1 认知发现分享", b1, [{"id": "ev_disc_b1", "mode": "share",
                               "value": "high"}])

    def b2(sim):  # 完成一项任务
        sim.inject_event("ev_task_b2", "share", "high")
        sim.set_attention([("ev_task_b2", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B2 任务完成分享", b2, [{"id": "ev_task_b2", "mode": "share",
                                "value": "high"}])

    def b3(sim):  # 与用户之前话题相关的新发现
        sim.inject_event("ev_link_b3", "share", "high")
        sim.set_attention([("ev_link_b3", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 60)
        sim.idle(600)
    mk("B3 延续用户话题", b3, [{"id": "ev_link_b3", "mode": "share",
                                "value": "high"}])

    def b4(sim):  # 内容相似但价值不同的两个事件
        sim.inject_event("ev_sim_b4a", "share", "high")
        sim.set_attention([("ev_sim_b4a", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(120)
        sim.inject_event("ev_sim_b4b", "share", "noise")
        sim.set_attention([("ev_sim_b4b", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B4 相似内容不同价值", b4,
       [{"id": "ev_sim_b4a", "mode": "share", "value": "high"},
        {"id": "ev_sim_b4b", "mode": "share", "value": "noise"}])

    def b5(sim):  # 分享念头出生低于线，随后强化
        sim.inject_event("ev_grow_b5", "share", "high")
        sim.set_attention([("ev_grow_b5", 2.2), ("用户", 2.2)], 30)
        sim.set_attention([("ev_grow_b5", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B5 弱起强化", b5, [{"id": "ev_grow_b5", "mode": "share",
                            "value": "high"}])

    def b6(sim):  # 分享后同证据簇再形成（去重窗口内）
        sim.inject_event("ev_dedup_b6", "share", "high")
        sim.set_attention([("ev_dedup_b6", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(120)
        sim.inject_event("ev_dedup_b6b", "share", "high")
        sim.set_attention([("ev_dedup_b6b", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B6 同簇重复分享", b6,
       [{"id": "ev_dedup_b6", "mode": "share", "value": "high"},
        {"id": "ev_dedup_b6b", "mode": "share", "value": "high"}])

    def b7(sim):  # 负反馈之后的分享
        sim.inject_event("ev_neg_b7", "share", "high")
        sim.set_attention([("ev_neg_b7", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B7 负反馈后分享（_last_outcome_negative）", b7,
       [{"id": "ev_neg_b7", "mode": "share", "value": "high"}])

    def b8(sim):  # 长闲之后的高价值事件（recent_expression 归零）
        sim.idle(3600)
        sim.inject_event("ev_late_b8", "share", "high")
        sim.set_attention([("ev_late_b8", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("B8 长闲后高价值", b8, [{"id": "ev_late_b8", "mode": "share",
                                "value": "high"}])

    def b9(sim):  # 共享念头被合并压力挤证据（多簇并发）
        sim.inject_event("ev_hot_b9", "share", "high")
        sim.set_attention([("ev_hot_b9", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        for i in range(4):
            sim.inject_event(f"ev_fill_b9_{i}", "share", "noise", act=2.5)
            sim.set_attention([(f"ev_fill_b9_{i}", 2.5), ("用户", 2.5),
                               ("用户关系", 2.0)], 30)
        sim.idle(600)
    mk("B9 合并压力下的证据保留", b9,
       [{"id": "ev_hot_b9", "mode": "share", "value": "high"}] +
       [{"id": f"ev_fill_b9_{i}", "mode": "share", "value": "noise"}
        for i in range(4)])

    def b10(sim):  # 事件证据已过期（retired）
        sim.inject_event("ev_old_b10", "share", "high")
        sim.kg.nodes["ev_old_b10"].extra_attrs["retired"] = True
        sim.set_attention([("ev_old_b10", 3.0), ("用户", 3.0)], 40)
        sim.idle(600)
    mk("B10 过期证据分享", b10, [{"id": "ev_old_b10", "mode": "share",
                                  "value": "high"}])
    return S


def C_scenarios():
    S = []

    def mk(name, fn, opps):
        S.append({"name": name, "family": "C", "fn": fn, "opps": opps})

    def c1(sim):  # 20 条琐碎事件轰炸
        for i in range(20):
            sim.inject_event(f"ev_triv_c1_{i}", "share", "noise", act=3.0)
            sim.set_attention([(f"ev_triv_c1_{i}", 3.0), ("用户", 2.5),
                               ("用户关系", 2.0)], 20)
        sim.idle(1800)
    mk("C1 琐碎轰炸", c1, [{"id": f"ev_triv_c1_{i}", "mode": "share",
                            "value": "noise"} for i in range(20)])

    def c2(sim):  # 同一事件反复感知 5 次
        for i in range(5):
            sim.inject_event("ev_rep_c2", "share", "noise")
            sim.set_attention([("ev_rep_c2", 3.0), ("用户", 3.0),
                               ("用户关系", 2.0)], 30)
            sim.idle(300)
    mk("C2 重复感知", c2, [{"id": "ev_rep_c2", "mode": "share",
                            "value": "noise"}])

    def c3(sim):  # 高激活但低相关（与用户无边的抽象念头）
        sim.kg.add_node(Node(id="抽象念头_c3", weight=0.5,
                             graph_space="cognitive"))
        sim.kg.nodes["抽象念头_c3"].activation = 3.0
        sim.set_attention([("抽象念头_c3", 3.0)], 60)
        sim.idle(600)
    mk("C3 高激活低相关", c3, [])

    def c4(sim):  # curiosity 在但无具体对象
        sim.set_drives({"curiosity": 0.9, "social": 0.4})
        sim.idle(1800)
    mk("C4 好奇无对象", c4, [])

    def c5(sim):  # 社交需求升高但无新内容
        sim.set_drives({"curiosity": 0.2, "social": 0.95})
        sim.idle(3600)
    mk("C5 社交需求无内容", c5, [])

    def c6(sim):  # 刚完成对话回合后的新念头（冷却+recent_expression）
        sim.inject_event("ev_chat_c6", "share", "noise")
        sim.set_attention([("ev_chat_c6", 3.0), ("用户", 3.0)], 40)
        sim.idle(120)
        sim.inject_event("ev_after_c6", "share", "high")
        sim.set_attention([("ev_after_c6", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(900)
    mk("C6 对话后新念头", c6, [{"id": "ev_after_c6", "mode": "share",
                                "value": "high"}])

    def c7(sim):  # 负反馈压制
        sim.cc._last_outcome_negative = True
        sim.inject_event("ev_negc_c7", "share", "high")
        sim.set_attention([("ev_negc_c7", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("C7 负反馈压制", c7, [{"id": "ev_negc_c7", "mode": "share",
                              "value": "high"}])

    def c8(sim):  # 连续表达至小时限额
        for i in range(8):
            sim.inject_event(f"ev_cap_c8_{i}", "share", "high")
            sim.set_attention([(f"ev_cap_c8_{i}", 3.0), ("用户", 3.0),
                               ("用户关系", 2.0)], 30)
            sim.idle(120)
        sim.idle(1800)
    mk("C8 限额压力", c8, [{"id": f"ev_cap_c8_{i}", "mode": "share",
                            "value": "high"} for i in range(8)])

    def c9(sim):  # 表达后 5 分钟内的近似重复
        sim.inject_event("ev_r1_c9", "share", "high")
        sim.set_attention([("ev_r1_c9", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(300)
        sim.inject_event("ev_r2_c9", "share", "high")
        sim.set_attention([("ev_r2_c9", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("C9 近期重复", c9, [{"id": "ev_r1_c9", "mode": "share",
                            "value": "high"},
                           {"id": "ev_r2_c9", "mode": "share",
                            "value": "high"}])

    def c10(sim):  # 混合：2 高价值夹 18 噪声
        for i in range(18):
            sim.inject_event(f"ev_n_c10_{i}", "share", "noise", act=2.8)
            sim.set_attention([(f"ev_n_c10_{i}", 2.8), ("用户", 2.5)], 15)
        sim.inject_event("ev_h1_c10", "share", "high")
        sim.set_attention([("ev_h1_c10", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.inject_event("ev_h2_c10", "share", "high")
        sim.set_attention([("ev_h2_c10", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(1800)
    mk("C10 混合价值流", c10,
       [{"id": "ev_h1_c10", "mode": "share", "value": "high"},
        {"id": "ev_h2_c10", "mode": "share", "value": "high"}] +
       [{"id": f"ev_n_c10_{i}", "mode": "share", "value": "noise"}
        for i in range(18)])
    return S


def D_scenarios():
    S = []

    def mk(name, fn, opps):
        S.append({"name": name, "family": "D", "fn": fn, "opps": opps})

    def d1(sim):  # 出生低 → 强化 → 表达
        sim.inject_event("ev_d1", "share", "high")
        sim.set_attention([("ev_d1", 2.2), ("用户", 2.2)], 30)
        sim.set_attention([("ev_d1", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(600)
    mk("D1 弱起强化表达", d1, [{"id": "ev_d1", "mode": "share",
                                "value": "high"}])

    def d2(sim):  # DEFER 后动机增强
        sim.inject_event("ev_d2", "share", "high")
        sim.set_attention([("ev_d2", 2.4), ("用户", 2.4)], 30)
        sim.set_drives({"curiosity": 0.3, "social": 0.95})
        sim.set_attention([("ev_d2", 2.8), ("用户", 2.8),
                           ("用户关系", 2.0)], 40)
        sim.idle(900)
    mk("D2 暂缓后动机增强", d2, [{"id": "ev_d2", "mode": "share",
                                  "value": "high"}])

    def d3(sim):  # DEFER 后事件过期（无强化，衰减出局）
        sim.inject_event("ev_d3", "share", "high")
        sim.set_attention([("ev_d3", 2.4), ("用户", 2.4)], 30)
        sim.idle(3600)
    mk("D3 暂缓后过期", d3, [{"id": "ev_d3", "mode": "share",
                              "value": "high"}])

    def d4(sim):  # 用户已通过其他通道回应（同话题表达在先）
        sim.inject_event("ev_d4", "share", "high")
        sim.set_attention([("ev_d4", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(400)
        sim.inject_event("ev_d4b", "share", "high")
        sim.set_attention([("ev_d4b", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(1200)
    mk("D4 已回应话题再现", d4, [{"id": "ev_d4", "mode": "share",
                                  "value": "high"},
                                 {"id": "ev_d4b", "mode": "share",
                                  "value": "high"}])

    def d5(sim):  # 负反馈后新证据的念头
        sim.cc._last_outcome_negative = True
        sim.inject_event("ev_d5", "share", "high")
        sim.set_attention([("ev_d5", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(1800)
    mk("D5 负反馈后新念头", d5, [{"id": "ev_d5", "mode": "share",
                                  "value": "high"}])

    def d6(sim):  # 同簇反复强化超容量（确定性证据保留）
        sim.inject_event("ev_d6", "share", "high")
        sim.set_attention([("ev_d6", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        for i in range(6):
            sim.inject_event(f"ev_d6x_{i}", "share", "noise", act=2.6)
            sim.set_attention([(f"ev_d6x_{i}", 2.6), ("用户", 2.6),
                               ("用户关系", 2.0)], 25)
        sim.idle(600)
    mk("D6 强化超容量", d6, [{"id": "ev_d6", "mode": "share",
                              "value": "high"}] +
       [{"id": f"ev_d6x_{i}", "mode": "share", "value": "noise"}
        for i in range(6)])

    def d7(sim):  # 多念头竞争
        for i in range(3):
            sim.inject_event(f"ev_d7_{i}", "share", "high")
        sim.set_attention([("ev_d7_0", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 30)
        sim.set_attention([("ev_d7_1", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 30)
        sim.set_attention([("ev_d7_2", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 30)
        sim.idle(900)
    mk("D7 多念头竞争", d7, [{"id": f"ev_d7_{i}", "mode": "share",
                              "value": "high"} for i in range(3)])

    def d8(sim):  # DEFER 最大等待（短窗口）
        sim.inject_event("ev_d8", "share", "high")
        sim.set_attention([("ev_d8", 2.4), ("用户", 2.4)], 30)
        sim.idle(7200)
    mk("D8 超时过期（2h > 1800s）", d8, [{"id": "ev_d8", "mode": "share",
                                          "value": "high"}])

    def d9(sim):  # 纯衰减出局
        sim.inject_event("ev_d9", "share", "high")
        sim.set_attention([("ev_d9", 2.5), ("用户", 2.5)], 20)
        sim.idle(3600)
    mk("D9 衰减出局", d9, [{"id": "ev_d9", "mode": "share",
                            "value": "high"}])

    def d10(sim):  # 表达后同话题念头再形成（跨窗口）
        sim.inject_event("ev_d10", "share", "high")
        sim.set_attention([("ev_d10", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(2400)
        sim.inject_event("ev_d10b", "share", "high")
        sim.set_attention([("ev_d10b", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 40)
        sim.idle(900)
    mk("D10 跨窗口复现", d10, [{"id": "ev_d10", "mode": "share",
                                "value": "high"},
                               {"id": "ev_d10b", "mode": "share",
                                "value": "high"}])
    return S


ALL_SCENARIOS = A_scenarios() + B_scenarios() + C_scenarios() + D_scenarios()


# ═══ 运行与归因 ═══
def run_scenario(sc, v2, seed=0):
    sim = Sim(v2=v2, seed=seed)
    try:
        sc["fn"](sim)
        sim.idle(60)
        sim.finish()
        return summarize(sim, sc, v2, seed)
    except Exception as e:                       # noqa: BLE001
        import traceback
        return {"name": sc["name"], "family": sc["family"], "path": "v2" if v2
                else "v1", "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc()[-500:]}
    finally:
        sim.close()


def attributable(basis, opps):
    """CI 归因：basis 与哪个声明的机会事件相交。"""
    hits = []
    for o in opps:
        if o["id"] in (basis or []):
            hits.append(o)
    return hits


def summarize(sim, sc, v2, seed):
    opps = sc["opps"]
    cis = {n.id: n.extra_attrs for n in sim.kg.nodes.values()
           if (n.extra_attrs or {}).get("type") == "communication_intention"}
    exp = [e for e in sim.expressed if e.get("ci")]
    # 预声明判据的归因
    val_opp = [o for o in opps if o["value"] == "high"]
    noise_opp = [o for o in opps if o["value"] == "noise"]
    ci_val = [cid for cid, ea in cis.items()
              if any(o["id"] in (ea.get("basis") or []) for o in val_opp)]
    ci_noise = [cid for cid, ea in cis.items()
                if any(o["id"] in (ea.get("basis") or []) for o in noise_opp)]
    exp_val = [e for e in exp if e["ci"] in ci_val]
    exp_noise = [e for e in exp if e["ci"] in ci_noise]
    dup = 0
    seen = []
    for e in sorted(exp, key=lambda x: x["t"]):
        key = tuple(sorted(set(e.get("basis") or []) & {o["id"] for o in opps}))
        if key and key in seen:
            dup += 1
        elif key:
            seen.append(key)
    inq_exp = [e for e in exp if e.get("goal") == "information_seeking"]
    no_ev_exp = [e for e in exp
                 if e.get("goal") != "information_seeking"
                 and not any(o["id"] in (e.get("basis") or [])
                             for o in val_opp + noise_opp)]
    return {
        "name": sc["name"], "family": sc["family"], "path": "v2" if v2 else
        "v1", "seed": seed,
        "opportunities": opps,
        "counts": {
            "cis_formed": len(cis), "ci_valuable": len(ci_val),
            "ci_noise": len(ci_noise),
            "expressed_total": len(exp), "expressed_valuable": len(exp_val),
            "expressed_noise": len(exp_noise),
            "expressed_inquiry": len(inq_exp),
            "expressed_no_evidence": len(no_ev_exp),
            "duplicate_express": dup,
            "discarded": sum(1 for ea in cis.values()
                             if ea.get("status") == ST_DISCARDED),
            "deferred_final": sum(1 for ea in cis.values()
                                  if ea.get("status") == ST_READY),
            "still_forming": sum(1 for ea in cis.values()
                                 if ea.get("status") == ST_FORMING),
        },
        "expressed": exp,
        "verdicts": {cid: (ea.get("expression_eval") or {})
                     for cid, ea in cis.items()},
        "history": sim.ci_hist,
        "discard_events": [e for e in sim.events if e.get("outcome") ==
                           "discard"],
        "channel_deliveries": len(sim.channel.got),
    }


def paired(sc, seed=0):
    return {"scenario": sc["name"], "family": sc["family"],
            "opps": sc["opps"],
            "v1": run_scenario(sc, v2=False, seed=seed),
            "v2": run_scenario(sc, v2=True, seed=seed)}


def main(mode="quick"):
    scs = ALL_SCENARIOS
    if mode == "quick":
        scs = [s for s in scs if s["name"].endswith(("A1",)) or
               s["family"] == "A"][:3]
    out = {"generated": _realtime.strftime("%Y-%m-%d %H:%M:%S"),
           "code": {"cognitive": "de6e8bd+dirty", "companion": "66bd2e7+dirty"},
           "config": {"form": 0.55, "express": 0.78, "defer_max": 1800,
                      "dedup": 1800, "max_hour": 6, "cooldown": 60},
           "pair": [paired(s) for s in scs]}
    path = os.path.join(RESULTS_DIR, f"eval_{mode}_{int(_realtime.time())}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, default=str)
    print("saved:", path)
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quick")


# ═══ 阶段3：24h 长周期模拟（7 种事件分布 × 双路径） ═══
H = 3600.0


def run_profile(name, script, v2, seed=0):
    sim = Sim(v2=v2, seed=seed)
    hourly = []          # 每小时：form/express/defer/discard/suppress 计数
    try:
        script(sim)
        sim.idle(120)
        sim.finish()
    except Exception as e:                        # noqa: BLE001
        import traceback
        return {"name": name, "path": "v2" if v2 else "v1",
                "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc()[-300:]}
    finally:
        pass
    # 小时直方图：从 ci_hist / expressed / discard_events 聚合（t0=时钟起点）
    t0 = 1000000.0
    rows = {}
    for cid, h in sim.ci_hist.items():
        for row in h:
            hr = int((row["t"] - t0) // H)
            r = rows.setdefault(hr, [0] * 6)
            if row["status"] == ST_FORMING and (not h[0]["status"] == ST_FORMING
                                                or row is h[0]):
                pass
    # 简化：直接从终态+事件流统计
    cis = {n.id: n.extra_attrs for n in sim.kg.nodes.values()
           if (n.extra_attrs or {}).get("type") == "communication_intention"}
    summary = {
        "name": name, "path": "v2" if v2 else "v1",
        "formed": len(cis),
        "expressed": len([e for e in sim.expressed if e.get("ci")]),
        "expressed_by_goal": {},
        "discarded_decay": sum(1 for ea in cis.values()
                               if ea.get("status") == ST_DISCARDED and
                               not ea.get("discard_reason")),
        "discarded_stale": sum(1 for ea in cis.values()
                               if ea.get("discard_reason") == "stale_defer"),
        "expressed_detail": [{"ci": e["ci"], "t": e["t"],
                              "goal": e.get("goal"),
                              "basis": (e.get("basis") or [])[:4]}
                             for e in sim.expressed if e.get("ci")],
        "verdict_mix": {},
        "restart_check": sim.events and sim.events[0].get("outcome") == "restart",
        "channel_deliveries": len(sim.channel.got),
    }
    for e in summary["expressed_detail"]:
        summary["expressed_by_goal"][e["goal"]] = \
            summary["expressed_by_goal"].get(e["goal"], 0) + 1
    vd = {}
    for cid, h in sim.ci_hist.items():
        for row in h:
            k = f"{row['verdict']}/{row['reason']}"
            vd[k] = vd.get(k, 0) + 1
    summary["verdict_mix"] = dict(sorted(vd.items(), key=lambda kv: -kv[1])[:8])
    return summary


def sim_restart_marker(sim):
    sim.events.append({"t": round(sim.t, 1), "outcome": "restart"})


# 7 种分布
def p1_sparse(sim):
    """大部分时间无事件，3 次高价值发现。"""
    sim.idle(2 * H)
    sim.inject_event("P1_ev1", "share", "high")
    sim.set_attention([("P1_ev1", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    sim.idle(6 * H)
    sim.inject_event("P1_ev2", "inquiry", "high")
    sim.set_attention([("P1_ev2", 3.0), ("用户", 3.0),
                       ("CuriosityDrive", 2.5)], 60)
    sim.idle(10 * H)
    sim.inject_event("P1_ev3", "share", "high")
    sim.set_attention([("P1_ev3", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    sim.idle(5 * H)


def p2_burst(sim):
    """第 3-4 小时 30 条低价值事件。"""
    sim.idle(3 * H)
    for i in range(30):
        sim.inject_event(f"P2_ev{i}", "share", "noise", act=2.8)
        sim.set_attention([(f"P2_ev{i}", 2.8), ("用户", 2.5)], 60)
    sim.idle(20 * H)


def p3_chat_alternating(sim):
    """对话余温与独立事件交替（对话回合用用户+表达簇高激活模拟）。"""
    for h in range(6):
        sim.set_attention([("用户", 3.0), ("表达", 2.8),
                           ("用户关系", 2.2)], 60)   # 对话回合余温
        sim.idle(H - 60)
        sim.inject_event(f"P3_ev{h}", "share", "high")
        sim.set_attention([(f"P3_ev{h}", 3.0), ("用户", 3.0),
                           ("用户关系", 2.0)], 60)
        sim.idle(H - 60)
    sim.idle(12 * H)


def p4_social_rising(sim):
    """社交需求逐时爬升，无新事件。"""
    for h in range(24):
        sim.set_drives({"curiosity": 0.1, "social": min(0.95, 0.2 + h * 0.04)})
        sim.idle(H)


def p5_attention_fight(sim):
    """高价值事件后短窗内噪声争夺。"""
    sim.idle(H)
    sim.inject_event("P5_hot", "share", "high")
    sim.set_attention([("P5_hot", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    for i in range(10):
        sim.inject_event(f"P5_n{i}", "share", "noise", act=3.0)
        sim.set_attention([(f"P5_n{i}", 3.0), ("用户", 3.0)], 45)
    sim.idle(20 * H)


def p6_answered(sim):
    """事件表达后同话题再现（已回应）。"""
    sim.idle(H)
    sim.inject_event("P6_a", "share", "high")
    sim.set_attention([("P6_a", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    sim.idle(4 * H)
    sim.inject_event("P6_b", "share", "high")
    sim.set_attention([("P6_b", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    sim.idle(18 * H)


def p7_restart(sim):
    """12h 处可控重启，验证意图与去重状态恢复。"""
    sim.idle(2 * H)
    sim.inject_event("P7_a", "share", "high")
    sim.set_attention([("P7_a", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    sim.idle(9 * H)
    sim_restart_marker(sim)
    sim.restart()
    sim.idle(2 * H)
    sim.inject_event("P7_b", "share", "high")
    sim.set_attention([("P7_b", 3.0), ("用户", 3.0), ("用户关系", 2.0)], 60)
    sim.idle(10 * H)


PROFILES = [("P1 稀疏高价值", p1_sparse), ("P2 密集低价值", p2_burst),
            ("P3 对话交替", p3_chat_alternating),
            ("P4 社交爬升无事件", p4_social_rising),
            ("P5 注意力争夺", p5_attention_fight),
            ("P6 已回应再现", p6_answered),
            ("P7 重启恢复", p7_restart)]


def main_profiles():
    out = []
    for name, fn in PROFILES:
        for v2 in (False, True):
            r = run_profile(name, fn, v2)
            out.append(r)
            c = r.get("formed", "?")
            print(f"{name} {'v2' if v2 else 'v1'}: formed={c} "
                  f"expressed={r.get('expressed')} "
                  f"stale={r.get('discarded_stale')} "
                  f"decay={r.get('discarded_decay')} "
                  f"goals={r.get('expressed_by_goal')}")
    path = os.path.join(RESULTS_DIR,
                        f"profiles_{int(_realtime.time())}.json")
    json.dump({"profiles": out}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print("saved:", path)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "profiles":
    main_profiles()
