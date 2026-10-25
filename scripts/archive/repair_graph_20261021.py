# -*- coding: utf-8 -*-
"""存量抽取修复 + 知识扩展（任务书 2026-10-21 第 2 条，一次性）。

A. 修复坏抽取：自环边删除（2026-10-21 普查 7 条）；尾缀垃圾节点改名并
   迁移全部边；"名字叫"方向错误（UP主 名字叫 歌名）改为"产生"。
B. 连通性扩展：只连可核常识，全部边与新类目节点诚实标
   source/extraction=knowledge_prior_2026-10-21, trust=inference,
   verified=false——证据闸不会把先验当外部事实。不联网。

用法：python scripts/repair_graph_20261021.py [--dry]
"""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:5000"
ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "data" / "runtime_graph.json"
S = "knowledge_prior_2026-10-21"
import urllib.parse


def call(path, body, method="POST"):
    req = urllib.request.Request(
        BASE + path,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def post(p, b):
    return call(p, b, "POST")


def put(p, b):
    return call(p, b, "PUT")


def dele(p, b=None):
    return call(p, b, "DELETE")


def tag_edge(src, dst, rel, source=S):
    put("/api/edges", {"src": src, "dst": dst, "relation": rel,
                       "extra_attrs": {"source": source,
                                       "extraction": "inference",
                                       "verified": False}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    d = json.load(open(GRAPH, encoding="utf-8"))
    N = d["nodes"]
    nodes = list(N.values()) if isinstance(N, dict) else N
    byid = {str(x.get("id")): x for x in nodes}
    E = d["edges"]
    edges = list(E.values()) if isinstance(E, dict) else E

    # ── A1 自环 ────────────────────────────────────────────
    loops = [(e["src"], str(e.get("relation"))) for e in edges
             if e.get("src") == e.get("dst")]
    print(f"A1 自环边 {len(loops)} 条")
    for src, rel in loops:
        print("   -", src[:40], rel)
        if not args.dry:
            dele("/api/edges", {"src": src, "dst": src, "relation": rel})

    # ── A2 垃圾尾缀改名 ────────────────────────────────────
    junk = [i for i in byid if str(i).endswith(" -") or str(i).endswith("—")]
    print(f"A2 尾缀垃圾节点: {junk}")
    for old in junk:
        new = old.rstrip(" -—")
        if not new or new in byid:
            continue
        if args.dry:
            continue
        n = byid[old]
        post("/api/nodes", {"id": new,
                            "weight": float(n.get("weight") or 0.5),
                            "label": n.get("label", "declarative-semantic"),
                            "graph_space": n.get("graph_space", "semantic"),
                            "created": n.get("created"),
                            "extra_attrs": dict(n.get("extra_attrs") or {})})
        for e in edges:
            if e.get("src") == old:
                post("/api/edges", {"src": new, "dst": e["dst"],
                                    "relation": e.get("relation"),
                                    "weight": float(e.get("weight") or 0.5)})
            if e.get("dst") == old:
                post("/api/edges", {"src": e["src"], "dst": new,
                                    "relation": e.get("relation"),
                                    "weight": float(e.get("weight") or 0.5)})
        dele("/api/nodes/" + urllib.parse.quote(old, safe=""))

    # ── A3 名字叫方向修正 ─────────────────────────────────
    fixes = [e for e in edges if str(e.get("relation")) == "名字叫"
             and e.get("src") == "祁言不吃香菜"]
    print(f"A3 名字叫方向修正 {len(fixes)} 条（改为 产生）")
    for e in fixes:
        if args.dry:
            continue
        dele("/api/edges", {"src": e["src"], "dst": e["dst"],
                            "relation": "名字叫"})
        post("/api/edges", {"src": e["src"], "dst": e["dst"],
                            "relation": "产生", "weight": 0.5})
        tag_edge(e["src"], e["dst"], "产生", source="repair_2026-10-21")

    # ── B 知识扩展（含原子化补概念：MicroG/张作霖只在活动文本里出现过，
    #    概念节点缺失——按刷到记录建原子概念并挂类目，全标 inference）──
    ENRICH = [
        # (主体, 是否新建概念主体, 类目, 关系)
        ("MicroG", True, "开源软件", "实例属于"),
        ("MicroG", True, "谷歌服务框架", "相关"),
        ("张作霖", True, "北洋军阀", "实例属于"),
        ("eMudhra Intermediate CA", False, "证书颁发机构", "实例属于"),
        ("私钥", False, "数字证书", "相关"),
        ("超强台风蔷琵", False, "台风", "实例属于"),
        ("祁言不吃香菜", False, "B站UP主", "实例属于"),
        ("狼蛛昆仑 L5", False, "游戏外设", "实例属于"),
        ("电磁微动鼠标", False, "游戏外设", "实例属于"),
        ("Withings", False, "健康设备品牌", "实例属于"),
    ]
    made_nodes = 0
    made_edges = 0
    live_ids = {str(x.get("id")) for x in nodes}

    def _mk_concept(cid, note):
        nonlocal made_nodes
        if cid in live_ids or args.dry:
            return
        st = post("/api/nodes", {"id": cid, "weight": 0.5,
                                 "label": "declarative-semantic",
                                 "graph_space": "semantic",
                                 "extra_attrs": {"type": "概念",
                                                 "source": S,
                                                 "trust": "inference",
                                                 "verified": False,
                                                 "note": note}})
        if st == 200:
            live_ids.add(cid)
            made_nodes += 1

    for subj, mk, cls, rel in ENRICH:
        if mk:
            _mk_concept(subj, "抽取时只落了活动文本，概念未原子化；"
                              "按刷到记录补建")
        _mk_concept(cls, "知识扩展类目节点（模型先验，未经她方证据核实）")
        if subj not in live_ids:
            print("  跳过（主体不存在）:", subj)
            continue
        if args.dry:
            made_edges += 1
            continue
        post("/api/edges", {"src": subj, "dst": cls, "relation": rel,
                            "weight": 0.5})
        tag_edge(subj, cls, rel)
        made_edges += 1
    # MicroG/张作霖 的刷到出处（活动体验 —涉及→ 概念，给新概念接上经历根）
    if not args.dry:
        for act_id, concept in (
                ("Activity_activity_browse_novel_在社区逛到个没见过的东西Micr_1792511370347", "MicroG"),
                ("Activity_activity_browse_novel_抽象历史人物志张作霖_1792548854606", "张作霖")):
            if act_id in live_ids and concept in live_ids:
                post("/api/edges", {"src": act_id, "dst": concept,
                                    "relation": "涉及", "weight": 0.45})
                made_edges += 1
    print(f"B 知识扩展：新节点 {made_nodes}，推理边 {made_edges}"
          f"{'（DRY 计划）' if args.dry else ''}")


if __name__ == "__main__":
    main()
