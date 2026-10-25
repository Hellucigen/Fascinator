# -*- coding: utf-8 -*-
"""graph_doctor — 图谱质量基线诊断（只读；结构/语义/消费三维）。

用法：python scripts/graph_doctor.py [graph.json]
默认诊断 data/runtime_graph.json 的副本（绝不写回）。
输出为结构化 JSON（供报告引用）+ 人读摘要。
"""
import io
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(HERE), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)


def norm_key(s):
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return re.sub(r"\s+", "", s)


def analyze(path):
    raw = json.load(open(path, encoding="utf-8"))
    nodes = raw["nodes"] if isinstance(raw.get("nodes"), list) \
        else [dict(v, id=k) for k, v in raw["nodes"].items()]
    edges = raw.get("edges", [])
    ids = [n["id"] for n in nodes]
    idset = set(ids)

    # 1 结构
    adj = defaultdict(set)          # 无向邻接
    outdeg = Counter()
    indeg = Counter()
    dangling = []
    selfloop = 0
    seen_e = set()
    dup_edges = 0
    rel_counter = Counter()
    for e in edges:
        s, d = e.get("src") or e.get("source"), e.get("dst") or e.get("target")
        rel = e.get("relation", "?")
        rel_counter[rel] += 1
        if s not in idset or d not in idset:
            dangling.append((s, d, rel))
            continue
        if s == d:
            selfloop += 1
            continue
        key = (s, d, rel)
        if key in seen_e:
            dup_edges += 1
        seen_e.add(key)
        adj[s].add(d)
        adj[d].add(s)
        outdeg[s] += 1
        indeg[d] += 1
    # 连通分量（BFS）
    comp_of = {}
    cid = 0
    comps = []
    for n in ids:
        if n in comp_of:
            continue
        cid += 1
        stack, size = [n], 0
        comp_of[n] = cid
        while stack:
            x = stack.pop()
            size += 1
            for y in adj.get(x, ()):
                if y not in comp_of:
                    comp_of[y] = cid
                    stack.append(y)
        comps.append(size)
    comps.sort(reverse=True)
    isolated = [n for n in ids if not adj.get(n)]
    terminals = [n for n in ids if outdeg.get(n, 0) == 0 and indeg.get(n, 0) > 0]
    hubs = [(n, outdeg.get(n, 0) + indeg.get(n, 0)) for n in ids]
    hubs.sort(key=lambda x: -x[1])

    # 2 语义
    norm_map = defaultdict(list)
    for i in ids:
        norm_map[norm_key(i)].append(i)
    dup_entities = {k: v for k, v in norm_map.items() if len(v) > 1}

    # 3 领域覆盖（按 label/type 粗分桶）
    by_label = Counter(n.get("label", "?") for n in nodes)
    by_type = Counter(str((n.get("extra_attrs") or {}).get("type"))
                      for n in nodes)
    # 跨空间桥：semantic↔episodic / semantic↔self / episodic↔self
    space = {n["id"]: n.get("graph_space", "?") for n in nodes}
    bridge = Counter()
    for e in edges:
        s, d = e.get("src") or e.get("source"), e.get("dst") or e.get("target")
        a, b = space.get(s, "?"), space.get(d, "?")
        if a != b:
            bridge[tuple(sorted((a, b)))] += 1

    weak = rel_counter.get("关于", 0)
    return {
        "graph_path": path,
        "nodes": len(ids), "edges": len(edges),
        "labels": dict(by_label), "types_top": dict(by_type.most_common(12)),
        "relations_top": dict(rel_counter.most_common(15)),
        "generic_about_share": round(weak / max(1, len(edges)), 3),
        "components": {"total": cid, "largest": comps[0],
                       "largest_share": round(comps[0] / max(1, len(ids)), 3),
                       "sizes": (comps or [0])[:8]},
        "isolated": len(isolated),
        "isolated_sample": isolated[:12],
        "terminals_only_in": len(terminals),
        "dangling_edges": len(dangling),
        "dangling_sample": dangling[:6],
        "selfloops": selfloop,
        "dup_edges": dup_edges,
        "dup_entities": dup_entities,
        "top_hubs": hubs[:12],
        "cross_space_bridges": {f"{a}->{b}": c for (a, b), c in bridge.items()},
        "avg_degree": round(2 * (len(edges) - len(dangling)) / max(1, len(ids)), 2),
    }


def consumption_check(path, seeds=None):
    """消费维度：真引擎多跳扩散的可达性/枢纽吸收采样。"""
    from graph_model import KnowledgeGraph
    from diffusion_engine import DiffusionEngine
    from config import DEFAULT_CONFIG
    kg = KnowledgeGraph.load(path)
    eng = DiffusionEngine(kg, dict(DEFAULT_CONFIG))
    deg = Counter()
    for e in kg.edges:
        deg[e.src] += 1
        deg[e.dst] += 1
    if not seeds:
        sem = [n.id for n in kg.nodes.values()
               if (n.extra_attrs or {}).get("type") in ("mc_species", "prior_concept")]
        seeds = sem[:4]
    out = []
    for sid in seeds:
        if sid not in kg.nodes:
            continue
        for n in kg.nodes.values():
            n.activation = 0.0
        eng.activate_from_inputs([sid], [])
        reached_before = {i for i, n in kg.nodes.items() if n.activation > 1e-6}
        for _ in range(4):
            eng.diffuse_step()
        got = [(i, round(n.activation, 3)) for i, n in kg.nodes.items()
               if n.activation > 1e-6]
        got.sort(key=lambda x: -x[1])
        top_absorber = got[0][0] if got else None
        out.append({"seed": sid, "active_after4": len(got),
                    "top5": got[:5],
                    "absorbed_by_hub": top_absorber,
                    "hub_degree": deg.get(top_absorber, 0)})
        for n in kg.nodes.values():
            n.activation = 0.0
        kg.save = lambda *a, **k: None
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "data", "runtime_graph.json")
    report = analyze(src)
    print("== 结构/语义基线 ==")
    for k in ("nodes", "edges", "avg_degree", "isolated", "terminals_only_in",
              "dangling_edges", "selfloops", "dup_edges",
              "generic_about_share"):
        print(f"  {k}: {report[k]}")
    print("  components:", report["components"])
    print("  top_hubs:", report["top_hubs"][:8])
    print("  cross_space_bridges:", report["cross_space_bridges"])
    print("  dup_entities:", json.dumps(report["dup_entities"],
                                        ensure_ascii=False)[:300])
    print("  dangling_sample:", report["dangling_sample"])
    print("== 消费（4 跳扩散抽样）==")
    for row in consumption_check(src):
        print("  ", json.dumps(row, ensure_ascii=False)[:220])
    json.dump(report, open(os.path.join(HERE, "data", "graph_doctor_baseline.json"),
                           "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved → data/graph_doctor_baseline.json")
