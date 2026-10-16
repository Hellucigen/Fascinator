# run_verify2.py — 第二阶段收尾真实验证（宿主同构）：
#   ①新抽取链路（900 tok + salvage + 重试≤1）对 Inferno 前 6 单元复验
#   ②读后问答（真实证据包→模型作答）+ Cato 未知探针（no_evidence→缺口）
#   ③跨语料：Alice 前 2 单元
# 调用与上一轮同构：system=宿主 prompt_templates.READER_EXTRACT，
# human=reading.make_llm_extractor 的提示文本（即 nlp.ask("reader_extract", p)
# 的原样语义）。预算硬顶 14 次；ALLOW_LLM=1 授权闸。
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HOST = os.path.dirname(ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

ALLOW = os.environ.get("ALLOW_LLM") == "1"
CAP = 14
n = {"calls": [0], "log": []}

if not ALLOW:
    print("ALLOW_LLM!=1，拒绝调用")
    sys.exit(2)

import openai                                        # noqa: E402
sys.path.insert(1, HOST)
sys.path.insert(1, os.path.join(HOST, "FAS-Companion"))
sec = json.load(open(os.path.join(HOST, "FAS-Companion", "data",
                                  "llm_secret.json"), encoding="utf-8"))
from prompt_templates import READER_EXTRACT          # noqa: E402  宿主模板
from graph_model import KnowledgeGraph               # noqa: E402
from experience import ExperienceTimeline            # noqa: E402
import reading as RD                                 # noqa: E402
from llm_provider import MiMoBackend                 # noqa: E402

MODEL = MiMoBackend._DEFAULT_MODEL
CLIENT = openai.OpenAI(api_key=sec.get("mimo_api_key") or sec["api_key"],
                       base_url=MiMoBackend._DEFAULT_BASE_URL)


def nlp_ask_reader(p, max_tokens=900):
    """宿主 nlp.ask("reader_extract", p) 的等价调用。"""
    if n["calls"][0] >= CAP:
        raise RuntimeError("预算硬顶 14")
    t0 = time.time()
    r = CLIENT.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens,
        messages=[{"role": "system", "content": READER_EXTRACT},
                  {"role": "user", "content": p}])
    row = {"model": MODEL, "max_tokens": max_tokens,
           "prompt_tokens": r.usage.prompt_tokens,
           "completion_tokens": r.usage.completion_tokens,
           "latency_s": round(time.time() - t0, 2),
           "raw": (r.choices[0].message.content or "")[:600]}
    n["calls"][0] += 1
    n["log"].append(row)
    print(f"  [call {n['calls'][0]}] tok={row['prompt_tokens']}+"
          f"{row['completion_tokens']} {row['latency_s']}s")
    return row["raw"]


ANSWER_SYS = ("Answer the reader's question using ONLY the evidence facts "
              "given. If the evidence does not contain the answer, reply "
              "exactly: INSUFFICIENT_EVIDENCE. Brief.")


def answer_with_pack(pack, question, max_tokens=400):
    if n["calls"][0] >= CAP:
        raise RuntimeError("预算硬顶 14")
    t0 = time.time()
    r = CLIENT.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens,
        messages=[{"role": "system", "content": ANSWER_SYS},
                  {"role": "user",
                   "content": f"Question: {question}\n{pack}"}])
    n["calls"][0] += 1
    n["log"].append({"model": MODEL, "purpose": "answer",
                     "prompt_tokens": r.usage.prompt_tokens,
                     "completion_tokens": r.usage.completion_tokens,
                     "latency_s": round(time.time() - t0, 2),
                     "raw": r.choices[0].message.content or ""})
    return (r.choices[0].message.content or "").strip()


def main():
    tmp = tempfile.mkdtemp(prefix="verify2_")
    lp = os.path.join(tmp, "ledger.json")
    tl = ExperienceTimeline(path=os.path.join(tmp, "tl.json"))
    out = {}

    # ① Inferno 前 6 单元（与上一轮同一切片，直接对照 3/6 失败基线）
    src = RD.load_source(os.path.join(HERE, "corpus", "inferno_c1.json"))
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    led = RD.open_ledger(lp, src)
    ex = RD.make_llm_extractor(
        lambda p: nlp_ask_reader(p), max_retries=1)
    res = []
    for k in range(1, 7):
        r = led.read_unit(k, ex, kg, tl=tl)
        res.append({"unit": k, "status": r["status"],
                    "partial": r.get("partial"),
                    "relations": r.get("relations", 0),
                    "error": (led.data[src["source_id"]]["units"][str(k)]
                              .get("error") or "")[:80]})
        print(f"unit {k}: {r['status']} partial={r.get('partial')} "
              f"rels={r.get('relations', 0)}")
    out["inferno_units"] = res
    out["inferno_facts"] = [
        {"s": f["s"], "rel": f["p"], "o": f["o"], "kind": f["kind"],
         "unit": f["unit"]}
        for f in led.data[src["source_id"]]["facts"]][:24]
    out["progress"] = led.progress_report()

    # ② 读后问答（真实）+ Cato 未知探针
    pk = led.evidence_pack("Where is Dante at the very beginning of the book?",
                           kg=kg)
    out["q1_state"] = pk["state"]
    out["q1_answer"] = (answer_with_pack(pk["pack"], "Where is Dante at the "
                         "very beginning of the book?")
                        if pk["state"] in ("sufficient", "conflict")
                        else "SKIPPED(no evidence)")
    pk2 = led.evidence_pack("What does Cato say on the shore of Purgatory?",
                            kg=kg)
    out["q2_state"] = pk2["state"]
    if pk2["state"] == "insufficient":
        out["q2_gap_registered"] = bool(led.register_gap(
            kg, None, "Cato 在净界海边的言行", config=None))
    out["conflicts"] = led.scan_conflicts()[:4]

    # ③ 跨语料（Alice 前 2 单元 + 1 问答）
    asrc = RD.load_source(os.path.join(HERE, "corpus", "alice_ch1.json"))
    kg2 = KnowledgeGraph()
    kg2.save = lambda *a, **k: None
    aled = RD.open_ledger(os.path.join(tmp, "alice.json"), asrc)
    ares = [aled.read_unit(k, ex, kg2, tl=tl)["status"] for k in (1, 2)]
    ap = aled.evidence_pack("Where is Alice at the beginning?", kg=kg2)
    out["alice_units"] = ares
    out["alice_state"] = ap["state"]
    out["alice_answer"] = (answer_with_pack(ap["pack"],
                            "Where is Alice at the beginning?")
                           if ap["state"] != "insufficient"
                           else "INSUFFICIENT_EVIDENCE")

    out["calls"] = n["calls"][0]
    out["tokens"] = [f"{x['prompt_tokens']}+{x['completion_tokens']}"
                     for x in n["log"]]
    d = os.path.join(HERE, f"verify2_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, "verify2_results.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(n, open(os.path.join(d, "llm_calls.json"), "w",
                      encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items()
                      if k != "inferno_facts"},
                     ensure_ascii=False, indent=1)[:1800])
    print("out:", d)


if __name__ == "__main__":
    main()
