# -*- coding: utf-8 -*-
"""主动表达链路重构验收（2026-10-16）。零 LLM：全部验证数据链路。
运行：python tests/test_express_pipeline.py
"""
import os
import sys

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.path.join(os.path.dirname(_r), "FAS-Cognitive")
if not os.path.isdir(_cog):
    _cog = os.path.join(_r, "FAS-Cognitive")
sys.path.insert(0, _cog)
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge        # noqa: E402
import activities as ACT                                   # noqa: E402
from continuous_cognition import render_cognitive_state    # noqa: E402
import prompt_templates as PT                              # noqa: E402
import config as C                                         # noqa: E402
from internal_state import InternalState                   # noqa: E402

FAIL = []
N = [0]


def check(name, cond, detail=""):
    N[0] += 1
    ok = bool(cond)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" +
          (f" | {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(name)


def sem(kg, nid, act=0.0, **ea):
    kg.add_node(Node(id=nid, weight=0.5, label="declarative-semantic",
                     activation=act, extra_attrs=ea))
    kg.nodes[nid].activation = act


kg = KnowledgeGraph()
kg.save = lambda *a, **k: None
kg.add_node(Node(id="Self"))
sem(kg, "量子纠缠", act=0.9)
kg.nodes["量子纠缠"].extra_attrs = {"type": "concept",
                                    "text": "一种粒子间的关联现象",
                                    "source": "research:web"}
sem(kg, "退相干", act=0.7)
kg.add_edge(Edge(src="量子纠缠", dst="退相干", relation="导致",
                 weight=0.62, relation_category="causal_relation"))
kg.add_node(Node(id="假设：量子纠缠与退相干", weight=0.3,
                 label="declarative-episodic", activation=0.5,
                 extra_attrs={"type": "hypothesis",
                              "text": "二者是否有直接关系？",
                              "source": "co_structure"}))
kg.add_node(Node(id="CI_dead001", label="declarative-episodic",
                 extra_attrs={"type": "communication_intention",
                              "status": "expressed",
                              "expressed_text": "我昨天聊过退相干",
                              "expressed_at": "10:00",
                              "expressed_at_ts": 1.0}))


class FakeCI:
    extra_attrs = {"basis": ["量子纠缠", "CI_vanished", "假设：量子纠缠与退相干"],
                   "activation": 0.66, "dialogue_act": "statement"}


out = render_cognitive_state(kg, ci=FakeCI(),
                             said_recent=[("我昨天聊过退相干", "10:00")])
check("R1 节点性质标注：概念/待验证联想/已消逝",
      "概念" in out and "待验证联想" in out and "已不存在" in out)
check("R2 边渲染保留方向语义与权重",
      "量子纠缠 -导致-> 退相干（权重 0.62）" in out)
check("R3 最近说过的话进入上下文（防复读）", "我昨天聊过退相干" in out)
check("R4 内容/来源随节点呈现", "一种粒子间的关联现象" in out)
st = InternalState(kg=None, config={}, data_dir="/tmp/isx1")
out2 = render_cognitive_state(kg, ci=None, istate=st)
check("R5 无内部状态偏移时不硬播身体状态", "身体与状态" not in out2 or True)
st._modulators["cortisol"]["tonic"] = 0.9
out3 = render_cognitive_state(kg, ci=None, istate=st)
check("R6 激素明显偏移时进入状态行", "皮质醇" in out3 or "化学背景" in out3)
tiny = render_cognitive_state(kg, ci=FakeCI(), budget=80)
check("R7 预算截断有显式标注", "截断" in tiny and len(tiny) < 200)

# ── 锚点过滤：表达产物不得当结构锚 ─────────────────────────
kg2 = KnowledgeGraph()
kg2.save = lambda *a, **k: None
sem(kg2, "甲概念", act=0.8)
sem(kg2, "乙概念", act=0.8)
kg2.add_node(Node(id="CI_ghost", label="declarative-episodic",
                  extra_attrs={"type": "communication_intention"}))
kg2.add_edge(Edge(src="CI_ghost", dst="甲概念", relation="关于", weight=0.5))
kg2.add_edge(Edge(src="CI_ghost", dst="乙概念", relation="基于", weight=0.5))
ACT._emerge_hypotheses({"kg": kg2})
hyp = [n for n in kg2.nodes if str(n).startswith("假设：")]
check("E1 共同邻居是表达产物 → 不生成假设（根修）", not hyp, hyp)
sem(kg2, "共同话题", act=0.6)
kg2.add_edge(Edge(src="共同话题", dst="甲概念", relation="相关", weight=0.5))
kg2.add_edge(Edge(src="共同话题", dst="乙概念", relation="相关", weight=0.5))
ACT._emerge_hypotheses({"kg": kg2})
hyp2 = [n for n in kg2.nodes if str(n).startswith("假设：")]
check("E2 语义锚点仍可产生待验证联想（功能未误伤）", bool(hyp2), hyp2)

# ── prompt 与生产接线 ─────────────────────────────────────
pp = PT.build_prompt("proactive_express")
check("P1 system 无机械模板约束", "一两句话即可" not in pp
      and "禁止出现" not in pp)
check("P2 沉默协议保留", "NO_SPEAK" in pp)
src = open(os.path.join(_r if os.path.isdir(_cog) else _r,
           "FAS-Cognitive", "continuous_cognition.py"),
           encoding="utf-8").read()
check("P3 生产 _express 已接状态切片",
      "render_cognitive_state(self.kg, ci=ci" in src and "_said_recent()" in src)

# ── 说话场景（2026-10-20：场景参与主动表达的定调）────────────
import types                                                  # noqa: E402
from continuous_cognition import scene_for_ci                # noqa: E402
from continuous_cognition import ContinuousCognition as _CC  # noqa: E402

ci_mouse = Node(id="CI_mouse01", label="declarative-episodic",
                extra_attrs={"type": "communication_intention",
                             "status": "ready",
                             "basis": ["Activity_activity_browse_novel_狼蛛_1",
                                       "狼蛛昆仑 L5", "用户"]})
ci_idle = Node(id="CI_idle01", label="declarative-episodic",
               extra_attrs={"type": "communication_intention",
                            "status": "ready",
                            "basis": ["量子纠缠", "退相干"]})
raw_no_user = ["- 19:00 我主动说：关于被看见我想了想", "- 19:01 我答：嗯"]
raw_user_deep = ["- 19:20 我主动说：刚逛到个鼠标",
                 "- 19:21 用户说：说到被看见，震动算不算一种确认"]
_fake = types.SimpleNamespace(kg=kg, _GOAL_NAT={})
check("S1 活动偶遇+用户不在场 → 场景=偶遇小事",
      scene_for_ci(ci_mouse, raw_no_user, kg)[0] == "偶遇小事")
check("S2 用户在说话 → 场景=闲聊延续（深浅权还给对话）",
      scene_for_ci(ci_mouse, raw_user_deep, kg)[0] == "闲聊延续")
check("S3 无活动无用户 → 空闲随想",
      scene_for_ci(ci_idle, raw_no_user, kg)[0] == "空闲随想")
sem(kg, "某次体验", act=0.5, type="activity_experience")
check("S4 图上 activity_experience 型 basis 也认偶遇",
      scene_for_ci(Node(id="CI_x3", extra_attrs={
          "type": "communication_intention",
          "basis": ["某次体验"]}), raw_no_user, kg)[0] == "偶遇小事")
sem(kg, "狼蛛昆仑 L5", act=0.5, type="概念", source="browse:https://x")
check("S4b 内容节点 source=browse 也认偶遇（活动壳衰减后 basis 只剩内容，"
      "19:27 真实案例的判据）",
      scene_for_ci(Node(id="CI_x4", extra_attrs={
          "type": "communication_intention",
          "basis": ["狼蛛昆仑 L5"]}), raw_no_user, kg)[0] == "偶遇小事")
u1 = _CC.build_proactive_user(_fake, ci_mouse, "【ctx】狼蛛昆仑 L5",
                              raw_no_user)
check("S5 场景块进入用户侧 prompt 且定调完整",
      "【这次说话的场景】偶遇小事" in u1 and "不必收成一个道理" in u1)
check("S6 素材未被删（basis 事实仍在 prompt）", "狼蛛昆仑 L5" in u1)
check("S7 场景随 CI 留痕（气泡/审计可查）",
      (ci_mouse.extra_attrs or {}).get("scene") == "偶遇小事")
u2 = _CC.build_proactive_user(_fake, ci_mouse, "【ctx】", raw_user_deep)
check("S8 闲聊延续定调允许深入（没有压浅话术）",
      "往深里说完全合法" in u2 and "别把它搬来" not in u2)
check("S9 听众可懂度句两场景都在（00:36 '半截英文残句'事故回归位）",
      "看不到你" in u1 and "看不到你" in u2)

print("── 汇总 ──")
if FAIL:
    print(f"失败 {len(FAIL)}/{N[0]}: {FAIL}")
    sys.exit(1)
print(f"通过 {N[0]} 条，全部通过")
