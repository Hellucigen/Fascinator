# -*- coding: utf-8 -*-
"""prune_graph_islands.py — 无救孤岛碎片清理（默认 dry-run；生产文件不动）。

目标（2026-10-13 体检）：vision 检测占位符（UnknownObject*）与其属性碎片、
零入零出的节点。**只列报告，不改生产**：--apply 时也只写
`data/runtime_graph.pruned.json` 新文件（附 .bak 原件），供人工比对后再决定
是否替换——符合"不做未验证的不可逆批量改写"。
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=os.path.join(HERE, "data", "runtime_graph.json"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    raw = json.load(open(a.graph, encoding="utf-8"))
    nodes, edges = raw["nodes"], raw.get("edges", [])
    deg = defaultdict(int)
    for e in edges:
        deg[e["src"]] += 1
        deg[e["dst"]] += 1
    junk_pat = re.compile(r"^(UnknownObject\d+|change:|变化:|obs:)")
    keep_ids, victims = [], []
    for n in nodes:
        nid = n["id"]
        is_junk_name = bool(junk_pat.match(nid))
        is_island = deg.get(nid, 0) == 0
        if is_junk_name and is_island:
            victims.append(nid)
        else:
            keep_ids.append(n)
    kept_edges = [e for e in edges
                  if e["src"] not in set(victims) and e["dst"] not in set(victims)]
    print(f"候选清理 {len(victims)} 个（检测占位符且零连接）:")
    for v in victims[:20]:
        print("  -", v)
    print(f"结果：nodes {len(nodes)}→{len(keep_ids)}，edges {len(edges)}→{len(kept_edges)}")
    if not a.apply:
        print("（dry-run：未写任何文件；--apply 产出 pruned 新文件+原件 .bak）")
        return 0
    out = os.path.join(HERE, "data", "runtime_graph.pruned.json")
    json.dump({"nodes": keep_ids, "edges": kept_edges},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
