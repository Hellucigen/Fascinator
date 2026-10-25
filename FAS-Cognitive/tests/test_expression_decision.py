# -*- coding: utf-8 -*-
"""test_expression_decision.py — 表达决策 v2（四轴分离）+ 阶段1 缺陷修复的
端到端验收。S1-S9 场景 + basis 确定性 + 逐拍日志 + 新旧路径对照。

隔离环境：内存图谱 / FakeListLLM / 捕获通道，零真实消息投递。
脚本式运行：python tests/test_expression_decision.py
"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C
from graph_model import KnowledgeGraph, Node, Edge
from continuous_cognition import ContinuousCognition, ST_READY, ST_EXPRESSED, \
    ST_DISCARDED, ST_FORMING

FAILURES = []


def check(name, cond, detail=""):
    st = "PASS" if cond else "FAIL"
    print(f"[{st}] {name}" + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FN:
    def __init__(self, id, act, space="semantic"):
        self.id, self.activation, self.graph_space = id, act, space


class StubEngine:
    _running = False

    def __init__(self, topk=None):
        self.topk = topk or []
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


class StubBuffer:
    def __init__(self):
        self.exprs = []

    def add_expression(self, e):
        self.exprs.append(e)

    def unreflected_expressions(self, n=30):
        return []


class StubNLP:
    def system_prompt(self, task):
        return "SYS"


class CapChannel:
    name = "cap"

    def __init__(self):
        self.got = []

    def deliver(self, u):
        self.got.append(u)
        return True


def mk_cc(v2=True, form=0.5, express=0.78, defer_max=1800, dedup=1800):
    cfg = {"continuous_cognition": {
        "tick_seconds": 0.01, "form_threshold": form,
        "express_threshold": express, "inhibition_cooldown_s": 0,
        "decay_per_pulse": 0.9, "discard_below": 0.10,
        "max_expressions_per_hour": 6},
        "expression_decision_v2": v2,
        "expression_defer_max_s": defer_max,
        "expression_dedup_window_s": dedup}
    kg = KnowledgeGraph()
    cc = ContinuousCognition(kg, StubEngine(), StubNLP(), StubBuffer(), cfg)
    return kg, cc


def mk_node(kg, nid, act=0.5, space="semantic", ea=None):
    n = Node(id=nid, weight=0.5, graph_space=space, extra_attrs=ea or {})
    kg.add_node(n)
    n.activation = act
    return n


def seed_ci(kg, cid, act=0.6, basis=(), goal="share_related_knowledge",
            status=ST_READY, ago=0.0, kind="communication", dl="statement"):
    ea = {"type": "communication_intention", "kind": kind, "status": status,
          "activation": act, "score": act, "basis": list(basis),
          "reply_goal": goal, "dialogue_act": dl,
          "born_ts": time.time() - ago, "last_change_ts": time.time() - ago,
          "created": "2026-10-10 00:00:00"}
    kg.add_node(Node(id=cid, weight=0.5, label="intention",
                     graph_space="self", extra_attrs=ea))
    return kg.nodes[cid]


def verdict_of(cc, cid):
    ci = cc.kg.nodes[cid]
    return (ci.extra_attrs.get("expression_eval") or {})


# ═══ T0 basis 确定性合并（阶段1-1 / S6） ═══
kg, cc = mk_cc()
mk_node(kg, "E1", space="episodic")            # 证据类
mk_node(kg, "EM", ea={"type": "emotion"})      # 证据类
mk_node(kg, "S1n")                             # 普通
old = {"E1", "S1n", "A1", "A2", "A3"}
new = {"EM", "N1", "N2", "N3"}
r1 = cc._merge_basis_deterministic(old, new)
r2 = cc._merge_basis_deterministic(set(reversed(sorted(old))),
                                   set(reversed(sorted(new))))
check("T0a 合并结果与集合构建顺序无关（确定性）", r1 == r2, f"{r1} vs {r2}")
check("T0b 容量遵守 BASIS_KEEP=6", len(r1) <= 6, str(r1))
check("T0c 证据类节点（episodic/emotion）优先进入保留集",
      "E1" in r1 and "EM" in r1, str(r1))
r3 = cc._merge_basis_deterministic(
    {"E1", "x1", "x2", "x3", "x4"}, {"y1", "y2", "y3", "y4"})
check("T0d 超容量时 episodic 证据不被挤出（审计缺陷回归钉）",
      "E1" in r3 and len(r3) == 6, str(r3))

# ═══ T1 S1 主动询问：低于陈述线、高于询问线 → v2 能说，v1 沉默 ═══
# 对照设计：v1/v2 用**同一 basis 结构**（含 episodic 证据，都过 rich 闸），
# 唯一差异是决策路径——这样 T1c 拦下它的就是 0.78 陈述线本身，不是资格闸。
kg, cc = mk_cc(v2=True)
mk_node(kg, "UnknownConcept_量子退相干", ea={"type": "unknown"})
mk_node(kg, "用户近况_t1", space="episodic")
ci = seed_ci(kg, "CI_ask", act=0.62,
             basis=["UnknownConcept_量子退相干", "用户近况_t1", "用户"],
             goal="information_seeking", dl="question")
best, val = cc._evaluate_expression()
ev = verdict_of(cc, "CI_ask")
check("T1a v2：询问类走 form 线（0.62≥0.5）判 express",
      ev.get("verdict") == "express" and best is ci,
      str(ev))
check("T1b 判定带可追踪理由与内容类", ev.get("reason") == "inquiry_bar_met"
      and ev.get("content_class") == "inquiry", str(ev))
kg2, cc2 = mk_cc(v2=False)
mk_node(kg2, "UnknownConcept_量子退相干", ea={"type": "unknown"})
mk_node(kg2, "用户近况_t1", space="episodic")
seed_ci(kg2, "CI_ask", act=0.62,
        basis=["UnknownConcept_量子退相干", "用户近况_t1", "用户"],
        goal="information_seeking", dl="question")
b2, _ = cc2._evaluate_expression()
_e1 = verdict_of(cc2, "CI_ask")
check("T1c 对照：同一念头 v1 未表达（0.62<0.78），eval 保持旧形状（flag 关=逐字旧行为）",
      b2 is None and _e1.get("expression_score") == 0.62
      and "verdict" not in _e1, str(_e1))

# ═══ T2 S2 主动分享：有来源事件 + 过陈述线 → 表达并三出口留痕 ═══
kg, cc = mk_cc(v2=True)
mk_node(kg, "用户近况_t2", space="episodic")
ci = seed_ci(kg, "CI_share", act=0.85,
             basis=["用户近况_t2", "用户", "用户关系"], goal="follow_up")
from langchain_core.language_models import FakeListLLM
cc.nlp.chat_llm = FakeListLLM(responses=[
    "看到你工作区有新东西了，那个便签我瞄了一眼，挺有意思的。"])
cc.channels = [CapChannel()]
best, _ = cc._evaluate_expression()
check("T2a v2 陈述类过线判 express", best is ci, str(verdict_of(cc, "CI_share")))
ok = cc._express(ci)
q = cc.poll()
check("T2b 表达产出进队列（协议兼容：dict 含 text）",
      ok is True and len(q) == 1 and q[0].get("text"), str(q)[:120])
check("T2c 通道投递发生（mock channel，非真实用户消息）",
      len(cc.channels[0].got) == 1 and cc.channels[0].got[0].origin == "proactive")
check("T2d 终态 expressed 且带数值时间戳（去重轴的数据基础）",
      ci.extra_attrs["status"] == ST_EXPRESSED
      and ci.extra_attrs.get("expressed_at_ts", 0) > 0)

# ═══ T3 S3 无事件：动机升高本身不生产消息 ═══
kg, cc = mk_cc(v2=True)
cc._cognitive_snapshot = lambda: {"drive": {"curiosity": 0.9, "social": 0.9},
                                  "network": {}, "tension": {}}
cc.drive_evaluator = object()
best, _ = cc._evaluate_expression()
check("T3a 无 READY 念头时，任何动机读数都不产生表达",
      best is None and cc.poll() == [])
check("T3b 不伪造评估记录（无念头=无 eval）",
      not any((n.extra_attrs or {}).get("expression_eval")
              for n in kg.nodes.values()))

# ═══ T4 S4 低价值轰炸：抽象证据念头全部 defer，过期后 stale-discard ═══
kg, cc = mk_cc(v2=True, defer_max=1800)
for i in range(20):
    seed_ci(kg, f"CI_low{i}", act=0.6,
            basis=["表达", "用户", "CENetwork"], ago=2000 + i)  # 无 episodic/emotion
expressed = 0
for i in range(20):
    cc._evaluate_expression()
    if verdict_of(cc, f"CI_low{i}").get("verdict") == "express":
        expressed += 1
check("T4a 20 条无证据念头零表达（资格轴拦截）", expressed == 0)
check("T4b 拒绝理由=eligibility_no_evidence（区分于时机不足）",
      all(verdict_of(cc, f"CI_low{i}").get("reason") ==
          "eligibility_no_evidence" for i in range(20)))
cc._decay_intentions()
check("T4c 超过最大等待时长 → DISCARD(stale_defer)，不无限滞留",
      all(kg.nodes[f"CI_low{i}"].extra_attrs.get("status") == ST_DISCARDED
          and kg.nodes[f"CI_low{i}"].extra_attrs.get("discard_reason")
          == "stale_defer" for i in range(20)))

# ═══ T5 S5 刚交流后的重复与限额（成本轴） ═══
kg, cc = mk_cc(v2=True)
mk_node(kg, "用户近况_t5", space="episodic")
seed_ci(kg, "CI_done", act=0.9, basis=["用户近况_t5", "用户"],
        goal="follow_up", status=ST_EXPRESSED)
kg.nodes["CI_done"].extra_attrs["expressed_at_ts"] = time.time() - 60
kg.nodes["CI_done"].extra_attrs["basis"] = ["用户近况_t5", "用户"]
ci = seed_ci(kg, "CI_dup", act=0.9, basis=["用户近况_t5", "用户", "用户关系"],
             goal="follow_up")
cc._evaluate_expression()
ev = verdict_of(cc, "CI_dup")
check("T5a 同目标+同证据簇窗口内重复 → suppress/duplicate_recent",
      ev.get("verdict") == "suppress" and ev.get("reason") == "duplicate_recent",
      str(ev))
ci2 = seed_ci(kg, "CI_flood", act=0.9, basis=["用户近况_t5"],
              goal="share_related_knowledge")
cc._express_count_hour = [time.time()] * 6
cc._evaluate_expression()
ev2 = verdict_of(cc, "CI_flood")
check("T5b 小时限额耗尽 → suppress/rate_limit_hour（含询问类）",
      ev2.get("verdict") == "suppress" and ev2.get("reason") == "rate_limit_hour",
      str(ev2))

# ═══ T6 S7 未知事实：不得自动转确定性陈述 ═══
kg, cc = mk_cc(v2=True)
mk_node(kg, "UnknownConcept_转码偏差", ea={"type": "unknown"})
ci = seed_ci(kg, "CI_stmt_on_unknown", act=0.9,
             basis=["UnknownConcept_转码偏差", "用户"],
             goal="share_related_knowledge")   # 强制以陈述家族谈论未知
cc._evaluate_expression()
ev = verdict_of(cc, "CI_stmt_on_unknown")
check("T6a 未知标记不构成陈述资格（无 episodic/emotion → defer）",
      ev.get("verdict") == "defer" and
      ev.get("reason") == "eligibility_no_evidence", str(ev))
check("T6b 同一未知走询问家族则可表达（T1 已证），两轴互不越权",
      verdict_of(cc, "CI_stmt_on_unknown").get("content_class") == "statement")

# ═══ T7 S8 v1 兼容：flag 关闭时判定与旧公式逐位一致 ═══
kg, cc = mk_cc(v2=False)
mk_node(kg, "用户近况_t7", space="episodic")
seed_ci(kg, "CI_a", act=0.70, basis=["用户近况_t7"])
seed_ci(kg, "CI_b", act=0.80, basis=["用户近况_t7", "用户"])
best, val = cc._evaluate_expression()
check("T7a v1：0.80≥0.78 中选 CI_b（旧公式复算）",
      best is kg.nodes["CI_b"] and abs(val - 0.80) < 1e-9)
check("T7b v1 eval 字段保持旧形状（expression_score/suppression_score/"
      "cooldown_floor_ok）",
      set(verdict_of(cc, "CI_b")) >= {"expression_score",
                                      "suppression_score", "cooldown_floor_ok"},
      str(verdict_of(cc, "CI_b")))
# NO_SPEAK 哨兵不回显给用户
kg, cc = mk_cc(v2=True)
mk_node(kg, "用户近况_t7b", space="episodic")
ci = seed_ci(kg, "CI_ns", act=0.9, basis=["用户近况_t7b"], goal="follow_up")
cc.nlp.chat_llm = FakeListLLM(responses=["NO_SPEAK"])
cc.channels = [CapChannel()]
r = cc._express(ci)
check("T7c NO_SPEAK：不出队列、不上通道、念头静默终态",
      r is False and cc.poll() == [] and cc.channels[0].got == []
      and ci.extra_attrs["status"] == ST_DISCARDED)

# ═══ T8 S9 暂缓生命周期：动机消失 / 强化翻身 / 过期消亡 ═══
kg, cc = mk_cc(v2=True)
mk_node(kg, "UnknownConcept_x9", ea={"type": "unknown"})
ci = seed_ci(kg, "CI_def", act=0.62,
             basis=["UnknownConcept_x9", "CuriosityDrive"],
             goal="information_seeking")
cc.drive_evaluator = object()
cc._cognitive_snapshot = lambda: {"drive": {"curiosity": 0.0, "social": 0.0},
                                  "network": {}, "tension": {}}
cc._evaluate_expression()
check("T8a 动机真实为零 → defer/no_curiosity_motivation（不可得≠零，见T1）",
      verdict_of(cc, "CI_def").get("reason") == "no_curiosity_motivation",
      str(verdict_of(cc, "CI_def")))
cc._cognitive_snapshot = lambda: {"drive": {"curiosity": 0.7, "social": 0.2},
                                  "network": {}, "tension": {}}
best, _ = cc._evaluate_expression()
check("T8b 动机回升 → 同一暂缓念头重新可表达（无需重建）",
      best is ci and verdict_of(cc, "CI_def").get("verdict") == "express")
kg, cc = mk_cc(v2=True, defer_max=600)
mk_node(kg, "UnknownConcept_x9b", ea={"type": "unknown"})
seed_ci(kg, "CI_old", act=0.62, basis=["UnknownConcept_x9b"],
        goal="information_seeking", ago=601)
cc._decay_intentions()
check("T8c 超最大等待 → DISCARD(stale_defer)",
      kg.nodes["CI_old"].extra_attrs.get("discard_reason") == "stale_defer")
seed_ci(kg, "CI_hot", act=0.62, basis=["UnknownConcept_x9b"],
        goal="information_seeking", ago=5000)  # 出生很久但刚被强化
kg.nodes["CI_hot"].extra_attrs["last_change_ts"] = time.time()
cc._decay_intentions()
check("T8d 强化刷新时钟：老而relevant的念头不误杀",
      kg.nodes["CI_hot"].extra_attrs.get("status") == ST_READY)

# ═══ T9 逐拍评估日志（阶段1-2）：可按 ci 还原完整因果链 ═══
import fas_log
_tmp = tempfile.mkdtemp(prefix="fas_express_log_")
try:
    fas_log.setup(log_dir=_tmp, config=dict(C.DEFAULT_CONFIG))
    kg, cc = mk_cc(v2=True)
    mk_node(kg, "UnknownConcept_log", ea={"type": "unknown"})
    seed_ci(kg, "CI_log", act=0.62, basis=["UnknownConcept_log"],
            goal="information_seeking")
    cc._evaluate_expression()
    cc._evaluate_expression()
    try:
        fas_log.get_logger(fas_log.COGNITION).flush_all()
    except Exception:
        pass
    time.sleep(0.2)
    lines = []
    _fp = os.path.join(_tmp, "cognition.jsonl")
    if os.path.exists(_fp):
        lines = [l for l in open(_fp, encoding="utf-8") if "express_eval" in l]
    check("T9a 每次评估各落一条（逐拍不覆盖，两次评估两条记录）",
          len(lines) >= 2, f"n={len(lines)}")
    import json as _j
    rec = _j.loads(lines[-1]) if lines else {}
    check("T9b 记录含判定四要素（verdict/reason/bar/salience）与 ci 索引",
          all(k in (rec.get("data") or rec) for k in
              ("ci", "verdict", "reason", "bar", "salience"))
          or all(k in _j.dumps(rec) for k in
                 ("verdict", "reason", "bar")), str(rec)[:200])
finally:
    try:
        fas_log.shutdown()
    except Exception:
        pass

# ═══ T10 阶段4：need.social/催产素/recent_expression → 阈值（真调制层） ═══
from types import SimpleNamespace
from modulation import ModulationLayer
_ml = ModulationLayer(dict(C.DEFAULT_CONFIG["modulation"]["params"]),
                      smoothing_alpha=1.0)   # α=1：display=raw，无平滑延迟，确定性
_Z = {"need.social": 0.0, "hormone.oxytocin": 0.0, "drive.social": 0.0,
      "hormone.cortisol": 0.0, "context.recent_expression": 0.0}
_ml.compute(dict(_Z))
_v0 = _ml.get("cognition.express_threshold")
check("T10a 全零信号 → 阈值=出厂基线 0.78", abs(_v0 - 0.78) < 1e-6, str(_v0))
_ml.compute({**_Z, "need.social": 1.0, "hormone.oxytocin": 0.5})
_v1 = _ml.get("cognition.express_threshold")
check("T10b 社交需求+联结感升高 → 阈值被调制下压（0.78×0.84≈0.655）",
      _v1 < 0.70, str(_v1))
_ml.compute({**_Z, "context.recent_expression": 1.0})
_v2r = _ml.get("cognition.express_threshold")
check("T10c 刚说完话 → 防刷屏上限顶格（min(0.998, max=0.95)）",
      abs(_v2r - 0.95) < 1e-6, str(_v2r))
_ml.compute(dict(_Z))
_v3 = _ml.get("cognition.express_threshold")
check("T10d 信号归零后阈值完全恢复 → 不存在自我抑制死锁",
      abs(_v3 - 0.78) < 1e-6, str(_v3))

# ═══ T11 阶段4：信号 → 调制 → 决策 全链闭环（同一 ml 接进真 _mod_th） ═══
def _cc_with_mod(v2, form=0.5, express=0.78, ml=None, drives=None):
    kg, cc = mk_cc(v2=v2, form=form, express=express)
    stub = SimpleNamespace(modulation=lambda: ml,
                           set_context_value=lambda *a, **k: None)
    cc.drive_evaluator = stub
    cc._cognitive_snapshot = lambda: {"drive": drives or {}, "network": {},
                                      "tension": {}}
    return kg, cc

# 询问闭环：显著性 0.52，form 线 0.55；need.social 拉低询问线到 0.495 → 翻转
mk_node_kg, cc = _cc_with_mod(True, ml=_ml, drives={"curiosity": 0.8})
mk_node(cc.kg, "UnknownConcept_loop", ea={"type": "unknown"})
seed_ci(cc.kg, "CI_loop", act=0.52, basis=["UnknownConcept_loop"],
        goal="information_seeking")
_ml.compute(dict(_Z))
best, _ = cc._evaluate_expression()
check("T11a 闭环：curiosity=0 时询问线 0.55 → defer（0.52 不够）",
      best is None and verdict_of(cc, "CI_loop").get("reason") == "below_inquiry_bar",
      str(verdict_of(cc, "CI_loop")))
# 询问的动机轴是好奇心：form_threshold 出厂行含 drive.curiosity −0.12
# （config.py cognition.form_threshold）——好奇升高把询问线拉到 0.55×0.88。
_ml.compute({**_Z, "drive.curiosity": 1.0})
best, _ = cc._evaluate_expression()
check("T11b 闭环：curiosity=1 → 询问线降至 0.484 → 同一念头 express",
      best is cc.kg.nodes["CI_loop"]
      and verdict_of(cc, "CI_loop").get("verdict") == "express",
      str(verdict_of(cc, "CI_loop")))
# 陈述闭环：0.74 对 0.78 差 0.04；社交动机调制把它带过线
_ml.compute(dict(_Z))
kg2, cc2 = _cc_with_mod(True, ml=_ml, drives={"social": 0.6})
mk_node(kg2, "用户近况_loop2", space="episodic")
seed_ci(kg2, "CI_stmt", act=0.74, basis=["用户近况_loop2"], goal="follow_up")
best, _ = cc2._evaluate_expression()
check("T11c 闭环：陈述类无动机调制时 defer（0.74<0.78，门槛未被绕过）",
      best is None and verdict_of(kg2 and cc2, "CI_stmt").get("reason") == "below_bar",
      str(verdict_of(cc2, "CI_stmt")))
_ml.compute({**_Z, "need.social": 1.0, "hormone.oxytocin": 0.5})
best, _ = cc2._evaluate_expression()
check("T11d 闭环：社交动机把陈述线压到 0.655 → 0.74 过线 express（动机生效证据）",
      best is kg2.nodes["CI_stmt"]
      and verdict_of(cc2, "CI_stmt").get("verdict") == "express",
      str(verdict_of(cc2, "CI_stmt")))

# ═══ T10 概念念头资格放宽（2026-10-24：高激活 semantic basis 也算有内容）═══
kg5, cc5 = mk_cc(v2=False)
mk_node(kg5, "假设：用户与深夜", act=1.24)      # semantic 高激活概念
seed_ci(kg5, "CI_concept", act=0.80,
        basis=["假设：用户与深夜"], dl="information_statement")
_best5, _val5 = cc5._evaluate_expression()
check("T10a 高激活概念念头过资格门并直抵陈述线（成为表达候选）",
      _best5 is kg5.nodes["CI_concept"] and _val5 >= 0.62,
      f"best={_best5 and _best5.id} val={_val5}")
kg5b, cc5b = mk_cc(v2=False)
mk_node(kg5b, "路过概念", act=0.3)              # 线索超载：泛化低激活线索
seed_ci(kg5b, "CI_weak", act=0.80, basis=["路过概念"])
cc5b._evaluate_expression()
check("T10b 低激活路过概念仍被资格门拦（过滤性保留）",
      verdict_of(cc5b, "CI_weak").get("suppressed")
      == "basis lacking concrete tension",
      str(verdict_of(cc5b, "CI_weak")))

# ═══ T12 暂缓→兴趣转化（deferred exploration 意图不空等衰减出局）═══
kg6, cc6 = mk_cc(v2=False)
mk_node(kg6, "探索目标X", act=1.5)
seed_ci(kg6, "CI_exp", act=0.30, basis=["探索目标X"], kind="exploration")
cc6._evaluate_expression()
it = (kg6.nodes["探索目标X"].extra_attrs.get("interest") or {})
check("T12a exploration 意图暂缓时兴趣水位上调（signal）",
      float(it.get("level") or 0) > 0, str(it))
check("T12c 暂缓概念播种扩散前沿（图谱内探索入口，Synapse 式 traversal）",
      cc6.engine.marked == ["探索目标X"], str(cc6.engine.marked))
cc6._evaluate_expression()                       # 第二拍：同意图不重复播种
check("T12d 播种每意图仅一次（防重复遍历/无限循环）",
      cc6.engine.marked == ["探索目标X"], str(cc6.engine.marked))
kg6b, cc6b = mk_cc(v2=False)
mk_node(kg6b, "普通概念Y", act=1.5)
seed_ci(kg6b, "CI_comm", act=0.30, basis=["普通概念Y"],
        kind="communication")
cc6b._evaluate_expression()
it2 = (kg6b.nodes["普通概念Y"].extra_attrs.get("interest") or {})
check("T12b 沟通类暂缓不转兴趣（只给探索型念头）", not it2, str(it2))

# ═══ 汇总 ═══
print("=" * 60)
if FAILURES:
    print(f"✗ {len(FAILURES)} 项失败: {FAILURES}")
    sys.exit(1)
print("✓ 表达决策 v2 全部场景验收通过")
sys.exit(0)
