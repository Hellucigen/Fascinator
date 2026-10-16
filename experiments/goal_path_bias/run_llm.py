# run_llm.py — 族 L（L-asym 变体）：行为层 A/B/C 配对实验，单次 LLM 决策/run
# 设计要点：
#   * 分歧世界：沙箱规则刻意偏离原版 Minecraft 常识（银镐、空手挖银矿），
#     使决策头的参数化知识无法答对——正确答案只能来自工作集（信息不对称口径，
#     beacon/A10 先例的隔离手段）。
#   * 同图、同种子（点火抖动配对）、同模型/温度/max_tokens、同 k=8 预算、
#     同提示模板；条件间唯一差异 = goal_path bias 开/关 + 可执行性检查。
#   * 评估器非 LLM：wp.next_step（生产规划器）给规范下一步，
#     答对 = 响应包含规范目标 token。逐 run 记录 token 是否可达（中介分层）。
#   * 停止：跑满 3 目标 × 3 条件 × 10 配对种子 = 90 决策；不追加。
import json
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge        # noqa: E402
from diffusion_engine import DiffusionEngine              # noqa: E402
from self_graph import bootstrap_self, set_current_goal   # noqa: E402
import world_prior as wp                                  # noqa: E402
import goal_path_bias as gpb                              # noqa: E402
import graphset as GS                                     # noqa: E402

OUT = os.path.join(HERE, "campaign_l", "run_" + time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)
N_SEEDS = 10
K = 8

# ── LLM 决策头（父仓实现口径：同模型/温度=0/max_tokens 固定/重试 3）──
PARENT = r"E:\Project\Fascinator"


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


# ── 分歧世界：全虚构材料链（参数化常识无法答对；附低可信陷阱支路）──
# 生产命名/属性口径；边带 provenance。规则刻意偏离 Minecraft：
#   ground_lumen ← lumen_sand×2（空手采光丘沙）；aether_lens ← ground_lumen。
#   陷阱支路：aether_lens ← void_glass（smelt 链，rare_sand 需 aether_lens
#   才能采 = 环），边权 0.3/置信 0.2 —— 测 B 是否强化死路。
#   resonance_core ← lumen_sand×2 ∧ hum_root×2（AND 双支）。
#   oak_planks 支链保留（常识一致的天花板哨兵层）。

def _prov(conf=0.9):
    return {"confidence": conf, "knowledge_type": "prior",
            "source": "goalpath-fictional-sandbox", "version_verified": True}


def build_world(target):
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    bootstrap_self(kg)
    kg.add_node(Node(id="Haru", graph_space="self"))

    def N(i, **kw):
        if kg.get_node(i) is None:
            kg.add_node(Node(id=i, **kw))

    def E(s, r, d, w=0.6, ea=None, cat=None):
        kw = {"extra_attrs": ea or _prov()}
        if cat:
            kw["relation_category"] = cat
        kg.add_edge(Edge(s, d, r, w, **kw))

    N("可采资源")

    def gather_leaf(block, item, conf=0.9):
        N(block, extra_attrs={"type": "mc_species"})
        N(f"物品:{item}")
        E(block, "属于", "可采资源", 0.8, cat="semantic_relation")
        E(block, "掉落", f"物品:{item}", 0.6, ea=_prov(conf))

    def recipe(rid, out_, ins, kind="hand", conf=0.9, needs_table=False):
        N(f"物品:{out_}")
        N(f"配方:{rid}:{kind}:0",
          extra_attrs={"type": "recipe", "kind": ("smelt" if kind == "smelt"
                                                  else "craft"),
                       "needs_table": needs_table,
                       **({"tool": "furnace"} if kind == "smelt" else {})})
        E(f"配方:{rid}:{kind}:0", "产生", f"物品:{out_}", 0.6, ea=_prov(conf))
        for mat, cnt in ins.items():
            N(f"物品:{mat}")
            E(f"配方:{rid}:{kind}:0", "需要", f"物品:{mat}", 0.6,
              ea={**_prov(conf), "count": cnt})

    # 主干（虚构名）
    gather_leaf("lumen_dune", "lumen_sand")
    gather_leaf("hum_vine", "hum_root")
    recipe("ground_lumen", "ground_lumen", {"lumen_sand": 2})
    recipe("aether_lens", "aether_lens", {"ground_lumen": 1})
    # 陷阱支路（低可信 + 环）
    gather_leaf("rare_deposit", "rare_sand", conf=0.2)
    E("rare_deposit", "需要工具", "aether_lens", 0.3,
      ea={**_prov(0.2), "note": "低可信边（测错误路径强化）"})
    recipe("void_glass", "void_glass", {"rare_sand": 1}, kind="smelt",
           conf=0.2)
    E("配方:aether_lens:smelt:0", "产生", "物品:aether_lens", 0.3,
      ea=_prov(0.2))
    E("配方:aether_lens:smelt:0", "需要", "物品:void_glass", 0.3,
      ea={**_prov(0.2), "count": 1})
    N("配方:aether_lens:smelt:0",
      extra_attrs={"type": "recipe", "kind": "smelt", "tool": "furnace"})
    # AND 双支目标
    recipe("resonance_core", "resonance_core",
           {"lumen_sand": 2, "hum_root": 2}, needs_table=True)
    # 常识一致哨兵层（MC 真名，答案与常识相同 → 预期零差分层）
    gather_leaf("oak_log", "oak_log")
    recipe("oak_planks", "oak_planks", {"oak_log": 1})

    # 全局固定干扰 fabric（三条件一致）
    for i in range(8):
        nid = f"经历_{i}"
        N(nid)
        E("Haru", "涉及", nid, 0.5, cat="episodic_relation")
        E("Haru", "关于", nid, 0.5, cat="episodic_relation")
    eng = DiffusionEngine(kg, dict(GS.ENG_CFG))
    eng.name_to_node = dict(kg.nodes)
    return kg, eng


TARGETS = ["aether_lens", "resonance_core", "oak_planks"]
VERBS = {"gather": ("挖", "采", "gather", "mine", "get", "拿", "收集",
                    "collect", "找", "去"),
         "craft": ("合成", "做", "造", "craft", "制作", "build", "make"),
         "smelt": ("烧", "炼", "smelt"),
         "explore": ("探索", "找", "explore", "search")}


def serialize_top(kg, eng):
    top, edges = eng.get_topk(k=K)
    lines = [f"- {n.id} (激活 {n.activation:.2f})" for n in top]
    rel = [f"  {e.src} -[{e.relation}]-> {e.dst} (w={e.weight:.1f})"
           for e in edges[:12]]
    return "\n".join(lines + rel), {n.id for n in top}


PROMPT = """你在一个沙箱世界里规划**一个**下一步行动。该世界的规则**可能与现实游戏常识不同**——只依据下面的记忆工作集，不要用外部常识猜测。

当前目标：获得 {target}
背包：空的（没有任何物品）
记忆工作集（按激活降序）：
{working}

规则提醒：世界规则以工作集里的关系为准。
问：为朝目标推进，**唯一正确的下一步**是什么？只回一行：
STEP: <动作 gather|craft|smelt> <目标的准确名字>
"""


def canonical_step(kg, target):
    st = wp.next_step(kg, target, {})
    act = st.get("action") or ""
    tok = str(st.get("item") or st.get("block") or "")
    if not tok:
        for n in kg.nodes:
            if str(n) == f"物品:{target}":
                return act, target
    return act, tok


def judge(ans, act, tok):
    a = (ans or "").lower()
    t = tok.lower()
    tok_hit = t in a
    verb_hit = any(v.lower() in a for v in VERBS.get(act, ()))
    return tok_hit and verb_hit, tok_hit, verb_hit


def main():
    client, model = make_head()
    head_meta = {"model": model, "temperature": 0, "max_tokens": 400,
                 "backend": "MiMo (parent llm_provider)"}
    raw = []
    conds = ("A", "B", "C")
    CFG_BY_COND = {"A": None,
                   "B": {"enabled": True, "search": True, "bias": True,
                         "require_state_anchor": False},
                   "C": {"enabled": True, "search": True, "bias": True,
                         "require_state_anchor": True}}
    total_calls = 0
    for target in TARGETS:
        kg0, _ = build_world(target)
        act, tok = canonical_step(kg0, target)
        for seed in range(1, N_SEEDS + 1):
            for cond in conds:
                kg, eng = build_world(target)
                set_current_goal(kg, f"获得 {target}")
                eng.name_to_node = dict(kg.nodes)
                rng = random.Random(seed * 104729 + sum(
                    ord(c) for c in target) * 7919)
                for i in range(8):
                    nid = f"经历_{i}"
                    kg.nodes[nid].activation = rng.uniform(0.3, 2.2)
                    kg.nodes[nid].touch()
                eng.mark_active([f"经历_{i}" for i in range(8)])
                eng.activate_from_inputs(["Haru"], [])
                tele = {"status": "n/a", "writes": 0}
                if cond != "A":
                    cfg = dict(GS.ENG_CFG)
                    cfg["goal_path"] = dict(gpb.DEFAULTS,
                                            **CFG_BY_COND[cond])
                    tele = gpb.run_goal_path(kg, eng, cfg)
                eng.diffuse_round(max_steps=3)
                working, top_set = serialize_top(kg, eng)
                prompt = PROMPT.format(target=target, working=working)
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
                    raw.append({"target": target, "cond": cond, "seed": seed,
                                "error": str(e)[:200]})
                    continue
                ok, tok_hit, verb_hit = judge(ans, act, tok)
                truth_tokens = {f"物品:{tok}", tok}
                tok_in_prompt = (f"物品:{tok}" in working
                                 or str(tok) in working)
                row = {"target": target, "cond": cond, "seed": seed,
                       "canonical": f"{act} {tok}", "success": ok,
                       "tok_hit": tok_hit, "verb_hit": verb_hit,
                       "token_in_prompt": tok_in_prompt,
                       "status": tele.get("status"),
                       "writes": tele.get("writes"),
                       "prompt_tokens": ptok, "completion_tokens": ctok,
                       "latency_s": round(time.time() - t0, 2),
                       "response": ans.strip()[:200]}
                raw.append(row)
                total_calls += 1
                print(f"[{target} {cond} s{seed}] ok={ok} "
                      f"canon={act} {tok} in_prompt={tok_in_prompt} "
                      f"-> {ans.strip()[:60]}")

    # ── 统计：McNemar 精确（配对二值），分层中介 ──
    def mcnemar(x, y):
        b = sum(1 for a, c in zip(x, y) if a and not c)   # A对B错
        cc = sum(1 for a, c in zip(x, y) if c and not a)  # B对A错
        n = b + cc
        if n == 0:
            return 1.0, b, cc
        p = sum(math.comb(n, k) for k in list(range(0, min(b, cc) + 1))) \
            * (0.5 ** n)
        return min(1.0, 2 * p), b, cc

    by = {(r["target"], r["cond"], r["seed"]): r for r in raw
          if "success" in r}
    stats = []
    for target in TARGETS:
        for cond in ("B", "C"):
            x = [by[(target, "A", s)]["success"] for s in range(1, N_SEEDS+1)
                 if (target, "A", s) in by and (target, cond, s) in by]
            y = [by[(target, cond, s)]["success"] for s in range(1, N_SEEDS+1)
                 if (target, "A", s) in by and (target, cond, s) in by]
            if not x:
                continue
            p, b, cc = mcnemar(x, y)
            stats.append({"target": target, "contrast": f"{cond}-A",
                          "rateA": sum(x)/len(x), "rateX": sum(y)/len(y),
                          "discordant_X_only": cc, "discordant_A_only": b,
                          "p_mcnemar_exact": round(p, 4)})
    # Holm
    fam = sorted(stats, key=lambda s: s["p_mcnemar_exact"])
    m = len(fam)
    run = 0.0
    for i, s in enumerate(fam):
        adj = min(1.0, (m - i) * s["p_mcnemar_exact"])
        run = max(run, adj)
        s["p_holm"] = round(run, 4)
    # 成本与中介分层
    cost = {}
    for cond in conds:
        rs = [r for r in raw if r.get("cond") == cond and "success" in r]
        cost[cond] = {"n": len(rs),
                      "mean_prompt_tok": round(sum(
                          r["prompt_tokens"] for r in rs)/max(1, len(rs)), 1),
                      "mean_latency_s": round(sum(
                          r["latency_s"] for r in rs)/max(1, len(rs)), 2)}
    med = {}
    for cond in conds:
        rs = [r for r in raw if r.get("cond") == cond and "success" in r]
        vis = [r for r in rs if r["token_in_prompt"]]
        inv = [r for r in rs if not r["token_in_prompt"]]
        med[cond] = {"success_given_token_visible": (
            sum(r["success"] for r in vis), len(vis)),
            "success_given_hidden": (
                sum(r["success"] for r in inv), len(inv))}

    with open(os.path.join(OUT, "raw_llm.jsonl"), "w", encoding="utf-8") as f:
        json.dump({"head": head_meta, "k": K, "n_seeds": N_SEEDS}, f,
                  ensure_ascii=False)
        f.write("\n")
        for r in raw:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "llm_stats.json"), "w", encoding="utf-8") as f:
        json.dump({"head": head_meta, "mcnemar_holm": stats,
                   "cost": cost, "mediation": med}, f,
                  ensure_ascii=False, indent=2)
    print("\n=== McNemar/Holm ===")
    for s in stats:
        print(s)
    print("=== cost ===")
    print(cost)
    print("=== mediation ===")
    print(med)
    print("calls:", total_calls, "out:", OUT)


if __name__ == "__main__":
    main()
