# 目标导向路径强化：机制实现与独立对照实验 — 最终报告（2026-10-09）

前置审计：`docs/audits/GOAL_PATH_AUDIT_2026-10-09.md`
预注册：`PREREGISTRATION.md`（数据产生前锁定；变更全部记录于 ADDENDUM-PRE）
生产接线状态：**机制已实现但默认关闭**（`config.goal_path.enabled=False`），
关闭态回归逐位一致（基线 worktree 对照 pytest 100/100 同集通过；
test_current_goal / test_cognitive_loop / test_cognitive_field /
test_activation_recall 独立套件亦全过）。

## 一句话总裁决

**该机制在机制层（节点可见性）有可重复的大效应，但在行为层（决策质量、
任务成功率）零收益且出现方向性负效应；收益归因于激活偏置而非可执行性检查
（后者只贡献"拒绝错误路径"的防护价值）；负效应的机制学根源是
"hop-0 目标节点成为工作集最显著项 + 序列化模板把高激活节点读成行动建议"。
按预注册成功标准判定：机制不达标，不应默认开启。**

---

## 1. 实现与测试

- `goal_path_bias.py`：目标指针读取（`self_graph.current_goal`）→ 白名单
  （产生/需要/掉落/需要工具/属于→可采资源/拥有）反向 BFS（复用
  `world_prior` 读 API）→ 路径质量（落地叶子/边权/provenance 置信）→
  激活直写（floor×γ^hop）+ `mark_active`。不写 edge.weight、
  edge.activation、不注册 activation source；search/bias/可执行性检查三开关
  独立（off+on 非法组合显式报错）。
- `tests/test_goal_path_bias.py` 21 项全绿：无目标零写入、不可达不伪造、
  环有界收敛（CYCLE 如实 unresolved）、语义边不入路径、开关/清除完全回滚、
  偏置期间边三字段逐字节不变、写入数≤预算、失败证据邻接冲突可记录、
  B/C 行为分野、目标已达成 ALREADY_OWNED 零写入。
- Phase-0 只读审计（`path_audit.py` → `artifacts/path_audit_report.json`）：
  生产路径 MC 图 11 个物品 forward-2hop 可达**全部 = 0**（独立复现
  relation_direction_campaign 的硬事实），反向白名单搜索 5 PATH / 6 PARTIAL /
  0 伪造；知识包合并图 0 个可用物品节点——非 MC 域无路径可搜。
  **实现失败披露**：拆仓缺 `sandbox_lab.py`（历史战役脚本 import 均不可满足），
  实验以自实现确定性桥（`sandbox_bridge.py`）替代；生产闭包路径未改动。

## 2. 族 M：机制层（零 LLM，7 图 × 3 条件 × 10 配对 seed）

主指标 recall@8（`campaign_m/run_20261009_122129/mechanism_report.json`），
Wilcoxon 符号秩精确置换，族内 Holm（m=10）：

| 图 | B−A | C−A | 备注 |
|---|---|---|---|
| star1 | 0→1.000，Holm p=0.0195 | 0→1.000，p=0.0195 | HL+1.0，CI[1,1] |
| chain5 | 0→0.500，p=0.0195 | 0→0（p=1） | C 拒 10 跳链（max_hops=8 截断） |
| distractor | 0.071→0.143，p=0.0195 | 0.071→0.071（p=1） | γ^hop 衰减输给噪声 |
| mc_wooden_pickaxe | 0→0.750，p=0.0195 | 0→0.750，p=0.0195 | 可完整落地→C 生效 |
| mc_iron_ingot | 0→0.375，p=0.0195 | 0→0（p=1） | 同 chain5 |
| ring | truth 空（n/a） | — | **B 偏置死环 40 节点·10seed（4/seed）；C=0** |
| unreachable | — | — | B/C 均 NO_PATH 零写入，不伪造 |

机制层分层发现（预登记）：
- **可见性≠预算**：hop≥5 的节点偏置值 0.9×0.6^5≈0.07，被 0.3–2.2 均匀噪声
  淹没——深度链的实际可见回收只有链前段。
- **C 的代价面**：require_state_anchor 对"被 max_hops 截断的真路径"也拒绝
  偏置（chain5/mc_iron C−A=0）。校准缺口：world_prior 自身爬链用
  CHAIN_MAX_DEPTH=14，而本模块 DEFAULT max_hops=8 对齐了闭包写入深度——
  属可修复的参数错误（不改机制结构），如实标记。
- **副作用①（挤占失败证据）**：distractor 图中失败证据节点
  `行动结果:挖oak_log:failed` 的前沿内排名 A=18 → B=26（10 seed 全部一致），
  C=18（拒绝偏置故不挤占）。Top-k 预算零和实锤。
- **副作用②（间接 Hebbian 漂移）**：模块本身不动边（单测 1.6 + 实验内
  in-run diff），但偏置抬升路径节点共同激活后，生产 Hebbian 白名单
  （semantic/emotional）边权被合法推高：mean_edges A=0.0 / B=1.14 / C=0.29，
  幅度 ~4e-5/run（在 max_gain 护栏内）。非缺陷，是必须报告的间接效应。
- 搜索耗时中位 <0.3ms/图——计算开销不是瓶颈。

**族 M 判定：H1 SUPPORTED（可见性）、H3-防护 SUPPORTED（C 拒死路）、
H4-guard 触发（B 挤占失败证据，C 不挤占）。进入行为层的预注册门槛满足。**

## 3. 族 L：行为层（LLM 决策头，信息不对称任务，90 决策/轮）

决策头：MiMo `mimo-v2.6-flash`，temperature=0。评估器非 LLM
（`wp.next_step` 规范答案 + token/动词匹配）。世界为**全虚构材料链**
（lumen_sand/hum_root/ground_lumen/aether_lens/resonance_core + 低置信(0.2)
环依赖陷阱支路 void_glass）+ 常识一致哨兵层（oak_planks）。
**v1 记录保留为 INVALID**（`campaign_l/run_20261009_122523/INVALID_HARNESS.md`：
max_tokens=120 被推理消耗吃光，A 空回答 25/30——装配缺陷，非机制结果）。
v2 正式轮（`campaign_l/run_20261009_123231/`，max_tokens=400；注意该轮
artifact 的 head 字段误记 120，代码实际生效 400，已修，如实披露）：

| 目标层 | A | B | C | McNemar B/C vs A |
|---|---|---|---|---|
| aether_lens（虚构，深链） | 0/10 | 0/10 | 0/10 | 无 discordant，p=1 |
| resonance_core（虚构，AND 双支） | 0/10 | 0/10 | 0/10 | 同上 |
| oak_planks（常识一致哨兵） | **8/10** | **1/10** | 1/10 | 精确 p=0.039，**Holm p=0.235**（方向性负，未过确证门槛） |

关键遥测（如实呈报，含不利解读）：
- **中介分层**：规范答案 token 在 B/C 工作集可见的次数=**1/30**（即族 M
  发现的深度衰减+噪声压制在行为层复现）。唯一可见 run（哨兵层 seed2）
  答对——方向与 H2 一致但 n=1 不构成证据。
- **"以目标当下一步"**：A 1/30，**B 23/30，C 22/30**。hop-0 偏置把
  `物品:<目标>` 推到工作集首位，序列化模板（按激活降序的节点+边）使决策头
  把"最显著的节点"读成"该做的动作"→ 直接答 `craft <目标>`。
  **这是路径强化自身制造的新决策缺陷**，不是原有缺陷。
- 陷阱支路（低置信环边）被决策头采纳：**0/90**——错误路径强化在行为层
  未被兑现为错误行动（主要因为它同样进不了 top-8）。
- 成本：prompt tokens A 454.7 → B/C 470.5（+3.5%）；延迟波动由后端主导
  （A 11.3s vs B 4.1s 不可比），token 开销结论：**新增成本小，
  但收益也为零，净值不达标**。
- A 层残余缺陷披露：v2 中 A 空回答仍 6/30、A 平均 completion 246.8
  （推理模型吃预算），意味着 A 的虚构层 0/20 含装配噪声——但 B/C 同为 0/20，
  方向性负只出现在无歧义的哨兵层，判定不受该噪声翻转。

## 4. 三个最终问题的回答

**Q1 究竟改善了什么？** 只改善了节点可见性（机制层，大且可重复：
star/mc 图 recall@8 +0.75~1.0，Holm p=0.0195）。决策质量未改善；
最终成功率在信息不对称层是彻底零结果，在常识层是方向性受损
（8→1，Holm 0.235）。"更多目标相关节点进 Top-k"没有转化为任何下游收益——
这正是预注册警告的失败模式，本实验把它实证了。

**Q2 收益来自哪里？** 可见性收益完全来自**激活偏置**（B−A 全显著）；
路径搜索本身（search-only 消融）零副作用零可见性贡献；可执行性检查
（C）不贡献任何额外收益，它的价值是**纯防护性的**：死环被偏置节点数
B=40 → C=0、失败证据排名 B=26 → C=18、截断链不被伪造为完整路径。
行为层没有任何一层贡献正收益。

**Q3 哪些条件下无效/更差？**
- 无效：目标深度 > max_hops×γ 衰减可覆盖范围（chain5、mc_iron、L 虚构层
  全部）；背包噪声点火强度 ≥ floor×γ^hop 时（distractor 仅 +0.07）；
  非 MC 域（知识包 0 可搜物品，机制自动 NO_PATH——按设计不伪造）。
- 更差：目标节点本身被 hop-0 floor 推到工作集首位 + 决策模板按显著性
  解读行动 → "以目标当下一步"（B/C 23/22 vs A 1）；Top-k 零和下失败证据
  被挤出（18→26）。两者都要求下一版设计（若继续）：不偏置目标节点本身、
  序列化时显式区分"目标项"与"路径候选项"、深度预算对齐 CHAIN_MAX_DEPTH。

## 5. 与历史负结果谱系的关系

本实验把审计报告 §D 的 H3/H5/H6 从"推断"变为"实测"：
可见性→决策的传导缺口不在扩散（族 M 机制层完全健康），在
**Top-k 呈现语义与消费者解释**——与 cross_episode_recomb 的
"失败层级=serialization/consumer"、行为汇聚 I 的 PRIMARY=IF、
ablation 矩阵的达成层致盲完全同构，且新增了可操作的负机制
（goal-as-salient-step 混淆）。按 `research_audit` 纪律，这是机制候选的
**FALSIFIED-at-behavior-level** 结果，如实归档。

## 6. 遗留与后续（不混入本版）

1. C 条件深度校准（max_hops 8→14，对齐 CHAIN_MAX_DEPTH）后族 M 的
   chain5/mc_iron 是否翻正——参数级后续实验。
2. 序列化修复（目标项与下一步候选项分栏）后再测行为层——属消费者层
   变更，非本机制责任范围，另案预注册。
3. 多步沙箱任务需要父仓 app.py 装配，本拆仓不可离线复现（ADDENDUM-PRE §3）。
4. `sandbox_lab.py` 拆仓缺失需上游决定（补齐或归档历史脚本 import 路径）。

## 7. 数据与记录位置

- 族 M 正式：`campaign_m/run_20261009_122129/`（raw_runs.jsonl、
  mechanism_report.json）。历史迭代保留：121925=Holm 初值 bug 版 +
  跨-run 边检查误判版；122020=Holm 修正版（仍含误判检查）；122122=崩溃
  空目录（import 期建目录后 NameError）。三者不入结论，recall 数字与正式版
  一致。
- 族 L：v1 `campaign_l/run_20261009_122523/`（INVALID_HARNESS.md 标注），
  v2 正式 `campaign_l/run_20261009_123231/`（raw_llm.jsonl 90 行全保留、
  llm_stats.json）。
- Phase-0：`artifacts/path_audit_report.json`。
- 生产 diff：`goal_path_bias.py`（新）、`config.py`（+goal_path 节，全关）、
  `autonomy.py:902-908`（+7 行默认关接线）、`tests/test_goal_path_bias.py`（新）。
  未修改 diffusion_engine/self_graph/world_prior/graph_model；
  未触碰任何历史实验目录、预注册与审计文件。
