# -*- coding: utf-8 -*-
"""情景记忆来源约束（2026-10-19 审计修复）：知道≠经历，说过≠做过，
状态镜像≠活动，用户话语主体是用户——把图谱里**已有**的来源事实传到
语言层，不新增闸门。

实锤案例：2026-10-19 12:47，"Minecraft会话"节点（type=mc_session，
state=disconnected）被标〔概念〕入认知切片，而当天时间轴里除发声外
没有任何活动事件——旧代码 `if life_events:` 在空账本时把
"没写在这里=没发生"的完整性声明整段吞掉，语言层把激活+知识连线编成
"我刚才在Minecraft里闲逛，挖到没见过的矿物"。
"""
import time

from graph_model import KnowledgeGraph, Node
from continuous_cognition import _state_node_note, render_cognitive_state


def _hot(kg, nid, attrs=None, label="declarative-semantic", act=0.5,
         created=None):
    kg.add_node(Node(id=nid, weight=0.5, label=label,
                     graph_space="self", activation=act,
                     created=created or time.strftime(
                         "%Y-%m-%d %H:%M:%S"),
                     extra_attrs=attrs or {}))
    return kg.nodes[nid]


def _render(kg, life_events=None):
    return render_cognitive_state(kg, ci=None, life_events=life_events)


# ── 1/2：真实经历可回忆；有记录时正常渲染 ────────────────────

def test_recorded_experience_renders_normally():
    kg = KnowledgeGraph()
    out = _render(kg, life_events=[
        "- 12:03 我玩了杀戮尖塔2：输了，打到第 8 层"])
    assert "【最近真实发生过的事" in out
    assert "打到第 8 层" in out          # 有证据的回忆通路不受影响


# ── 3/7：空账本的完整性声明绝不消失 ─────────────────────────

def test_empty_ledger_keeps_completeness_claim():
    kg = KnowledgeGraph()
    out = _render(kg, life_events=None)
    assert "【最近真实发生过的事" in out
    assert "没写在这里的事就没有发生" in out
    assert "没有任何活动被记录" in out
    # _life_events 返回 [] 与 None 两条路都要保留
    assert "没有任何活动被记录" in _render(kg, life_events=[])


# ── 知识/研究/计划 ≠ 经历 ───────────────────────────────────

def test_knowledge_concept_note_and_boundary():
    kg = KnowledgeGraph()
    _hot(kg, "阿司匹林", {"type": "concept"})
    out = _render(kg)
    assert "〔概念〕" in out
    assert "不代表我做过" in out


def test_research_hypothesis_note():
    kg = KnowledgeGraph()
    _hot(kg, "假设：Minecraft会话与组胺样", {"type": "hypothesis"})
    out = _render(kg)
    assert "〔待验证联想〕" in out       # 研究主题回归不变


def test_mc_session_mirror_surfaces_state():
    kg = KnowledgeGraph()
    _hot(kg, "Minecraft会话", {"type": "mc_session", "canon": "cognitive_state",
                               "state": "disconnected",
                               "text": "我正想要在Minecraft世界中展开探索"})
    out = _render(kg)
    assert "桥接状态" in out and "当前=disconnected" in out
    assert "不是玩过的经历" in out
    node_line = next(l for l in out.split("\n")
                     if l.startswith("- Minecraft会话"))
    assert "〔概念〕" not in node_line       # 不再被降级标注成普通概念


def test_pending_intention_is_not_completion():
    """计划/意图：思路流段本来就标"还没说"（回归钉：不得被当完成事件）。"""
    kg = KnowledgeGraph()
    _hot(kg, "CI_plan", {"type": "communication_intention",
                         "status": "forming", "basis": ["Minecraft会话"]},
         act=0.0)                       # 只走思路流段，不走热节点
    out = _render(kg)
    assert "还没说" in out


# ── 用户话语归属 ────────────────────────────────────────────

def test_utterance_attributed_to_user_not_self():
    kg = KnowledgeGraph()
    _hot(kg, "话语_20261019_111150_165", {"type": "utterance_event",
                                          "text": "我膝盖疼了两周了"},
         label="declarative-episodic")
    out = _render(kg)
    assert "主体=用户" in out
    assert "〔经历片段〕" not in out      # 旧兜底把用户的话标成"经历片段"
    assert "话语_20261019_111150_165" in out   # 原则C：不剔除，只标归属


def test_expression_event_said_not_done():
    kg = KnowledgeGraph()
    _hot(kg, "表达_20261019120000001", {"type": "expression_event",
                                        "answer_head": "我说过我想逛Minecraft"},
         label="declarative-episodic")
    out = _render(kg)
    # 10-21 契约升级：表达事件属内部痕迹，不再占素材热位（不出现即无从
    # 冒充）；"说过"信息由 raw 对话窗/防复述专段诚实呈现（test_express_*）。
    material = out.split("我正在想的事")[0]
    assert "表达_20261019120000001" not in material
    assert "〔经历片段〕" not in out


def test_thought_note_direct():
    kg = KnowledgeGraph()
    n = _hot(kg, "思考_123", {"type": "thought", "content": "我正感受到牵引"})
    assert _state_node_note(n) == "我自己的念头（心理活动，不是外部世界的证据）"


# ── 12:47 实锤形态回归（2026-10-19 追踪结论）────────────────
# 旁白其实写在 思考_1791542916 上（label=declarative-episodic、
# type=thought、content=第一人称念头），旧渲染兜底标成〔经历片段〕。
# Minecraft会话节点本身**没有**被污染——不存在 mc 侧旁白写入源。

def test_thought_in_slice_is_not_experience():
    kg = KnowledgeGraph()
    _hot(kg, "思考_1791542916",
         {"type": "thought",
          "content": "我正感受到网络意识的强烈牵引，想要在Minecraft世界中"
                     "展开探索并把所见分享出来，同时认知预算在提醒我平衡"
                     "深度与延续。"},
         label="declarative-episodic", act=1.5)
    _hot(kg, "Minecraft会话", {"type": "mc_session",
                               "state": "disconnected"}, act=2.7)
    out = _render(kg)
    # 10-21 契约升级：思考不再占素材热位（内部痕迹出局）；内容由 思路流
    # 段呈现，该段段头整体钉住性质——"自己的心理活动，不是外部事实的证据"。
    material = out.split("我正在想的事")[0]
    assert "思考_1791542916" not in material   # 不在"我此刻心里有什么"素材里
    assert "〔经历片段〕" not in out
    assert "心理活动，不是外部事实" in out      # 性质由 思路流 段头钉死
    assert "展开探索" in out               # 念头内容仍可见（想谈可谈）
    assert "Minecraft会话" in material     # 镜像保留带注记的状态行


def test_empty_ledger_body_stays_in_scope():
    """空账本声明只约束叙事举证义务，不对未登记的活动类型做形而上断言
    （任务书§四：账本覆盖部分活动，不能扩张成"什么都没发生"）。"""
    kg = KnowledgeGraph()
    out = _render(kg, life_events=None)
    assert "没有任何活动被记录" in out          # 账本实况
    assert "在其登记范围内是完整的" in out      # 范围边界
    assert "必须能在这份记录或上面的对话原文里找到" in out  # 举证义务
    assert "不代表我做过" in out
    assert "没出门浏览" not in out              # 已删除的过度断言
    assert "没玩过游戏、没听过音乐" not in out  # 同上


def test_action_pattern_not_single_experience():
    kg = KnowledgeGraph()
    _hot(kg, "操作:点击确认", {"type": "action_pattern",
                               "source": "causal_hypothesis",
                               "description": "确认前保存导致掉档减少"},
         act=0.4)
    out = _render(kg)
    line = next(l for l in out.split("\n")
                if l.startswith("- 操作:点击确认"))
    assert "归纳" in line and "不是某一次具体经历" in line


def test_prior_concept_is_scaffold_but_instances_stay():
    """2026-10-20 C 契约：本体**类别**节点（属性/用途…，type=prior_concept）
    是内容脚手架——不进素材行（此前"标〔概念〕照常入场"是过渡态断言，
    被更强的新契约取代）；而**具体个体**（钻石矿，type=concept）是正常
    知识内容仍可见。计算资格（扩散可达）不受任何影响，见
    test_extraction_routing T7。"""
    from graph_model import is_content_scaffold, is_cognitive_visible
    kg = KnowledgeGraph()
    _hot(kg, "属性", {"type": "prior_concept", "source": "prior_seed",
                      "text": "性质分类"}, act=1.6)
    _hot(kg, "钻石矿", {"type": "concept", "text": "稀有矿物，需铁镐以上"},
         act=0.4)
    assert is_content_scaffold(kg.get_node("属性"))
    assert not is_content_scaffold(kg.get_node("钻石矿"))
    assert not is_cognitive_visible(kg.get_node("属性"))
    assert is_cognitive_visible(kg.get_node("钻石矿"))
    out = _render(kg)
    assert "- 属性" not in out
    assert "〔概念〕" in out.split("- 钻石矿")[1].split("\n")[0]
    assert "〔经历片段〕" not in out.split("- 钻石矿")[1].split("\n")[0]


def test_procedural_nodes_never_enter_slice():
    """能力/流程节点（label=procedural，含"进入Minecraft世界"说明书）
    本就不进 declarative 热切片——回归钉，防止未来有人改过滤器。"""
    kg = KnowledgeGraph()
    kg.add_node(Node(id="进入Minecraft世界", weight=0.5,
                     label="procedural", graph_space="semantic",
                     activation=9.0,
                     extra_attrs={"text": "进入用户的Minecraft世界一起玩"}))
    out = _render(kg)
    assert "进入Minecraft世界" not in out


# ── 真·经历节点保留原有标注 ─────────────────────────────────

def test_genuine_episode_still_experience_note():
    kg = KnowledgeGraph()
    n = _hot(kg, "某次六级考试", {"type": "event"},
             label="declarative-episodic")
    assert _state_node_note(n) == "经历片段"    # 回忆能力未被阉割（§7.1/10）


def test_activity_experience_note_intact():
    kg = KnowledgeGraph()
    n = _hot(kg, "活动_x", {"type": "activity_experience"})
    assert "活动体验" in _state_node_note(n)


# ── §7.9 两条表达通道共用同一渲染 ───────────────────────────

def test_both_channels_share_renderer():
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    src = open(_os.path.join(root, "app.py"), encoding="utf-8").read()
    # 被动（L2 compile）与主动（_express）都经 render_cognitive_state
    assert "render_cognitive_state(" in src
    cc = open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "continuous_cognition.py"), encoding="utf-8").read()
    assert cc.count("render_cognitive_state(") >= 2   # 定义 + 主动调用
