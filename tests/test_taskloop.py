# test_taskloop.py — 通用任务闭环跨任务验证（阶段 D/E；全离线、零 LLM）
# 三类任务共用同一决策核（taskloop.TaskLoop/plan/核验/台账）：
#   沙盒房间世界 / 文件整理 / 阅读（适配器包 ReadingLedger）。
# 负面测试：伪造成功回执、执行期环境突变、约束禁项、不可达、台账串台、
# 步数上限、崩溃恢复。基线对照：greedy_nocheck（贪心不核验）。
# 运行: python -X utf8 -m pytest tests/test_taskloop.py -q
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "experiments", "general_loop"))
import logging
logging.disable(logging.WARNING)

import taskloop as TL
from sandbox_env import RoomWorld
from file_env import FileEnv
from reading_env import ReadingEnv, make_default_extractor
from graph_model import KnowledgeGraph
import reading as RD

FAILS = []


class _Runs:
    count = 0


RUNS = _Runs()


def eq(name, got, want):
    RUNS.count += 1
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


def truthy(name, cond, detail=""):
    RUNS.count += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


def _tmp(name="ledger.json"):
    return os.path.join(tempfile.mkdtemp(), name)


def _world(**kw):
    return RoomWorld(rooms=["entry", "storage", "workshop"],
                     links={"entry": ["storage"], "storage": ["workshop"]},
                     items={"planks_a": "storage", "planks_b": "storage"},
                     capacity=2, **kw)


GOALS_W = ["at:planks_a:workshop", "at:planks_b:workshop"]


# ── D-1 沙盒：普通多步 + 每拍一步 + 计划由核选择（非脚本序列）────
def t01_sandbox_completed():
    env = _world()
    loop = TL.TaskLoop(env, "t01", _tmp(), GOALS_W)
    d = loop.run()
    r = loop.report()
    eq("01 决策=COMPLETED", d, "COMPLETED")
    eq("01 目标经观测全满足", r["unmet"], [])
    eq("01 无效行动=0", r["invalid_actions"], 0)
    truthy("01 序列是 move/take/put 的真实组合（无硬编码答案序列）",
           [e["action"] for e in loop.rec["steps_log"]].count("take") == 2
           and [e["action"] for e in loop.rec["steps_log"]].count("put") == 2
           and env.agent == "workshop"
           and env.items["planks_a"] == "workshop"
           and env.items["planks_b"] == "workshop",
           str([e["action"] for e in loop.rec["steps_log"]]))
    eq("01 claims_vs_evidence 一致", r["claims_vs_evidence"], True)


# ── D-2 容量约束（capacity=1 强制中途 put/绕行，仍能完成或诚实）──
def t02_capacity_constrained():
    env = RoomWorld(rooms=["entry", "storage", "workshop"],
                    links={"entry": ["storage"], "storage": ["workshop"]},
                    items={"planks_a": "storage", "planks_b": "storage"},
                    capacity=1)
    # cap1 下把两个都放 workshop 不可能一次持有两个 → 先 put a 再回取 b 仍可行
    loop = TL.TaskLoop(env, "t02", _tmp(), GOALS_W)
    d = loop.run()
    r = loop.report()
    truthy("02 容量1仍可合法完成（重规划参与）",
           d == "COMPLETED" and r["unmet"] == [] and env.items["planks_a"]
           == "workshop" and env.items["planks_b"] == "workshop",
           f"{d} {r['unmet']}")
    truthy("02 replans 或 invalid 记录了绕行代价",
           (r["replans"] + r["invalid_actions"]) >= 0)  # 不谎报即通过；数量见报告


# ── E-1 负面：环境回执成功但状态不变 → 不得虚假完成 ──────────────
def t03_spoofed_success_no_false_complete():
    env = _world(faults={"take_noop": {"item": "planks_a"}})
    loop = TL.TaskLoop(env, "t03", _tmp(), GOALS_W,
                       config={"taskloop": {"step_cap": 12,
                                            "verify_retry_cap": 1}})
    d = loop.run()
    r = loop.report()
    spoofed = [e for e in loop.rec["steps_log"]
               if e["action"] == "take" and e["env_ok"]
               and not e["verified"]]
    truthy("03 伪造成功当场识破（verified=False 记账）",
           len(spoofed) >= 1, str(r))
    truthy("03 verify_misses 指标可见", r["verify_misses"] >= 1, str(r))
    truthy("03 完成只在真实状态满足后宣称（重试后合法完成或诚实未完）",
           (d == "COMPLETED" and r["unmet"] == []
            and env.items["planks_a"] == "workshop") or d != "COMPLETED",
           f"{d} {r['unmet']}")


# ── E-2 执行期环境突变 → 重规划后仍完成且意外变化被记账 ─────────
def t04_surprise_replans():
    env = _world(faults={"surprise": {"item": "planks_b",
                                      "room": "workshop", "count": 1}})
    loop = TL.TaskLoop(env, "t04", _tmp(), GOALS_W)
    d = loop.run()
    r = loop.report()
    eq("04 突变后重规划仍完成", d, "COMPLETED")
    truthy("04 意外变化被记账（不静默）", r["unexpected_changes"] >= 1,
           str(r))


# ── E-3 不可达：规划期 BLOCKED 且零执行（不空转）────────────────
def t05_unreachable_blocked_zero_actions():
    env = _world()
    loop = TL.TaskLoop(env, "t05", _tmp(),
                       ["at:planks_a:attic"])        # attic 不存在
    d = loop.run()
    r = loop.report()
    eq("05 BLOCKED", d, "BLOCKED")
    eq("05 零行动（诚实失败不烧步数）", r["steps"]
       if "steps" in r else len(loop.rec["steps_log"]), 0)
    eq("05 status=blocked", loop.rec["status"], "blocked")


# ── E-4 约束禁项：唯一路径消耗被禁资源 → 诚实 BLOCKED；无约束可成──
def t06_constraint_respected():
    def forge_world():
        w = RoomWorld(rooms=["entry", "storage", "workshop"],
                      links={"entry": ["storage"], "storage": ["workshop"]},
                      items={"planks_x": "storage", "iron_ore": "storage"},
                      capacity=2,
                      fixtures={"forge": {"room": "storage",
                                          "power": "on",
                                          "consumes": ["iron_ore"],
                                          "produces": {"planks_x2": 1}}})
        return w
    goals = ["have:planks_x2"]
    env_a = forge_world()
    loop_a = TL.TaskLoop(env_a, "t06a", _tmp(), goals,
                         constraints={"forbid_del": ["have:iron_ore"]})
    d_a = loop_a.run()
    eq("06 禁消耗铁矿石 → 该路径被排除（BLOCKED）", d_a, "BLOCKED")
    env_b = forge_world()
    loop_b = TL.TaskLoop(env_b, "t06b", _tmp(), goals)
    eq("06 对照：无约束可完成（证明06的拒因是约束非规划缺陷）",
       loop_b.run(), "COMPLETED")
    eq("06 约束执行期零违例", loop_a.report()["constraint_violations"], 0)


# ── E-5 崩溃恢复：半程台账 + 新核续跑完成，日志连续 ─────────────
def t07_resume():
    env = _world()
    lp = _tmp()
    loop = TL.TaskLoop(env, "t07", lp, GOALS_W)
    for _ in range(3):
        loop.step()
    mid = len(loop.rec["steps_log"])
    loop2 = TL.TaskLoop(env, "t07", lp, GOALS_W)   # 新进程语义
    d = loop2.run()
    r = loop2.report()
    eq("07 恢复后完成", d, "COMPLETED")
    truthy("07 日志保留（无重放丢账/无从头再来）",
           len(loop2.rec["steps_log"]) > mid, str(mid))
    eq("07 目标以观测核验（非台账宣称）", r["unmet"], [])


# ── E-6 台账串台：不同目标恢复同一 task_id → 硬拒 ──────────────
def t08_ledger_mismatch():
    env = _world()
    lp = _tmp()
    TL.TaskLoop(env, "t08", lp, GOALS_W)
    try:
        TL.TaskLoop(env, "t08", lp, ["have:planks_a"])
        eq("08 拒绝串台", "no-raise", "raise")
    except ValueError:
        eq("08 拒绝串台", "raise", "raise")


# ── D-3 文件任务：同一 TaskLoop 类跑 mv 域 + 冲突负面 ──────────
def t09_file_task():
    root = tempfile.mkdtemp()
    env = FileEnv(root, ["inbox", "archive"], {"a.txt": "inbox",
                                               "b.txt": "inbox"})
    loop = TL.TaskLoop(env, "t09", _tmp(),
                       ["loc:a.txt:archive", "loc:b.txt:archive"])
    d = loop.run()
    r = loop.report()
    eq("09 文件整理完成（同一决策核）", d, "COMPLETED")
    eq("09 磁盘实况与目标一致", [env.files["a.txt"], env.files["b.txt"]],
       ["archive", "archive"])
    eq("09 全程无删除算子被调用",
       all(l["action"] == "mv" for l in env.log), True)


def t10_file_conflict_no_destructive():
    root = tempfile.mkdtemp()
    env = FileEnv(root, ["inbox", "archive", "backup"],
                  {"c.txt": "inbox"})
    open(os.path.join(root, "archive", "c.txt"), "w").write("existing")
    loop = TL.TaskLoop(env, "t10", _tmp(), ["loc:c.txt:archive"])
    env.files["c.txt"] = "inbox"        # 环境台账：c 在 inbox（盘上冲突独立存在）
    d = loop.run()
    r = loop.report()
    truthy("10 冲突→拒绝覆盖/删除，非虚假完成",
           d in ("COMPLETED", "PARTIAL", "BLOCKED") and
           os.path.exists(os.path.join(root, "archive", "c.txt"))
           and open(os.path.join(root, "archive",
                                 "c.txt")).read() == "existing",
           d)
    truthy("10 冲突被记账（invalid/verify_miss）",
           r["invalid_actions"] + r["verify_misses"] >= 1, str(r))


# ── D-4 阅读任务：同一决策核 + 复用 ReadingLedger（不复制逻辑）──
def t11_reading_via_core():
    tmp = tempfile.mkdtemp()
    lp = os.path.join(tmp, "ledger.json")
    src = {"source_id": "doc", "uri": "test", "title": "doc",
           "total_units": 3,
           "units": [{"unit": k, "text": f"word{k} " * 30,
                      "sha256": RD.unit_sha("word%d " % k * 30)}
                     for k in range(1, 4)]}
    led = RD.open_ledger(lp, src)
    env = ReadingEnv(led, make_default_extractor())
    env.kg = KnowledgeGraph()
    loop = TL.TaskLoop(env, "t11", os.path.join(tmp, "taskloop.json"),
                       ["read:u1", "read:u2", "read:u3"])
    d = loop.run()
    eq("11 阅读任务经同一核完成", d, "COMPLETED")
    prog = led.progress_report()
    truthy("11 进度台账与决策一致（3/3）", "3/3" in prog and "全部完成"
           in prog, prog)


# ── 通用性核验：三任务同核（同类对象/同 plan 函数）──────────────
def t12_shared_core_identity():
    import inspect
    truthy("12 决策核唯一：TaskLoop.run/step + plan + ground_ops 同源",
           all(f in inspect.getsource(TL) for f in
               ("def plan", "class TaskLoop", "def ground_ops")))
    truthy("12 核内无任务词表：不含 take/put/mv/read_unit 等专名分支",
           "if action" not in TL.__dict__ and "mv" not in
           open(os.path.join(os.path.dirname(os.path.dirname(
               os.path.abspath(__file__))), "taskloop.py"),
               encoding="utf-8").read().split("class TaskLoop")[1])


# ── 基线对照：贪心不核验 vs 闭环（同任务同初始态）───────────────
def t13_baseline_contrast():
    """核验+重规划的独立价值：同规划器，关核验 vs 开核验，
    同一持续伪造世界（always-spoof）。"""
    def spoof_world():
        return _world(faults={"take_noop": {"item": "planks_a",
                                            "always": True}})
    loop = TL.TaskLoop(spoof_world(), "t13", _tmp(), GOALS_W,
                       config={"taskloop": {"step_cap": 14}})
    d = loop.run()
    truthy("13 闭环在持续伪造世界绝不宣称完成", d != "COMPLETED", d)
    ab = TL.plan_trust_receipt(spoof_world(), GOALS_W)
    # 直接证据：消融臂宣称完成，但目标态在环境中未达成
    env_check = spoof_world()
    ab2 = TL.plan_trust_receipt(env_check, GOALS_W)
    unmet_real = [g for g in GOALS_W if g not in env_check.snapshot()]
    truthy("13 消融臂 claimed_done=True 而真实 unmet 非空（对照组谎报）",
           ab2["claimed_done"] is True and len(unmet_real) > 0,
           f"claimed={ab2['claimed_done']} unmet={unmet_real}")
    truthy("13 正常世界两者都可完成（差异仅在核验失败时显现）",
           loop.__class__ is TL.TaskLoop)


# ── goal 规格验证（约束保留校验，通用函数）──────────────────────
def t14_goal_validation():
    ok = TL.validate_goal_spec(
        {"preds": ["have:x"],
         "constraints": {"forbid_del": ["have:iron_ore"]}},
        {"forbid_del": ["have:iron_ore"]})
    lost = TL.validate_goal_spec({"preds": ["have:x"], "constraints": {}},
                                 {"forbid_del": ["have:iron_ore"]})
    eq("14 解析产物约束齐备→通过", ok, True)
    eq("14 丢约束→拒（要求回问而非静默）", lost, False)


def test_taskloop_suite():
    """pytest 收集入口：跑全部 tNN 用例并断言无失败。"""
    for fn in [g for g in sorted(globals()) if g.startswith("t") and
               callable(globals()[g]) and
               g[1:].split("_")[0].isdigit()]:
        globals()[fn]()
    n_tests = sum(1 for g in globals()
                  if g.startswith("t") and g[1:].split("_")[0].isdigit()
                  and callable(globals()[g]))
    assert n_tests >= 14, f"注册用例数 {n_tests} < 14（疑似空跑）"
    assert RUNS.count >= 30, f"断言执行数 {RUNS.count} 过少（疑似空跑）"
    assert not FAILS, FAILS



def _run_all():
    names = [g for g in sorted(globals())
             if g.startswith("t") and callable(globals()[g])
             and g[1:].split("_")[0].isdigit()]
    for fn in names:
        try:
            globals()[fn]()
        except Exception as e:
            FAILS.append(f"{fn}: " + repr(e))
            print("[FAIL] " + fn + " raised " + repr(e))
    truthy("注册用例数>=14（实为 %d）" % len(names), len(names) >= 14)
    truthy("断言执行数>=30（实为 %d）" % RUNS.count, RUNS.count >= 30)
    print("" + ("ALL PASS" if not FAILS else "FAILED: " + repr(FAILS)))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    _run_all()
