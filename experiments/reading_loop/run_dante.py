# run_dante.py — 《神曲》主测试 + 跨语料泛化：真实 LLM 集成实验（A-F）
# 预算硬顶 16 次调用（超限即中止）；每次调用记录 model/tokens/latency/purpose。
# 语料：Project Gutenberg 公版真实切片（inferno_c1 8 单元 / alice_ch1 5 单元）。
# 严禁任务专用分支：reading.py 对所有语料同一路径；本脚本只做编排与记分。
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

import openai                                       # noqa: E402
from graph_model import KnowledgeGraph              # noqa: E402
from experience import ExperienceTimeline           # noqa: E402
import reading as RD                                # noqa: E402

PARENTS = [r"E:\Project\FAS-Companion", r"E:\Project\Fascinator"]
OUT = os.path.join(HERE, "artifacts_" + time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)
CALL_CAP = 10   # 前次崩溃运行已耗 6 次（无效消耗，如实入账）；总账 16
_calls = {"n": 0, "log": []}

def _find_secret():
    for pth in PARENTS:
        for cand in (os.path.join(pth, "data", "llm_secret.json"),
                     os.path.join(pth, "llm_secret.json")):
            if os.path.exists(cand):
                return cand
    raise FileNotFoundError("llm_secret.json not found under "
                            + ", ".join(PARENTS))


def _find_provider():
    for pth in PARENTS:
        for cand in (os.path.join(pth, "llm_provider.py"),
                     os.path.join(pth, "scripts", "llm_provider.py")):
            if os.path.exists(cand):
                return os.path.dirname(cand)
    raise FileNotFoundError("llm_provider.py not found")


sec = json.load(open(_find_secret(), encoding="utf-8"))
sys.path.insert(1, _find_provider())
from llm_provider import MiMoBackend                # noqa: E402
MODEL = MiMoBackend._DEFAULT_MODEL
CLIENT = openai.OpenAI(api_key=sec.get("mimo_api_key") or sec["api_key"],
                       base_url=MiMoBackend._DEFAULT_BASE_URL)

EXTRACT_SYS = (
    "You extract knowledge from a literary text unit. Return STRICT JSON: "
    '{"entities": [names], "relations": [{"src":..,"rel":..,"dst":..,'
    '"kind":"text|inference","quote":"short exact phrase"}]}. '
    'Use ONLY these rel values: 位于 拥有 需要 导致 涉及 属于 是 叫做 相关 包含. '
    'kind=text only if the unit states it; kind=inference otherwise. No prose.')
ANSWER_SYS = (
    "Answer the reader's question using ONLY the evidence facts given "
    "(unit = where in the book it was read). If the evidence does not "
    "contain the answer, reply exactly: INSUFFICIENT_EVIDENCE. Be brief.")


def llm(purpose, messages, max_tokens=400):
    if _calls["n"] >= CALL_CAP:
        raise RuntimeError(f"预算硬顶 {CALL_CAP} 次调用已耗尽")
    t0 = time.time()
    r = CLIENT.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens,
        messages=messages)
    row = {"purpose": purpose, "model": MODEL,
           "prompt_tokens": r.usage.prompt_tokens,
           "completion_tokens": r.usage.completion_tokens,
           "latency_s": round(time.time() - t0, 2),
           "answer": r.choices[0].message.content or ""}
    _calls["n"] += 1
    _calls["log"].append(row)
    assert os.environ.get("ALLOW_LLM") == "1", "LLM 未授权"
    print(f"[llm {purpose}] tok={row['prompt_tokens']}+"
          f"{row['completion_tokens']} {row['latency_s']}s")
    return row["answer"]


def make_extractor():
    def ex(text):
        raw = llm("extract", [{"role": "system", "content": EXTRACT_SYS},
                              {"role": "user",
                               "content": text[:1500]}], 500)
        i, j = raw.find("{"), raw.rfind("}")
        try:
            d = json.loads(raw[i:j + 1])
            assert isinstance(d.get("entities"), list)
            return d
        except Exception:
            # 抽取失败按 failed 记录（不静默伪造成功）
            raise RuntimeError("extractor produced non-JSON")
    return ex


def pack_evidence(facts):
    return "\n".join(f"- [unit {f['unit']}] {f['s']} -{f['p']}-> {f['o']} "
                     f"({f['kind']})" for f in facts[:12])


def run():
    results = {}
    tmp = tempfile.mkdtemp(prefix="dante_ledger_")
    ledger_path = os.path.join(tmp, "reading_ledger.json")
    tl = ExperienceTimeline(path=os.path.join(tmp, "tl.json"))
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    src = RD.load_source(os.path.join(HERE, "corpus", "inferno_c1.json"))
    led = RD.ReadingLedger(src, ledger_path)
    ex = make_extractor()

    # ── A：目标形成（LLM 无关，纯结构证据）──
    results["A_goal"] = {"goal": led.data[src["source_id"]]["goal"],
                         "first_next": led.next_unit()}

    # ── B：分段学习（读 6 单元，真实抽取+写回）+ 旧知识调用 ──
    read_log = []
    for n in range(1, 7):
        r = led.read_unit(n, ex, kg, tl=tl)
        read_log.append({"unit": n, "status": r["status"],
                         "relations": r.get("relations", 0)})
    results["B_read"] = read_log

    def answer(q):
        units, facts = led.evidence_for(q)
        if not units:
            return {"status": "no_evidence", **led.ask(q)}
        ans = llm("answer", [{"role": "system", "content": ANSWER_SYS},
                             {"role": "user",
                              "content": (f"Question: {q}"
                                         + chr(10) + "Evidence:" + chr(10)
                                         + pack_evidence(facts))}], 300)
        return {"status": "evidence", "units": units,
                "n_facts": len(facts), "answer": ans[:300]}

    results["B_q_wood"] = answer("Where is Dante at the very beginning?")
    results["B_q_beast"] = answer("Which beast blocks Dante's path up the hill?")

    # ── C/D：恢复与冲突扫描（不调用 LLM；机制层由确定性测试锁定）──
    led2 = RD.ReadingLedger(src, ledger_path)
    results["C_resume"] = {
        "progress_after_restart": led2.progress(),
        "next_unit_after_restart": led2.next_unit()}
    results["D_conflicts"] = led2.scan_conflicts()[:6]
    results["D_history_query"] = [
        {"object": h["object"], "valid_from": h["valid_from"],
         "valid_until": h["valid_until"]}
        for h in __import__("memrep").fact_history(tl, *("Dante", "位于"))][:6]

    # ── E：未知与重规划 + 无闸门基线对照 ──
    results["E_gated"] = answer("What does Cato say on the shore of Purgatory?")
    base = llm("baseline_fabrication_probe",
               [{"role": "user",
                 "content": "In Dante's Divine Comedy, what does Cato say on "
                            "the shore of Purgatory? Answer briefly."}], 200)
    results["E_baseline_no_gate"] = {"answer": base[:250]}

    # ── F：跨任务泛化（同代码路径，Alice 语料，真实抽取）──
    aside = os.path.join(tmp, "alice_ledger.json")
    asrc = RD.load_source(os.path.join(HERE, "corpus", "alice_ch1.json"))
    kg_a = KnowledgeGraph(); kg_a.save = lambda *a, **k: None
    aled = RD.ReadingLedger(asrc, aside)
    ar = [aled.read_unit(n, ex, kg_a, tl=tl)["status"] for n in (1, 2)]
    au, af = aled.evidence_for("Where is Alice at the start?")
    ares = ("INSUFFICIENT_EVIDENCE" if not au else llm(
        "answer_alice",
        [{"role": "system", "content": ANSWER_SYS},
         {"role": "user", "content": "Question: Where is Alice at the start?"
          + chr(10) + "Evidence:" + chr(10)
          + pack_evidence(af)}], 250))
    results["F_alice"] = {"read": ar, "answer": ares[:200],
                          "progress": aled.progress()}

    results["claims_vs_evidence_inferno"] = led2.claims_vs_evidence()
    results["dropped_relations_count"] = len(
        led2.data[src["source_id"]].get("dropped_relations", []))
    with open(os.path.join(OUT, "dante_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "llm_calls.json"), "w", encoding="utf-8") as f:
        json.dump(_calls, f, ensure_ascii=False, indent=1)
    tot_pt = sum(c["prompt_tokens"] for c in _calls["log"])
    tot_ct = sum(c["completion_tokens"] for c in _calls["log"])
    print(f"\ncalls={_calls['n']}/{CALL_CAP} tokens={tot_pt}+{tot_ct}")
    print("out:", OUT)
    for k in ("B_q_virgil", "B_q_wood", "C_reuse_old", "E_gated",
              "E_baseline_no_gate", "F_alice"):
        print("·", k, json.dumps(results[k], ensure_ascii=False)[:220])


if __name__ == "__main__":
    run()
