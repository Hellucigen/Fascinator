# -*- coding: utf-8 -*-
"""受体敏感度可塑性闸门（2026-10-16 统一校准 §3.3/§3.4）。

不变量：敏化按次不按幅（无正反馈）、有界、相反经历减敏、静置恢复、
持久化往返、modulator_field("sensitivity") 单一真源。
"""
import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C                                        # noqa: E402
from graph_model import KnowledgeGraph, Node              # noqa: E402
from internal_state import (InternalState, SENSITIZE_CAP, # noqa: E402
                            SENSITIZE_STEP_PER_PULSE,
                            SENSITIVITY_CEIL, SENSITIVITY_FLOOR)


def build():
    cfg = copy.deepcopy(C.DEFAULT_CONFIG)
    kg = KnowledgeGraph()
    kg.add_node(Node(id="Self", label="declarative-semantic",
                     graph_space="self", weight=1.0))
    return InternalState(kg=kg, config=cfg,
                         data_dir=tempfile.mkdtemp()), kg


def test_count_driven_step():
    st, _ = build()
    st.pulse("dopamine", 0.5, reason="t")
    sz1 = st._modulators["dopamine"]["sensitization"]
    assert abs(sz1 - SENSITIZE_STEP_PER_PULSE) < 1e-6
    st.pulse("dopamine", 0.5, reason="t")
    assert abs(st._modulators["dopamine"]["sensitization"] - 2 * sz1) < 1e-6


def test_amplitude_does_not_drive_sensitization():
    st, _ = build()
    st.pulse("dopamine", 0.01, reason="tiny")
    a = st._modulators["dopamine"]["sensitization"]
    st.pulse("dopamine", 0.9, reason="big")
    b = st._modulators["dopamine"]["sensitization"]
    assert abs(a - SENSITIZE_STEP_PER_PULSE) < 1e-6
    assert abs(b - 2 * SENSITIZE_STEP_PER_PULSE) < 1e-6


def test_bounded_no_explosion():
    st, _ = build()
    for _i in range(200):
        st.pulse("dopamine", 0.5, reason="spam")
    sz = st._modulators["dopamine"]["sensitization"]
    eff = st.modulator_field("dopamine", "sensitivity")
    assert abs(sz) <= SENSITIZE_CAP + 1e-6
    assert SENSITIVITY_FLOOR - 1e-6 <= eff <= SENSITIVITY_CEIL + 1e-6


def test_opposite_experience_desensitizes():
    st, _ = build()
    for _i in range(5):
        st.pulse("dopamine", 0.5, reason="t")
    before = st._modulators["dopamine"]["sensitization"]
    st.pulse("dopamine", -0.5, reason="opposite")
    assert st._modulators["dopamine"]["sensitization"] < before


def test_recovery_when_events_stop():
    st, _ = build()
    st.pulse("dopamine", 0.5, reason="t")
    st.tick_decay(now=st._now() + 8 * 3600)
    sz = st._modulators["dopamine"]["sensitization"]
    assert sz < SENSITIZE_STEP_PER_PULSE * 0.75


def test_persistence_roundtrip():
    st, _ = build()
    st.pulse("dopamine", 0.5, reason="t")
    st.pulse("dopamine", 0.5, reason="t")
    st.pulse("dopamine", 0.5, reason="t")
    target = st._modulators["dopamine"]["sensitization"]
    st.save()
    st2, _ = build()
    st2.path = st.path          # 同一状态目录：模拟重启
    st2._load()
    assert abs(st2._modulators["dopamine"]["sensitization"] - target) < 1e-6


def test_single_source_of_truth():
    st, _ = build()
    st.pulse("dopamine", 0.5, reason="t")
    raw = st._modulators["dopamine"].get("sensitivity", 1.0)
    eff = st.modulator_field("dopamine", "sensitivity")
    sz = st._modulators["dopamine"]["sensitization"]
    assert eff != raw
    assert abs(eff - raw * (1 + sz)) < 1e-6
