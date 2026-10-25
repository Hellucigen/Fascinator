# -*- coding: utf-8 -*-
"""新增生活活动：复盘/读本地/望桌面（2026-10-19）。
tmp 数据目录 + 桥打桩 + 内存图；不触生产、不联网、零 LLM。"""
import json
import os
import sys
import tempfile
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "FAS-Cognitive"))
import logging                                   # noqa: E402
logging.disable(logging.WARNING)

import activities                                # noqa: E402
from graph_model import KnowledgeGraph, Node    # noqa: E402


class Eng:
    def mark_active(self, ids): pass
    def register_activation_source(self, ids, st=None): pass
    def get_topk(self, k=15): return [], []


def _ctx(**cfg):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="用户", weight=1.0, graph_space="semantic"))
    c = {"config": dict(cfg), "kg": kg, "engine": Eng()}
    return c


def _datadir(tmp):
    os.environ["FAS_LIVING_DATA_DIR"] = tmp
    return tmp


def _seed(tmp, ledger_acts, chat):
    json.dump({"activities": ledger_acts, "experiences": [],
               "share_candidates": [], "daily_web_calls": {}},
              open(os.path.join(tmp, "living_ledger.json"), "w",
                   encoding="utf-8"))
    json.dump(chat, open(os.path.join(tmp, "chat_log.json"), "w",
                         encoding="utf-8"))


def test_review_appeal_and_beat_and_quiet():
    tmp = tempfile.mkdtemp(prefix="fb_rev_")
    _datadir(tmp)
    try:
        now = time.time()
        iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 600))
        _seed(tmp, [{"id": "a1", "topic": "搞清楚「甲」", "state": "completed",
                     "updated": now - 900, "created": now - 900}],
              [{"time": iso, "user_input": "(主动)",
                "system_response": "我说了一句", "proactive": True},
               {"time": iso, "user_input": "用户问了",
                "system_response": "我答了"}])
        st = {}
        ap = activities._review_appeal(_ctx(), st)
        assert ap > 0.12, ap
        sent = []
        orig = activities._journal_send
        activities._journal_send = lambda t, g: sent.append(t) or True
        try:
            r = activities.review_beat(_ctx(), st)
        finally:
            activities._journal_send = orig
        assert r["result"] == "ok" and sent and "复盘" in sent[0]
        assert st["review"]["last_ts"] > now - 5
        # 消化完之后欲望归零（不为复盘制造事）
        assert activities._review_appeal(_ctx(), st) == 0.0
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_read_dormant_then_reads_with_facts():
    assert activities.read_available(_ctx()) == (False, ) + tuple() or \
        activities.read_available(_ctx())[0] is False   # 默认休眠
    tmp = _datadir(tempfile.mkdtemp(prefix="fb_rd_"))
    rd = tempfile.mkdtemp(prefix="fb_rdir_")
    with open(os.path.join(rd, "游戏公告.md"), "w", encoding="utf-8") as f:
        f.write("《星露谷物语1.6》正式上线，新增若干机制。")
    try:
        ctx = _ctx(self_reading_dirs=[rd])
        assert activities.read_available(ctx)[0] is True
        assert activities._read_appeal(ctx, {}) > 0.12
        st = {}
        r = activities.read_beat(ctx, st)
        assert r["result"] == "ok"
        exps = [n for n in ctx["kg"].nodes.values()
                if (n.extra_attrs or {}).get("type") == "activity_experience"
                and "self_read" in str((n.extra_attrs or {}).get("kind"))]
        assert exps, "读了要有经历节点"
        fact = [e for e in ctx["kg"].edges
                if (e.extra_attrs or {}).get("fact")]
        assert fact and fact[0].dst == "已上线", \
            "规则抽取链路复用应产出 具有-已上线"
        assert st["self_read"]["seen"]
        r2 = activities.read_beat(ctx, st)
        assert r2["result"] == "nothing_new"        # 读完不重复吃
    finally:
        os.environ.pop("FAS_LIVING_DATA_DIR", None)


def test_watch_permission_and_freshness():
    assert activities.watch_available(_ctx())[0] is False   # 隐私默认
    ctx = _ctx(screen_observe_enabled=True)
    assert activities.watch_available(ctx)[0] is True
    import screen_watch
    old = dict(screen_watch._STATE)
    try:
        screen_watch._STATE["last_result"] = {"ts": time.time() - 7200}
        r = activities.watch_beat(ctx, {})
        assert r["result"] == "unavailable"        # 陈帧=让位不装看
        screen_watch._STATE["last_result"] = {"ts": time.time() - 30}
        r2 = activities.watch_beat(ctx, {})
        assert r2["result"] == "ok"
    finally:
        screen_watch._STATE.clear()
        screen_watch._STATE.update(old)


def test_tidy_healthy_graph_is_left_alone():
    kg = KnowledgeGraph()
    kg.add_node(Node(id="活", label="declarative-semantic",
                     graph_space="semantic", activation=1.0))
    ctx = {"config": {}, "kg": kg, "engine": Eng()}
    st = {}
    assert activities._tidy_appeal(ctx, st) == 0.0      # 干净=不打扰
    r = activities.tidy_beat(ctx, st)
    assert r["done"] and "last_ts" in st["tidy"]


def test_registered_and_gated():
    names = [n for n, *_ in activities.ACTIVITIES]
    assert {"review", "read", "watch", "tidy"} <= set(names)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"新活动：{len(fns) - fails}/{len(fns)} 通过")
    sys.exit(1 if fails else 0)
