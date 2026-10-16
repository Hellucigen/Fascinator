# -*- coding: utf-8 -*-
"""run_c6_diagnosis.py — 02:08 案例的四条件隔离对照（阶段3）。

复现生产 prompt 结构（v1 路径、修复后模板），仅实验条件不同：
  1 原始条件           digest 原文
  2 证据澄清           digest + "仅为标题清单，无用户操作记录"边界说明
  3 动机约束           system 附加"有真实交流理由才表达，别为互动制造问题"
  4 无表达压力         system 附加"素材不值得说就 NO_SPEAK"强化
每条件 ×2 重复真实 LLM（MiMo），捕获通道，零真实投递。生产代码零修改。
"""
import json
import os
import sys
import time as _rt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, "E:/Project/FAS-Companion")

import run_eval as RE
import run_real_llm as RLL
from run_real_llm import REAL_NLP, CaptureChat, MODEL_ID

# 生产 02:08 案例的真实 digest（runtime_graph 中 用户近况_1791655680 的 text，
# 与 logs 02:08:00 快照行一致）
DIGEST = ("用户工作区快照 — 最近笔记：日記（Notion同步）；リーディングリスト（Notion同步）；"
          "Movie List；概念ノート；AI学習計画")   # 生产 02:08 真实 text（graph 只读核对）
DIGEST_CLARIFIED = DIGEST + "（注：以上只是笔记标题清单的快照，没有任何用户正在打开或操作这些笔记的记录）"

CONSTR_MOTIVATION = ("\n【本次表达的额外约束】只有在素材本身给出明确、具体的交流理由时才开口；"
                     "不要为了发起互动而制造问题，不要推测用户正在做什么。")
CONSTR_SILENCE = ("\n【本次表达的额外约束】如果素材不值得主动说，或者你只能说空泛的寒暄，"
                  "只输出 NO_SPEAK。安静是合法回答。")

CALLS_LOG = RLL.CALLS   # 复用 run_real_llm 的调用记录


def run(cond_name, digest_text, sys_suffix="", repeat=0):
    sim = RE.Sim(v2=False)                     # 生产等价（v1，flag 关）
    tag = f"{cond_name}|r{repeat}"
    sim.cc.nlp = REAL_NLP
    from prompt_templates import build_prompt
    if sys_suffix:
        # 生产 _express 的 system 实际来自 build_prompt fallback
        # （NLPProcessor 无 system_prompt 属性 → getattr None → fallback）
        sim.cc.nlp.system_prompt = lambda task: build_prompt(task) + sys_suffix
    sim.cc.nlp.chat_llm = CaptureChat(REAL_NLP.chat_llm, tag).as_runnable()
    # 注入与生产 02:08 完全同构的感知节点（含 digest 文本）
    from graph_model import Node, Edge
    sim.kg.add_node(Node(id="用户近况_replay", weight=0.6,
                         graph_space="episodic",
                         extra_attrs={"type": "perception",
                                      "source": "charon_workspace",
                                      "text": digest_text}))
    sim.kg.nodes["用户近况_replay"].activation = 5.0
    sim.kg.add_edge(Edge(src="用户", dst="用户近况_replay", relation="关注",
                         weight=0.9, relation_category="social_relation"))
    sim.engine.topk = [RE.FN("用户近况_replay", 3.0), RE.FN("用户", 3.0),
                       RE.FN("用户关系", 2.0)]
    for _ in range(4):
        sim._beat(10)
    sim.idle(90)
    sim.finish()
    gens = [c for c in CALLS_LOG if c["tag"] == tag]
    outs = [g["output"][:160] for g in gens]
    print(f"[{cond_name} r{repeat}] expressed={len(sim.expressed)} gen={outs}")
    return {"cond": cond_name, "repeat": repeat,
            "expressed": len(sim.expressed),
            "outputs": outs,
            "no_speak": sum(1 for o in outs if "NO_SPEAK" in o)}


def main():
    out = {"model": MODEL_ID, "digest": DIGEST[:80] + "...", "runs": []}
    for r in range(2):
        out["runs"].append(run("1原始", DIGEST, "", r))
    for r in range(2):
        out["runs"].append(run("2证据澄清", DIGEST_CLARIFIED, "", r))
    for r in range(2):
        out["runs"].append(run("3动机约束", DIGEST, CONSTR_MOTIVATION, r))
    for r in range(2):
        out["runs"].append(run("4无表达压力", DIGEST, CONSTR_SILENCE, r))
    p = os.path.join(RE.RESULTS_DIR, f"c6_diagnosis_{int(_rt.time())}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, default=str)
    print("saved:", p, "| calls:", len(CALLS_LOG))


if __name__ == "__main__":
    main()
