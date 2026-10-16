# run_llm.py — serial_fix 行为层（小规模）：3 条件 × 6 问 × 3 配对种子 = 54 决策
# 条件：
#   G3-ids      现状复刻（R2 情节新近性激活 + ids 序列化）
#   G3-narrfix  R2 + 事件属性化表示修复 + 叙事序列化（1-hop 图补全）
#   B2-flat     原 B2 参照（检索行扁平序列化，字符相似度确定性近似）
# 判定（非 LLM）：exact_success = gold_chain 全部实体 ∧ gold_actions 全部
# 动作词出现在回答中（与原实验 exact 口径同族）。max_tokens=400（v1 教训）。
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

from run_mech import build_kg, QUESTIONS, EPISODES      # noqa: E402
import serialize as S                                   # noqa: E402

PARENT = r"E:\Project\Fascinator"
OUT = os.path.join(HERE, "campaign_l", "run_" + time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)
N_SEEDS = 3
K = 8
PROMPT = """You are answering questions about a small world.
Question: {question}
{context}
Answer in Chinese. If the context connects the entities through
intermediate entities/relations, describe the connecting chain.
If the context does not contain enough information, say so.
Answer:"""


def make_head():
    import openai
    sys.path.insert(0, PARENT)
    sys.path.insert(1, os.path.join(PARENT, "scripts"))
    sec = json.load(open(os.path.join(PARENT, "data", "llm_secret.json"),
                         encoding="utf-8"))
    from llm_provider import MiMoBackend
    return (openai.OpenAI(api_key=sec["api_key"],
                          base_url=MiMoBackend._DEFAULT_BASE_URL),
            MiMoBackend._DEFAULT_MODEL)


def context_for(cond, q, kg=None, eng=None):
    if cond == "B2-flat":
        return S.serial_flat(q["text"], EPISODES, k=6)
    top, edges = eng.get_topk(k=K)
    if cond == "G3-ids":
        return S.serial_ids(top, edges)
    return S.serial_narrative(top, edges, kg=kg, episodes=EPISODES)


def judge(ans, q):
    a = ans or ""
    chain = all(e in a for e in q["gold_chain"])
    acts = all(v in a for v in q["gold_actions"])
    return chain and acts, chain, acts


def main():
    client, model = make_head()
    head = {"model": model, "temperature": 0, "max_tokens": 400}
    raw = []
    for q in QUESTIONS:
        for seed in range(1, N_SEEDS + 1):
            # 配对：同种子下三条件共享同一激活/上下文构建路径
            for cond in ("G3-ids", "G3-narrfix", "B2-flat"):
                if cond == "B2-flat":
                    kg = eng = None
                else:
                    kg, eng = build_kg("eventframe", rep_fix=(cond == "G3-narrfix"))
                    eng.activate_from_inputs(list(q["seeds"]), [])
                    ev = [nid for nid in kg.nodes
                          if str(nid).startswith("事件:")]
                    eng.activate_from_inputs(ev, [])   # R2 情节新近性
                    eng.diffuse_round()
                ctx = context_for(cond, q, kg, eng)
                prompt = PROMPT.format(question=q["text"], context=ctx)
                t0 = time.time()
                try:
                    r = client.chat.completions.create(
                        model=model, temperature=0, max_tokens=400,
                        messages=[{"role": "user", "content": prompt}])
                    ans = r.choices[0].message.content or ""
                    u = getattr(r, "usage", None)
                    ptok = (u.prompt_tokens or 0) if u else 0
                    ctok = (u.completion_tokens or 0) if u else 0
                except Exception as e:
                    raw.append({"qid": q["id"], "cond": cond,
                                "seed": seed, "error": str(e)[:200]})
                    continue
                ok, chain, acts = judge(ans, q)
                raw.append({"qid": q["id"], "cond": cond, "seed": seed,
                            "success": ok, "chain": chain, "acts": acts,
                            "prompt_tokens": ptok, "completion_tokens": ctok,
                            "latency_s": round(time.time() - t0, 2),
                            "chars_ctx": len(ctx),
                            "response": ans.strip()[:300]})
                print(f"[{q['id']} {cond} s{seed}] ok={ok} -> {ans.strip()[:50]}")
    by = {(r["qid"], r["cond"], r["seed"]): r for r in raw
          if "success" in r}
    stats = []
    for x_cond, y_cond in (("G3-ids", "G3-narrfix"),
                           ("G3-ids", "B2-flat"),
                           ("G3-narrfix", "B2-flat")):
        xs, ys = [], []
        for q in QUESTIONS:
            for s in range(1, N_SEEDS + 1):
                xr = by.get((q["id"], x_cond, s))
                yr = by.get((q["id"], y_cond, s))
                if xr and yr:
                    xs.append(xr["success"])
                    ys.append(yr["success"])
        b = sum(1 for a, c in zip(xs, ys) if a and not c)
        c = sum(1 for a, cc in zip(xs, ys) if cc and not a)
        n = b + c
        p = 1.0 if n == 0 else min(1.0, 2 * sum(
            math.comb(n, k2) for k2 in range(0, min(b, c) + 1)) * 0.5 ** n)
        stats.append({"contrast": f"{y_cond}-{x_cond}",
                      "rateX": sum(ys) / len(ys) if ys else None,
                      "rateY0": sum(xs) / len(xs) if xs else None,
                      "discordant_X_only": c, "discordant_base_only": b,
                      "p_mcnemar_exact": round(p, 4)})
    cost = {}
    for cond in ("G3-ids", "G3-narrfix", "B2-flat"):
        rs = [r for r in raw if r.get("cond") == cond and "success" in r]
        if rs:
            cost[cond] = {"n": len(rs),
                          "mean_ctx_chars": round(sum(r["chars_ctx"]
                                                      for r in rs) / len(rs)),
                          "mean_ptok": round(sum(r["prompt_tokens"]
                                                 for r in rs) / len(rs), 1)}
    with open(os.path.join(OUT, "raw_llm.jsonl"), "w", encoding="utf-8") as f:
        json.dump({"head": head, "k": K, "n_seeds": N_SEEDS}, f,
                  ensure_ascii=False)
        f.write("\n")
        for r in raw:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "llm_stats.json"), "w",
              encoding="utf-8") as f:
        json.dump({"head": head, "mcnemar": stats, "cost": cost}, f,
                  ensure_ascii=False, indent=1)
    print("\n=== McNemar (paired over 6q×3seeds) ===")
    for srow in stats:
        print(srow)
    print("=== cost ===")
    print(cost)
    print("out:", OUT)


if __name__ == "__main__":
    main()
