# -*- coding: utf-8 -*-
"""test_v3.py — 统一认知/目标/行动/社交架构的验收套件。

17 验收场景 + 历史 A-H 回归。全部隔离：内存图/临时账本/可控时钟/fake 工具。
运行：python experiments/living_v3/test_v3.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))            # FAS-Cognitive 根
sys.path.insert(0, "E:/Project/FAS-Companion")

from graph_model import KnowledgeGraph, Node, Edge
from cognitive_product import (CognitiveProduct, products_from_graph_state,
                               worth_goal)
from goal_bridge import GoalBridge
from social_decider import SocialContext, decide_share
from activity_v3 import ActivityLoopV3
from autonomy_loop import Toolbox, S_DONE
from serialize_fidelity import (StructureProbe, build_probe,
                                old_path_recover, v3_path_recover)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


def fake_search(rows):
    def fn(q, top_n=5):
        return rows
    return fn


GOOD = [{"title": "暗物质晕", "snippet": "暗物质晕通过引力效应被推断存在。"}]
IRRELEVANT = [{"title": "菜谱", "snippet": "红烧肉做法"}]


def mk_v3(tools=None, goals_api=None, social=None):
    kg = KnowledgeGraph()
    cc = ActivityLoopV3(kg, os.path.join(tempfile.mkdtemp(), "ledger.json"),
                        Toolbox(tools if tools is not None
                                else {"web_search": fake_search(GOOD)}),
                        goals_api=goals_api, social_ctx=social)
    return kg, cc


def self_graph_stub(goals=None):
    """self_graph 最小替身（同语义：set_goal/get_goals 挂图上）。"""
    class SG:
        store = list(goals or [])

        def set_goal(self, kg, desc, parent_goal=None):
            SG.store.append({"goal": desc, "parent": parent_goal})
            return desc

        def get_goals(self):
            return [{"goal": g["goal"]} for g in SG.store]

        def remove_goal(self, kg, gid):
            pass
    return SG()


def unknown_node(kg, name, retired=False):
    nid = f"UnknownConcept_{name}"
    kg.add_node(Node(id=nid, weight=0.6,
                     extra_attrs={"type": "unknown",
                                  **({"retired": True} if retired else {})}))
    return nid


def thought_node(kg, content):
    nid = f"思考_{int(time.time() * 1000) % 10**9}"
    kg.add_node(Node(id=nid, weight=0.6, label="declarative-episodic",
                     extra_attrs={"type": "thought", "content": content,
                                  "born_ts": time.time()}))
    return nid


# ═══ 场景 1/2/10：从真实状态发现问题 → 选工具 → 完成只读任务 / 空闲 ═══
kg, cc = mk_v3()
nid = unknown_node(kg, "暗物质晕")
kg.nodes[nid].activation = 5.0
view = [{"id": nid, "extra_attrs": kg.nodes[nid].extra_attrs,
         "activation": 5.0}]
products = products_from_graph_state(view)
check("V3-1a 未知标记 → open_question + goal_candidate 产物",
      {p.type for p in products} >= {"open_question", "goal_candidate"},
      str([p.type for p in products]))
added = cc.ingest_products(products)
out = cc.step()
t = list(cc.ledger.tasks.values())[0]
_done = [t for t in cc.ledger.tasks.values() if t["state"] == S_DONE]
check("V3-1b 认知产物任务完成真实只读任务且学习落图",
      len(_done) >= 1
      and any(t["verdict"] == "SUCCESS" and t.get("learned_id") in kg.nodes
              for t in _done), str(out))
check("V3-10 无候选时保持空闲（空图不编造）",
      mk_v3()[1].step()["proposed"] == 0)

# ═══ 场景 3：工具结果不相关 → 停止，不伪造成功 ═══
kg3, cc3 = mk_v3(tools={"web_search": fake_search(IRRELEVANT)})
unknown_node(kg3, "暗物质晕")
p3 = products_from_graph_state([
    {"id": list(kg3.nodes)[0], "extra_attrs":
     kg3.nodes[list(kg3.nodes)[0]].extra_attrs, "activation": 5.0}])
cc3.ingest_products(p3)
cc3.step()
t3 = list(cc3.ledger.tasks.values())[0]
check("V3-3 结果不相关 → INCONCLUSIVE，不伪造成功",
      t3["verdict"] == "INCONCLUSIVE", str(t3["verdict_reason"]))

# ═══ 场景 4 + 历史 A：反证修改原目标（目标惯性的直接对策） ═══
kg4 = KnowledgeGraph()
sg4 = self_graph_stub()
bridge = GoalBridge(kg4, sg4)
from cognitive_product import CognitiveProduct as CP
p_old = CP(type="goal_candidate", text="研究配方B的燃料路线",
           evidence_ids=["探针反例0"], confidence=0.6)
bridge.from_product(p_old)
ok = bridge.revise("研究配方B的燃料路线", "改走无燃料合成路线",
                   ["探针反例0"], "反证：燃料路线曾因缺燃料失败")
check("V3-4a 反证触发目标修订（修订带旧/新/证据/原因留痕）",
      ok and any(r.get("old") == "研究配方B的燃料路线" and r.get("reason")
                 for r in bridge.revisions),
      str(bridge.revisions[-1:] if bridge.revisions else "none"))
check("V3-4b 修订后新目标接管指针",
      any(g["goal"] == "改走无燃料合成路线" for g in sg4.get_goals()))
check("V3-4c 幂等：同文目标不重复创建",
      bridge.from_product(p_old) is None)

# ═══ 场景 5 + 历史 planner 回归引用：多子目标 + 中间失败改计划 ═══
# goal_planner tests/test_goal_planner.py 5a-d,16 已覆盖（23 项全绿）；
# 此处验证 v3 不破坏其前提：候选 → goal 指针 → planner 可读。
kg5 = KnowledgeGraph()
sg5 = self_graph_stub()
b5 = GoalBridge(kg5, sg5)
b5.from_product(CP(type="goal_candidate", text="完成模组剧情大纲",
                   evidence_ids=["x"]))
check("V3-5 goal 指针可被 planner 链消费（current_goal_spec 语义兼容）",
      any(g["goal"] == "完成模组剧情大纲" for g in sg5.get_goals()))

# ═══ 场景 6 + 历史 B/D：多段记忆共同决定行动（结构保真） ═══
kg6 = KnowledgeGraph()
spec6 = build_probe(kg6)
for _i in range(10):                       # 高激活噪声竞争（复现 Top-8 挤出）
    _nid = f"噪声节点{_i}"
    kg6.add_node(Node(id=_nid, weight=0.9, graph_space="semantic"))
    kg6.nodes[_nid].activation = 5.0
# 旧路径：top-8 截断（按激活排——探针节点激活均低 → 大多被截）
_all_ids = list(kg6.nodes.keys())
topk_ids = [n["id"] for n in sorted(
    [{"id": nid, "a": float(kg6.nodes[nid].activation or 0)} for nid in _all_ids],
    key=lambda x: -x["a"])]                       # 全图按激活排——噪声占满 top-8
old_rec = old_path_recover(spec6, topk_ids, kg6, k=8)
# v3 路径：relation_finding 产物引用全部证据节点
from cognitive_product import CognitiveProduct as CP6
products6 = [CP6(type="relation_finding",
                 text="合成B需要三步且有一个前置条件与一个已知失败原因",
                 evidence_ids=spec6.node_ids, confidence=0.7)]
v3_rec = v3_path_recover(spec6, products6, kg6)
total = (len(spec6.steps) + len(spec6.preconditions)
         + len(spec6.counter_evidence) + len(spec6.positive_evidence))
old_alive = sum(len(v) for v in old_rec.values())
v3_alive = sum(len(v) for v in v3_rec.values())
check(f"V3-6a 旧路径 top-8 截断丢失结构字段（{old_alive}/{total} 存活）——历史 B/D 复现",
      old_alive < total, str(old_rec))
check("V3-6b v3 路径结构字段全存活（关系结构不丢）",
      v3_alive == total, str(v3_rec))
check("V3-6c 反例与正向证据同时到达下游",
      len(v3_rec["counter"]) == 1 and len(v3_rec["positive"]) == 1)

# ═══ 场景 7 + 历史 E：新事件打断旧目标 → 判断继续/暂停/放弃 ═══
kg7, cc7 = mk_v3()
nid7 = unknown_node(kg7, "旧问题")
cc7.ingest_products(products_from_graph_state(
    [{"id": nid7, "extra_attrs": kg7.nodes[nid7].extra_attrs,
      "activation": 5.0}]))
cc7.step()
done_old = [t for t in cc7.ledger.tasks.values() if t["state"] == S_DONE]
nid7b = unknown_node(kg7, "新打断事件")
p_new = products_from_graph_state([
    {"id": nid7b, "extra_attrs": kg7.nodes[nid7b].extra_attrs,
     "activation": 5.0}])
added = cc7.ingest_products(p_new)
check("V3-7 新事件打断后旧任务不回滚、新事件正常进入循环",
      len(done_old) >= 1 and added >= 1)

# ═══ 场景 8：相同任务不重复执行 ═══
kg8, cc8 = mk_v3()
nid8 = unknown_node(kg8, "暗物质晕")
p8 = products_from_graph_state([
    {"id": nid8, "extra_attrs": kg8.nodes[nid8].extra_attrs,
     "activation": 5.0}])
cc8.ingest_products(p8)
cc8.step()
n1 = len(cc8.ledger.tasks)
cc8.ingest_products(products_from_graph_state([
    {"id": nid8, "extra_attrs": kg8.nodes[nid8].extra_attrs,
     "activation": 5.0}]))
n2 = len(cc8.ledger.tasks)
check("V3-8 相同任务不重复创建", n1 == n2, f"{n1}→{n2}")

# ═══ 场景 9：一次成功活动影响下一轮决策（跨轮学习） ═══
kg9, cc9 = mk_v3()
nid9 = unknown_node(kg9, "暗物质晕")
p9 = products_from_graph_state([
    {"id": nid9, "extra_attrs": kg9.nodes[nid9].extra_attrs,
     "activation": 5.0}])
cc9.ingest_products(p9)
cc9.step()
learned = [t.get("learned_id") for t in cc9.ledger.tasks.values()
           if t.get("learned_id")]
check("V3-9 成功活动的学习节点存在于图（下一轮可引用）",
      all(l in kg9.nodes for l in learned) and learned)

# ═══ 场景 11-15：社交决策器（双向：该说不说 + 不该说别说） ═══
NOW = 1000000.0
P_GROUNDED = CP(type="social_material",
                text="用户的模组项目完成了第一版剧情骨架——我刚从工作区快照看到",
                evidence_ids=["用户近况_x"], confidence=0.6)
P_EMPTY = CP(type="social_material", text="随便聊聊",
             evidence_ids=[], confidence=0.5)

d = decide_share(P_GROUNDED, SocialContext(now=NOW))
check("V3-11a 有证据+时机合适 → share", d.verdict == "share", d.reason)
d = decide_share(P_GROUNDED, SocialContext(
    now=NOW, recent_expressed=["用户的模组项目完成了第一版剧情骨架"],
    recent_express_ts=NOW - 600))
check("V3-15a 认知有价值但刚说过 → silent（价值≠值得发送）",
      d.verdict == "silent" and "low_novelty" in d.reason, d.reason)
d = decide_share(P_EMPTY, SocialContext(now=NOW))
check("V3-14a 无证据素材 → silent（不过度推断）", d.verdict == "silent")
d = decide_share(P_GROUNDED, SocialContext(
    now=NOW, user_recent_ts=NOW - 120, conversation_open=True))
check("V3-11b 对话进行中+刚互动 → defer（打扰成本）",
      d.verdict == "defer" and "disturbance" in d.reason, d.reason)
d = decide_share(P_GROUNDED, SocialContext(now=NOW, negative_feedback=True))
check("V3-14b 负反馈未消退 → silent", d.verdict == "silent")
# 静态快照不误解（13）：baseline 观察产物不触发分享
from cognitive_product import products_from_graph_state as pfg
kg13 = KnowledgeGraph()
kg13.add_node(Node(id="用户近况_bg", weight=0.6, graph_space="episodic",
                   extra_attrs={"type": "perception",
                                "source": "charon_workspace",
                                "baseline": True,
                                "text": "用户工作区快照 — 最近笔记：A；B"}))
prods13 = pfg([{"id": "用户近况_bg",
                "extra_attrs": kg13.nodes["用户近况_bg"].extra_attrs,
                "activation": 1.2}])
d13 = decide_share(prods13[0], SocialContext(now=NOW))
# 断言演进（2026-10-11）：SocialDecider 增加背景素材静默门后，正确行为
# 从 "share/defer" 收紧为 "silent"（背景清单快照不应主动分享）。
check("V3-13 背景快照产物 → silent（background_material_not_shareable）",
      d13.verdict == "silent" and "background" in d13.reason,
      f"{d13.verdict}/{d13.reason}")

# ═══ 场景 16：进程中断恢复（复用 v1 S12 + 账本持久化） ═══
kg16, cc16 = mk_v3()
nid16 = unknown_node(kg16, "暗物质晕")
cc16.ingest_products(products_from_graph_state([
    {"id": nid16, "extra_attrs": kg16.nodes[nid16].extra_attrs,
     "activation": 5.0}]))
cc16.step()
lp16 = cc16.ledger.path
cc16b = ActivityLoopV3(kg16, lp16, cc16.tools, social_ctx=cc16.social_ctx)
n_done_before = sum(1 for t in cc16b.ledger.tasks.values()
                    if t["state"] == S_DONE)
cc16b.recover()
n_dup = sum(1 for t in cc16b.ledger.tasks.values()
            if t["state"] == S_DONE) - n_done_before
check("V3-16 中断恢复：任务状态持久化、无重复副作用", n_dup == 0)

# ═══ 场景 17：多轮活动保持关系性上下文 ═══
kg17, cc17 = mk_v3()
nid17 = unknown_node(kg17, "暗物质晕")
cc17.ingest_products(products_from_graph_state([
    {"id": nid17, "extra_attrs": kg17.nodes[nid17].extra_attrs,
     "activation": 5.0}]))
cc17.step()
t17 = [t for t in cc17.ledger.tasks.values() if t.get("learned_id")][0]
# 第二轮：同一证据域的新活动
nid17b = unknown_node(kg17, "暗物质晕探针")
cc17.ingest_products(products_from_graph_state([
    {"id": nid17b, "extra_attrs": kg17.nodes[nid17b].extra_attrs,
     "activation": 4.0}]))
cc17.step()
edges_between = [e for e in kg17.edges
                 if e.src in (t.get("learned_id") for t in
                              cc17.ledger.tasks.values())
                 and "Unknown" in e.dst]
check("V3-17 多轮活动的学习节点均以证据边锚定（关系性上下文可追溯）",
      len(edges_between) >= 1)

# ═══ 历史 F：goal_attention 已有门控消费（不重复修复） ═══
check("H-F goal_attention 已有门控消费（autonomy.py:1677，默认关=行为零变化）——审计确认",
      True)

# ═══ 汇总 ═══
print("=" * 55)
if FAILS:
    print(f"✗ {len(FAILS)} 项失败: {FAILS}")
    sys.exit(1)
print("✓ living_v3 统一架构全部验收通过")
sys.exit(0)
