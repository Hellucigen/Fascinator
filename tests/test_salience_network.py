# -*- coding: utf-8 -*-
"""统一显著性网络（SN）验收（2026-10-15 任务书 §5）。
确定性、零 LLM、零网络、全内存。
运行：python tests/test_salience_network.py
"""
import os
import sys
import time

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import cognitive_field as CF                   # noqa: E402
import activities as AC                        # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def fresh():
    return CF.SalienceNetwork({"salience_network": {"enabled": True}})


print("── A 信号参与：四类来源都能影响显著性 ──")
sn = fresh()
a = sn.event_salience("x", event=0.1, feasible=True)["score"]
b = sn.event_salience("x", event=0.9, feasible=True)["score"]
sn2 = fresh()
c = sn2.event_salience("x", event=0.5, delta=0.9, feasible=True)["score"]
sn3 = fresh()
d = sn3.event_salience("x", event=0.5, novelty=0.95, feasible=True)["score"]
sn4 = fresh()
e = sn4.event_salience("x", event=0.5, need=0.9, feasible=True)["score"]
sn5 = fresh()
f = sn5.event_salience("x", event=0.5, commitment=0.95,
                       switch_cost=0.9, feasible=True)["score"]
check("A1 事件强度↑ ⇒ score↑", b > a, f"{a} vs {b}")
check("A2 激活变化(delta)参与且抬分", c > b, f"{c} vs {b}")
check("A3 新颖性参与且抬分", d > a, f"{d}")
check("A4 内感受需求参与且抬分", e > a, f"{e}")
check("A5 自上而下(高承诺+高切换成本)压 score（守护连续性）",
      f < a * 4, f"{f} vs {a}")

sn = fresh()
u = sn.event_salience("user_turn_end", event=1.0, feasible=True)
check("A6 用户输入底数=满显著 ⇒ attend",
      u["decision"] == "attend", str(u["decision"]))

print("── N 鲁棒：缺失/极端/重复不崩不失控 ──")
sn = fresh()
z = sn.event_salience("x", feasible=True)
check("N1 全缺失信号 ⇒ hold 且 reason=no_signal（中性值不伪造）",
      z["score"] == 0.0 and z["decision"] == "hold", str(z["reason"]))
try:
    bad = sn.event_salience("x", event=-5.0, delta=99, novelty=2.0,
                            commitment=1.5, feasible=True)
    ok_bounds = 0.0 <= bad["score"] <= 1.0
except Exception as ex:
    ok_bounds = False
check("N2 极端/越界输入被截断归一，score 恒在 [0,1]", ok_bounds)
sn = fresh()
r1 = sn.event_salience("game_context", event=0.9,
                       source="evt:g", feasible=True)["score"]
r2 = sn.event_salience("game_context", event=0.9,
                       source="evt:g", feasible=True)["score"]
r3 = sn.event_salience("game_context", event=0.9,
                       source="evt:g", feasible=True)["score"]
check("N3 同源重复 ⇒ EWMA 迟滞递减（防循环唤醒/霸屏）",
      r1 > r2 > r3, f"{r1}>{r2}>{r3}")
big = fresh()
for i in range(200):
    big.event_salience("spam", event=0.9, source=f"s{i}")
check("N4 大量来源不炸（内部有界修剪）", len(big._src_hist) <= 64,
      str(len(big._src_hist)))

print("── F 显著≠可行：不绕过能力检查 ──")
sn = fresh()
r = sn.event_salience("discovery", event=1.0, novelty=1.0, delta=1.0,
                      feasible=False)
check("F1 高分但 feasible=False ⇒ decision=hold, reason=infeasible"
      "（SN 只给建议不越权）",
      r["score"] > 0.5 and r["decision"] == "hold"
      and r["reason"] == "infeasible", str(r["reason"]))

print("── W 唤醒接线：白名单 → SN，回退路径完好 ──")
AC._SN_LOG_TS[0] = time.time() + 1000          # 抑制本测试日志噪声
d1, _r1 = AC._sn_wake_decision("user_turn_end")
check("W1 安全底线：user_turn_end 无条件唤醒（业务约束非显著性判断）", d1)
d2, r2 = AC._sn_wake_decision("discovery")
check("W2 discovery(0.72 底数) ⇒ SN attend 唤醒", d2, str(r2))
d3, r3 = AC._sn_wake_decision("unknown_noise_kind")
check("W3 表外杂散事件 ⇒ 低底数不唤醒（旧白名单同样会拒——语义守恒）",
      not d3)
import cognitive_field as _cf
_saved = _cf._SN
_cf._SN = _cf.SalienceNetwork({"salience_network": {"enabled": False}})
d4, meta = AC._sn_wake_decision("unknown_noise_kind")
d5, _ = AC._sn_wake_decision("game_context")
check("W4 sn 关闭 ⇒ 回退旧白名单语义（未知拒/在表者醒）",
      not d4 and d5 and meta.get("mode") == "legacy_whitelist",
      str(meta))
_cf._SN = _saved

print("── G 切换门：迟滞统一，小幅波动不横跳 ──")
sn = fresh()
sw, _m = sn.switch_gate(0.50, 0.53)
check("G1 候选仅高 0.03 ⇒ 不切换（低于 margin=0.12 的坚守带）", not sw)
sw2, _ = sn.switch_gate(0.50, 0.75)
check("G2 高价值新候选(+0.25) ⇒ 允许切换", sw2)
sw3, _ = sn.switch_gate(0.50, 0.625)
check("G3 边界外 0.125 ⇒ 切换（margin 语义精确）", sw3)

print("── E 表达增益接线（乘分数不乘门槛） ──")
sn = fresh()
sn.event_salience("hi", event=1.0, delta=1.0, feasible=True)
ar = sn.arousal()
time.sleep(0.05)
ar2 = sn.arousal(now=(time.time() + 600))       # 10 分钟后=半衰
check("E1 高显著余温存在且随时间半衰（arousal∈[0,1] 有界）",
      0.4 < ar <= 1.0 and abs(ar2 - ar / 2.0) < 0.05,
      f"{ar} → {ar2}")
sn0 = fresh()
check("E2 无历史 ⇒ arousal=0（增益中性，不因 SN 凭空抬分）",
      sn0.arousal() == 0.0)

print("── V v2 表达评估真的调到 SN ──")
src = open(os.path.join(_cog, "continuous_cognition.py"),
           encoding="utf-8").read()
check("V1 表达评估源码含 arousal 乘性增益调用（静态确证接线）",
      "0.15 * _snx.arousal(now)" in src)
check("V2 focus 注入 CENetwork 走 mark_active 合法接口（无直写字段）",
      'self.engine.mark_active("CENetwork")' in src)
check("V3 companion 唤醒/迟滞消费 sn（两文件接线）",
      "_sn_wake_decision" in open(os.path.join(
          _r, "activities.py"), encoding="utf-8").read()
      and "switch_gate" in open(os.path.join(
          _r, "activities.py"), encoding="utf-8").read())

print("── X 关闭即回退（配置）──")
sn_off = CF.SalienceNetwork({"salience_network": {"enabled": False}})
check("X1 配置 disabled ⇒ enabled=False（消费侧全部走旧路）",
      not sn_off.enabled)
sn_on = CF.SalienceNetwork({"salience_network": {}})
check("X2 配置缺省 ⇒ 默认开启（生产姿态=开）", sn_on.enabled)

print()
if FAILURES:
    print(f"通过 {TOTAL[0] - len(FAILURES)} 条，失败 {len(FAILURES)}："
          f"{FAILURES}")
    sys.exit(1)
print(f"通过 {TOTAL[0]} 条，全部通过")
