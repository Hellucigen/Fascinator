# -*- coding: utf-8 -*-
"""自主行动闭环端到端验收（2026-10-15 任务书 §八，12 案例）。
全内存隔离：无网络、无 LLM、不写生产图谱/账本。
运行：python tests/test_action_loop.py
"""
import json
import os
import sys
import tempfile
import time

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import activities as AC                        # noqa: E402
import living_loop as LL                       # noqa: E402
from graph_model import KnowledgeGraph, Node, Edge  # noqa: E402
from diffusion_engine import DiffusionEngine   # noqa: E402
from config import DEFAULT_CONFIG              # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def mk(search=None):
    td = tempfile.mkdtemp(prefix="actloop_")
    AC._STATE_PATH_OVERRIDE = os.path.join(td, "state.json")
    os.environ["FAS_LIVING_DATA_DIR"] = td
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    kg.add_node(Node(id="Self", label="self", weight=1.0))
    kg.add_node(Node(id="用户", label="disposition", weight=1.0))
    cfg = dict(DEFAULT_CONFIG) if isinstance(DEFAULT_CONFIG, dict) else {}
    cfg["living_loop_max_activities_open"] = 1
    cfg["living_loop_daily_web_budget"] = 60
    eng = DiffusionEngine(kg, cfg)
    ctx = {"config": cfg, "kg": kg, "engine": eng, "curiosity": None,
           "drive": None, "busy": lambda: False, "gaps": [],
           "save_fn": lambda: None, "deliver_fn": lambda c: True,
           "search_fn": (lambda q, top_n=4: list(search or []))}
    LL.read_page = lambda u, **k: {"ok": True,
        "text": "量子达尔文：环境筛选产生客观性的机制正文。", "url": u}
    _fi = AC._forum_items            # 测试环境绝对不碰真实网络（任务书§二.3）
    AC._forum_items = lambda cfg: []
    json.dump([], open(os.path.join(td, "chat_log.json"), "w",
                       encoding="utf-8"))
    AC._HARVEST_INIT[0] = True
    AC._HARVEST_SEEN.clear()
    return td, ctx


def add_concept(kg, cid, act=0.0):
    kg.add_node(Node(id=cid, label="declarative-semantic", weight=0.5))
    kg.nodes[cid].activation = act


def add_ci(kg, name, kind, basis, act=0.9, status="ready"):
    kg.add_node(Node(id=name, label="intention", graph_space="self",
                     weight=0.5,
                     extra_attrs={"type": "intention", "kind": kind,
                                  "status": status, "basis": basis,
                                  "affinity": 0.5}))
    kg.nodes[name].activation = act


def cand_map(ctx):
    return {c: (s, k) for c, s, k, _e in AC._graph_strength(ctx)}


REL = [{"title": "量子达尔文研究综述", "snippet": "量子达尔文 环境筛选",
        "url": "https://x.org/qd"}]

print("── 1 无事件+有效探索 CI ──")
td, ctx = mk()
add_concept(ctx["kg"], "退相干历史", 0.2)
add_ci(ctx["kg"], "int_探索1", "exploration",
       ["退相干历史", "CuriosityDrive"], act=0.9)
cm = cand_map(ctx)
check("L1 未开始的探索 CI ⇒ 其焦点实体成为候选（分数=act×0.55）",
      "退相干历史" in cm and cm["退相干历史"][1] == "ci_exploration"
      and abs(cm["退相干历史"][0] - 0.495) < 0.01, str(cm))

print("── 2 基线保持：无 CI 时与现网一致 ──")
td2, ctx2 = mk()
add_concept(ctx2["kg"], "无关概念", 0.2)
cm2 = cand_map(ctx2)
check("L10 无 CI ⇒ 无 ci_ 通道候选（开关不存在时=桥前基线）",
      not any(k.startswith("ci_") for _s, k in cm2.values()), str(cm2))

print("── 3 CI 衰减 ⇒ 影响随之减弱 ──")
kg = ctx["kg"]
kg.nodes["int_探索1"].activation = 0.3
cm3 = cand_map(ctx)
check("L3 CI 激活 0.9→0.3 ⇒ 候选分数同步下降（无独立状态）",
      cm3.get("退相干历史", (9,))[0] < 0.2, str(cm3.get("退相干历史")))

print("── 4 表达意图不转任务 ──")
td, ctx = mk()
add_concept(ctx["kg"], "某个话题", 0.2)
kg = ctx["kg"]
kg.add_node(Node(id="int_沟通", weight=0.5, label="intention",
                 graph_space="self",
                 extra_attrs={"type": "communication_intention",
                              "kind": "communication", "status": "ready",
                              "basis": ["某个话题"]}))
kg.nodes["int_沟通"].activation = 1.0
check("L4 communication 类意图绝不映射为行动候选",
      "某个话题" not in cand_map(ctx))

print("── 5/11 已有承诺不重复提名；连续拍不重启同意图 ──")
td, ctx = mk(search=REL)
add_concept(ctx["kg"], "量子达尔文", 0.2)
add_ci(ctx["kg"], "int_a", "exploration", ["量子达尔文"], act=0.9)
led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
led.activities["life_x"] = {"id": "life_x", "topic": "搞清楚「量子达尔文」",
    "concept": "量子达尔文", "state": "active", "created": time.time(),
    "updated": time.time(), "progress": [], "methods_tried": [],
    "known_failures": [], "evidence": [], "findings": [], "web_calls": 0,
    "budget": 6, "next_candidates": [], "end_reason": None,
    "resume_count": 0, "consumed_evidence": []}
led.save()
cm = cand_map(ctx)
check("L5 同概念已有行动承诺 ⇒ CI 不再提名（防重复启动）",
      "ci_" not in str(cm.get("量子达尔文", ("", ""))[1]), str(cm))
n1 = len(led.activities)
AC.research_beat(ctx, {})
AC.research_beat(ctx, {})
led2 = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
check("L11 多拍运行 ⇒ 未因同一 CI 产生新活动（活动数不变）",
      len(led2.activities) == n1, str(len(led2.activities)))

print("── 6 意图失效（discarded/expressed）⇒ 桥信号消失 ──")
td, ctx = mk()
add_concept(ctx["kg"], "旧意图对象", 0.2)
add_ci(ctx["kg"], "int_dead", "exploration", ["旧意图对象"], act=0.9)
add_ci(ctx["kg"], "int_dead2", "exploration", ["旧意图对象"],
       act=0.9, status="discarded")
cm = cand_map(ctx)
check("L6 READY 的意图可提名（对照），status 决定信号生死",
      cm.get("旧意图对象", ("", "none"))[1] == "ci_exploration", str(cm))
ctx["kg"].nodes["int_dead"].extra_attrs["status"] = "discarded"
check("L6b 被丢弃的意图不再推动行动",
      "旧意图对象" not in cand_map(ctx))

print("── 7 无法映射的 CI 不强造任务 ──")
td, ctx = mk()
add_ci(ctx["kg"], "int_纯驱力", "action",
       ["CuriosityDrive", "DMNetwork"], act=1.0)
check("L7 basis 全是驱动/网络节点 ⇒ 零候选（保留记录不硬造）",
      not cand_map(ctx), str(cand_map(ctx)))

print("── 8 桥开关关闭 ⇒ 基线回退 ──")
td, ctx = mk()
add_concept(ctx["kg"], "退相干历史", 0.2)
add_ci(ctx["kg"], "int_sw", "exploration", ["退相干历史"], act=0.9)
ctx["config"]["ci_action_bridge"] = {"enabled": False, "weight": 0.55}
check("L10b 开关 off ⇒ ci 通道整体消失，行为回无桥基线",
      not any(str(k).startswith("ci_") for _s, k in cand_map(ctx).values()))

print("── 4(发现回流) 真发现⇒事件，无发现⇒不发 ──")
td, ctx = mk(search=REL)
seed_ledger = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
seed_ledger.activities["life_f"] = {"id": "life_f",
    "topic": "搞清楚「量子达尔文」", "concept": "量子达尔文",
    "state": "active", "created": time.time(), "updated": time.time(),
    "progress": [], "methods_tried": ["q"], "known_failures": [],
    "evidence": ["u"], "findings": [], "web_calls": 1, "budget": 6,
    "next_candidates": [], "end_reason": None, "resume_count": 0,
    "consumed_evidence": []}
seed_ledger.save()
AC._WAKE.clear()
AC.research_beat(ctx, {})                       # 这一步会 found
check("D1 新发现 ⇒ 事件进入通知链（_WAKE 被置位）", AC._WAKE.is_set())
AC._WAKE.clear()
import cognitive_field as _cf0
_cf0.salience_network()._src_hist.pop("evt:discovery", None)  # 从干净计数开始
d2, meta = AC._sn_wake_decision("discovery")
AC._WAKE.clear()
d3, _ = AC._sn_wake_decision("discovery")
d4, _ = AC._sn_wake_decision("discovery")
check("D2 重复 discovery ⇒ SN 同源连击折减，第三击醒不来（自激保险丝）",
      d2 and d3 and not d4, f"{d2}/{d3}/{d4}")
# 无发现的一拍：失败研究不发 discovery
td, ctx = mk(search=[{"title": "无关", "snippet": "无", "url": "u"}])
led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
led.activities["life_p"] = {"id": "life_p", "topic": "搞清楚「查无此人」",
    "concept": "查无此人", "state": "active", "created": time.time(),
    "updated": time.time(), "progress": [], "methods_tried":
    ["查无此人", "此人", "查无", "无此"], "known_failures": [],
    "evidence": [], "findings": [], "web_calls": 4, "budget": 6,
    "next_candidates": [], "end_reason": None, "resume_count": 0,
    "consumed_evidence": []}
led.save()
AC._WAKE.clear()
AC.research_beat(ctx, {})                       # →策略耗尽 paused
check("D3 研究失败/搁置 ⇒ 不发 discovery（不因此反复唤醒）",
      not AC._WAKE.is_set())

print("── 9 watchdog 空转到账不造任务；12 恢复不重复建承诺 ──")
td, ctx = mk()
AC._WAKE.clear()
out = AC.beat(ctx, trigger="sweep")
check("L9 无事件无待办无认知信号 ⇒ sweep 到点也安静（不强行制造任务）",
      out.get("activity") is None, str(out))
# 12: recover 幂等（两次调用不新建活动）
led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
led.activities["life_r"] = {"id": "life_r", "topic": "t", "concept": "c",
    "state": "active", "created": time.time(), "updated": time.time(),
    "progress": [], "methods_tried": [], "known_failures": [],
    "evidence": [], "findings": [], "web_calls": 0, "budget": 6,
    "next_candidates": [], "end_reason": None, "resume_count": 0,
    "consumed_evidence": []}
led.save()
loop = LL.LivingLoop(os.path.join(td, "living_ledger.json"),
                     search_fn=lambda q, top_n=4: [],
                     social_ctx=LL.build_social_context([]),
                     budget=dict(LL.DEFAULT_BUDGET))
n = loop.recover()
loop2 = LL.LivingLoop(os.path.join(td, "living_ledger.json"),
                      search_fn=lambda q, top_n=4: [],
                      social_ctx=LL.build_social_context([]),
                      budget=dict(LL.DEFAULT_BUDGET))
loop2.recover()
led3 = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
check("L12 重启式对账：recover 幂等恢复承诺，不新建不丢失",
      n == 1 and len(led3.activities) == 1
      and led3.activities["life_r"]["state"] == "active")

print("── 用户消息优先级不被桥破坏 ──")
td, ctx = mk()
add_concept(ctx["kg"], "某个念头对象", 0.2)
add_ci(ctx["kg"], "int_u", "exploration", ["某个念头对象"], act=1.0)
ctx["busy"] = lambda: True
AC._last_reeval_ts[0] = 0.0           # 清事件合并冷却（独立场景）
out = AC.beat(ctx, trigger="event")
check("L7b busy（用户交互中）⇒ 桥+一切活动让路（既有规则优先）",
      out.get("why") == "user_interacting", str(out))

print()
if FAILURES:
    print(f"通过 {TOTAL[0] - len(FAILURES)} 条，失败 {len(FAILURES)}："
          f"{FAILURES}")
    sys.exit(1)
print(f"通过 {TOTAL[0]} 条，全部通过")
