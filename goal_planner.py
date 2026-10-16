# goal_planner.py — 目标驱动最小闭环计划器（候选机制，默认关闭）
# ============================================================================
# 闭环：目标设定 → 当前状态识别 → 规划 → 行动队列（单步派发）→ 执行
#       → 状态监测（预期效果核对）→ 完成判定 / 重新规划 → 证据记录。
#
# 设计审计：docs/audits/PLANNER_AUDIT_2026-10-09.md。
# 与 goal_path_bias 的关系：完全正交。计划判定**不读节点激活、不占 Top-k**
# （族 L 已证"目标显著=行动建议"混淆，FINAL_REPORT §3）；规划依据=
# 图上状态转换边（产生/需要/掉落/需要工具/属于→可采资源/拥有）的
# **静态语义 + provenance**，与激活动力学无关（relation_direction_campaign
# 的"两条路径分工"裁决）。
#
# 硬约束（违者即 bug）：
#   1. 默认关：config.planner.enabled=False 时本模块零触碰（maybe_tick 先查）。
#   2. Goal ≠ Action：目标=状态谓词 have(item,count)；达成判定只依据观测
#      状态（percept 或图观测边），**绝不**因"目标节点存在/激活/有图路径"
#      判达成，也不把目标节点当行动派发。
#   3. 图路径 ≠ 计划：计划步骤必须带前置条件（AND 结构）、预期效果、
#      依据边引用；派发闸门=前置条件在**当前观测**上全部成立。
#   4. 规划失败可观测：不可达（无生产者/环/超深/预算/不可采/AND 缺项）
#      一律 NO_FEASIBLE_PLAN + 终止目标（achieved=False）+ 证据，不伪造。
#   5. 重规划有终止条件：revision ≤ max_revisions；失败选项进 exclude 集，
#      重规划不得重新选中；超限终止。
#   6. 学习写回最小且定向：只更新**与该步依据直接相关**的配方/方块节点
#      计数（plan_success_count/plan_fail_count + blame），绝不改边权、
#      绝不无差别降级经过的边；单次成功不放大权重（无自动 promotion）。
#   7. 同一目标单计划：计划挂在目标节点 extra_attrs，revision 整体替换；
#      旧计划步骤全部落终态后才允许新计划派发（防双计划争抢队列）。
#   8. 不新建平行目标系统：复用 self_graph 指针与 goal_state 生命周期。
# ============================================================================

import logging
import math
import time
import uuid

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": False,           # 总开关（默认关）
    "max_depth": 6,             # 反向链深度上限
    "max_steps": 12,            # 单计划步数预算
    "max_revisions": 3,         # 重规划上限（超限终止目标）
    "step_retry_limit": 2,      # 同步骤原地重试上限（blame=action）
    "evidence_enabled": True,   # 定向计数写回（不动任何边权）
    "dispatch_priority": 0.7,
    "dispatch_motivation": "planned_goal",
}

# 动作命名与生产 obtain 通道一致（autonomy._goal_step_candidates）
ACTION_BY_KIND = {"gather": "gather_resource", "craft": "craft_item",
                  "smelt": "smelt_item"}


def _cfg(config):
    c = dict(DEFAULTS)
    c.update((config or {}).get("planner") or {})
    return c


# ── Goal：结构化目标谓词（复用 self_graph 指针）──────────────────

def attach_goal(kg, item, count=1, desc=None):
    """把"获得 item×count"挂为当前目标：走既有 set_current_goal 指针，
    结构条件写进目标节点 extra_attrs（不新建第二套目标存储）。"""
    from self_graph import set_current_goal
    desc = str(desc or f"获得 {item}×{count}")[:40]
    gid = set_current_goal(kg, desc)
    if not gid:
        return ""
    node = kg.nodes.get(gid)
    if node is not None:
        if not isinstance(node.extra_attrs, dict):
            node.extra_attrs = {}
        node.extra_attrs["goal_spec"] = {"type": "have",
                                         "item": str(item).lower(),
                                         "count": max(1, int(count))}
        node.touch()
    return gid


def _parse_spec_from_desc(kg, desc):
    """无 goal_spec 的历史目标：与 autonomy._obtain_goals 同一子串口径
    解析出 obtain 谓词（count=1）。解析不出 = 不可计划目标。"""
    for nid in kg.nodes:
        s = str(nid)
        if not s.startswith("物品:"):
            continue
        tgt = s[3:]
        if tgt and tgt in (desc or ""):
            return {"type": "have", "item": tgt.lower(), "count": 1}
    return None


def current_goal_spec(kg):
    """(goal_node_id, spec) 或 ("", None)。只认进行态指针。"""
    from self_graph import current_goal
    g = current_goal(kg) or {}
    gid = str(g.get("id") or "")
    if not gid or str(g.get("state") or "") != "进行中":
        return "", None
    node = kg.nodes.get(gid)
    spec = (node.extra_attrs or {}).get("goal_spec") if node else None
    if not isinstance(spec, dict) or spec.get("type") != "have":
        spec = _parse_spec_from_desc(kg, g.get("desc"))
    if not spec:
        return gid, None
    return gid, spec


def goal_satisfied(spec, state):
    """达成判定 = 观测库存满足谓词。不看激活、不看路径、不看节点存在。"""
    if not spec:
        return False
    return int(state.get("inventory", {}).get(spec["item"], 0) or 0) \
        >= int(spec.get("count", 1))


# ── Observation：状态视图（percept 优先；图观测为次，来源如实标记）──

def state_view(kg, percept=None):
    if percept is not None:
        inv = {}
        for i in (percept.get("inventory_items") or []):
            if isinstance(i, dict):
                nm = str(i.get("name") or "").lower()
                if nm:
                    raw = i.get("count", 1)
                    try:
                        c = int(float(1 if raw is None else raw))
                    except (TypeError, ValueError):
                        c = 0
                    inv[nm] = inv.get(nm, 0) + max(c, 0)
        seen = {str(b.get("name") or "").lower()
                for b in (percept.get("blocks") or [])
                if isinstance(b, dict)}
        return {"inventory": inv, "seen_blocks": seen, "source": "percept"}
    # 图观测路径：背包=物品节点 extra_attrs.count（minecraft/perception.py:221）
    inv = {}
    for nid, n in kg.nodes.items():
        s = str(nid)
        if s.startswith("物品:"):
            c = float((n.extra_attrs or {}).get("count", 0) or 0)
            if c > 0:
                inv[s[3:]] = int(c)
    return {"inventory": inv, "seen_blocks": set(), "source": "graph"}


# ── 图知识读取（复用 world_prior 公开读 API；严格判定不复用兜底）──

def _prov_ok(node_or_edge_ea, min_conf=0.5):
    ea = node_or_edge_ea or {}
    conf = ea.get("confidence")
    verified = ea.get("version_verified")
    ok = (conf is None or float(conf) >= min_conf)
    return ok, bool(verified)


def _gatherable_strict(kg, block):
    """属于→可采资源 白名单边必须存在。与 world_prior._gatherable_block
    的差别：那里查询异常保守放行（执行层兜底），计划层必须严格失败
    ——不可采就是不可采，不派发注定被拒的采集步。"""
    try:
        return kg.get_edge(str(block), "可采资源", "属于") is not None
    except Exception:
        return False


def _recipe_yield(kg, rid):
    n = kg.nodes.get(rid)
    try:
        return max(1, int((n.extra_attrs or {}).get("yield", 1) or 1))
    except Exception:
        return 1


# ── Plan：有界反向链（AND 前置；确定性；纯读图）─────────────────

class Unreachable(Exception):
    def __init__(self, item, why):
        self.item, self.why = item, why
        super().__init__(f"{item}: {why}")


def build_plan(kg, spec, state, cfg, exclude=None):
    """返回 {"steps":[...], "excluded":[...]} 或 {"unreachable":{item,why}}。
    steps 依赖序：子需求步骤先于父步骤。工作库存随计划推演（只累计本
    计划步骤自身的产出/消耗，不虚构外部补给）；每个选项失败时自恢复
    （steps 与 work 回卷），AND 缺项不会留下半成品计划。"""
    import world_prior as wp
    exclude = set(exclude or [])
    work = dict(state.get("inventory", {}))
    steps = []
    budget = [int(cfg["max_steps"])]

    def key_of(kind, owner, item):
        return f"{kind}:{owner}->{item}"

    def option_ea(node_id):
        n = kg.nodes.get(node_id)
        return (n.extra_attrs or {}) if n is not None else {}

    def _option_verified(kind, payload, nid, item):
        try:
            if kind == "recipe":
                e = kg.get_edge(nid, f"物品:{item}", "产生")
            else:
                e = kg.get_edge(nid, f"物品:{item}", "掉落")                     or kg.get_edge(nid, f"物品:{item}", "产生")
            ea = dict((e.extra_attrs or {}) if e is not None
                      else option_ea(nid))
        except Exception:
            ea = option_ea(nid)
        return _prov_ok(ea)

    def _apply_option(opt, item, need, depth, trail):
        base_n = len(steps)
        base_work = dict(work)
        try:
            kind, payload = opt
            if kind == "block":
                blk = str(payload)
                for t in sorted(wp.tool_required(kg, blk)):
                    satisfy(t, 1, depth + 1, trail + (item,))
                budget[0] -= 1
                if budget[0] < 0:
                    raise Unreachable(item, "BUDGET")
                qty = max(1, int(need))
                steps.append({
                    "id": f"s{len(steps) + 1}", "kind": "gather",
                    "action": ACTION_BY_KIND["gather"], "target": blk,
                    # 与生产 gather 口径一致：quantity 承载缺口数
                    # （一次采集满足需求，否则需要多个的配方永远凑不齐）
                    "params": {"resource": blk, "quantity": qty},
                    "pre": [{"type": "gatherable", "block": blk}],
                    "expect": [{"type": "have", "item": item,
                                "min_delta": qty}],
                    "justify": [f"{blk}-[掉落]->物品:{item}"],
                    "status": "pending", "attempts": 0, "evidence": [],
                })
                work[item] = work.get(item, 0) + qty
            else:
                pr = payload
                inputs = pr["inputs"] or {}
                yld = _recipe_yield(kg, pr["recipe"])
                times = min(4, max(1, math.ceil(need / max(1, yld))))
                for mat in sorted(inputs):
                    total = int(inputs[mat]) * times
                    if work.get(mat, 0) < total:
                        satisfy(mat, total, depth + 1, trail + (item,))
                    work[mat] = work.get(mat, 0) - total
                pre = [{"type": "have", "item": m,
                        "count": int(inputs[m]) * times}
                       for m in sorted(inputs)]
                is_smelt = str(pr.get("kind") or "craft") == "smelt"
                if is_smelt:
                    tool = str(pr.get("tool") or "furnace")
                    pre.append({"type": "seen_or_have", "block": tool,
                                "item": tool})
                    pre.append({"type": "fuel"})
                elif pr.get("needs_table"):
                    pre.append({"type": "seen_or_have",
                                "block": "crafting_table",
                                "item": "crafting_table"})
                budget[0] -= 1
                if budget[0] < 0:
                    raise Unreachable(item, "BUDGET")
                steps.append({
                    "id": f"s{len(steps) + 1}",
                    "kind": "smelt" if is_smelt else "craft",
                    "action": ACTION_BY_KIND["smelt" if is_smelt else
                                              "craft"],
                    "target": item,
                    "params": {"item": item, "count": times},
                    "pre": pre,
                    "expect": [{"type": "have", "item": item,
                                "min_delta": yld * times}],
                    "justify": [f"{pr['recipe']}-[产生]->物品:{item}"],
                    "status": "pending", "attempts": 0, "evidence": [],
                })
                work[item] = work.get(item, 0) + yld * times
            return
        except Unreachable:
            del steps[base_n:]
            work.clear()
            work.update(base_work)
            raise

    def satisfy(item, need, depth, trail):
        if work.get(item, 0) >= need:
            return
        if item in trail:
            raise Unreachable(item, "CYCLE")
        if depth > int(cfg["max_depth"]):
            raise Unreachable(item, "DEPTH")
        if budget[0] <= 0:
            raise Unreachable(item, "BUDGET")
        opts = []
        for pr in wp.producers_of(kg, item):
            if key_of("craft", pr["recipe"], item) not in exclude:
                opts.append(("recipe", pr))
        for blk in wp.drop_sources(kg, item):
            if key_of("gather", blk, item) in exclude:
                continue
            if not _gatherable_strict(kg, blk):
                continue          # 不可采方块不进选项（严格；无保守放行）
            opts.append(("block", blk))
        if not opts:
            raise Unreachable(item, "NO_PRODUCER")

        def oscore(o):
            kind, payload = o
            nid = payload["recipe"] if kind == "recipe" else payload
            # provenance 读依据边（生产事实源在边上），节点 attrs 兜底
            _ok, verified = _option_verified(kind, payload,
                                             nid, item)
            if kind == "recipe":
                deps = len(payload["inputs"] or {})
            else:
                deps = len(wp.tool_required(kg, payload))
            return (0 if verified else 1, deps, str(nid))

        opts.sort(key=oscore)
        last = None
        for o in opts:
            try:
                _apply_option(o, item, need - work.get(item, 0),
                              depth, trail)
            except Unreachable as e:
                last = f"{e.item}:{e.why}"
                continue
            if work.get(item, 0) >= need:
                return
        raise Unreachable(item, last or "INSUFFICIENT_SUPPLY")

    try:
        satisfy(spec["item"], int(spec.get("count", 1)), 0, ())
    except Unreachable as e:
        return {"steps": [],
                "unreachable": {"item": e.item, "why": e.why},
                "excluded": sorted(exclude)}
    return {"steps": steps, "excluded": sorted(exclude)}


# ── 前置条件在当前观测上的成立判定（派发闸门 / 执行前重验）────────

def pre_holds(p, state):
    t = p.get("type")
    inv = state.get("inventory", {})
    seen = state.get("seen_blocks", set())
    if t == "have":
        return inv.get(p["item"], 0) >= int(p.get("count", 1))
    if t == "gatherable":
        return True     # 白名单已在规划期严格核验；现场可再核（kg 句柄不在
                        # 此处——派发时由 step_pre_holds(kg,…) 完整版判）
    if t == "fuel":
        import world_prior as wp
        name, _pieces = wp.best_fuel(inv, 1)
        return bool(name)
    if t == "seen_or_have":
        return (p.get("block") in seen) or (p.get("item") in inv
                                            and inv.get(p.get("item")) > 0)
    return False


def step_pre_holds(kg, step, state):
    for p in step.get("pre", []):
        if p.get("type") == "gatherable":
            if not _gatherable_strict(kg, p.get("block")):
                return False, p
        elif not pre_holds(p, state):
            return False, p
    return True, None


# ── tick：监测→推进/重规划→完成判定→单步派发（每拍唯一写者）────

def tick(kg, actions, state, config, engine=None, now=None):
    """闭环一拍（唯一写者）。顺序：读目标 → 监测已结算步（按当前观测核对
    预期效果）→ 达成收束(E) → 规划/重规划 → 环境失效(D) → 派发闸门。
    状态由调用方给（观测来源标记在 state["source"]），本函数不观察世界。"""
    cfg = _cfg(config)
    now = time.time() if now is None else now
    tele = {"status": "", "writes": 0, "dispatched": None, "notes": []}
    if not cfg["enabled"]:
        tele["status"] = "disabled"
        return tele
    gid, spec = current_goal_spec(kg)
    if not gid or not spec:
        tele["status"] = "NO_GOAL"
        return tele
    node = kg.nodes.get(gid)
    if node is None:
        tele["status"] = "NO_GOAL"
        return tele
    if not isinstance(node.extra_attrs, dict):
        node.extra_attrs = {}

    # 1) 监测先行：最后一步的结算事实要先入账，达成收束才能带上证据
    plan = node.extra_attrs.get("plan")
    if isinstance(plan, dict):
        _monitor(kg, node, plan, state, cfg, now, tele)

    # 2) E：目标条件被观测满足（无论来源）→ 收束计划、结束目标、零派发
    if goal_satisfied(spec, state):
        if isinstance(plan, dict):
            for s in plan.get("steps", []):
                if s.get("status") == "pending":
                    s["status"] = "cancelled_external"
            plan["outcome"] = "achieved"
            node.extra_attrs.setdefault("plan_history", []).append(
                {"plan_id": plan.get("plan_id"),
                 "revision": plan.get("revision"), "outcome": "achieved",
                 "ts": now})
        node.extra_attrs["plan"] = None
        from self_graph import clear_current_goal
        clear_current_goal(kg, achieved=True)
        tele["status"] = "GOAL_ACHIEVED"
        return tele

    # 3) 无计划 → 规划（revision 0）；不可达 = 可观测失败，不伪造
    if not isinstance(plan, dict):
        built = build_plan(kg, spec, state, cfg, exclude=set())
        if built.get("unreachable"):
            _terminate(kg, gid, "NO_FEASIBLE_PLAN:" +
                       f"{built['unreachable']['item']}:"
                       f"{built['unreachable']['why']}")
            tele["status"] = "NO_FEASIBLE_PLAN"
            tele["unreachable"] = built["unreachable"]
            return tele
        plan = _new_plan(gid, built, revision=0)
        node.extra_attrs["plan"] = plan
        tele["notes"].append(f"planned:{len(plan['steps'])}steps")

    # 4) D：环境意外变化 → pending 步骤前置逐一步重验，白名单失效者标废
    for s in plan["steps"]:
        if s.get("status") != "pending":
            continue
        for p in s.get("pre", []):
            if p.get("type") == "gatherable" and                     not _gatherable_strict(kg, p.get("block")):
                s["status"] = "invalidated"
                s["evidence"].append(
                    f"env_changed:gatherable_lost@{p.get('block')}")
                _exclude_option(plan, s)
                plan["needs_replan"] = True

    # 5) 计划穷尽但未达成（残差）→ 也触发重规划
    if all(s.get("status") in ("done", "invalidated", "cancelled",
                               "cancelled_external")
           for s in plan["steps"]):
        plan["needs_replan"] = True

    # 6) 重规划（revision 整体替换；失败选项已进 exclude，不得复发）
    if plan.get("needs_replan"):
        rev = int(plan.get("revision", 0)) + 1
        if rev > int(cfg["max_revisions"]):
            _terminate(kg, gid, "REVISION_BUDGET_EXCEEDED")
            tele["status"] = "GOAL_TERMINATED"
            return tele
        built = build_plan(kg, spec, state, cfg,
                           exclude=set(plan.get("excluded", [])))
        node.extra_attrs.setdefault("plan_history", []).append(
            {"plan_id": plan.get("plan_id"),
             "revision": plan.get("revision"),
             "outcome": "superseded", "excluded": list(
                 plan.get("excluded", [])), "ts": now})
        if built.get("unreachable"):
            _terminate(kg, gid, "NO_FEASIBLE_PLAN:" +
                       f"{built['unreachable']['item']}:"
                       f"{built['unreachable']['why']}")
            tele["status"] = "NO_FEASIBLE_PLAN"
            return tele
        plan = _new_plan(gid, built, revision=rev,
                         excluded=plan.get("excluded", []))
        node.extra_attrs["plan"] = plan
        tele["notes"].append(f"replanned:r{rev}")
        tele["revisions"] = rev

    # 7) 派发闸门：在飞步存在 → 不重复派发（去重/防旧新计划争抢）
    inflight = [s for s in plan["steps"]
                if s.get("status") in ("dispatched", "settled_ok",
                                       "settled_fail")]
    if inflight:
        tele["status"] = "INFLIGHT"
        return tele
    for s in plan["steps"]:
        if s.get("status") != "pending":
            continue
        ok, bad = step_pre_holds(kg, s, state)
        if not ok:
            tele["status"] = "WAIT_PRECOND"
            tele["blocked_on"] = bad
            return tele
        cand = _candidate(s, gid, plan, state)
        if actions is not None:
            actions.propose(cand, source="planner")
        s["status"] = "dispatched"
        s["attempts"] = int(s.get("attempts", 0)) + 1
        s["dispatched_pre"] = {"inventory": dict(
                                   state.get("inventory", {})),
                               "seen_blocks": list(
                                   state.get("seen_blocks", set())),
                               "ts": now}
        tele["status"] = "DISPATCHED"
        tele["dispatched"] = s["id"]
        tele["writes"] = 1
        return tele
    tele["status"] = "IDLE_WAIT"
    return tele


def maybe_tick(kg, actions, percept, config, engine=None):
    """生产接线入口：先查开关（关=零触碰），再构造状态视图。"""
    if not ((config or {}).get("planner") or {}).get("enabled"):
        return {"status": "disabled"}
    st = state_view(kg, percept)
    return tick(kg, actions, st, config, engine=engine)


def _new_plan(gid, built, revision=0, excluded=None):
    steps = built["steps"]
    for i, s in enumerate(steps):
        s["id"] = f"r{revision}:s{i + 1}"
    return {"plan_id": f"{gid}#r{revision}:{uuid.uuid4().hex[:6]}",
            "revision": revision, "steps": steps,
            "excluded": sorted(set(excluded or [])),
            "created_ts": time.time(), "history": []}


def _candidate(step, gid, plan, state):
    p = dict(step.get("params") or {})
    p.update({"step_id": step["id"], "plan_id": plan["plan_id"],
              "goal_id": gid})
    from graph_model import now_str
    return {"action_type": step["action"], "target": step.get("target"),
            "params": p,
            "motivation": "planned_goal",
            "expected_effect": _expect_text(step),
            "reason": [gid] + list(step.get("justify", [])),
            "priority": DEFAULTS["dispatch_priority"], "urgency": 0.6,
            "explain": f"计划 {plan['plan_id']} 步 {step['id']}",
            "timeout_s": 600.0 if step["kind"] == "gather" else None,
            "interruptible": step["kind"] != "gather"}


def _expect_text(step):
    e = (step.get("expect") or [{}])[0]
    return f"{step.get('target')}→+{e.get('min_delta', 1)} {e.get('item')}"


def _monitor(kg, node, plan, state, cfg, now, tele):
    """按当前观测核对已结算步骤（监测五分支 A/B/C/D/E 的落点）。"""
    changed = False
    for s in plan.get("steps", []):
        st = s.get("status")
        if st == "settled_ok":
            ok = _expect_met(s, state)
            if ok:
                s["status"] = "done"
                _record_evidence(kg, s, success=True, blame="", cfg=cfg)
                tele["notes"].append(f"step_done:{s['id']}")
            else:
                # 成功但预期未现：归因 观察/计划（不是行动本身失败）
                s["status"] = "failed"
                s["evidence"].append("success_without_expected_effect"
                                     f"@{now:.0f}")
                _record_evidence(kg, s, success=False,
                                 blame="plan", cfg=cfg)
                _exclude_option(plan, s)
                plan["needs_replan"] = True
                tele["notes"].append(f"step_no_effect:{s['id']}")
            changed = True
        elif st == "settled_fail":
            reason = str(s.pop("_settle_reason", "") or "fail")
            if reason in ("cooldown", "interrupted", "cancelled"):
                s["status"] = "pending"       # 未真正执行，不判失败
                changed = True
                continue
            if reason.startswith("block_not_found"):
                # D 分支：回执携带环境证据（图上白名单还在、世界已没有）
                # → 立即归因 environment、标废、排除选项、重规划（不空转重试）
                s["status"] = "invalidated"
                s["evidence"].append(f"env_evidence:{reason}")
                _record_evidence(kg, s, success=False,
                                 blame="environment", cfg=cfg)
                _exclude_option(plan, s)
                plan["needs_replan"] = True
                changed = True
                continue
            pre_ok, _bad = step_pre_holds(kg, s, state)
            if not pre_ok:
                # 前置在观测上已不成立 → 归因 环境/前提，标失效并重规划
                s["status"] = "invalidated"
                s["evidence"].append(f"pre_broken:{reason}")
                _record_evidence(kg, s, success=False,
                                 blame="environment", cfg=cfg)
                _exclude_option(plan, s)
                plan["needs_replan"] = True
            elif s.get("attempts", 1) <= int(cfg["step_retry_limit"]):
                s["status"] = "pending"        # 原地重试（前置仍成立）
                s["evidence"].append(f"retry:{reason}")
            else:
                s["status"] = "failed"         # 行动失败（前置成立）
                s["evidence"].append(f"action_failed:{reason}")
                _record_evidence(kg, s, success=False,
                                 blame="action", cfg=cfg)
                _exclude_option(plan, s)
                plan["needs_replan"] = True
            changed = True
    if changed:
        node.extra_attrs["plan"] = plan


def _expect_met(step, state):
    inv = state.get("inventory", {})
    pre = (step.get("dispatched_pre") or {}).get("inventory", {})
    for e in step.get("expect", []):
        if e.get("type") != "have":
            return False
        delta = int(inv.get(e["item"], 0) or 0) - \
            int(pre.get(e["item"], 0) or 0)
        if delta < int(e.get("min_delta", 1)):
            return False
    return True


def _exclude_option(plan, step):
    """失败/无效果的选项进 exclude 集：重规划不得重新选中（防死循环）。"""
    for j in step.get("justify", []):
        try:
            owner, rest = str(j).split("-[", 1)
            rel_dst = rest.split("]->", 1)
            if len(rel_dst) == 2:
                item = rel_dst[1].replace("物品:", "").strip()
                kind = ("craft" if "配方" in owner or "配方:" in j
                        else "gather")
                if rel_dst[0].startswith(("产生", "掉落")):
                    plan.setdefault("excluded", [])
                    if f"{kind}:{owner}->{item}" not in plan["excluded"]:
                        plan["excluded"].append(f"{kind}:{owner}->{item}")
        except Exception:
            continue


# ── 执行回执入口（挂在 ActionManager.on_settled 链上）─────────────

def on_settled(kg, action, result, success, config=None):
    """把结算**事实**写到计划步骤上；判定（A/B/C/D）推迟到下一拍
    tick——因为"预期效果是否出现"要等新观测，不能在回执瞬间下结论。
    B 分支（仍在执行/结果不可判）由 ActionManager 自身机制承担，
    本函数不会被调用（running/pending 不结算）。"""
    if not ((config or {}).get("planner") or {}).get("enabled"):
        return
    params = action.get("params") or {}
    step_id = params.get("step_id")
    plan_id = params.get("plan_id")
    gid = params.get("goal_id")
    if not step_id or not gid:
        return
    node = kg.nodes.get(gid)
    plan = (node.extra_attrs or {}).get("plan") if node else None
    if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
        return       # 旧计划回执：忽略（新计划已接管，防旧计划争抢）
    for s in plan.get("steps", []):
        if s.get("id") == step_id and s.get("status") == "dispatched":
            if success and not (result or {}).get("cancelled"):
                s["status"] = "settled_ok"
            else:
                s["status"] = "settled_fail"
                s["_settle_reason"] = str((result or {}).get("reason")
                                          or "fail")[:80]
            node.extra_attrs["plan"] = plan
            return


def revalidate(kg, action, state, config=None):
    """ActionManager.revalidate 链上的计划闸门：队首步骤出队前按
    当前状态重验前置；不成立 → 返回 None 丢弃（autonomy 既有 P1b 语义）。"""
    if not ((config or {}).get("planner") or {}).get("enabled"):
        return action
    params = action.get("params") or {}
    step_id = params.get("step_id")
    gid = params.get("goal_id")
    if not step_id or not gid:
        return action
    node = kg.nodes.get(gid)
    plan = (node.extra_attrs or {}).get("plan") if node else None
    if not isinstance(plan, dict) or \
            plan.get("plan_id") != params.get("plan_id"):
        return None
    for s in plan.get("steps", []):
        if s.get("id") == step_id:
            ok, _bad = step_pre_holds(kg, s, state)
            if ok:
                return action
            s["status"] = "invalidated"
            s["evidence"].append("dropped_at_queue:pre_broken")
            plan["needs_replan"] = True
            node.extra_attrs["plan"] = plan
            return None
    return action


# ── 目标终止与证据 ────────────────────────────────────────

def _terminate(kg, gid, reason):
    node = kg.nodes.get(gid)
    if node is not None:
        if not isinstance(node.extra_attrs, dict):
            node.extra_attrs = {}
        plan = node.extra_attrs.get("plan")
        if isinstance(plan, dict):
            for s in plan.get("steps", []):
                if s.get("status") in ("pending", "dispatched",
                                       "settled_ok", "settled_fail"):
                    s["status"] = "cancelled"
            plan["outcome"] = f"terminated:{reason}"
            node.extra_attrs.setdefault("plan_history", []).append(
                {"plan_id": plan.get("plan_id"),
                 "revision": plan.get("revision"),
                 "outcome": reason, "ts": time.time()})
        node.extra_attrs["plan"] = None
        node.extra_attrs["termination"] = reason
        node.touch()
    from self_graph import clear_current_goal
    clear_current_goal(kg, achieved=False)


def _record_evidence(kg, step, success, blame, cfg):
    """定向、最小、可追溯：只更新该步依据指向的配方/方块节点计数。
    绝不写 edge.weight / edge.activation；绝不无差别降级经过的边。"""
    if not cfg.get("evidence_enabled", True):
        return
    owners = set()
    for j in step.get("justify", []):
        owner = str(j).split("-[", 1)[0].strip()
        if owner:
            owners.add(owner)
    for o in owners:
        n = kg.nodes.get(o)
        if n is None or not isinstance(n.extra_attrs, dict):
            continue
        ea = n.extra_attrs
        if success:
            ea["plan_success_count"] = \
                int(ea.get("plan_success_count", 0)) + 1
        else:
            ea["plan_fail_count"] = int(ea.get("plan_fail_count", 0)) + 1
            ea["plan_last_blame"] = blame
        ea["plan_last_outcome_ts"] = time.time()
        n.touch()
