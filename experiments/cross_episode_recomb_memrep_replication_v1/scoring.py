# scoring.py — 评分器与提示词：逐字移植自历史实验 run_llm.py（锁定预注册指定）
# 移植来源：experiments/cross_episode_recomb/run_llm.py
#   PROMPT      :20-31
#   check_answer:83-96
# 除注释与空格外逻辑零改动（diff 审计：与本文件逐行对照）。禁止调整判定逻辑。

PROMPT = """You are answering questions about a small world.
Question: {question}
{context}
Answer in Chinese. If the context connects the entities through
intermediate entities/relations, describe the connecting chain.
If the context does not contain enough information, say so.
Answer:"""


def check_answer(ans, q):
    """原实验确定性评分器（逐字移植）。返回分项 dict；exact_success 为二元。"""
    chain = q["gold_chain"]
    mids = chain[1:-1]
    mentioned = [e for e in chain if e in ans]
    mid_hits = [m for m in mids if m in ans]
    act_hits = [a for a in q["gold_actions"] if a in ans]
    exact = len(mid_hits) == len(mids) and len(mentioned) >= 2
    partial = len(mid_hits) >= 1
    path_ok = all(mentioned[i] in chain and
                  (i + 1 >= len(mentioned) or
                   abs(chain.index(mentioned[i]) -
                       chain.index(mentioned[i + 1])) == 1)
                  for i in range(len(mentioned) - 1)) if mentioned else False
    return {"exact_success": int(exact), "partial_success": int(partial),
            "path_validity": int(path_ok and len(mentioned) >= 2),
            "relation_validity": int(len(act_hits) > 0),
            "mentioned": mentioned}
