# 预注册（锁定版，2026-10-09）— 目标导向路径强化 A/B/C 对照

本文件在行为层任何 LLM 数据产生**之前**锁定；与 PREREGISTRATION_DRAFT.md 的差异
全部发生在数据产生之前，逐条见 §ADDENDUM-PRE（追加不改写）。

## 假设（不变）
- H1 机制层：B 提高正确路径 recall@8。
- H2 行为层：在信息不对称任务上 B/C 提高成功率（相对 A）。
- H3 归因：C−B 度量可执行性检查的独立贡献（拒绝死路/环/不可落地分支）。
- H4 guard：失败证据可见性不被显著挤占。

## 族 M（机制层，无 LLM）— 实际执行口径
- 图：star1 / chain5 / ring / unreachable / distractor(40% 共现 fabric+失败证据
  边) / mc_production(wooden_pickaxe PATH, iron_ingot PARTIAL) ×
  A/B/C × 10 配对 seed（点火抖动由 seed 决定，三条件共享）。
- 主指标 recall@8（真值=图构造期已知最小推导 / mc 深搜推导）；
  次指标：错误偏置（被偏置 ∉ 真值）、失败证据 rank、环/死路被偏置节点数、
  搜索耗时、Hebbian 边权漂移（区分模块泄漏 vs 生产通道间接效应）。
- 统计：配对 sign-rank 精确置换（2^n）+ Hodges-Lehmann + bootstrap 95%CI +
  族内 Holm（m=10）。停止判据：全图 recall B−A CI 含 0 → 不进行为层。

## 族 L（行为层）— 实际执行口径
- 决策头：openai 客户端 → MiMo backend（父仓 llm_provider.MiMoBackend，
  模型 mimo-v2.6-flash，temperature=0，max_tokens=120，重试 3）。
- 任务：单次决策 QA（每 run 1 次调用）：目标"获得 X"，背包空，
  唯一可见信息 = 工作集 top-8（节点+激活+关系边，模板三条件一致）。
- 世界：**全虚构材料链**（lumen_sand/hum_root/ground_lumen/aether_lens/
  resonance_core；含低置信(0.2)/环(需自身)陷阱支路 void_glass 链；
  oak_planks 常识一致哨兵层）。虚构化原因：v1 沙箱曾用 vanilla-MC 命名，
  预检发现决策头参数化常识可绕过工作集答对第一步（信息不对称被污染）——
  该污染在**任何 LLM 数据产生之前**被离线预检发现并更换世界（见 ADDENDUM-PRE）。
- 规范答案：wp.next_step（生产规划器，独立于被测机制），评估器为
  字符串 token+动词匹配，非 LLM。
- 条件：A / B（bias，无前置检查）/ C（bias+require_state_anchor）；
  配对 seed（点火噪声同序列）；n=10 seed × 3 目标 × 3 条件 = 90 决策。
- 主指标：成功率（canonical token+动作正确）。
- 次指标：正确 token 是否在工作集（中介分层：success | visible / hidden）、
  prompt/completion tokens、延迟、陷阱分支被采纳次数。
- 统计：McNemar 精确（配对二值，双侧）+ Holm（m=6：{B,C}×3 目标）；
  判定纪律：单一 p 值不足以宣布有效；哨兵层（oak_planks）预期零差分，
  若该层出现显著差分视为设计泄漏信号（阴性对照破功），全族结论降级复核。
- 停止：跑满 90 即停，不追加 seed；LLM 基础设施失败按 run 记录 error 重跑
  上限 1 次（capability_gap §16 口径，原始记录保留）。

## 报告义务（不变）
零结果、负结果、实现失败逐条如实；三问裁决（可见性/决策/成功率；
归因 search vs bias vs 可执行性；无效/劣化边界）。

## ADDENDUM-PRE（数据产生前的设计变更，不覆盖正文）
1. C 条件实现为"require_state_anchor"（全叶落 拥有/可采资源 才偏置），
   未引入新规划器——与草案 §1 条件表一致。
2. 族 M 的"多目标竞争"层未实现为独立图（distractor 含双配方汇聚）；
   分层曲线以 4 个合成拓扑 + 2 个 mc 目标替代，拓扑覆盖 星形/链/环/不可达/
   干扰fabric，与草案 §2 族 M 一致。
3. 族 L 从"多步交互任务"简化为"单次决策 QA"：多步沙箱需要装配生产
   ActionManager/桥（本仓库拆仓后主装配在仓库外 app.py，不可离线复现），
   单步决策保留"工作集→决策"的因果链且把成本约束在 90 次调用内。
   该简化限制了结论外推到多步序列——写入报告限制段。
4. vanilla-MC 命名世界在 LLM 数据产生前被更换为虚构世界（预检发现污染，
   无任何基于 v1 世界的 LLM 记录）。
