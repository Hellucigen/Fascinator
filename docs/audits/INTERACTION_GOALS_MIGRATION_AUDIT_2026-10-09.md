# 目标驱动闭环 → 陪伴层 迁移审计（Phase 1，2026-10-09）

审计范围=当前工作区真实代码（非文档承诺）：FAS-Cognitive 未提交工作区
（goal_planner.py 750 行 + goal_path_bias.py 413 行 + autonomy/config 各一处接线，
`git status` 实证）与 FAS-Companion@66bd2e7（app.py 8609 行）。

---

## 1. 两层目前分别有哪些真实能力

### 认知层（goal_planner 本轮新增，全部有测试覆盖）
`experiments/goal_planner/REPORT.md` 与 `tests/test_goal_planner.py`（15 组 32 断言，
`python tests/test_goal_planner.py` 退出码=结果）实证的能力：
- Goal：结构化谓词 `have(item,count)`，挂 self_graph 现有指针（不新建存储）；
  达成判定**只认观测库存**（T12：高激活目标节点不产生派发/达成）。
- Plan：图语义反向链（产生/需要/掉落/需要工具/属于→可采资源/拥有），
  AND 前置条件 + 预期效果 + 依据边引用；不可达一律 NO_FEASIBLE_PLAN+终止，不伪造。
- 派发：每拍至多一步、在飞去重、前置在**当前观测**上成立才出闸（含队列重验闸门）。
- Monitor：结算事实与判定分离（判定推迟到下拍取新观测）；五分支归因
  blame=action/plan/environment，失败进 exclude 集防复发。
- Learning：定向最小写回（只动依据节点的 plan_success_count/fail_count，
  T13b 断言处理器窗口内所有边逐字段不变）。
- 关闭态：`config.planner.enabled=False` 时 maybe_tick/on_settled/revalidate
  零触碰（T14），autonomy 钩子包装不安装（autonomy.py diff 实证）。

**验证边界（不得夸大）**：闭环 A/B 只在 `simenv.py` 确定性测试替身上跑过
（REPORT.md 首部"环境身份声明"）；对照结论=可达场景与近似反应式基线持平，
价值在失败可观测性与结构；真实 Minecraft/生产未验证。

### 陪伴层（现状链路，app.py 实读）
- 上下文组装：LLM 解析（:3365-3371）→ 语义召回/激活/扩散（:3760-3806）→
  **零 LLM 行为竞争 `dialogue_decide`（:4385，返回 decision/constraints/factors）**→
  `build_cognitive_context`（:4556）七分区 → `compile_for_language` L1/L2 →
  `发言提纲 build_outline`（cognitive_context.py:299，must/must_not 硬约束）→ LLM 措辞。
- 已有的"跨轮"机制：`mark_termination/inhibit_topics`（话题终止抑制，
  dialogue_decision.py:105/186）、curiosity `settle_inquiry`（悬案结算，app:3549）、
  `expression_feedback.observe_response`（**下轮开头**评估上一句的真实结果，
  app:4312，图谱共激活后验，不猜内心）、episodic_buffer、disposition 学习通道。
- 交际目的裁决者：dialogue_decide 胜者行为（respond/ask/empathize/share/continue/
  end/silence/…，disposition_store.BEHAVIORS）+ exploration 候选竞争。
- 离线可测：陪伴仓 13 个脚本式测试全离线零真实 API（拆仓日验证）。

## 2. 认知层计划器可被陪伴层复用的东西

**可复用（思想/纪律级）**：
- 生命周期与终态语义：进行中/已完成/已结束（self_graph:395-445）+
  plan_history/termination 的"可观测失败不伪造"记录形态。
- 七条硬约束中的六条（Goal≠Action、显著≠行动、判定只认观测、
  失败可观测、重规划有预算上限、写回定向不动边权、防双计划）。
- `on_settled 记事实、tick 里判定` 的两拍分离（回执瞬间不下结论）。
- exclude 集防同策略复发。

**可复用（代码级）但本轮不该用**：`build_plan` 反向链、`pre_holds`、
`state_view`、`_record_evidence`——签名即 MC 世界语义（inventory/gather/craft/
smelt/world_prior 配方）。直接 import 会把游戏世界状态带进陪伴层（任务明令禁止）。

## 3. 名称相似、语义不同，禁止直连的点

| 同名概念 | 认知层（goal_planner/autonomy） | 陪伴层（本次目标） | 风险 |
|---|---|---|---|
| **Goal** | 世界状态谓词 have(item)，由自主循环派发世界行动 | 关系/交际意图（延续话题、择机跟进） | 若把交际目标挂上 `当前目标` 指针（self_graph:395 唯一指针），autonomy 会按 obtain 子串口径误解析并派发世界行动 |
| **current_goal** | autonomy goal_attention 消费者（默认关） | 只能**旁观**，不可占用 | 同上；指针语义是"正在执行的任务"，不是"想维护的关系状态" |
| **Plan** | 多步行动序列+前置条件闸门+动作队列 | 单步交际策略为主（任务书：简单互动直接决定当前策略） | 复用计划结构会诱导"为完成计划而提问" |
| **Monitor** | 库存/观测差分核对预期效果 | 只允许**可观察对话信号**（问题是否被回答、话题是否被主动延续/转换、是否明确纠正） | 用户没回答 ≠ 失败；回复短 ≠ 生气；禁止推断内心 |
| **Learning** | 定向计数写回配方/方块节点 | 复用既有 disposition/reward 通道，本轮**只**在目标节点记 history | 一次互动不得永久改变偏好（reward 缩放学习率机制已存在，不另建） |
| **follow-up/追问** | curiosity 悬案 + exploration 候选竞争（已存在！） | 新机制不得与悬案机制造第二套提问通道 | 两套"该问什么"并存=重复跟进源头；exploration 必须仍走 dialogue_decide 同一竞技场 |

## 4. 接入点（陪伴链路中位置）

1. **Monitor**：app:4326 区（`observe_response` 返回 `_fb` 之后、`cc.note_outcome` 旁）
   ——交际目标的状态迁移与既有 outcome 观察同点消费（同一份可观察信号，
   不新建评估器）。
2. **Strategy（可选前置步）**：app:4412 `_silence_chosen` 判定之后、
   build_cognitive_context 之前——只在**已经决定要说话**的前提下微调
   `_dd.constraints/factors`（经既有 must/must_not 提纲通道进语言层，
   不新增文本生成路径）；沉默裁决不可被推翻。
3. **Goal 生成（仅显式证据）**：app:5135 `record_expression`/回合尾区——
   本轮只支持两类显式来源（用户明确请托"记得/回头/明天"类时间锚+future 意图；
   用户提出且未解决的问题被 FAS 认领），隐式话题延续**不加**新目标
   （现有 exploration/curiosity 已覆盖）。

## 5. 状态放图谱 vs 短期运行态

- 图谱（self 空间节点，`Self-[目标]->` 边，extra_attrs.kind="interaction_goal"
  与自主目标显式区分；**不占 当前目标 指针边**）：目标谓词、生命周期终态、
  advance history、blame——跨轮/跨进程留存，就是台账说的"关系状态"。
- 短期运行态（进程内 dict/回合局部）：本轮话题连续性判定、min_interval 计数、
  exclude 集、遥测 tele——重启即清零可接受（重建代价低，避免图谱污染）。

## 6. 最小集成要动的文件（实施时逐一兑现）

| 文件 | 改动 |
|---|---|
| FAS-Companion/interaction_planner.py | 新增（唯一新模块，零 LLM） |
| FAS-Companion/app.py | 3 处门控调用（各 ≤6 行，关=不进函数） |
| FAS-Companion/tests/test_interaction_planner.py | 新增确定性测试（10 组） |
| FAS-Companion/scripts/ab_interaction_planner.py | 新增 A/B 离线对照 |
| 认知仓 | **零改动**（config.py 不加节：模块 DEFAULTS 自带 enabled=False，
  开启时经 PUT /api/config 注入 `interaction_planner` 节，与 planner 同模式） |

## 7. 关闭时原有行为不变的保证

- 三重零触碰：config 缺省/False → app 接线处短路（函数不进入）；模块内
  DEFAULTS.enabled=False 兜底；单测 #10 + 既有 13 个陪伴脚本回归必须全绿。
- 开启态也只经由**既有**约束通道（`_dd.constraints` → outline must/must_not），
  不改 dialogue_decide 的胜负、不改 LLM 调用次数（策略裁决零 LLM）、
  不新增语言模板。
