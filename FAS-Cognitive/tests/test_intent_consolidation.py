# -*- coding: utf-8 -*-
"""反刍固化闸门（2026-10-16）：被反复温和的念头衰减更慢，但收敛有界。
断言 _decay_intentions 的真实衰减率，非模拟函数。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node                  # noqa: E402
from continuous_cognition import ContinuousCognition, ST_READY  # noqa: E402

import pytest


class StubEngine:
    _running = False

    def get_topk(self, k=15):
        return [], []

    def decay_step(self):
        pass

    def diffuse_step(self):
        pass

    def mark_active(self, ids):
        pass

    def register_activation_source(self, ids, source_type="external_input"):
        pass

    def clear_anchors(self):
        pass


class StubNLP:
    def system_prompt(self, task):
        return "SYS"


def mk_cc():
    cfg = {"continuous_cognition": {
        "tick_seconds": 0.01, "form_threshold": 0.5,
        "express_threshold": 0.78, "inhibition_cooldown_s": 0,
        "decay_per_pulse": 0.9, "discard_below": 0.02,
        "max_expressions_per_hour": 6,
        "expression_decision_v2": True}}
    kg = KnowledgeGraph()
    return kg, ContinuousCognition(kg, StubEngine(), StubNLP(), None, cfg)


def seed(kg, nid, reinforced):
    n = Node(id=nid, weight=0.5, graph_space="cognitive",
             extra_attrs={"type": "communication_intention",
                          "status": ST_READY, "kind": "communication",
                          "basis": [], "reinforced": reinforced,
                          "born_pulse": -99, "activation": 0.60})
    kg.add_node(n)
    return n


def test_reinforced_thought_decays_slower():
    kg, cc = mk_cc()
    plain = seed(kg, "CI_plain", 0)
    rumi = seed(kg, "CI_rumination", 12)
    cc._decay_intentions()
    dp = 0.9
    assert plain.extra_attrs['activation'] == pytest.approx(round(0.60 * dp, 4))
    assert rumi.extra_attrs['activation'] > plain.extra_attrs['activation']
    assert rumi.extra_attrs['activation'] == pytest.approx(
        round(0.60 * (1.0 - (1.0 - dp) * (1.0 - 0.05 * 12)), 4))


def test_consolidation_bounded():
    kg, cc = mk_cc()
    max1 = seed(kg, "CI_a", 40)
    max2 = seed(kg, "CI_b", 1000)
    cc._decay_intentions()
    # damp 封顶 0.6 → 有效衰减率 0.94，reinforced 再大也不再变
    assert max1.extra_attrs["activation"] == pytest.approx(max2.extra_attrs["activation"])
    assert max1.extra_attrs["activation"] <= round(0.60 * 0.96, 4) + 1e-9


def test_no_reinforced_field_is_old_behavior():
    kg, cc = mk_cc()
    n = Node(id="CI_legacy", weight=0.5, graph_space="cognitive",
             extra_attrs={"type": "communication_intention",
                          "status": ST_READY, "kind": "communication",
                          "basis": [], "born_pulse": -99,
                          "activation": 0.60})
    kg.add_node(n)
    cc._decay_intentions()
    assert n.extra_attrs['activation'] == pytest.approx(0.54)


# ── reinforced 语义（2026-10-16）：扫描/选中频率 ≠ 有意义的认知重访 ────────
# 旧缺陷实测：CI_136216572 reinforced=29 而激活 0.0 —— 计数来自每拍焦点
# 扫描的 basis 重叠命中，不是重访。现在只有"间隔后强度创下比上次强化高
# ≥eps 的新高分"才计一次，且强化速率与扫描节拍解耦。

import time                                    # noqa: E402

KINDS = {"communication": 0.5, "exploration": 0.1}


def form_ci(cc, kg, score=0.8):
    kg.add_node(Node(id="焦点x", weight=0.7, graph_space="semantic"))
    cc._merge_or_form([kg.nodes["焦点x"]], score, {"t": 1}, KINDS, {})
    cis = cc._active_intentions()
    assert len(cis) == 1, str(cis)
    return cis[0]


def test_repeat_scan_does_not_farm_reinforced():
    kg, cc = mk_cc()
    ci = form_ci(cc, kg, 0.8)
    act0 = ci.extra_attrs["activation"]
    for _ in range(5):                         # 同一焦点反复被扫描/选中
        cc._merge_or_form([kg.nodes["焦点x"]], 0.8, {"t": 1}, KINDS, {})
    ea = ci.extra_attrs
    assert int(ea.get("reinforced", 0)) == 0   # 不刷计数
    assert ea["activation"] == pytest.approx(act0)   # 白送 +0.06 地板已移除
    assert abs(float(ea["score"]) - 0.8) < 1e-9      # 台账仍跟踪当前焦点
    assert int(ea.get("reinforced", 0)) == 0 and "rehearsal_base" in ea


def test_meaningful_rehearsal_counts_once():
    kg, cc = mk_cc()
    ci = form_ci(cc, kg, 0.8)
    ea = ci.extra_attrs
    ea["born_ts"] = time.time() - 200          # 距上次强化已过最小间隔
    cc._merge_or_form([kg.nodes["焦点x"]], 0.9, {"t": 2}, KINDS, {})
    assert int(ea["reinforced"]) == 1
    assert ea["activation"] == pytest.approx(0.8 + 0.5 * 0.1 + 0.06)
    assert float(ea["rehearsal_base"]) == pytest.approx(0.9)
    # 再创新高但间隔未到 → 不重复计（强化速率与扫描节拍解耦）
    cc._merge_or_form([kg.nodes["焦点x"]], 1.0, {"t": 3}, KINDS, {})
    assert int(ea["reinforced"]) == 1
    # 上涨未被消费就一直等在那里：间隔到后结算——新信息复活旧话题不丢
    ea["last_boosted_ts"] = time.time() - 200
    cc._merge_or_form([kg.nodes["焦点x"]], 1.0, {"t": 4}, KINDS, {})
    assert int(ea["reinforced"]) == 2
    assert ea["activation"] == pytest.approx(1.0)  # 封顶仍有界


def test_rehearsal_bound_per_gap():
    # 每个间隔窗口至多一次强化：连续 10 拍扫描只结算 1 次
    kg, cc = mk_cc()
    ci = form_ci(cc, kg, 0.8)
    ea = ci.extra_attrs
    ea["born_ts"] = time.time() - 200
    rising = [0.85, 0.9, 0.95, 1.0]
    for s in rising:
        for _ in range(10):
            cc._merge_or_form([kg.nodes["焦点x"]], s, {"t": 1}, KINDS, {})
    assert int(ea["reinforced"]) == 1, str(ea["reinforced"])


def test_expressed_terminal_no_self_reinforcement():
    # 说过的念头是终态：既不吃衰减（不会固化续命），也不会被再扫描强化
    from continuous_cognition import ST_EXPRESSED
    kg, cc = mk_cc()
    kg.add_node(Node(id="焦点x", weight=0.7, graph_space="semantic"))
    done = Node(id="CI_done", weight=0.5, graph_space="self",
                extra_attrs={"type": "communication_intention",
                             "status": ST_EXPRESSED, "kind": "communication",
                             "basis": ["焦点x"], "reinforced": 0, "score": 0.8,
                             "activation": 0.9, "born_pulse": -99,
                             "expressed_at_ts": time.time()})
    kg.add_node(done)
    cc._merge_or_form([kg.nodes["焦点x"]], 1.0, {"t": 1}, KINDS, {})
    assert int(done.extra_attrs["reinforced"]) == 0    # 终态不可再强化
    assert done.extra_attrs["activation"] == 0.9       # 未被命中改写
    a0 = done.extra_attrs["activation"]
    cc._decay_intentions()
    assert done.extra_attrs["activation"] == a0        # 终态不吃衰减
