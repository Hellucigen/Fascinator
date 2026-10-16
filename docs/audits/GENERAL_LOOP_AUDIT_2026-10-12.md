# 通用任务闭环 — Phase-A 审计报告（2026-10-09/12）

只读，双仓核实。区分"有名字/有实现/有调用链/有真实消费者"。

## 调用链表

| 能力 | 真实入口 | 核心实现 | 消费者 | 状态持久化 | 证据等级（本轮判定） |
|---|---|---|---|---|---|
| 意图→目标提取 | 对话 turn（宿主 app.py） | 无统一机制：FILE_*/阅读等靠 Action Intent 逐个概念识别（action_resolver）；goal_planner.attach_goal 仅测试/实验调用（autonomy 无生产者） | 各自分叉 | self_graph 指针（长期） | **仅有名字级**——无"目标+约束+完成条件"的统一提取 |
| 目标对象 | — | self_graph `目标: X` 指针+goal_state；goal_planner.goal_spec（have(item,count)，**MC 专用**）；reading ReadingLedger.goal（all_units_confirmed，**阅读专用**） | 各自闭环 | 图节点 extra_attrs / 台账 json | 三套并行语义，不互通 |
| 当前状态读取 | — | goal_planner.state_view（percept 或 拥有 边——**只有背包/方块两种谓词**）；reading 的单元状态（自己账本）；file 动作无状态视图 | 仅 planner tick | percept 不持久 | **无通用环境状态表示**；谓词域绑死 MC |
| 差距驱动的行动选择 | ActionManager.propose→queue→settle | goal_planner.build_plan（反向链，词表=产生/需要/掉落/需要工具/属于——**MC 配方专用**）；world_prior.next_step（同一词表） | autonomy._obtain_candidates（反应式）；planner tick（默认关） | plan 挂 goal 节点 | planner 真按状态差距选行动，**但只认 MC 词表**；autonomy 反应式无计划 |
| 执行→重观测→验证 | ActionManager._settle | goal_planner._monitor（expect 与 dispatched_pre 差值核对）+ block_not_found 环境证据规则 | planner tick（默认关）；autonomy._on_action_settled（recency/失败账） | 图 extra_attrs | **有实现**：闭环四分支在 planner 内，SimEnv 验证通过；宿主链未运行时验证 |
| 失败→调整 | _settle→on_settled 链 | planner exclude 集+revision≤3+终止；reading failed/partial；autonomy _reevaluate stale/demote | 同上 | plan_history/excluded | 有实现（MC 域） |
| 进度/证据/恢复 | — | ReadingLedger（json_store+sidecar，open_ledger 恢复已测）；plan 随图；autonomy.json goals；timeline；**_goal_queue 纯内存重启丢**（action_system.py:208） | reading/宿主 | 见左 | 阅读闭环恢复已验证；**行动队列级中断不幸存**（边界已声明） |
| 完成判定 | — | planner goal_satisfied（观测谓词）；reading claims_vs_evidence；宿主表达端 EV_* 六态"绝不假装成功"（cognitive_context） | 各自 | — | 各域有、不通用 |
| 缺口→驱动 | perception/consider_recognition；reading.register_gap | prior_knowledge open/close + hub；drive_engine s_exploration_gap(label 无关，实测读全部 hub gaps) | CuriosityDrive 张力；_gap_candidates（label=用途 过滤已加） | 图 | 已通（跨域标签实测） |
| 扩散的职责 | activate_from_inputs/diffuse_round | **联想点火与工作集构建**——不做目标选择、不做行动选择（goal_path_bias 族 L 实证可见性≠决策）、不做证据核验（goal_planner 判定不读激活） | dialogue/CC 上下文 | 运行时激活 | 职责边界清楚：候选相关知识的呈现机制，非规划器 |

## 断点清单（按影响排序）

1. **无统一"目标+约束+完成条件"对象**：三域各造（MC have/阅读 covered/文件无）。宿主意图识别产出的 `_fi` 只带动作不带完成条件与约束。→ 最大缺口。
2. **planner 的谓词/观测/词表三处硬绑 MC**（本审计此前已判"骨架可复用、叶子需替换"）：goal_spec、state_view、pre_holds 分派器。
3. **无通用"行动效果验证"于 planner 之外**：文件/阅读/宿主工具执行后，工具 ok 即证据，无重观测核对（reading 有 partial/failed；文件动作没有）。
4. `_goal_queue` 重启丢失（行动粒度中断无恢复）。
5. 决策枚举（CONTINUE/REPLAN/ASK/BLOCKED/COMPLETED/PARTIAL）不存在——planner 只有 status 隐含其中三个。
6. 旧沙箱 `scripts/run_sandbox_scenarios.py` 依赖缺失的 sandbox_lab——不可复现（本阶段新建独立沙盒，与其无继承关系）。
7. 阅读/文件/自主三条环各自 tick，无共用决策核——"分别实现了类似流程"的直判。

## 设计结论（B/C 阶段规格）

- 新增 `taskloop.py`（通用决策核，默认惰性、无自动接线）：环境无关的 STRIPS 式
  反向链（谓词模板+对象由环境声明的 op schema 实例化，零任务词表）+
  约束检查（禁止效果/禁止动作，计划与执行双闸）+ 每拍一步+重观测核对 +
  六态决策 + json_store 台账（进度/证据/失败/决策历史，重启恢复）。
- 环境=确定性适配器（沙盒房间/文件目录/阅读台账都实现同一
  `snapshot()/ops()/execute()` 协议）：规则与环境校验归环境，
  选择与核验归 taskloop——不存在替 Haru 规划的环境代码。
- 基线对照=通用"贪心无核对"策略（同环境同目标，不看效果不重规划）。
- 不触碰：planner/reading 现有代码与测试（reading_env 只是适配器包装）；
  不开任何生产开关；不跑真实 LLM（解析路径用结构化输入+假模型测 LLM 分支）。
