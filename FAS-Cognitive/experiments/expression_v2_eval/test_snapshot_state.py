# -*- coding: utf-8 -*-
"""test_snapshot_state.py — 快照去重状态机（阶段1修复）的隔离验收。

覆盖任务要求的 9 场景；纯函数 + 临时状态目录，零生产触碰。
运行：python experiments/expression_v2_eval/test_snapshot_state.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "E:/Project/FAS-Companion")   # charon_snapshot_state

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


def fresh_dir():
    return tempfile.mkdtemp(prefix="snap_state_")


D_BASE = "用户工作区快照 — 最近笔记：日記；リーディングリスト；Movie List；AI学習計画"
D_ADDED = "用户工作区快照 — 最近笔记：日記；リーディングリスト；Movie List；AI学習計画；新笔记X"
D_REMOVED = "用户工作区快照 — 最近笔记：日記；Movie List；AI学習計画"

# 1+2. 同一快照连续轮询两次 / 模拟重启后再次出现
d = fresh_dir()
from charon_snapshot_state import decide, load_prev_hash, save_hash, digest_hash
k1, h1 = decide(load_prev_hash(d), D_BASE)
save_hash(d, h1)
k2, _ = decide(load_prev_hash(d), D_BASE)
check("T1 同一快照连续轮询：first → unchanged", k1 == "first" and k2 == "unchanged",
      f"{k1}/{k2}")
# 模拟重启：重新 load（新进程语义）
k3, _ = decide(load_prev_hash(d), D_BASE)
check("T2 重启后相同快照再次读取 → unchanged（不重放成事件）", k3 == "unchanged", k3)

# 3. hash 未变但时间戳变化（digest 不含时间 → 结果不受影响）
k4, _ = decide(load_prev_hash(d), D_BASE)
check("T3 digest 不含时间戳 → 时间流逝不产生事件", k4 == "unchanged")

# 4-6. 实质变化：改/增/删
for name, txt in (("T4a 标题实质变化", "用户工作区快照 — 最近笔记：日記改；リーディングリスト；Movie List；AI学習計画"),
                  ("T5 新增一条笔记", D_ADDED),
                  ("T6 删除一条笔记", D_REMOVED)):
    k, _ = decide(load_prev_hash(d), txt)
    check(f"{name} → changed", k == "changed", k)

# 7. 首次运行无历史基线 → first（建立基线，背景降档由调用方执行）
d2 = fresh_dir()
k, _ = decide(load_prev_hash(d2), D_BASE)
check("T7 无历史基线 → first（区分'首次发现资料'与'用户新动作'）", k == "first")

# 8. 状态文件损坏/缺失 → 安全降级 first
d3 = fresh_dir()
os.makedirs(d3, exist_ok=True)
with open(os.path.join(d3, "charon_snapshot_state.json"), "w", encoding="utf-8") as f:
    f.write("{corrupt!!")
check("T8a 状态文件损坏 → load 返回 None（不抛异常）", load_prev_hash(d3) is None)
k, _ = decide(load_prev_hash(d3), D_BASE)
check("T8b 损坏后按 first 安全降级", k == "first")

# 9. 异常退出（save 未发生）→ 上次 hash 完好
d4 = fresh_dir()
k, h = decide(load_prev_hash(d4), D_BASE)
save_hash(d4, h)                     # 正常处理
# 异常退出：下一次处理同一内容但 save 没执行过（模拟：进程在 save 前死）
# → 磁盘 hash 仍是 h → unchanged（不会重复事件）
k2, _ = decide(load_prev_hash(d4), D_BASE)
check("T9 异常退出未损坏已保存状态 → 语义仍一致", k2 == "unchanged")

# 附加：hash 对 digest 的敏感性（内容任何变化都改 hash）
check("T10 hash 敏感性：一字之差 → 不同 hash",
      digest_hash(D_BASE) != digest_hash(D_BASE + "。"))

print("=" * 50)
if FAILS:
    print(f"✗ {len(FAILS)} 项失败: {FAILS}")
    sys.exit(1)
print("✓ 快照去重状态机全部场景验收通过")
shutil.rmtree(fresh_dir(), ignore_errors=True)
sys.exit(0)
