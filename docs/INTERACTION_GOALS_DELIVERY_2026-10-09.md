# 目标驱动交际机制迁移 — 交付报告（Phase 5，2026-10-09）

审计依据：`docs/audits/INTERACTION_GOALS_MIGRATION_AUDIT_2026-10-09.md`（Phase 1）

---

## 1. 认知层最新实现审计结论（真实状态）

计划器 `goal_planner.py` **确实存在于工作区**（750 行，未提交态），非虚构：
- 有实现、有 32 断言单测、有闭环 A/B 实验（`experiments/goal_planner/`）。
- `config.planner.enabled=False` 默认关，autonomy 钩子包装仅在开启时安装。
- **但其世界语义全是 Minecraft 的**：谓词 `have(item)`、依据边
  `产生/需要/掉落/需要工具/属于→可采资源/拥有`、行动 `gather/craft/smelt`、
  前置=背包/燃料/工作台、达成=观测库存。**没有一行可直接搬到陪伴层**。
- 环境身份：闭环验证只在确定性测试替身 `simenv.py` 上（REPORT 首部自declare），
  真实 Minecraft/生产**未验证**。
- `goal_path_bias` 是**正交的另一机制**（激活偏置，同样默认关），不是计划器本身——
  任务书提醒的"别混淆"在代码里确认成立（二者仅共享 `docs/audits` 目录）。

结论：迁移的是**控制思想**（Goal≠Action、判定只认观察、两拍结算、失败归因、
定向最小写回），实现必须陪伴层自建薄适配层。审计给出 6 个"同名不同义、禁止直连"
点，最关键：**绝不自建第二套长期记忆、绝不占用 `当前目标` 指针边**
（那是自主循环派发世界行动的通道，占用会让交际目标被当成可执行任务派发）。

## 2. 陪伴层架构与集成点

现有回合链路（app.py）：LLM 解析 → 激活/扩散 → **零 LLM 行为竞争
`dialogue_decide`（裁决是否回应/何种行为）** → `build_cognitive_context` →
`compile_for_language` → **发言提纲 must/must_not** → LLM 措辞。

已有可复用件（不重建）：`expression_feedback.observe_response`（轮首评估上一句
真实结果，图谱后验、不猜内心）、`curiosity.settle_inquiry`（悬案）、
`disposition/reward`（社交反馈学习通道）、episodic_buffer、self_graph 目标生命周期。

选定 3 个门控接入点，全部**默认关**、异常吞掉不影响本轮：
- **Monitor**（app:4368）：复用刚算出的 `_fb`，只读可观察量做目标状态迁移。
- **Strategy**（app:4438，`_silence_chosen` 为假才调）：话题在场+过闸门→
  往 `_dd.constraints` 追加一条行为姿态约束，走既有提纲通道，不新增文本生成路径。
- **Create**（app:5251，轮尾）：仅显式请托句式建目标。

## 3. 实际修改文件清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `FAS-Companion/interaction_planner.py` | 新增 ~330 行 | 交流目标闭环：create/arbitrate/observe_turn，零 LLM 零网络 |
| `FAS-Companion/app.py` | +35 行 | 3 处门控调用（每处 try 包裹，关=首行短路） |
| `FAS-Companion/tests/test_interaction_planner.py` | 新增 | 10 组确定性测试 |
| `FAS-Companion/scripts/ab_interaction_planner.py` | 新增 | A/B + 无闸门参照回放 |
| `FAS-Companion/docs/audits/INTERACTION_GOALS_MIGRATION_AUDIT_2026-10-09.md` | 新增 | Phase 1 审计 |
| 本文件 | 新增 | 交付报告 |

**认知仓改动：零。** 未新增/未修改任何认知机制、config.py 未动、实验数据未动。

## 4. 新增配置与默认行为

config 键 `interaction_planner`（不写进 config.py，模块 DEFAULTS 自带、开启时经
`PUT /api/config` 注入，与 planner 同模式）：
```
enabled=False（缺省即关）, max_active=2, advance_min_interval_s=1800,
expire_after_s=7*86400, strategy_retry_limit=2, pending_grace_turns=2
```
**关闭时行为逐位不变**（三重保证：config 缺省短路 + 模块兜底 + 测试 #10）。

## 5. 测试结果

- 确定性测试 **10 组 24 断言全过**（任务书 Phase-4 十项逐条覆盖：无目标自然回应、
  不逐轮重复、显著≠行动、话题转换优先当前、纠正入账、模糊不伪造、跨轮保留可到期、
  无目标不硬提问、策略耗尽不重试、关闭态不变）。
- 关闭态回归：陪伴 14 脚本式测试全过、认知 pytest **100 passed**、
  认知 `test_goal_planner` 退出码 0、app 装配冒烟 453 节点正常启动。
- A/B 离线对照（`_ab_interaction_result.json`）：结构行为层面，闸门相对无闸门参照，
  "话题连续复现"从 4 次提议降到 1 次且连续重复归零，"沉默"臂提议 0。

## 6. 尚未实现 / 无法验证（如实）

- **真实对话中的自然度、"是否更合适"**：本机制零 LLM，只在结构层控制"何时允许推进"，
  **无法**离线证明陪伴质量提升——那需要真实 LLM + 盲化成对人工评价，本轮未做。
- **A 臂提议恒 0** 是"现有层没有结构化请托记忆"的定义性事实，不是质量优势，不用于对比。
- 请托达成判定用图谱后验 `expression_feedback` 的 positive/negative 粗粒度标签，
  **未细分**"用户回答了问题 vs 只是延续话题"；模糊情形一律保持不确定（不判负）。
- 目标**只从显式请托句式**生成；隐式话题延续仍归 curiosity/exploration，本轮未合并两套来源
  （合并属更大改动，登记为后续项）。
- `strategy_retry_limit` 语义=同策略累计**明确负反馈**上限，不是"两次不理就放弃"——
  刻意保守，避免一次结果永久改变关系（任务书明令）。

## 7. 设计如何满足关键约束

- 不把游戏规划器复制进来：`interaction_planner` 不 import goal_planner/world_prior，
  谓词与闸门是交际语义（话题在场、反馈正负），无背包/配方/采集。
- 不把 Goal 文本当 Action：推进只追加一条"姿态约束"进既有 constraints 通道，
  由发言提纲消化，绝不拼接回复、绝不外泄目标 ID/状态词（硬约束 7，测试 #4/#8 覆盖）。
- 不每轮调完整规划器：arbitrate 是 O(活跃目标数≤2) 的常数闸门检查，零 LLM。
- 学习复用现有通道：本模块只写目标节点 extra_attrs；社交反馈进 disposition 仍走
  app 既有的 reward/disposition 路径，未新建平行偏好存储、未微调。

## 8. 是否建议继续推进

**建议：可以小流量开启验证，但不要据此声称陪伴质量已提升。**
- 结构层（防重复跟进、显著≠行动、沉默不可推翻、单次不放弃）已被确定性测试证明正确。
- 价值假设（"跨轮记住请托并择机一次跟进"优于"每轮临时生成"）仍需真实 LLM 盲评。
- 推荐下一步：开启 `interaction_planner`，用**相同模型配置**在 A/B 两组真实多轮脚本上
  跑成对盲评，重点测"是否出现重复跟进/是否错误地把长期目标当当前行动"两条负向指标
  （任务书警告的"更主动≠更好"作为红线，只评这两类可证伪的错误率，不评"话更多/更长"）。

---
### 运行/验收命令
```bash
python tests/test_interaction_planner.py          # 10 组确定性，exit 0=过
python scripts/ab_interaction_planner.py          # A/B 结构回放 + JSON
python -m pytest ../FAS-Cognitive/tests -q        # 认知 100 未受影响
```
