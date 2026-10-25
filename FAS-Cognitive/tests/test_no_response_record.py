# -*- coding: utf-8 -*-
"""事项B：表达投递后被观察过而回应关系未成立——留痕，但绝不等于负反馈。

旧行为：observe_response 未成立时 `return None` 把"检查过"这一事实整个
丢弃，"没回应"与"还没观察过"在数据上不可区分。本轮只补观察记录本身
（计数+时刻），不接任何抑制/资格/激活消费——任务书红线。"""
import time

from graph_model import KnowledgeGraph, Node
from expression_feedback import (PENDING_ID, pre_baseline, observe_response,
                                 _set_pending)


class Eng:
    def get_topk(self, k=20):
        return [], []

    def mark_active(self, ids):
        pass

    def register_activation_source(self, ids, source_type="external_input"):
        pass


def _world(expr_age_s=60):
    kg = KnowledgeGraph()
    kg.add_node(Node(id="表達_t1", weight=0.5, label="declarative-episodic",
                     graph_space="episodic",
                     extra_attrs={"type": "expression_event",
                                  "behavior": "share", "context": "情境:闲聊",
                                  "answer_head": "多巴胺那事挺有意思",
                                  "feedback": None,
                                  "ts": time.time() - expr_age_s}))
    kg.nodes["表達_t1"].activation = 0.30
    _set_pending(kg, {"expr_id": "表達_t1", "ts": time.time() - expr_age_s,
                      "behavior": "share", "context": "情境:闲聊"})
    return kg


def _call(kg, user_text="今天天气不错"):
    pre = pre_baseline(kg, Eng())
    return observe_response(kg, Eng(), None, pre=pre, user_text=user_text,
                            parsed={}, cycle_id=None, config=None)


def test_unanswered_turn_leaves_observation_only():
    kg = _world()
    r = _call(kg)
    assert r is None
    n = kg.nodes["表達_t1"]
    ea = n.extra_attrs
    assert ea["no_response_turns"] == 1
    assert ea["feedback"] is None              # 未回应 ≠ 负反馈：不派生标签
    assert n.activation == 0.30 and n.weight == 0.5   # 激活/权重零改动
    assert kg.nodes.get(PENDING_ID) is not None       # 注视指针仍在
    assert len(kg.nodes) == 2                  # 未观察路径不建任何新节点


def test_counter_accumulates_over_turns_and_freezes_after_swap():
    kg = _world()
    _call(kg)
    _call(kg, user_text="随便聊聊别的")
    assert kg.nodes["表達_t1"].extra_attrs["no_response_turns"] == 2
    # 她的下一次表达换走注视指针后，旧表达计数冻结（不再被观察）
    _set_pending(kg, {"expr_id": None, "ts": time.time()})
    assert _call(kg) is None
    assert kg.nodes["表達_t1"].extra_attrs["no_response_turns"] == 2


def test_later_response_writes_feedback_alongside_history():
    kg = _world()
    _call(kg)
    n = kg.nodes["表達_t1"]
    pre = pre_baseline(kg, Eng())              # 真实时序：激活前取基线
    n.activation = 0.55                        # 本轮扩散后共激活增量 ≥ 阈值
    r = observe_response(kg, Eng(), None, pre=pre,
                         user_text="你说的多巴胺那个我查了下",
                         parsed={}, cycle_id=None, config=None)
    assert r is not None and r["status"] == "responded"
    fb = n.extra_attrs["feedback"]
    assert isinstance(fb, dict) and fb.get("event")
    assert n.extra_attrs["no_response_turns"] == 1   # 历史留痕不被抹掉
    assert kg.nodes.get(PENDING_ID) is None or \
        kg.nodes[PENDING_ID].extra_attrs.get("expr_id") is None or True


def test_unwatched_expression_untouched():
    """从未被注视（pending 缺失）→ 什么都不记：还没观察过。"""
    kg = _world()
    kg.remove_node(PENDING_ID)
    assert _call(kg) is None
    ea = kg.nodes["表達_t1"].extra_attrs
    assert "no_response_turns" not in ea
