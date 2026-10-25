# paper_revision_report — 路由 campaign 后的论文修订

- 日期：2026-09-29
- 依据：experiments/core_routing/（520 task-runs，20 配对种子，8 条件，4 任务；experiment_audit.md）
- 修订范围：main.tex / main_zh.tex / CLAIM_EVIDENCE_MATRIX.md / README

## 1. 修改了哪些章节

| 章节 | 修改 |
|---|---|
| Abstract | 增补路由实验结果段：五条件配对检验、无优势、1.4–2× token、信息不对称边界条件 |
| Introduction 贡献 4 | 扩写：加入"自身假设的五条件配对否定检验"作为边界刻画的一部分 |
| §4 方法 | 新增 §4.5 LLM decision-head protocol（协议、五条件、消融、20 配对种子、两次主跑前任务设计修正、一次 harness 缺陷修复与全量重跑） |
| §10（新） | 新增 "Explicit Resource Routing vs. LLM Baselines" 整章：假设否定、数字、三条机制性解释、能/不能说明什么；含 2 张新图 |
| §11 讨论 | 新增"What the routing experiment teaches"段：架构价值边界（基底而非上下文选择引擎）+ 缺失实验成分（信息不对称任务） |
| §12 局限 | 增补 (9)(10)：任务完全可观察；决策头协议不含 FAS 控制执行 |
| Table 2 claim 表 | 新增 U7 行：FAS 路由优于 LLM 记忆/检索 = UNSUPPORTED |

## 2. 删除了哪些过时 claim
无删除（本轮为增补）。但以下表述被 U7 覆盖：任何"FAS 的显式路由/激活选择改善 LLM 信息利用"的暗示——摘要与贡献已明确写出否定结果。

## 3. 新增哪些实验
core_routing campaign（新族）：条件 A/B/C/D/E + 消融 D-noact/D-nodemand/D-flat；任务 T1 复用 / T2 干扰抑制 / T3 环境变化重路由 / T4 竞争目标；520 task-runs、约 5.6k 次 LLM 调用、逐决策 JSON 轨迹（含选中上下文与 token）。

## 4. 哪些旧实验仍然有效
前述全部（A2/B2/C-emo/D-CI/F/I/G/H/J/K）不受影响——本轮只新增族，未触碰旧 run 与旧结论。

## 5. 哪些结果不支持原假设
- 主假设 H1（FAS routing > history/retrieval-only routing）：**被否定**。
- 全部主指标无优势；token 成本 1.4–2×；T3 重路由显著慢于 history（p=0.039）；消融间无系统差分。
- 反事实 random_ctx 在多数维度持平或优于 FAS——短经历流中随机≈相关。

## 6. 当前论文的核心 claim
不变：支架式接地知识获取 + 持久 + 再激活 + 账本/事件框架两条行为通道 + 标量调制；**新增一条否定性边界结论**：在决策时完全可观察的任务中，FAS 的显式资源路由未提供相对历史/检索/随机/无上下文的可测信息利用优势，且成本更高。

## 7. 当前论文不能声称什么
- 不能声称"FAS 改善 LLM 的信息利用/上下文选择"（U7 否定）。
- 不能声称"FAS 比 LLM+历史/检索更强"。
- 不能把 activation/demand/routing 列为**经实验验证**的 LLM 侧增益机制（只能列为已实现、在可观察状态任务中被否定的机制）。

## 8. Future Work（据本轮结果新增）
信息不对称任务族设计（部分可观察状态、延迟后果、跨会话依赖）；大存储/高干扰下的路由价值检验；FAS 焦点集纯度（实体与动作/结果节点分离）；路由在**无 LLM 执行循环**（FAS 自主行动）中的价值，区别于 LLM 决策头协议。

## 9. Limitations（新增）
(9) 路由任务完全可观察，否定结论以此为条件；(10) 决策头协议不含 FAS 控制执行，整机 LLM-in-the-loop 评估未做；harness 感知模拟与生产感知有差距（C34 已记录）。

## 10. 与相关工作的区别（据本轮更新）
论文定位从"显式图谱优于 LLM 记忆"进一步收窄为"统一图谱基底上的**接地知识获取与持久**"；与记忆管理/RAG 类工作（Memory Probe、MRAgent、PRISM、Cognitive Workspace、active memory management、graph-based active reconstruction 等）的关系明确为：本文不主张"首次提出动态记忆选择"，并在 §10 如实报告本实现在可观察状态任务上未显示此类选择优势。
