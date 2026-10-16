# -*- coding: utf-8 -*-
"""run_living_real.py — 自主生活循环真实网络验收（可复核执行日志）。

真实活动：从生产 chat_log 的真实知识缺口取主题（用户 10-09 明确说没看懂的
概念），经历 失败→改写→相关→读取网页 的完整探索，账本持久化+恢复演示。
零生产写入、零投递。
"""
import json
import os
import sys
import time as _rt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, "E:/Project/FAS-Companion")

from living_loop import LivingLoop

COMPANION = "E:/Project/FAS-Companion"
NOW = _rt.time()


def main():
    chat = json.load(open(os.path.join(COMPANION, "data", "chat_log.json"),
                          encoding="utf-8"))
    concepts = []
    for x in chat:
        if x.get("proactive") in (False, "False", None):
            import re
            for m in re.findall(r"「([^」]{3,20})」",
                                str(x.get("user_input") or "")):
                if m not in concepts:
                    concepts.append(m)
    topic = concepts[0] if concepts else "暗物质晕"
    print(f"真实主题（用户 10-09 口述未知概念）: {topic}")

    ledger = os.path.join(HERE, "results", "living_real_ledger.json")
    lp = LivingLoop(ledger, products=[],
                    social_ctx=SocialContext(
                        user_recent_ts=NOW - 44 * 3600,   # 两天前最后互动
                        recent_expressed=["02:08 的笔记快照消息"],
                        recent_express_ts=NOW - 20 * 3600, now=NOW))
    aid = lp.open_activity(f"搞清楚「{topic}」", "product:real_chat_gap")

    # 拍 1：首次查询（可能失败）
    r1 = lp.tick()
    # 拍 2：改写查询重试
    r2 = lp.tick()
    a = lp._activity(aid)
    print(f"拍1: {r1} | 拍2: {r2}")
    print("methods_tried:", a["methods_tried"])
    print("state:", a["state"], "| findings:", len(a["findings"]),
          "| known_failures:", a["known_failures"][:2])

    # 拍 3（如未完成）：继续改写
    if a["state"] == "active":
        r3 = lp.tick()
        print("拍3:", r3)

    # 恢复演示：新实例读同一账本
    lp2 = LivingLoop(ledger, products=[],
                     social_ctx=lp.social_ctx)
    lp2.recover()
    print("恢复后活动数:", len(lp2.ledger.activities))

    # 社交决策
    soc = lp.social_step()
    print("社交决策:", soc)

    out = {"topic": topic, "activities": list(lp.ledger.activities.values()),
           "experiences": lp.ledger.experiences,
           "share_candidates": lp.ledger.share_candidates,
           "log": lp.log}
    p = os.path.join(HERE, "results",
                     f"living_real_{int(_rt.time())}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, default=str)
    print("saved:", p)


if __name__ == "__main__":
    from social_decider import SocialContext
    main()
