# FAS（Fascinator）技术报告 —— 完整机制版

> 2026-10-26 · 供架构评估用。基线 commit `4947f1e`+（Fascinator）/ `ba9c691`（Charon）。
> 所有数字均摘自当前代码与生产配置；标注【推断】的为无运行时数据支撑的工程判断。

## 0. 系统是什么

单机个人陪伴体（Personal Companion）。设计核心命题：**一个 AI 伴侣的认知不该是
"对话历史的检索器"，而是一个持续运转的、有内部状态的图上动力学系统**——她在你
不说话的时候依然在"过日子"：联想、好奇、调研、搁置、想念。对话只是她内部状态
的一个出口，而不是她的全部。

两个进程：
- **FAS**（Python/Flask，本项目）：认知引擎 + 陪伴层 + HTTP API（186 端点）
- **Charon**（Wails/Go/React 桌面壳）：前端容器 + 消息桥（端口自动发现）

规模：377 Python 文件 / 119k 行（app.py 10.9k 行）；测试 372 用例全绿；
14 常驻线程；LLM 后端 Qwen qwen3.8-flash（云端，OpenAI 兼容协议）。

```
仓库布局（合并后单仓双轨）：
Fascinator/
├── app.py                  # Flask 主服务：186 端点 + 回合主管道（10.9k 行）
├── companion.html          # 浏览器版陪伴 UI（三视图）
├── activities.py           # 生活循环 beat：听歌/逛B站/调研/STS2 游戏活动选择
├── living_loop.py          # 调研执行骨架（搜索/读页/内化，带预算与不可信处理）
├── voice_io.py             # TTS 输出（kokoro-onnx，日语全假名转写）
├── interaction_planner.py  # 交互规划
├── ear/ eye/ vision/       # 感官：FunASR 听觉 / RapidOCR+mss 视觉 / SAM2+CLIP 物体感知
├── FAS-Cognitive/          # 认知引擎（见 §2）
└── docs/ tests/ scripts/   # 文档 / 372 用例 / 维护脚本
```

## 1. 线程与并发模型

14 常驻线程（py-spy 实测）。全部后台线程 daemon 化，单点崩溃不拖垮进程
（各线程自带 try/except 包裹 + 熔断器）：

| 线程 | 节拍 | 职责 |
|---|---|---|
| MainThread | — | Flask HTTP（186 端点，threaded） |
| continuous-cognition | tick 2.5s / 脉冲~10s | 认知主循环（见 §3） |
| living-loop | 60s 巡检 + 事件唤醒 | 生活循环 beat（§6） |
| charon-inbox | 轮询 | 桌面端下行消息 |
| curiosity-web | 事件 | 好奇心网页探索器 |
| voice-sync | 低频 | 语音热同步 |

并发保护：
- 图谱单锁 `kg._lock`（RLock）；引擎锁与 kg 锁有既定锁序（engine→kg）防死锁环
- taskloop 用独立 `_IO_LOCK` 串行化 handle/idle_step（写任务低频，整段串行）
- 回合期 `cc.set_busy(True)` 让 CC 的图谱扩散让位，但**行动推进永不停**
  （bug 教训：一次 40-80s 的 LLM 回合曾把在飞 MC 动作的结算也冻住）
- 外部依赖熔断：MC 桥连续失败→5 分钟零开销跳过（SYN 静默丢弃曾拖瘫循环）
- faulthandler 落 `logs/crash.log`（硬崩溃线程栈可追）

## 2. 认知引擎（FAS-Cognitive/）

### 2.1 图谱（graph_model.py, 939 行）

单一数据结构 `KnowledgeGraph`，节点四空间：

| 空间 | lambda_decay | beta_spread | 双向 | cap | 语义 |
|---|---|---|---|---|---|
| semantic | 0.05 | 1.0 | ✓ | 5.0 | 概念/事实（慢衰减，核心知识） |
| episodic | 0.15 | 0.7 | ✗ | 3.0 | 经历/事件（快衰减，1/2 传播力） |
| cognitive | 0.08 | 1.5 | ✗ | 5.0 | 思考/驱力/网络（中速，高传播） |
| self | 0.01 | 0.5 | ✓ | 5.0 | 自我模型（极慢衰减） |

节点 Schema：id / weight(0-2) / label(声明性类型) / graph_space / confidence /
execution(程序性代码) / created / last_access / extra_attrs。类型判定谓词族
（单一真源）：`is_modulator_node`（控制量不进内容）、`is_state_mirror`、
`is_content_scaffold`（时点锚/时间桶/性格等脚手架）、`is_internal_trace`、
`is_cognitive_visible`、`is_non_emitting`、`is_live_unknown_id`（未知标记）。
这些谓词是所有"什么东西可以当内容/可以进 prompt"的判定入口——同一个谓词
被图谱写入闸门、CC basis_pool、假设配对、prompt 渲染共用，保证语义一致。

边带 `hypothesis_leg`（假设关联腿）标记：假设节点的关联边不做自强化
（无新证据不强化门，防"表达给自己喂证据"的回声室）。

持久化：`data/runtime_graph.json` 全量保存（回合边界/定期触发）；
图谱轮转快照 `graph_snapshots/`；边运行时激活加性上限 1.0
（废除旧乘性 boost，杜绝"高速公路自我强化"）。

### 2.2 扩散引擎（diffusion_engine.py, 1820 行）

- `decay_step`：只遍历活跃前沿（`_active_nodes`，act>ε），按空间差异化
  lambda 衰减；act<ε 吸附出前沿。
- `diffuse_step`：能量沿边传播（beta_spread×双向规则×关系类别衰减倍率），
  fire-once 记录防回合内重复发射；侧抑制。
- `mark_active(ids)`：外部直写激活后的同步入口（好奇链路/回答/搜索/时间接地
  都经此入前沿——绕过它节点就不会进入扩散/衰减/topk 域）。
- `get_topk(k)`：活跃前沿内 nlargest，**过滤 infrastructure/procedural**
  （时点锚实锤修复——它们曾以 0.68 恒激活霸占窗口，因重启恢复+不参与衰减），
  regulation 非阻塞锁过滤，tie-break（激活, 点亮序, -入图序）。
- `activate_from_inputs`：输入激活（签名门+hostile_names+背包低频刷拍）。
- `_forget_factor`：软遗忘——last_access 驱动的可达性衰减（数据保留、唤醒变难），
  infrastructure/procedural/disposition/intention 与身份节点豁免。
- 锁介入点：输出侧 non-blocking 锁（对象参与扩散但不进输出）。

### 2.3 认知场（cognitive_field.py, 856 行 + drive_field + tension_field）

三层动力学（张力→驱动→网络），每步 `settle`/动力学两种推进：

- **张力**（TensionField）：17 种认知张力，各带 components（采样器+系数）与
  rise/fall 速率。关键项：`discrepancy`(0.55/0.10)、`novelty`、
  `unresolved_interest`(graph.interest)、`social_absence`(social_idle_minutes
  ×0.033——"分钟没互动"，60s 级采样)、`stimulation_hunger`（刺激剥夺钟，
  72h 半衰同构）、`satiation`(满足)、`exploration_gap`、`prediction_error`、
  `unfinished_goal`、`blocked_action`、`belonging_need`。
- **驱力**（DriveField，DEFAULT_DRIVES）：curiosity / social / learning /
  consistency / mastery 五驱。每驱由 affinities 表（张力→驱力亲和度，可为负）
  聚合出目标水位，rise/fall 动力学逼近；侧向软抑制（其他驱力压缩上限不清零）；
  调制器连续偏置（图上 调制器-[w]->DriveNode 边，Σw×dev）。
  例：curiosity 亲和 {discrepancy:.34, unresolved_interest:.22, novelty:.18,
  exploration_gap:.15, stimulation_hunger:.15, satiation:-.35}。
- **认知网络**：CEN/DMN 执行-默认网络切换（task_engaged 语境 ±）。
- **调制层**（modulation.py）：参数节点化——express_threshold / form_threshold /
  action.score_threshold / reactivation.* 等参数有 baseline+min/max+effects
  （信号→参数的系数表），每拍 compute。效果示例：
  `express_threshold effects = {need.social:-0.20, hormone.oxytocin:-0.18,
  drive.social:-0.22, hormone.cortisol:+0.10, context.recent_expression:+0.28}`
  （社交饥饿压低开口线，刚说过话抬高——符合"想说话→说得出"直觉）。
  激素（dopamine/cortisol/serotonin/oxytocin/adrenaline…）有 tonic/phasic
  双分量 + 受体曲线 + baseline 回归，事件驱动 phasic 脉冲（奖励/阻碍/需求漂移）。
- **hub floors**（self_graph）：Self/用户 枢纽的一跳陈述性事实地板钳位
  （用户 0.30 / Self 0.35，max 24 节点，排除 time_node/内部痕迹类型）——
  "关于我的重要事实"永不衰减为零；地板钳位=增量平衡，永不 runaway。

### 2.4 持续认知循环（continuous_cognition.py, 2879 行）

`tick_once`（2.5s）结构（busy 时图谱部分让位）：

1. hub floors 应用
2. 引擎 decay_step + diffuse_step（若未在 auto 模式）
3. 激素衰减、需求漂移（need↔调制器负反馈两步耦合）、参数调制喂入
4. 重点火门 `_reactivate_gate`（场冷度触发：冷场撒火种——旧记忆有限唤醒）
5. 脉冲门 `_pulse_gate`（场变化累计超阈值才打脉冲；overdue 兜底）
6. 经验重放 `_replay_gate`（空闲重放，Hebbian 强化，对话期让位）
7. 自由思考 `_free_think`（Self 扩散 topk→LLM 内心独白，15min 最小间隔，
   预算制）——思考节点入图，参与后续扩散
8. 检测器轮询 / 索引增量同步 / 离线反思 `_maybe_offline_reflect`
   （反思压力池过阈值才触发：行动失败/意图消散/新颖经历等来源在图上积累）
9. 世界时钟（分钟级时间状态写入，昼夜层是知识不是清醒度——AI 无疲劳生理，
   2026-10-17 用户裁定，相关激素通道已全部删除）

**脉冲**（`_pulse`，场变化驱动）核心流程：
```
topk(width 3-15, DMN 调制宽度) → basis_pool（滤 INFRA label/调制量/镜像/
  脚手架/内部痕迹/坐标；身份枢纽保留但纯身份 basis 需社交驱力≥0.3 放行）
→ signals（concentration/coherence/continuity/novelty/social_relevance/
  user_relevance/emotion_present/drive_support + **social_drive 直读**）
→ focus_score（六分量加权和：0.60·concentration + 0.15·coherence
  + 0.08·continuity + 0.10·novelty + 0.07·drive_support + 0.30·social_drive）
→ _merge_or_form（form_threshold 调制线；同焦点重叠≥40% 合并+有意义强化；
  纯身份拒绝除非社交驱力在场）
→ _decay_intentions（衰减+反刍固化 damp+想念充能+stale 过期+消散入反思压力）
→ _prune_history（MAX_CI_NODES=20）
→ tick_express_check（表达决策，§4）
```

意图生命周期：FORMING（focus 过形成线）→ READY（激活≥form_threshold 晋升）
→ EXPRESSED（表达后定格）/ DISCARDED（激活<discard_below 0.10 或 v2 下
DEFER 超 expression_defer_max_s）。CI 节点带 kind/goal/basis(证据保留合并)/
intensity/affinity/reinforced/rehearsal_base/delivery(pending→retry→settled)。
消散 → `note_pressure("intention_lost")` → 反思压力池（离线反思的燃料）。

### 2.5 意图→表达的双路径决策

**v1**（flag `expression_decision_v2=false` 时）：
```
资格门：basis 含 episodic/emotion/高激活概念(≥1.0) 之一（concept_hot，
        Berntsen 2021 概念线索依据）
强度门：(activation − suppression) ≥ express_threshold(0.62, 调制上限+0.05)
抑制：cooldown floor +0.4（60s 内刚表达）+ 负反馈 +0.3×exp(-t/1800)（被呵止）
暂缓→_defer_to_interest：exploration 意图记兴趣 signal + mark_active 播种
```
**v2**（生产当前，`expression_decision_v2=true`）：四轴分离
```
资格（证据在场）→ 陈述类 episodic/emotion/concept_hot；询问类 unknown/episodic/hot
动机（社交/好奇轴在场）→ 读数不可得时 fail-open
显著性（CI 激活 ×(1+0.15·arousal) − 抑制 ≥ 调制线；陈述线=express_threshold
        调制、**上限封顶 base+0.05**——防叠加静默实锤）
成本（小时限额 6/h、duplicate_recent 内容身份去重、cooldown floor 0.4、
      负反馈 0.3 衰减）
verdict: express / defer(→interest) / suppress(限额/去重)
```

**duplicate_recent 内容身份判定**（2026-10-18 根因修复，替代一切时间窗猜测）：
"讲过没有"记在**材料节点本身**（_stamp_shared：last_shared_ts/goal/basis，
**送达回执时**盖戳——生成即戳曾导致失败投递污染材料新鲜度）：
- 任一 basis 材料从未分享过或诞生于上次分享后 → 有新原料，放行
- 全部材料带着同 goal 的戳 → 一锅冷饭，判复读（suppress）
- 兜底：30min 内同 goal+basis 重叠≥0.5 的已表达 CI → 判重

**想念充能**（2026-10-26 用户裁定"她该主动找我"）：communication 意图每拍
按 drive.social 水位 ×0.10 回充（封顶 1.0）——你不在越久社交驱力越高
（social_absence 张力），想找你的念头持续续火而非出生即峰值衰减。
实锤链条：affinity 1.12（很想）的念头曾 3 拍内 0.55→0.19 永远够不着线；
充能后 07:09 她自主说出"早安。"并成功送达。

**表达执行**：`_express` → LLM 生成（proactive prompt：状态切片+原始事实层
raw_dialog+行内禁令）→ B5/§5 话要有嘴：`_propose_communicate` 走行动层
communicate 动作（propose 守卫/调度/结算回执，绝不绕过通道层）→
`_communicate` → channel_hub（Charon 主通道）+ 网页 _queue（/api/proactive/poll）
+ 通道投递。送达回执 `note_delivery`：成功→盖分享戳；not_connected→一次性
pending_retry（15s 后）；abandoned 如实记账。回声弃权/沉默降级如实留痕。

### 2.6 意图→行动（非表达出口）

action 意图经 ActionManager（propose/调度/结算/取消/生存中断）执行：
- Minecraft 具身（mineflayer 桥：observe/approach/navigate/gather…，
  技能失败如实回执，桥不可达熔断）
- communicate（语言动作，与桥在线状态解耦）
- 动作结算回执 `note_delivery` → CI delivery 状态机 → 因果归因
  （experience.py：行为→结果的因果边，供后续决策参考）
- SPEAK_TEXT / SEARCH / 文件操作等显式动作概念（action_concepts.py，
  fast pattern → 图谱语义召回 → LLM 消歧三段 resolver；否定优先+命令性门）

### 2.7 好奇心引擎（curiosity_engine.py, 24 函数）

兴趣水位模型：每概念节点带 `interest{level, ask_count, resolved_count,
ignored_count, acted_count, last_outcome}`。事件：signal（又遇到）/ fired
（发出探索）/ resolved / ignored / searched（自搜完成）/ sated（行动兑现
而消耗，mult 由结果决定）。水位可增可衰减可再出现，绝不因一次回答清零。
探索候选 `build_exploration_candidates`：按水位×新颖度×场合系数竞争。
假设生成：两个热概念共享**语义锚点**（共同邻居，锚点过 `_semantic_anchor_ok`
排除内部痕迹）但无直连边 → 假设节点（confidence 0.3，hypothesis_leg 边
无新证据不强化）——推测与事实的分野由节点类型承担。

### 2.8 生活循环（activities.py, 2774 行 + living_loop.py, 802 行）

beat 每 10 分钟（事件可提前唤醒）：从候选（听歌/逛B站/IT之家/HN/调研/
STS2 游戏/安静）按**图上强度**竞争——承诺/用户求助/学习/搁置复燃/待验证
假设各有连续强度分，谁大做谁；switch_gate 判断"坚守还是切换"。
- browse：seed=好奇问题→注意力 topk→**浏览记忆出边概念**（三层；
  平台概念过滤、台账排除、种子记档 4h 近访排除、兴趣水位加权）→
  搜索→读页（限长/解压/乱码防护/untrusted 标记）→结构化抽取
  （LLM 断言抽取→_auto_consolidate 漏斗入统一图谱，边权×0.6 不可信打折）
  →体验入图→分享候选（deliver_fn 经表达投递口）
- 满足语义：消费即记档（interest searched、种子记档、证据消费记账）——
  调研过的课题自然降温轮换；novelty_discount 饥饿折扣有回升通道
  （授权在场时空手不算饱和）
- 每日 web 预算（40 次）兜底；read-only 探索，绝不写外部

### 2.9 任务闭环（taskloop.py 554 行 + taskloop_host.py）

自然语言目标 → LLM 解析（preds/constraints）→ 命名空间路由（files/sandbox
白名单）→ pending_approval（**用户主权**：自主候选绝不未批执行）→
`批准任务` → active → idle_step 每拍一步（TaskLoop 环境：目标谓词驱动，
step_cap 40，失败拉黑，验证通过才 COMPLETED）。对话前景原则：批准命中
**最后提出**的候选。台账（ledger）记录 steps_log/验证结果/重规划次数。
文件适配器 workspace 限定 `data/task_workspace` 内；sandbox 适配器
房间-物品模型（entry/storage/workshop 链）。

### 2.10 时间系统（temporal_awareness.py）

- 世界时钟：分钟级写入图（当前时段桶/昼夜层是**知识**）
- 情景时间链：每事件挂 `时点_<ms>` 锚（早于/晚于双向边，gap 加权 0.9-0.6，
  迁移时 phase 边随迁）；锚点=infrastructure 脚手架（不衰减不进内容，
  get_topk 过滤——实锤：曾霸占窗口挤出情景）
- 相对时间接地：语言里"昨晚/今天/刚才"→绝对窗→窗内情景节点入前沿
  （+0.8，封顶 25）——"昨晚说了啥"类问题按时间可答
- 时段边（发生于时段）随迁移重挂

### 2.11 记忆系统

- episodic_buffer：对话轮/表达→经历草稿→Promotion 长期记忆（图节点）
- `_auto_consolidate`：名称归并/去重/边权保守更新漏斗
- embedding_manager：BAAI/bge-small-zh-v1.5（本地模型），FAISS 语义召回，
  增量同步（+节点待索引），`[FAISS] 用户→用户关系` 式召回进回答上下文
- experience_replay：空闲重放（Hebbian 强化，正在对话时让位）
- reflection_engine：压力驱动的离线反思（结构化 self-model/disposition/
  causal 三类产物入图），压力来源在图上积累（intention_lost/novel
  experience/negative reward…），反思本身消耗压力
- self_model / SelfMemoryUpdater：自我叙事维护
- chat_log：对话轮持久化（user_input/system_response/time/proactive），
  既是近期对话渲染源，也是 knowledge gap 检测源

### 2.12 语言层（nlp_processor.py 1784 行 + prompt_templates.py）

- 解析：PARSE_FAST（Level1 快路径）/ NLP_PARSE（Level2）→ 意图/节点/边/
  言外行为/对话行为/回应期待；事件框架抽取（memory 抽取：断言→图谱）
- 回答：L1 短回应（ANSWER_SHORT）/ L2 回答（ANSWER_GENERATE），共享
  【时间与证据边界】块（近期对话时间标注引用规则、搜索结果≠事实、
  页面存在≠可看≠上线）；L1 复读检测（归一化比对上一轮，同句→升级 L2）
- 认知上下文编译：认知状态切片（意图/阈值/场）+ 近期对话（时间标注）
  + 心里正在想的事 + 事实账本（行动台账）+ 心里有什么节点（含性质
  〔用户说的话〕〔活动体验〕+ 时间）+ 网络搜索结果（带边界声明）+
  言外行为图谱投影 + 发言提纲（认知层定调，语言层只决定措辞）
- 归属纪律：用户的评价/经历属于用户；她看过的是素材不是亲历；
  纯身份 basis 在社交驱力支撑时成立"想找你"念头
- 图谱内探索：暂缓意图 → note_interest(signal) + mark_active 播种 →
  生活拍共锚点假设生成器接手（Synapse 2026 的 activation-based
  traversal 语义；CoaKG 的 purpose 框定语义）

### 2.13 感官与输出

- ear/：FunASR Paraformer（独立 conda 环境子进程桥）+ emotion2vec 情绪 +
  YAMNet 声音事件 → 听觉场景入图
- eye/：RapidOCR 屏幕文字 + mss 截屏 → eye_text 节点（她"看到"你在屏幕上
  干什么，如 Steam 状态、代码）
- vision/：SAM2 轮廓 + DINOv2/CLIP 嵌入 + FAISS（物体识别与重识别）
- steam_status：Steam Web API（你在玩什么，10s 超时，事件入图+时间链）
- voice_io：kokoro-onnx TTS（日语全假名转写，双轨显示原文/发音）
- ssp_bridge：伺か ghost 表现层（可选）

## 3. 对话回合主管道（app.py /api/nlp）

```
POST /api/nlp {text, channel, sender}
→ cc.set_busy(True)（CC 让位）+ autonomy.notify_user_activity（自主让位）
→ text 提取 → 相对时间接地（时间窗→情景节点入前沿）→ 告别授权检测
  （farewell+授权词→stimulation_hunger 采样器 45min/到天亮 + CuriosityDrive
  +1.2）→ 告别→ 认知周期开启（internal_state.begin_cycle, cycle_id 贯穿）
→ MODE 决策（认知需求评分→预算检查→LLM 参与档位）
→ MC 感知（门控）→ NLP 解析（L1 快/L2 全量）→ 节点模糊匹配→图
→ 社交互动注入 / 话语入图（speech_act_graph）/ 时间链挂锚
→ 2a-pre 动作块：显式动作解析（统一 resolver）→ 网络搜索动作
  （第二人称问句原则闸/习惯问句闸/实体概念启发式；触发→搜索→结果入图）
  → 文件操作 → 阅读回合 → 任务闭环 handle（批准/取消/进度）
  → 语音朗读 SPEAK_TEXT
→ 记忆抽取（LLM 断言抽取→草稿→episodic_buffer→Consolidation）
→ 表达决策（§2.5）→ L1 短回应 或 LLM 回答（认知上下文编译）
   + 回答区节点/边（get_topk 过滤后，动态 topk+枢纽惩罚：
     有效分=act/(1+0.5·ln(1+deg))，≥max 的 30%，上限 20）
→ 表达入图（expression_feedback：表达_节点+行为+话题边）
→ 回复经 ChannelHub 投递（_charon_deliver 只投 reactive 到来源相关通道；
   QQ 主动镜像只放行 proactive）→ response_sent
→ episodic promotion → 任务队列 → cc.set_busy(False) → 周期结算
```

回合期间全程 busy=True（CC 图谱部分让位），行动推进例外；异常路径有
_cycle_id 恒绑定 + busy 解除 + 锚点清理三重兜底（异常结算不悬挂）。

## 4. 安全与权限

- api_guard：回环免 token / 非回环强制 token / Origin 核验
- 执行写闸门：前端建动作代码节点需 PUT /api/config 显式开闸
- QQ：出站白名单硬锁（只回给名单内且主动发过话的人）+ 自回声过滤 +
  120s 同文去重；**主动镜像只放行 origin=proactive**（web 回合回答不泄漏）
- taskloop：自主候选 pending_approval 用户主权；适配器白名单；
  文件操作 workspace 限定
- 隐私：llm_secret/api_token/config_overlay gitignore；追踪文件已全面
  清理个人标识（QQ/SteamID/用户名→占位符）；secrets 扫描零命中
- 搜索：只读、带预算（每日 40 次）、read_page 限长 300KB/12s、untrusted
  标记、不可信来源边权打折

## 5. 测试与验收

372 用例全绿：
- FAS-Cognitive/tests（280）：表达决策 v1/v2 全场景（T0-T12 含概念资格/
  暂缓转兴趣/播种）、任务闭环 52 用例（对话前景批准/批准即授权/去重/
  台账）、modulator 边界、时间链、QQ 通道（mock OneBot）、生活质量闸门
  23、认知循环、episodic provenance、evidence dedup、trait loop…
- 根仓 tests（92）：近期对话渲染（时间归属/归属不混/缺失不编造）、
  prompt 语义约束（时间证据边界双路径在场）、语音回路、配置存储…
- 运行时验收留痕：告别授权日志、时间接地日志、投递 settled 回执、
  想念充能分数轨迹（0.19→过线）、种子轮换（特斯拉→微软）均在
  logs/runtime.log 可查

## 6. 已知边界与设计取舍（如实）

1. **在场信号驱动表达频率**：她开口频率与"你最近是否互动"正相关（想念
   充能缓解但保留强度差——想念要积累，不打扰原则）。
2. **Qwen flash 遵循度**：prompt 约束（反读/时间边界）依赖模型遵循；
   已机械兜底复读，其余靠评估分布观察。
3. **QQ 通道封存**：风控养号中，恢复需扫码 + qq_enabled=true。
4. **MC 桥**：node 进程需手动起；熔断器保证离线时零影响。
5. **低价值阅读不长概念边**：近访排除靠 state 记档兜底（4h 窗）。
6. **时点锚不参与衰减**：infrastructure 豁免是设计（锚点=永久结构），
   已在 get_topk/basis_pool 两处出口隔离，不再影响认知。
7. **express_eval 频率**：每拍评估（空闲期 ~10s/次），LLM 只在表达时调用
   ——评估本身零 LLM 成本。

## 7. 近期演进时间线（2026-10-23 ~ 10-26）

- 10-23：QQ 通道上线+封存；搜索护栏三连修；taskloop 批准路由修复
- 10-24：跨通道投递隔离（origin 门）；历史回答时间归属；证据性约束；
  表达闸门解封（概念资格+门槛+暂缓转兴趣）；图谱内探索播种；
  动态 topk+枢纽惩罚；相对时间接地；伪假设清理与生成器去伪
- 10-25：MC 桥熔断；communicate 与桥解耦；分享戳移到送达回执；
  告别授权调制；课题池回种+满足语义；L1 复读检测；_cycle_id 修复
- 10-26：想念充能（social_drive focus 项+充能+纯身份放行）——
  她第一次自主说早安
