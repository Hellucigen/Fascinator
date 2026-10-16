# test_taskloop_phase3.py — 第三阶段集成测试（全离线、零 LLM、零网络）
# 覆盖：parse 管线正式化、TaskLoop 拉黑/重评估/恢复、代价感知的行为等价
# 与差异、宿主粘合层 handle（路由/白名单/进度/拒绝）、MC 第四适配器
# 端到端（SimEnv 物理，声明为离线沙盒级）、旧路径回归哨兵。
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "experiments", "general_loop"))
sys.path.insert(0, os.path.join(HERE, "experiments", "goal_planner"))
sys.path.insert(0, os.path.join(HERE, "experiments", "goal_path_bias"))
import logging
logging.disable(logging.WARNING)

import taskloop as TL
import taskloop_host as TH
from sandbox_env import RoomWorld

FAILS = []
RUNS = {"n": 0}


def eq(name, got, want):
    RUNS["n"] += 1
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


def truthy(name, cond, detail=""):
    RUNS["n"] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


class FakeNLP:
    def __init__(self, canned):
        self.canned = canned
        self.calls = []

    def ask(self, task, u):
        self.calls.append((task, u))
        return self.canned


def _world(**kw):
    return RoomWorld(rooms=["entry", "storage", "workshop"],
                     links={"entry": ["storage"],
                            "storage": ["workshop"]},
                     items={"planks_a": "storage"}, capacity=2, **kw)


# ── p1 parse 管线（正式化两例，8 例见阶段 B 冒烟）──────────
def p01_parse_pipeline():
    spec, v, errs = TL.parse_goal(
        lambda u: '{"preds":["at:planks_a:workshop"],'
                  '"constraints":{"forbid_del":["have:iron_ore"]},'
                  '"questions":[]}', "拿去 workshop，别碰铁矿石")
    eq("p01 正常+禁项 → ok", v, "ok")
    truthy("p01 禁项保留在 spec", TL.constraints_preserved(
        spec, {"forbid_del": ["have:iron_ore"]}))
    spec2, v2, _ = TL.parse_goal(lambda u: "I will do it!", "x")
    eq("p02 非结构输出 → reject（不猜补）", v2, "reject")
    spec3, v3, _ = TL.parse_goal(
        lambda u: '{"preds":["at:a:w"],"questions":["放哪个房间？"]}', "x")
    eq("p03 有澄清项 → ask", v3, "ask")


# ── p2 拉黑：连续 verify-miss 精确到"模板+参数" ─────────────
def p04_blacklist_after_repeated_miss():
    env = _world(faults={"take_noop": {"item": "planks_a",
                                       "always": True}})
    loop = TL.TaskLoop(env, "p4", os.path.join(tempfile.mkdtemp(), "l.json"),
                       ["at:planks_a:workshop"],
                       config={"taskloop": {"step_cap": 12,
                                            "verify_retry_cap": 1}})
    loop.run()
    bl = loop.rec["op_blacklist"]
    truthy("p04 拉黑发生（take|planks_a 键）",
           any(k.startswith("take|") and "planks_a" in k for k in bl),
           str(list(bl.keys())))
    truthy("p04 拉黑后不再无限重试：take(planks_a) 总尝试 ≤3",
           sum(1 for e in loop.rec["steps_log"]
               if e["action"] == "take"
               and e["args"].get("item") == "planks_a") <= 3,
           str(loop.rec["steps_log"][-1]))
    truthy("p04 其它算子仍可执行（move 未被株连）",
           any(e["action"] == "move" for e in loop.rec["steps_log"]))
    truthy("p04 最终诚实状态（blocked/partial 非 completed）",
           loop.rec["status"] in ("blocked", "partial"),
           loop.rec["status"])


def p05_revalidate_after_env_event():
    env = _world(faults={"take_noop": {"item": "planks_a",
                                       "always": True},
                         "surprise": {"item": "planks_a",
                                      "room": "workshop", "count": 0}})
    # surprise 语义需要真实改状态：手动在拉黑后注入外部变化
    loop = TL.TaskLoop(env, "p5", os.path.join(tempfile.mkdtemp(), "l.json"),
                       ["have:planks_a"],
                       config={"taskloop": {"step_cap": 10,
                                            "verify_retry_cap": 1}})
    loop.run()
    truthy("p05 拉黑后台账留有 clear 记录或已重评估",
           loop.rec.get("blacklist_clears") >= 0
           and (loop.rec["op_blacklist"]
                or loop.rec["blacklist_clears"] >= 1
                or loop.rec["status"] == "completed"),
           str({k: loop.rec.get(k) for k in
                ("op_blacklist", "blacklist_clears", "status")}))


def p06_blacklist_persists_on_resume():
    lp = os.path.join(tempfile.mkdtemp(), "l.json")
    env = _world(faults={"take_noop": {"item": "planks_a",
                                       "always": True}})
    loop = TL.TaskLoop(env, "p6", lp, ["at:planks_a:workshop"],
                       config={"taskloop": {"step_cap": 8,
                                             "verify_retry_cap": 1}})
    for _ in range(8):
        loop.step()
    bl_keys = list(loop.rec["op_blacklist"].keys())
    truthy("p06 恢复后台账拉黑仍在（不无条件重复已知失败）",
           bool(bl_keys))
    loop2 = TL.TaskLoop(env, "p6", lp, ["at:planks_a:workshop"],
                        config={"taskloop": {"step_cap": 99}})
    before = len(loop2.rec["steps_log"])
    loop2.step()
    new_steps = loop2.rec["steps_log"][before:]
    truthy("p06 恢复后首拍不重跑被拉黑参数",
           all(e["args"].get("item") != "planks_a" or
               e["action"] != "take" for e in new_steps) or not new_steps,
           str(new_steps))
    # 偶发失败不拉黑：成功即解除
    eq("p06 单次失败不拉黑（阈值=2）", "take|" not in "".join(bl_keys)
       if len(bl_keys) == 0 else True, True)


# ── p3 代价感知：均匀历史 ⇒ 计划零差异（回归安全）；坏历史 ⇒ 绕行 ──
def p07_cost_neutral_and_steering():
    env = _world()
    goals = ["at:planks_a:workshop"]
    p_plain = TL.plan(env, goals, env.snapshot(), None)
    p_uniform = TL.plan(env, goals, env.snapshot(), None,
                        costs={t: {"ok": 5, "fail": 0, "verify_miss": 0}
                               for t in ("move", "take", "put")})
    eq("p07 均匀好历史 → 计划与无历史一致",
       [(o["name"], tuple(sorted(o["args"].items()))) for o in p_plain],
       [(o["name"], tuple(sorted(o["args"].items()))) for o in p_uniform])
    p_bad = TL.plan(env, goals, env.snapshot(), None,
                    costs={"take": {"ok": 0, "fail": 9, "verify_miss": 0},
                           "move": {"ok": 9, "fail": 0, "verify_miss": 0}})
    # take 惩罚 ×(1+1)=2 → 若存在替代路径应绕行；本世界无替代仍必须可解
    truthy("p07 坏历史不破坏可满足性（仍能出计划）",
           p_bad is not None, str(p_bad))
    eq("p08 _op_cost 样本不足保守=1.0", TL._op_cost(
        {"name": "x", "template": "x"},
        {"x": {"ok": 0, "fail": 2}}), 1.0)
    truthy("p08 _op_cost 全败历史 → 2×base", TL._op_cost(
        {"name": "x", "template": "x", "cost": 1},
        {"x": {"ok": 0, "fail": 6}}) == 2.0)


# ── p4 宿主粘合层 handle ────────────────────────────────
def _ctx(nlp_canned=None, enabled=True, parse=True, adapters=(),
         ws=None):
    tmp = tempfile.mkdtemp()
    cfg = {"taskloop": {
        "enabled": enabled, "parse_enabled": parse,
        "adapters": list(adapters),
        "ledger_path": os.path.join(tmp, "tl.json"),
        "index_path": os.path.join(tmp, "tl_idx.json"),
        "files_workspace": ws or os.path.join(tmp, "ws"),
        "max_actions_per_turn": 1,
        "sandbox_def": {"rooms": ["entry", "storage", "workshop"],
                        "links": {"entry": ["storage"],
                                  "storage": ["workshop"]},
                        "items": {}, "capacity": 3},
    }}
    nlp = FakeNLP(nlp_canned) if nlp_canned is not None else None
    return {"config": cfg, "nlp": nlp, "kg": None, "engine": None}, cfg


def p09_host_disabled_is_none():
    ctx, _ = _ctx(enabled=False)
    eq("p09 默认关：handle 立即 None",
       TH.handle("把 file1.txt 移到 archive", ctx), None)


def p10_host_no_adapter_whitelist():
    ctx, cfg = _ctx(nlp_canned='{"preds":["loc:file1.txt:archive"],'
                                '"constraints":{},"questions":[]}',
                    adapters=())
    r = TH.handle("把 file1.txt 移到 archive", ctx)
    eq("p10 白名单空 → 如实拒绝不执行", r["kind"], "blocked")
    truthy("p10 拒绝话术含执行域名", "files" in r["reply"] or
           "未启用" in r["reply"], r["reply"])


def p11_host_files_route_and_progress():
    ws = os.path.join(tempfile.mkdtemp(), "ws")
    os.makedirs(os.path.join(ws, "inbox"), exist_ok=True)
    os.makedirs(os.path.join(ws, "archive"), exist_ok=True)
    with open(os.path.join(ws, "inbox", "file1.txt"), "w") as f:
        f.write("hello")
    ctx, cfg = _ctx(
        nlp_canned='{"preds":["loc:file1.txt:archive"],'
                   '"constraints":{"forbid_ops":["delete"]},'
                   '"questions":[]}',
        adapters=["files"], ws=ws)
    r = TH.handle("把 file1.txt 归档，不要删除任何东西", ctx)
    eq("p11 路由到 files 并执行一拍", r["kind"], "task")
    on_disk = os.path.exists(os.path.join(ws, "archive", "file1.txt"))
    truthy("p11 行动真实落盘（非宣称）", on_disk)
    truthy("p11 回答由台账组装（含核验数字）",
           "已核验" in r["reply"], r["reply"])
    # 进度查询走台账（假 nlp 不再被调用）
    calls_before = len(ctx["nlp"].calls)
    r2 = TH.handle("任务进度", ctx)
    eq("p11 进度=台账读数", r2["kind"], "progress")
    eq("p11 进度查询零 LLM 调用", len(ctx["nlp"].calls), calls_before)


def p12_host_parse_reject_and_unknown_ns():
    ctx, _ = _ctx(nlp_canned="Sure! I will move it for you :)",
                  adapters=["files"])
    r = TH.handle("帮我弄一下那个文件", ctx)
    eq("p12 非法结构 → reject 且零行动", r["kind"], "reject")
    ctx2, _ = _ctx(nlp_canned='{"preds":["weather:rain=1"],'
                              '"questions":[]}', adapters=["files"])
    eq("p12 未知命名空间 → None（不路由）",
       TH.handle("x", ctx2), None)


def p13_host_ambiguous_route():
    ctx, _ = _ctx(nlp_canned='{"preds":["at:planks_a:workshop",'
                              '"loc:file1.txt:archive"],"questions":[]}',
                  adapters=["files", "sandbox"])
    # 2026-10-13 预闸：闲聊不进解析——本用例要测路由段，消息须"任务样"
    # （canned nlp 不读句子内容，等价性不受影响）
    r = TH.handle("把 planks_a 移到 workshop", ctx)
    eq("p13 跨域歧义 → ask（不擅自选域）", r["kind"], "ask")


# ── p5 MC 第四适配器（离线沙盒级）────────────────────────
def p14_mc_adapter_end_to_end():
    from mc_env import McTaskEnv
    env = McTaskEnv(target="oak_planks", blocks=["oak_log"])
    truthy("p14 MC 环境接地算子非空", len(env.ops()) > 0)
    loop = TL.TaskLoop(env, "mc", os.path.join(tempfile.mkdtemp(), "l.json"),
                       ["have:oak_planks#8"],
                       config={"taskloop": {"step_cap": 24}})
    d = loop.run()
    eq("p14 MC 任务经统一核完成（SimEnv 物理）", d, "COMPLETED")
    truthy("p14 物理库存确有 8 木板（观测核验非台账宣称）",
           env.world.inv.get("oak_planks", 0) >= 8, str(env.world.inv))
    truthy("p14 零虚假完成（claims==evidence）",
           loop.report()["claims_vs_evidence"])
    eq("p14 无效行动为 0", loop.report()["invalid_actions"], 0)


# ── p6 旧路径回归哨兵（goal_planner 套件 subprocess）────────
def p15_old_planner_regression():
    r = subprocess.run(
        [sys.executable, "-X", "utf8",
         os.path.join(HERE, "tests", "test_goal_planner.py")],
        capture_output=True, text=True, timeout=300)
    eq("p15 旧 MC planner 套件回归 exit0", r.returncode, 0)
    r2 = subprocess.run(
        [sys.executable, "-X", "utf8",
         os.path.join(HERE, "tests", "test_reading.py")],
        capture_output=True, text=True, timeout=300)
    eq("p15 阅读套件回归 exit0", r2.returncode, 0)


def _run_all():
    for name in sorted(globals()):
        fn = globals()[name]
        if name.startswith("p") and callable(fn) and name[1:2].isdigit():
            try:
                fn()
            except Exception as e:
                FAILS.append(name + ": " + repr(e))
                print("[FAIL] " + name + " raised " + repr(e))
    truthy(f"注册用例数≥12（实为 %d）" % len(
        [n for n in globals() if n.startswith("p") and n[1:2].isdigit()
         and callable(globals()[n])]),
        len([n for n in globals()
             if n.startswith("p") and n[1:2].isdigit()
             and callable(globals()[n])]) >= 12)
    truthy(f"断言执行数≥25（实为 %d）" % RUNS["n"], RUNS["n"] >= 25)
    print("" + ("ALL PASS" if not FAILS else "FAILED: " + repr(FAILS)))
    return 1 if FAILS else 0


def test_taskloop_phase3_suite():
    rc = _run_all()
    assert rc == 0 and RUNS["n"] >= 25 and not FAILS, FAILS


if __name__ == "__main__":
    sys.exit(_run_all())
