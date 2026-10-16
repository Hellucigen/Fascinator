# taskloop.py — 通用任务闭环决策核（2026-10-12 审计 docs/audits/GENERAL_LOOP_AUDIT_2026-10-12.md）
# ============================================================================
# 目标：把"理解目标→对比当前/目标状态→选一步→执行→重观测核验→更新
# 台账→判下一步（CONTINUE/REPLAN/ASK/BLOCKED/COMPLETED/PARTIAL）"做成
# **任务无关**的决策核；世界规则与校验归环境适配器（snapshot/ops/execute
# 协议），选择与核验归本模块。为阅读/文件/Minecraft/任何环境提供同一条环。
#
# 与既有件的关系（复用不重造）：
#   * 状态两阶段"发起≠确认"沿用 reading.ReadingLedger 教训；
#   * "工具 ok ≠ 目标达成、以观测差值核对"沿用 goal_planner._monitor 语义；
#   * 台账 json_store 原子写沿用既有持久化原语；
#   * 谓词/算子为小型 STRIPS 模板（pre/add/del），由环境以**数据**声明
#     ——不为任何任务在核内写词表或 if。
# 默认惰性：本模块无自动接线、无生产开关；宿主/autonomy 何时消费另行门控。
# ============================================================================

import itertools
import json
import os
import time

from json_store import atomic_write_json, load_json

DECISIONS = ("CONTINUE", "REPLAN", "ASK_USER", "BLOCKED", "COMPLETED",
             "PARTIAL")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── 计划核（通用：对环境声明的 op schema 做回归式规划）───────────

def ground_ops(env):
    """环境协议约定：ops() 返回**已接地**算子（pre/add/del 为字面谓词，
    args 为值）。universe() 保留给环境自身生成接地集合，决策核不做
    模板绑定——少一层容易出错的特化。"""
    out = []
    for g in env.ops():
        if all(isinstance(x, str) for x in
               list(g.get("pre", [])) + list(g.get("add", []))
               + list(g.get("del", []))):
            out.append({"name": g["name"],
                        "args": dict(g.get("args") or {}),
                        "pre": list(g.get("pre") or []),
                        "add": list(g.get("add") or []),
                        "del": list(g.get("del") or []),
                        "template": g.get("template", g["name"])})
    return out


def _op_key(g):
    import json as _j
    return g.get("template", g["name"]) + "|" + _j.dumps(
        g.get("args") or {}, sort_keys=True, ensure_ascii=False)


def _allowed(g, constraints):
    cons = constraints or {}
    if _op_key(g) in set(cons.get("blacklist") or []):
        return False
    for f in cons.get("forbid_del", []):
        for d in g["del"]:
            if d == f or d.startswith(f.rstrip("*").rstrip(":")):
                return False
    if g["name"] in (constraints or {}).get("forbid_ops", []):
        return False
    return True


def plan(env, goals, state, constraints=None, max_steps=16,
         expand_cap=4000, costs=None):
    """前瞻 best-first 搜索（谓词状态空间）：对小型接地域稳健且通用，
    规避线性回归规划的抖动/序错误。启发式=未满足目标数；不满足即 None
    （绝不伪造计划）。"""
    import heapq
    goals = list(goals)
    gset = set(goals)
    start = frozenset(state)
    _all_ground(env, constraints)          # 预热接地缓存并编号
    seq = 0
    pq = [(len(gset - start), 0, seq, start, ())]   # (f, g, 序号防集比较, state, path)
    seen = {start: 0}
    pops = 0
    while pq and pops < expand_cap:
        pops += 1
        _f, gcost, _seq, cur, path = heapq.heappop(pq)
        if gset <= cur:
            return _decode(path, env, constraints)
        if gcost >= max_steps:      # 预算=累计有效代价（默认每步 1）
            continue
        for o in _allowed_ops(_all_ground(env, constraints), cur):
            if not _allowed(o, constraints):
                continue
            nxt = frozenset((cur | set(o["add"])) - set(o["del"]))
            if nxt == cur:
                continue
            ng = gcost + _op_cost(o, costs)
            if nxt in seen and seen[nxt] <= ng:
                continue
            seen[nxt] = ng
            h = len(gset - nxt)
            seq += 1
            heapq.heappush(pq, (round(ng + h, 6), round(ng, 6), seq, nxt,
                                 path + (o["_id"],)))
    return None


def _op_cost(o, costs):
    """单步有效代价：声明 cost（默认 1）× 历史失败惩罚。
    样本 <3 一律保守取 1.0（不凭噪声历史歪曲排序）；约束/合法性
    已在 _allowed 与 pre 过滤中先行，代价只影响同可达方案间的排序。"""
    base = float(o.get("cost", 1)) or 1.0
    if not costs:
        return base
    st = costs.get(o.get("template", o["name"])) or {}
    ok = int(st.get("ok", 0))
    bad = int(st.get("fail", 0)) + int(st.get("verify_miss", 0))
    n = ok + bad
    if n < 3:
        return base
    return base * (1.0 + (bad / n))


def _all_ground(env, constraints):
    ops = getattr(env, "_grounded_cache", None)
    if ops is None:
        ops = ground_ops(env)
        for i, o in enumerate(ops):
            o["_id"] = i
        env._grounded_cache = ops       # 对象属性缓存（id() 会复用，禁用）
    return ops


def _allowed_ops(ops, state):
    return [o for o in ops if all(p in state for p in o["pre"])]


def _decode(path, env, constraints):
    ops = _all_ground(env, constraints)
    return [dict(ops[i]) for i in path]


# ── 闭环主体 ─────────────────────────────────────────────

class TaskLoop:
    """一个任务一条台账。每拍：live snapshot → 差距 → 计划（必要时重规
    划）→ 至多一步 → 执行 → **重观测核验** → 记证据 → 给决策。"""

    def __init__(self, env, task_id, ledger_path, goals, constraints=None,
                 config=None):
        self.env = env
        self.ledger_path = ledger_path
        cfg = (config or {}).get("taskloop") or {}
        self.step_cap = int(cfg.get("step_cap", 40))
        self.verify_retry_cap = int(cfg.get("verify_retry_cap", 1))
        data = load_json(ledger_path, default=None) or {}
        self.tid = task_id
        if task_id in data:
            self.rec = data[task_id]
            # 目标一致性：恢复必须以台账目标为准；不一致拒开（防串台）
            if self.rec.get("goals") != sorted(goals) or \
                    self.rec.get("constraints") != (constraints or {}):
                raise ValueError("台账目标与传入目标不一致（拒绝恢复）")
        else:
            self.rec = {"goals": sorted(goals), "constraints":
                        constraints or {},
                        "created": _now(), "steps_log": [],
                        "decisions": [], "status": "active",
                        "replans": 0, "invalid_actions": 0,
                        "verify_misses": 0, "constraint_hits": 0,
                        "unexpected_changes": 0,
                        # 阶段 D：算子级拉黑与 op 历史（复用 planner
                        # exclude 语义；恢复沿用、不无条件重复已知失败）
                        "op_blacklist": {}, "op_stats": {},
                        "blacklist_clears": 0}
            self._flush()

    # ── 工具：目标核对 ─────────────────────────────────
    def unmet(self, snap):
        return [g for g in self.rec["goals"] if g not in snap]

    def _flush(self):
        data = load_json(self.ledger_path, default=None) or {}
        data[self.tid] = self.rec
        atomic_write_json(self.ledger_path, data)

    def report(self):
        snap = set(self.env.snapshot())
        unmet = self.unmet(snap)
        return {"task_id": self.tid,
                "status": self.rec["status"],
                "goals": len(self.rec["goals"]),
                "met_by_observation": len(self.rec["goals"]) - len(unmet),
                "unmet": unmet,
                "steps": len(self.rec["steps_log"]),
                "replans": self.rec["replans"],
                "invalid_actions": self.rec["invalid_actions"],
                "verify_misses": self.rec["verify_misses"],
                "constraint_violations": self.rec["constraint_hits"],
                "unexpected_changes": self.rec["unexpected_changes"],
                "claims_vs_evidence":
                    self.rec["status"] != "completed" or not unmet}

    # ── 一拍 ──────────────────────────────────────────
    def step(self):
        snap = set(self.env.snapshot())
        unmet = self.unmet(snap)
        if not unmet:
            self.rec["status"] = "completed"
            self.rec["decisions"].append(
                {"d": "COMPLETED", "why": "全部目标谓词经观测核验成立",
                 "ts": _now()})
            self._flush()
            return "COMPLETED"
        if len(self.rec["steps_log"]) >= self.step_cap:
            self.rec["status"] = "partial"
            self.rec["decisions"].append(
                {"d": "PARTIAL", "why": f"步数上限 {self.step_cap}，未满足="
                                        f"{unmet[:4]}", "ts": _now()})
            self._flush()
            return "PARTIAL"
        # 每拍从 live 快照重规划；拉黑集并入约束（跨恢复持久生效）
        cons = dict(self.rec.get("constraints") or {})
        bl = self.rec.get("op_blacklist") or {}
        cons["blacklist"] = list(bl.keys())
        if bl and self.rec.get("_env_changed_last"):
            # 环境实质变化 → 清空拉黑一次、允许重评估（有界：最多 2 次，
            # 防"抖动→解除→再中毒"无限循环）
            if self.rec["blacklist_clears"] < 2:
                self.rec["op_blacklist"] = {}
                self.rec["blacklist_clears"] += 1
                self.rec["decisions"].append(
                    {"d": "REPLAN", "why": "环境变化：拉黑算子全部重评估",
                     "ts": _now()})
            self.rec["_env_changed_last"] = False
        p = plan(self.env, self.rec["goals"], snap, cons,
                 costs=self.rec.get("op_stats"),
                 )
        if p is None or not p:
            self.rec["status"] = "blocked"
            self.rec["decisions"].append(
                {"d": "BLOCKED", "why": f"目标在环境规则+约束下不可达: "
                                        f"{unmet[:4]}", "ts": _now()})
            self._flush()
            return "BLOCKED"
        if p is None:
            pass  # 下方统一处理
        nxt = p[0]
        last = self.rec["steps_log"][-1] if self.rec["steps_log"] else None
        if last and (last["action"] != nxt["name"]
                     or last["args"] != nxt["args"]):
            self.rec["replans"] += 1
            self.rec["decisions"].append(
                {"d": "REPLAN", "why": f"计划前缀 {last['action']} → "
                                        f"{nxt['name']}", "ts": _now()})
        # 双闸：约束的静态违例（plan 已过滤，此处兜底）+ 前置现场核验
        if not _allowed(nxt, self.rec.get("constraints")):
            self.rec["constraint_hits"] += 1
            self.rec["decisions"].append({"d": "BLOCKED",
                                          "why": "约束冲突", "ts": _now()})
            self._flush()
            return "BLOCKED"
        missing = [x for x in nxt["pre"] if x not in snap]
        if missing:
            self.rec["invalid_actions"] += 1
            self.rec["decisions"].append(
                {"d": "REPLAN", "why": f"前置缺失 {missing[:3]}（不盲执行）",
                 "ts": _now()})
            self._flush()
            return "REPLAN"
        # 执行一步
        res = self.env.execute({"name": nxt["name"], "args": nxt["args"]})
        snap2 = set(self.env.snapshot())
        # 核验：期望效果/删除以**观测**为准；非预期变化单独记账
        want_add = [x for x in nxt["add"] if x not in snap2]
        want_del = [x for x in nxt["del"] if x in snap2]
        unexpected = (snap2 - snap) - set(nxt["add"]) | \
            (snap - snap2) - set(nxt["del"])
        verified = bool(res.get("ok")) and not want_add and not want_del
        entry = {"seq": len(self.rec["steps_log"]) + 1,
                 "action": nxt["name"], "args": nxt["args"],
                 "expected": {"add": nxt["add"], "del": nxt["del"]},
                 "unmet_before": want_add + want_del,
                 "unexpected": sorted(list(unexpected))[:6],
                 "env_ok": bool(res.get("ok")),
                 "env_reason": str(res.get("reason") or "")[:120],
                 "verified": verified, "ts": _now()}
        self.rec["steps_log"].append(entry)
        if unexpected:
            self.rec["unexpected_changes"] += 1
        TL_key = nxt.get("template", nxt["name"]) + "|" + json.dumps(
            nxt["args"], sort_keys=True, ensure_ascii=False)
        st = self.rec["op_stats"].setdefault(
            nxt.get("template", nxt["name"]),
            {"ok": 0, "fail": 0, "verify_miss": 0})
        if not res.get("ok"):
            self.rec["invalid_actions"] += 1
            st["fail"] += 1
            self.rec["decisions"].append(
                {"d": "REPLAN", "why": "环境拒绝: " + entry["env_reason"],
                 "ts": _now()})
        elif not verified:
            self.rec["verify_misses"] += 1
            st["verify_miss"] += 1
            cnt = sum(1 for e in self.rec["steps_log"]
                      if e["action"] == entry["action"]
                      and e["args"] == entry["args"] and not e["verified"])
            if cnt > self.verify_retry_cap:
                # 阶段 D：同"模板+参数"连续 verify-miss 超阈 → 精确拉黑
                # （不封整个工具；该键核验成功一次即解除）
                self.rec["op_blacklist"][TL_key] = {
                    "pre": sorted(nxt["pre"]), "misses": cnt,
                    "ts": _now()}
                self.rec["decisions"].append(
                    {"d": "REPLAN",
                     "why": "拉黑 " + TL_key[:70] + "（连续 " + str(cnt)
                            + " 次回执成功无变化，不再信任其回执）",
                     "ts": _now()})
            else:
                self.rec["decisions"].append(
                    {"d": "REPLAN", "why": "回执成功但观测无变化，重试",
                     "ts": _now()})
        else:
            st["ok"] += 1
            self.rec["op_blacklist"].pop(TL_key, None)
            self.rec["decisions"].append(
                {"d": "CONTINUE", "why": entry["action"] + " 核验通过",
                 "ts": _now()})
        if entry["unexpected"]:
            self.rec["_env_changed_last"] = True
        self._flush()
        return self.rec["decisions"][-1]["d"]

    def run(self, max_rounds=60):
        for _ in range(max_rounds):
            d = self.step()
            if d in ("COMPLETED", "BLOCKED", "PARTIAL", "ASK_USER"):
                return d
        return "PARTIAL"


# ── 通用"理解→结构化目标"的验证钩子（不绑定具体任务）───────────────

def validate_goal_spec(spec, required_constraints):
    """LLM/解析器产物入库前的核验：用户明确列出的约束必须原样保留。
    required_constraints: {"forbid_ops":[...], "forbid_del":[...]} 子集检查。
    缺任一 → False（调用方应回问用户，不得静默丢约束）。"""
    cons = (spec or {}).get("constraints") or {}
    for key, vals in (required_constraints or {}).items():
        have = set(cons.get(key) or [])
        if not set(vals or []) <= have:
            return False
    return bool((spec or {}).get("preds"))


def plan_trust_receipt(env, goals, max_steps=40):
    """消融臂：同一 forward 规划器，但**不重观测核验回执**、执行完序列
    即宣称完成。用于证明"核验+重规划"环节的独立价值。"""
    steps_taken = 0
    invalid = 0
    while steps_taken < max_steps:
        snap = set(env.snapshot())
        unmet = [g for g in goals if g not in snap]
        if not unmet:
            return {"claimed_done": True, "invalid": invalid,
                    "steps": steps_taken}
        p = plan(env, goals, snap)
        if not p:
            return {"claimed_done": False, "invalid": invalid,
                    "steps": steps_taken}
        for o in p:
            res = env.execute({"name": o["name"], "args": o["args"]})
            steps_taken += 1
            invalid += 0 if res.get("ok") else 1
            # 不核验：不比对 add/del 与实际状态
        # 序列走完 → 信任式宣称
        return {"claimed_done": True, "invalid": invalid,
                "steps": steps_taken}
    return {"claimed_done": False, "invalid": invalid,
            "steps": steps_taken}


# ── 基线：通用"贪心、不核验、不重规划"策略（对照用）────────────────

def greedy_nocheck(env, goals, max_steps=40):
    """同环境同目标的最小白名单基线：选第一个能补未满足目标的接地算子，
    前置交给环境拒绝；信任回执、不重观测、不看约束（约束=无）。
    返回 (claimed_done, metrics, log)。"""
    snap = set(env.snapshot())
    log = []
    invalid = 0
    false_claim = False
    for _ in range(max_steps):
        unmet = [g for g in goals if g not in snap]
        if not unmet:
            return True, {"invalid_actions": invalid}, log
        ops = [o for o in ground_ops(env) if unmet and
               set(unmet) & set(o["add"])]
        if not ops:
            break
        o = ops[0]
        res = env.execute({"name": o["name"], "args": o["args"]})
        invalid += 0 if res.get("ok") else 1
        snap_new = set(env.snapshot())
        progressed = snap_new != snap
        snap = snap_new
        log.append({"action": o["name"], "ok": bool(res.get("ok")),
                    "progressed": progressed})
        if not res.get("ok") and log.count(
                {"action": o["name"], "ok": False, "progressed": False}) > 3 \
                and progressed is False:
            break
    unmet = [g for g in goals if g not in snap]
    if unmet and log and all(x["ok"] for x in log[-2:]):
        false_claim = False   # 基线不宣称——诚实记录
    return (not unmet), {"invalid_actions": invalid,
                         "false_claim": false_claim}, log


# ── 阶段 B：通用目标解析管线（LLM→结构→严格校验；不猜补）──────────

_PREDS_RE = __import__("re").compile(r"^[a-z_][a-z0-9_]*(:[^:]*)*$")


def parse_goal(call_fn, utterance):
    """call_fn(prompt)->raw。返回 (spec|None, verdict, errors)。
    verdict: "ok" 可执行 | "ask" 有澄清问题 | "reject" 结构非法/缺项。
    规则：解析失败/字段类型不符/preds 含未命名空间谓词/questions 非空
    ——一律不执行；不允许把残缺输出猜补成"看起来合理"的目标。"""
    from reading import salvage_extract_json
    raw = call_fn(utterance)
    try:
        obj, _partial = salvage_extract_json(raw)
    except Exception as e:
        return None, "reject", ["unparseable: " + repr(e)[:80]]
    if not isinstance(obj, dict):
        return None, "reject", ["root not object"]
    errs = []
    preds = obj.get("preds")
    if not isinstance(preds, list) or not preds or             not all(isinstance(p, str) and _PREDS_RE.match(p) for p in preds):
        errs.append("preds 缺失/为空/非规范谓词")
    cons = obj.get("constraints", {})
    if not isinstance(cons, dict):
        errs.append("constraints 非对象")
    else:
        for k in ("forbid_ops", "forbid_del"):
            v = cons.get(k, [])
            if not isinstance(v, list) or not all(isinstance(x, str)
                                                  for x in v):
                errs.append("constraints." + k + " 非字符串列表")
    qs = obj.get("questions", [])
    if not isinstance(qs, list) or not all(isinstance(x, str) for x in qs):
        errs.append("questions 非字符串列表")
    if errs:
        return None, "reject", errs
    spec = {"preds": preds, "constraints": {
        "forbid_ops": cons.get("forbid_ops", []),
        "forbid_del": cons.get("forbid_del", [])},
        "questions": qs}
    if qs:
        return spec, "ask", []
    return spec, "ok", []


def constraints_preserved(spec, required):
    """用户显式约束在解析后必须原样在场（丢任一 → False → 宿主必须
    拒执行/回问，绝不静默丢约束）。"""
    cons = (spec or {}).get("constraints") or {}
    for k, vals in (required or {}).items():
        if not set(vals or []) <= set(cons.get(k) or []):
            return False
    return True
