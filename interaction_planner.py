# interaction_planner.py — 陪伴层·交流目标最小闭环（候选机制，默认关闭）
# ============================================================================
# 迁移的是认知层 goal_planner（FAS-Cognitive，2026-10-09）的**控制思想**，
# 不是它的游戏任务实现：审计与语义冲突清单见
# docs/audits/INTERACTION_GOALS_MIGRATION_AUDIT_2026-10-09.md。
#
# 闭环：显式证据生成交流目标 → 回合裁决时把"适不适合推进"过可观察闸门 →
#       下一轮从真实互动反馈（expression_feedback 的可观察结果）落账 →
#       推进/搁置/放弃/到期 + 定向证据记录。零 LLM、零网络。
#
# 硬约束（违者即 bug，继承 goal_planner 纪律并加陪伴特例）：
#   1. 默认关：config["interaction_planner"].enabled=False 或缺节时，
#      三个入口（try_create_from_turn / arbitrate / observe_turn）原样返回，
#      dd 对象恒等不改（关=陪伴行为逐位不变）。
#   2. Goal ≠ Action：交流目标只是"值得维护的关系状态"，推进与否由
#      可观察闸门决定；**绝不**因为目标节点存在/激活高/图里有路径就推进。
#      （族 L 实验教训：目标显著=行动建议 是混淆。）
#   3. 判定只认观察：推进=目标话题出现在本轮解析结构（用户实际说到）；
#      用户没提到 ≠ 不重要（不判失败、不强行推进也不强判放弃）。
#      简短回复 ≠ 生气；未回答 ≠ 拒绝（模糊=保持不确定，pending 宽限一轮）。
#   4. 沉默不可推翻：dialogue_decide 选 silence 时本模块不注入任何策略。
#      本模块只在"已决定说话"的前提下调整说什么的姿态（constraints 通道），
#      是否回应/是否提问的最终裁决权仍完整属于 dialogue_decide。
#   5. 防重复推进：同目标推进有冷却（advance_min_interval_s）；同一策略
#      被明确负反馈达 strategy_retry_limit 次后进 excluded（不得复发）；
#      连续负向才 suspended——单次绝不放弃目标（一次交互不永久改变关系）。
#   6. 写回定向最小：只写目标节点 extra_attrs.ig 与 Self-[目标] 边
#      （kind 标记隔离）；绝不写边权到行为/人格节点、绝不新建平行存储、
#      **绝不占用 当前目标 指针边**（那是自主循环的世界行动通道）。
#   7. 不外泄：本模块产出一律进约束/遥测通道，不拼接用户可见文本；
#      目标 ID、策略名、状态词不得出现在回复文案里（constraints 只给
#      语言层"行为姿态"描述，由提纲机制消化为自然表达）。
#   8. 到期可观测：expire_after_s 无推进 → expired（终态留痕，不删节点；
#      用户再提起时同 topic 重建视为新目标并保留旧 history 引用）。
# ============================================================================

import logging
import re
import time

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": False,
    "max_active": 2,               # 同时活跃交流目标上限（防一轮多线跟进）
    "advance_min_interval_s": 1800.0,   # 同目标两次推进之间最小间隔（可观察冷却）
    "expire_after_s": 7 * 24 * 3600.0,  # 长期无人提起且未推进 → expired
    "strategy_retry_limit": 2,     # 同策略累计明确负反馈次数上限 → excluded
    "pending_grace_turns": 2,      # 模糊反馈宽限轮数（超后按 unanswered 落账，非失败）
}

# 显式请托标记：只在用户**自己说出口**的跟进请求处建目标（任务书：不因
# 每条消息造长期目标）。检测≠行为决定——建出来的目标仍要过闸门才可能推进。
_COMMIT_RE = re.compile(
    r"(记得|别忘|回头|改天|下次|下回|晚点|有空|明天|后天|下周|到时候)"
    r".{0,12}(问|看|提|聊|说|提醒|试|弄|查|讲)")
_RESUME_RE = re.compile(r"(之前|上次| Earlier|前几天).{0,10}(说的|提到的|聊的)")

_STATE_ACTIVE = "active"
_STATE_SATISFIED = "satisfied"
_STATE_SUSPENDED = "suspended"
_STATE_EXPIRED = "expired"
_STATE_ABANDONED = "abandoned"
_TERMINAL = (_STATE_SATISFIED, _STATE_EXPIRED, _STATE_ABANDONED)


def _cfg(config):
    c = dict(DEFAULTS)
    c.update((config or {}).get("interaction_planner") or {})
    return c


# ── Goal 存储（图谱 self 空间，kind 隔离，绝不占 当前目标 指针）──────

def _goal_id(desc):
    return f"交流目标:{str(desc).strip()[:36]}"


def _ig_of(node):
    ig = (node.extra_attrs or {}).get("ig")
    return ig if isinstance(ig, dict) else None


def list_goals(kg, states=(_STATE_ACTIVE,)):
    """只读枚举交流目标节点（按 extra_attrs.kind 严格过滤——
    与 self_graph 长期目标同边不同类，互不冒充）。"""
    out = []
    for nid, n in kg.nodes.items():
        if not str(nid).startswith("交流目标:"):
            continue
        ig = _ig_of(n)
        if ig and ig.get("kind_marker") == "interaction_goal" \
                and ig.get("state") in states:
            out.append({"id": nid, "ig": ig, "node": n})
    return out


def create_goal(kg, *, desc, topic, evidence, config=None, now=None):
    """建交流目标：节点 + Self-[目标]-> 边（edge extra_attrs 标 kind）。
    去重：同 topic 已有活跃目标 → 返回既有 id（不重复造）。上限 max_active。"""
    cfg = _cfg(config)
    if not cfg["enabled"]:
        return ""
    now = time.time() if now is None else now
    topic = str(topic or "").strip()
    if not topic:
        return ""
    for g in list_goals(kg):
        if g["ig"].get("topic") == topic:
            return g["id"]
    active = list_goals(kg)
    if len(active) >= int(cfg["max_active"]):
        return ""            # 满额：不再新增（交流目标宁缺毋滥）
    from graph_model import Node, Edge
    gid = _goal_id(desc or topic)
    if kg.get_node(gid) is None:
        ig = {"kind_marker": "interaction_goal",
              "state": _STATE_ACTIVE,
              "topic": topic,
              "evidence": str(evidence)[:60],
              "created_ts": now,
              "last_advance_ts": 0.0,
              "advances": [],
              "outcomes": [],
              "excluded_strategies": [],
              "pending": None}
        kg.add_node(Node(id=gid, weight=0.6, label="declarative-semantic",
                         graph_space="self",
                         extra_attrs={"kind": "interaction_goal", "ig": ig}))
    existing = kg.get_edge("Self", gid, "目标")
    if existing is None:
        kg.add_edge(Edge(src="Self", dst=gid, relation="目标", weight=0.6,
                         extra_attrs={"kind": "interaction_goal"}))
    logger.info("[IntGoal] 建立交流目标 %s（topic=%s evidence=%s）",
                gid, topic, evidence)
    return gid


def try_create_from_turn(kg, *, text, parsed, config=None, now=None):
    """仅**显式证据**建目标（审计 §4-3）：
      a) 请托句式（用户要求自己记得/回头问某事）；
      b) 无标记时不建——隐式话题延续由既有 exploration/curiosity 通道覆盖，
         本模块不建第二套提问来源。
    topic 取本轮解析节点里最长的具名节点（结构观察，不做心理推断）。"""
    cfg = _cfg(config)
    if not cfg["enabled"]:
        return ""
    t = str(text or "")
    if not (_COMMIT_RE.search(t) or _RESUME_RE.search(t)):
        return ""
    nodes = [n.get("id") if isinstance(n, dict) else n
             for n in (parsed or {}).get("nodes", [])]
    nodes = [str(x) for x in nodes if x and not str(x).startswith(("用户", "Haru"))]
    if not nodes:
        return ""
    topic = max(nodes, key=len)
    # 传原始 config（create_goal 内部自己 _cfg；传合并后的 cfg 会被二次
    # 合并丢掉 interaction_planner 节 → 回落默认关，2026-10-09 测试抓到）
    return create_goal(kg, desc=t[:36], topic=topic,
                       evidence="explicit_commitment", config=config, now=now)


# ── Strategy：回合裁决的可选前置步（只在已决定说话时微调姿态）──────────

def arbitrate(kg, dd, parsed, *, config=None, now=None):
    """读活跃目标 → 可观察闸门 → 通过则往 dd['constraints'] 追加一条
    行为姿态约束、dd['factors'] 记遥测，并把本次"提议推进"记为 pending
    （成败下一轮 observe_turn 落账——继承 goal_planner 的两拍分离）。
    返回 (dd, tele)。关=原对象恒等返回。"""
    cfg = _cfg(config)
    tele = {"status": "disabled", "proposed": None}
    if not cfg["enabled"]:
        return dd, tele
    now = time.time() if now is None else now
    if not dd or dd.get("decision") == "silence":
        tele["status"] = "respects_silence" if dd else "no_dd"
        return dd, tele                      # 硬约束 4
    turn_topics = set()
    for n in (parsed or {}).get("nodes", []):
        nid = n.get("id") if isinstance(n, dict) else n
        if nid:
            turn_topics.add(str(nid))
    proposals = []
    for g in sorted(list_goals(kg),
                    key=lambda x: x["ig"].get("created_ts", 0)):
        ig = g["ig"]
        topic = ig.get("topic") or ""
        # 闸门 1（可观察）：目标话题必须真的出现在本轮用户话语的解析结构里。
        # 不在=什么都不做（不推进、不判负、不强挂旧目标）。
        if topic not in turn_topics:
            continue
        # 闸门 2：冷却（同目标不得连续轮推进 → 防重复跟进）。
        # 从未推进过（last_advance_ts<=0）不受冷却——冷却只约束"已推进
        # 之后"的重提，不惩罚首次兑现（A/B 对照抓到：时间基小会死锁）。
        _la = float(ig.get("last_advance_ts", 0) or 0)
        if _la > 0 and now - _la < float(cfg["advance_min_interval_s"]):
            continue
        # 闸门 3：上一次提议未结算（pending 在场）→ 不重复推进。
        # 同 goal_planner 的在飞去重纪律：两拍分离，成败必须先看观察。
        if isinstance(ig.get("pending"), dict):
            continue
        # 闸门 4：策略未耗尽（同策略被明确负反馈达上限 → excluded；
        # 全部策略耗尽 → 该目标本轮无话可推进，允许结果为"不推进"）。
        strategy = _pick_strategy(ig, cfg)
        if strategy is None:
            continue
        # 到期检查顺路做（结构事实，不看激活）
        proposals.append((g, strategy))
    for g, _s in proposals:
        _expire_passive(g["node"], g["ig"], now, cfg)
    if not proposals:
        tele["status"] = "no_advance_needed"
        return dd, tele
    g, strategy = proposals[0]              # 每回合最多推进一个（max 1 提案）
    ig = g["ig"]
    desc = ig.get("topic", "")
    posture = {
        "light_follow_up": f"本轮可顺带一句关于「{desc}」的近况，一句为止，"
                           f"用户没接就自然放下，不连续追问",
        "offer_help": f"用户在谈「{desc}」，若其表达困难可直接给一次"
                      f"具体帮助意愿，不替用户做决定",
    }[strategy]
    dd.setdefault("constraints", [])
    dd["constraints"] = list(dd["constraints"]) + [posture]
    dd.setdefault("factors", {})
    dd["factors"] = dict(dd["factors"])
    dd["factors"]["interaction_goal"] = {"id": g["id"], "strategy": strategy,
                                         "proposed_ts": now}
    ig["pending"] = {"strategy": strategy, "ts": now, "grace_left":
                     int(cfg["pending_grace_turns"])}
    ig["advances"].append({"ts": now, "strategy": strategy})
    _store(g["node"], ig)
    tele["status"] = "proposed"
    tele["proposed"] = {"id": g["id"], "strategy": strategy}
    logger.info("[IntGoal] 提议推进 %s strategy=%s", g["id"], strategy)
    return dd, tele


def _pick_strategy(ig, cfg):
    excl = set(ig.get("excluded_strategies") or [])
    outcomes = ig.get("outcomes") or []
    fails = {}
    for o in outcomes:
        if o.get("outcome") == "declined":
            fails[o.get("strategy")] = fails.get(o.get("strategy"), 0) + 1
    for s in ("light_follow_up", "offer_help"):
        if s in excl:
            continue
        if fails.get(s, 0) >= int(cfg["strategy_retry_limit"]):
            ig.setdefault("excluded_strategies", []).append(s)
            continue
        return s
    return None


def _expire_passive(node, ig, now, cfg):
    """到期是结构事实（长期无推进），不是行为失败判定。"""
    if ig.get("state") != _STATE_ACTIVE:
        return
    if now - float(ig.get("created_ts", 0)) > float(cfg["expire_after_s"]) \
            and not ig.get("advances"):
        ig["state"] = _STATE_EXPIRED
        _store(node, ig)
        logger.info("[IntGoal] %s 到期 expired", ig.get("topic"))


def _store(node, ig):
    if not isinstance(node.extra_attrs, dict):
        node.extra_attrs = {}
    node.extra_attrs["ig"] = ig
    node.touch()


# ── Monitor：下一轮从可观察反馈落账（复用 expression_feedback 的结果）───

def observe_turn(kg, *, parsed, fb, config=None, now=None):
    """对每个带 pending 的目标做状态迁移。输入只有可观察量：
      fb=expression_feedback 的图谱后验结果（None=本轮没有回应到上句）；
      parsed=本轮解析结构（话题是否延续）。
    迁移表（模糊一律保持不确定）：
      responded 且话题延续            → outcome=advanced；请托类视为 satisfied
      responded 但用户转了话题          → outcome=topic_shift（不判负，冷却照常）
      未回应（fb None，宽限耗尽）       → outcome=unanswered（不判负、不追问）
      明确负反馈（fb legacy=negative） → outcome=declined（计策略负例，
                                        连续 declined 达上限 → suspended）
    返回遥测列表。关=返回 []。"""
    cfg = _cfg(config)
    tele = []
    if not cfg["enabled"]:
        return tele
    now = time.time() if now is None else now
    turn_topics = set()
    for n in (parsed or {}).get("nodes", []):
        nid = n.get("id") if isinstance(n, dict) else n
        if nid:
            turn_topics.add(str(nid))
    for g in list_goals(kg, states=(_STATE_ACTIVE,)):
        ig = g["ig"]
        _expire_passive(g["node"], ig, now, cfg)
        pend = ig.get("pending")
        if not isinstance(pend, dict):
            continue
        outcome = None
        legacy = (fb or {}).get("legacy") if fb else None
        topic_present = ig.get("topic") in turn_topics
        if legacy == "positive":
            outcome = "advanced" if topic_present else "topic_shift"
        elif legacy == "negative":
            outcome = "declined"
        elif fb is None:
            pend["grace_left"] = int(pend.get("grace_left", 0)) - 1
            if pend["grace_left"] > 0:
                tele.append({"id": g["id"], "outcome": "uncertain"})
                _store(g["node"], ig)      # 宽限：保持不确定
                continue
            outcome = "unanswered"
        else:
            outcome = "topic_shift" if not topic_present else "unanswered"
        ig["outcomes"].append({"ts": now, "strategy": pend.get("strategy"),
                               "outcome": outcome})
        ig["last_advance_ts"] = float(pend.get("ts", now))
        ig["pending"] = None
        if outcome == "advanced" and ig.get("evidence") == "explicit_commitment":
            ig["state"] = _STATE_SATISFIED   # 请托已带到一次并完成使命
        elif outcome == "declined":
            declines = sum(1 for o in ig["outcomes"]
                           if o.get("outcome") == "declined")
            if declines >= int(cfg["strategy_retry_limit"]):
                ig["state"] = _STATE_SUSPENDED   # 连续负向才搁置；单次不放弃
        tele.append({"id": g["id"], "outcome": outcome,
                     "state": ig["state"]})
        _store(g["node"], ig)
    return tele
