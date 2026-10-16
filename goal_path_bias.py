# goal_path_bias.py — 目标导向路径强化机制（候选机制实验实现）
# ============================================================================
# 机制（审计报告 docs/audits/GOAL_PATH_AUDIT_2026-10-09.md / 设计
# experiments/goal_path_bias/DESIGN.md）：
#   当 self_graph 存在明确"当前目标"时，在**可执行语义关系白名单**上从目标
#   锚点反向搜索到当前状态锚点（背包/可采资源叶子）的候选路径，并按路径
#   质量对路径节点施加**临时激活偏置**（直写 node.activation + mark_active），
#   交现有 Top-k/决策消费者。
#
# 硬约束（设计原则，违者即 bug）：
#   1. 默认关闭：config["goal_path"]["enabled"]=False 时本模块零写入，
#      生产行为逐位不变。
#   2. 不永久修改长期边权：只写节点激活；edge.weight / edge.activation
#      绝不触碰。偏置随现有 decay_step 自然消退，另有显式 clear 通道。
#   3. 不把普通语义关联伪装成可执行路径：白名单只含 world_prior 使用的
#      状态转换关系（产生/需要/掉落/需要工具/属于→可采资源/拥有）；
#      关联/关于/涉及/参与/表达方式 等一律不得进入路径。
#   4. search 与 bias 可独立消融：search=只读审计（零激活写入）；
#      bias 依赖 search；search=off & bias=on 是非法组合（显式报错）。
#   5. 可执行性检查（require_state_anchor）独立开关：B 条件不检查叶子
#      是否落在真实状态锚点（允许部分路径被偏置），C 条件只偏置
#      全叶可落地的推导树——这是 B/C 的唯一差别。
#   6. 失败证据不被屏蔽：被偏置节点若邻接负权 结果 边，只记录冲突遥测。
#
# 复用件（不重复实现读边语义）：world_prior.producers_of / drop_sources /
# tool_required；self_graph.current_goal / SELF_ID。
# ============================================================================

import logging
import time

from graph_model import Edge  # noqa: F401  (仅类型语境引用)

logger = logging.getLogger(__name__)

# 可执行语义白名单（B.3 审计裁决：仅这些边承载状态转换）
EXEC_RELATIONS = ("产生", "需要", "掉落", "需要工具", "属于", "拥有")
GATHERABLE_CATEGORY = "可采资源"          # mc_knowledge / world_prior 同一口径

DEFAULTS = {
    "enabled": False,          # 总开关（默认关）
    "search": False,           # 路径搜索+遥测记录（只读）
    "bias": False,             # 激活偏置（依赖 search）
    "require_state_anchor": False,  # C 条件：可执行性检查（依赖 bias）
    "max_hops": 8,             # 与 world_prior.MAX_DEPTH 对齐
    "max_paths": 3,            # 每层候选生产者/来源数上限
    "max_nodes": 12,           # 单次推导的节点预算（含未采用分支）
    "bias_floor": 0.9,         # 距目标 0 跳的偏置地板（autonomy §9 同值先例）
    "bias_gamma": 0.6,         # 每跳衰减
    "min_confidence": 0.5,     # C 条件 provenance 下限
}

# 活跃句柄：id(kg) → handle（同图重复应用先清除旧偏置，防止跨 tick 叠加）
_ACTIVE: dict = {}


class ConfigError(ValueError):
    pass


def _cfg(config: dict) -> dict:
    c = dict(DEFAULTS)
    c.update((config or {}).get("goal_path") or {})
    if c["bias"] and not c["search"]:
        raise ConfigError("goal_path: bias 依赖 search（off+on 是非法组合）")
    if c["require_state_anchor"] and not c["bias"]:
        raise ConfigError("goal_path: require_state_anchor 依赖 bias")
    return c


def _bare(name: str) -> str:
    s = str(name or "")
    return s[3:] if s.startswith("物品:") else s


def _item_id(name: str) -> str:
    return f"物品:{_bare(name)}"


# ── 当前状态锚点（背包：Self/Haru-[拥有]->物品:x）──────────────────

def owned_items(kg) -> dict:
    """{bare_name: n_edges}，图面上"已拥有"的物品集合（背包的图镜像）。
    主语认两个身份：self_graph 的 SELF_ID（"Self"）与具身层的 "Haru"
    （minecraft/perception.py:90 写 拥有 边用的就是它）；其他实体
    （村民-[拥有]->…）不算我的背包。"""
    from self_graph import SELF_ID
    subjects = {str(SELF_ID), "Haru"}
    inv = {}
    for e in kg.edges:
        if e.relation == "拥有" and str(e.src) in subjects:
            inv[_bare(e.dst)] = inv.get(_bare(e.dst), 0) + 1
    return inv


def gatherable(kg, block: str) -> bool:
    """block-[属于]->可采资源（world_prior._gatherable_block 同一判据，
    但查询异常按"不可采"处理——审计/实验代码保守失败，不冒充执行层兜底）。"""
    try:
        return kg.get_edge(str(block or "").split(":", 1)[-1],
                           GATHERABLE_CATEGORY, "属于") is not None
    except Exception:
        return False


# ── 路径搜索：目标反向推导树（复用 world_prior 读 API）──────────────

def resolve_target(kg, goal: dict) -> tuple:
    """current_goal 指针 → 目标锚点。返回 (kind, node_id_or_name, reason)。
    kind: item（物品:X 子串匹配，autonomy._obtain_goals 同一口径）| none。"""
    desc = str((goal or {}).get("desc") or "")
    if not desc:
        return "none", None, "NO_TARGET"
    hits = []
    for nid in kg.nodes:
        s = str(nid)
        if not s.startswith("物品:"):
            continue
        tgt = s[3:]
        if tgt and (tgt in desc or tgt.lower() in desc.lower()):
            hits.append(s)
    if hits:
        hits.sort(key=len)
        return "item", hits[0], f"MATCH {desc!r}→{hits[0]}"
    return "none", None, f"NO_ITEM_TARGET {desc!r}"


def search_goal_path(kg, cfg: dict, target_id: str) -> dict:
    """从目标物品反向展开推导树。返回 derivation：
      nodes: {node_id: {hop, kind(item/recipe/block), terminals:[], edges_in}}
      leaves: [{item, status: owned|gatherable|unresolved, why}]
      edges: [(src, rel, dst, weight, confidence, verified_flags)]
      resolved: bool（全部叶子可落地）
    只读：不写任何节点/边。"""
    import world_prior as wp
    target_bare = _bare(target_id)
    inv = owned_items(kg)
    nodes = {}
    edges = []
    leaves = []
    budget = [int(cfg["max_nodes"])]
    hop_of = {}

    def _note(nid, hop, kind, via):
        if nid not in nodes:
            budget[0] -= 1
            nodes[nid] = {"hop": hop, "kind": kind, "via": [], "terminals": []}
            hop_of[nid] = hop
        nodes[nid]["via"].append(via)
        nodes[nid]["terminals"] = sorted(set(nodes[nid]["terminals"]))

    def _edge_info(src, rel, dst):
        e = None
        with kg._lock:
            for cand in kg.edges:
                if str(cand.src) == str(src) and cand.relation == rel \
                        and str(cand.dst) == str(dst):
                    e = cand
                    break
        w = float(getattr(e, "weight", 0.5)) if e is not None else 0.0
        ea = dict((getattr(e, "extra_attrs", None) or {}) if e else {})
        conf = ea.get("confidence")
        prov_ok = bool(ea.get("knowledge_type") or ea.get("source"))
        return w, conf, prov_ok

    def _expand(item, hop, trail):
        """item: 裸名。返回该子树是否全部落地（AND 语义）。"""
        nid = _item_id(item)
        if nid in trail:                     # 环：如实记 unresolved，不伪造
            leaves.append({"item": item, "status": "unresolved",
                           "why": "CYCLE"})
            return False
        if budget[0] <= 0:
            leaves.append({"item": item, "status": "unresolved",
                           "why": "BUDGET"})
            return False
        _note(nid, hop, "item", list(trail))
        if item in inv:                      # 背包已有 → 状态锚点落地
            nodes[nid]["terminals"].append("owned")
            leaves.append({"item": item, "status": "owned", "why": ""})
            return True
        if hop >= int(cfg["max_hops"]):
            leaves.append({"item": item, "status": "unresolved",
                           "why": "DEPTH"})
            return False
        trail2 = trail + (nid,)
        branch_ok = False
        options = []
        # 合成/熔炼路径：配方-产生->物品（wp.producers_of 只认 type=recipe 节点）
        for pr in wp.producers_of(kg, item):
            options.append(("craft", pr["recipe"], pr))
        # 采集路径：方块-掉落/产生->物品
        for blk in wp.drop_sources(kg, item):
            options.append(("gather", blk, None))
        options = options[: int(cfg["max_paths"])]
        if not options:
            leaves.append({"item": item, "status": "unresolved",
                           "why": "NO_PRODUCER"})
            return False
        for kind, src, pr in options:
            if kind == "craft":
                _note(src, hop + 1, "recipe", list(trail2))
                ok_inputs = True
                mats = pr["inputs"] if pr else {}
                if not mats:
                    # 有 产生 边但无可解析 需要 边：可执行性存疑，如实记录
                    leaves.append({"item": item, "status": "unresolved",
                                   "why": "RECIPE_NO_INPUTS"})
                    ok_inputs = False
                for mat in mats:
                    w, conf, prov = _edge_info(src, "需要", _item_id(mat))
                    ve = (conf is None or float(conf) >=
                          float(cfg["min_confidence"])) and prov
                    edges.append((src, "需要", _item_id(mat), w, conf, ve))
                    ok_inputs = _expand(mat, hop + 2, trail2) and ok_inputs
                w, conf, prov = _edge_info(src, "产生", _item_id(item))
                ve = (conf is None or float(conf) >=
                      float(cfg["min_confidence"])) and prov
                edges.append((src, "产生", _item_id(item), w, conf, ve))
                branch_ok = branch_ok or ok_inputs
            else:
                _note(src, hop + 1, "block", list(trail2))
                w, conf, prov = _edge_info(src, "掉落", _item_id(item))
                if kg.get_edge(str(src), GATHERABLE_CATEGORY, "属于") is None:
                    # 检查是否 产生 边来源（mc_species）
                    w2, conf2, prov2 = _edge_info(src, "产生", _item_id(item))
                    if w2:
                        w, conf, prov = w2, conf2, prov2
                edges.append((src, "produce_or_drop", _item_id(item),
                              w, conf, prov))
                tools_ok = True
                for t in wp.tool_required(kg, src):
                    w, conf, prov = _edge_info(src, "需要工具", t)
                    edges.append((src, "需要工具", _bare(t), w, conf, prov))
                    tools_ok = _expand(_bare(t), hop + 2, trail2) and tools_ok
                if gatherable(kg, src):
                    nodes[src]["terminals"].append("gatherable")
                    leaves.append({"item": item, "status": "gatherable",
                                   "why": f"@{src}"})
                    branch_ok = branch_ok or tools_ok
                else:
                    leaves.append({"item": item, "status": "unresolved",
                                   "why": f"BLOCK_NOT_GATHERABLE@{src}"})
                    branch_ok = branch_ok or False
        return branch_ok

    ok = _expand(target_bare, 0, ())
    seen = {}
    for s, r, d, w, conf, ve in edges:
        seen[(s, r, d)] = (s, r, d, w, conf, ve)
    uniq_edges = list(seen.values())
    return {"target": target_id, "nodes": nodes, "edges": uniq_edges,
            "leaves": leaves, "resolved": bool(ok),
            "n_nodes": len(nodes)}


def path_quality(derivation: dict) -> dict:
    n_leaves = max(1, len(derivation["leaves"]))
    resolved = sum(1 for l in derivation["leaves"]
                   if l["status"] in ("owned", "gatherable"))
    ws = [e[3] for e in derivation["edges"] if e[3]]
    confs = [float(e[4]) for e in derivation["edges"] if e[4] is not None]
    verified = all(bool(e[5]) for e in derivation["edges"]) \
        if derivation["edges"] else False
    return {"resolved_fraction": resolved / n_leaves,
            "min_edge_weight": min(ws) if ws else 0.0,
            "mean_confidence": (sum(confs) / len(confs)) if confs else None,
            "all_edges_verified": verified,
            "depth": max((v["hop"] for v in derivation["nodes"].values()),
                         default=0)}


def _bias_nodes(derivation, cfg) -> list:
    """返回 [(node_id, value, hop)]。B：所有被访问节点；
    C（require_state_anchor）：仅全叶落地推导中的节点。"""
    if cfg["require_state_anchor"] and not derivation["resolved"]:
        return []
    out = []
    floor = float(cfg["bias_floor"])
    gamma = float(cfg["bias_gamma"])
    budget = int(cfg["max_nodes"])
    ranked = sorted(derivation["nodes"].items(),
                    key=lambda kv: (kv[1]["hop"], str(kv[0])))
    for nid, meta in ranked[:budget]:
        v = floor * (gamma ** int(meta["hop"]))
        if v > 0.0:
            out.append((nid, v, meta["hop"]))
    return out


def _failure_conflicts(kg, node_ids) -> list:
    """被偏置节点邻接的负权 结果 边（失败证据）——只记录，不屏蔽。"""
    ids = set(node_ids)
    out = []
    for e in kg.edges:
        if float(getattr(e, "weight", 0.0)) < 0 and e.relation == "结果" \
                and (str(e.src) in ids or str(e.dst) in ids):
            out.append({"node": str(e.src) if str(e.src) in ids
                        else str(e.dst),
                        "edge": f"{e.src}-[结果({e.weight})]->{e.dst}"})
    return out


# ── 偏置施加与清除（唯一写通道：node.activation 直写 + mark_active）──

def apply_bias(kg, engine, plan, cfg):
    """plan=[(node_id,value,hop)]。返回 handle；重复应用同图先清除旧句柄。"""
    global _ACTIVE
    key = id(kg)
    prev = _ACTIVE.pop(key, None)
    if prev is not None:
        _restore(kg, engine, prev)
    written = []
    for nid, val, hop in plan:
        n = kg.nodes.get(nid)
        if n is None:
            continue
        if float(n.activation or 0.0) < val:
            written.append((nid, float(n.activation or 0.0), val, hop))
            n.activation = val
            n.touch()
    if engine is not None and written:
        try:
            engine.mark_active([w[0] for w in written])
        except Exception as e:
            logger.debug(f"[GoalPath] mark_active 失败: {e}")
    handle = {"kg": kg, "written": written, "ts": time.time(),
              "bias_floor": float(cfg["bias_floor"])}
    _ACTIVE[key] = handle
    return handle


def _restore(kg, engine, handle):
    ids = []
    for nid, old, new, _hop in handle["written"]:
        n = kg.nodes.get(nid)
        if n is None:
            continue
        # 只有当激活仍是我们写上去的水平（未被其它更强输入抬高）才回滚，
        # 否则会覆盖真实认知的写入
        if float(n.activation or 0.0) <= new + 1e-9:
            n.activation = old
            n.touch()
            ids.append(nid)
    if engine is not None and ids:
        try:
            engine.mark_active(ids)
        except Exception as e:
            logger.debug(f"[GoalPath] 清除时 mark_active 失败: {e}")
    return len(ids)


def clear_bias(kg, engine) -> int:
    """显式清除本模块在 kg 上施加的最近一次偏置。返回回滚节点数。"""
    handle = _ACTIVE.pop(id(kg), None)
    if handle is None:
        return 0
    return _restore(kg, engine, handle)


# ── 端到端入口 ────────────────────────────────────────────

def run_goal_path(kg, engine, config: dict, *, force: bool = False) -> dict:
    """读目标→搜路径→（可选）施加偏置，返回遥测 dict。
    disabled/NO_TARGET 等零副作用；非法开关组合抛 ConfigError。"""
    cfg = _cfg(config)
    if not cfg["enabled"]:
        return {"status": "disabled", "writes": 0}
    from self_graph import current_goal
    t0 = time.time()
    tele = {"status": "", "writes": 0, "goal": {}, "search_ms": 0.0,
            "bias_ms": 0.0, "conflicts": []}
    goal = current_goal(kg) or {}
    tele["goal"] = {"desc": goal.get("desc"), "state": goal.get("state")}
    kind, target, why = resolve_target(kg, goal)
    tele["resolve"] = why
    if kind != "item":
        tele["status"] = why
        return tele
    dv = search_goal_path(kg, cfg, target)
    q = path_quality(dv)
    tele["search_ms"] = (time.time() - t0) * 1000
    tele["derivation"] = {"target": dv["target"], "n_nodes": dv["n_nodes"],
                          "resolved": dv["resolved"],
                          "leaves": dv["leaves"],
                          "hops": {nid: m["hop"] for nid, m in
                                   dv["nodes"].items()}}
    tele["quality"] = q
    if dv["n_nodes"] <= 1:
        # 只有目标节点本身：要么背包已有（goal 达成，无需偏置），
        # 要么什么都没有（NO_PATH）——都不写激活
        tele["status"] = ("ALREADY_OWNED" if dv["resolved"] else "NO_PATH")
        return tele
    tele["status"] = "PATH" if dv["resolved"] else "PARTIAL_PATH"
    if not cfg["bias"]:
        return tele                          # search-only：审计模式，零写入
    plan = _bias_nodes(dv, cfg)
    tele["conflicts"] = _failure_conflicts(kg, [p[0] for p in plan])
    t1 = time.time()
    h = apply_bias(kg, engine, plan, cfg)
    tele["bias_ms"] = (time.time() - t1) * 1000
    tele["writes"] = len(h["written"])
    tele["biased"] = [(w[0], round(w[2], 4), w[3]) for w in h["written"]]
    return tele


def maybe_run(kg, engine, config: dict) -> dict:
    """生产接线入口：默认关（含 config 无 goal_path 节）时立即返回，
    不 import 任何重依赖、零副作用。异常由调用方兜底。"""
    gp = (config or {}).get("goal_path") or {}
    if not gp.get("enabled"):
        return {"status": "disabled", "writes": 0}
    return run_goal_path(kg, engine, config)
