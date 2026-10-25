# narrative_trigger.py — 事件结构化叙事触发器（Event-Structure-based Trigger）
# ============================================================================
# 规范：判断依据从"这段文字够不够长"变为
#       "这段输入是否描述了多个相互关联的事件/状态变化"。
#
# 评分（零 LLM，规则+词表，可复用已有解析结果）：
#   narrative_score = event + temporal + causal + shared_context + state_transition
#                   + multi_clause_bonus
#
# 判定：score ≥ threshold（balanced 0.45 / economy 0.60）→ 叙事编码管线。
#
# 语义边界（规范九）：
#   A. 用户亲身经历（第一人称，actors 含 用户）→ 用户-[参与]->事件
#   B. 用户讲述他人/虚构故事 → 用户-[讲述]->Narrative，角色-[参与]->事件
# （区别由 _ingest_narrative 依据 actors 是否含"用户"落地，本模块输出 first_person 信号）
# ============================================================================

import re

# 时间连接词（序列关系；不含 今天/现在 这类纯指示词——它们不是顺序信号）
TEMPORAL = (
    "然后", "之后", "随后", "最后", "接着", "于是", "首先", "其次",
    "第二天", "当时", "后来", "此前", "之前", "同时", "最终", "终于",
    "早上", "上午", "中午", "下午", "晚上", "凌晨", "夜里", "傍晚",
)

# 因果连接词
CAUSAL = ("因为", "所以", "导致", "由于", "结果", "使得", "弄得", "因此",
          "搞的", "以至于", "从而")

# 状态变化动词/模式
STATE = ("打开", "关上", "关闭", "变成", "开始", "结束", "发现", "出现",
         "消失", "坏了", "好了", "丢了", "找到", "装好", "修好", "熄灭", "亮了")

# 常见行为动词（事件子句判定用；优先双字词减少子串误匹配）
ACTION_VERBS = ("去", "吃", "喝", "玩", "买", "睡", "跑", "坐", "飞", "住",
                "打", "看", "听", "说", "问", "答", "找", "修", "花", "学",
                "考", "搬", "提交", "参加", "报名", "到达", "出发", "起床",
                "离开", "打扫", "规避", "驾驶", "工作", "考试", "回家", "返回",
                "开始", "结束", "讲述", "购买")

CLAUSE_SPLIT = re.compile(r"[。！？!?；;，,\n]+")
TOKEN_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}")

# 概念定义信号词（A1，2026-10-20）：区分"讲解概念"与"讲述事件"——
# 心理可见性案例的根修判据（详见 narrative_score 内注释）
DEFINITION_MARKERS = ("概念", "理论", "术语", "定义为", "指的是", "是指",
                      "所谓", "称为", "叫做", "意思是", "提出", "机制",
                      "定义", "解释")

# 阈值
THRESHOLD_BALANCED = 0.35
THRESHOLD_ECONOMY = 0.65


def _clauses(text: str) -> list:
    return [c.strip() for c in CLAUSE_SPLIT.split(text) if len(c.strip()) >= 2]


def narrative_score(text: str, profile: str = "balanced") -> dict:
    """事件结构评分。返回 {score, decision, components}。零 LLM。"""
    clauses = _clauses(text)
    n_clauses = len(clauses)
    joined = text or ""

    # 1. Event Count：含行为动词的子句才算事件子句（描述性子句不算）
    event_clauses = sum(1 for c in clauses if any(v in c for v in ACTION_VERBS))
    event_score = min(1.0, event_clauses / 3.0)

    # 2. Temporal：时间连接词命中
    t_hits = sum(joined.count(w) for w in TEMPORAL)
    temporal_score = min(1.0, t_hits / 2.0)

    # 3. Causal：显式因果连接词（强信号）
    c_hits = sum(joined.count(w) for w in CAUSAL)
    causal_score = min(1.0, c_hits)

    # 4. Shared Context：跨子句重复出现的实体词（共同参与者/对象）
    clause_tokens = [set(TOKEN_RE.findall(c)) for c in clauses]
    shared = {}
    for i in range(len(clause_tokens)):
        for j in range(i + 1, len(clause_tokens)):
            for tok in clause_tokens[i] & clause_tokens[j]:
                shared[tok] = shared.get(tok, 0) + 1
    shared_score = min(1.0, len(shared) / 2.0)

    # 5. State Transition：状态变化动词
    s_hits = sum(joined.count(w) for w in STATE)
    state_score = min(1.0, s_hits / 2.0)

    # 多子句加成：≥2 子句 且 存在关联证据（时间/因果连接词或跨句共享实体）
    # ——纯描述性长文（无关联证据）不拿加分，防知识说明误触发
    relational_evidence = (t_hits + c_hits) >= 1 or s_hits >= 2 or len(shared) >= 2
    bonus = 0.15 if (event_clauses >= 1 and n_clauses >= 2 and relational_evidence) else 0.0

    score = round(
        0.30 * event_score + 0.25 * temporal_score + 0.25 * causal_score
        + 0.10 * shared_score + 0.10 * state_score + bonus, 3)

    # 概念定义信号（2026-10-20 根因修复 A1，综合判据而非单一长度阈值）：
    # "提出了X概念，X是指……"这类聊天从句多、偶含"说/提出"，旧判分器把
    # 它判成剧情 → 概念抽取通道整轮被跳过，术语只活在情节摘要文本里，
    # 永远无法作为节点被扩散（心理可见性案例）。四类内容的区分：
    #   纯叙事（事件推进强）           → narrative
    #   定义/讲解主导（事件推进弱）     → normal（走概念/断言抽取）
    #   混合（定义强且事件也强）        → narrative（概念由 A2 entities
    #                                     条款与 B1 留痕在叙事通道内兜住）
    #   普通聊天（都弱）                → normal
    # 事件子句判据在"被看到/被理解"这类被动描述上误报（"看"字命中），
    # 所以主导性用**故事推进的硬信号**：没有任何时间/因果连接词的
    # 多定义标记文本，是在讲解概念而不是讲述事件。
    def_hits = sum(1 for w in DEFINITION_MARKERS if w in joined)
    definition_dominant = def_hits >= 2 and (t_hits + c_hits) == 0

    threshold = THRESHOLD_ECONOMY if profile == "economy" else THRESHOLD_BALANCED
    is_narrative = (n_clauses >= 2 and score >= threshold
                    and not definition_dominant)

    return {
        "score": score,
        "decision": "narrative" if is_narrative else "normal",
        "threshold": threshold,
        "components": {
            "clauses": n_clauses,
            "event": round(event_score, 2),
            "temporal": round(temporal_score, 2),
            "causal": round(causal_score, 2),
            "shared_context": round(shared_score, 2),
            "state_transition": round(state_score, 2),
            "bonus": bonus,
            "temporal_hits": t_hits,
            "causal_hits": c_hits,
            "definition_hits": def_hits,
            "definition_dominant": definition_dominant,
        },
        # 第一人称信号：供 _ingest_narrative 区分 经历 vs 讲述
        "first_person": bool(re.search(r"我[们]?|俺|本人", joined)),
    }
