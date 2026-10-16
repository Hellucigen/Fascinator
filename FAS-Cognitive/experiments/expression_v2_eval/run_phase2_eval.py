# -*- coding: utf-8 -*-
"""run_phase2_eval.py — 阶段2（边界措辞验证）+ 阶段3（"值得打扰"八场景评估）。

阶段2：生产新措辞 digest（含边界句） vs 原始 digest，各 3 次真实生成，
检查虚构行为词（同时开着/切换/先点开）是否消失。
阶段3：八场景经 v1 生产路径（flag 关）运行，对照"运行前预声明"的
应表达判定——显著性≠交流价值的实证矩阵。
全部隔离捕获，零真实投递。生产代码本轮零修改（快照修复在工作区待部署）。
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
from run_real_llm import REAL_NLP, CaptureChat, MODEL_ID
from graph_model import Node, Edge

CALLS = []


def sim_run(name, nodes, topk, drives=None, beats=40, idle_after=600, v1=True):
    sim = RE.Sim(v2=not v1)
    tag = name
    sim.cc.nlp = REAL_NLP
    sim.cc.nlp.chat_llm = CaptureChat(REAL_NLP.chat_llm, tag).as_runnable()
    if drives is not None:
        sim.set_drives(drives)
    for spec in nodes:
        nid = spec["id"]
        sim.kg.add_node(Node(id=nid, weight=0.6,
                             graph_space=spec.get("space", "episodic"),
                             extra_attrs=spec.get("ea") or {}))
        sim.kg.nodes[nid].activation = spec.get("act", 3.0)
        if spec.get("link_user", True) and sim.kg.get_node("用户"):
            sim.kg.add_edge(Edge(src="用户", dst=nid, relation="关注",
                                 weight=0.9, relation_category="social_relation"))
    tk = [(t[0], t[1]) if isinstance(t, tuple) else
          (t["id"], t.get("act", 3.0)) for t in topk]
    end = sim.t + beats * 10
    while sim.t < end:
        sim.engine.topk = [RE.FN(a, b) for a, b in tk]
        sim._beat(10)
    sim.idle(idle_after)
    sim.finish()
    gens = [c["output"][:120] for c in
            __import__("run_real_llm").CALLS if c["tag"] == tag]
    verdicts = {cid: h[-1].get("verdict") for cid, h in sim.ci_hist.items()}
    return {"expressed": [{"basis": (e.get("basis") or [])[:3],
                           "text": e.get("text", "")[:100]}
                          for e in sim.expressed],
            "gens": gens, "verdicts": verdicts,
            "channel": len(sim.channel.got)}


def main():
    out = {"model": MODEL_ID, "runs": {}}

    # ── 阶段2：边界措辞对比（生产将上线的确切措辞） ──
    TITLES = ("用户工作区快照 — 最近笔记：日記（Notion同步）；リーディングリスト"
              "（Notion同步）；Movie List；概念ノート；AI学習計画")
    BOUNDARY = "（以上只是清单快照，不代表用户正在打开或操作它们）"
    FICTION_MARKERS = ["同时开着", "切换", "先点开", "几摊"]
    for label, digest in (("原始措辞", TITLES),
                          ("边界措辞(将上线)", TITLES + BOUNDARY)):
        results = []
        for r in range(3):
            sim = RE.Sim(v2=False)
            tag = f"措辞-{label}-r{r}"
            sim.cc.nlp = REAL_NLP
            sim.cc.nlp.chat_llm = CaptureChat(REAL_NLP.chat_llm,
                                              tag).as_runnable()
            sim.kg.add_node(Node(id="用户近况_w", weight=0.6,
                                 graph_space="episodic",
                                 extra_attrs={"type": "perception",
                                              "source": "charon_workspace",
                                              "text": digest}))
            sim.kg.nodes["用户近况_w"].activation = 5.0
            sim.kg.add_edge(Edge(src="用户", dst="用户近况_w", relation="关注",
                                 weight=0.9,
                                 relation_category="social_relation"))
            sim.engine.topk = [RE.FN("用户近况_w", 3.0), RE.FN("用户", 3.0),
                               RE.FN("用户关系", 2.0)]
            for _ in range(4):
                sim._beat(10)
            sim.idle(90)
            sim.finish()
            gens = [c["output"][:120] for c in
                    __import__("run_real_llm").CALLS if c["tag"] == tag]
            fiction = sum(1 for g in gens
                          if any(m in g for m in FICTION_MARKERS))
            results.append({"gens": gens, "fiction_count": fiction})
        total_f = sum(r["fiction_count"] for r in results)
        total_g = sum(len(r["gens"]) for r in results)
        out["runs"][f"阶段2-{label}"] = {
            "generations": total_g, "fiction_marker_hits": total_f,
            "detail": results}
        print(f"阶段2 {label}: 生成{total_g} 次，虚构行为词命中 {total_f}")

    # ── 阶段3：八场景"值得打扰"评估（v1 生产路径） ──
    # 运行前预声明的"应表达？"判定（依据：证据真实性×新鲜度×具体动机）：
    # S1 重启重复清单(新代码已防): 不应表达   S2 新笔记无讨论: 可表达(低价值)
    # S3 用户刚表达的兴趣:      应表达       S4 任务有意义进展: 应表达
    # S5 相关真实追问:          应表达       S6 无事件无动机:   不应表达
    # S7 高显著低价值内部状态:  不应表达     S8 低显著但当下有用: 理想应表达
    pre = {"S1": False, "S2": None, "S3": True, "S4": True, "S5": True,
           "S6": False, "S7": False, "S8": True}

    def run8(sid, nodes, topk, drives=None, **kw):
        r = sim_run(f"{sid}", nodes, topk, drives, **kw)
        n_exp = len(r["expressed"])
        fiction = sum(1 for g in r["gens"]
                      if any(m in g for m in FICTION_MARKERS))
        out["runs"][f"阶段3-{sid}"] = {
            "预声明应表达": pre[sid], "实际表达数": n_exp,
            "verdicts": r["verdicts"], "gens": r["gens"],
            "fiction_markers": fiction}
        print(f"阶段3 {sid}: 应表达={pre[sid]} 实际表达={n_exp} "
              f"verdicts={list(r['verdicts'].values())[:3]}")

    run8("S1", [{"id": "用户近况_s1", "ea": {"type": "perception",
          "source": "charon_workspace", "baseline": True,
          "text": TITLES + BOUNDARY}, "act": 1.2}],
         [("用户近况_s1", 1.2), ("用户", 2.0)])
    run8("S2", [{"id": "用户近况_s2",
                 "ea": {"type": "perception", "source": "charon_workspace",
                        "text": "用户工作区快照 — 最近笔记新增：模组剧情大纲（今天刚建）"},
                 "act": 5.0}],
         [("用户近况_s2", 3.0), ("用户", 3.0), ("用户关系", 2.0)])
    run8("S3", [{"id": "用户兴趣_s3",
                 "ea": {"type": "perception",
                        "text": "用户刚明确说想学 AI 学習計画里的内容"},
                 "act": 4.0}],
         [("用户兴趣_s3", 4.0), ("用户", 3.0), ("用户关系", 2.0)],
         drives={"curiosity": 0.6, "social": 0.5})
    run8("S4", [{"id": "任务进展_s4",
                 "ea": {"type": "perception",
                        "text": "用户的模组项目完成了第一版剧情骨架"},
                 "act": 4.0}],
         [("任务进展_s4", 4.0), ("用户", 3.0), ("用户关系", 2.0)],
         drives={"social": 0.5})
    run8("S5", [{"id": "追问_s5",
                 "ea": {"type": "perception",
                        "text": "对话里用户提到但没解释的'转码偏差'概念"},
                 "act": 3.5}],
         [("追问_s5", 3.5), ("用户", 3.0), ("CuriosityDrive", 2.5)],
         drives={"curiosity": 0.7})
    run8("S6", [], [], drives={"curiosity": 0.3, "social": 0.8})
    run8("S7", [{"id": "内部状态_s7", "space": "cognitive",
                 "ea": {"type": "cognitive_network"}, "act": 3.0,
                 "link_user": False}],
         [("内部状态_s7", 3.0)], drives={"curiosity": 0.4})
    run8("S8", [{"id": "线索_s8",
                 "ea": {"type": "perception",
                        "text": "用户正在编辑的文件里出现了刚才对话提到的那个函数名"},
                 "act": 1.5}],
         [("线索_s8", 1.5), ("用户", 2.5)],
         drives={"social": 0.4})

    path = os.path.join(RE.RESULTS_DIR, f"phase2_eval_{int(_rt.time())}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, default=str)
    print("saved:", path)


if __name__ == "__main__":
    main()
