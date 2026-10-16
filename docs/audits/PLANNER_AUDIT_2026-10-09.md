# 目标驱动计划器 — Phase-1 代码审计报告（2026-10-09）

只读审计。行号以当前 main（含上一轮 goal_path_bias 默认关接线）为准。
姊妹文档：`GOAL_PATH_AUDIT_2026-10-09.md`（目标数据流/图语义/扩散审计，本轮不重复其结论，
只引用其裁决）。

## 1. 目标存储与生命周期（可复用，有缺口）

- 指针：`self_graph.set_current_goal/current_goal/clear_current_goal`
  （self_graph.py:395/417/429）。单指针 in-place；终态写 `goal_state`
  已完成/已结束，节点不删。**无 TTL/衰减**（衰减在 autonomy 另一套
  `_goals`：600s demote/1800s stale/900s 豁免，autonomy.py:1176-1178）。
- 生产写入点：`ActionManager.set_goal_context`（action_system.py:1170）；
  队列排空 `_tick` 自动 `achieved=True`（378-380）。
- **缺口**：goal 是自由文本 desc（≤40 字符），**没有结构化达成条件**。
  当前"完成"判定=队列排空（执行完既定步骤即算完成），不是
  "观测状态满足目标条件"。本设计必须新增 goal_spec（结构化状态谓词），
  且完成判定只看观测。

## 2. 世界状态/库存/行动结果（有真实来源，可离线注入）

- 观测上图：`minecraft/perception.py`（世界差分 → `Haru-[当前状态]->…-[状态项]->`
  槽位；背包低频上图 `Haru-[拥有]->物品:x`，count 在边/属性上；
  "本次快照未出现的旧物品 count 置 0（拥有=此刻）"，182-183 注释）。
- 即时感知：`AutonomousLoop._inv_counts(percept)`（autonomy.py:1641）
  从 `percept.inventory_items` 算 {name:count}——**percept 是计划器
  首选状态源，图观测为次选**（两者都真实，不需伪造）。
- 行动回执：`minecraft/actions.py` 头注释——"每个动作返回结构化结果
  {success, action, target?, result|reason}，失败也必须产生反馈"。
- ActionManager 结算流 `_settle`（action_system.py:534-600）：
  统计（success/failed/interrupted/cancelled 计数）+ `_recent` 环形
  + `_emit_result_event` + `_write_action_memory`（事件框架证据节点
  `行动经验:atype(sig)`，**success_count/fail_count 账本**，
  1041-1163）+ `_apply_reward`（倾向通道）+ **`on_settled` 回调钩子**
  （215 行，autonomy 已占用于 recency/失败计数，autonomy.py:306）
  + 具身 `on_settled` 世界事件协议 + 投递回执。
- **现成接缝**：`am.revalidate`（action_system.py:216,367）——
  队列出队执行前的世界状态重验钩子，autonomy 实现为
  `_revalidate_queued_action`（385：重试冷却+对象在场重验，fail-open）。
  计划器的"步骤执行前按当前状态重验前置条件"可挂在同一点（链式包装），
  不需要新机制。

## 3. 图谱语义/provenance/写回（沿用上轮裁决）

- 承载状态转换的边：`产生/需要(count)/掉落/需要工具/属于→可采资源/拥有`
  （world_prior.py:209-315 写入，带 provenance：knowledge_type/
  mc_version/version_verified/confidence，111-116）。
- 纯语义边（关联/关于/涉及/表达方式…）不入计划依据（上轮白名单裁决不变）。
- 配方节点：`extra_attrs.type=recipe`，kind ∈ {craft, smelt}，
  needs_table、tool、yield；材料在 `配方-[需要]->物品:x (count)`。
- 写回护栏：Hebbian 白名单类别+max_gain 限幅（diffusion_engine.py:268-298）；
  事件框架极性边（force_weight 覆盖异号，add_edge:512）；
  `graph_evolution_log.py` 记录结构变更。**没有通用的"行动效果"边**
  （见 §5 限制）。

## 4. 现有规划/队列/监测逻辑（核心事实源，必须复用）

- `world_prior.next_step(kg, target, inventory, exclude)`（678-881）：
  纯读图爬链，返回 {action: done|craft|smelt|gather|explore,
  item/block, chain, why, cost}；带全链代价择优（背包感知+环罚,
  _chain_cost 577）、证据分级（_evidence_rank 535）、
  `_inputs_ok/_missing`（438-445，AND 语义的原料判定已有！）、
  `_gatherable_block`（448：可采白名单，**异常时保守放行是执行层兜底，
  计划器不复用该兜底**——计划层必须严格判不可采）。
  已生产接线：autonomy.py:1697/1750/1908/1944。
- 候选派发形态：`_act(action_type,target,params,motivation,expected,reason,
  priority,urgency,explain,interruptible,timeout_s)`（autonomy.py:2506）
  → `am.propose(spec, source)` 入 current/queue。
- **反应式基线的真实行为**（本轮对照 A 的口径）：每拍调用 next_step
  出**一步提示**转候选；无计划对象、无步骤状态、无重验失败归因、
  无重规划概念——目标推进完全依赖每拍重新查询；smelt 在途状态由
  `g["smelt_pending"]` 硬编码分支维护（1706-1743）。
- 技能执行器可离线驱动：`SkillContext(bridge=…)` 接受注入的桥对象
  （skills/base.py:221-224，duck-typing get_state/inventory）——但
  完整技能状态机（gathering/crafting）还依赖 bot 端语义；本轮闭环实验
  用**显式确定性测试替身**（SimEnv）执行动作语义，不复用 bot 技能
  （见 §6 不可验证项）。

## 5. LLM 消费者序列化（goal_path_bias 教训的直接引用）

- 工作集= `get_topk(k=8)` 按激活降序的节点+边序列化；族 L 实测
  hop-0 目标节点置顶导致 23/30 次"以目标当下一步"
  （experiments/goal_path_bias/FINAL_REPORT.md §3）。
- **计划器设计的对应约束**：计划是结构化对象，派发依据=前置条件在
  观测状态上的成立判定，**不读激活、不占 Top-k**；goal_path_bias 保持
  默认关且与本机制正交（规划路径与激活动力学分离是架构事实，
  relation_direction_campaign §130 裁决）。

## 6. 分类清单（任务要求逐项回答）

**已有可复用**：self_graph 目标指针与终态；ActionManager 生命周期
（propose/queue/tick/超时/poll/settle/revalidate 钩子/on_settled 钩子/
事件框架证据账本）；world_prior 读 API（producers_of/drop_sources/
tool_required/_inputs_ok/_chain_cost/next_step 语义与 provenance）；
_obtain_goals 的物品解析口径；_act 候选形状；autonomy 目标生命周期
参数（demote/stale/grace）。

**缺失需新增**：
1. **Goal 的结构化达成条件**（goal_spec：`have(item,count)` 谓词）与
   "达成=观测满足谓词"的判定器——现有"完成"判定是队列排空，语义错位。
2. **Plan 对象**（有序步骤+前置条件 AND 结构+预期效果+依据边引用+
   步骤状态机+修订号）——next_step 只给单步提示，无跨拍计划身份。
3. **监测器的分类归因**（A-E 五分支：预期达成/待定/失败且归因
   action|precondition|observation|plan|environment/环境变化重验/
   外部达成清理）——现有 _settle 只有成功/失败二值。
4. **步骤级派发闸门**：队列里只允许"前置条件在当前观测成立"的步骤
   出队（revalidate 钩子的计划器实现）。

**组合现有代码即可解决**：向后链规划（用 producers_of/drop_sources/
_inputs_ok 递归，不新建知识）；动作候选派发（_act 形状 + am.propose）；
失败留痕（事件框架通道语义，计划器写同构证据字段）；去重（计划挂在
goal 节点上，天然单实例；已派发步骤状态防重复入队）。

**必须新增的数据结构/接口**（最小集）：
- goal 节点 extra_attrs["goal_spec"] = {type:"have", item, count}
- goal 节点 extra_attrs["plan"] = {plan_id, revision, steps[], history[]}
- 状态视图 StateView（来自 percept 或图观测边，标记来源）
- goal_planner.tick(kg, actions, state, config) 编排入口 +
  revalidate 链 + on_settled 链。

**不可在当前仓库可靠验证（如实披露）**：
- 真实 Minecraft 执行闭环（桥/bot 在仓库外依赖，上一轮已证拆仓缺
  sandbox_lab；本仓 minecraft/bridge.py 是 HTTP 客户端需要活 bot）。
  闭环行为实验只报**确定性测试替身**结果，明确标注模拟。
- `smelt 需要炉子在场` 的"设备在场"语义：图上没有设备在场谓词的
  标准结构（world_prior 靠 seen_blocks 现算），计划器以
  {type:"seen"} 前置条件表达，离线可注入、生产接线需感知层配合——
  列为接口限制而非缺陷。
- 行动效果边：图谱没有"动作→效果"的通用可执行结构（效果语义=
  配方 需要/产生 边的反向使用）；本实现用配方边推导效果
  （craft X ⇒ +X, −inputs），不新造边类型，限制写入文档。
- disposition/reward 通道与计划器的交互：本轮**不触碰**
  （约束"避免同时改多种学习机制"）。

## 7. 最小架构与状态机（设计定稿）

```
Goal(节点 goal_state=进行中, goal_spec) 
  └─ Plan(goal 节点 extra_attrs.plan, revision)
       Step{id, action∈{gather,craft,smelt}, args,
            pre:[{have|tool|gatherable|seen|device}, ...]  # AND
            expect:[{have,+n}], justification:[edge refs],
            status: pending|dispatched|done|failed|invalidated|cancelled,
            attempts, evidence:[reason strings]}
状态迁移（每拍 tick，全部以观测 StateView 为准）：
  pending --前置全成立且队首--> dispatched(入队,带 step_id)
  dispatched --settle ok + 预期 delta 出现--> done → 重查 goal_spec
  dispatched --settle ok + delta 未出现--> failed(blame=plan|observation) → 重规划
  dispatched --settle fail--> failed(blame=action|precondition|environment
      按当前状态是否仍满足 pre 区分) → retry(≤2) 或 重规划
  pending --状态变化令 pre 永假(环/不可采)--> invalidated → 重规划
  goal_spec 满足(任何来源)--> Plan 收束: pending 步 cancelled(external)，
      clear_current_goal(achieved=True)
  重规划预算 revision≤max_revisions，超限 → goal 终止(achieved=False,
      证据 NO_FEASIBLE_PLAN)；旧 plan 由 revision 递增整体替换，
      防新旧同排（派发闸门只认 goal 节点当前 plan_id）。
规划算法（有界反向链，纯读图）：
  need(item,count): 满足→[]; 环→UNREACHABLE(CYCLE); 深度>max_depth→
  UNREACHABLE(DEPTH); 配方(优先已见/低代价，AND 递归缺料) ∨
  采集(方块必须 属于→可采资源，严格；工具缺→递归)；均无→
  UNREACHABLE(NO_PRODUCER)。UNREACHABLE 一律不派发、不伪造。
学习记录（最小、可追溯、不动边权）：
  配方节点计数 plan_success_count/plan_fail_count(带 blame) +
  事件框架同构的行动经验计数（生产已接线通道，enabled 默认关由宿主配置）；
  单次成功不放大任何权重（护栏：无自动 promotion，计数只是证据）。
```

涉及文件（Phase 2）：新增 `goal_planner.py`；`config.py` +`planner` 节
（默认关）；`autonomy.py` +≤12 行接线（tick 调用+钩子链，默认关逐位不变）；
新增 `tests/test_goal_planner.py`；新增 `experiments/goal_planner/`
（simenv.py、run_closedloop.py、artifacts、REPORT.md）。
不改：diffusion_engine/self_graph/world_prior/graph_model/action_system
核心（只用其公开钩子）。

---

## 追加更正（2026-10-12，第三阶段复核）

§6"不可在当前仓库可靠验证"中关于 `sandbox_lab.py 拆仓缺失、历史战役脚本
import 不可满足` 的表述**有误**：该文件存在于 `FAS-Companion/scripts/
sandbox_lab.py`，且内部带 split_repos bootstrap（自动挂载 FAS-Cognitive）。
历史战役（routing v2/信标/机制实验）从陪伴仓侧运行可复现；当时的"缺失"
结论源于只在认知仓内搜索。本阶段 mc_env 适配器复用其同族资产（SimEnv/
sandbox_bridge）继续可用，goal_planner 自写桥保留为冗余件不再依赖。
