# -*- coding: utf-8 -*-
"""自主生活深化验收（2026-10-14 v2：图谱量驱动版）。
本轮验收对象是"硬规则删除 + 图谱量接管"本身：
  C 承诺=图谱量连续函数（激活跌不抹掉问题；边权决定持久下限）
  E 证据消费复活（72h 时锁已删：新证据 1 分钟后可复活；同证据不重复触发）
  H 联想→假设（共同邻居+无直接边=待验证问题；有边=不是新问号）
  K 知识内化（found 正文→断言抽取→统一图谱→反哺选题新鲜度）
  F 用户求助新鲜度连续（过时需求自然让位，非永久高分）
  G 图谱生题+目标边开关    Q 安静/开关    S 分享复审
全部 Fake 搜索/隔离数据目录，无真实网络、无真实 LLM。
运行：python tests/test_life_continuity.py
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


def fresh_harvest():
    AC._HARVEST_INIT[0] = True
    AC._HARVEST_SEEN.clear()


class StubNLP:
    """假抽取器：正文→断言草稿（真实路径是 LLM，此处固化输出）。"""

    def extract_assertion_graph(self, text, context_nodes=None, **kw):
        return {"assertion_type": "semantic",
                "nodes": [{"id": "量子达尔文", "node_type": "概念"},
                          {"id": "环境筛选", "node_type": "概念"}],
                "edges": [{"src": "量子达尔文", "dst": "环境筛选",
                           "type": "相关", "weight": 0.7}]}


def stub_consolidate(kg, draft, buffer_, original_text,
                     source="curiosity_auto", w_scale=1.0):
    """与 _auto_consolidate_curiosity_knowledge 同构的最小写回：
    新节点带 source/w_scale 落图；边保守加。"""
    added = {"nodes": 0, "edges": 0}
    for n in draft.get("nodes", []):
        nid = str(n.get("id", "")).strip()
        if nid and nid not in kg.nodes:
            kg.add_node(Node(id=nid, weight=0.45 if w_scale < 1 else 0.6,
                             label="declarative-semantic",
                             graph_space="semantic",
                             extra_attrs={"source": source,
                                          "type": "概念"}))
            added["nodes"] += 1
    for e in draft.get("edges", []):
        if kg.get_node(e["src"]) and kg.get_node(e["dst"]) \
                and not kg.get_edge(e["src"], e["dst"], e["type"]):
            if kg.add_edge(Edge(src=e["src"], dst=e["dst"],
                                relation=e["type"],
                                weight=float(e["weight"]) * w_scale)):
                added["edges"] += 1
    return added


def mk_env(search_results=None, gaps=None,
           page_text="量子达尔文是环境筛选产生客观性的机制："
                     "系统把自身的经典信息冗余地印刻在环境碎片中，"
                     "观察者通过抽样环境副本达成共识。"):
    td = tempfile.mkdtemp(prefix="life_cont_")
    AC._STATE_PATH_OVERRIDE = os.path.join(td, "state.json")
    os.environ["FAS_LIVING_DATA_DIR"] = td
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    kg.add_node(Node(id="Self", label="self", weight=1.0))
    kg.add_node(Node(id="用户", label="disposition", weight=1.0))
    cfg = dict(DEFAULT_CONFIG) if isinstance(DEFAULT_CONFIG, dict) else {}
    # 外部服务隔离：STS2 桥是否在线属于用户环境，不该影响本测试断言
    # （游戏开着时它本就该是合法候选，"预算耗尽真安静"必须排除它）
    cfg["activity_sts2"] = False
    cfg["living_loop_max_activities_open"] = 1
    cfg["living_loop_daily_web_budget"] = 60
    eng = DiffusionEngine(kg, cfg)
    ctx = {"config": cfg, "kg": kg, "engine": eng, "curiosity": None,
           "drive": None, "busy": lambda: False,
           "gaps": list(gaps or []),
           "nlp": StubNLP(), "consolidate_fn": stub_consolidate,
           "save_fn": lambda: None, "deliver_fn": lambda c: True,
           "search_fn": (lambda q, top_n=4: list(search_results or []))}
    LL.read_page = lambda url, max_bytes=4096, timeout=12: {
        "ok": True, "text": page_text, "url": url}
    json.dump([], open(os.path.join(td, "chat_log.json"), "w",
                       encoding="utf-8"))
    return td, ctx


def seed_ledger(td, rows):
    led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
    for a in rows:
        led.activities[a["id"]] = a
    led.save()


def act_rows(td):
    led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
    return list(led.activities.values())


def cands_of(ctx):
    return {c: (s, k) for c, s, k, _e in AC._graph_strength(ctx)}


def new_activity(concept, state="active", created=None, updated=None,
                 resume_count=0, tried=None, end=None, consumed=None):
    t = created or time.time()
    return {"id": f"life_{int(t)}", "topic": f"搞清楚「{concept}」",
            "concept": concept, "state": state, "created": t,
            "updated": updated if updated is not None else t,
            "progress": [], "methods_tried": tried or [],
            "known_failures": [], "evidence": [], "findings": [],
            "web_calls": 0, "budget": 6, "next_candidates": [],
            "end_reason": end, "resume_count": resume_count,
            "consumed_evidence": consumed or []}


RELEVANT = [{"title": "量子达尔文：客观性如何从环境中涌现",
             "snippet": "量子达尔文 环境 自然选择 客观性",
             "url": "https://example.org/qd"}]
DORMANT = {"title": "别的站", "snippet": "完全无关的内容",
           "url": "https://e.org/x"}
ISO_NOW = time.strftime("%Y-%m-%dT%H:%M:%S")


print("── C 承诺=图谱量（激活是因子不是开关）──")
td, ctx = mk_env()
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="量子达尔文", label="declarative-semantic", weight=0.5))
kg.add_edge(Edge(src="Self", dst="量子达尔文", relation="当前目标",
                 weight=0.6))
seed_ledger(td, [new_activity("量子达尔文")])
n = kg.get_node("量子达尔文")
n.activation = 1.0
c = cands_of(ctx)["量子达尔文"]
check("C1 承诺强度=边权×(0.5+0.5×激活)（高注意 1.0→0.60）",
      abs(c[0] - 0.6) < 0.01, str(c))
n.activation = 0.0
c2 = cands_of(ctx)["量子达尔文"]
check("C2 激活跌到 0 强度只减半不消失（短暂失焦≠遗忘问题）",
      abs(c2[0] - 0.3) < 0.01 and c2[0] > 0, str(c2))
check("C3 强度随激活连续变化（非档位跳变）",
      c[0] > c2[0] and c2[0] > 0, f"{c} vs {c2}")
avail, _ = AC.ACTIVITIES[2][1](ctx)
appeal = AC.ACTIVITIES[2][2](ctx, {})
check("C4 appeal 读的就是这个图谱量（候选行=竞争强度，无硬编码）",
      avail and abs(appeal - c2[0]) < 0.01, str((appeal, c2)))

print("── E 证据消费复活（72h 时锁已删）──")
td, ctx = mk_env(search_results=[])
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="拓扑熵", label="declarative-semantic", weight=0.5))
old_paused = new_activity(
    "拓扑熵", state="paused", created=time.time() - 60,
    updated=time.time() - 60, tried=["拓扑熵"],
    end="all_query_strategies_exhausted")
seed_ledger(td, [old_paused])
check("E1 搁置 1 分钟且无新证据 ⇒ 不提名（不看时钟看信息，安静是自然态）",
      "拓扑熵" not in cands_of(ctx))
kg.add_node(Node(id="Activity_new_1", label="declarative-episodic",
                 weight=0.5, graph_space="episodic",
                 extra_attrs={"type": "activity_experience",
                              "kind": "new_info", "value": "low",
                              "text": "逛到一篇讲拓扑熵在数据压缩里应用的文章"}))
kg.nodes["Activity_new_1"].created = time.strftime("%Y-%m-%d %H:%M:%S")
cc = cands_of(ctx)
check("E2 暂停之后出现命中其概念的新信息 ⇒ 立刻重新提名（无等待）",
      "拓扑熵" in cc and cc["拓扑熵"][1] == "paused_rekindle", str(cc))
AC.research_beat(ctx, {})
r = act_rows(td)[0]
check("E3 复活成功：同一活动 id、resume_count=1、active",
      r["id"] == old_paused["id"] and r["state"] == "active"
      and r["resume_count"] == 1, str((r["state"], r.get("resume_count"))))
check("E4 驱动复活的那条证据被消费（记账进账本）",
      "Activity_new_1" in (r.get("consumed_evidence") or []),
      str(r.get("consumed_evidence")))
check("E5 同一证据不再触发新提名（无效重试防护=信息增量而非次数/时间）",
      "拓扑熵" not in cands_of(ctx) or
      AC._graph_strength(ctx) and not any(
          c[0] == "拓扑熵" and "Activity_new_1" in c[3]
          for c in AC._graph_strength(ctx)))
led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
r["state"] = "paused"                      # 模拟复活后再次搁置
r["updated"] = time.time() - 30            # 第二次搁置在 30s 前
led.activities[r["id"]] = r
led.save()
kg.add_node(Node(id="Activity_new_2", label="declarative-episodic",
                 weight=0.5, graph_space="episodic",
                 extra_attrs={"type": "activity_experience",
                              "kind": "new_info", "value": "low",
                              "text": "又看到拓扑熵与信道容量的新联系"}))
kg.nodes["Activity_new_2"].created = time.strftime("%Y-%m-%d %H:%M:%S")
check("E6 第二次真新证据 ⇒ 再次获得提名（已消费清单只挡旧证据，不止损于一次机会）",
      any(c[0] == "拓扑熵" and "Activity_new_2" in c[3]
          and "Activity_new_1" not in c[3]
          for c in AC._graph_strength(ctx)),
      str([(c[0], c[3]) for c in AC._graph_strength(ctx)]))

print("── H 联想→假设（结构锚点，不是共激活断言）──")
td, ctx = mk_env()
fresh_harvest()
kg = ctx["kg"]
for cid, act in (("冯诺依曼熵", 0.5), ("自然选择", 0.45)):
    kg.add_node(Node(id=cid, label="declarative-semantic", weight=0.5))
    kg.nodes[cid].activation = act
kg.add_node(Node(id="信息", label="declarative-semantic", weight=0.5))
kg.add_edge(Edge(src="冯诺依曼熵", dst="信息", relation="相关", weight=0.5))
kg.add_edge(Edge(src="自然选择", dst="信息", relation="相关", weight=0.5))
made = AC._emerge_hypotheses(ctx)
check("H1 共邻居+无直接边的概念对 ⇒ 长出待验证假设（情景节点非事实）",
      len(made) == 1 and kg.get_node(made[0]) is not None
      and kg.get_node(made[0]).label == "declarative-episodic"
      and float(kg.get_node(made[0]).weight) <= 0.3, str(made))
hyp = kg.get_node(made[0]) if made else None
check("H2 假设带锚点证据（共享邻居 id 可追溯）",
      hyp is not None and (hyp.extra_attrs or {}).get("anchor") == "信息",
      str((hyp.extra_attrs or {}).get("anchor") if hyp else None))
check("H3 假设进入候选池参选（可被后续研究消费，非只写日志）",
      any(k == "hypothesis" for _s, k in cands_of(ctx).values()),
      str(list(cands_of(ctx).items())[:3]))
AC._emerge_hypotheses(ctx)
check("H4 同对不重复建（联想不刷屏）",
      sum(1 for n in kg.nodes.values()
          if (n.extra_attrs or {}).get("type") == "hypothesis") == 1)
kg.add_edge(Edge(src="冯诺依曼熵", dst="自然选择", relation="相关",
                 weight=0.5))
td2, ctx2 = mk_env()
for cid, act in (("甲", 0.5), ("乙", 0.5)):
    ctx2["kg"].add_node(Node(id=cid, label="declarative-semantic",
                             weight=0.5))
    ctx2["kg"].nodes[cid].activation = act
ctx2["kg"].add_node(Node(id="丙", label="declarative-semantic", weight=0.5))
ctx2["kg"].add_edge(Edge(src="甲", dst="丙", relation="相关", weight=0.5))
ctx2["kg"].add_edge(Edge(src="乙", dst="丙", relation="相关", weight=0.5))
ctx2["kg"].add_edge(Edge(src="甲", dst="乙", relation="相关", weight=0.5))
check("H5 已有直接关联的两概念不再长假设（不虚构问号）",
      not AC._emerge_hypotheses(ctx2))

print("── K 知识内化（正文→图谱→反哺）──")
td, ctx = mk_env(search_results=RELEVANT)
fresh_harvest()
seed_ledger(td, [new_activity("量子达尔文", state="active")])
AC.research_beat(ctx, {})
kg = ctx["kg"]
kn = kg.get_node("环境筛选")              # 草稿的**新概念**=真新增知识
kn_old = kg.get_node("量子达尔文")
check("K1 found 正文经既有漏斗写回：新概念带 research:url 来源入语义空间",
      kn is not None and kn.label == "declarative-semantic"
      and str((kn.extra_attrs or {}).get("source") or "").startswith(
          "research:"), str((kn.extra_attrs or {})
                            if kn else None)[:120])
check("K1b 已有概念（研究主题本身）不被重复创建（既有节点优先）",
      kn_old is not None
      and sum(1 for n in kg.nodes.values() if n.id == "量子达尔文") == 1)
check("K2 抽取的关系入图且边权打折扣（网页≠确证）",
      kg.get_edge("量子达尔文", "环境筛选", "相关") is not None
      and kg.get_edge("量子达尔文", "环境筛选", "相关").weight <= 0.45,
      str(kg.get_edge("量子达尔文", "环境筛选", "相关").weight))
check("K3 内化幂等（同一活动不重复抽取烧预算）",
      act_rows(td)[0].get("knowledge_ingested", 0) >= 1)
row = act_rows(td)[0]
n_ing = row.get("knowledge_ingested")
old_val = n_ing
AC.research_beat(ctx, {})
check("K3b 幂等复验：二次调用不新增结构",
      act_rows(td)[0].get("knowledge_ingested") == old_val)
td, ctx = mk_env(gaps=[{"concept": "量子达尔文", "ts": ISO_NOW,
                        "evidence": "用户说没懂"}])
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="量子达尔文", label="declarative-semantic", weight=0.5,
                 confidence=0.6))
kg.nodes["量子达尔文"].extra_attrs.update(
    {"source": "research:https://x"})
kg.nodes["量子达尔文"].activation = 0.3
s_fresh_closed = cands_of(ctx)["量子达尔文"][0]
td, ctx = mk_env(gaps=[{"concept": "全新概念", "ts": ISO_NOW,
                        "evidence": "用户说没懂"}])
s_fresh_open = cands_of(ctx)["全新概念"][0]
check("K4 已有高置信研究知识的缺口 ⇒ 求助强度自然衰减（已答过≠新需求）",
      s_fresh_closed < s_fresh_open, str((s_fresh_closed, s_fresh_open)))

print("── F 用户求助新鲜度连续（非永久高分）──")
td, ctx = mk_env()
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="旧问题", label="declarative-semantic", weight=0.5))
old_h = time.strftime("%Y-%m-%dT%H:%M:%S",
                      time.localtime(time.time() - 720 * 3600))
ctx["gaps"] = [{"concept": "旧问题", "ts": time.strftime(
    "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 240 * 3600)),
    "evidence": ""}]
s_mid = cands_of(ctx).get("旧问题", (0.0,))[0]
ctx["gaps"] = [{"concept": "旧问题", "ts": ISO_NOW, "evidence": ""}]
s_new = cands_of(ctx)["旧问题"][0]
check("F1 同一求助：1 小时前强度 ≫ 10 天前（连续衰减，非档位）",
      s_new > 4 * s_mid > 0, str((s_new, s_mid)))
ctx["gaps"] = [{"concept": "旧问题", "ts": old_h, "evidence": ""}]
check("F1b 30 天未处理的旧求助自然落选（让位=衰减极限，不是硬拒）",
      "旧问题" not in cands_of(ctx))
kg.add_edge(Edge(src="Self", dst="旧问题", relation="当前目标", weight=0.6))
kg.nodes["旧问题"].activation = 0.8
seed_ledger(td, [new_activity("旧问题", state="active")])
sc = cands_of(ctx)["旧问题"][0]
check("F2 10 天前的旧求助让位于进行中承诺（由量决定，不是来源规则）",
      sc > s_mid, str((sc, s_mid)))

print("── G 图谱生题与目标边（回归自 v1）──")
td, ctx = mk_env(search_results=RELEVANT)
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="量子达尔文", label="declarative-semantic", weight=0.5))
kg.add_edge(Edge(src="Self", dst="量子达尔文", relation="正在学习",
                 weight=0.7))
kg.nodes["量子达尔文"].activation = 0.6
cc = cands_of(ctx)
check("G1 正在学习边提名（strength=边权×注意加成，读自图谱）",
      "量子达尔文" in cc and cc["量子达尔文"][1] == "learning", str(cc))
AC.research_beat(ctx, {})
ge = [e for e in kg.get_out_edges("Self") if e.relation == "当前目标"]
check("G2 活动开启即挂 Self-[当前目标]（图谱可见行动承诺）",
      len(ge) == 1 and ge[0].dst == "量子达尔文", str(ge))
AC.research_beat(ctx, {})
check("G3 done 后目标边自动摘除",
      not [e for e in kg.get_out_edges("Self")
           if e.relation == "当前目标"])

td, ctx = mk_env(search_results=[])
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="乙事", label="declarative-semantic", weight=0.5))
kg.add_node(Node(id="甲事", label="declarative-semantic", weight=0.5))
kg.add_edge(Edge(src="Self", dst="甲事", relation="当前目标", weight=0.6))
AC.write_state_field(ctx, "甲事")                 # 图谱与状态挂着旧承诺
AC.write_state_field(ctx, "甲事")
kg.add_edge(Edge(src="Self", dst="乙事", relation="正在学习", weight=0.6))
seed_ledger(td, [new_activity("乙事", state="active")])  # 实际承诺已是乙
AC._reconcile_goal(ctx)
ge = [e.dst for e in kg.get_out_edges("Self")
      if e.relation == "当前目标"]
check("G4 切换目标：旧承诺边摘除、新承诺边建立（图谱同时最多一条当前目标）",
      ge == ["乙事"], str(ge))

td, ctx = mk_env(search_results=[])
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="搁置学习项", label="declarative-semantic", weight=0.5))
kg.add_edge(Edge(src="Self", dst="搁置学习项", relation="正在学习",
                 weight=0.7))          # 图谱里挂着学习声明
seed_ledger(td, [new_activity("搁置学习项", state="paused",
                              created=time.time() - 300,
                              updated=time.time() - 300,
                              tried=["搁置学习项"],
                              end="all_query_strategies_exhausted")])
check("E7 刚搁置的概念不被 正在学习 边直接重推（学习边也曾成自我消费回路）",
      "搁置学习项" not in cands_of(ctx))
kg.add_node(Node(id="Activity_ext_1", label="declarative-episodic",
                 weight=0.5, graph_space="episodic",
                 extra_attrs={"type": "activity_experience",
                              "kind": "new_info", "value": "low",
                              "text": "用户刚聊到搁置学习项的用法"}))
kg.nodes["Activity_ext_1"].created = time.strftime("%Y-%m-%d %H:%M:%S")
check("E7b 但外部新信息命中它 ⇒ 仍可经证据通道回来（学习边不是死刑）",
      any(c[0] == "搁置学习项" and c[2] == "paused_rekindle"
          for c in AC._graph_strength(ctx)))

print("── Q 安静/开关 + S 分享复审 ──")
td, ctx = mk_env(search_results=[])
fresh_harvest()
_f0 = AC._forum_items
AC._forum_items = lambda cfg: []        # 安静场景=论坛今天也没东西（隔离网络）
try:
    out = AC.beat(ctx, trigger="sweep")
finally:
    AC._forum_items = _f0
check("Q1 无承诺/无求助/无学习/无假设 ⇒ 合法安静",
      out.get("activity") is None, str(out))
check("Q2 安静不产生活动（无并行路径空转）", act_rows(td) == [])
td, ctx = mk_env(search_results=RELEVANT)
fresh_harvest()
seed_ledger(td, [new_activity("量子达尔文", state="done",
                              tried=["量子达尔文"])])
a0 = act_rows(td)[0]
a0["findings"] = [{"query": "q", "evidence": [{"title": "t", "url": "u"}],
                   "page_read": {"ok": True, "text": "量子达尔文……"}}]
led = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
led.activities[a0["id"]] = a0
led.save()
_orig = LL.decide_share
try:
    LL.decide_share = lambda prod, sc: type("D", (), {
        "verdict": "no_share", "reason": "对话正热"})()
    loop = LL.LivingLoop(os.path.join(td, "living_ledger.json"),
                         search_fn=lambda q, top_n=4: [],
                         social_ctx=LL.build_social_context([]),
                         budget=dict(LL.DEFAULT_BUDGET,
                                     max_activities_open=1))
    loop.social_step()
    r1 = act_rows(td)[0]
    check("S1 首拒=情境性：记 review 1，不永久封箱",
          int(r1.get("share_reviews") or 0) == 1
          and not r1.get("share_decided"), str((r1.get("share_reviews"),
                                               r1.get("share_decided"))))
    loop.social_step()
    r2 = act_rows(td)[0]
    LL.decide_share = lambda prod, sc: type("D", (), {
        "verdict": "share", "reason": "现在合适"})()
    loop.social_step()
    r3 = act_rows(td)[0]
    check("S2 复审两次被拒后封箱（有界），期间情境变好仍可得机会",
          (r2.get("share_reviews") == 2) or (r3.get("share_decided")
                                             and r3.get("share_verdict")
                                             == "share"),
          str((r2.get("share_reviews"), r3.get("share_verdict"))))
finally:
    LL.decide_share = _orig

print("── B 论坛巡逻（环境新信息→命中才逛→点亮搁置研究）──")
td, ctx = mk_env(search_results=[])
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="拓扑熵", label="declarative-semantic", weight=0.5))
seed_ledger(td, [new_activity("拓扑熵", state="paused",
                              created=time.time() - 300,
                              updated=time.time() - 300,
                              tried=["拓扑熵"],
                              end="all_query_strategies_exhausted")])
_orig_items = AC._forum_items
_orig_rp = LL.read_page
try:
    AC._forum_items = lambda cfg: [
        {"title": "拓扑熵在数据压缩中的新应用讨论",
         "url": "https://fake.example/tp", "src": "hn"},
        {"title": "今天中午吃什么", "url": "https://fake.example/eat",
         "src": "ithome"}]
    LL.read_page = lambda u, **k: {"ok": True, "text": "正文……", "url": u}
    t, u, c, kind = AC._forum_seed(ctx)
    check("B1 论坛标题命中搁置研究的概念 ⇒ 选题（paused 优先）",
          c == "拓扑熵" and kind == "paused", str((t, c, kind)))
    res = AC.browse_beat(ctx, {})
    check("B2 巡逻一拍：读文章并登记体验（带 concept=拓扑熵）",
          res.get("done") and any(
              n.extra_attrs.get("concept") == "拓扑熵"
              for n in kg.nodes.values()
              if (n.extra_attrs or {}).get("type") == "activity_experience"),
          str(res)[:100])
    cands = AC._graph_strength(ctx)
    check("B3 闭环：那条浏览体验成为新证据 ⇒ 搁置研究下一拍重新参选",
          any(x[0] == "拓扑熵" and x[2] == "paused_rekindle"
              and any(str(nid).startswith("Activity_") for nid in x[3])
              for x in cands), str(cands)[:140])
    ledchk = LL.ActivityLedger(os.path.join(td, "living_ledger.json"))
    import datetime as _dtm
    today = _dtm.date.today().isoformat()
    check("B4 巡逻记账进每日预算（feed+文章）",
          int(ledchk.daily.get(today, 0)) >= 3, str(ledchk.daily))
    AC._forum_items = lambda cfg: [
        {"title": "完全无关的八卦新闻标题一二三", "url": "https://x",
         "src": "hn"}]
    t2 = AC._forum_seed(ctx)
    check("B5 不命中已有概念但标题对她是陌生的 ⇒ 仍点进去看看（探索=遇新，"
          "不是只翻旧账）",
          t2[3] == "novel", str(t2)[:80])
    AC._forum_items = lambda cfg: [
        {"title": "拓扑熵 元认知 超对称规范反常 转码",   # 全是她图里的词
         "url": "https://x2", "src": "hn"}]
    t3 = AC._forum_seed(ctx)
    check("B5b 命中她已在意的事 ⇒ 按命中选题（paused 优先于 novel）",
          t3[2] == "拓扑熵" and t3[3] == "paused", str(t3)[:80])
finally:
    AC._forum_items = _orig_items
    LL.read_page = _orig_rp

print("── B' 逛的欲望是状态量不是时钟（想看就看，逛腻了自己停）──")
td, ctx = mk_env(search_results=[])
fresh_harvest()
_f0 = AC._forum_items
_rp0 = LL.read_page
try:
    AC._forum_items = lambda cfg: []            # 今天论坛里没她在意的东西
    st0 = {"browse": {}}
    a0 = AC.ACTIVITIES[1][2](ctx, st0)
    _sh = AC._load_state()
    AC.browse_beat(ctx, _sh)                    # 空手而归 ×3（共享 state）
    AC.browse_beat(ctx, _sh)
    AC._save_state(_sh)
    st2 = {"browse": AC._load_state().get("browse", {})}
    a2 = AC.ACTIVITIES[1][2](ctx, st2)
    AC.browse_beat(ctx, AC._load_state())
    a3 = AC.ACTIVITIES[1][2](
        ctx, {"browse": AC._load_state().get("browse", {})})
    check("B7 连次空手而归 ⇒ 逛的欲望逐次减半（状态梯度，非一刀切 30 分钟；"
          "地板 0.25=最低好奇不至于永远不想逛）",
          a0 > a2 >= a3 > 0 and abs(a2 - a0 * 0.25) < 1e-6,
          str((round(a0, 3), round(a2, 3), round(a3, 3))))
    check("B8 腻了之后分数沉到行动阈值下 ⇒ 她自然不去了（不用时钟禁）",
          a3 < AC.THRESHOLD, str(a3))
    # 喂一次成功巡逻：兴趣复燃
    AC._forum_items = lambda cfg: [
        {"title": "全新概念的陌生展览今天开幕", "url": "https://fake/y",
         "src": "hn"}]
    LL.read_page = lambda u, **k: {"ok": True, "text": "正文内容示例若干",
                                   "url": u}
    AC.browse_beat(ctx, AC._load_state())
    a4 = AC.ACTIVITIES[1][2](
        ctx, {"browse": AC._load_state().get("browse", {})})
    check("B9 真逛到新东西 ⇒ 折扣回血、兴趣复燃（欲望被满足喂大而非耗尽）",
          a4 > a3, str((round(a3, 3), round(a4, 3))))
finally:
    AC._forum_items = _f0
    LL.read_page = _rp0

print("── B'' 旧货就换：跳过看过的、源降权、下次去别家 ──")
td, ctx = mk_env(search_results=[])
fresh_harvest()
kg = ctx["kg"]
_f0 = AC._forum_items
_rp0 = LL.read_page
try:
    _f_seen = AC._forum_items
    # 先成功逛一条（进"已逛记录"）
    AC._forum_items = lambda cfg: [
        {"title": "新奇展览甲", "url": "https://fake/a", "src": "ithome"}]
    LL.read_page = lambda u, **k: {"ok": True, "text": "甲展览的正文内容",
                                   "url": u}
    _st_shared = AC._load_state()
    AC.browse_beat(ctx, _st_shared)          # 共享 state 引用（与生产 beat 一致）
    AC._save_state(_st_shared)
    # 再逛时：ithome 还推同一条（被跳过）+ hn 有新内容 → 换 hn
    AC._forum_items = lambda cfg: [
        {"title": "新奇展览甲", "url": "https://fake/a", "src": "ithome"},
        {"title": "乙游戏公布续作预告", "url": "https://fake/b",
         "src": "hn"}]
    picked = AC._forum_seed(ctx)
    check("B10 已逛过的标题在选择阶段跳过，直接换源看新的（不换源就空手）",
          picked[0] == "乙游戏公布续作预告" and picked[3] == "novel",
          str(picked)[:110])
    st_ = AC._load_state().get("browse", {})
    sd_ = st_.get("src_discount") or {}
    check("B11 老推旧货的源被降权（ithome < 1，下次排序吃亏）",
          float(sd_.get("ithome") or 1.0) < 1.0, str(sd_))
finally:
    AC._forum_items = _f0
    LL.read_page = _rp0

print("── R' 预算与愿望同步（想做=能干）──")
td, ctx = mk_env(search_results=[])
fresh_harvest()
kg = ctx["kg"]
kg.add_node(Node(id="量子达尔文", label="declarative-semantic", weight=0.5))
kg.add_edge(Edge(src="Self", dst="量子达尔文", relation="正在学习", weight=0.7))
kg.nodes["量子达尔文"].activation = 0.6
kg.add_edge(Edge(src="Self", dst="量子达尔文", relation="当前目标", weight=0.6))
seed_ledger(td, [new_activity("量子达尔文", state="active")])
ok0, _ = AC.ACTIVITIES[1][1](ctx) and AC.ACTIVITIES[2][1](ctx)
ledp = os.path.join(td, "living_ledger.json")
_lf = json.load(open(ledp, encoding="utf-8"))
import datetime as _dtm
_lf["daily_web_calls"] = {_dtm.date.today().isoformat(): 60}  # mk_env 预算=60
json.dump(_lf, open(ledp, "w", encoding="utf-8"), ensure_ascii=False)
b_avail, _ = AC.ACTIVITIES[1][1](ctx)
r_avail, _ = AC.ACTIVITIES[2][1](ctx)
check("R1' 预算耗尽 ⇒ browse 与 research 双双不可选（不再'想做但做不了'，"
      "音乐等零成本活动不受影响）",
      ok0 and not b_avail and not r_avail, str((b_avail, r_avail)))
out = AC.beat(ctx, trigger="sweep")
check("R2' 预算耗尽时真实安静（不空转拉列表吹爆预算）",
      out.get("activity") is None, str(out)[:110])

print()
if FAILURES:
    print(f"通过 {TOTAL[0] - len(FAILURES)} 条，失败 {len(FAILURES)} 条：{FAILURES}")
    sys.exit(1)
print(f"通过 {TOTAL[0]} 条，全部通过")
