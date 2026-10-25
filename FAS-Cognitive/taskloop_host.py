# taskloop_host.py — 通用任务闭环的生产宿主粘合层（阶段 B/C）
# ============================================================================
# 被 FAS-Companion app.py 的 process_nlp 在门控内调用（handle(text, ctx)）。
# 职责：意图→parse_goal→校验→按谓词命名空间路由到环境适配器→TaskLoop
# 每拍至多一个可核验行动→台账读取回答（进度不经 LLM 猜测）。
# 铁律：默认全关（config.taskloop.enabled=False → handle 立即 None=旧路径）；
# 路由不过滤即不执行；解析 reject/ask 绝不下发行动；适配器无匹配返回
# None（保持原路径，**不**错误路由到沙盒/文件）；恢复用台账的目标/约束，
# 与传入不符即拒（TaskLoop 内建）；新路径异常→如实报错，不回退到可能
# 违约束的旧执行器。
# ============================================================================
import hashlib
import json
import os
import re
import sys
import time

import taskloop as TL

_EXP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "experiments", "general_loop")
if _EXP not in sys.path:
    sys.path.insert(0, _EXP)

# 谓词命名空间 → 适配器（命名空间级路由，非关键词/任务硬编码）
NS_ROUTER = {"sandbox": ("at:agent", "at:", "have:", "slot:", "powered:",
                         "linked:", "exists:", "exists_fixture:"),
             "files": ("loc:", "dir_exists:"),
             "reading": ("read:", "next:", "reading_done")}

# 并发保护（2026-10-13 验收轮）：index/台账是读-改-写。回合线程 handle
# 与 poller idle_step 可能对同一任务并发步进 → 互相覆盖 env_state 与
# 台账。任务操作毫秒级（LLM 解析在回合线程不持锁等待……为简单与正确
# 取舍：整段 handle/idle_step/propose/drain 串行——写任务本就低频）。
import threading as _threading
_IO_LOCK = _threading.RLock()


def _cfg(ctx):
    return ((ctx or {}).get("config") or {}).get("taskloop") or {}


def _task_id(adapter, spec):
    h = hashlib.sha256(json.dumps(
        [adapter, sorted(spec["preds"]), spec.get("constraints")],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]
    return "task-" + adapter + "-" + h


def _index_path(ctx):
    return _cfg(ctx).get("index_path", "data/taskloop_tasks.json")


def _load_index(ctx):
    from json_store import load_json
    return load_json(_index_path(ctx), default=None) or {}


def _save_index(ctx, idx):
    from json_store import atomic_write_json
    atomic_write_json(_index_path(ctx), idx)


# ── 适配器工厂（state 持久化在 index 里；重建=确定性重建）──────────

def _route(spec):
    """所有目标谓词的命名空间必须一致命中单一适配器，否则不路由。"""
    hits = set()
    for p in spec["preds"]:
        ns = p.split(":")[0]
        for name, prefixes in NS_ROUTER.items():
            if any(p.startswith(x) for x in prefixes):
                hits.add(name)
                break
        else:
            return None, "unknown-namespace"
    if len(hits) != 1:
        return None, ("ambiguous" if hits else "none")
    return next(iter(hits)), "ok"


def _report_reply(rep):
    """回答只由台账/观测报告组装——零 LLM 猜测。"""
    st = rep["status"]
    line = {
        "active": "任务进行中",
        "completed": "任务完成（全部目标经观测核验）",
        "blocked": "任务受阻：当前环境与约束下无法继续",
        "partial": "部分完成：步数预算用尽，仍有未满足条件",
    }.get(st, st)
    return (f"{line}；已核验 {rep['met_by_observation']}/{rep['goals']} 项目标"
            + (f"；未满足：{rep['unmet'][:4]}" if rep["unmet"] else "")
            + f"；本任务累计行动 {rep['steps']} 步、"
            f"重规划 {rep['replans']} 次、无效 {rep['invalid_actions']} 次、"
            f"未核验 {rep['verify_misses']} 次")


_PROGRESS_RE = re.compile(r"任务(进度|状态|到哪)")
_CONTINUE_RE = re.compile(r"^继续任务")
_CANCEL_RE = re.compile(r"^(取消|停止|放弃)任务")
_APPROVE_RE = re.compile(r"^(批准|允许|同意)任务")
# MC 显式域（前缀与 sandbox 的 have: 有交集，自动路由会 ambiguous——
# 真实 MC 桥接入前，minecraft 域只走显式触发，不冒充通用路由已就绪）
_MC_RE = re.compile(r"^minecraft任务[：:]")
# 任务样预闸（P0 修复 2026-10-13）：此前每条聊天消息都付一次
# goal_parse LLM 调用（生产日志实锤，还有闲聊被解析成任务截胡回复）。
# 只有命中"祈使/行动+对象"特征的消息才值得结构化；漏报可接受
# （用户可换说法或显式前缀），误报由解析的 reject/ask 兜住。
_TASKLIKE_RE = re.compile(
    r"^(把|将|帮|请|麻烦|去|将)"
    r"|(搬到|移到|移动到|挪到|放到|复制到|归档|整理|改名|创建|下载到"
    r"|收集|采集|清点|移到|移入|移出)"
    r"|^(任务|新任务|minecraft任务)[：:]")


def _set_status(ctx, idx, tid, status, ledger_path):
    """取消/批准共用：index 与台账同步改状态（不新增第二处存储）。"""
    from json_store import load_json, atomic_write_json
    idx[tid]["status"] = status
    data = load_json(ledger_path, default=None) or {}
    if tid in data:
        data[tid]["status"] = status
        atomic_write_json(ledger_path, data)
    _save_index(ctx, idx)


def _open_task(idx, status="active"):
    tids = [k for k, v in idx.items() if v.get("status") == status]
    return tids[0] if tids else None     # FIFO：先开的任务先推进


def handle(text, ctx):
    """返回 None=本模块不介入（旧路径原样）；dict=已处理。"""
    cfg = _cfg(ctx)
    if not cfg.get("enabled"):
        return None
    try:
        with _IO_LOCK:
            return _handle(text, ctx, cfg)
    except Exception as e:
        # 新路径故障绝不静默回退旧执行器（可能违约束）——如实报错
        return {"kind": "error",
                "reply": "任务闭环内部故障（未回退旧路径）: " + repr(e)[:160]}


def _handle(text, ctx, cfg):
    from json_store import load_json, atomic_write_json
    t = str(text or "").strip()
    ledger_path = cfg.get("ledger_path", "data/taskloop_ledger.json")
    idx = _load_index(ctx)
    allowed_adapters = set(cfg.get("adapters") or [])

    # 0) 取消任务（用户主权：取消后不再推进，也不"顺手复活"）
    if _CANCEL_RE.match(t):
        tid = _open_task(idx, "active") or _open_task(idx, "pending_approval")
        if not tid:
            return {"kind": "progress", "reply": "没有进行中的任务可取消。"}
        _set_status(ctx, idx, tid, "cancelled", ledger_path)
        return {"kind": "cancelled", "task_id": tid,
                "reply": "好，任务已取消，不再推进。"}

    # 0b) 批准任务（propose 的候选只有经批准才进入执行）
    if _APPROVE_RE.match(t):
        # 对话前景原则：批准的是她**最近向你提出**的候选，不是积压最久的
        _pend = [k for k, v in idx.items()
                 if v.get("status") == "pending_approval"]
        tid = _pend[-1] if _pend else None
        if not tid:
            return {"kind": "progress", "reply": "没有等待批准的任务。"}
        entry = idx[tid]
        if entry.get("spec"):
            # propose 而来的任务：批准时才构建环境并登记台账（构造本身
            # 有建立工作目录等副作用，绝不在未批准时发生）
            spec = entry["spec"]
            if entry.get("adapter") not in set(
                    (cfg.get("adapters") or [])):
                return {"kind": "blocked",
                        "reply": "批准失败：所需执行域『%s』未启用。"
                                 % entry.get("adapter")}
            env = _build_env(entry["adapter"], spec, ctx)
            if env is None:
                idx[tid]["status"] = "blocked"
                _save_index(ctx, idx)
                return {"kind": "blocked",
                        "reply": "批准失败：环境构建不成（不猜测执行）。"}
            TL.TaskLoop(env, tid, ledger_path, spec["preds"],
                        spec.get("constraints"))
            entry["env_state"] = _env_state(env)
        # 用户显式批准=授权自主步进；autopilot 总闸关时仅放行带此标的任务
        # （直接命令型任务没有此标，维持"回合内步进"的旧行为）
        entry["approved_by_user"] = True
        _set_status(ctx, idx, tid, "active", ledger_path)
        return {"kind": "approved", "task_id": tid,
                "reply": "收到批准，任务开始推进（下一拍一步）。"}

    # 1) 进度查询：读台账，零 LLM
    if _PROGRESS_RE.search(t):
        tid = _open_task(idx, "active") or _open_task(
            idx, "pending_approval")
        if not tid:
            return {"kind": "progress", "reply": "没有进行中的任务。"}
        if idx[tid].get("status") == "pending_approval":
            return {"kind": "progress",
                    "reply": "有一个待批准的任务：%s（说「批准任务」开始）"
                             % str((idx[tid].get("utterance") or ""))[:60]}
        rec = (load_json(ledger_path, default=None) or {}).get(tid)
        if not rec:
            return {"kind": "progress",
                    "reply": "台账缺失（索引与账本不一致，已如实报告）"}
        env = _rebuild_env(idx[tid], ctx)
        if env is None:
            return {"kind": "progress",
                    "reply": "任务台账在，但执行环境暂无法重建"
                             "（适配器缺状态恢复；不谎报）。"}
        loop = TL.TaskLoop(env, tid, ledger_path, rec["goals"],
                           rec.get("constraints"))
        return {"kind": "progress", "reply": _report_reply(loop.report())}

    # 2) 继续任务：恢复正确 task_id/目标/约束 → 一拍一步
    if _CONTINUE_RE.match(t):
        tid = _open_task(idx, "active")
        if not tid:
            return {"kind": "progress", "reply": "没有待续任务。"}
        rec = (load_json(ledger_path, default=None) or {}).get(tid)
        env = _rebuild_env(idx[tid], ctx)
        if env is None:
            return {"kind": "blocked",
                    "reply": "无法从台账重建执行环境（不重复盲执行）。"}
        loop = TL.TaskLoop(env, tid, ledger_path, rec["goals"],
                           rec.get("constraints"))
        d = None
        for _ in range(max(1, int(cfg.get("max_actions_per_turn", 1)))):
            d = loop.step()
            if d in ("COMPLETED", "BLOCKED", "PARTIAL"):
                break
        idx[tid]["status"] = ("active" if d in ("CONTINUE", "REPLAN")
                              else loop.rec["status"])
        # env_state 必须回写（2026-10-13 修复：此前不写→每次"继续任务"都
        # 回滚到旧环境重放，永远走不完多步任务——见测试 T5b）
        idx[tid]["env_state"] = _env_state(env)
        _save_index(ctx, idx)
        return {"kind": "task", "task_id": tid,
                "status": loop.rec["status"],
                "terminal": loop.rec["status"] in ("completed", "blocked",
                                                   "partial"),
                "report": loop.report(),
                "reply": _report_reply(loop.report())}

    # 3) 新任务：预闸 → 异步通道排队（语音/回合不阻塞）或同步处理（文本）
    #    （P0 2026-10-13：无预闸时每条聊天都付一次 goal_parse 调用，
    #     且有闲聊被解析成任务后截胡回复——只放行"任务样"消息。
    #     P0.8：goal_parse 30-70s，绝不进语音回合的同步路径。）
    mc_explicit = bool(_MC_RE.match(t))
    if not mc_explicit and not _TASKLIKE_RE.search(t):
        return None
    if not cfg.get("parse_enabled") or ctx.get("nlp") is None:
        return None
    if ctx.get("queue_async"):
        return _enqueue_goal(t, ctx)
    return _start_new_task(t, ctx, cfg, mc_explicit)


def _start_new_task(t, ctx, cfg, mc_explicit=False):
    """新任务处理核：解析→校验→路由→起步（同步一步）。"""
    from json_store import load_json
    ledger_path = cfg.get("ledger_path", "data/taskloop_ledger.json")
    idx = _load_index(ctx)
    allowed_adapters = set(cfg.get("adapters") or [])
    parse_input = t.split("：", 1)[-1] if mc_explicit else t

    def _call(u):
        return ctx["nlp"].ask("goal_parse", u)
    spec, verdict, errs = TL.parse_goal(_call, parse_input)
    if verdict == "reject":
        return {"kind": "reject",
                "reply": "无法把这句话安全结构化为任务目标（"
                         + "；".join(errs) + "），不执行。"}
    if verdict == "ask":
        return {"kind": "ask", "reply": "需要先确认："
                 + "；".join(spec["questions"])}
    if mc_explicit:
        # 显式域：谓词必须全部落在 mc 词表，否则拒绝（不借道其它域）
        if not all(p.split(":")[0] in ("have", "block", "table")
                   for p in spec["preds"]):
            return {"kind": "reject",
                    "reply": "minecraft任务的目标谓词不在该域词表内，不执行。"}
        adapter, why = "minecraft", "ok"
    else:
        adapter, why = _route(spec)
    if adapter is None:
        return None if why == "unknown-namespace" else {
            "kind": "ask", "reply": "这条指令同时匹配多个执行域，请澄清。"}
    if adapter == "reading":
        return {"kind": "blocked", "reply": "阅读任务请使用阅读通道"
                                            "（『继续读』/reader 台账）。"}
    if adapter not in allowed_adapters:
        return {"kind": "blocked",
                "reply": f"该任务需要『{adapter}』执行域，当前未启用"
                         f"（config.taskloop.adapters），不擅自执行。"}
    env = _build_env(adapter, spec, ctx)
    if env is None:
        return {"kind": "blocked",
                "reply": f"『{adapter}』执行域已启用但环境构建失败"
                         f"（不猜测执行）。"}
    tid = _task_id(adapter, spec)
    loop = TL.TaskLoop(env, tid, ledger_path, spec["preds"],
                       spec.get("constraints"))
    d = None
    for _ in range(max(1, int(cfg.get("max_actions_per_turn", 1)))):
        d = loop.step()
        if d in ("COMPLETED", "BLOCKED", "PARTIAL"):
            break
    rep = loop.report()
    idx[tid] = {"adapter": adapter, "status": rep["status"],
                "env_state": _env_state(env)}
    _save_index(ctx, idx)
    return {"kind": "task", "task_id": tid, "status": rep["status"],
            "terminal": rep["status"] in ("completed", "blocked", "partial"),
            "report": rep,
            "reply": _report_reply(rep)}


# ── 环境构造/重建（状态可持久 = index 里 env_state）───────────

def _build_env(adapter, spec, ctx):
    cfg = _cfg(ctx)
    if adapter == "files":
        from file_env import FileEnv
        root = cfg.get("files_workspace", "data/task_workspace")
        dirs = sorted({p.split(":")[2] for p in spec["preds"]
                       if p.startswith("loc:") and len(p.split(":")) == 3}
                      | {"inbox"})
        return FileEnv.from_disk(root, dirs)
    if adapter == "sandbox":
        from sandbox_env import RoomWorld
        sd = cfg.get("sandbox_def") or {}
        return RoomWorld(rooms=sd.get("rooms", ["entry", "storage",
                                                "workshop"]),
                         links=sd.get("links", {"entry": ["storage"],
                                                "storage": ["workshop"]}),
                         items=sd.get("items", {}),
                         capacity=int(sd.get("capacity", 3)),
                         fixtures=sd.get("fixtures"))
    if adapter == "minecraft":
        from mc_env import McTaskEnv
        kw = _mc_kwargs(spec, cfg)
        env = McTaskEnv(**kw)
        env._haru_kw = kw          # env_state 需携带构造参数供恢复
        return env
    if adapter == "reading":
        return None    # 阅读走 reader 台账通道（宿主 reader 块），
                       # 不在本层重复建设取单元执行器
    return None


def _mc_kwargs(spec, cfg):
    """minecraft 域构造参数：目标物品/世界方块来自 spec，起始物品
    来自 constraints（白名单语义：不虚构补给）。"""
    items, blocks = [], []
    for p in spec["preds"]:
        if p.startswith("have:"):
            items.append(p.split(":")[1].split("#")[0])
        elif p.startswith("block:"):
            blocks.append(p.split(":")[1])
    cons = spec.get("constraints") or {}
    md = cfg.get("mc_def") or {}
    return {"target": items[0] if items else None,
            "seed_items": list(cons.get("seed_items")
                               or md.get("seed_items") or ()),
            "blocks": blocks or md.get("blocks") or []}


def _env_state(env):
    st = env.state() if hasattr(env, "state") else None
    kw = getattr(env, "_haru_kw", None)
    return {"kw": kw, "st": st} if kw is not None else st


def _rebuild_env(entry, ctx):
    adapter = entry.get("adapter")
    st = entry.get("env_state")
    if adapter == "sandbox" and st is not None:
        from sandbox_env import RoomWorld
        base = (_cfg(ctx).get("sandbox_def") or {})
        return RoomWorld.restore(base, st)
    if adapter == "files" and st is not None:
        from file_env import FileEnv
        return FileEnv.restore(st)
    if adapter == "minecraft" and isinstance(st, dict) \
            and st.get("kw") is not None and st.get("st") is not None:
        from mc_env import McTaskEnv
        env = McTaskEnv.restore(st["kw"], st["st"])
        env._haru_kw = st["kw"]          # 保 kw，后续步进回写不丢
        return env
    return None


# ── 自主候选目标（P1）与背景步进（P0）───────────────────────────────

def propose_goal(ctx, utterance, source="haru"):
    """自主模块（生活循环/认知层）提交候选目标：走**同一条**
    解析/校验/路由/白名单管线，但只进入 pending_approval——未经用户
    批准绝不执行任何行动（权限边界不因来源改变）。

    返回 None=不该出现（模块关）；dict=结果（proposed/skipped/dupe）。"""
    cfg = _cfg(ctx)
    if not cfg.get("enabled") or not cfg.get("parse_enabled") \
            or ctx.get("nlp") is None:
        return None
    try:
        def _call(u):
            return ctx["nlp"].ask("goal_parse", u)
        spec, verdict, errs = TL.parse_goal(_call, utterance)
        if verdict != "ok":
            return {"kind": "propose_skipped", "why": verdict,
                    "errs": errs[:2]}
        adapter, why = _route(spec)
        if adapter is None or adapter == "reading":
            return {"kind": "propose_skipped",
                    "why": "route:" + str(why or "reading")}
        if adapter not in set(cfg.get("adapters") or []):
            return {"kind": "propose_skipped",
                    "why": "adapter_not_allowed:" + adapter}
        tid = _task_id(adapter, spec)
        idx = _load_index(ctx)
        if tid in idx:
            return {"kind": "propose_dupe", "task_id": tid,
                    "status": idx[tid].get("status")}
        idx[tid] = {"adapter": adapter, "status": "pending_approval",
                    "source": str(source)[:40],
                    "utterance": str(utterance)[:200],
                    "spec": {"preds": spec["preds"],
                             "constraints": spec.get("constraints") or {}},
                    "env_state": None}
        _save_index(ctx, idx)
        return {"kind": "proposed", "task_id": tid, "adapter": adapter,
                "preds": spec["preds"],
                "reply": "我想试个任务：%s——说「批准任务」我就开始，"
                         "说「取消任务」就作罢。" % str(utterance)[:60]}
    except Exception as e:                        # noqa: BLE001
        return {"kind": "propose_error", "why": repr(e)[:120]}


def idle_step(ctx):
    """空闲一拍：把最早的活动任务推进**一步**（由宿主 poller 调用）。

    硬闸：taskloop.enabled；步进资格=autopilot_enabled（全量自主，默认关
    =新权限不擅自打开）**或**该任务被用户显式批准过（approved_by_user——
    批准即授权，批准了的候选必须在空闲拍真正跑起来，否则"收到批准"是空头
    支票）。ctx["busy"]() 真（用户交互中）→ 让位不推进。
    有界性由 TaskLoop 自身保证（step_cap/失败拉黑/重规划计数）。
    返回 None=无事发生；dict=本拍报告（terminal 标记供宿主做经验写回
    与分享，频率天然受"只在终态"限制）。"""
    cfg = _cfg(ctx)
    if not cfg.get("enabled"):
        return None
    busy = ctx.get("busy")
    if callable(busy) and busy():
        return None
    try:
        from json_store import load_json
        idx = _load_index(ctx)
        autopilot = bool(cfg.get("autopilot_enabled"))
        tid = None
        for k, v in idx.items():                     # FIFO：先开的先推进
            if v.get("status") == "active" and (
                    autopilot or v.get("approved_by_user")):
                tid = k
                break
        if not tid:
            return None
        ledger_path = cfg.get("ledger_path", "data/taskloop_ledger.json")
        rec = (load_json(ledger_path, default=None) or {}).get(tid)
        env = _rebuild_env(idx[tid], ctx)
        if not rec or env is None:
            idx[tid]["status"] = "blocked"
            idx[tid]["status_reason"] = "idle_rebuild_failed"
            _save_index(ctx, idx)
            return {"kind": "step", "task_id": tid, "decision": "BLOCKED",
                    "terminal": True,
                    "reply": "环境/台账不可重建，任务已置为受阻（不盲跑）。",
                    "report": None}
        loop = TL.TaskLoop(env, tid, ledger_path, rec["goals"],
                           rec.get("constraints"))
        d = loop.step()
        idx[tid]["status"] = ("active" if d in ("CONTINUE", "REPLAN")
                              else loop.rec["status"])
        idx[tid]["env_state"] = _env_state(env)
        _save_index(ctx, idx)
        return {"kind": "step", "task_id": tid, "decision": d,
                "terminal": d in ("COMPLETED", "BLOCKED", "PARTIAL"),
                "reply": _report_reply(loop.report()),
                "report": loop.report()}
    except Exception as e:                        # noqa: BLE001
        return {"kind": "step_error", "reply": repr(e)[:160]}


# ── 异步任务队列（P0.8：goal_parse 30-70s，绝不进语音/聊天回合的同步路径）──

def _queue_path(ctx):
    return _cfg(ctx).get("queue_path", "data/taskloop_queue.json")


def _enqueue_goal(t, ctx):
    """把任务样消息排入后台队列，立即返回轻量确认（不解析、不执行）。
    用户明确交代 = 授权来源：drain 时校验通过即进 active，无需再批准
    （与自主候选 propose→pending_approval 的权限层级不同）。"""
    from json_store import load_json, atomic_write_json
    q = load_json(_queue_path(ctx), default=None) or []
    q.append({"text": str(t)[:300], "ts": time.time(), "status": "pending"})
    atomic_write_json(_queue_path(ctx), q)
    return {"kind": "queued", "task_id": None, "terminal": False,
            "reply": "好，这个任务我记下了——先想清楚怎么做，进展我随时跟你说。"}


def drain_queue(ctx):
    """宿主 poller 调用：消费一条排队目标（解析=LLM 调用，一拍一条限速）。

    返回处理结果列表（宿主据此做经验写回/澄清分享）；队列文件里该条
    标 done+result（幂等，重启不重解析）。"""
    cfg = _cfg(ctx)
    if not cfg.get("enabled"):
        return []
    with _IO_LOCK:
        from json_store import load_json, atomic_write_json
        qp = _queue_path(ctx)
        q = load_json(qp, default=None) or []
        todo = next((x for x in q if x.get("status") == "pending"), None)
        if todo is None:
            return []
        todo["status"] = "processing"
        atomic_write_json(qp, q)
        text = str(todo.get("text", ""))
        mc = bool(_MC_RE.match(text))
        try:
            res = _start_new_task(text, ctx, cfg, mc)
        except Exception as e:                    # noqa: BLE001
            res = {"kind": "error", "terminal": False,
                   "reply": "后台起步失败（不重试风暴）：" + repr(e)[:120]}
        # 起步后连推至终态（上限 drain_max_steps，默认 4）：否则
        # autopilot 关着时"核验完成"这类只差一步确认的任务会永远挂
        # active，等用户手动续——队列起步本就该交付一个交代。
        if (res or {}).get("kind") == "task" and not res.get("terminal"):
            from json_store import load_json as _lj
            tid = res["task_id"]
            ledger_path = cfg.get("ledger_path", "data/taskloop_ledger.json")
            idx = _load_index(ctx)
            rec = (_lj(ledger_path, default=None) or {}).get(tid)
            env = _rebuild_env(idx.get(tid, {}), ctx)
            if rec and env is not None:
                loop = TL.TaskLoop(env, tid, ledger_path, rec["goals"],
                                   rec.get("constraints"))
                for _ in range(max(0, int(cfg.get("drain_max_steps", 4)) - 1)):
                    d = loop.step()
                    if d in ("COMPLETED", "BLOCKED", "PARTIAL"):
                        break
                idx[tid]["status"] = ("active" if d in ("CONTINUE", "REPLAN")
                                      else loop.rec["status"])
                idx[tid]["env_state"] = _env_state(env)
                _save_index(ctx, idx)
                rep = loop.report()
                res = {"kind": "task", "task_id": tid, "status": rep["status"],
                       "terminal": rep["status"] in ("completed", "blocked",
                                                     "partial"),
                       "report": rep, "reply": _report_reply(rep)}
        todo["status"] = "done"
        todo["result_kind"] = (res or {}).get("kind")
        atomic_write_json(qp, q)
        if res is not None:
            res["from_queue"] = True
            return [res]
    return []
