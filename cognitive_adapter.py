# -*- coding: utf-8 -*-
"""cognitive_adapter — 陪伴层↔认知层的最小稳定入口（P4）。

原则（实施任务 §P4）：
  · FAS-Cognitive 是能力提供方，本模块只是**薄门面**：动态调用已 import
    的真实生产对象（cc/autonomy/goal_planner/reading/temporal/self_graph），
    不复制认知逻辑、不重写底层、不发起架构改造；
  · 每个入口 = (能力名, 方法名) 白名单；未接线的认知机制（goal_planner
    tick、memrep、taskloop、参考管线）如实标注 mode（flag_off/unwired），
    绝不假装在用；
  · 错误隔离：能力炸了返回 {"ok": False, "error": ...} + reason，
    Haru 照 commonly 聊天/发声/显示形象；失败记日志不静默。
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("cognitive_adapter")


class CognitiveAdapter:
    """组件注册表 + 白名单调用。components 由 app.py 装配后注入。"""

    def __init__(self, components: dict, config: dict, logger_=None):
        self.c = components
        self.config = config
        self.log = logger_ or logger
        self._calls = {"ok": 0, "err": 0}

    # ── 可用性（诚实清单）───────────────────────────────────────────
    # mode 词表（绝不混用）：
    #   production_in_use           本进程生产路径每轮都在走
    #   enabled_wired_runtime_unverified  配置开+接线代码在，但真实运行时
    #                                   未验证（认知仓 2026-10-12 ENABLEMENT
    #                                   自述"宿主块运行时未测"，如实传递）
    #   flag_off                    配置关（零行为）
    def availability(self) -> dict:
        cfg = self.config

        def flag(*keys):
            v = cfg
            for k in keys:
                v = (v or {}).get(k)
            return v

        def wired(on, note):
            return {"mode": ("enabled_wired_runtime_unverified" if on
                             else "flag_off"), "detail": note}

        caps = {}
        caps["continuous_cognition"] = {
            "present": self.c.get("cc") is not None,
            "mode": "production_in_use",
            "detail": "tick→CI→表达（channels=%d）" % len(
                getattr(self.c.get("cc"), "channels", []) or [])}
        caps["autonomy"] = {
            "present": self.c.get("autonomy") is not None,
            "mode": "production_in_use",
            "detail": "world-action loop; 意图/取消/反思闭环"}
        caps["goal_planner"] = dict(present=True, **wired(
            flag("planner", "enabled"),
            "2026-10-12 已启用（认知侧 SimEnv 23 测绿；attach 生产入口经本适配器"
            "/api/goals，tick 派发在 autonomy 节拍内）；真实 MC 运行未验证"))
        caps["goal_path_bias"] = dict(present=True, **wired(
            flag("goal_path", "enabled"), "autonomy 候选偏置"))
        caps["memrep"] = dict(present=True, **wired(
            flag("memrep", "enabled"),
            "试点在 action_system.enrich；有效期/来源字段的独立消费端仍缺"
            "（MEMREP 审计 §5 自认），别当完整记忆层用"))
        caps["reading"] = dict(present=True, **wired(
            flag("reader", "enabled"),
            "宿主块在 app 回合内（台账+逐单元+register_gap 2026-10-12 已接）；"
            "运行时首验待真实 read_file 回合"))
        caps["taskloop"] = dict(present=True, **wired(
            flag("taskloop", "enabled"),
            "taskloop_host 在 app 回合内；adapters 白名单为空时不路由"))
        caps["prior_knowledge_gaps"] = {
            "present": self.c.get("kg") is not None,
            "mode": "production_in_use",
            "detail": "hub/张力账本；CuriosityDrive 消费"}
        caps["temporal_awareness"] = {
            "present": True, "mode": "production_in_use",
            "detail": "时钟/时段节点（BUCKET_CIRCADIAN 夜型标定 2026-10-11）"}
        caps["self_model"] = {
            "present": True, "mode": "production_in_use",
            "detail": "经验/情绪/偏好读写（self_graph）"}
        caps["expression_v2"] = dict(present=True, **wired(
            cfg.get("expression_decision_v2"), "四轴表达决策（评估器路径）"))
        caps["living_loop"] = dict(present=True, **wired(
            cfg.get("living_loop_enabled"),
            "缺口→检索→账本→分享消费（P5 投递口已接）"))
        caps["voice_loop"] = dict(present=True, **wired(
            cfg.get("voice_enabled"),
            "P1：VAD→ASR→主管道→双轨→TTS→打断（见 GET /api/voice/status）"))
        caps["screen_watch"] = dict(present=True, **wired(
            cfg.get("screen_observe_enabled"),
            "P3：隐私 ephemeral，重启必关"))
        caps["steam_context"] = dict(present=True, **wired(
            cfg.get("steam_poll_enabled"),
            "P3：只读 Web API；需 STEAM_API_KEY+steam_id"))
        return caps

    # ── 白名单调用表：能力→方法→(实现, 描述) ──
    def _resolve(self, cap: str, method: str):
        c = self.c
        table = {
            "continuous_cognition": {
                "state": lambda: c["cc"].state(),
                "poll": lambda: c["cc"].poll(),
            },
            "autonomy": {
                "state": lambda: c["autonomy"].state(),
            },
            "goal_planner": {
                "attach": lambda item, count=1, desc=None: self._goal_attach(
                    item, count, desc),
                "state": lambda: self._goal_state(),
            },
            "prior_knowledge_gaps": {
                "open": lambda: self._gaps_open(),
            },
            "temporal_awareness": {
                "clock": lambda: self._clock_state(),
            },
            "self_model": {
                "summary": lambda: self._self_summary(),
            },
        }
        fn = table.get(cap, {}).get(method)
        return fn

    # ── 实际实现（全部走认知层既有入口，不复制逻辑）──
    def _goal_attach(self, item, count=1, desc=None):
        """goal_planner.attach_goal 的生产入口（此前零调用=断点）。
        item=库存物品节点 id；计划推演需要 MC 世界观测，非 MC 语境下
        build_plan 可能返回 unreachable——**如实返回**，不假装能规划。"""
        import goal_planner as gp
        c = self.c
        gid = gp.attach_goal(c["kg"], str(item), count=int(count), desc=desc)
        _gid, spec = gp.current_goal_spec(c["kg"])
        state = gp.state_view(c["kg"])
        plan = None
        if spec:
            try:
                plan = gp.build_plan(c["kg"], spec, state, self.config)
            except Exception as e:                # noqa: BLE001
                plan = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        return {"goal_node": gid, "spec": spec,
                "plan_steps": (plan or {}).get("steps", [])[:5],
                "plan": plan,
                "note": "planner.tick 由 planner.enabled 控制（当前 %s）" % (
                    (self.config.get("planner") or {}).get("enabled"))}

    def _goal_state(self):
        import goal_planner as gp
        gid, spec = gp.current_goal_spec(self.c["kg"])
        return {"goal_id": gid, "spec": spec,
                "state_view": gp.state_view(self.c["kg"])}

    def _gaps_open(self):
        try:
            import prior_knowledge as pk
            return pk.open_gaps(self.c["kg"])
        except Exception:                         # noqa: BLE001
            import curiosity_engine as ce
            return ce.get_curiosity_state(self.c["kg"])

    def _clock_state(self):
        try:
            from temporal_awareness import update_clock_state
            return update_clock_state(self.c["kg"])
        except Exception as e:                    # noqa: BLE001
            return {"error": str(e)[:120]}

    def _self_summary(self):
        from self_graph import get_self_model_summary
        return get_self_model_summary(self.c["kg"])

    # ── 统一入口（错误隔离 + 耗时观测 + 计数）──
    def call(self, cap: str, method: str, *args):
        t0 = time.time()
        fn = self._resolve(cap, method)
        if fn is None:
            self._calls["err"] += 1
            return {"ok": False,
                    "error": f"unknown_capability_or_method: {cap}.{method}",
                    "hint": "白名单见 availability()+源码 _resolve"}
        try:
            result = fn(*args) if args else fn()
            self._calls["ok"] += 1
            return {"ok": True, "cap": cap, "method": method,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "result": result}
        except Exception as e:                    # noqa: BLE001
            self._calls["err"] += 1
            self.log.warning("[Adapter] %s.%s 失败：%r", cap, method, e)
            return {"ok": False, "cap": cap, "method": method,
                    "error": f"{type(e).__name__}: {str(e)[:200]}",
                    "elapsed_ms": int((time.time() - t0) * 1000)}

    def stats(self):
        return dict(self._calls)
