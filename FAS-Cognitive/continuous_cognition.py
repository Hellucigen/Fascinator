# continuous_cognition.py — 持续认知循环 + 交流意图（Communication Intention）
# ============================================================================
# 设计原则（FAS Continuous Cognition 规范）：
#   1. 主动交流是认知运行的结果，不是定时聊天功能
#   2. 持续运行 ≠ 持续调 LLM：tick 只跑图谱机制（衰减/扩散/检索/评估），
#      仅当一个 CI 通过表达决策后才调 1 次 LLM 做语言实现
#   3. CI 是图节点（self 空间），不是动作枚举：可保持/增强/竞争/抑制/消亡
#   4. "不表达"是合法且常态的结果
#   5. 可解释性：每个 CI 携带 basis/激活路径/得分/决策原因
#
# 状态机：forming → ready → expressed
#                ↘ discarded（激活衰减出局）
# ready 且未达表达阈值 = WAIT（自然滞留，可被后续脉冲再次增强）
#
# LLM 调用点：仅 _express() 内 1 次 nlp.ask("proactive_express")。
# ============================================================================

import logging
import re
import threading
import time
from datetime import datetime

from graph_model import (Node, Edge, now_str, ENGINE_PART_LABELS,
                         is_modulator_node, is_state_mirror,
                         is_content_scaffold, is_internal_trace)

# 身份枢纽（2026-10-25）：可参与念头 basis（与真事件共激活），但不得
# 成为**唯一**内容——见 _merge_or_form 的纯身份拒绝。
_IDENTITY_HUBS = frozenset({"用户", "Fascinator", "Haru", "Self"})
from graph_evolution_log import get_evolution_log

logger = logging.getLogger(__name__)

# 状态常量
ST_FORMING = "forming"
ST_READY = "ready"          # 达到形成阈值；未达表达阈值即 WAIT
ST_EXPRESSED = "expressed"
ST_DISCARDED = "discarded"

MAX_CI_NODES = 20           # 图中 CI 节点保留上限（含历史，防膨胀）
MAX_ACTIVE = 3              # 同时活跃（forming/ready）的 CI 数上限（竞争）
BASIS_KEEP = 6


class ContinuousCognition:
    """持续认知循环：无输入时继续图谱认知活动，并从图状态形成交流意图。"""

    # ── 统一认知循环默认参数（config["cognitive_loop"] 同构可覆盖；
    #    与 cognitive_field 的 DEFAULT_* 同一模式：config 缺位时系统
    #    最低可运行，调参走 config）────────────────────────────
    _DEFAULT_LOOP = {
        "reactivation": {
            "weights": {"importance": 0.25, "recency_gap": 0.20,
                         "field_coupling": 0.25, "drive_tie": 0.15,
                         "novelty": 0.10, "noise": 0.15},
            "half_life_s": 900, "cold_field_activation": 0.35,
            "min_interval_ticks": 2, "count": 4, "boost": 1.2,
            "recent_penalty": 0.6, "recent_window_s": 180},
        "intention_kinds": {
            "communication": {"signals": {
                "social_relevance": 0.45, "user_relevance": 0.40,
                "emotion_present": 0.20, "drive.social": 0.35,
                "network.DMN": -0.15}},
            "exploration": {"signals": {
                "drive.curiosity": 0.50, "unknown_present": 0.35,
                "novelty": 0.10, "network.DMN": 0.25,
                "social_relevance": -0.20}},
            "action": {"signals": {
                "world_resource": 0.30, "world_hostile": 0.35,
                "goal_present": 0.30, "drive.learning": 0.25,
                "network.CEN": 0.25, "social_relevance": -0.10}},
            "reflection": {"signals": {
                "tension.self_contradiction": 0.45,
                "drive.consistency": 0.45, "network.DMN": 0.20}},
            "attention_shift": {"signals": {
                "salience": 0.35, "novelty": 0.30, "network.DMN": 0.30,
                "field_change": 0.20}}},
        "max_active_per_kind": 2,
        "focus": {"topk_base": 15, "weights": {
            "concentration": 0.60, "coherence": 0.15, "continuity": 0.08,
            "novelty": 0.10, "drive_support": 0.07}},
        "pulse_gate": {"min_field_change": 0.8, "max_interval_s": 25},
        "pressure": {
            "node": "反思压力", "threshold": 1.2,
            "sources": {"action_failure": 0.25, "negative_feedback": 0.30,
                         "prediction_error": 0.15, "intention_lost": 0.20,
                         "novel_experience": 0.05},
            # 注意力焦点"新到什么程度"才算一次新经历（R2 P11/D-10：这一档压力原先
            # 有表、有金额，但**全仓没有一个 emit 点**，等于这个来源不存在）。
            # 判据用已经算好的 `novelty = 1 − 连续性`（焦点集合与上一拍的 Jaccard），
            # 不另起一套"新颖度"——两处各算一个新颖度才是真正的平行状态。
            "novel_min_novelty": 0.5,
            "max_inject": 2.5, "cooldown_s": 600},
    }

    def __init__(self, kg, engine, nlp, buffer, config, chat_log=None,
                 channels=None):
        self.kg = kg
        self.engine = engine
        self.nlp = nlp
        self.buffer = buffer
        self.config = config
        self.chat_log = chat_log
        # 外部表达通道（fas.protocols.ExpressionChannel，如 Charon 桌面
        # 气泡）：在表达产出时刻投递，不依赖网页端 _queue 轮询。空=零行为变化。
        self.channels = list(channels or [])
        self._evo = get_evolution_log()

        cfg = config.setdefault("continuous_cognition", {})
        cfg.setdefault("tick_seconds", 2.5)
        cfg.setdefault("pulse_every_ticks", 4)        # ~10s 一次认知脉冲
        cfg.setdefault("form_threshold", 0.55)        # CI 形成阈值
        cfg.setdefault("express_threshold", 0.62)     # 表达阈值（高于形成）。
        # 2026-10-24：0.78→0.62。代码事实：CI 出生激活 0.8-0.9 且每拍 ×0.9
        # 衰减，0.78 门槛叠加情绪调制（实测抬到 0.839）→ 出生即压线、两三拍
        # 必死（below_bar 123 次/日，最高分 0.615 vs 门槛 0.839）。0.62 让
        # 出生拍与反刍强化的念头实际可达；防高频仍由 inhibition_cooldown_s
        # 与 max_expressions_per_hour 把守，不是靠门槛硬扛。
        cfg.setdefault("discard_below", 0.10)
        cfg.setdefault("decay_per_pulse", 0.90)
        cfg.setdefault("inhibition_cooldown_s", 60)   # 调度 floor：两条主动消息的最小物理间隔
        cfg.setdefault("max_expressions_per_hour", 6)
        # reinforced 语义（2026-10-16 修正）：重复扫描/重复选中同一焦点不再
        # 自动等价于一次重访。计入强化需同时满足：① 焦点强度比上次强化时
        # 记录的新高分（rehearsal_base）至少再涨 eps——未被消费的上涨会一直
        # 等在那里，间隔一到即结算，新信息复活旧话题不会丢；② 距上次强化
        # ≥ rehearsal_gap_s——强化速率与扫描节拍解耦。此前 reinforced 实为
        # 选中次数（实测 reinforced=29 而激活 0.0），会被衰减固化的 damp
        # 下限拖成慢衰减僵尸、自我强化。
        cfg.setdefault("reinforce_rise_eps", 0.05)
        cfg.setdefault("rehearsal_gap_s", 120.0)
        # 论文 §3.3 自主意识模块：离线自由思考/思维跳跃/反思自问
        cfg.setdefault("reignite_every_pulses", 3)    # 冷场需持续的拍数（调制层缺位时的兜底）
        cfg.setdefault("reignite_count", 3)           # 每次唤醒的记忆事件数
        cfg.setdefault("reignite_boost", 1.2)
        # 离线经验重放微调（batch_max/seeds_max/预算/退避等，默认值集中在
        # experience_replay.DEFAULTS——这里空 dict = 全用默认，勿在此复制）
        cfg.setdefault("replay", {})
        cfg.setdefault("thought_every_pulses", 12)    # 低频自由思考（1 次 LLM）
        cfg.setdefault("thought_min_interval_s", 900) # 思考最小间隔 15 分钟
        cfg.setdefault("offline_reflection", True)    # 长时间静默+有未反思表达时自问
        cfg.setdefault("index_sync_every_ticks", 5)   # 每 5 tick 把新节点增量编入语义索引
        cfg.setdefault("monitor_poll_every_ticks", 4)  # 每 4 tick 轮询到期状态检测器
        cfg.setdefault("autonomy_every_ticks", 4)      # 每 4 tick 跑一次自主决策（≈10s）
        cfg.setdefault("clock_every_ticks", 24)         # 每 24 tick（≈60s）更新世界时钟状态
        self.cfg = cfg
        # 统一认知循环（2026-09-20）：cognitive_loop 段是反应性参数真源
        # （config 逐键覆盖内置默认——离线/测试 config 缺段也能运行）
        merged = {k: (dict(v) if isinstance(v, dict) else v)
                  for k, v in self._DEFAULT_LOOP.items()}
        for k, v in ((config or {}).get("cognitive_loop") or {}).items():
            prev = merged.get(k)
            if isinstance(v, dict) and isinstance(prev, dict):
                m = dict(prev)
                m.update(v)
                merged[k] = m
            else:
                merged[k] = v
        self._loop_cfg = merged
        self._last_focus_sig = []       # 上一脉冲焦点签名（连续性/新颖性）
        self._last_pulse_ts = 0.0       # 脉冲时间兜底门
        self._last_react_ts = 0.0       # 再点火 cooldown
        self._cold_beats = 0          # 连续观测到"场过冷"的拍数（R2 P8 防抖）
        self._reactivated_recent = {}   # node → 最近点亮时刻（重复惩罚）
        self._field_sig_prev = None     # 激活场签名（变化量门）

        self._thread = None
        self._stop = threading.Event()
        self._busy = threading.Event()   # /api/nlp 处理中 → 暂停 tick 扩散
        self._lock = threading.RLock()
        self._tick = 0
        self._pulse_seq = 0          # 脉冲序号（B5 出生拍豁免的键；_tick 在
                                     # busy 期不前进，不能当"同一拍"的判据）
        self._last_express_ts = 0.0
        self._express_count_hour = []
        self._queue = []                 # 待取主动消息 [{ci_id, text, ...}]
        self._last_outcome_negative = False
        self._last_outcome_ts = 0.0        # 委屈不再全天闩死（20:0x 校准）
        # 枢纽背景激活：Self/用户 一跳事实的地板集（时钟拍刷新，每拍施加）
        self._hub_targets = {}
        self._last_thought_ts = 0.0
        self._last_offline_reflect = 0.0
        self.reflection = None           # 可选：ReflectionEngine 引用（离线自问）
        self._emb_mgr = None             # 可选：EmbeddingManager（新节点增量入索引）
        self.regulation = None           # 可选：CognitiveRegulation（检测器轮询）
        self.autonomy = None             # 可选：AutonomousLoop（自主行动节拍）
        self.action_manager = None       # 可选：ActionManager（动作推进/中断/结算）
        self.drive_evaluator = None      # 可选：DriveEvaluator（自主期驱动力刷新）
        self.internal_state = None       # 可选：InternalState（激素衰减 tick）
        self.timeline = None             # 可选：ExperienceTimeline（时钟迁移事件入统一时间轴）
        self._replay = None              # 可选：ExperienceReplay（离线经验重放调度层，惰性建）

    # ── 生命周期 ──────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="continuous-cognition", daemon=True)
        self._thread.start()
        logger.info("[CC] 持续认知循环已启动 "
                    f"(tick={self.cfg['tick_seconds']}s, pulse_every={self.cfg['pulse_every_ticks']})")
        import fas_log
        fas_log.get_logger(fas_log.COGNITION).info(
            "loop_started", "持续认知循环已启动",
            tick_s=self.cfg["tick_seconds"],
            pulse_every=self.cfg["pulse_every_ticks"])

    def stop(self):
        self._stop.set()

    def set_busy(self, busy: bool):
        """/api/nlp 处理期间置位，tick 扩散让位，避免与请求内扩散叠加。"""
        if busy:
            self._busy.set()
        else:
            self._busy.clear()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as e:
                logger.warning(f"[CC] 循环异常: {e}")
                import fas_log
                fas_log.get_logger(fas_log.COGNITION).exception(
                    "cc_loop_exception", f"循环 tick 异常: {e}")
            self._stop.wait(self.cfg["tick_seconds"])
        import fas_log
        fas_log.get_logger(fas_log.COGNITION).info(
            "loop_stopped", "持续认知循环已停止", tick=self._tick)

    def tick_once(self):
        """一个认知 tick。图谱扩散/脉冲在对话回合期间让位（busy）；
        **具身行动推进永不停**（Bug 修复 2026-09-20）：回合内 busy 曾冻结
        整个 tick 体，一次 40~80 秒的 LLM 回合把在飞动作的轮询/结算也冻住
        ——她"一思考就站住"，走到了也不结算（实测日志 01:09:36 出发的
        navigate 直到回合结束都没 poll）。行动推进不碰扩散前沿，
        与回合内的 activate/diffuse 没有资源冲突。"""
        if not self._busy.is_set():
            self._tick += 1
            # 手动 auto 模式开启时让位其扩散，避免双重扩散
            if not getattr(self.engine, "_running", False):
                self.engine.decay_step()
                self.engine.diffuse_step()
            # 枢纽背景激活（2026-10-17 用户设计）：把 Self/用户 的常激活
            # 事实钳回地板——地板钳位即"增量=衰减量"的平衡，高于地板不加，
            # 永不 runaway（self_graph）。必须在让位分支**外面**：后台
            # auto 扩散自己衰减但不施地板，放进去该模式就永久没地板。
            try:
                import self_graph as _sg
                _sg.apply_hub_floors(self.kg, self.engine,
                                     self._hub_targets)
            except Exception:                         # noqa: BLE001
                pass
                import fas_log
                fas_log.aggregator(
                    "cc_diffusion_ticks", fas_log.ACTIVATION,
                    "diffusion_ticks", flush_every_s=120.0,
                    msg="后台图谱扩散（聚合）").add()
            # 激素衰减：phasic 快速回 0、level 向 baseline 回归。
            # 只动内存值（落盘仍走既有 cycle 边界），不新增磁盘压力。
            # §16 实验屏蔽 internal_state_heartbeat：decay/drift/needs 三个
            # 写入节拍全跳过 ⇒ 内部状态钉在装配时刻（排除心情/激素漂移干扰）。
            _is_shielded = False
            try:
                import experiment_mode as _xm
                _is_shielded = _xm.shield("internal_state_heartbeat")
            except Exception:
                pass
            if self.internal_state is not None and not _is_shielded:
                try:
                    self.internal_state.tick_decay()
                    # 需求控制器（Phase 2+ 补账）：有 provider 的维度向
                    # 世界信号缓步收敛；没接 provider 的不动。
                    #
                    # R2 P9：这一拍把**图上**的 需求↔调制器 耦合走两步——
                    #   ① 需求→调制器（`apply_need_drift`）：缺口按边权慢慢抬/压通道；
                    #   ② 调制器→需求（`bias=`）：通道水位反过来给靶值一个连续位移。
                    # 一正一反成**负反馈**（缺口→抬通道→靶值收敛缺口→通道回落），
                    # 有界性由两侧钳位保证（① 唯一写入口+受体曲线，② 需求量程）。
                    # dt 用本拍的实际时长（tick 节拍被回合暂停时不会补跳）。
                    # （R2 P10 的 ⓪ 步"昼夜→清醒度漂移"已删除，2026-10-17 用户
                    #   裁定：AI 没有疲劳/清醒的生理——时段是知识不是睡眠压力。）
                    _need_bias = {}
                    try:
                        import modulator_subgraph as _ms
                        _dt = float(self.cfg["tick_seconds"]) / 60.0
                        _ms.apply_need_drift(self.kg, self.internal_state,
                                             self.config, dt_min=_dt)
                        _need_bias = (_ms.graph_biases(
                            self.kg, self.internal_state, self.config)
                            or {}).get("need") or {}
                    except ImportError:
                        pass
                    self.internal_state.update_needs_from_signals(
                        bias=_need_bias)
                except Exception as _de:
                    logger.debug(f"[CC] 内部状态控制跳过: {_de}")
            # 参数调制（论文"参数节点化"最小兑现；2026-09-20 Drive 重构
            # 收编）：情绪唤醒/皮质醇压力喂入 CognitiveField 语境，
            # diffusion.param_gain 由统一调制层合成（网络态/激素/张力一并
            # 生效），引擎经 engine.modulation 读回。只读既有状态。
            try:
                _ar = 0.0
                with self.kg._lock:
                    for _n in self.kg.nodes.values():
                        if (_n.extra_attrs or {}).get("type") == "emotion"                                 and _n.activation > _ar:
                            _ar = min(1.0, _n.activation / 3.0)
                _st = 0.0
                if self.internal_state is not None:
                    # 参数通道（context.stress）读**慢分量偏移**：modulator_dev 已经
                    # 减过基线并过受体曲线，这里不再自己 level−baseline（R2 P3）。
                    _st = max(0.0, min(1.0,
                                       float(self.internal_state.modulator_dev(
                                           "cortisol") or 0.0)))
                if self.drive_evaluator is not None:
                    try:
                        self.drive_evaluator.set_context_value("arousal", _ar)
                        self.drive_evaluator.set_context_value("stress", _st)
                        self.drive_evaluator.refresh_modulation()
                    except Exception:
                        pass
                self.engine.update_param_modulation(_ar, _st)
            except Exception as _pme:
                logger.debug(f"[CC] 参数调制跳过: {_pme}")
            # ── 再点火 / 认知脉冲：由"场状态"决定是否运行（§十一）──
            # 不堆固定闹钟：reactivation 由场冷度触发（火种不足才撒），
            # pulse 由激活场累积变化触发（有认知素材才采样），
            # cooldown/时间上限只作兜底，不是主要条件。
            self._reactivate_gate()
            self._pulse_gate()
            self._replay_gate()      # 空闲经验重放（对话期不到此拍，天然可抢占）
            if self._tick % self.cfg["thought_every_pulses"] == 0:
                self._free_think()
            if (self._tick % self.cfg["monitor_poll_every_ticks"] == 0
                    and self.regulation is not None):
                # 状态检测器轮询：只采样已登记数据源的 poll 型检测器，
                # 无数据源时零成本返回（不新建线程，借用既有 tick 节拍）
                try:
                    self.regulation.poll_due()
                except Exception as _re:
                    logger.warning(f"[CC] 检测器轮询跳过: {_re}")
            if (self._tick % self.cfg["index_sync_every_ticks"] == 0
                    and self._emb_mgr is not None):
                # 索引跟随图谱：新节点（能力/事件/未知）进语义召回
                self._emb_mgr.flush_pending(self.kg)
            self._maybe_offline_reflect()
            # tick 边界：清空本轮激活来源（本 tick 的注入只在本 tick
            # 免扣；下一 tick 的注入重新登记）。对话期 CC 暂停，
            # 来源由 app 回合末的 clear_anchors 清空。
            self.engine.clear_anchors()
        # ── 具身推进：busy 与否都要跑的部分在下面 ──
        # 世界时钟（temporal 重构 2026-09-20）：时间状态与用户输入无关、
        # 与 busy 无关——现实时间持续写入图谱（分钟级地板 + 迁移脉冲）。
        # 用真实时间门而非 _tick 取模：busy 期 _tick 冻结，时钟不能停。
        if time.time() - getattr(self, "_last_clock_ts", 0.0) >= \
                max(10.0, float(self.cfg["clock_every_ticks"])
                    * float(self.cfg["tick_seconds"])):
            self._last_clock_ts = time.time()
            try:
                # 世界时钟=事实认知（她知道现在是凌晨，能谈时段），保留；
                # 跨时段曾作为"清醒度调制事件"（R2 P10 快通道）已删除
                # （2026-10-17 用户裁定：AI 无疲劳/清醒的生理机制）。
                from temporal_awareness import update_clock_state
                update_clock_state(self.kg, self.engine,
                                   timeline=self.timeline)
                # 枢纽背景：重取一跳事实地板集（60s 级，边变了自动跟上）。
                # 顺带确保疾病·关怀种子包在场（幂等，首拍之后几乎全空转）。
                import self_graph as _sg
                try:
                    import disease_care_pack as _dcp
                    _dcp.ensure(self.kg, self.config)
                except Exception:                     # noqa: BLE001
                    pass
                self._hub_targets = _sg.hub_floor_targets(
                    self.kg, self.config)
            except Exception as _ce:
                logger.debug(f"[CC] 时钟更新跳过: {_ce}")
        # 自主"决策"仍在非 busy 期做（回合期用户正在交互，回合开头的
        # notify_user_activity 已经接管；busy 期 _tick 不前进，取模调度
        # 会失效）。但动作推进/结算（action_manager）永远继续——
        # 这正是"一边做事一边说话"的执行面。
        _auto_out = None
        if self.autonomy is not None and not self._busy.is_set() \
                and self._tick % self.cfg["autonomy_every_ticks"] == 0:
            # 自主行动决策：确定性、零 LLM、最小间隔由 autonomy 自己把关
            # （模式关闭/未连接/无依据时它只会如实返回"没做"）
            try:
                # 驱动力先刷新（Bug 修复 2026-09-19：evaluate 原本只在
                # 对话轮跑，纯自主模式下 CuriosityDrive 节点被衰减吃光
                # （实测掉到 0.023），observe/approach 候选永远低于
                # 阈值 → 她在游戏里结构性瘫痪不动。5s 缓存，成本低）
                if self.drive_evaluator is not None:
                    self.drive_evaluator.evaluate()
                _auto_out = self.autonomy.tick()
            except Exception as _ae:
                _auto_out = None
                logger.warning(f"[CC] 自主行动跳过: {_ae}")
        if self.action_manager is not None:
            # Action 节点推进（每个 tick）：在飞动作轮询回执、
            # 超时结算、生存紧急中断、目标队列出队。
            # 独立于自主模式：用户指令产生的动作也要推进。
            # 收尾修复 2026-09-22：autonomy.tick 在承诺期内已自行 tick 过
            # ActionManager（reason=action_progress），本拍不再补第二下
            # ——否则技能每拍推进两步，动作节奏翻倍。
            _am_ticked_by_autonomy = (isinstance(_auto_out, dict)
                                      and _auto_out.get("reason") == "action_progress")
            if not _am_ticked_by_autonomy:
                try:
                    self.action_manager.tick()
                except Exception as _ame:
                    logger.debug(f"[CC] Action 推进跳过: {_ame}")

    # ── 认知脉冲：图谱评估，零 LLM ────────────────────────

    # ── 认知脉冲：观察激活场正在形成什么（不是"找话跟用户说"）────
    # activation field → coherent focus → candidate intention(kind)
    # → competition（同类合并/强化，满额抑制）→ formation / nothing。
    # "什么都不产生"是合法结果：焦点弱、无明确 kind、同类满员都属正常。

    def _field_signature(self):
        try:
            topk, _ = self.engine.get_topk(k=8)
        except Exception:
            # L1-DGR-05:失败返回 None(而非 []),避免与"空场"混淆——
            # 空列表会被 _sig_change 解读成"全场消失"的重大变化,触发脉冲
            # 并给意图集体降一口衰减,全程零日志。
            return None
        return [(n.id, round(float(n.activation or 0), 1)) for n in topk]

    def _pulse_gate(self):
        gc = self._loop_cfg.get("pulse_gate") or {}
        now = time.time()
        sig = self._field_signature()
        if sig is None:
            # L1-DGR-05:探测失败本拍跳过,不采样也不触发脉冲
            import logging
            logging.getLogger(__name__).debug(
                "[CC] 场签名探测失败，脉冲门本拍跳过")
            return
        change = self._sig_change(self._field_sig_prev, sig)
        overdue = now - self._last_pulse_ts >= float(gc.get("max_interval_s", 25))
        if change < float(gc.get("min_field_change", 0.8)) and not overdue:
            return                     # 场没动，没必要采样
        self._field_sig_prev = sig
        self._last_pulse_ts = now
        self._last_field_change = change
        # ── 观测：脉冲周期（internal_state 账本外的短周期，x_ 前缀）──
        import fas_log
        _cc_cyc = fas_log.ephemeral_cycle()
        fas_log.set_cycle(_cc_cyc)
        fas_log.get_logger(fas_log.COGNITION).info(
            "cycle_start", "认知脉冲开始", trigger="cc_pulse",
            tick=self._tick, field_change=round(change, 3),
            overdue=overdue)
        _t0 = time.time()
        try:
            self._pulse({"field_change": min(1.0, change / 5.0)})
        finally:
            fas_log.get_logger(fas_log.COGNITION).info(
                "cycle_end", "认知脉冲结束", kind="cc_pulse", tick=self._tick,
                duration_s=round(time.time() - _t0, 3))
            fas_log.set_cycle(None)

    @staticmethod
    def _sig_change(prev, now_sig):
        if not prev:
            return 5.0
        p = dict(prev)
        n = dict(now_sig)
        ids = set(p) | set(n)
        return sum(abs(n.get(i, 0.0) - p.get(i, 0.0)) for i in ids)

    def _cognitive_snapshot(self):
        """Drive/网络/张力信号（供意图 kind 亲和度用；缺位按 0）。"""
        snap = {"drive": {}, "network": {}, "tension": {}}
        de = self.drive_evaluator
        if de is None:
            return snap
        try:
            f = de.field
            snap["drive"] = f.drives.levels()
            snap["network"] = f.networks.levels()
            snap["tension"] = f.tensions.levels()
        except Exception:
            pass
        return snap

    def _world_signals(self):
        """图上世界信号（focus 的 kind 亲和度输入，读既有状态节点）。"""
        out = {"unknown_present": 0.0, "world_hostile": 0.0,
               "world_resource": 0.0, "goal_present": 0.0, "salience": 0.0}
        with self.kg._lock:
            for nid, n in self.kg.nodes.items():
                ea = n.extra_attrs or {}
                act = float(n.activation or 0.0)
                if act < 0.1:
                    continue
                if str(nid).startswith(("UnknownEntity_", "UnknownBlock_",
                                         "UnknownPlayer_")):
                    out["unknown_present"] = max(out["unknown_present"],
                                                 min(1.0, act / 3.0))
                if ea.get("type") in ("goal", "reply_goal"):
                    out["goal_present"] = max(out["goal_present"],
                                              min(1.0, act / 3.0))
            hub = self.kg.get_node("附近的生物")
            if hub is not None and (hub.extra_attrs or {}).get("hostile"):
                out["world_hostile"] = 1.0
            blocks = self.kg.get_node("附近的方块")
            if blocks is not None and str(
                    (blocks.extra_attrs or {}).get("value") or "") \
                    not in ("", "无"):
                out["world_resource"] = 0.6
            ui = self.kg.get_node("未知信息")
            if ui is not None:
                out["salience"] = min(1.0, float(ui.activation or 0.0) / 3.0)
        return out

    def _pulse(self, extra_signals: dict = None):
        self._pulse_seq += 1         # B5：本拍号（形成与衰减共用，出生拍豁免判据）
        # R2 P8（D-3）：`retrieval.topk_scale` 的真消费者 —— 这次脉冲从认知场里
        # 取多宽的素材面。DMN 高→读得更宽（发散时翻更多角落），CEN 高时该参数
        # 不降（它没有 CEN 行），但 negative_experience 抬升也会放宽（反刍时更容易
        # 捞进旧账），这就是"同一份场，不同状态看见不同东西"。
        width = max(3, int(round(15.0 * self._mod_th("retrieval.topk_scale", 1.0))))
        topk, _ = self.engine.get_topk(k=width)
        with self.kg._lock:
            INFRA = {nid for nid, n in self.kg.nodes.items()
                     if n.label in ENGINE_PART_LABELS}
        basis_pool = [n for n in topk
                      if n.id not in INFRA and n.activation > 0.15
                      # 控制量与状态镜像可参与激活与排序，但不得成为
                      # 念头的内容来源（2026-10-19 表达边界：DMNetwork
                      # "神游联想的状态"曾以〔概念〕身份被叙述化进 prompt）
                      and not is_modulator_node(n)
                      and not is_state_mirror(n)
                      # 本体/标签/时间桶/性格不配当"内容"进 basis
                      # （计算资格不受影响，2026-10-20 C1/C2）
                      and not is_content_scaffold(n)
                      and not n.id.startswith(("坐标(", "CI_", "思考_", "反思_",
                                               "回答记录_", "搜索记录_",
                                               "文件操作记录_"))]
        # 身份枢纽过滤（2026-10-25 实锤修复）：'用户'（度数 656）永远发亮，
        # 独占 topk 且毫无内容量——10 小时 452 个 basis=['用户'] 的空探索
        # 意图全由它而生。但只滤"纯身份 basis"，混合池保留身份+真概念
        # （'用户'常与真事件共激活，全部剔除会掐掉话源——15:27 实锤：
        # 纯剔除后 basis_pool 长期为空，她整晚零意图）。规则：basis 里
        # 除身份外必须有至少一个真概念，否则该拍不形成（decay 照常）。
        _IDENTITY = {"用户", "Fascinator", "Haru", "Self"}
        # 结构脚手架（2026-10-25 深夜实锤：时点锚 label=infrastructure，
        # 扩散点亮后不衰减（引擎对 infrastructure 跳过衰减），0.68×15+
        # 个占满 topk 中后段，把 0.3 的情景内容全部挤出 width 窗——
        # basis_pool 剩一个'进入Minecraft世界'。按 label 过滤结构件。
        basis_pool = [n for n in basis_pool
                      if getattr(n, "label", "") not in ENGINE_PART_LABELS]
        if not basis_pool:
            self._decay_intentions()
            return

        # ── focus 质量（"认知场里正在形成什么"，先于任何表达考虑）──
        ids = [n.id for n in basis_pool]
        idset = set(ids)
        internal_edges = 0
        with self.kg._lock:
            for nid in ids:
                for e in self.kg.get_out_edges(nid):
                    if e.dst in idset:
                        internal_edges += 1
        max_pairs = max(1, len(ids) * (len(ids) - 1) / 2.0)
        coherence = min(1.0, internal_edges / (max_pairs * 0.4))
        prev_focus = set(self._last_focus_sig)
        overlap = len(idset & prev_focus) / max(len(idset | prev_focus), 1)
        continuity = min(1.0, overlap * 2.0)
        novelty = 1.0 - continuity
        top_act = max(n.activation for n in basis_pool)
        concentration = min(top_act / 3.0, 1.0)
        # ── SN 统一显著性（2026-10-15）：focus 变化喂进显著性网络；
        # 外部事件显著（bottom_up 强）时经合法接口点亮执行网络 CENetwork
        # ——不写激活字段、不另造控制流，mark_active 是"本拍参与更新"的
        # 既有信号，涨多少仍由扩散自己决定。sn 关闭=整段跳过，行为回旧。──
        try:
            from cognitive_field import salience_network as _sn_get
            _sn = _sn_get(self.config if isinstance(self.config, dict)
                          else None)
            if _sn.enabled:
                _prev = float(getattr(self, "_sn_last_act", 0.0) or 0.0)
                _delta = abs(float(top_act) - _prev) / 3.0
                self._sn_last_act = float(top_act)
                _sn.event_salience(
                    "field_shift", delta=_delta, novelty=float(novelty),
                    feasible=True, source="field")
                if _sn.last.get("score", 0.0) >= 0.45 \
                        and self.kg.get_node("CENetwork") is not None:
                    self.engine.mark_active("CENetwork")
        except Exception as _sn_err:              # noqa: BLE001
            logger.debug("[SN] focus 注入异常（忽略）: %r", _sn_err)
        with self.kg._lock:
            drive_support = 0.0
            for n in basis_pool:
                ea = getattr(n, "extra_attrs", None) or {}
                if ea.get("type") in ("drive", "emotion", "cognitive_network"):
                    drive_support = max(drive_support, min(1.0,
                                      float(n.activation or 0.0) / 3.0))
        sig = self._cognitive_snapshot()
        with self.kg._lock:
            user_edges = {e.dst: float(e.weight or 0)
                          for e in self.kg.get_out_edges("用户")}
            emotion_ids = {nid for nid, n in self.kg.nodes.items()
                           if (n.extra_attrs or {}).get("type") == "emotion"
                           and float(n.activation or 0) > 0.1}
        # 2026-10-17（"为啥不找我"取证）：「用户」本人就在焦点里，本身就是
        # 最强的用户相关性证据——旧判据只数"用户出边命中的焦点节点"，他人在
        # 脑子里却不计分。
        _ids = {n.id for n in basis_pool}
        user_relevant = sum(1 for n in basis_pool
                            if user_edges.get(n.id, 0) > 0.2)
        user_relevant += 1 if "用户" in _ids else 0
        emotion_present = 1.0 if any(n.id in emotion_ids for n in basis_pool) else 0.0
        social_relevance = min(1.0, (0.5 if emotion_present else 0.0)
                               + 0.15 * min(user_relevant, 3))
        affordance_w = (self._loop_cfg.get("focus") or {}).get("weights") or {}
        focus_score = (
            float(affordance_w.get("concentration", 0.60)) * concentration
            + float(affordance_w.get("coherence", 0.15)) * coherence
            + float(affordance_w.get("continuity", 0.08)) * continuity
            + float(affordance_w.get("novelty", 0.10)) * novelty
            + float(affordance_w.get("drive_support", 0.07)) * drive_support)
        focus_explain = {
            "concentration": round(concentration, 2), "coherence": round(coherence, 2),
            "continuity": round(continuity, 2), "novelty": round(novelty, 2),
            "drive_support": round(drive_support, 2),
            "focus_score": round(focus_score, 3),
            # 社交三读数入账（2026-10-17 表达去门控）：分享价值是**内容
            # 属性**，随念头定格——事后图谱焦点会漂走，评估时必须拿得到
            # "形成那一刻它与用户/社交有没有关系"。additive 字段，旧消费
            # 方按 key 取值不受影响。
            "user_relevance": round(min(1.0, user_relevant / 3.0), 3),
            "social_relevance": round(social_relevance, 3),
            "emotion_present": emotion_present,
            "top_activation": round(top_act, 3)}

        # ── focus → 候选意图 kinds（affinity 数据表；kind 开放可扩展）──
        # 分享冲动的新信号（2026-10-15 用户指正："不能只聊有关我的"）：
        # 焦点里若有她**刚经历的事**（活动体验节点——逛到的、学到的、
        # 做成的），其显著度直接构成"想说点什么"——人搭话常因"我碰上了
        # 个东西"而非"这事关于你"。经历与用户的相关度仍是独立因子。
        recent_experience = 0.0
        for n in basis_pool:
            ea_n = getattr(n, "extra_attrs", None) or {}
            if str(ea_n.get("type") or "") == "activity_experience":
                recent_experience = max(recent_experience, min(
                    1.0, float(n.activation or 0.0)))
        signals = {
            "concentration": concentration, "coherence": coherence,
            "novelty": novelty, "salience": 0.0,
            "social_relevance": social_relevance,
            "user_relevance": min(1.0, user_relevant / 3.0),
            "recent_experience": recent_experience,
            "emotion_present": emotion_present,
            "unknown_present": 0.0, "world_hostile": 0.0,
            "world_resource": 0.0, "goal_present": 0.0,
            "field_change": float((extra_signals or {}).get("field_change", 0.0)),
        }
        try:
            signals.update(self._world_signals())
        except Exception:
            pass
        for d, lv in sig["drive"].items():
            signals["drive." + d] = lv
        for k, lv in sig["network"].items():
            signals["network." + k] = lv
        for t, lv in sig["tension"].items():
            signals["tension." + t] = lv
        kinds_aff = {}
        for kind, spec in (self._loop_cfg.get("intention_kinds") or {}).items():
            a = 0.0
            for key, w in (spec.get("signals") or {}).items():
                a += float(w) * float(signals.get(key, 0.0) or 0.0)
            kinds_aff[kind] = round(a, 3)
        # 采样观测（2026-10-17，"为啥不找我"取证）：此前只记胜者，输家分数
        # 全黑盒——她不来找你怎么都说不清是哪个信号被压。~6 分钟一条。
        if self._pulse_seq % 36 == 0 and kinds_aff:
            _rank = sorted(kinds_aff.items(), key=lambda kv: -kv[1])
            logger.info("[CC] 种类亲和度：%s",
                        " ".join("%s=%.2f" % kv for kv in _rank))

        self._last_focus_sig = ids
        # R2 P11（审计 D-10）：焦点底子换掉大半 = 一次"新经历"，进反思压力池。
        # 金额一直在 config 的 `pressure.sources.novel_experience`（0.05）里，缺的
        # 从来不是数值而是这个 emit 点 ⇒ 那个来源此前等于不存在。判据复用**已经算好**
        # 的 `novelty = 1 − 连续性`（本拍焦点集合与上一拍的 Jaccard），不另起一套
        # 新颖度算法——两处各算一个"新"才是真正的平行状态。
        if novelty >= float((self._loop_cfg.get("pressure") or {})
                            .get("novel_min_novelty", 0.5)):
            self.note_pressure("novel_experience")
        self._merge_or_form(basis_pool, focus_score, focus_explain,
                            kinds_aff, signals)
        self._decay_intentions()
        self._prune_history()
        self.tick_express_check()

    # ── CI 形成与竞争 ─────────────────────────────────────

    # ── 意图形成与竞争（kind 感知：communication/action/exploration/…开放表）──

    def _mod_th(self, key: str, fallback: float) -> float:
        """调制层读点（阈值不是静态 magic number）。"""
        de = self.drive_evaluator
        if de is None:
            return float(fallback)
        try:
            v = de.modulation().get(key)
            return float(v) if v is not None else float(fallback)
        except Exception:
            return float(fallback)

    def _merge_basis_deterministic(self, old: set, new: set) -> list:
        """同簇强化时 basis 的确定性证据保留（替代 list(set)[:6] 的随机挤出）。

        排序键（全部确定性，与 set 迭代顺序无关）：
          ① 证据类：episodic/emotion 节点优先——它们是表达 rich 闸的合法证据，
            不得仅因合并顺序丢失（2026-10-10 审计：「用户近况」被无序截断挤出，
            意图此后每拍都死在 rich 闸，成为不可见缺陷）；
          ② 新焦点成员优先于旧成员（recency：当前脉冲的相关性）；
          ③ id 字典序兜底（完全确定、可复现）。
        容量 BASIS_KEEP 不变——超出容量按上述规则淘汰冗余/低类证据，
        不扩上限、不伪造证据类。"""
        with self.kg._lock:
            def rank(n):
                bn = self.kg.nodes.get(n)
                if bn is None:
                    return 2          # 悬空引用最先淘汰
                if (bn.graph_space == "episodic"
                        or (bn.extra_attrs or {}).get("type") == "emotion"):
                    return 0          # rich 闸合法证据
                return 1
            return sorted(
                set(old) | set(new),
                key=lambda n: (rank(n), 0 if n in new else 1, n))[:BASIS_KEEP]

    def _merge_or_form(self, basis_nodes, focus_score, focus_explain,
                       kinds_aff, signals):
        basis = [n.id for n in basis_nodes[:BASIS_KEEP]]
        # 纯身份 basis 不配成念头（2026-10-25：452 个 basis=['用户'] 空意图
        # 的根因）。混合池（身份+真概念）保留——'用户'常与真事件共激活。
        if basis and all(b in _IDENTITY_HUBS for b in basis):
            return
        basis_set = set(basis)
        # 意图形成阈值：受 Drive/网络/激素连续调制。
        # 注意形成判定与 kind 判定分离——focus 够强就形成（"认知场里正在
        # 形成什么"优先）；kind 只是给它类型（没有明确方向时退为
        # attention_shift：一次注意力转向，不参与表达，自然衰减）。
        form_th = self._mod_th("cognition.form_threshold",
                               float(self.cfg["form_threshold"]))
        if focus_score < form_th or not kinds_aff:
            return     # 焦点不足：不形成（合法状态）
        # attention_shift 是兜底类型（不参与 argmax）：焦点有方向就用方向，
        # 完全没方向才算一次注意力转向
        directed = {k: v for k, v in kinds_aff.items()
                    if k != "attention_shift"}
        kind, affinity = (max(directed.items(), key=lambda kv: kv[1])
                          if directed else (None, 0.0))
        if kind is None or affinity < 0.05:
            kind = "attention_shift"
            affinity = float(kinds_aff.get("attention_shift", 0.0))

        # 同一认知焦点（basis 重叠 ≥40%）= 同一意图本体保持连续（merge 非新建）
        # ——kind 无关，焦点"方向"随场演化时 kind 跟着漂移（affinity 显著更高
        # 才换，防抖）。但"连续"不等于"每次都强化"（2026-10-16 语义修正）：
        # reinforced 只在真正发生有意义的认知重访时 +1——焦点强度创下比上次
        # 强化高 ≥eps 的新高（上涨未被消费就一直等在那里，间隔一到即结算，
        # 新信息复活旧话题不丢），且距上次强化 ≥rehearsal_gap_s。同强度重复
        # 扫描只记账（score/basis/explain），不加激活、不动 reinforced。
        for ci in self._active_intentions():
            ea = ci.extra_attrs
            old_basis = set(ea.get("basis", []))
            if old_basis & basis_set:
                overlap = len(old_basis & basis_set) / max(len(old_basis | basis_set), 1)
                if overlap >= 0.4:
                    now_ts = time.time()
                    # 老意图兼容：无基线 → 以上次记录的焦点强度为基线
                    base = float(ea.get("rehearsal_base",
                                        float(ea.get("score", 0.0))))
                    rise = focus_score - base
                    gap_anchor = float(ea.get("last_boosted_ts")
                                       or ea.get("born_ts") or now_ts)
                    meaningful = (
                        rise >= float(self.cfg["reinforce_rise_eps"])
                        and (now_ts - gap_anchor)
                        >= float(self.cfg["rehearsal_gap_s"]))
                    new_basis = self._merge_basis_deterministic(
                        old_basis, basis_set)
                    kind_drift = affinity > float(ea.get("affinity", 0)) + 0.1
                    if meaningful:
                        ea["activation"] = min(
                            1.0, float(ea.get("activation", 0)) +
                            0.5 * rise + 0.06)
                        ea["reinforced"] = int(ea.get("reinforced", 0)) + 1
                        ea["rehearsal_base"] = focus_score
                        ea["last_boosted"] = now_str()
                        ea["last_boosted_ts"] = now_ts
                    ea["score"] = focus_score   # 台账：始终跟踪当前焦点强度
                    if kind_drift:
                        ea["kind"] = kind        # 焦点方向明确改变 → 意图漂移
                        ea["affinity"] = affinity
                    ea["basis"] = new_basis
                    ea["explain"] = focus_explain
                    # last_change=最后一次实质变化：强化/基线增长/方向漂移才算，
                    # 重复扫描不再把 defer 有效期无限续命（持续性≠永生）
                    if meaningful or kind_drift or len(new_basis) > len(old_basis):
                        ea["last_change_ts"] = now_ts
                    if ea.get("type") == "communication_intention":
                        self._promote_goal(ci)
                    return
        # 同类并发上限：满了 → 该型新意图竞争失败（inhibition 的图谱化）
        if len(self._active_intentions(kind)) >= \
                int(self._loop_cfg.get("max_active_per_kind", 2)):
            focus_explain["suppressed"] = f"kind_full:{kind}"
            return

        ci_id = f"CI_{int(time.time() * 1000) % 10 ** 9}"
        # 意图强度 = 焦点强度（focus 够强才形成，形成即多强）；affinity
        # 只决定"朝哪个方向"，不给强度打折——表达与否另有更高门槛把关
        intensity = round(min(1.0, focus_score), 4)
        is_comm = kind == "communication"
        with self.kg._lock:
            self.kg.add_node(Node(
                id=ci_id, weight=0.5, label="intention",
                graph_space="self",
                extra_attrs={
                    # 沟通类沿用旧 type（兼容测试/前端），其余为通用意图
                    "type": ("communication_intention" if is_comm else "intention"),
                    "kind": kind,
                    "affinity": affinity,
                    "status": (ST_FORMING if is_comm else ST_READY),
                    "activation": intensity,
                    "score": focus_score,
                    # 强化基线：只有再涨 eps 以上的"新高"才计一次重访（见
                    # _merge_or_form 的 reinforced 语义）
                    "rehearsal_base": focus_score,
                    "basis": basis,
                    "goal": None, "illocutionary_act": None,
                    "dialogue_act": None, "reply_goal": None,
                    "explain": focus_explain,
                    "created": now_str(),
                    # v2 决策的时间轴锚点：born=出生，last_change=最后一次
                    # 实质变化（强化也算）——defer 过期判定用，additive 字段。
                    "born_ts": time.time(),
                    "last_change_ts": time.time(),
                    # B5：出生脉冲号——同一拍里先形成（L575）后衰减（L577），
                    # 不记拍号就没法豁免"出生即被 ×decay 咬掉一口"。
                    "born_pulse": self._pulse_seq,
                }))
            if not self.kg.add_edge(Edge(src="Self", dst=ci_id, relation="意图",
                                         weight=0.5,
                                         relation_category="cognitive_relation")):
                # PIN-11 留痕: hub 边(Self→CI)依赖 Self 节点存在;
                # 若缺失(异常图态)静默丢边会让意图脱离纽带,留 warning。
                logger.warning(f"[CC] 意图 hub 边失败: Self -> {ci_id} 意图 "
                               f"(Self 节点可能不在图内)")
            for b in basis:
                if self.kg.get_node(b):
                    self.kg.add_edge(Edge(src=ci_id, dst=b, relation="基于",
                                          weight=0.5,
                                          relation_category="cognitive_relation"))
            self._evo.note_node_added(ci_id, label="intention", weight=0.5)
        logger.info(f"[CC] 意图形成: {ci_id} kind={kind} "
                    f"intensity={intensity:.2f} affinity={affinity:.2f} "
                    f"basis={basis[:3]}…")

    def _promote_goal(self, ci):
        """goal 推导（图谱规则，非 LLM）：basis 构成决定表达家族。

        规范八（CI 二次原子化）：goal/target 用边连接到独立节点表达，
        不塞 JSON blob——goal 连到封闭词表的目标节点，target 连 用户。
        """
        ea = ci.extra_attrs
        if ea.get("illocutionary_act"):
            return  # 已定型
        basis = ea.get("basis", [])
        with self.kg._lock:
            is_emotion = any(
                (self.kg.nodes.get(b) and
                 (self.kg.nodes[b].extra_attrs or {}).get("type") == "emotion")
                for b in basis)
            is_event = any(
                self.kg.nodes.get(b) and self.kg.nodes[b].graph_space == "episodic"
                for b in basis)
        if is_emotion:
            fam = ("expressive", "emotion_expression", "empathize", "共情回应")
        elif ("未知信息" in basis or "好奇" in basis
              or "CuriosityDrive" in basis):
            fam = ("directive", "question", "information_seeking", "追问未知")
        elif is_event:
            fam = ("assertive", "sharing", "follow_up", "延续话题")
        else:
            fam = ("assertive", "information_statement", "share_related_knowledge", "分享知识")
        ea.update(illocutionary_act=fam[0], dialogue_act=fam[1], reply_goal=fam[2])
        # 原子化表达：意图目标/指向对象 用边连接（目标词表 4 节点，cognitive 空间）
        with self.kg._lock:
            goal_id = f"目标:{fam[3]}"
            if goal_id not in self.kg.nodes:
                self.kg.add_node(Node(
                    id=goal_id, weight=0.5, label="declarative-semantic",
                    graph_space="cognitive",
                    extra_attrs={"type": "reply_goal", "key": fam[2]}))
            if not self.kg.get_edge(ci.id, goal_id, "目标"):
                self.kg.add_edge(Edge(src=ci.id, dst=goal_id, relation="目标",
                                      weight=0.6, relation_category="cognitive_relation"))
            if self.kg.get_node("用户") and not self.kg.get_edge(ci.id, "用户", "指向"):
                self.kg.add_edge(Edge(src=ci.id, dst="用户", relation="指向",
                                      weight=0.5, relation_category="social_relation"))
        ea["status"] = ST_READY
        ea["last_change_ts"] = time.time()

    _INTENTION_TYPES = ("communication_intention", "intention")

    def _active_intentions(self, kind: str = None) -> list:
        with self.kg._lock:
            return [n for n in self.kg.nodes.values()
                    if (n.extra_attrs or {}).get("type") in self._INTENTION_TYPES
                    and (kind is None
                         or n.extra_attrs.get("kind") == kind)
                    and n.extra_attrs.get("status") in (ST_FORMING, ST_READY)]

    def _active_cis(self):
        with self.kg._lock:
            return [n for n in self.kg.nodes.values()
                    if (n.extra_attrs or {}).get("type") == "communication_intention"
                    and n.extra_attrs.get("status") in (ST_FORMING, ST_READY)]

    def _share_eligible(self, n) -> bool:
        """表达候选资格 = **多路径取值**，不是单一信号一票否决
        （2026-10-18 修正：旧版把"具体证据"和"社交≥0.25"捆成 AND 硬门槛，
        把不带用户色彩的有趣发现、暂缺实据但相关的念头、可标注分享的
        新假设全挡在门外——那是另一种标签垄断）。

        任何一条成立即进入评估（评不评得过另说）：
          a) 有具体可讲的内容：basis 含经历/情绪/未知（值得分享的发现、
             过程、进展——哪怕与用户无直接关系，知识本身可分享）；
          b) 社交语境在场：user_relevance / social_relevance /
             emotion_present 任一过线（与用户有关、或带着想靠近的情绪，
             即使事实细节还薄）；
          c) 明确的新联想：basis 含未验证假设——作为"标注不确定的想法"
             分享是合法形态（v2 询问/陈述证据闸负责守住不冒充事实）。
        空泛（无内容、无社交、无假设）的念头三条路都不沾 → 不进评估；
        顶着 communication 标签的空话同样被 v2 证据闸拒（不双重扣：
        这里 OR 判"有无任一路价值"，v2 判"这次说不说"，职责不同）。"""
        ea = n.extra_attrs or {}
        ev = self._basis_evidence(ea.get("basis") or [])
        if ev["episodic"] or ev["emotion"] or ev["unknown"]:
            return True
        ex = ea.get("explain") or {}
        social = max(float(ex.get("user_relevance") or 0.0),
                     float(ex.get("social_relevance") or 0.0),
                     0.5 * float(ex.get("emotion_present") or 0.0))
        if social >= 0.25:
            return True
        with self.kg._lock:
            for b in (ea.get("basis") or []):
                nd = self.kg.nodes.get(str(b))
                if nd is not None and str(
                        (nd.extra_attrs or {}).get("type") or "") == "hypothesis":
                    return True
        return False

    def _expression_candidates(self):
        """v2 的候选池：沟通类照旧全量进评估（时机由四闸定，空泛内容由
        资格判定挡）；非沟通类念头**若内容合格也获得评估机会**——标签不再
        垄断表达资格。非沟通候选在进入前补齐表达家族（复用 _promote_goal
        的图谱规则：basis 构成决定陈述/询问/共情，幂等，非新机制）。"""
        cis = self._active_cis()
        seen = {n.id for n in cis}
        with self.kg._lock:
            extra = [n for n in self.kg.nodes.values()
                     if (n.extra_attrs or {}).get("type") == "intention"
                     and (n.extra_attrs or {}).get("status") == ST_READY
                     and n.id not in seen]
        for n in extra:
            if not self._share_eligible(n):
                continue
            try:
                if not (n.extra_attrs or {}).get("illocutionary_act"):
                    self._promote_goal(n)      # 定表达家族（纯图谱规则）
                cis.append(n)
            except Exception:                  # noqa: BLE001
                logger.debug("[CC] 候选家族推导失败: %s", n.id,
                             exc_info=True)
        return cis

    def _decay_intentions(self):
        """意图衰减/晋升/丢弃。ready 未达表达阈值 = WAIT（自然滞留）。
        衰减出局 → 反思压力（说过/想做而没做到的念头会攒疑问）。"""
        with self.kg._lock:
            for n in list(self.kg.nodes.values()):
                ea = n.extra_attrs or {}
                if ea.get("type") not in self._INTENTION_TYPES:
                    continue
                st = ea.get("status")
                if st in (ST_EXPRESSED, ST_DISCARDED):
                    continue
                # v2：DEFER 过期出口——距最后一次实质变化（强化会刷新时钟）
                # 超过 expression_defer_max_s 仍未表达 → DISCARD(stale)。
                # 暂缓不再是无限期滞留：相关性消失由衰减管，长尾由这里管。
                if bool(self.config.get("expression_decision_v2", False)):
                    _last = float(ea.get("last_change_ts") or ea.get("born_ts") or 0.0)
                    _maxw = float(self.config.get("expression_defer_max_s", 1800))
                    if _last and time.time() - _last > _maxw:
                        ea["status"] = ST_DISCARDED
                        ea["discarded_at"] = now_str()
                        ea["discard_reason"] = "stale_defer"
                        self._evo.note_node_updated(n.id, {"status": ST_DISCARDED})
                        logger.info(f"[CC] 意图丢弃: {n.id} kind={ea.get('kind')} "
                                    f"(DEFER 超过最大等待时长，过期)")
                        continue
                # B5/§5 出生拍豁免：沟通类在形成拍的同一脉冲里就会被 ×
                # decay_per_pulse 咬掉（0.79/0.77/0.60 出生即濒死的根因）。
                # 只豁免"不吃这一口衰减"——晋升/淘汰照常评估；EXPRESSED
                # 是终态，双表达仍不可能。
                born_exempt = (ea.get("type") == "communication_intention"
                               and ea.get("born_pulse") == self._pulse_seq)
                if not born_exempt:
                    # 反刍固化（2026-10-16）：反复被重新拿起焦点的念头衰减更慢。
                    # 此前半衰期 ~12 拍（约 3 分钟）与表达时序错配——实锤案例：
                    # intensity 0.80 的念头 14 分钟凉到 act 0.12（reinforced=12
                    # 仍救不回），评估窗口每拍都在但分数永远过不了线。被强化
                    # 越多次的念头该越长寿（每次重温和巩固），从没再想到的照常
                    # 消散——不新增阈值，只把衰减率向 1 方向按次数收敛。
                    r_n = int(ea.get("reinforced", 0) or 0)
                    damp = 1.0 - min(0.6, 0.05 * r_n)
                    eff_decay = 1.0 - (1.0 - float(
                        self.cfg["decay_per_pulse"])) * damp
                    ea["activation"] = round(
                        float(ea.get("activation", 0)) * eff_decay, 4)
                if ea["activation"] >= self.cfg["form_threshold"] \
                        and st == ST_FORMING:
                    self._promote_goal(n)
                if ea["activation"] < self.cfg["discard_below"]:
                    ea["status"] = ST_DISCARDED
                    ea["discarded_at"] = now_str()
                    self._evo.note_node_updated(n.id, {"status": ST_DISCARDED})
                    logger.info(f"[CC] 意图丢弃: {n.id} kind={ea.get('kind')} "
                                f"(激活衰减出局)")
            dead = [n for n in self.kg.nodes.values()
                    if (n.extra_attrs or {}).get("status") == ST_DISCARDED
                    and (n.extra_attrs or {}).get("discarded_at")
                    and not (n.extra_attrs or {}).get("pressure_counted")]
            for n in dead:
                n.extra_attrs["pressure_counted"] = True
        if dead:
            for _ in dead:
                self.note_pressure("intention_lost")

    def _prune_history(self):
        with self.kg._lock:
            cis = [n for n in self.kg.nodes.values()
                   if (n.extra_attrs or {}).get("type") in self._INTENTION_TYPES]
            if len(cis) <= MAX_CI_NODES:
                return
            cis.sort(key=lambda n: n.extra_attrs.get("created", ""))
            for n in cis[:len(cis) - MAX_CI_NODES]:
                cid = n.id
                self.kg.edges = [e for e in self.kg.edges
                                 if e.src != cid and e.dst != cid]
                del self.kg.nodes[cid]

    # ── 表达决策（图谱+抑制分，非 LLM）────────────────────

    def _evaluate_expression(self):
        best, best_val = None, 0.0
        now = time.time()
        cooldown_ok = now - self._last_express_ts >= self.cfg["inhibition_cooldown_s"]
        hour_expr = [t for t in self._express_count_hour if now - t < 3600]
        # 表达抑制调制化（2026-09-21）：300s 冷却/每小时上限等"固定社交
        # 规则"拆除——融合成一个连续的 recent_expression 通道（小时密度 +
        # 刚说完的指数衰减）喂给 express_threshold 调制；只保留一个调度
        # floor（最小间隔，防抽风）。有强社交/意图支撑时，她可以连续说话。
        _decay = 0.0
        if self._last_express_ts:
            _decay = __import__("math").exp(
                -(now - self._last_express_ts) / 300.0)
        if self.drive_evaluator is not None:
            try:
                self.drive_evaluator.set_context_value(
                    "recent_expression",
                    min(1.0, len(hour_expr) / 6.0 * 0.6 + _decay * 0.6))
            except Exception:
                pass
        # ── v2 决策（flag 门控，默认关=线上行为与旧实现逐字一致）──
        if bool(self.config.get("expression_decision_v2", False)):
            return self._evaluate_expression_v2(now, cooldown_ok, len(hour_expr))
        for ci in self._active_cis():
            ea = ci.extra_attrs
            if ea.get("status") != ST_READY:
                continue
            rich = False
            with self.kg._lock:
                for b in ea.get("basis", []):
                    bn = self.kg.nodes.get(b)
                    if bn and (bn.graph_space == "episodic"
                               or (bn.extra_attrs or {}).get("type") == "emotion"):
                        rich = True
                        break
                    # 2026-10-24 放宽：高激活概念（≥1.0）也算"有内容"。
                    # 依据：Berntsen 2021 自发记忆综述——抽象/语义概念线索
                    # 足以独立触发值得表达的念头，不依赖新事件；线索超载
                    # 原理保证过滤性——路过概念激活通常 <0.5，只有真正
                    # "烧着"的联想（假设研究、DeepSeek 1.97 这类）过线。
                    # 此前 277 次/日的资格拒绝全灭她的概念型念头。
                    if bn and bn.graph_space == "semantic" \
                            and float(bn.activation or 0) >= 1.0:
                        rich = True
                        break
            if not rich:
                ea["expression_eval"] = {"suppressed": "basis lacking concrete tension"}
                self._log_express_eval(ci, {
                    "verdict": "defer", "reason": "eligibility_no_evidence",
                    "content_class": "statement",
                    "evidence": self._basis_evidence(ea.get("basis", []))}, now)
                self._defer_to_interest(ci, "deferred_no_evidence")
                continue
            expr = float(ea.get("activation", 0))
            supp = 0.0
            if not cooldown_ok:
                supp += 0.4   # 最小间隔 floor（调度防抽风，非社交规则）
            if self._last_outcome_negative:
                _nw = __import__("math").exp(
                    -(now - (self._last_outcome_ts or 0)) / 1800.0)
                supp += 0.3 * _nw   # 上次被叫停→抑制，随时间自然褪色（20:0x
                # 校准：此前无衰减，一次呵止全天噤声——132 条评估全被 +0.3 压死）
            explain = {"expression_score": round(expr, 3),
                       "suppression_score": round(supp, 3),
                       "cooldown_floor_ok": cooldown_ok}
            ea["expression_eval"] = explain
            val = expr - supp
            _bar = self._mod_th("cognition.express_threshold",
                                float(self.cfg["express_threshold"]))
            # 调制上限：情绪/情境最多把门槛抬 0.05——此前深夜可抬到 0.839
            # （高于 CI 出生分），造成"越没人陪越永远不开口"的叠加静默。
            _bar = min(_bar, float(self.cfg["express_threshold"]) + 0.05)
            _evd = self._basis_evidence(ea.get("basis", []))   # 仅日志摘要
            if val >= _bar and val > best_val:
                best, best_val = ci, val
                self._log_express_eval(ci, dict(explain, verdict="express",
                    reason="statement_bar_met", content_class="statement",
                    bar=round(float(_bar), 3), evidence=_evd), now)
            else:
                self._log_express_eval(ci, dict(explain, verdict="defer",
                    reason="below_bar", content_class="statement",
                    bar=round(float(_bar), 3), evidence=_evd), now)
                self._defer_to_interest(ci, "deferred_below_bar")
        return best, best_val

    def _defer_to_interest(self, ci, reason):
        """表达被暂缓的探索型意图不空等衰减出局（ACT-R：亚阈值念头转为
        低成本内部动作优于丢弃——内部记录动作的期望效用为正；Berntsen
        2021：未解决线索经持续启动更易自发重现）。两步，全部复用既有机制：
        ① 兴趣记号（curiosity note_interest "signal"，目标概念水位抬升）；
        ② 图谱内探索播种（engine.mark_active 把暂缓概念推进活跃前沿，
        下一拍扩散从它出发——Synapse 2026 的 activation-based traversal：
        经既有侧抑制/时间衰减过滤点亮相关记忆与共锚概念；共锚配对由
        生活拍的 _emerge_hypotheses 接手生成"待验证联想"候选假设，
        置信 0.3、hypothesis_leg 标记、无新证据不强化——推测与事实分野
        由既有假设节点语义承担）。每意图只播种一次（防重复遍历/循环）。
        不新增配置、不改衰减、不引入 LLM。"""
        try:
            ea = ci.extra_attrs
            if str(ea.get("kind") or "") != "exploration":
                return
            if ea.get("explore_seeded"):
                return
            ea["explore_seeded"] = True
            from curiosity_engine import note_interest
            seeds = []
            with self.kg._lock:
                for b in (ea.get("basis") or [])[:3]:
                    if self.kg.nodes.get(b):
                        # "signal"=又遇到（合法枚举）：念头反复浮现本身
                        # 就是兴趣信号；reason 只进日志。
                        note_interest(self.kg, b, "signal", self.config)
                        seeds.append(b)
                        break
            if seeds and getattr(self, "engine", None) is not None:
                self.engine.mark_active(seeds)
                logger.info("[CC] 暂缓意图转图谱内探索: %s (%s) 播种 %s",
                            ci.id, reason, seeds)
        except Exception:                          # noqa: BLE001
            logger.debug("[CC] 暂缓→兴趣转化失败（忽略）: %s", ci.id,
                         exc_info=True)

    # ── v2：显著性/事实置信（证据）/社交动机/表达成本 四轴分离决策 ──────

    def _basis_evidence(self, basis) -> dict:
        """basis 证据普查（决策的"事实置信"轴的可得部分）。
        语义诚实：这里只有**证据在场性**（经历过/有情绪标记/挂着未知），
        没有语义级的事实正确度——后者当前系统不存在，标记 unavailable
        由 _express 的 NO_SPEAK 哨兵兜底，不伪装成数值置信度。"""
        from graph_model import is_live_unknown_id
        out = {"episodic": False, "emotion": False, "unknown": False,
               "concept_hot": False}
        with self.kg._lock:
            for b in basis or []:
                bn = self.kg.nodes.get(b)
                if bn is None:
                    continue
                if bn.graph_space == "episodic":
                    out["episodic"] = True
                # 2026-10-24：高激活概念（≥1.0）也是"有内容"（Berntsen
                # 2021 概念线索；与 v1 资格门同一判据，两路径一致）
                if bn.graph_space == "semantic" \
                        and float(bn.activation or 0) >= 1.0:
                    out["concept_hot"] = True
                if (bn.extra_attrs or {}).get("type") == "emotion":
                    out["emotion"] = True
                try:
                    if is_live_unknown_id(self.kg, b):
                        out["unknown"] = True
                except Exception:                    # noqa: BLE001
                    pass
        return out

    def _motivation_present(self, axis: str):
        """动机轴：读现有场信号（drive.curiosity / drive.social），不新增机制。
        读数不可得（无 drive_evaluator/异常）→ (True, "unavailable")：
        观测缺失不拦截决策；信号真实为零才拦截（fail-open 只针对不可知）。"""
        de = self.drive_evaluator
        if de is None:
            return True, "unavailable"
        try:
            sig = self._cognitive_snapshot()
            lvl = float((sig.get("drive") or {}).get(axis, 0.0) or 0.0)
            return lvl > 0.05, f"drive.{axis}={lvl:.2f}"
        except Exception:                            # noqa: BLE001
            return True, "unavailable"

    def note_spoken(self, now: float = None):
        """被动回复更新"她刚说过话"的时刻（2026-10-18 修正后语义）：
        只占用**短冷却**与上下文新鲜度——刚答完几秒内主动不插嘴（21:13:29
        回复/21:13:33 主动重复播报的实锤由此挡住）。但**不再消耗主动分享
        的小时限额**：聊得投入不等于失去主动分享能力，限额管的是主动打扰
        的频率，不是说话总量。"""
        ts = now if now is not None else time.time()
        self._last_express_ts = max(float(self._last_express_ts or 0.0), ts)

    def _stamp_shared(self, ci, now: float):
        """把"这些材料最近讲过了"盖在 **basis 节点本身**上（2026-10-18）：
        CI 会被剪枝、会被新 CI 替换，长生话题（假设/经历节点）才是复读
        检测真正该依赖的记忆——念头跨 CI 复活时，身份连续性由图上这些
        戳记承担，不靠时间窗猜。戳记带上当时的交流目的与原料组合，
        使"这条料按这个讲法讲过"与"这条料在别的语境用过"可区分，
        不误伤合理的延伸。"""
        ea0 = ci.extra_attrs or {}
        goal = str(ea0.get("reply_goal") or "")
        basis = [str(b) for b in (ea0.get("basis") or [])]
        with self.kg._lock:
            for b in basis:
                n = self.kg.nodes.get(b)
                if n is None:
                    continue
                ea = n.extra_attrs
                if ea is None:
                    n.extra_attrs = ea = {}
                ea["last_shared_ts"] = now
                ea["last_shared_goal"] = goal
                ea["last_shared_basis"] = basis[:8]

    def _node_born(self, n) -> float:
        """节点入图时刻（epoch）：created 是 "YYYY/MM/DD HH:MM:SS" 串。
        解析失败 → 0（视为极旧，宁可漏认不可假新）。"""
        raw = getattr(n, "created", None)
        if not raw:
            return 0.0
        try:
            import datetime as _dt
            return _dt.datetime.fromisoformat(
                str(raw).replace("/", "-").replace(" ", "T")).timestamp()
        except Exception:                         # noqa: BLE001
            return 0.0

    def _is_duplicate_recent(self, ci, now: float, window_s: float) -> bool:
        """去重 = **内容身份判定**，不是时间窗猜（2026-10-18 根因修复）。

        旧实现的失效模式：CI 会被剪枝、长寿命假设会被新证据复活成全新
        CI——任何固定窗（30min 近窗、4h 不应期）都只是"隔多久算重复"的
        猜测，被复活周期一绕一个准（00:35→03:16 六连换皮、15:15→19:08
        全文复读实锤）。现在"讲过没有"记在材料节点本身（_stamp_shared）：

          · 任一 basis 材料**从未被分享过**，或**诞生在上次分享之后**
            （用户的新发言、逛到的新经历、新证据、新假设）→ 有新原料，
            这是延伸不是复读——直接放行，不需要等任何冷却窗；
          · 全部原料都带着"分享戳晚于其诞生"→ 一锅冷饭，无论隔 4 分钟
            还是 4 小时都判复读；
          · 念头自身的出生时刻**不算**新料（复活≠新信息）。

        另有比分享更早的兜底近窗：同 goal+basis 重叠≥0.5 在 window_s
        （30min，本轮之前就存在的节流）内刚表达过 → 判重。它只在上面
        判不出"新原料"时作为第二道保险。"""
        ea = ci.extra_attrs
        goal = str(ea.get("reply_goal") or "")
        basis = [str(b) for b in (ea.get("basis") or [])]
        if not goal or not basis:
            return False
        bset = set(basis)
        with self.kg._lock:
            known_material = 0
            all_told = True
            for b in basis:
                n = self.kg.nodes.get(b)
                na = (n.extra_attrs or {}) if n is not None else {}
                shared = float(na.get("last_shared_ts") or 0.0)
                if n is None or not shared:
                    # 悬空或从未分享 → 这块料是新的（或判不了）——判不了
                    # 就不误伤（老纪律），按新料放行
                    all_told = False
                    break
                known_material += 1
                if str(na.get("last_shared_goal") or "") != goal:
                    all_told = False              # 上次是别的交流目的讲它
                    break
                sb = set(str(x) for x in (na.get("last_shared_basis") or []))
                if sb and len(sb & bset) / max(len(sb | bset), 1) < 0.5:
                    all_told = False              # 同一块料，不同配方
                    break
                if self._node_born(n) > shared:
                    all_told = False              # 分享之后材料自己又更新过
                    break
            if all_told and known_material:
                return True                       # 同族原配方全旧料 = 复读
            # 有（或疑似有）新原料 → 保留原有的 30min 同族近窗节流
            for n in self.kg.nodes.values():
                e = n.extra_attrs or {}
                if n is ci or e.get("type") not in self._INTENTION_TYPES:
                    continue
                if e.get("status") != ST_EXPRESSED:
                    continue
                if str(e.get("reply_goal") or "") != goal:
                    continue
                ts = float(e.get("expressed_at_ts") or 0.0)
                if not ts or now - ts > window_s:
                    continue
                ob = set(str(x) for x in (e.get("basis") or []))
                if ob and len(ob & bset) / max(len(ob | bset), 1) >= 0.5:
                    return True
        return False

    def _evaluate_expression_v2(self, now, cooldown_ok, hour_count):
        """表达决策 v2。四类判定（verdict）：
          express   现在值得说           defer  时机/证据未熟（继续滞留，
          suppress  成本轴硬约束          discard 由 _decay_intentions 的
                 （限额/重复）                   stale/衰减分支负责过期）
        轴与门的对应：
          资格（证据在场）→ 陈述类必须有 episodic/emotion；询问类必须踩在
            未知标记上——问"我不知道的东西"本身不需要事实置信。
          动机 → 询问要好奇心在场；分享/共情要社交轴在场。动机读数不可得
            时放行并标注（观测缺失 ≠ 动机为零）。
          显著性 → 陈述走原 0.78 调制线（不动）；询问走 form_threshold
            调制线——它不断言任何事实，风险只在打扰，而打扰归成本轴管。
          成本 → 冷却 floor/负反馈（沿用 v1 的抑制分量）+ 小时限额 +
            同目标去重。"""
        bar_stmt = self._mod_th("cognition.express_threshold",
                                float(self.cfg["express_threshold"]))
        # 调制上限（2026-10-24，与 v1 同规）：情绪/情境最多抬 0.05——
        # 实测深夜 v2 调制线到 0.862，而 CI 出生分 ~0.75，结构性永不达线。
        bar_stmt = min(bar_stmt, float(self.cfg["express_threshold"]) + 0.05)
        bar_inq = self._mod_th("cognition.form_threshold",
                               float(self.cfg["form_threshold"]))
        dedup_win = float(self.config.get("expression_dedup_window_s", 1800))
        cap = int(self.cfg.get("max_expressions_per_hour", 6))
        best, best_val = None, 0.0
        # 候选池升级（2026-10-17 解除标签垄断）：沟通类逐字照旧（含空泛
        # 内容由下方证据闸拒绝），非沟通类**内容合格者**也在池中——标签
        # 不再决定谁能被评估，证据/相关性在候选入口判定一次，下方各闸
        # 只管时机与成本，同一判据不重复扣分。
        for ci in self._expression_candidates():
            ea = ci.extra_attrs
            if ea.get("status") != ST_READY:
                continue
            ev = self._basis_evidence(ea.get("basis", []))
            goal = str(ea.get("reply_goal") or "")
            inquiry = goal == "information_seeking"
            salience = float(ea.get("activation", 0))
            # SN 接入表达评估（2026-10-15）：近期场显著性余温作为乘性增益
            # （上限 +15%）——值得表达的内容更容易挣到机会，但**高显著
            # 不能白送**：bar、资格、成本闸全部照旧（乘的是分数不是门槛）。
            try:
                from cognitive_field import salience_network as _sn_g
                _snx = _sn_g(None)
                if _snx.enabled:
                    salience *= (1.0 + 0.15 * _snx.arousal(now))
            except Exception:                     # noqa: BLE001
                pass
            supp, why = 0.0, []
            if not cooldown_ok:
                supp += 0.4
                why.append("cooldown_floor")
            if self._last_outcome_negative:
                _nw2 = __import__("math").exp(
                    -(now - (self._last_outcome_ts or 0)) / 1800.0)
                supp += 0.3 * _nw2
                why.append("negative_feedback")
            val = salience - supp
            if hour_count >= cap:
                verdict, reason = "suppress", "rate_limit_hour"
            elif self._is_duplicate_recent(ci, now, dedup_win):
                verdict, reason = "suppress", "duplicate_recent"
            elif inquiry:
                mot, msrc = self._motivation_present("curiosity")
                if not (ev["unknown"] or ev["episodic"] or ev["concept_hot"]):
                    verdict, reason = "defer", "inquiry_without_grounding"
                elif not mot:
                    verdict, reason = "defer", "no_curiosity_motivation"
                elif val >= bar_inq:
                    verdict, reason = "express", "inquiry_bar_met"
                else:
                    verdict, reason = "defer", "below_inquiry_bar"
            else:
                if not (ev["episodic"] or ev["emotion"] or ev["concept_hot"]):
                    verdict, reason = "defer", "eligibility_no_evidence"
                elif goal in ("follow_up", "empathize"):
                    mot, msrc = self._motivation_present("social")
                    if not mot:
                        verdict, reason = "defer", "no_social_motivation"
                    elif val >= bar_stmt:
                        verdict, reason = "express", "statement_bar_met"
                    else:
                        verdict, reason = "defer", "below_bar"
                elif val >= bar_stmt:
                    verdict, reason = "express", "statement_bar_met"
                else:
                    verdict, reason = "defer", "below_bar"
            ea["expression_eval"] = {
                "verdict": verdict, "reason": reason,
                "decision": "v2",
                "expression_score": round(val, 3), "salience": round(salience, 3),
                "suppression_score": round(supp, 3),
                "bar": round(bar_inq if inquiry else bar_stmt, 3),
                "content_class": "inquiry" if inquiry else "statement",
                "evidence": ev, "cooldown_floor_ok": cooldown_ok,
                "suppression_terms": why}
            self._log_express_eval(ci, ea["expression_eval"], now)
            if verdict == "defer":
                self._defer_to_interest(ci, reason)
            if verdict == "express" and val > best_val:
                best, best_val = ci, val
        return best, best_val

    def _log_express_eval(self, ci, ev: dict, now: float):
        """逐拍表达评估记录（fas_log COGNITION 通道，随既有轮转策略）。
        只记 READY 候选（活跃上限 3），载荷不含用户原文/密钥；
        basis 只记证据在场性摘要，可按 ci_id 还原完整生命周期。"""
        try:
            import fas_log
            _ev = dict(ev)
            _ev.pop("evidence", None)
            fas_log.get_logger(fas_log.COGNITION).info(
                "express_eval",
                f"{ci.id} {_ev.get('verdict')}/{_ev.get('reason')}",
                ci=ci.id, kind=str((ci.extra_attrs or {}).get("kind")),
                evidence=",".join(k for k, v in
                                  (ev.get("evidence") or {}).items() if v)
                or "none",
                **_ev)
        except Exception:                            # noqa: BLE001
            pass

    # ── 反思压力（pressure-driven reflection，2026-09-20）─────────
    # 各信号源（行动失败/负反馈/预测误差/意图消散/新经验）把压力写进图上
    # 一个持续节点；压力够高才进入离线反思——时间只是 cooldown 下限，
    # 不再是触发器本身。节点激活靠现有 cognitive 空间衰减自然消退。

    def _pressure_cfg(self) -> dict:
        return (self._loop_cfg.get("pressure") or {})

    def note_pressure(self, source: str, amount: float = None):
        """压力信号注入（图节点 activation，上限封顶防滚雪球）。"""
        pcfg = self._pressure_cfg()
        if amount is None:
            amount = float((pcfg.get("sources") or {}).get(source, 0.0))
        if amount <= 0:
            return
        pid = str(pcfg.get("node") or "反思压力")
        cap = float(pcfg.get("max_inject", 2.5))
        with self.kg._lock:
            node = self.kg.get_node(pid)
            if node is None:
                node = Node(id=pid, weight=0.5, label="declarative-semantic",
                            graph_space="cognitive",
                            extra_attrs={"type": "cognitive_pressure",
                                         "canon": "state",
                                         "sources": {}})
                self.kg.add_node(node)
            node.activation = min(5.0, float(node.activation or 0.0) + amount)
            srcs = dict(node.extra_attrs.get("sources") or {})
            srcs[source] = round(float(srcs.get(source, 0)) + amount, 3)
            node.extra_attrs["sources"] = srcs
            node.extra_attrs["last_source"] = source
            node.touch()
        if self.engine is not None:
            try:
                self.engine.mark_active([pid])
                self.engine.register_activation_source([pid], "internal_drive")
            except Exception:
                pass
        if self.engine is not None and cap and amount > cap:
            logger.debug("[CC] 压力注入超上限（已由 activation min 封顶）")

    def pressure_value(self) -> float:
        pcfg = self._pressure_cfg()
        with self.kg._lock:
            node = self.kg.get_node(str(pcfg.get("node") or "反思压力"))
            return float(node.activation or 0.0) if node else 0.0

    def note_outcome(self, negative: bool):
        """由 app.py 在 outcome 标注处回调：用户正反馈解除抑制，负反馈加强。"""
        self._last_outcome_negative = negative
        self._last_outcome_ts = time.time()
        if negative:
            self.note_pressure("negative_feedback")

    # ── 表达（唯一 LLM 调用点）────────────────────────────

    _SELF_ACTORS = ("self", "haru")     # 历史兼容：旧战报曾写 actor="haru"
    _RUN_RESULT_ZH = {"victory": "赢了", "defeat": "输了",
                      "aborted": "中途停下"}

    def _raw_dialog(self, k=6):
        """近期真实对话的原文+说话人+时刻（chat_log）。主动话语带"我主动
        说过"标记——她要知道自己已问过什么，语言层不再从节点反猜。"""
        if not self.chat_log:
            return None
        try:
            lines = []
            for e in self.chat_log.recent(n=k):
                tm = str(e.get("time") or "")[11:16]
                ui = str(e.get("user_input") or "")
                sr = str(e.get("system_response") or "")
                if e.get("proactive"):
                    if sr:
                        # 防复述由专段「我最近已经说出口的话」负责（全文级）；
                        # 本窗只留大意占位——主动话全文在这里进两次同一 prompt
                        # 时，模型会拿自己的旧独白接着编（10-21 实锤：窗口 6 条
                        # 里 5 条是她的"被看见"独白，心理可见性×8）。
                        lines.append(f"- {tm} 我主动说过（内容见防复述段）：{sr[:24]}…")
                    continue
                if ui and not ui.startswith(("(主动)", "(FAS")):
                    lines.append(f"- {tm} 用户说：{ui[:90]}")
                if sr:
                    lines.append(f"- {tm} 我答：{sr[:90]}")
            return lines or None
        except Exception:                            # noqa: BLE001
            return None

    def _life_events(self, k=8):
        """近期真实行动记录（experience_timeline 的 ACTION 事件，带主体）。
        对话类 say/communicate 跳过——原文已在对白层，重复注入只会挤预算。"""
        tl = getattr(self, "timeline", None)
        try:
            from experience import EVENT_ACTION
            out = []
            for e in (tl.recent(n=40) if tl is not None else []):
                if e.get("event_type") != EVENT_ACTION:
                    continue
                subj = str(e.get("subject") or "")
                if subj in ("say", "communicate"):
                    continue
                act = str(e.get("actor") or "")
                who = ("我" if act in self._SELF_ACTORS
                       else "用户" if act == "user" else (act or "?"))
                tm = str(e.get("ts_str") or "")
                c = e.get("content") or {}
                if subj == "sts2_run":
                    boot = "，是我自己决定开的" if c.get("self_booted") else ""
                    out.append(f"- {tm} {who}玩了杀戮尖塔2："
                               f"{self._RUN_RESULT_ZH.get(str(c.get('result')), c.get('result'))}"
                               f"，打到第 {c.get('floor')} 层{boot}")
                else:
                    txt = str(c.get("text") or c.get("change") or "")[:60]
                    out.append(f"- {tm} {who} {subj}" + (f"：{txt}" if txt else ""))
                if len(out) >= k:
                    break
            # 台账标题级并流（2026-10-19）：浏览/调研不写 ACTION 账本，
            # 曾被叙述成"没有做任何事"。台账里真实记录过的活动（标题级）
            # 补进同一事实段；只列已记录的，不虚构、不要求登记内部节拍。
            # 台账路径由装配层显式注入（cc.ledger_path）：认知核不猜
            # 部署布局，测试天然隔离生产数据。
            try:
                import os as _os
                import json as _json
                lp = getattr(self, "ledger_path", None)
                if lp and _os.path.exists(lp):
                    acts = (_json.load(open(lp, encoding="utf-8"))
                            .get("activities") or {})
                    items = (list(acts.values()) if isinstance(acts, dict)
                             else list(acts))
                    for a in sorted(items, key=lambda x: float(
                            x.get("updated") or 0), reverse=True):
                        st_ = str(a.get("state") or "")
                        ts_ = float(a.get("updated") or a.get("created") or 0)
                        if st_ == "cancelled" or (time.time() - ts_) > 6 * 3600:
                            continue
                        topic = str(a.get("topic") or "")[:24]
                        if not topic:
                            continue
                        out.append("- %s 台账：%s" % (
                            time.strftime("%H:%M",
                                          time.localtime(ts_)), topic))
                        if len(out) >= k:
                            break
            except Exception as _le:                 # noqa: BLE001
                logger.debug("[CC] 台账并流失败（忽略）: %r", _le)
            return out or None
        except Exception:                            # noqa: BLE001
            return None

    def _recent_spoken(self, window_s: float = None):
        """她近期真正说出口的话（epoch, 文本, 展示时刻）——**主动表达与
        被动回复都算**（2026-10-17 修复：18:11 主动逐字复读 18:10 的被动
        答案，因为回声材料只收 EXPRESSED CI、看不见 answer_question 写进
        chat_log 的被动回复）。窗口默认取表达去重窗，与硬闸同源。"""
        if window_s is None:
            window_s = float(self.config.get(
                "expression_dedup_window_s", 1800))
        now = time.time()
        out = []
        with self.kg._lock:
            for n in self.kg.nodes.values():
                ea = n.extra_attrs or {}
                if str(ea.get("type") or "") == "communication_intention" \
                        and ea.get("status") == "expressed" \
                        and str(ea.get("expressed_text") or ""):
                    ts = float(ea.get("expressed_at_ts") or 0)
                    if now - ts <= window_s:
                        out.append((ts, str(ea["expressed_text"]),
                                    str(ea.get("expressed_at") or "")))
        if self.chat_log:
            try:
                import datetime as _dt
                for e in self.chat_log.recent(n=12):
                    sr = str(e.get("system_response") or "").strip()
                    if not sr:
                        continue
                    iso = str(e.get("time") or "")
                    try:
                        ets = _dt.datetime.fromisoformat(iso).timestamp()
                    except Exception:               # noqa: BLE001
                        continue
                    if now - ets <= window_s:
                        out.append((ets, sr, ets and iso[11:16]))
            except Exception:                        # noqa: BLE001
                pass
        # 按文本去重（同一句可能既是主动 EXPRESSED 又在 chat_log）
        seen, dedup = set(), []
        for item in sorted(out, key=lambda x: -x[0]):
            key = "".join(str(item[1]).split())
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
        return dedup

    def _said_recent(self, k=3):
        """回声防御材料（LLM 侧）：告诉她哪些话已经讲过，由她自行不再复述
        ——被动回复同样计入（_recent_spoken）。"""
        return [(t[:120], ts) for _e, t, ts in self._recent_spoken()[:k]]

    def _spoken_ledger(self, k: int = 24):
        """她最近说出口的话（主动+被动）取 k 条，**不设时限窗**
        （2026-10-19 补账）。旧硬闸只拿 30min 窗内的话比全文相等——
        10:04→10:38 恰好隔 34 分钟、前两句**逐字**复用，窗把证据放过。
        复读不因隔得久而成立：这条账本只认一个事实——这段**字面**她
        说过；话题有没有新证据是基座身份去重（_is_duplicate_recent）
        的职责，两条线各管各的，都不靠猜时间。"""
        out = []
        with self.kg._lock:
            for n in self.kg.nodes.values():
                ea = n.extra_attrs or {}
                if str(ea.get("type") or "") == "communication_intention" \
                        and ea.get("status") == "expressed" \
                        and str(ea.get("expressed_text") or ""):
                    out.append((float(ea.get("expressed_at_ts") or 0),
                                str(ea["expressed_text"])))
        if self.chat_log:
            try:
                import datetime as _dt
                for e in self.chat_log.recent(n=k):
                    sr = str(e.get("system_response") or "").strip()
                    if not sr:
                        continue
                    iso = str(e.get("time") or "")
                    try:
                        ets = _dt.datetime.fromisoformat(iso).timestamp()
                    except Exception:               # noqa: BLE001
                        ets = 0.0
                    out.append((ets, sr))
            except Exception:                       # noqa: BLE001
                pass
        out.sort(key=lambda x: -x[0])
        seen, dedup = set(), []
        for _ts, t in out:
            key = "".join(str(t).split())
            if key in seen:
                continue
            seen.add(key)
            dedup.append((_ts, t))
            if len(dedup) >= k:
                break
        return dedup

    _GOAL_NAT = {  # reply_goal → 自然语言（机制标签不外显）
        "empathize": "我想靠近一点，回应他刚才说的",
        "information_seeking": "我有件事想问他",
        "follow_up": "我想接着之前聊的事再说两句",
        "share_related_knowledge": "我碰上了点东西，想分享给他",
    }

    def build_proactive_user(self, ci, ctx: str, raw_dialog=None) -> str:
        """主动表达的用户侧 prompt（纯函数：不碰 LLM，可直接断言）。
        2026-10-16 重设计：不再"把指定内容说出来"，也不再把激活度/言外
        行为/对话行为等机制数值与标签塞给语言层——给事实、给状态、给
        一句意图说明，说什么/怎么说/说不说由她综合决定。
        2026-10-20：加入**说话场景**块（scene_for_ci 派生自 basis+对话
        原文）——场景参与定调而非只当标签：它不删任何素材，只说明
        "这次话落在偶遇的小事上还是延续聊天上"，深浅权随之不同。"""
        ea = ci.extra_attrs or {}
        goal = self._GOAL_NAT.get(str(ea.get("reply_goal") or ""),
                                  "心里有点东西，想自然地聊两句")
        _scene, _tone = scene_for_ci(ci, raw_dialog, self.kg)
        ea["scene"] = _scene      # 场景随 CI 留痕（气泡/审计可查这次话在哪定的调）
        return redact_internal_state_names(
            f"{ctx}\n\n"
            f"【这次说话的场景】{_scene}——{_tone}\n\n"
            f"【这次想开口的缘由】{goal}。"
            "这只是驱力的描述，不是必须执行的脚本。\n\n"
            "先理解上面的信息：谁说了什么、谁做了什么，哪些是真实记录、"
            "哪些只是联想或旧背景；再像跟熟悉的人相处那样，自然决定"
            "此刻要不要说、说什么、怎么说。说出口的内容要让**看不到你"
            "屏幕的人**对得上：名词、引句、外文片段，要么带一句对方猜得"
            "着的来由或大意，要么就把「没点开/没看懂」本身当话头——单独甩"
            "一个对方无从理解的残句，等于没说。没有值得说的就只回复"
            "NO_SPEAK（别的不写），沉默是合法的回答。")

    def _debug_graph_for(self, ci) -> dict:
        """调试视图（2026-10-19）：这条话**所用的图谱**=basis + 全部热节点。

        与 render_cognitive_state 的切片同一套取数规则（basis[:8] 打头，
        补 declarative 且 act≥0.3 的热节点降序补足，合计 ≤12；边在这批
        节点内部连），并给每个节点标 role=basis|hot——12:47/16:33 两次
        "话与 basis 对不上"的错位，以后在气泡里直接可见：登记的和语言层
        实际读到的材料一并摊开。纯只读；异常返回 None，降级为无图。"""
        try:
            ea = ci.extra_attrs or {}
            basis = [str(b) for b in (ea.get("basis") or [])][:8]
            with self.kg._lock:
                hot = sorted(
                    ((float(getattr(n, "activation", 0.0) or 0.0),
                      str(n.id)) for n in self.kg.nodes.values()
                     if str(getattr(n, "label", "") or "").startswith(
                         "declarative")
                     and not is_modulator_node(n)
                     and not is_content_scaffold(n)
                     and not is_internal_trace(n)
                     and float(getattr(n, "activation", 0.0) or 0.0) >= 0.3),
                    key=lambda x: -x[0])
                ids = []
                for b in basis:                       # 存量旧 basis 里的
                    n = self.kg.get_node(b)            # 调制镜像/脚手架不展示
                    if n is not None and (is_modulator_node(n)
                                          or is_content_scaffold(n)):
                        continue
                    ids.append(b)
                for _a, nid in hot:
                    if len(ids) >= 12:
                        break
                    if nid not in ids:
                        ids.append(nid)
                nodes = []
                for b in ids:
                    role = "basis" if b in basis else "hot"
                    n = self.kg.get_node(b)
                    if n is None:
                        nodes.append({"id": b, "note": "已不存在",
                                      "act": 0.0, "role": role})
                        continue
                    nodes.append({
                        "id": b, "note": _state_node_note(n),
                        "act": round(float(n.activation or 0.0), 2),
                        "conf": (n.confidence if n.confidence is not None
                                 else None),
                        "created": str(getattr(n, "created", "") or ""),
                        "role": role})
                eset = set(ids)
                edges = []
                for e in self.kg.edges:
                    if len(edges) >= 12:
                        break
                    if (str(e.src) in eset and str(e.dst) in eset
                            and not (is_modulator_node(self.kg.get_node(
                                str(e.src)) or 0)
                                    or is_modulator_node(self.kg.get_node(
                                        str(e.dst)) or 0))):
                        edges.append([str(e.src), str(e.relation),
                                      str(e.dst),
                                      round(float(e.weight or 0.0), 2)])
            _scrub = redact_internal_state_names     # 展示层洗名（内部 id/
            # 机制名不进 UI；准入过滤在前，这里只是最后一道显示清洗）
            return {"ci": str(ci.id),
                    "goal": str(ea.get("reply_goal") or ""),
                    "class": str(ea.get("content_class") or ""),
                    "nodes": [dict(n, id=_scrub(n["id"])) for n in nodes],
                    "edges": [[_scrub(x) if isinstance(x, str) else x
                              for x in row] for row in edges]}
        except Exception:                             # noqa: BLE001
            return None

    def _express(self, ci):
        from langchain_core.prompts import ChatPromptTemplate
        if getattr(self, "llm_budget", None) is not None:
            if not self.llm_budget.can_call("language"):
                logger.info("[LLMBudget] 主动表达语言预算不足，降级为不表达（CI 保持）")
                return False
            self.llm_budget.register("language", tokens=200)
        # 模板文本经语言注入面取（CognitiveLanguageAccess.system_prompt，
        # 2026-10 两仓拆分：认知模块不再直接 import 陪伴侧 prompt_templates；
        # system_prompt 缺席=遗留环境，回退旧直连，逐字等价）。
        _sp = getattr(self.nlp, "system_prompt", None)
        # 2026-10-16 主动表达重构（同日二次修订）：状态切片之外必须带
        # **原始事实层**——近期对话原文（谁说的）与真实行动记录（谁做的）。
        # 只给节点名时，语言层会把共现拼成独白、把她的游戏进度说成用户
        # 的经历（00:21/19:57 实锤）：图谱是组织形式，不是事实的替代品。
        _raw = self._raw_dialog()
        ctx = render_cognitive_state(self.kg, ci=ci,
                                     istate=getattr(self, "internal_state",
                                                    None),
                                     said_recent=self._said_recent(),
                                     raw_dialog=_raw,
                                     life_events=self._life_events())
        if _sp is not None:
            system = _sp("proactive_express")
        else:
            from prompt_templates import build_prompt
            system = build_prompt("proactive_express")
        user = self.build_proactive_user(ci, ctx, _raw)
        # 逐字捕获（2026-10-17）：主动表达也是"她看到了什么"的一部分，
        # 与被动通道同一 prompt_capture.jsonl。陪伴侧观测件缺位时静默跳过。
        try:
            from nlp_processor import _capture_prompt as _cap
            _cap("proactive", system, user)
        except Exception:                            # noqa: BLE001
            pass
        try:
            # 2026-10-11 缺陷修复：human 模板误用 f-string 语法 "{input}" 而声明
            # mustache 格式——单括号不是 mustache 标签，"想法来源"（basis 证据）
            # 从未进入 prompt，LLM 每次都只凭 system 人设空谈（真实 LLM 隔离评估
            # 实锤：生成内容与触发证据零相关）。改为 mustache 转义 "{{input}}"。
            prompt = ChatPromptTemplate.from_messages(
                [("system", system), ("human", "{{input}}")],
                template_format="mustache")
            import fas_log
            with fas_log.llm_purpose("proactive_expression"):
                resp = (prompt | self.nlp.chat_llm).invoke({"input": user})
            text = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        except Exception as e:
            logger.warning(f"[CC] 语言生成失败: {e}")
            return False
        if not text:
            return False
        # 硬闸（2026-10-17 建档，2026-10-19 升级）：LLM 逐字复述她说过的
        # 话 → 按沉默处理。两处旧缺口：①只比全文相等——开头两句整句复用、
        # 后文接新话的"半回声"全数漏网（10:04→10:38 实锤）；②材料窗 30min
        # ——隔 34 分钟的复用恰好越窗。现在拿**无时限账本**（_spoken_ledger）
        # 比：全文相等，或任一 ≥10 字的句子是旧话的字面子串，即判回声。
        # 短的应答填充（"嗯有道理"级）不参与，日常接话的重复语气不算复读。
        _norm = lambda s: "".join(ch for ch in str(s) if ch.isalnum())
        _ledger = self._spoken_ledger()
        _nt = _norm(text)
        _echo_whole = bool(_nt) and any(_norm(sp) == _nt
                                        for _ts, sp in _ledger)
        _echo_sent = False
        if not _echo_whole:
            for _sent in re.split(r"[。！？!?；;，,\n]+", str(text)):
                _ns = _norm(_sent)
                if len(_ns) >= 10 and any(_ns in _norm(sp)
                                          for _ts, sp in _ledger):
                    _echo_sent = True
                    break
        if _echo_whole or _echo_sent:
            with self.kg._lock:
                _ea = ci.extra_attrs
                _ea["status"] = ST_DISCARDED
                _ea["last_change_ts"] = time.time()
                self._evo.note_node_updated(ci.id, {"status": ST_DISCARDED})
            logger.info(
                "[CC] 主动表达弃权（回声，%s复用旧话）: %s",
                "整段" if _echo_whole else "整句", ci.id)
            return False
        # NO_SPEAK 哨兵：想法来源没有具体话题时诚实沉默。CI 直接终态
        # （discarded 不再被节拍重试，否则每 10s 白烧一次 LLM），零投递。
        if "NO_SPEAK" in text.upper() and len(text) <= 24:
            with self.kg._lock:
                _ea = ci.extra_attrs
                _ea["status"] = ST_DISCARDED
                _ea["last_change_ts"] = time.time()
                self._evo.note_node_updated(ci.id, {"status": ST_DISCARDED})
            logger.info(f"[CC] 主动表达沉默（来源无具体话题）: {ci.id}")
            try:
                import fas_log
                fas_log.get_logger(fas_log.COGNITION).info(
                    "express_output", f"{ci.id} no_speak",
                    ci=ci.id, outcome="no_speak")
            except Exception:                        # noqa: BLE001
                pass
            return False

        # 输出侧机制名清洗（10-21 实修）：输入替换表只保证"模型没见过原名"，
        # 拦不住模型从语料先验里自带 CENetwork/DMN 这类术语回抛给用户
        # （15:22 气泡"说到 CENetwork"实锤）。投递前把原文按同一张表反向
        # 洗一遍：只做机械改名，不删句、不改判断，账本/缓冲/投递同一文本。
        text = redact_internal_state_names(text)

        now = time.time()
        self._last_express_ts = now
        self._express_count_hour.append(now)
        with self.kg._lock:
            ea = ci.extra_attrs
            ea["status"] = ST_EXPRESSED
            ea["expressed_at"] = now_str()
            ea["expressed_at_ts"] = now
            ea["last_change_ts"] = now
            ea["expressed_text"] = text[:200]
            self._evo.note_node_updated(ci.id, {"status": ST_EXPRESSED})
        # _stamp_shared 已移至 note_delivery 送达回执处（2026-10-24 实锤：
        # 生成即盖戳 + 投递失败 → 材料被标"已讲过"，重试/新 CI 永远被判
        # duplicate_recent，那句话永远送不出去也不许再说）。
        if self.chat_log:
            try:
                self.chat_log.record(user_input="(主动)", system_response=text,
                                     proactive=True)
            except Exception as e:
                logger.warning(f"[CC] 对话记忆写入失败: {e}")
        if getattr(self, "_save_fn", None):
            try: self._save_fn()
            except Exception as e: logger.warning(f"[CC] 落盘失败: {e}")
        self._queue.append({
            "ci_id": ci.id, "text": text,
            "basis": (ea.get("basis") or [])[:5],   # None 值键：get 的默认
            # 只在缺键时生效——脏数据下 [:5] 会炸（调试测试抓到）
            "goal": ea.get("reply_goal"),
            "illocutionary_act": ea.get("illocutionary_act"),
            "dialogue_act": ea.get("dialogue_act"),
            "expression_eval": ea.get("expression_eval"),
            "time": now_str(),
        })
        # 主动表达也是一次 FAS 表达事件（进入 Reflection Evolution 闭环）
        try:
            if self.buffer:
                self.buffer.add_expression({
                    "user_text": "",
                    "answer": text,
                    "behavior": "share",
                    "context": "情境:主动发起",
                    "context_ids": ["情境:主动发起"],
                    "topics": (ea.get("basis") or [])[:5],
                    "proactive": True,
                })
        except Exception:
            pass
        logger.info(f"[CC] 主动表达: {ci.id} → {text[:60]}")
        # 外部表达通道（如 Charon 桌面气泡）：产出即投递。放在网页 _queue
        # 之后、行动层之前——三个出口各走各的，任一故障不影响其它留痕。
        _dbg = self._debug_graph_for(ci)      # 调试：这条话所用的图谱
        for ch in self.channels:
            try:
                from fas.contracts import Utterance
                _refs = {"ci_id": ci.id, "act": ea.get("dialogue_act"),
                         "scene": ea.get("scene")}
                if _dbg:
                    _refs["graph"] = _dbg
                ch.deliver(Utterance(text=text, origin="proactive",
                                     refs=_refs))
            except Exception as _ce:                 # noqa: BLE001
                logger.debug(f"[CC] 表达通道 {getattr(ch, 'name', '?')} "
                             f"投递异常（不影响表达留痕）: {_ce}")
        # B5/§5：话要有嘴——产出的句子交给行动层作为 communicate 动作执行
        # （过 propose 守卫/调度/结算回执），不绕过通道层直接 say。
        # 网页 _queue 轮询保留：同一次表达的两个出口（屏幕+世界），非双写。
        try:
            self._propose_communicate(ci, text)
        except Exception as e:
            logger.debug(f"[CC] 主动表达投递异常（不影响表达留痕）: {e}")
        return True

    # ── 主动投递（B5/§5：CI → communicate 动作 → 通道 → 真实回执）──

    def _propose_communicate(self, ci, text, note=None):
        """把已表达的话提交为 communicate 动作。

        关键时序：**先**把 action_id 写进 CI.delivery.pending，**再** propose
        ——同步执行的 communicate 会在 propose 调用栈内完成结算并回调
        note_delivery；顺序反了回执就找不到这个 CI（假丢失）。
        被拒（忙/内核守卫）→ pending_retry，≥retry_min_s 后由
        _retry_pending_delivery 一次性再试；不是插队，是一次执行机会。
        """
        import uuid
        am = getattr(self, "action_manager", None)
        aid = f"act_{uuid.uuid4().hex[:8]}"
        with self.kg._lock:
            ea = ci.extra_attrs
            prev_att = int((ea.get("delivery") or {}).get("attempts", 0))
            ea["delivery"] = {"status": "pending", "action_id": aid,
                              "proposed_at": now_str(), "attempts": prev_att + 1}
        if am is None:
            with self.kg._lock:
                ci.extra_attrs["delivery"] = {
                    "status": "no_action_manager", "action_id": aid,
                    "proposed_at": now_str(), "attempts": prev_att + 1}
            return False
        reason = [ci.id] + ([str(note)] if note else [])
        spec = {"action_type": "communicate", "target": "用户",
                "action_id": aid, "params": {"text": str(text)[:120]},
                "motivation": "self_expression", "priority": 0.55,
                "reason": reason}
        try:
            res = am.propose(spec, source="cognition") or {}
        except Exception as e:
            res = {"started": False, "queued": False, "reason": str(e)[:100]}
        accepted = bool(res.get("started") or res.get("queued"))
        if not accepted:
            rc = float((self._loop_cfg.get("delivery") or {})
                       .get("retry_min_s", 60.0))
            with self.kg._lock:
                ea = ci.extra_attrs
                d = dict(ea.get("delivery") or {})
                d.update({"status": "pending_retry",
                          "retry_after": time.time() + rc,
                          "reason": str(res.get("reason") or "")[:120]})
                ea["delivery"] = d
            import fas_log
            fas_log.get_logger(fas_log.COMMUNICATION).info(
                "delivery_deferred", "主动表达被排队/守卫拒绝，延后一次再试",
                ci_id=ci.id, action_id=aid,
                reason=str(res.get("reason") or "")[:120])
        return accepted

    def note_delivery(self, action_id, result, success):
        """行动层结算回执（由 action_system._settle 经 self.cc 回调）。

        只认领 delivery.action_id 匹配且仍在 pending 的 CI——其余动作
        过一遍就返回。送达与否**只认回执**：没有回执就一直 pending，
        绝不自判"说了"。"""
        if not action_id:
            return False
        hit = None
        with self.kg._lock:
            for n in self.kg.nodes.values():
                ea = n.extra_attrs or {}
                if ea.get("type") not in self._INTENTION_TYPES:
                    continue
                d = ea.get("delivery") or {}
                if d.get("action_id") == action_id \
                        and d.get("status") == "pending":
                    d["status"] = "delivered" if success else "say_failed"
                    d["settled_at"] = now_str()
                    d["success"] = bool(success)
                    d["detail"] = str((result or {}).get("result")
                                      or (result or {}).get("detail") or "")[:120]
                    if not success:
                        d["reason"] = str((result or {}).get("reason") or "")[:120]
                        # 通道暂时故障（桥未连≠社交拒绝）→ 延后重投
                        # （一次性；23:37 实锤：她头一次主动话撞上重启
                        # 窗口的 not_connected 直接死档，违背失败可恢复原则）
                        if ("not_connected" in d["reason"]
                                or "bridge" in d["reason"].lower()):
                            d["status"] = "pending_retry"
                            d["retry_after"] = time.time() + 15.0
                    else:
                        # 送达成功才盖"讲过了"戳（2026-10-24：盖戳点从生成
                        # 移到送达——失败投递不得污染材料的新鲜度）
                        self._stamp_shared(n, time.time())
                    ea["delivery"] = d
                    hit = (n.id, ea.get("expressed_text"), d["status"])
                    break
        if hit:
            import fas_log
            fas_log.get_logger(fas_log.COMMUNICATION).info(
                "delivery_settled",
                f"{hit[2]}: {str(hit[1] or '')[:40]}",
                ci_id=hit[0], action_id=action_id, success=bool(success))
        return bool(hit)

    def _retry_pending_delivery(self):
        """pending_retry 的一次性再试（≥retry_min_s 到点才动）。

        再试仍被拒 → abandoned：不反复贴嘴（防刷屏语义），也不假装送达。"""
        now = time.time()
        due = []
        with self.kg._lock:
            for n in self.kg.nodes.values():
                ea = n.extra_attrs or {}
                if ea.get("type") not in self._INTENTION_TYPES:
                    continue
                d = ea.get("delivery") or {}
                if d.get("status") == "pending_retry" \
                        and float(d.get("retry_after", 0)) <= now \
                        and int(d.get("attempts", 1)) < 2:
                    due.append((n, str(ea.get("expressed_text") or "")))
        for n, text in due:
            if not text:
                with self.kg._lock:
                    d = dict(n.extra_attrs.get("delivery") or {})
                    d["status"] = "abandoned"
                    d["reason"] = d.get("reason") or "no_text"
                    n.extra_attrs["delivery"] = d
                continue
            try:
                self._propose_communicate(n, text, note="retry_once")
            except Exception as e:
                logger.debug(f"[CC] 投递再试异常: {e}")
            with self.kg._lock:
                d = n.extra_attrs.get("delivery") or {}
                if d.get("status") == "pending_retry":
                    d["status"] = "abandoned"   # 一次性机会，到此为止
                    n.extra_attrs["delivery"] = d
                    import fas_log
                    fas_log.get_logger(fas_log.COMMUNICATION).info(
                        "delivery_abandoned", "再试仍被拒，放弃本次投递",
                        ci_id=n.id, reason=str(d.get("reason") or "")[:120])

    # ── 论文 §3.3：离线自主思考三机制 ─────────────────────

    # ── 重新点亮（reactivation）：全图 eligible 竞争，非随机回忆 ──
    # 语义：让已衰减、暂时离开认知场的**任何普通节点**重获进入认知过程的
    # 机会——概念/情景/人物/情绪/Drive/能力/未知/MC 对象一律有资格；
    # 点亮后仍须经过正常 diffusion/竞争，不会直达意图。

    # ── 经验重放（replay）：空闲时把少量高价值经验重新接进扩散 ──
    # 定位：调度/入口层，不是第二套学习机制（experience_replay 模块注释）。
    # 本门只判断"现在是否轮到它跑"——节流/预算/零收益退避在 replay 层内；
    # 抢占由所在分支保证：对话回合整个非 busy 段不执行，动作执行中不进。

    def _replay_gate(self):
        try:
            rp = self._replay
            if rp is None:
                if not (self.cfg.get("replay") or {}).get("enabled", True):
                    return
                from experience_replay import ExperienceReplay
                rp = self._replay = ExperienceReplay(
                    self.kg, self.engine, self.cfg.get("replay") or {})
            am = self.action_manager
            if am is not None and am.busy():
                return                   # 行动优先：做事时不重放
            rp.gate(timeline=self.timeline,
                    causal=getattr(am, "causal", None))
        except Exception as e:
            logger.debug(f"[CC] 经验重放跳过: {e}")

    def _reactivate_gate(self):
        rc = (self._loop_cfg.get("reactivation") or {})
        now = time.time()
        if now - self._last_react_ts < \
                float(rc.get("min_interval_ticks", 2)) * \
                float(self.cfg["tick_seconds"]):
            return                       # cooldown 下限（防连点），非闹钟
        # 认知场过冷：当前 top-k 平均激活不足以维持多样火种
        temp = self._field_temperature()
        if temp is None:
            # L1-DGR-05:温度探测失败,本拍跳过冷场判定
            import logging
            logging.getLogger(__name__).debug(
                "[CC] 场温度探测失败，再点火门本拍跳过")
            return
        cold = float(self._mod_th("reactivation.cold_field",
                                  float(rc.get("cold_field_activation", 0.35))))
        if temp >= cold:
            self._cold_beats = 0               # 回暖即清零（不是闹钟，是持续度）
            return
        # R2 P8（D-3）：`retrieval.reignite_every` 的真消费者 —— **冷场要持续多久**才
        # 值得再点火（防抖，不是定时器：触发条件仍然是"场冷"，这里只规定它必须连续
        # 成立 N 拍）。CEN 高→拉长（别打断聚焦），DMN 高→缩短（发散态欢迎翻旧账）。
        # 计数单位是本门自己观测到的冷拍数，不用 `self._tick`：tick 节拍与门节拍
        # 不同源（对话期 tick 会停），用绝对 tick 差值会让"冷场持续度"被暂停污染。
        every = max(1, int(round(self._mod_th(
            "retrieval.reignite_every", float(self.cfg["reignite_every_pulses"])))))
        self._cold_beats += 1
        if self._cold_beats < every:
            return
        self._last_react_ts = now
        self._cold_beats = 0
        self._reactivate_field(rc, temp)

    def _field_temperature(self):
        """当前激活场温度：top-k 平均激活（engine 缺位回退图扫描）。"""
        try:
            topk, _ = self.engine.get_topk(k=10)
        except Exception:
            # L1-DGR-05:失败返回 None 由门跳过判定,避免 0.0 被误判
            # "过冷"→触发再点火,方向性放大错误。
            return None
        acts = [float(n.activation or 0.0) for n in topk if n.activation > 0]
        return (sum(acts) / len(acts)) if acts else 0.0

    def _reactivate_field(self, rc: dict, temp: float):
        import math
        import random
        w = rc.get("weights") or {}
        half_life = max(30.0, float(rc.get("half_life_s", 900)))
        window = float(rc.get("recent_window_s", 180))
        count = max(1, int(rc.get("count", 4)))
        now_ts = time.time()
        with self.kg._lock:
            nodes = self.kg.nodes
            # 排除：引擎零件、坐标、进行中的意图/思考/记录类产物、
            # 以及还热着（≥0.3 激活）的节点——它们不需要重新点亮
            INFRA = {nid for nid, n in nodes.items()
                     if n.label in ENGINE_PART_LABELS}
            hot = {n.id for n in nodes.values()
                   if float(n.activation or 0.0) >= 0.3}
        # L1-DGR-02:锁序 engine→kg;get_topk 不得在 kg._lock 内取(此处两锁混用)
        try:
            focus_ids = {n.id for n in self.engine.get_topk(k=8)[0]}
        except Exception as e:
            # L1-DGR-05:探测失败不静默——空集让再点火失去焦点约束,退化为全图随机
            import logging
            logging.getLogger(__name__).warning(
                "[CC] focus_ids 探测失败，再点火进入无焦点模式: %r", e)
            focus_ids = set()
        with self.kg._lock:
            nodes = self.kg.nodes
            drive_ids = {nid for nid, n in nodes.items()
                         if (n.extra_attrs or {}).get("type") in
                         ("drive", "emotion", "cognitive_network")}
            drive_nbrs = set()
            for d in list(drive_ids)[:8]:
                for e in self.kg.get_out_edges(d):
                    drive_nbrs.add(e.dst)
            scored = []
            for nid, n in nodes.items():
                if nid in INFRA or nid in hot or nid in focus_ids:
                    continue
                if str(nid).startswith(("CI_", "思考_", "反思_", "回答记录_",
                                         "搜索记录_", "文件操作记录_",
                                         "表达_", "坐标(")):
                    continue
                ea = n.extra_attrs or {}
                if ea.get("type") in ("dynamic_state", "inventory_item"):
                    continue   # 世界状态由感知节拍维护，不参与联想点火
                if is_modulator_node(n) or is_state_mirror(n):
                    continue   # 控制量/状态镜像的能量来自控制通道（脉冲/
                    # 需求漂移），再点火会在它们与旧念头之间造共振腔——
                    # 2026-10-20 实锤：mc 镜像被反复点回 5.0，经"关于"边
                    # 给 10-09 的思考旁白续电，僵尸霸占热位
                la = getattr(n, "last_access", None)
                gap = half_life                      # 无时间戳：视为已久
                if hasattr(la, "timestamp"):
                    gap = now_ts - la.timestamp()
                elif isinstance(la, str) and la:
                    try:
                        from datetime import datetime as _dt
                        t = _dt.strptime(
                            la, "%Y/%m/%d %H:%M:%S").timestamp()
                        gap = now_ts - t
                    except ValueError:
                        gap = half_life
                # eligibility 分量（权重是数据表，非硬公式）
                recency_gap = 1.0 - math.exp(-max(0.0, gap) / half_life)
                coupling = 0.0
                for e in self.kg.get_out_edges(nid):
                    if e.dst in focus_ids:
                        coupling = max(coupling, float(e.weight or 0))
                for e in self.kg.get_in_edges(nid):
                    if e.src in focus_ids:
                        coupling = max(coupling, float(e.weight or 0))
                drive_tie = 0.5 if nid in drive_nbrs else 0.0
                novel = 0.0 if (now_ts - self._reactivated_recent.get(
                    nid, 0.0)) < window else 1.0
                s = (float(w.get("importance", 0.25)) * min(1.0, float(n.weight))
                     + float(w.get("recency_gap", 0.20)) * recency_gap
                     + float(w.get("field_coupling", 0.25)) * coupling
                     + float(w.get("drive_tie", 0.15)) * drive_tie
                     + float(w.get("novelty", 0.10)) * novel
                     + float(w.get("noise", 0.15)) * random.random())
                s *= float(rc.get("recent_penalty", 0.6)) if novel == 0.0 else 1.0
                scored.append((s, nid, {"gap_s": round(gap),
                                        "coupling": round(coupling, 2),
                                        "drive_tie": drive_tie,
                                        "novelty": novel}))
            scored.sort(key=lambda x: -x[0])
            picks = scored[:count]
            if not picks:
                return
            boost = float(rc.get("boost", 1.2)) * self._mod_th(
                "reactivation.boost_scale", 1.0)
            wake, detail = [], []
            for s, nid, why in picks:
                n = nodes[nid]
                n.activation = min(3.0, float(n.activation or 0.0) + boost
                                   * max(0.25, min(1.0, s)))
                n.touch()
                wake.append(nid)
                self._reactivated_recent[nid] = now_ts
                detail.append(f"{nid}(score={s:.2f},gap={why['gap_s']}s,"
                              f"tie={why['coupling']})")
            self.engine.mark_active(wake)
            # 内源注入（reactivation）：发射免扣——点亮是"回忆的火种"
            # 不是注意资源的转移
            self.engine.register_activation_source(wake, "reactivation")
        self._last_reactivation = {"field_temperature": round(temp, 3),
                                    "picked": detail}
        logger.info(f"[CC] 认知场再点火（场温 {temp:.2f}<{self._mod_th('reactivation.cold_field', 0.35):.2f}）: "
                    + "; ".join(detail[:4]))

    def _free_think(self):
        """自由思考/思维跳跃：Self 扩散 TopK → 一句内心独白（1 次 LLM）。
        LLM 参与模式 MODE4_REFLECT 级；预算不足时跳过（慢通道降级，图谱继续）。"""
        if self.nlp is None:
            return
        now = time.time()
        if now - self._last_thought_ts < self.cfg["thought_min_interval_s"]:
            return
        if getattr(self, "llm_budget", None) is not None:
            if not self.llm_budget.can_call("reflect"):
                logger.info("[LLMBudget] 自由思考预算不足，跳过（图谱继续）")
                return
            self.llm_budget.register("reflect", tokens=300)
        self._last_thought_ts = now
        try:
            tid = self.engine.generate_thought(self.nlp, k=8)
            if tid:
                logger.info(f"[CC] 自由思考: {tid}")
        except Exception as e:
            logger.warning(f"[CC] 自由思考失败: {e}")

    def _maybe_offline_reflect(self):
        """反思性自问：由反思压力驱动（行动失败/负反馈/预测误差/意图消散
        等信号在图上攒出的持续压力），压力过阈值才反思；时间只是 cooldown，
        不是触发器。反思输出结构化进图谱（self-model/disposition/causal）。"""
        if self.reflection is None or not self.cfg.get("offline_reflection"):
            return
        pcfg = self._pressure_cfg()
        now = time.time()
        if now - self._last_offline_reflect < float(pcfg.get("cooldown_s", 600)):
            return                       # cooldown：两次反思的最小距离
        pressure = self.pressure_value()
        if pressure < float(pcfg.get("threshold", 1.2)):
            return                       # 压力不足：不反思（合法）
        # 收尾修复 2026-09-22：离线反思也是 LLM 慢通道，须与 _free_think
        # 同走预算账（旧版只有压力阈值一道闸，预算体系对它失明）。
        # 预算不足时不消耗压力、不进 cooldown——压力仍在，下拍重试。
        if getattr(self, "llm_budget", None) is not None:
            if not self.llm_budget.can_call("reflect"):
                logger.info("[LLMBudget] 离线反思预算不足，跳过（压力保留，下拍重试）")
                return
            self.llm_budget.register("reflect", tokens=600)
        self._last_offline_reflect = now
        try:
            with self.engine._lock:
                topk, _ = self.engine.get_topk(k=15)
            src = None
            with self.kg._lock:
                pn = self.kg.get_node(str(pcfg.get("node") or "反思压力"))
                if pn is not None:
                    src = dict((pn.extra_attrs or {}).get("sources") or {})
                    # 消耗压力（反思本身就是消化动作）
                    ea = dict(pn.extra_attrs or {})
                    ea["last_reflection_at"] = now_str()
                    ea["last_reflection_pressure"] = round(pressure, 2)
                    ea["sources"] = {k: round(v * 0.3, 3) for k, v in src.items()}
                    pn.extra_attrs = ea
                    pn.activation = float(pn.activation or 0.0) * 0.3
                    pn.touch()
            logger.info(f"[CC] 反思压力过阈值（{pressure:.2f}，来源 "
                        f"{sorted(src or {}, key=lambda k: -(src or {}).get(k, 0))[:3]}"
                        f"），触发离线反思")
            r = self.reflection.run(trigger="pressure",
                                     topk_nodes=topk,
                                     chat_log_entries=self.chat_log.recent(n=10) if self.chat_log else None)
            if r and not r.get("skipped"):
                logger.info(f"[CC] 离线反思完成: {r.get('reflection_id')}")
        except Exception as e:
            logger.warning(f"[CC] 离线反思失败: {e}")

    # ── 对外接口 ──────────────────────────────────────────

    def poll(self) -> list:
        """前端轮询：取走已表达的主动消息。"""
        with self._lock:
            out, self._queue = self._queue, []
        return out

    def tick_express_check(self):
        """在 pulse 后调用：表达决策 + 语言生成（唯一 LLM 入口）。"""
        try:
            # §16 实验屏蔽 idle_companion：空闲自发表达节拍停摆（CI 照常
            # 形成/滞留，只是不再产生"随口说话"这一行为出口）。
            import experiment_mode as _xm
            if _xm.shield("idle_companion"):
                return
        except Exception:
            pass
        ci, val = self._evaluate_expression()
        if ci is not None:
            self._express(ci)
        # B5：到期的延后投递（每拍扫一遍 pending_retry，零 LLM）
        try:
            self._retry_pending_delivery()
        except Exception as e:
            logger.debug(f"[CC] 投递再试跳过: {e}")

    def state(self) -> dict:
        with self.kg._lock:
            cis = [{
                "id": n.id,
                "kind": n.extra_attrs.get("kind"),
                "status": n.extra_attrs.get("status"),
                "activation": n.extra_attrs.get("activation"),
                "basis": n.extra_attrs.get("basis", []),
                "goal": n.extra_attrs.get("reply_goal"),
                "illocutionary_act": n.extra_attrs.get("illocutionary_act"),
                "explain": n.extra_attrs.get("explain"),
                "expression_eval": n.extra_attrs.get("expression_eval"),
                "delivery": n.extra_attrs.get("delivery"),
                "created": n.extra_attrs.get("created"),
            } for n in self.kg.nodes.values()
                if (n.extra_attrs or {}).get("type") in self._INTENTION_TYPES]
        return {"tick": self._tick, "busy": self._busy.is_set(),
                "thresholds": {
                    "form": round(self._mod_th("cognition.form_threshold",
                                               float(self.cfg["form_threshold"])), 3),
                    "express": round(self._mod_th("cognition.express_threshold",
                                                  float(self.cfg["express_threshold"])), 3),
                    "form_base": self.cfg["form_threshold"],
                    "express_base": self.cfg["express_threshold"]},
                "reflection_pressure": round(self.pressure_value(), 3),
                "last_reactivation": getattr(self, "_last_reactivation", None),
                "field_change": getattr(self, "_last_field_change", None),
                "queue": len(self._queue),
                "cooldown_remaining": max(0, int(self.cfg["inhibition_cooldown_s"]
                    - (time.time() - self._last_express_ts))),
                "intentions": sorted(cis, key=lambda c: -(c.get("activation") or 0))}


# ── 认知状态切片渲染（2026-10-16 主动表达重构）────────────────
# 只读：不改图、不提激活、不造关联。产出的文本交给 LLM 自行综合，
# 材料自带性质与时间标注（假设≠事实、表达产物≠外部证据、旧≠新），
# 让"这条信息凭什么可信"成为模型能看见的属性，而不是我们代的隐喻。

_STATE_KIND_NOTE = {
    "hypothesis": "待验证联想",
    "communication_intention": "我自己的念头/表达产物（内部痕迹，不是外部证据）",
    "disposition": "行为倾向（经验习得）",
    "mood_state": "心情瞬态",
    "modulator": "生理调制状态",
    "modulator_target": "调制目标",
    # 调制镜像即便从旁路漏进素材行，也要顶着真名出现，绝不再是"概念"
    #（准入过滤是第一道，这里是最后一道：洗名/展示都不能把控制量
    #  伪装成心理内容——2026-10-19 审计结论"洗名不能代替准入"）
    "drive": "内部驱动强度（认知控制量，不是心理概念）",
    "cognitive_network": "认知网络状态（引擎内部量，不是想法）",
    "eye_perception": "我在屏幕上看到的",
    "activity_experience": "活动体验",
    "concept": "概念",
    "sts_tag": "活动标签",
    "card_instance": "知识实例",
    # ── 情景来源约束（2026-10-19 审计：知道≠经历）──
    # 这些 type 都是既有节点（图谱早已在写），只是性质标注此前落到
    # 标签兜底——用户话语与表达痕迹都被标成"经历片段"，主体与"说≠做"
    # 在渲染时丢失。修复=把已有事实传到语言层，不新增任何判定。
    "utterance_event": "用户说的话（主体=用户；不是我的经历）",
    "user_expression_event": "用户的表达事件（主体=用户）",
    "expression_event": "我说过的话（说话记录——说过≠做过，不算活动经历）",
    "thought": "我自己的念头（心理活动，不是外部世界的证据）",
    # 因果学习器写出的归纳规则（experience.py 晋升路径）：它们来自
    # 多次真实经历，但**不指任何一次具体事件**——标清楚，避免"我做过X"
    # 把归纳规律叙述成单日经历。
    "action_pattern": "从反复经历归纳出的操作规律（不是某一次具体经历）",
    "state_change": "从反复经历归纳出的变化规律（不是某一次具体经历）",
}


def _mc_session_note(ea: dict) -> str:
    """Minecraft 会话节点是**桥接状态镜像**（minecraft/session.py 只写
    state 字段）：它记录连接状态，不记录"玩过"。2026-10-19 实锤案例：
    12:47 该节点带着 state=disconnected 被标成〔概念〕入切片，语言层把
    激活+知识连线写成"我刚才在Minecraft里闲逛"。"""
    return (f"Minecraft桥接状态（当前={ea.get('state') or 'unknown'}；"
            f"这只说明连接与否，不代表我在玩，更不是玩过的经历）")


# 内部状态节点的"自然语言真名"（2026-10-17）：图谱 id 与激素英文键是
# 机制原料，模型见过就可能念给用户（18:34 "CuriosityDrive"、19:35
# "DMNetwork" 两次实锤）。不赌指令遵从——prompt 出口直接替换，模型
# 从没见过原始名，泄漏从源头消失；决策拿到的读数（强度/状态）不减。
_INTERNAL_STATE_NAT = {
    "CuriosityDrive": "好奇",
    "SocialDrive": "对联结的渴望",
    "LearningDrive": "学习的冲动",
    "ConsistencyDrive": "保持一致的意愿",
    "CENetwork": "专注执行的状态",
    "DMNetwork": "神游联想的状态",
}
_HORMONE_NAT = {
    "dopamine": "多巴胺", "serotonin": "血清素", "oxytocin": "催产素",
    "cortisol": "皮质醇", "adrenaline": "肾上腺素", "endorphin": "内啡肽",
    "histamine": "组胺", "melatonin": "褪黑素",   # 图谱遗留镜像节点仍要洗名；
    #   这两个调制器本身已删（2026-10-17：AI 无疲劳/清醒生理）
}


# ── 说话场景（2026-10-20）──────────────────────────────────
# 病灶：主动表达把"逛到个鼠标"写成"被看见×霍桑效应"的随笔（19:27 实锤）。
# 气泡取证显示升华的原料**不在激活图谱里**（心理可见性/布兰登 act≈0）——
# 它们来自上文中（旧聊天）与模型自身的世界知识，语言层把刚遇到的小事和
# 背景记忆编成了一篇"必然要有结论"的文章。修法：让当前说话场景参与表达
# 定调。场景不新建任何状态，纯派生自已有数据（CI basis + 对话原文）；
# 只调"这次话的落点深浅"，不删素材、不拦概念、不设阈值闸。
SCENES = {
    "闲聊延续": "用户此刻正在说话，你这次是接着聊——深浅跟着 ta 提的话走，"
              "往深里说完全合法。",
    "偶遇小事": "你刚在外面遇到件小事（网页、屏幕、活动里撞见的）。值得说的"
              "多半是这件事本身：联想随意，可以只迈半步、可以不落地、不必"
              "收成一个道理。上文里旧话题是背景记忆——用户这轮没再提的，"
              "就别把它搬来当这次偶遇的哲理结论。",
    "空闲随想": "空闲里想起点东西。联想按原样说就好；要不要牵到大主题，"
              "看那主题是不是你和用户之间最近真实发生过、还没聊完的事——"
              "不是的话，随想就只是随想，不用写成随笔。",
}


# 外部偶遇的出处标记（节点 extra_attrs.source 的冒号前缀，全已有写入方，
# 不新增字段）：浏览/读文/检索/游戏观察/Minecraft 世界/活动产出——
# basis 里出现这类内容 = 这次话落在"刚遇到的事"上。实测 19:27 案例：
# 活动壳节点衰减快出不了 basis，真据是内容节点的 source=browse:*。
_ENCOUNTER_SOURCES = frozenset({"browse", "activities", "steam", "narrative",
                                "curiosity", "read", "mc"})


def _is_encounter_node(n) -> bool:
    if n is None:
        return False
    ea = n.extra_attrs or {}
    src = str(ea.get("source") or "").split(":")[0].split("_")[0]
    return src in _ENCOUNTER_SOURCES


def scene_for_ci(ci, raw_dialog=None, kg=None):
    """说话场景判定：返回 (场景名, 定调句)。优先级=对话在场 > 活动偶遇 > 随想。
    纯读已有数据，无副作用；供 build_proactive_user 调用（测试可直接调）。"""
    ea = getattr(ci, "extra_attrs", None) or {}
    basis = [str(b) for b in (ea.get("basis") or [])]
    if raw_dialog and any("用户说：" in str(ln)
                          for ln in list(raw_dialog)[-4:]):
        return "闲聊延续", SCENES["闲聊延续"]
    for b in basis:
        if b.startswith("Activity_"):
            return "偶遇小事", SCENES["偶遇小事"]
        if kg is not None:
            n = kg.get_node(b)
            if n is not None and (
                    str((n.extra_attrs or {}).get("type") or "")
                    == "activity_experience" or _is_encounter_node(n)):
                return "偶遇小事", SCENES["偶遇小事"]
    return "空闲随想", SCENES["空闲随想"]


def redact_internal_state_names(text: str) -> str:
    """把机制原始名换成自然语言（节点名、drive.x 键、边引用、激素键
    一次洗齐；同一段文字内保持一致替换，节点与连线仍对得上）。"""
    if not text:
        return text
    for k, v in _INTERNAL_STATE_NAT.items():
        text = text.replace(k, v)
    import re as _re
    for k, v in _HORMONE_NAT.items():
        text = _re.sub(rf"\b{k}\b", v, text)
    text = text.replace("drive.", "").replace("network.", "")
    return text


def _state_node_note(n) -> str:
    ea = n.extra_attrs or {}
    t = str(ea.get("type") or "")
    if t == "mc_session":
        return _mc_session_note(ea)
    if t in _STATE_KIND_NOTE:
        return _STATE_KIND_NOTE[t]
    src = str(ea.get("source") or "")
    if src.startswith("research"):
        return "研究结论（有检索证据）"
    if src in ("co_structure", "hypothesis"):
        return "待验证联想"
    lab = str(getattr(n, "label", "") or "")
    if lab == "declarative-semantic":
        return "概念"
    if lab == "declarative-episodic":
        return "经历片段"
    return lab or "节点"


def render_cognitive_state(kg, ci=None, istate=None, said_recent=None,
                           budget=2400, now=None, raw_dialog=None,
                           life_events=None) -> str:
    """当前认知状态切片：先给**真实记录**（近期对话原文 raw_dialog、
    实际发生的行动 life_events——谁做的、什么时候），再给图谱摘要
    （节点+性质标注+真实边）、内部状态、最近说过的话、时间。
    图谱是认知的组织形式，不是原始事实的替代品（2026-10-16 规范）：
    没有原文与主体，语言层只能从节点名反向猜测发生过什么——那正是
    "CuriosityDrive×CENetwork 拼独白"和"她的游戏进度说成用户经历"的
    土壤。缺界点显式标'已不存在-不是证据'。"""
    import time as _t
    now = now if now is not None else _t.time()
    ids = []
    if ci is not None:
        for b in ((ci.extra_attrs or {}).get("basis") or [])[:8]:
            if str(b) not in ids:
                ids.append(str(b))
    with kg._lock:
        hot = sorted(
            ((float(getattr(n, "activation", 0.0) or 0.0), str(n.id))
             for n in kg.nodes.values()
             if str(getattr(n, "label", "") or "").startswith("declarative")
             and not is_modulator_node(n)     # 控制量不占素材席位，腾出的
            #  槽位回补给语义内容；状态镜像(mc_session)保留——带诚实注记，
            #  只供"当前连接与否"的状态判断，不作内容联想；内部痕迹
            #  （思考/反思/行动记录…）也出局——它们是能量累积器不是素材，
            #  旧想法能靠 关于 边在热位挂几天（10-21 实锤 act=2.35 的 10-14
            #  思考进 prompt），想法内容本身由 思路流 段按时间呈现
             and not is_internal_trace(n)
             and float(getattr(n, "activation", 0.0) or 0.0) >= 0.3),
            key=lambda x: -x[0])[:10]
    for _a, nid in hot:
        if nid not in ids:
            ids.append(nid)
    ids = ids[:12]
    idset = set(ids)
    seg = []
    edges = []
    with kg._lock:
        for nid in ids:
            n = kg.nodes.get(nid)
            if n is not None and (is_modulator_node(n)
                                  or is_content_scaffold(n)):
                continue          # 存量 CI 的旧 basis 里可能还挂着调制
                # 镜像/脚手架（修复前形成的念头）：渲染端最后一道闸，
                # 不为其保留行位，热槽候选照常补齐
            if n is None:
                seg.append(f"- {nid}: 【已不存在——历史指向的已消逝念头，"
                           f"其残留名字不是证据】")
                continue
            ea = n.extra_attrs or {}
            bits = [f"- {nid}〔{_state_node_note(n)}〕 激活"
                    f"{round(float(n.activation or 0.0), 2)}"]
            # 事件时刻=节点顶层 created（ea.created 只是个别写手的副本，
            # 曾致素材"生于"出现 0 次——19:34 审计实锤）
            cre = str(getattr(n, "created", "") or "") or str(
                ea.get("created") or "")
            if cre:
                bits.append(f" 生于{cre}")
            conf = ea.get("confidence")
            if conf is not None:
                bits.append(f" 置信{conf}")
            # 自由思考产出的内容存 content，非 text（2026-10-16 修复：
            # 只认 text 时"在想什么"类问题永远拿到空内容）
            tx = str(ea.get("text") or ea.get("content") or "")[:150]
            if tx:
                bits.append(f"\n    内容：{tx}")
            seg.append("".join(bits))
        for e in kg.edges:
            s, d = str(e.src), str(e.dst)
            if s in idset and d in idset and not (
                    is_modulator_node(kg.nodes.get(s))
                    or is_modulator_node(kg.nodes.get(d))):
                edges.append((s, str(e.relation), d,
                              round(float(e.weight or 0.0), 2)))
    out = []
    _facts_header = ("【最近真实发生过的事（事实记录：谁做的、什么时候。"
                     "图谱节点只是它们的摘要，不能替代这里的事实；"
                     "这份记录是完整的——没写在这里的事就没有发生，"
                     "不说没发生过的已完成，也不许诺没有依据的打法、"
                     "能力或结果）】")
    if life_events:
        out.append(_facts_header + "\n" + "\n".join(life_events))
    else:
        # 空记录时这一段**更不能消失**（2026-10-19 审计：12:47"我刚才在
        # Minecraft 里闲逛"实锤——当天时间轴里除了发声没有任何活动事件，
        # _life_events 返回空 → 旧代码 `if life_events:` 把整段（连同
        # "没写在这里=没发生"的唯一反虚构声明）一起跳过。最没有经历可引用
        # 的时刻，恰恰是最需要这份完整性声明的时刻。空账本如实呈现，
        # 不是新闸门：它不拦任何内容，只是把本来就存在的事实记录边界讲完。）
        # 措辞边界（2026-10-19 复审）：账本只覆盖**已被写成 ACTION 的
        # 执行行为**（对局、动作系统执行等），未采集的活动不能替它做
        # "什么都没发生"的断言；但叙事的举证义务反过来——说自己做过，
        # 必须能在这里或对话原文里找到那条。
        out.append(_facts_header + "\n"
                   "- （这份账本最近没有任何活动被记录。它登记对局、执行类"
                   "行动与台账标题级活动，在其登记范围内是完整的——要说"
                   "'我做了X/我刚才在X'，必须能在这份记录或上面的对话原文"
                   "里找到对应条目；**没被登记不等于没发生过，未记录时既"
                   "不要说'做了X'、也不要说'什么都没做'**——前者无据，"
                   "后者越权。图谱里与X有关的节点只代表我知道、我想做或"
                   "我研究过，不代表我做过）")
    if raw_dialog:
        out.append("【最近真实发生的对话（原文与说话人）】\n"
                   + "\n".join(raw_dialog))
    out.append("【我此刻心里有什么（节点，含性质与时间）】\n" + "\n".join(seg))
    if edges:
        out.append("【它们之间真实的连线（方向=从我指向；共同出现≠因果）】\n"
                   + "\n".join(f"- {s} -{r}-> {d}（权重 {w}）"
                               for s, r, d, w in edges[:20]))
    # 思路流（2026-10-16）：自由思考节点衰减很快，多数已低于上面的 0.3
    # 热线——但被问"你在想什么/干嘛"时，恰恰是这些内容本身。按创建时间
    # 取最近 3 条（不看激活），连同酝酿中未说出口的念头一起入切片。
    # 时间真源是节点顶层 created（"2026/10/16 16:51" 斜杠格式；extra_attrs
    # 里的是旧写入路径的副本）——必须解析成秒，字符串序在两种格式间是错的
    # （2026-10-16 捕获实锤：字符串序 top3 全是 7 天前的旧思考）。
    import datetime as _dt2

    def _born(n) -> float:
        ea = n.extra_attrs or {}
        for cand in (getattr(n, "created", None), ea.get("created")):
            s = str(cand or "")
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S"):
                try:
                    return _dt2.datetime.strptime(
                        s.replace("/", "-") if fmt == "%Y-%m-%d %H:%M:%S"
                        else s, fmt).timestamp()
                except ValueError:
                    continue
        return 0.0
    recent_thoughts, pending = [], []
    with kg._lock:
        for n in kg.nodes.values():
            ea = n.extra_attrs or {}
            ty = str(ea.get("type") or "")
            if ty == "thought":
                ct = str(ea.get("content") or "").strip()
                if ct:
                    recent_thoughts.append((_born(n), str(n.id), ct))
            elif ty in ("communication_intention", "intention") \
                    and ea.get("status") in (ST_FORMING, ST_READY):
                bs = "×".join(
                    str(b) for b in (ea.get("basis") or [])[:6]
                    if not is_modulator_node(kg.nodes.get(str(b)))
                    and not is_state_mirror(kg.nodes.get(str(b))))
                act = round(float(ea.get("activation") or 0.0), 2)
                if ty == "communication_intention":
                    pending.append(f"- 有个想开口的冲动（关于 {bs or '…'}，"
                                   f"强度 {act}，还没说）")
                else:
                    pending.append(f"- {ea.get('kind') or '探索'}类的念头正在酝酿"
                                   f"（基于 {bs or '…'}，强度 {act}）")
    if recent_thoughts or pending:
        _ts = ["【我正在想的事（思路流与酝酿中的念头——这是我自己的心理活动，"
               "不是外部事实的证据）】"]
        for born, tid, ct in sorted(recent_thoughts,
                                    key=lambda x: x[0],
                                    reverse=True)[:3]:
            _when = (_dt2.datetime.fromtimestamp(born).strftime("%m-%d %H:%M")
                     if born else "时间不明")
            _ts.append(f"- {tid}（{_when}）：{ct[:120]}")
        _ts.extend(pending[:3])
        out.append("\n".join(_ts))
    if istate is not None:
        try:
            snap = istate.snapshot() or {}
            mods = []
            for k, v in (snap.get("modulators") or {}).items():
                lv = float((v or {}).get("level", 0.0) or 0.0)
                base = float((v or {}).get("tonic", lv) or lv)
                if abs(lv - 0.5) > 0.12:
                    mods.append(f"{k}={round(lv, 2)}")
            needs = sorted(
                ((float((v or {}).get("urgency", 0) or 0), k)
                 for k, v in (snap.get("needs") or {}).items()),
                key=lambda x: -x[0])
            need_s = ", ".join(f"{k}(紧迫{round(u, 2)})"
                               for u, k in needs[:2] if u > 0.3)
            if mods or need_s:
                line = "【我的身体与状态】"
                if mods:
                    line += " 化学背景：" + "、".join(mods[:6]) + "。"
                if need_s:
                    line += " 正被牵挂：" + need_s + "。"
                out.append(line)
        except Exception:                                # noqa: BLE001
            pass
    if said_recent:
        out.append("【我最近已经说出口的话（别说第二遍）】\n"
                   + "\n".join(f"- 「{t}」（{ts}）" for t, ts in said_recent))
    import datetime as _dt
    _now_line = f"【此刻】{_dt.datetime.fromtimestamp(now):%Y-%m-%d %H:%M}"
    out.append(_now_line)
    _marker = "\n……（预算截断：截断不等于完整，未展示部分不可当作已核实的证据）"
    full = "\n\n".join(out)
    if len(full) > budget:
        # 时间锚与事实声明段永不可被裁掉（19:34 实锤：裸尾切把 %H:%M
        # 拦腰截断，模型在没有钟点的情况下断言"间隔了二十多分钟"且算错）。
        # 分级降级：①整段丢"连线/思路流"（最长、非锚）；②只留事实声明
        # +时间锚；③极限预算连这俩都装不下 → 只保时间锚+截断标注——
        # 时间永不缺席；输出始终 ≤ budget（标注计入）。
        drop = {i for i, s in enumerate(out)
                if s.startswith("【它们之间真实的连线")
                or s.startswith("【我正在想的事")}
        trimmed = "\n\n".join(s for i, s in enumerate(out) if i not in drop)
        if len(trimmed) + len(_marker) > budget:
            trimmed = "\n\n".join(
                s for s in out if s.startswith(("【最近真实发生过的事",
                                                "【此刻")))
        if len(trimmed) + len(_marker) > budget:
            trimmed = _now_line
        full = trimmed + _marker
        if len(full) > budget:
            full = full[:budget]
    return full
