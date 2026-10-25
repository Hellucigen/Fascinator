# disease_care_pack.py — 疾病·关怀确定性知识种子包（2026-10-17 用户任务）
# ============================================================================
# 目的：把散点的"发烧/身体状态/社交需求/共情"接成一小片可推的亚结构，
# 使"用户病了"能沿 发烧→疾病→病人→需要→关心→社交需求/行为:共情 自然
# 扩散到她心里——而不是每次都靠语言模型裸猜。
#
# 纪律：
#   - 确定性种子（config 数据表），无 LLM、无幻觉扩展；扩展=往 config
#     `disease_care_pack.edges` 加行；
#   - 幂等 ensure（重复调用零写入）；已有节点一律复用（人类/社交需求/
#     身体不适/行为:共情 都连旧不建）；
#   - 主体归属不靠通用概念边表达——"谁在发烧"仍由情景边
#     （用户-[经历]->发烧不适）承载，概念层不混淆人物。

import logging

from graph_model import Edge, Node, now_str

logger = logging.getLogger("disease_care_pack")

DEFAULT_NODES = ("疾病", "生病", "病人", "关心")
# [src, rel, dst, weight, reason]
DEFAULT_EDGES = (
    ("发烧", "属于", "疾病", 0.85, "症状—病症类属"),
    ("疾病", "困扰", "人类", 0.80, "普遍生物事实"),
    ("人类", "会", "生病", 0.80, "普遍生物事实"),
    ("生病", "表现为", "身体不适", 0.70, "症状学"),
    ("生病", "的人是", "病人", 0.80, "角色定义"),
    ("病人", "是一种", "人类", 0.90, "上位类"),
    ("病人", "需要", "关心", 0.85, "社会常识：病中盼关怀"),
    ("关心", "满足", "社交需求", 0.60, "关怀是被接收方的社交需要"),
    ("关心", "体现于", "行为:共情", 0.60, "言行通道：既有行为概念"),
    ("喝水", "缓解", "发烧", 0.50, "常识照护行为"),
    ("休息", "缓解", "发烧", 0.55, "常识照护行为"),
    ("发烧", "导致", "身体不适", 0.60, "症状—体感"),
    ("用户", "可能", "生病", 0.65, "用户=人类一员：病事实可归属到他"),
    ("Self", "相关", "关心", 0.70, "关怀是她自我网络的一部分（白名单关系）"),
    # 念头→动作的桥（2026-10-17 用户设计）：沟通意图形成时，"用户相关性"
    # 的判据是"用户有出边指向焦点节点"（continuous_cognition 信号计算）。
    # 关心缺这条 → 关心的念头即使被点亮也不算社交燃料。这条边让
    # "关心你"成为用户相关事实：念头激活→进焦点→抬沟通 affinity→促进开口。
    ("用户", "相关", "关心", 0.65, "关心的对象正是用户：念头计入用户相关性"),
)


def _cfg(config: dict):
    blk = (config or {}).get("disease_care_pack") or {}
    return (tuple(blk.get("nodes") or DEFAULT_NODES),
            tuple(tuple(r) for r in (blk.get("edges") or DEFAULT_EDGES)))


def ensure(kg, config: dict = None) -> dict:
    """幂等种入。返回 {"nodes": 新增数, "edges": 新增数}。"""
    nodes, edges = _cfg(config)
    added_n = added_e = 0
    with kg._lock:
        for nid in nodes:
            if kg.get_node(nid) is not None:
                continue
            kg.add_node(Node(
                id=nid, weight=0.5, label="declarative-semantic",
                graph_space="semantic",
                extra_attrs={"type": "concept",
                             "source": "disease_care_pack_v1",
                             "created": now_str()}))
            added_n += 1
        for src, rel, dst, w, _why in edges:
            if kg.get_node(src) is None or kg.get_node(dst) is None:
                continue
            if kg.get_edge(src, dst, rel) is not None:
                continue
            kg.add_edge(Edge(src=src, dst=dst, relation=rel,
                             weight=float(w),
                             relation_category="semantic_relation"))
            added_e += 1
        if added_n or added_e:
            kg.rebuild_indexes()
    if added_n or added_e:
        logger.info("[CarePack] 疾病·关怀种子包：节点+%d 边+%d", added_n, added_e)
    return {"nodes": added_n, "edges": added_e}
