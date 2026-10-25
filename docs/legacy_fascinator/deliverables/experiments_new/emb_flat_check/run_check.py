# -*- coding: utf-8 -*-
# run_check.py — D-flat embedding 检索基线:import 级核实 + 零 LLM 检索可达性检验
# 设计冻结于 DESIGN.md(2026-10-01)。零 LLM;与信标战役 step-0 装配一致。
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_exp_routing_v2 as v2  # noqa: E402
import run_exp_beacon as bk  # noqa: E402

GOAL = bk.B1Beacon.goal_text  # 与战役相同的查询文本
K = 8                          # 与战役 flat_focus(k=8) 相同


def main():
    out = {}
    # 1) import 级核实:flat_focus 的实现与模型身份
    import inspect
    from embedding_manager import EmbeddingProvider, _resolve_local_model_path
    src = inspect.getsource(v2.FASContext.flat_focus)
    out["verification"] = {
        "flat_focus_uses_EmbeddingProvider": "EmbeddingProvider" in src,
        "no_activation_no_propagation": ("diffuse" not in src and "activation" not in
                                         src.replace("activation\": None", "")),
        "model_path": _resolve_local_model_path(),
        "model_is_dir": os.path.isdir(_resolve_local_model_path()),
        "k": K,
    }
    prov = EmbeddingProvider()
    _ = prov.model  # 强制加载
    out["verification"]["model_name"] = str(prov.model_name)

    # 2) 零 LLM 检索可达性检验:20 配对种子逐个重建 step-0 装配
    ranks = []
    for seed in range(20):
        world = v2.SandboxWorld()
        ex = bk.BeaconExecutor(world, gate=set())
        bk.B1Beacon().setup_phase(world, ex, 1)
        fc = bk.BeaconFASContext(world, use_diffusion=False, use_demand=False,
                                 use_flat=True)
        sel = fc.flat_focus(GOAL, k=K)
        ids = [s["id"] for s in sel]
        # 全图排序中的名次(1-based)
        full = fc.flat_focus(GOAL, k=10 ** 6)
        order = [s["id"] for s in full]
        r_planks = order.index("物品:oak_planks") + 1 if "物品:oak_planks" in order else None
        r_log = order.index("物品:oak_log") + 1 if "物品:oak_log" in order else None
        ranks.append({
            "seed": seed, "n_nodes": len(fc.kg.nodes),
            "top8": ids,
            "oak_planks_rank": r_planks, "oak_log_rank": r_log,
            "top8_hit_planks": "物品:oak_planks" in ids,
            "top8_hit_log": "物品:oak_log" in ids,
        })
        print("[emb-check] seed %d nodes=%d planks_rank=%s log_rank=%s top8_hit=%s"
              % (seed, ranks[-1]["n_nodes"], r_planks, r_log,
                 ranks[-1]["top8_hit_planks"]), flush=True)
    with open(os.path.join(HERE, "raw_ranks.jsonl"), "w", encoding="utf-8") as f:
        for r in ranks:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_planks = sum(r["top8_hit_planks"] for r in ranks)
    n_log = sum(r["top8_hit_log"] for r in ranks)
    out["analysis"] = {
        "n": len(ranks),
        "top8_hit_planks": n_planks,
        "top8_hit_log": n_log,
        "planks_rank_set": sorted({r["oak_planks_rank"] for r in ranks}),
        "log_rank_set": sorted({r["oak_log_rank"] for r in ranks}),
        "graph_nodes": sorted({r["n_nodes"] for r in ranks}),
    }
    with open(os.path.join(HERE, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("done:", json.dumps(out["analysis"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
