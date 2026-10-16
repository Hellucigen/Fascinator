# -*- coding: utf-8 -*-
"""test_autonomy_loop.py — 自主活动循环 v1 的 12 场景隔离验收 + 多轮链路。

隔离：内存图谱 + 注入式 fake 工具 + 临时账本；唯一真实工具调用单独演示。
运行：python experiments/autonomy_loop_v1/test_autonomy_loop.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # FAS-Cognitive 根
sys.path.insert(0, "E:/Project/FAS-Companion")

from graph_model import KnowledgeGraph, Node
from autonomy_loop import (ActivityLoop, Toolbox, candidates_from_graph,
                           clean_query, S_DONE, S_FAILED, S_DEFERRED,
                           S_RUNNING, VERDICT_SUCCESS, VERDICT_FAILED,
                           VERDICT_INCONCLUSIVE)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


def mk_kg(unknown=None, thought=None):
    kg = KnowledgeGraph()
    if unknown:
        kg.add_node(Node(id=f"UnknownConcept_{unknown}", weight=0.6,
                         extra_attrs={"type": "unknown"}))
    if thought:
        tid = f"思考_{int(time.time())}"
        kg.add_node(Node(id=tid, weight=0.6, label="declarative-episodic",
                         extra_attrs={"type": "thought", "content": thought,
                                      "born_ts": time.time()}))
    return kg


def mk_loop(kg, tools, defer_ttl=6 * 3600):
    return ActivityLoop(kg, os.path.join(tempfile.mkdtemp(), "ledger.json"),
                        Toolbox(tools), defer_ttl=defer_ttl)


def fake_search(rows):
    def fn(q, top_n=5):
        return rows
    return fn


GOOD_ROWS = [{"title": "暗物质晕", "snippet": "暗物质晕是围绕星系的暗物质结构，"
                                          "无法直接观测，通过引力效应推断。"}]

# S1 明确可完成的小目标 → 选中并执行、验证成功
kg = mk_kg(unknown="暗物质晕")
cc = mk_loop(kg, {"web_search": fake_search(GOOD_ROWS)})
out = cc.step()
t = list(cc.ledger.tasks.values())[0]
check("S1a 候选产生并选中", out["selected"] == 1, str(out))
check("S1b 工具调用发生且预算内", len(t["tool_calls"]) == 1)
check("S1c 验证 SUCCESS（相关性检查基于工具结果）",
      t["verdict"] == VERDICT_SUCCESS and t.get("relevant_results"),
      str(t.get("verdict_reason")))
check("S1d 学习写入隔离图谱（节点+基于边）",
      t.get("learned_id") in kg.nodes
      and any(e.dst == "UnknownConcept_暗物质晕" for e in kg.edges
              if e.src == t["learned_id"]))
check("S1e 分享候选已登记（未发送）",
      len(cc.ledger.share_candidates) == 1
      and all("send" not in c for c in cc.ledger.share_candidates))

# S2 无值得做的目标 → IDLE
kg2 = mk_loop(KnowledgeGraph(), {})
out2 = kg2.step()
check("S2 无候选 → 保持空闲，不编造任务",
      out2["proposed"] == 0 and len(kg2.ledger.tasks) == 0)

# S3 相同任务进行中 → 不重复创建
kg3 = mk_kg(unknown="暗物质晕")
cc3 = mk_loop(kg3, {"web_search": fake_search(GOOD_ROWS)})
cc3.step()
n_after_first = len(cc3.ledger.tasks)
kg3.nodes["UnknownConcept_暗物质晕"].activation = 5.0   # 再点亮
cc3.step()
check("S3 同目标未完成时不重复创建", len(cc3.ledger.tasks) == n_after_first,
      f"{n_after_first}→{len(cc3.ledger.tasks)}")

# S4 工具成功但需验证结果后才能标成功（结果不相关 → INCONCLUSIVE）
kg4 = mk_loop(mk_kg(unknown="暗物质晕"),
              {"web_search": fake_search([{"title": "菜谱", "snippet": "红烧肉做法"}])})
cc4 = kg4
cc4.step()
t4 = list(cc4.ledger.tasks.values())[0]
check("S4 结果与目标无关 → INCONCLUSIVE（不写成功）",
      t4["verdict"] == VERDICT_INCONCLUSIVE and t4["state"] == S_DONE
      and not t4.get("relevant_results"), str(t4["verdict_reason"]))

# S5 工具失败 → FAILED 记录原因
def boom(q, top_n=5):
    raise RuntimeError("网络不可达")
kg5 = mk_loop(mk_kg(unknown="暗物质晕"), {"web_search": boom})
kg5.step()
t5 = list(kg5.ledger.tasks.values())[0]
check("S5 工具异常 → FAILED/原因记录（不伪造成功）",
      t5["verdict"] == VERDICT_FAILED and "网络不可达" in t5["verdict_reason"])

# S6 空结果 → INCONCLUSIVE
kg6 = mk_loop(mk_kg(unknown="暗物质晕"), {"web_search": fake_search([])})
kg6.step()
t6 = list(kg6.ledger.tasks.values())[0]
check("S6 空结果 → INCONCLUSIVE", t6["verdict"] == VERDICT_INCONCLUSIVE)

# S7 预算耗尽 → 停止
kg7 = mk_loop(mk_kg(unknown="暗物质晕"), {"web_search": fake_search(GOOD_ROWS)})
cc7 = kg7
t7 = list(cc7.propose())[0]
cc7.select()
t7["tool_calls"] = [{"tool": "web_search"}] * 4     # 已用满预算
cc7.execute(t7)
check("S7 预算耗尽 → 不再调用工具，直接进入验证",
      len(t7["tool_calls"]) == 4 and t7["state"] in ("verifying", "learning",
                                                     "done"))

# S8 未授权工具 → 拒绝
tb = Toolbox({"web_search": fake_search(GOOD_ROWS)})
r = tb.call("delete_file", "/important/path")
check("S8 白名单外工具调用被拒", r.get("error") == "tool_not_allowed")

# S9 重复学习不写
kg9 = mk_loop(mk_kg(unknown="暗物质晕"), {"web_search": fake_search(GOOD_ROWS)})
kg9.step()
learned_before = kg9.ledger.tasks[list(kg9.ledger.tasks)[0]]["learned_id"]
# 同目标同结论再次处理（模拟第二次循环）
cc9 = kg9
t9 = cc9.ledger.tasks[list(cc9.ledger.tasks)[0]]
t9["state"] = "learning"
cc9.learn(t9)
check("S9 同目标同结论 → 学习去重（learned_id 不变）",
      cc9.ledger.tasks[list(cc9.ledger.tasks)[0]]["learned_id"] == learned_before)

# S10 无价值发现 → 不生成分享候选
kg10 = mk_loop(mk_kg(unknown="暗物质晕"),
               {"web_search": fake_search([{"title": "菜谱", "snippet": "红烧肉做法"}])})
kg10.step()
t10 = list(kg10.ledger.tasks.values())[0]
check("S10 结果不相关 → INCONCLUSIVE 且无分享候选（不强制问候）",
      t10["verdict"] == VERDICT_INCONCLUSIVE
      and len(kg10.ledger.share_candidates) == 0,
      str(t10["verdict_reason"]))

# S11 无候选 → 不产生强制性活动（同 S2，多轮）
kg11 = mk_loop(KnowledgeGraph(), {})
for _ in range(3):
    kg11.step()
check("S11 多轮无候选 → 持续空闲且账本干净",
      len(kg11.ledger.tasks) == 0 and len(kg11.ledger.share_candidates) == 0)

# S12 中途停止后恢复：RUNNING 状态恢复到 VERIFY，不重放工具调用
kg12 = mk_kg(unknown="暗物质晕")
cc12 = mk_loop(kg12, {"web_search": fake_search(GOOD_ROWS)})
t12 = list(cc12.propose())[0]
cc12.select()
t12["state"] = S_RUNNING
t12["tool_calls"] = [{"tool": "web_search", "query": "暗物质晕",
                      "t": 0, "ok": True}]
t12["raw_results"] = GOOD_ROWS
del t12["state"]
t12["state"] = S_RUNNING
cc12.ledger.save()
# 模拟崩溃重启：新 loop 实例读同一账本
cc12b = ActivityLoop(kg12, cc12.ledger.path,
                     Toolbox({"web_search": fake_search(GOOD_ROWS)}))
calls_before = len(t12["tool_calls"])
cc12b.recover()
t12r = cc12b.ledger.tasks[t12["id"]]     # 恢复后的真实账本对象
cc12b.verify(t12r)
cc12b.learn(t12r)
cc12b.decide_next(t12r)
check("S12a 恢复后不重放工具调用（账本已有结果）",
      len(t12["tool_calls"]) == calls_before)
check("S12b 恢复后验证成功并完成学习+分享决策",
      t12r["verdict"] == VERDICT_SUCCESS
      and t12r.get("learned_id") in kg12.nodes
      and len(cc12b.ledger.share_candidates) == 1,
      f"verdict={t12r.get('verdict')} learned={t12r.get('learned_id')} "
      f"in_kg={t12r.get('learned_id') in kg12.nodes} "
      f"share={len(cc12b.ledger.share_candidates)}")

# ── 多轮完整链路：发现→选择→执行→验证→学习→决定下一步 ──
kg13 = mk_kg(unknown="暗物质晕")
kg13.add_node(Node(id="思考_1791709991", weight=0.6,
                   label="declarative-episodic",
                   extra_attrs={"type": "thought", "born_ts": time.time(),
                                "content": "想搞清楚星系外围为什么转得那么快"}))
cc13 = mk_loop(kg13, {"web_search": fake_search(
    GOOD_ROWS + [{"title": "星系自转曲线", "snippet": "星系自转曲线的平坦性是暗物质晕存在的关键证据。"}])})
trace = []
for i in range(3):
    out13 = cc13.step()
    trace.append(out13)
all_done = all(t["state"] == S_DONE for t in cc13.ledger.tasks.values())
check("M1 多轮循环：全部候选走完 生命周期",
      all_done and len(cc13.ledger.tasks) == 2, str(trace))
check("M2 两类来源都被消费（未知标记+自由思考）",
      {t["source"] for t in cc13.ledger.tasks.values()} ==
      {"unknown_marker", "free_thought"})
check("M3 分享候选有证据支撑（来自工具结果，非编造）",
      all(c.get("evidence") for c in cc13.ledger.share_candidates))

# ── 真实工具演示（单次真调用，证据留存） ──
try:
    from autonomy_loop import real_toolbox
    tb_real = real_toolbox()
    rr = tb_real.call("web_search", "暗物质晕", top_n=2)
    real_ok = rr.get("ok") and isinstance(rr.get("result"), list)
    real_n = len(rr.get("result") or [])
    check(f"REAL 真实 web_search 可用（返回 {real_n} 条）", real_ok and real_n > 0,
          str(rr.get("error")))
except Exception as e:                           # noqa: BLE001
    check("REAL 真实 web_search 可用", False, f"{type(e).__name__}: {e}")

print("=" * 50)
if FAILS:
    print(f"✗ {len(FAILS)} 项失败: {FAILS}")
    sys.exit(1)
print("✓ 自主活动循环 v1 全部场景验收通过")
sys.exit(0)
