# -*- coding: utf-8 -*-
"""外部内容抽取质量修复（2026-10-19 任务书）端到端离线验收。
覆盖 §九 A-I：具体关系保真 / 否定与状态 / 外部代词 / 截断可观测 /
经历关联边 / 真实链路。全部伪造模型响应，零 LLM、零生产写入。"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))
import logging                                  # noqa: E402
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge   # noqa: E402
import browse_memory as BM                          # noqa: E402
import graph_schema                                 # noqa: E402
import activities                                   # noqa: E402

URL = "https://bilibili.com/video/BV_TEST"


class Eng:
    def mark_active(self, ids): pass


def _world():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="用户", weight=1.0, graph_space="semantic"))
    kg.add_node(Node(id="expA", label="declarative-episodic",
                     graph_space="episodic",
                     extra_attrs={"type": "activity_experience",
                                  "text": "逛到"}))
    return kg


def _cons(kg, title, snippet, deep=None):
    return BM.consolidate_browse_memory(kg, Eng(), "expA", URL, title,
                                        snippet, page_ok=True,
                                        fuzzy_match=lambda x: x,
                                        deep_extractor=deep)


# ── normalize_verbose / add_edge 留痕 ──────────────────────

def test_normalize_verbose_kinds():
    assert graph_schema.normalize_verbose("") == ("关联", "empty")
    assert graph_schema.normalize_verbose("导致")[1] == "canonical"
    assert graph_schema.normalize_verbose("引发") == ("导致", "synonym")
    assert graph_schema.normalize_verbose("制作") == ("关联", "fallback")
    assert graph_schema.FALLBACK_RELATION == "关联"


def test_add_edge_fallback_annotation_observable():
    kg = _world()
    kg.add_node(Node(id="甲", graph_space="semantic"))
    kg.add_node(Node(id="乙", graph_space="semantic"))
    kg.add_edge(Edge(src="甲", dst="乙", relation="拍摄", weight=0.5))
    e = kg.get_edge("甲", "乙", "关联")          # 归一行为不变
    assert e is not None
    assert e.extra_attrs["relation_raw"] == "拍摄"
    assert e.extra_attrs["relation_status"] == "normalized_fallback"


# ── A. 具体关系保留（外部通道不再压平）────────────────────

def test_A_concrete_relations_survive_external_channel():
    kg = _world()
    deep = lambda t, s: (
        [{"s": "弹丸真人视频", "rel": "制作", "o": "上万元成本",
          "excerpt": "花费上万元制作", "method": "deep"},
         {"s": "弹丸真人视频", "rel": "使用", "o": "AI技术",
          "excerpt": "使用了AI技术", "method": "deep"},
         {"s": "弹丸真人视频", "rel": "配音", "o": "真人演员",
          "excerpt": "由某演员配音", "method": "deep"}],
        ["弹丸真人视频"])
    r = _cons(kg, "真人版弹丸论破", "花费上万元制作，使用了AI技术，由某演员配音。",
              deep=deep)
    by_rel = {}
    for e in kg.edges:
        if (e.extra_attrs or {}).get("fact"):
            by_rel[e.relation] = e
    assert "制作" in by_rel and "配音" in by_rel   # 不被压平成 关联
    assert "使用" in by_rel                        # 词表内正常归一
    m = by_rel["制作"]
    assert m.extra_attrs["relation_status"] == "unnormalized"
    assert m.extra_attrs["excerpt"] == "花费上万元制作"
    assert "expA" in m.extra_attrs["evidence"] and m.extra_attrs["url"]
    kinds = {f["rel"]: f["rel_kind"] for f in r["facts"]}
    assert kinds["制作"] == "fallback" and kinds["使用"] == "canonical"


# ── B. 否定事实 ───────────────────────────────────────────

def test_B_negation_blocks_affirmative_rules():
    kg = _world()
    r = _cons(kg, "数毛社：《GTA6》发售预告片并未采用写实方案",
              "官方表示并未采用。")
    facts_written = [e for e in kg.edges if (e.extra_attrs or {}).get("fact")]
    assert facts_written == []                     # 规则被拒且无 deep 注入
    assert any("规则级拒绝[" in s and ("]" in s) for s in r["skipped"])
    assert any("规则未找到明确陈述" in s for s in r["skipped"])


def test_B2_affirmative_still_passes():
    kg = _world()
    BM.consolidate_browse_memory(kg, Eng(), "expA", URL,
                                 "《星露谷物语1.6》正式上线", "更新内容若干",
                                 page_ok=True, fuzzy_match=lambda x: x)
    e = kg.get_edge("星露谷物语1.6", "星露谷物语1.6", "具有") or \
        next((x for x in kg.edges
              if (x.extra_attrs or {}).get("fact")), None)
    assert e is not None and e.relation == "具有"
    assert e.dst == "已上线"


# ── C. 计划与历史状态 ─────────────────────────────────────

def test_C_plan_and_historical_not_current_state():
    kg = _world()
    r = _cons(kg, "《某作品2》计划于明年发售。", "旧版本曾经上线，如今不再更新。")
    facts_written = [e for e in kg.edges if (e.extra_attrs or {}).get("fact")]
    assert facts_written == []                     # 计划≠已发售；历史≠现在
    reasons = " ".join(r["skipped"])
    assert "not_yet" in reasons and "historical" in reasons


# ── D. 外部第一人称 ──────────────────────────────────────

def test_D_external_pronoun_not_mapped_to_user():
    kg = _world()
    deep = lambda t, s: (
        [{"s": "用户", "rel": "花费", "o": "上万元",
          "excerpt": "我花了上万元", "method": "deep"},
         {"s": "某UP主", "rel": "制作", "o": "真人版视频",
          "excerpt": "制作了真人版视频", "method": "deep"}], [])
    r = _cons(kg, "我花了上万元做了个真人版视频", "评论区想看就继续做", deep=deep)
    hub_facts = [e for e in kg.edges if (e.extra_attrs or {}).get("fact")
                 and e.src == "用户"]
    assert hub_facts == []                         # 假主语事实边被端点过滤拒建
    assert any("枢纽端点拒绝事实边" in s for s in r["skipped"])
    up = next((e for e in kg.edges if e.src == "某UP主"), None)
    assert up is not None and up.relation == "制作"  # 真主语照常建边，可追溯


def test_D2_user_self_report_channel_untouched():
    """端点过滤只挂在外部通道；MEMORY_EXTRACT 的用户自述通道不受影响
    ——静态钉：过滤在 browse_memory/reading，app 摄取路径无 HUB_ENTITY_NAMES。"""
    src = open(os.path.join(_ROOT, "browse_memory.py"),
               encoding="utf-8").read()
    assert "HUB_ENTITY_NAMES" in src
    appsrc = open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read()
    assert "HUB_ENTITY_NAMES" not in appsrc


# ── E. 截断可观测 ────────────────────────────────────────

class _FakeNLP:
    def __init__(self, payload):
        self.payload = payload
        self.seen_text = ""

    def extract_assertion_graph(self, text, ctx_nodes=None):
        self.seen_text = text
        return self.payload


def test_E_truncation_is_logged_and_bounded():
    edges = [{"src": "X", "dst": "y%d" % i, "type": "包含", "quote": "q"}
             for i in range(12)] + \
            [{"src": "X", "dst": "z", "type": ""}]          # 空关系 1 条
    nodes = [{"id": "n%d" % i} for i in range(16)]
    nlp = _FakeNLP({"edges": edges, "nodes": nodes})
    logs = []
    fs, es = activities._browse_deep_adapter(
        nlp, "标题", "正文正文", log=logs.append)
    assert len(fs) == 8                                   # 预算 8，不是旧的 4
    assert len(es) <= 8 * 2 + 12                          # 端点+实体封顶
    assert logs and "关系入8/来12(预算8)" in logs[0] and "空关系弃1" in logs[0]


def test_E2_marker_prefix_in_prompt_input():
    nlp = _FakeNLP({"edges": [], "nodes": []})
    activities._browse_deep_adapter(nlp, "标题X", "片段Y")
    assert nlp.seen_text.startswith("【外部材料·非用户自述】")
    assert "标题X" in nlp.seen_text and "片段Y" in nlp.seen_text


# ── F. 经历关联边照常 ────────────────────────────────────

def test_F_experience_involves_edges_still_built():
    kg = _world()
    deep = lambda t, s: ([{"s": "某视频", "rel": "使用", "o": "AI技术",
                           "excerpt": "e", "method": "deep"}],
                         ["某视频", "AI技术"])
    r = _cons(kg, "某视频", "使用了AI技术", deep=deep)
    inv = [e for e in kg.edges if e.src == "expA" and e.relation == "涉及"]
    facts = [e for e in kg.edges if (e.extra_attrs or {}).get("fact")]
    assert len(inv) >= 2 and len(facts) == 1        # 两类边各自存在、互不冒充
    assert r["stage"] == "facts_extracted"


# ── G. 端到端 + 幂等（同一经历二次整合不重复建边）───────

def test_G_end_to_end_idempotent():
    kg = _world()
    deep = lambda t, s: (
        [{"s": "弹丸真人视频", "rel": "采用", "o": "AI配音",
          "excerpt": "采用AI配音", "method": "deep"}], ["弹丸真人视频"])
    r1 = _cons(kg, "真人版弹丸论破", "采用AI配音制作", deep=deep)
    n1 = len([e for e in kg.edges if (e.extra_attrs or {}).get("fact")])
    r2 = _cons(kg, "真人版弹丸论破", "采用AI配音制作", deep=deep)
    n2 = len([e for e in kg.edges if (e.extra_attrs or {}).get("fact")])
    assert n1 == 1 and n2 == 1                       # 幂等：证据合并非新边
    assert r1["facts"][0]["rel_kind"] == "fallback"  # 采用→词表达不了→原词
    e = kg.edges[next(i for i, x in enumerate(kg.edges)
                      if (x.extra_attrs or {}).get("fact"))]
    assert e.relation == "采用" and e.extra_attrs["relation_raw"] == "采用"


# ── I. prompt 两条新规则在位（静态）─────────────────────

def test_I_prompt_rules_present():
    import prompt_templates as pt
    assert "【外部材料·非用户自述】" in pt.MEMORY_EXTRACT
    assert "叙述者归属" in pt.MEMORY_EXTRACT
    assert "不是用户，也不是 Fascinator" in pt.MEMORY_EXTRACT
    assert "优先从下面选" in pt.MEMORY_EXTRACT
    assert "不许为凑词表" in pt.MEMORY_EXTRACT
    assert "必须从下面选一个，不要自创" not in pt.MEMORY_EXTRACT
