# 预注册草案 — 目标导向路径强化（A/B/C 三条件对照）

状态：**DRAFT——在生成任何实验数据之前，本文件须以 PREREGISTRATION.md 锁定**
（锁定后只许追加 ADDENDUM，不许改写正文；参照 persistent_state_controls 的纪律）。

## 0. 假设

- H1（机制层）：相对 A，B 使"正确路径节点"的 recall@8 提高 ≥ 15pp。
- H2（行为层）：在**信息不对称任务族**（路径信息只存在于图结构、决策头不直接
  获得 next_step 提示）上，B/C 的配对任务成功率高于 A。
- H3（归因分解）：C − B 的差分衡量"可执行性检查"的独立贡献；B − A 衡量纯偏置。
- H4（副作用 guard）：失败证据 recall@8 留存率在 B/C 下相对 A 下降 ≤ 10pp。
- 预期零/负结果域：闭包可达的 MC obtain 任务（审计 H6：达成层对激活无感，
  ablation matrix 先例）——若该族出现零差分，属**预登记的可解释零结果**，
  不追加解释、不换任务重跑。

## 1. 条件

| 条件 | search | bias | 可执行性检查 | 说明 |
|---|---|---|---|---|
| A 原始 FAS | off | off | off | 基线，含现有 mark_active/§9 通道照常（生产原样） |
| B 路径激活偏置 | on | on | off | 白名单关系反向 BFS + 衰减直写（DESIGN §2） |
| C B+可执行性检查 | on | on | on | 路径须落真实状态/背包锚点、provenance 达标才偏置 |

C 在 v1 由白名单+锚点检查实现，**不含新规划器**；next_step 级规划交互列后续实验。
偏置强度三条件共享一套标定（机制层 grid 预先定死 floor_scale/γ 并冻结，行为层不许再调）。

## 2. 任务与图（两个分层族）

**族 M（机制层，无 LLM，确定性）**：固定图集 =
① `FAS_Research_Experiments/baselines/run_20260928_113149/full_graph.json`；
② knowledge_packs/{common,minecraft,computer}；
③ Graph F（生产建图口径 44 节点/53 边，relation_direction_campaign 复刻）；
④ 合成拓扑：深度 1 星形、深度 5 链、3-环、双目标竞争、目标不可达、
语义 fabric 噪声（40% "涉及"共现边）注入版。
每图 × {2, 3, 5, 8} 跳目标距离分层。

**族 L（行为层，LLM 决策头）**：
- L-asym：路径节点初始不在感知回显/候选注入中，只存在于图结构
  （beacon/A10 域先例：信息不对称才测得出可见性→决策的传导）；
  任务=多步 craft/obtain，决策头只见 Working-set（k=8 序列化，节点带 label+关系叙述，
  修复 cross_episode_recomb 指认的序列化不可读问题——**序列化三条件同一模板**）。
- L-distract：同任务 + 干扰经历注入（测挤占与错误路径强化）。
- L-blind（哨兵族，预期零差分）：闭包 MC obtain 复刻 ablation 口径，验证 H6。

## 3. 控制变量

同任务、同初始状态与目标、同图、**配对 seed**（seed 决定点火噪声与呈现序）；
同 LLM 模型版本/温度/提示模板/max_tokens（记录并快照进 run 目录）；
同 k=8 预算、同 token 上限；除 goal_path 开关外 config 逐字节相同。
运行隔离：`experiments/goal_path_bias/campaign_<date>/`，保留逐次日志、
config 快照、图快照；生产代码与正式实验目录零写入（bias 模块只读图+写运行时激活，
落盘由既有 decay/save 通道决定，实验 harness 用内存图）。

## 4. 指标

主指标：
- 族 M：正确路径 recall@8（路径节点中进入 Top-8 的比例）。
- 族 L：任务成功率（配对二值）。

次级（预登记但不作确证声明）：目标推进率（状态锚点向目标变化的步比）、
决策次数、无效动作数、失败证据 recall@8（guard H4）、错误路径强化率
（低 provenance / REJECTED 候选被偏置的比例）、路径搜索耗时、总 token、
分层（拓扑 × 目标距离）表现曲线。

## 5. 统计

- 配对 Wilcoxon signed-rank（族 L 二值结果用 McNemar 精确），双侧；
- 每族报告 Hodges-Lehmann 位移估计 + bootstrap 95% CI；
- 多重比较：族内 Holm（M：1 主假设；L：H2×{L-asym, L-distract}+H3×2 共 6 项，m=6）；
  族间分开裁决，不合并；
- **判定纪律**：不以单一 p 值下结论；H2 成立需同时满足
  (a) Holm 校正后 p<0.05，(b) HL 位移 ≥ 预登记最小效应（+15pp 成功率），
  (c) H4 guard 未破，(d) token/时间开销增长如实呈报并与收益并置。

## 6. 样本量与停止条件

- 族 M：4 类合成拓扑 + 4 真实图 × 10 seed（确定性图部分 seed 仅影响点火序）。
- 族 L：n=20 配对 seed × 3 条件 × 2 主任务族 = 120 runs（功效声明：n=20 对
  中等效应灵敏度有限，与 capability_gap_v2 的 n=10 先例比属加宽；若 discordant<5
  则报"不可判"，不扩样本）。
- 停止：① 族 M 主假设 CI 含 0 → 停在机制层，不跑族 L；
  ② 族 L 跑满计划数即停，不因结果追加 seed；
  ③ H4 破防（失败证据留存下降 >10pp 且 Holm 显著）→ 该条件的"有效"结论
  自动降级为"有副作用的可见性改善"，写入报告标题而非脚注。

## 7. 报告义务

逐字报告：零结果（L-blind 族）、负结果、实现失败（如某拓扑 NO_PATH 率 100%）、
与 H1-H4 相违的结果。最终裁决回答三问（可见性/决策/成功率各归位；
收益来自 search 还是 bias 还是可执行性；无效/劣化边界），格式沿用
persistent_state_controls 的 INTERPRETATION + ADDENDUM 双层。
