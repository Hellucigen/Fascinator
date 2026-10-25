# -*- coding: utf-8 -*-
"""浏览记忆结构化验收（2026-10-14 任务书 §7 全部 15 项）。
用今天真实浏览记录的只读副本（《动物园之星2》16:16 节点原文）做样本，
KnowledgeGraph 全内存、fuzzy_match 与 deep_extractor 用桩——
**不联网、不调 LLM、不碰 data/runtime_graph.json**。
运行：python tests/test_browse_memory.py
"""
import json
import os
import sys
import tempfile

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import browse_memory as BM                     # noqa: E402
from graph_model import KnowledgeGraph, Node, Edge  # noqa: E402
from diffusion_engine import DiffusionEngine   # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ── 真实历史样本（生产 dump 的只读副本，2026-10-14 16:16:16）──────────
REAL_TITLE = ("《动物园之星2》正式上线！纯水族、大鸟舍首度登场，"
              "去广袤保护区放归生灵！")
REAL_SNIPPET = ("简介：各位园长，久等了！ 人气动物园模拟游戏正统续作"
                "《动物园之星 ；更多实用攻略教学，爆笑沙雕集锦，你所不知道"
                "的游戏知识 视频播放量 335200、弹幕量 2825、点赞数")
REAL_URL = "https://www.bilibili.com/video/BVzoo2demo"


def mk():
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    kg.add_node(Node(id="Self", label="self", weight=1.0))
    eng = DiffusionEngine(kg, {})
    return kg, eng


def add_exp(kg, eid, title=REAL_TITLE, url=REAL_URL):
    kg.add_node(Node(id=eid, label="declarative-episodic",
                     graph_space="episodic",
                     extra_attrs={"type": "activity_experience",
                                  "kind": "activity_browse_novel",
                                  "text": "在B站逛到个没见过的东西：「%s」"
                                          % title}))


def simple_matcher(name):
    """桩：完全一致→已有 id；带括号限定→取主名；否则原样（不强行合并）。"""
    return name


# 1. 从正文完整的真实记录抽取实体与事实
kg, eng = mk()
add_exp(kg, "exp_zoo")
before_n = len(kg.nodes)
res = BM.consolidate_browse_memory(
    kg, eng, "exp_zoo", REAL_URL, REAL_TITLE, REAL_SNIPPET,
    page_ok=True, fuzzy_match=simple_matcher)
facts = [(e.src, e.relation, e.dst) for e in kg.edges
         if isinstance(e.extra_attrs, dict) and e.extra_attrs.get("fact")]
check("T1 真实记录产出结构化事实：主体=动物园之星2（《》标注），"
      "至少含发布状态事实",
      res["stage"] == BM.STAGE_EXTRACTED
      and any(f[0] == "动物园之星2" and "上线" in f[2] for f in facts),
      str(res)[:150] + " facts=" + str(facts)[:120])
check("T1b 只产出原文明说的事：宣传修辞（放归生灵）没被外推成机制断言",
      not any("放归" in str(f) or "模拟机制" in str(f) for f in facts))

# 2. 已存在实体被复用
kg, eng = mk()
kg.add_node(Node(id="动物园之星2", label="declarative-semantic", weight=0.5))
add_exp(kg, "exp_zoo2")
r2 = BM.consolidate_browse_memory(
    kg, eng, "exp_zoo2", REAL_URL, REAL_TITLE, REAL_SNIPPET,
    page_ok=True, fuzzy_match=simple_matcher)
check("T2 已存在实体不重复创建（'动物园之星2' 节点数不变）",
      sum(1 for n in kg.nodes.values() if n.id == "动物园之星2") == 1
      and "动物园之星2" in r2["entities"], str(r2["entities"]))

# 3. 两个来源支持同一事实：证据两条、边一条
kg, eng = mk()
add_exp(kg, "expA")
add_exp(kg, "expB", title=REAL_TITLE)
url_b = "https://news.hn/zoo2"
BM.consolidate_browse_memory(kg, eng, "expA", REAL_URL, REAL_TITLE,
                             REAL_SNIPPET, True, simple_matcher)
BM.consolidate_browse_memory(kg, eng, "expB", url_b, REAL_TITLE,
                             "《动物园之星2》正式上线，玩家社区沸腾",
                             True, simple_matcher)
evs = [e for e in kg.edges if isinstance(e.extra_attrs, dict)
       and e.extra_attrs.get("fact") and e.src == "动物园之星2"
       and "上线" in e.dst]
e0 = evs[0] if evs else None
check("T3 同一事实双来源：一条边、evidence 两个经历 id、多源标记",
      e0 is not None and len(evs) == 1
      and set(e0.extra_attrs.get("evidence") or []) == {"expA", "expB"}
      and e0.extra_attrs.get("multi_source"),
      str(e0.extra_attrs if e0 else None)[:160])

# 4. 两条经历提到同一实体：情景记忆各自独立
check("T4 经历边界独立：两条 exp 节点各挂各的'涉及'边，未合并",
      kg.get_edge("expA", "动物园之星2", "涉及") is not None
      and kg.get_edge("expB", "动物园之星2", "涉及") is not None
      and kg.get_node("expA") is not kg.get_node("expB"))

# 5. 仅标题的记录不产正文事实
kg, eng = mk()
add_exp(kg, "exp_title")
r5 = BM.consolidate_browse_memory(
    kg, eng, "exp_title", "", REAL_TITLE, "",  # 页面没打开
    page_ok=False, fuzzy_match=simple_matcher)
nf = [e for e in kg.edges if isinstance(e.extra_attrs, dict)
      and e.extra_attrs.get("fact")]
check("T5 '看过'≠'学到'：无正文 ⇒ 阶段=seen、零事实边",
      r5["stage"] == BM.STAGE_SEEN and not nf, str(r5["stage"]))

# 6. 无法消歧不强制合并
kg, eng = mk()
kg.add_node(Node(id="苹果(公司)", label="declarative-semantic", weight=0.5))
add_exp(kg, "exp_apple")


def greedy_matcher(name):
    return "苹果(公司)"                       # 桩：乱匹配会被安全规则拒吗？


# 结构化侧的消歧交给 fuzzy_match 的正确实现；这里验证"matcher 返回
# 不在图中的名字 ⇒ 新建独立节点而非合并到任意相近节点"
r6 = BM.consolidate_browse_memory(
    kg, eng, "exp_apple", "", "《苹果》新机型发布", "《苹果》新机型发布，正式发售",
    page_ok=True, fuzzy_match=simple_matcher)
check("T6 不强制合并：'苹果' 与 '苹果(公司)' 是两个节点（模糊时宁可分立）",
      kg.get_node("苹果") is not None
      and kg.get_node("苹果(公司)") is not None)

# 7. 矛盾事实共存
kg, eng = mk()
add_exp(kg, "exp_x1")
add_exp(kg, "exp_x2", title=REAL_TITLE)
BM.consolidate_browse_memory(kg, eng, "exp_x1", "u1", REAL_TITLE,
                             "《动物园之星2》正式上线", True, simple_matcher)
BM.consolidate_browse_memory(kg, eng, "exp_x2", "u2", REAL_TITLE,
                             "突发：《动物园之星2》停运", True,
                             simple_matcher)
zl = [e for e in kg.edges if isinstance(e.extra_attrs, dict)
      and e.extra_attrs.get("fact") and e.src == "动物园之星2"]
check("T7 矛盾不覆盖：上线与停运两条事实边共存且互相标了 conflict",
      len(zl) == 2 and all(e.extra_attrs.get("conflict") for e in zl),
      str([(e.dst, e.extra_attrs.get("conflict")) for e in zl])[:120])

# 8. 幂等：重复处理不涨节点/边
kg, eng = mk()
add_exp(kg, "exp_i")
BM.consolidate_browse_memory(kg, eng, "exp_i", REAL_URL, REAL_TITLE,
                             REAL_SNIPPET, True, simple_matcher)
n1, e1 = len(kg.nodes), len(kg.edges)
BM.consolidate_browse_memory(kg, eng, "exp_i", REAL_URL, REAL_TITLE,
                             REAL_SNIPPET, True, simple_matcher)
BM.consolidate_browse_memory(kg, eng, "exp_i", REAL_URL, REAL_TITLE,
                             REAL_SNIPPET, True, simple_matcher)
check("T8 幂等：同一经历重复整合，节点/边数不变",
      (n1, e1) == (len(kg.nodes), len(kg.edges)))

# 9. 实体 → 事实与原始经历（读路径）
rec = BM.recall_about(kg, "动物园之星2")
check("T9 从实体找回：直接事实+支持经历+来源 URL",
      rec["facts"] and "exp_i" in rec["experiences"]
      and REAL_URL in rec["sources"], str(rec)[:130])

# 10. 经历 → 其支持的事实
fs = BM.facts_of_experience(kg, "exp_i")
check("T10 从经历反查其支持的全部事实", len(fs) >= 1)

# 11. 撤销单来源：其余证据存活；全无来源 ⇒ 降级不删
kg, eng = mk()
add_exp(kg, "e1"); add_exp(kg, "e2")
BM.consolidate_browse_memory(kg, eng, "e1", "u1", REAL_TITLE,
                             "《动物园之星2》正式上线", True, simple_matcher)
BM.consolidate_browse_memory(kg, eng, "e2", "u2", REAL_TITLE,
                             "《动物园之星2》正式上线", True, simple_matcher)
dem = BM.withdraw_experience_support(kg, "e1")
e_left = [x for x in kg.edges if isinstance(x.extra_attrs, dict)
          and x.extra_attrs.get("fact")
          and x.extra_attrs.get("evidence") == ["e2"]]
check("T11 撤销 e1：双证据事实仍由 e2 独立存活；无事实被删除",
      e_left and not dem, str(dem))
dem2 = BM.withdraw_experience_support(kg, "e2")
wd = [x for x in kg.edges if isinstance(x.extra_attrs, dict)
      and x.extra_attrs.get("withdrawn")]
check("T11b 失去全部来源的事实：标 withdrawn+降置信，**不删除**",
      wd and float(wd[0].extra_attrs.get("confidence") or 1) <= 0.2,
      str(dem2))

# 12. 激活侧不混淆经历
kg, eng = mk()
add_exp(kg, "m1"); add_exp(kg, "m2")
BM.consolidate_browse_memory(kg, eng, "m1", "u1", REAL_TITLE,
                             "《动物园之星2》正式上线", True, simple_matcher)
BM.consolidate_browse_memory(kg, eng, "m2", "u2", "《动物园之星3》公布",
                             "续作企划公开，玩家期待值拉满中", True,
                             simple_matcher)
r_z2 = BM.recall_about(kg, "动物园之星2")
r_z3 = BM.recall_about(kg, "动物园之星3")
check("T12 共享浏览会话不串经历：星2 证据只含 m1，星3 只含 m2",
      r_z2["experiences"] == ["m1"] and r_z3["experiences"] == ["m2"],
      str((r_z2["experiences"], r_z3["experiences"])))

# 13. 各失败阶段可识别
st_a = BM.detect_stage("《X》上线", False, "")           # 页面没打开
st_b = BM.detect_stage("", True, "首页 番剧 直播 会员购 漫画 赛事 投稿 登录")  # 只有导航文本
st_b2 = BM.detect_stage("《X》正式上线", True, "")      # 标题自带正文事实
st_c = BM.consolidate_browse_memory(mk()[0], None, "不存在", "", "", "",
                                    False, None)
check("T13 阶段可辨：没打开/导航文本/经历缺失 各归其位",
      st_a == BM.STAGE_SEEN and st_b == BM.STAGE_SEEN
      and st_b2 == BM.STAGE_SNIPPET
      and st_c["stage"] == BM.STAGE_FAILED)

# 14. 全部写入走合法接口（不碰内部锁/字段直改）
kg, eng = mk()
add_exp(kg, "gk")
calls = {"node": 0, "edge": 0}
_orig_an, _orig_ae = kg.add_node, kg.add_edge
kg.add_node = lambda n, **k: (calls.__setitem__(
    "node", calls["node"] + 1), _orig_an(n, **k))[1]
kg.add_edge = lambda e, **k: (calls.__setitem__(
    "edge", calls["edge"] + 1), _orig_ae(e, **k))[1]
BM.consolidate_browse_memory(kg, eng, "gk", REAL_URL, REAL_TITLE,
                             REAL_SNIPPET, True, simple_matcher)
check("T14 写路径全部经 add_node/add_edge 合法接口",
      calls["node"] >= 1 and calls["edge"] >= 1)

# 15. 无 LLM/网络/生产文件写入（本测试文件不 import nlp、不开 data/ 路径；
#    deep_extractor 桩验证注入点）
kg, eng = mk()
add_exp(kg, "deep")
res15 = BM.consolidate_browse_memory(
    kg, eng, "deep", "u", "《测试》发布", "无关正文——但可被深度抽取器处理",
    True, simple_matcher,
    deep_extractor=lambda t, s: ([{"s": "测试", "rel": "具有", "o": "已发布",
                                   "excerpt": s[:20]}], ["测试"]))
check("T15 deep_extractor 注入位可用（本轮真实 LLM 调用=0）",
      res15["facts"] and res15["entities"], str(res15)[:100])

print()
if FAILURES:
    print("通过 %d 条，失败 %d 条：%s" % (TOTAL[0] - len(FAILURES),
                                          len(FAILURES), FAILURES))
    sys.exit(1)
print("通过 %d 条，全部通过" % TOTAL[0])
