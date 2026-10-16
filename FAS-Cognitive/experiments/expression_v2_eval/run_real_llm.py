# -*- coding: utf-8 -*-
"""run_real_llm.py — 阶段A：v2 判定层接入真实 LLM（MiMo，复用项目既有配置）。

隔离：判定层决策与上轮完全一致；真实 LLM 仅在 _express 生成阶段被调用，
输出只进捕获通道；prompt/输出全量记录，密钥不落日志。
评分 rubric 在运行前固定（RUBRIC 常量），人工可审计：报告附原始生成文本+证据。
"""
import json
import os
import sys
import time as _rt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))            # FAS-Cognitive 根
sys.path.insert(0, "E:/Project/FAS-Companion")       # NLPProcessor/语言总线

import run_eval as RE                                 # 上一轮 harness（场景复用）
from langchain_core.runnables import RunnableLambda

# ── 真实 LLM 装配（复用项目既有 provider 配置；密钥不打印） ──
_CFG = json.load(open("E:/Project/FAS-Companion/data/llm_config.json",
                      encoding="utf-8"))
_KEY = json.load(open("E:/Project/FAS-Companion/data/llm_secret.json",
                      encoding="utf-8")).get("api_key", "")
sys.path.insert(0, "E:/Project/FAS-Cognitive")

import config as C
from nlp_processor import NLPProcessor

REAL_NLP = NLPProcessor(provider=_CFG.get("provider"),
                        api_key=_KEY or None,
                        model=_CFG.get("model"))
MODEL_ID = f"{_CFG.get('provider')}/{_CFG.get('model')}"

CALLS = []          # 全部生成调用记录


class CaptureChat:
    """包装真实 chat_llm：记录渲染 prompt 与原始输出，透传调用。"""

    def __init__(self, inner, tag):
        self.inner = inner
        self.tag = tag

    def as_runnable(self):
        cap = self

        def fn(prompt_value):
            rendered = prompt_value.to_string()
            t0 = _rt.time()
            err = None
            out = None
            try:
                out = cap.inner.invoke(prompt_value)
            except Exception as e:               # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            dt = round(_rt.time() - t0, 2)
            text = getattr(out, "content", None) or (str(out) if out else "")
            CALLS.append({"tag": cap.tag, "t": round(_rt.time(), 1),
                          "latency_s": dt, "error": err,
                          "prompt_tail": rendered[-600:],
                          "output": str(text)[:400]})
            if err:
                raise RuntimeError(err)
            return out

        return RunnableLambda(fn)


def sim_real(sc_fn, v2, repeat, opps, name):
    """真实 LLM 版 Sim：除生成器外与上一轮 harness 完全一致。"""
    sim = RE.Sim(v2=v2, seed=0)
    tag = f"{name}|{'v2' if v2 else 'v1'}|r{repeat}"
    sim.cc.nlp = REAL_NLP                                 # 真实模板+语言总线
    sim.cc.nlp.chat_llm = CaptureChat(REAL_NLP.chat_llm, tag).as_runnable()
    sc_fn(sim)
    sim.idle(60)
    sim.finish()
    rec = RE.summarize(sim, {"name": name, "family": "real", "opps": opps},
                       v2, repeat)
    rec["generations"] = [c for c in CALLS if c["tag"] == tag]
    return rec


def main():
    import run_eval
    picks = ["A2 新术语询问", "B1 认知发现分享", "B5 弱起强化",
             "B10 过期证据分享", "C4 好奇无对象", "C5 社交需求无内容",
             "C6 对话后新念头", "C10 混合价值流"]
    scs = {s["name"]: s for s in run_eval.ALL_SCENARIOS}
    out = {"model": MODEL_ID, "rubric": RUBRIC, "runs": []}
    for name in picks:
        sc = scs.get(name)
        if sc is None:
            print("missing scenario:", name)
            continue
        for v2 in (False, True):
            for r in range(3):
                rec = sim_real(sc["fn"], v2, r, sc["opps"], name)
                out["runs"].append(rec)
                print(f"{name} {'v2' if v2 else 'v1'} r{r}: "
                      f"expressed={rec['counts']['expressed_total']} "
                      f"goal={ [e.get('goal') for e in rec['expressed']] }")
    path = os.path.join(RE.RESULTS_DIR,
                        f"real_llm_{int(_rt.time())}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, default=str)
    print("saved:", path, "| llm calls:", len(CALLS))


# ── 评分 rubric（运行前固定；0-2 分，事实支持另设标记） ──
RUBRIC = {
    "dimensions": ["证据相关性", "事实支持", "交流价值", "重复性",
                   "语境适配", "自然程度", "打扰成本"],
    "scale": "0=明显失败 1=部分满足/有明显瑕疵 2=满足",
    "fact_support_marker": "supported | unsupported | uncertain",
    "notes": [
        "语言流畅不等于交流价值",
        "模型自述情绪/好奇不视为真实动机证据",
        "最终质量判定需人工可审计：报告附生成原文与证据，AI 辅助评分仅供初筛",
    ],
}

if __name__ == "__main__":
    main()
