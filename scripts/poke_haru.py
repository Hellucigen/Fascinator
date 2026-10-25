# -*- coding: utf-8 -*-
"""调试用一键开口：泵社交燃料，让 Haru 在最短时间内自己主动说一句话。

背景：调试重启后要等她自然攒够社交意愿才开口，一等半天。本脚本只做两件事：
① 把她的社交燃料泵上去——SocialDrive + 用户 + 用户最近的几条真实经历节点，
   全走她自己的 /api/activate 能量通道（等价于"你刚跟她说过话"的余温，
   不改阈值、不伪造回复、不碰表达决策）；
② 盯日志等 [CC] 主动表达 出现，打印原话。

为什么光泵 SocialDrive 不够（2026-10-20 实测）：意图 kind 亲和度是信号加权表，
communication 的权重里 drive.social 只占 0.35，单泵驱动 comm≈0.30 仍输给
exploration≈0.40——必须把"社交相关性/用户相关"两路信号也点起来。

用法：  python scripts/poke_haru.py [--wait 240]
退出码：0=开口（打印原话）；2=她选择不说（打印原因）；3=超时；4=连不上 FAS。
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:5000"
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "haru_stderr.log"
GRAPH = ROOT / "data" / "runtime_graph.json"
PAT = re.compile(r"主动表达|降级为不表达")


def post_activate(nodes):
    req = urllib.request.Request(
        BASE + "/api/activate",
        data=json.dumps({"nodes": nodes}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        json.loads(r.read().decode("utf-8"))


def recent_shareable_ids(k=3):
    """最新的"可分享具体经历"：Activity_ 活动体验本身 + 它"涉及"边指向的
    内容节点（实测只泵活动壳时 LLM 判 NO_SPEAK——话题在内容那头，
    2026-10-20：泵 DeepInfer 所在的 browse 体验要连 DeepInfer 一起泵）。
    排除 剧情_/用户表达_——那些是她自己/用户说过的话，进 basis 必触发回声弃权。"""
    d = json.load(open(GRAPH, encoding="utf-8"))
    nodes = d["nodes"]
    nodes = list(nodes.values()) if isinstance(nodes, dict) else nodes
    edges = d["edges"]
    edges = list(edges.values()) if isinstance(edges, dict) else edges
    pref = ("Activity_", "用户近况_")
    cand = [x for x in nodes if str(x["id"]).startswith(pref)
            and not str(x["id"]).startswith(("Activity_self_read",
                                             "Activity_activity_review"))
            and str(x.get("created") or "")]
    cand.sort(key=lambda x: str(x["created"]), reverse=True)
    out = []
    for x in cand:
        if len(out) >= k:
            break
        out.append(x["id"])
        eps = [e for e in edges if e.get("src") == x["id"]
               and (e.get("relation") or "") in ("涉及", "关于", "包含")
               and e.get("dst") and str(e["dst"]) not in out
               and not str(e["dst"]).startswith(("剧情_", "用户", "Activity_"))]
        eps.sort(key=lambda e: -float(e.get("weight") or 0))
        out += [e["dst"] for e in eps[:2]]   # 只带最相关的 2 条内容
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=240)
    ap.add_argument("--reset", action="store_true",
                    help="先全图激活清零——清掉上一口泵残留的碎片段子，"
                         "让 basis 只剩本次燃料（调试专用，等于按了暂停再开拍）")
    args = ap.parse_args()

    fuel = ["SocialDrive", "用户"] + recent_shareable_ids(3)
    try:
        if args.reset:
            post_activate([])
        for _ in range(3):             # 每次 +1.0 激活，泵三口（衰减快，2口实测欠火）
            post_activate(fuel)
            time.sleep(0.4)
    except Exception as e:
        print(f"连不上 FAS（{e}）——确认 :5000 活着再跑")
        sys.exit(4)
    print(f"泵社交燃料: {fuel}")
    print(f"等她自己开口（≤{args.wait}s）…")

    off = LOG.stat().st_size if LOG.exists() else 0
    t0 = time.time()
    declines = []      # 沉默/弃权记录：别的 CI 的失败不该终止观察，攒着报告
    last_refuel = time.time()
    while time.time() - t0 < args.wait:
        time.sleep(3)
        # 持续补泵（2026-10-24 实测：一次泵入的燃料 ×0.9/拍衰减，2 分钟
        # 内亲和度 0.67→0.32，焦点分攒不到形成线就凉了）——每 30s 补一口
        if time.time() - last_refuel >= 30:
            last_refuel = time.time()
            try:
                post_activate(fuel)
            except Exception:
                pass
        time.sleep(3)
        if not LOG.exists():
            continue
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(off)
            new = f.read()
            off = f.tell()
        for line in new.splitlines():
            if PAT.search(line):
                tail = f"{time.time() - t0:.0f}s"
                if "沉默" in line or "降级" in line or "弃权" in line:
                    declines.append(f"[{tail}] {line.strip()}")
                    continue
                print(f"[{tail}] 开口了：{line.strip()}")
                for d in declines:
                    print("  此前弃说：" + d)
                sys.exit(0)
    print(f"等了 {args.wait}s 没有开口。弃说记录：")
    for d in declines or ["(无——连评估都没到，看 意图形成 kind/亲和度 日志)"]:
        print("  " + d)
    sys.exit(2 if declines else 3)


if __name__ == "__main__":
    main()
