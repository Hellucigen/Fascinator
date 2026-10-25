# test_hebbian_bounds.py — Hebbian 封顶跨重启恒定性（2026-10-19 实验A/B 钉）
# ============================================================================
# 实锤缺陷（修复前）：基线只活在运行时（_hebb_w0 不落盘），每次重启以
# 已膨胀权重为新基线，封顶随基线漂移——每会话恰 +50%，30 个模拟会话把
# 0.4 的语义边推到 2.30、把 0.5 的喜欢边（无任何兑现行为）推到同值。
# 修复：首见基线持久化 edge.extra_attrs["hebb_w0"]（to_dict 全量往返），
# 封顶 min(|w0|×(1+max_gain), 2.0)。
# 运行: python -X utf8 -m pytest tests/test_hebbian_bounds.py
# ============================================================================
import sys, os, json, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

from graph_model import KnowledgeGraph, Node, Edge
from diffusion_engine import DiffusionEngine

CFG = {"hebbian": {"enabled": True, "epsilon": 0.0015, "max_gain": 0.5,
                   "categories": ["semantic_relation", "emotional_relation"]}}


def _fresh_pair(edge_dict):
    """模拟"重启加载"：走真实序列化往返（to_dict→json→from_dict）。"""
    e = Edge.from_dict(json.loads(json.dumps(edge_dict)))
    kg = KnowledgeGraph()
    kg.add_node(Node(id="甲", graph_space="semantic"))
    kg.add_node(Node(id="乙", graph_space="semantic"))
    kg.add_edge(e)
    eng = DiffusionEngine.__new__(DiffusionEngine)   # 避开重型 __init__
    eng.config = CFG
    eng._hebb_w0 = {}
    return kg, eng


def _load_session(edge_dict, rounds=200):
    kg, eng = _fresh_pair(edge_dict)
    src = kg.get_node("甲")
    src.activation = 5.0
    edge = kg.edges[0]
    for _ in range(rounds):
        eng._hebbian(edge, src)
    return edge.to_dict(), edge.weight


def _make_edge(relation, cat, seed):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="甲")); kg.add_node(Node(id="乙"))
    e = Edge(src="甲", dst="乙", relation=relation, weight=seed)
    e.relation_category = cat
    kg.add_edge(e)
    return kg.edges[0].to_dict()


def test_ratchet_is_dead_semantic():
    """0.4 语义边跨 10 次重启：封顶恒为 0.6（旧实现会到 2.1+）。"""
    d = _make_edge("相关", "semantic_relation", 0.4)
    w = None
    for _ in range(10):
        d, w = _load_session(d)
    assert abs(w - 0.6) < 1e-9, w


def test_ratchet_is_dead_emotional_liking():
    """喜欢边同样被钉在 1.5×首见：自然偏好强化保留、无界膨胀终止。"""
    d = _make_edge("喜欢", "emotional_relation", 0.5)
    w = None
    for _ in range(10):
        d, w = _load_session(d)
    assert abs(w - 0.75) < 1e-9, w
    assert float(d["extra_attrs"]["hebb_w0"]) == 0.5   # 基线可追溯


def test_baseline_survives_serialization():
    d = _make_edge("相关", "semantic_relation", 0.4)
    d, w1 = _load_session(d)
    assert d["extra_attrs"].get("hebb_w0") == 0.4
    d2 = json.loads(json.dumps(d))                     # 磁盘往返
    assert d2["extra_attrs"]["hebb_w0"] == 0.4


def test_legacy_inflated_edge_capped_once():
    """存量棘轮边（修复前已膨胀、无 hebb_w0）：绝对钳使其原地钉死，
    连最后一轮涨幅都不给（1.9 起步则最多多涨一轮 max_gain 到 2.0）。"""
    d = _make_edge("相关", "semantic_relation", 2.0)   # 已是重灾值
    for _ in range(5):
        d, w = _load_session(d)
    assert w == 2.0
    d = _make_edge("相关", "semantic_relation", 1.9)
    w = None
    for _ in range(3):
        d, w = _load_session(d)
    assert w == 2.0                                     # min(1.5×1.9, 2.0)


def test_absolute_clamp_two():
    d = _make_edge("相关", "semantic_relation", 1.9)
    w = None
    for _ in range(10):
        d, w = _load_session(d)
    assert w <= 2.0 + 1e-9, w


def test_disabled_flag_exact_noop():
    cfg = json.loads(json.dumps(CFG)); cfg["hebbian"]["enabled"] = False
    kg, eng = _fresh_pair(_make_edge("相关", "semantic_relation", 0.4))
    eng.config = cfg
    kg.get_node("甲").activation = 5.0
    before = kg.edges[0].weight
    for _ in range(50):
        eng._hebbian(kg.edges[0], kg.get_node("甲"))
    assert kg.edges[0].weight == before


def test_whitelist_outside_untouched():
    kg, eng = _fresh_pair(_make_edge("导致", "causal_relation", 0.4))
    kg.get_node("甲").activation = 5.0
    for _ in range(50):
        eng._hebbian(kg.edges[0], kg.get_node("甲"))
    assert kg.edges[0].weight == 0.4
    assert "hebb_w0" not in (kg.edges[0].extra_attrs or {})
