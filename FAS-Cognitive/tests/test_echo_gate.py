# test_echo_gate.py — 句级回声硬闸（2026-10-19 补账）
# ============================================================================
# 事故：10:04 主动说"嗯，多巴胺的'意外'机制确实很迷人。它像是在说，大脑
# 本质上是个预测机器……"，10:38 新 CI（调研带来新证据，基座级判定"是延伸"
# 放行——正确）生成的文本**逐字复用**了前两句。旧硬闸只比全文相等、材料
# 只取 30min 窗（34 分钟恰好越窗），整句级"半回声"零防御。
# 现在：_spoken_ledger 无时限取最近 24 条她说过的话；全文相等或任一
# ≥10 字句子是旧话字面子串 → 弃权（CI 丢弃，不重试不白烧 LLM）。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 -m pytest tests/test_echo_gate.py
# ============================================================================
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node
from continuous_cognition import (ContinuousCognition, ST_READY,
                                  ST_EXPRESSED, ST_DISCARDED)
from langchain_core.runnables import RunnableLambda


class FakeEngine:
    def __init__(self):
        import threading
        self._lock = threading.RLock()
        self._running = False
        self.topk = []

    def register_activation_source(self, ids, source_type="external_input"):
        pass

    def get_topk(self, k=15):
        return self.topk[:k], []

    def decay_step(self): pass
    def diffuse_step(self): pass
    def mark_active(self, ids): pass
    def mark_edges_active(self, edges): pass
    def clear_anchors(self): pass


class FakeNLP:
    def __init__(self, out_text):
        self.out = out_text
        self.system_prompt = lambda name: "你是 HARU。（回声闸隔离测试桩）"
        self.chat_llm = RunnableLambda(lambda *a, **k: type(
            "Resp", (), {"content": self.out})())


class FakeBuffer:
    def add_expression(self, e): pass


CFG = {"continuous_cognition": {
    "tick_seconds": 0.01, "pulse_every_ticks": 1,
    "form_threshold": 0.50, "express_threshold": 1.01,
    "inhibition_cooldown_s": 0.1}}


OLD_SPOKEN = ("嗯，多巴胺的“意外”机制确实很迷人。它像是在说，大脑本质上"
              "是个预测机器，只有当现实跟预测对不上号的时候，它才真正醒过来。")


def make_cc(out_text):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="用户", weight=1.0, graph_space="semantic"))
    kg.add_node(Node(id="Self", weight=1.0, graph_space="self"))
    # 旧话：2 小时前说出口并投递（**在旧 30min 材料窗之外**）
    kg.add_node(Node(
        id="CI_old", weight=0.5, label="intention", graph_space="self",
        extra_attrs={"type": "communication_intention", "kind": "communication",
                     "status": ST_EXPRESSED, "activation": 0.1,
                     "basis": ["用户"], "expressed_text": OLD_SPOKEN,
                     "expressed_at_ts": time.time() - 7200,
                     "expressed_at": time.strftime(
                         "%Y-%m-%d %H:%M:%S",
                         time.localtime(time.time() - 7200))}))
    cc = ContinuousCognition(kg, FakeEngine(), FakeNLP(out_text),
                             FakeBuffer(), dict(CFG))
    ci = Node(id="CI_new", weight=0.5, label="intention", graph_space="self",
              extra_attrs={"type": "communication_intention",
                           "kind": "communication", "status": ST_READY,
                           "activation": 0.9, "basis": ["用户"],
                           "reply_goal": "share_related_knowledge"})
    kg.add_node(ci)
    return kg, cc, ci


def test_verbatim_sentence_echo_blocked_despite_time_gap():
    """复用旧话里一整句（≥10字）→ 弃权；隔 2 小时也拦（无时限账本）。"""
    kg, cc, ci = make_cc(
        "确实，多巴胺的“意外”机制确实很迷人。不过昨晚我在游戏里的翻盘"
        "完全是另一回事，紧张得手心出汗。")
    assert cc._express(ci) is False
    assert ci.extra_attrs["status"] == ST_DISCARDED


def test_rewritten_content_passes():
    """同一话题、全新措辞（没有一个 10 字以上的字面复用）→ 正常出口。
    回声闸管字面，不管'想法像不像'——那是基座身份去重的职责。"""
    kg, cc, ci = make_cc(
        "说起来，预测误差这个概念让我联想到昨晚尖塔里那把翻盘：第三层"
        "那张牌我完全没料到，结果反而成了整局最醒的一刻。")
    assert cc._express(ci) is True
    assert ci.extra_attrs["status"] == ST_EXPRESSED


def test_full_repetition_still_blocked():
    """整段逐字复读（旧闸就覆盖的形态）继续拦。"""
    kg, cc, ci = make_cc(OLD_SPOKEN)
    assert cc._express(ci) is False
    assert ci.extra_attrs["status"] == ST_DISCARDED


def test_short_fillers_not_flagged():
    """"嗯，有道理。"级短应答不参与句子比对——日常接话的语气重复
    不算复读（阈值只在 ≥10 字整句上生效）。"""
    kg, cc, ci = make_cc("嗯，有道理。那我继续去看看。")
    assert cc._express(ci) is True


def test_ledger_includes_passive_replies():
    """账本覆盖被动回复：她 2 小时前的答话（chat_log）被复用同样拦。"""
    kg, cc, ci = make_cc(
        "接话前先想想，多巴胺的“意外”机制确实很迷人，这我在回答里已经"
        "讲过一次了。")
    # 把旧话以 chat_log 被动行形态注入（无 kg EXPRESSED 节点也可命中）
    class CL:
        def recent(self, n=12):
            return [{"system_response": OLD_SPOKEN,
                     "time": time.strftime("%Y-%m-%dT%H:%M:%S",
                                           time.localtime(time.time() - 7000))}]

        def record(self, **k): pass
    cc.chat_log = CL()
    # 把 kg 里的主动旧话抹掉：证明拦下它的只有被动回复账本
    kg.nodes["CI_old"].extra_attrs["status"] = "discarded"
    assert cc._express(ci) is False
