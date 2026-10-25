# -*- coding: utf-8 -*-
"""事项D：调研复燃的"新证据"不得是她自己的表达痕迹/念头/假设。

台账实锤：living_ledger 里 consumed_evidence=['假设：Minecraft会话与组胺样']
——假设节点把自己喂成了"搞清楚这个假设"的复燃证据（Minecraft×SocialDrive
回声室同型）。_emerge_hypotheses 早有同类过滤器但两处不共享，且其类型黑名单
写的是 "expression" 而 EXPR_TYPE 实为 "expression_event"。
现在统一走 activities._semantic_anchor_ok，复燃证据回路同享。"""
import os
import sys
import time
import json
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))
import logging                                    # noqa: E402
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node      # noqa: E402
import activities                                 # noqa: E402


def _mk_node(kg, nid, ntype, text, born_ago_s=3600,
             label="declarative-episodic"):
    kg.add_node(Node(id=nid, weight=0.5, label=label,
                     graph_space="episodic",
                     created=time.strftime(
                         "%Y-%m-%d %H:%M:%S",
                         time.localtime(time.time() - born_ago_s)),
                     extra_attrs={"type": ntype, "text": text}))


def _world(extra_nodes):
    """paused 调研「搞清楚组胺样」于 2h 前；extra_nodes 是本拍图上的候选证据。"""
    td = tempfile.mkdtemp(prefix="fas_rekindle_")
    with open(os.path.join(td, "living_ledger.json"), "w",
              encoding="utf-8") as f:
        json.dump({"activities": [{
            "id": "life_test_1", "topic": "搞清楚组胺样",
            "concept": "组胺样", "state": "paused",
            "created": time.time() - 7200, "updated": time.time() - 7200,
            "consumed_evidence": [], "methods_tried": []}],
            "experiences": [], "share_candidates": [],
            "daily_web_calls": {}}, f)
    os.environ["FAS_LIVING_DATA_DIR"] = td
    kg = KnowledgeGraph()
    kg.add_node(Node(id="组胺样", weight=0.4, label="declarative-semantic",
                     graph_space="semantic"))
    for spec in extra_nodes:
        _mk_node(kg, *spec)
    return kg, td


def _rekindle_hits(kg):
    out = activities._graph_strength({"kg": kg, "config": {},
                                      "engine": None, "gaps": []})
    return [(c, k, ev) for c, s, k, ev in out if k == "paused_rekindle"]


def test_expression_node_is_not_rekindle_evidence():
    """她自己的表达事件（含主题词）→ 不得复燃调研。"""
    kg, td = _world([("表达_20261019120000001", "expression_event",
                      "组胺样的机制挺有意思，我刚才说了")])
    try:
        assert _rekindle_hits(kg) == []
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_hypothesis_node_is_not_rekindle_evidence():
    """别的假设节点同样不行（台账实锤的那条路径）。"""
    kg, td = _world([("假设：用户与组胺样", "hypothesis",
                      "用户和组胺样有没有关系")])
    try:
        assert _rekindle_hits(kg) == []
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_user_utterance_still_is_valid_evidence():
    """用户话语（话语_/utterance_event）是环境新信息——必须照常能复燃
    （任务书问的"误伤有效证据"就在这条边界上）。"""
    kg, td = _world([("话语_20261019_115900_000", "utterance_event",
                      "组胺样到底是什么 帮我查查")])
    try:
        hits = _rekindle_hits(kg)
        assert hits and hits[0][0] == "组胺样", hits
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_user_expression_event_valid_too():
    """expression_feedback 建的用户表达事件（user_expression_event）
    也属于用户侧，不该被黑名单误伤。"""
    kg, td = _world([("用户表达_20261019120500002",
                      "user_expression_event", "组胺样 是什么")])
    try:
        hits = _rekindle_hits(kg)
        assert hits, hits
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_plain_concept_remains_valid():
    """外部学习来的普通语义节点不受影响。"""
    kg, td = _world([("肥大细胞", "concept", "肥大细胞释放组胺样物质",
                      3600, "declarative-semantic")])
    try:
        hits = _rekindle_hits(kg)
        assert hits, hits
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_shared_filter_single_source():
    """两处消费者共用同一函数（防漂移回归钉）。"""
    src = open(os.path.join(_ROOT, "activities.py"), encoding="utf-8").read()
    assert src.count("def _anchor_ok(") == 0        # 内嵌版已删
    assert "not in _TRACE_TYPES" not in src          # 旧类型集已并入
    assert src.count("_semantic_anchor_ok(") >= 2   # 复燃回路 + emerge 桥接


if __name__ == "__main__":
    fails = 0
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"复燃证据过滤：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
