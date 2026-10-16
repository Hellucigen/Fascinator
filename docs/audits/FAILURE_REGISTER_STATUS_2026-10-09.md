# 失败实验登记簿 — 解决状态对账（2026-10-09）

依据：`research_audit/FINAL_DIAGNOSIS.md`、`FAILURE_REGISTER.md`、各实验
FINAL_REPORT/EXPERIMENT_REPORT，及本轮两阶段工作（goal_path_bias、
goal_planner）的实测结果。状态四档：**已解决 / 部分（有接线未验证或已绕行）
/ 未解决（本仓可做）/ 未解决（本仓不可验证，需上游）**。

| # | 失败实验 | 失败环节（原文口径） | 状态 | 依据 |
|---|---|---|---|---|
| 1 | capability_gap_v2 PRECHECK 附录 D：`current_goal()` 0 读取者、F 消融钩子 no-op | 目标数据流写而不读 | **部分→实质改善**：goal_planner 成为指针的结构化读者（goal_spec 谓词+达成判定），默认关；SimEnv 闭环验证控制面；真实环境未验证 | experiments/goal_planner/REPORT.md §1-3 |
| 2 | goal_path_bias 族 L：可见性↑但决策零收益、"目标即下一步"混淆 | 目标显著度→决策解释 | **部分**：根因已定位（hop-0 显著性+呈现模板）；goal_planner 用前置条件派发绕开该通道（不读激活）；其修复项（序列化目标项/候选项分栏、max_hops 校准）**未做** | experiments/goal_path_bias/FINAL_REPORT.md §3-4 |
| 3 | cross_episode_recomb：working-set ✗ + serialization ✗✗（G3 0/30） | 序列化/消费者层 | **未解决 → 本轮进行中**：新发现表示层根因（G3 事件节点无动作属性，动作词只活在 G2 直连边）；最小修复实验 `experiments/serial_fix/`（机制层+小 LLM） | 本文档 §补充 |
| 4 | 行为汇聚 I：PRIMARY=Interface/Representation（FAS 0-2/10 vs LLM 10/10，rep 0/30） | 同上（序列化/叙事缺失） | **未解决**：与 #3 同根因，serial_fix 结果适用 | I_FINDINGS.md |
| 5 | persistent_state_controls T3：失败证据被挤出 8 槽呈现（C3 极性排序/C4 1 跳不可达）；controls_revision 呈现等价预检 60 条失败 → 0-run 停止 | 工作集排序/呈现通道 | **未解决**：呈现等价修复（失败证据强制呈现位）未实现 | ADDENDUM_T3_AUDIT、PREREGISTRATION_REVISION §4 |
| 6 | mechanism_campaign：13/13 汇点、forward 2-hop=0 | 图本体方向语义 | **已绕行未修复**：规划器/goal_path 反向读边绕开（功能等价）；扩散 forward 穿越本身按 relation_direction 裁决不应硬改 | RELATION_DIRECTION_EXPERIMENT §129-130 |
| 7 | core_incremental_value：ΔJCG 4/4 反向显著（预算归一化+地板干扰吞噬判别信号） | 扩散预算语义 | **未解决**：属扩散核心参数语义，改动需独立预注册；与目标域正交 | FINAL_REPORT.md (c) |
| 8 | routing v2：T4 未过 Bonferroni、token 2.1-3.7×、T3 更慢 | 任务全可观察+成本 | **未解决**：需要信息不对称任务族重测；生产对话链路未渲染 demand/gap 注解（L1-CON）也未解决 | EXPERIMENT_REPORT.md H |
| 9 | routing v1：0 边图/异常吞没（INVALID ASSEMBLY） | harness 装配 | **已归档**（作废保留，v2 重跑）；拆仓后其 harness 依赖 sandbox_lab 缺失 | FAILURE_REGISTER L2-HAR-01 |
| 10 | diffusion B/B2、hebbian、ablation 矩阵：达成层零差分（评测致盲）、U1 扩散不驱动行动 | 评估器/消费者阈值 | **部分**：goal_planner 给"激活→行动"提供了非激活通道（前置闸门）；致盲的评估器问题未动 | FINAL_DIAGNOSIS E6 |
| 11 | longchain L3：熔炼任务先验缺失 0/5 | 任务先验覆盖 | **未解决**：world_prior 闭包对未知任务域无先验；planner 会以 NO_FEASIBLE_PLAN 诚实终止（比空转好，但不会变出知识） | failure_analysis.md |
| 12 | episodic 自动晋升零调用（mark_accessed）、前瞻记忆 NOT_IMPLEMENTED、100 周期巩固未触发 | 死路径 | **未解决**：独立于本轮范围 | docs/COGNITIVE_REPORT.md 死路径节 |
| 13 | sandbox_lab.py 拆仓缺失（历史战役脚本 import 不可满足） | 可复现性 | **原判断有误，2026-10-12 复核更正**：`FAS-Companion/scripts/sandbox_lab.py` 存在且自带双仓 bootstrap——从陪伴仓侧运行历史脚本可复现；"缺失"仅指认知仓内。goal_planner 当时自写的 sandbox_bridge 属重复建设（无害），保留不再依赖 | 实测 find + 文件头 |

## 本轮继续项：#3/#4/#5 的共同根因（序列化/呈现层）

选择理由：FINAL_DIAGNOSIS 元结论中该环节被三个独立实验指认为 PRIMARY，
且本仓可直接复现数据集（cross_episode_recomb 的 6 问题/3 图/审计产物齐备，
LLM 决策头可用）。新审计发现：**G3 事件节点不携带动作属性**——即使呈现层
完美，图上也恢复不出"放入/位于"。最小修复 = 表示补全（事件节点补同源
action 属性，动作词来自经历记录，与 G2 直连边同源，非注入答案）+
叙事序列化（事件→"主-动作-客"句 + 时序 + 失败标记规则预留）。
对照：G3-ids（现状复刻）/ G3-narrative / B2-flat（原始胜者参照）。
