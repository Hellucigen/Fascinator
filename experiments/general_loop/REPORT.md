# 通用任务闭环 — 阶段最终报告（2026-10-12）

按 §10 十二问逐条回答。证据文件：`experiments/general_loop/taskloop_run.log`
（38 断言全 [PASS]）、`docs/audits/GENERAL_LOOP_AUDIT_2026-10-12.md`、
`tests/test_taskloop.py`。全部测试零 LLM、零网络、临时目录隔离。

## 1. 原先通用闭环完成了多少
三条平行专项环（MC planner / 阅读 ledger / 文件动作无环），共享的只有
ActionManager 队列与 memrep 原语；"目标+约束+完成条件+核验+恢复"的决策
核不存在（审计 §断点 1/3/5）。planner 的核真实存在但词表绑死 MC 配方；
阅读环真实存在但只服务阅读。

## 2. 已有 vs 只有名字
真实可用：goal_planner 的监测/排除/修订骨架（SimEnv 实证）、reading
台账（26 测）、prior_knowledge 缺口账本（drive 真消费）、json_store。
有名字无消费者：`faiss_recall_topk`、conversation_gap_detector、
`queue_goal`、planner `attach_goal` 生产入口、FILE_READ 执行器（本轮补）。

## 3. 本轮生产文件改动
- **新增 `taskloop.py`**（通用决策核：接地算子协议 + best-first 规划 +
  每拍一步 + 观测核验 + 六态决策 + 台账持久化 + `plan_trust_receipt`
  消融）。零自动接线——惰性库，不改变任何现有行为。
- `experiments/general_loop/{sandbox_env,file_env,reading_env}.py`：三个
  环境适配器（规则与校验归环境；reading_env 只是委托 ReadingLedger，
  未复制逻辑）。
- `tests/test_taskloop.py`：14 用例 38 断言 + 防空跑护栏。
未动：扩散、planner、reading、memrep 主体、宿主（本轮无需宿主改动）。

## 4. 沙盒是否真由 Haru 决策
是：环境只提供 `ops/snapshot/execute`（规则+故障注入），不含任何目标
序列；行动序列由 `taskloop.plan` 从"当前快照→目标差距"搜出（01 用例
断言步序列由核生成且末态核验；03 用例证明环境伪造回执时核不被骗）。
容量 1 世界（02）需中途 put 绕行——由规划器自发产生，非脚本。

## 5. 三任务是否共用同一闭环
是（t12 结构性验证 + 14 用例事实）：沙盒（01/02）、文件（09/10）、阅读
（11）全部经同一 `TaskLoop.step/run/plan/report`；各域只换环境适配器。
文件与沙盒的"完成=观测核验"、阅读的进度即台账，均出自同一决策枚举
（CONTINUE/REPLAN/BLOCKED/PARTIAL/COMPLETED）。

## 6. 有实测证据 vs 仅单测
实测（离线真实执行）：多步完成、容量约束、持续伪造拒判、突变重规划、
不可达零执行、约束禁项+对照、崩溃恢复、台账串台拒收、文件冲突拒覆盖、
阅读经核完成、消融对照谎报可测、goal 规格校验。
仅单元/离线级：真实 LLM 参与"目标理解"（validate_goal_spec 只有结构
校验；LLM 解析→约束保留验证链路未真跑——见 §12）。

## 7. 失败重规划与不可达识别
REPLAN 触发路径实测（02 绕行、04 突变后仍 COMPLETED 且 unexpected≥1）；
不可达在规划期即 BLOCKED 且**零行动**（05，不烧步数）。

## 8. 约束违反/虚假完成/状态不一致
全程 `constraint_violations=0`；虚假完成在闭环侧 0（13：持续伪造世界
拒判完成），消融臂（同规划、关核验）在同一世界 claimed_done=True 而
真实 unmet 非空——证明防谎报来自"核验+重观测"环节本身。台账串台
（08）与文件盘上冲突（10）均硬拒不静默。

## 9. 测试与运行统计
`test_taskloop.py`：14 用例 / 38 断言 / 0 失败 / 0 跳过（独立脚本入口 +
pytest 收集双通道，带"注册用例≥14、断言≥30"防空跑护栏——护栏曾抓到
一次真实空跑）。全仓 pytest **160/160**。未验证项见 §12。

## 10. 生产接入安全性
默认配置不变（实测 reader/memrep/planner/goal_path 全 False）；taskloop
为惰性库未接入任何 tick；文件操作仅在构造时给定测试根目录内（越界硬拒、
无删除算子）。

## 11. 当前最关键缺口
"用户自然语言 → 结构化目标+约束"的**真实 LLM 提取→校验**链路：现在只有
`validate_goal_spec` 的结构闸门，没有真跑过的解析器接入。闭环本体已通，
输入侧（理解）仍靠结构化直给。次要缺口：规划器无动作代价/历史信息利用
（不读经验成本）；REPLAN 无"该算子不再信任"的排除记忆（03 靠重试上限
收敛而非拉黑）。

## 12. 下一步（按价值排序）
1. 把宿主 app.py 的意图解析接 `validate_goal_spec` + taskloop（一次真跑
   会话验证，约 5-10 LLM 调用，需授权）。
2. 给 TaskLoop 加"verify-miss 计数超阈→该接地算子临时拉黑"（planner
   exclude 语义复用），消除 03 类靠步数上限收敛的钝感。
3. 行动代价/历史成功率进入规划启发式（用 plan_success_count 账本）。
4. 与 goal_planner 合流：MC 域作为第四个环境适配器接入同一核（消灭
   最后一条平行环）。

测试命令：
`python -X utf8 tests/test_taskloop.py`（独立，含护栏与日志计数）；
`python -X utf8 -m pytest tests/test_taskloop.py -q`；
全仓 `python -X utf8 -m pytest tests -q` → 160 passed。
