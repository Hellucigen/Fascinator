# 目标导向路径强化机制 — 架构审计报告（2026-10-09）

> 只读审计。未修改任何生产代码、实验结果、预注册文件或历史审计记录。
> 所有行号以当前 main（de6e8bd 后工作树）为准。
> 配套文档：`experiments/goal_path_bias/DESIGN.md`（最小机制设计，待确认）、
> `experiments/goal_path_bias/TEST_PLAN.md`、`experiments/goal_path_bias/PREREGISTRATION_DRAFT.md`。

---

## 0. 审计对象与一句话结论

**候选机制**：当存在明确当前目标时，优先搜索从当前状态到目标的可行路径，
并提高路径上的关系对工作集构建与扩散激活的影响力。

**审计后的核心事实**：该机制试图解决的问题在仓库中已被逐层定位过，但结论是
——目标数据流是"写而不读"的（且比这更糟：目标节点连 Top-k 的入场券都没有）；
结构知识对 forward 扩散**结构性不可穿越**；而负结果的主发生部位在扩散**下游**
（Top-k 预算截断、序列化/消费者接口、评测器致盲），不在扩散算法本身
（这是所有历史报告的元结论，`research_audit/FINAL_DIAGNOSIS.md` E1）。
仓库中**已经存在**一套目标→路径→注意的雏形（`world_prior.next_step` +
`autonomy.py:1760-1783` 的注意力地板直写），它覆盖了 MC obtain 域，
未覆盖其余一切域，且其效果在闭包任务上被消融矩阵证明"达成层无感"。

---

## A. 当前目标的真实数据流

### A.1 CEN 不是目标的来源

- `cognitive_networks.py:31` `NetworkField`：CEN（中央执行网络）是**连续标量的
  "任务专注组织态"调制场**。类头注释（1-18 行）明说"目标由张力/驱动/任务语境的
  加权和决定"；此处 `self._targets[name]`（69 行）/`target_of()`（84 行）的
  "target" 是场的**趋稳 set-point**，与任务目标无关（双关，极易误读）。
- CEN 的输入规格：`cognitive_field.py:102-131` `DEFAULT_NETWORKS["CEN"]` =
  `base 0.10 + context.task_engaged 0.45 + tension.unfinished_goal 0.25 …`。
  数据流方向是 **目标类张力 → CEN**，CEN 从不写入任何目标。
- CEN 的消费是**调制**：效应表 `cognitive_field.py:156-250`
  （`diffusion.*`、`retrieval.topk_scale`、`behavior.exploration_rate`、
  `action.score_threshold` 等含 `network.CEN` 行）。真实读取者：
  `autonomy.py:2804-2810`（探索率）、`dialogue_decision.py:307-320`（候选收窄）、
  `continuous_cognition.py:493-499`（检索宽度）。
- **注意**：`diffusion_engine.py:156` `self.modulation = None`，注释"app 装配注入"——
  CEN→扩散参数的调制链在**本仓库内无生产者接线**（仓库无 app.py；
  facade/assembly 均不注入 modulation）。仓库内唯一注入者是 `tests/test_cognitive_field.py:324`。

### A.2 真实"当前目标" = self_graph 的一条单边指针

| 操作 | 位置 | 语义 |
|---|---|---|
| 写 | `self_graph.py:395` `set_current_goal` | `Self-[当前目标]->目标:X`，先 `remove_edges` 再 `add_edge(weight=0.9)`（单指针 in-place 换边，注释 390-393） |
| 读 | `self_graph.py:417` `current_goal` | 扫边返回 `{id, desc, source, state}`；**无则 `{}`** |
| 清除 | `self_graph.py:429` `clear_current_goal` | 摘边、节点写终态"已完成/已结束"，节点不删 |

**关键缺陷（本次审计新确认）**：`set_current_goal` **全程不写 `node.activation`**。
`action_system.py:1186` 的旁路 `engine.mark_active([goal_id])` 依赖
`mark_active` 的入集条件 `activation >= eps`（`diffusion_engine.py:405`），
而目标节点激活恒 0 ⇒ **mark_active 为空操作，目标节点从不进入活跃前沿，
也就从不出现在 `get_topk` / `active_snapshot` 里**。
"写而不读"（docs/COGNITIVE_MODULE_STATUS.md:86，v6 结论）在扩散层面还要更字面：
不仅没有读取者，连可见性都不存在。

### A.3 写入者 / 读取者清单（仓库内）

写入者：
- `action_system.py:1170` `ActionManager.set_goal_context` — 唯一生产封装；
  **仓库内调用者只有** `tests/test_current_goal.py:64,80,94` 与
  `experiments/capability_gap_v2/run_f_selfmodel.py:57`；真实调用点在仓库外 app.py。
- 清除：`_end_goal_context`（1192）、`_tick` 队列排空自动 achieved（378-380）、`clear_goals`（1212）。

读取者：
- `autonomy.py:1620-1638` `_obtain_goals` — **全仓唯一行为消费者**：
  仅当 `config self_model.goal_attention=True`（`config.py` 的 self_model 段
  **无此键，默认关**；autonomy.py:1616 注释自证"默认 False=生产行为零变化"）；
  且只做 `物品:X` 子串匹配派生 obtain 目标（v7 修复，首个行为差分 0/5→5/5，
  docs/COGNITIVE_REPORT.md "self-model" 条）。
- `continuous_cognition.py:463-479` `_world_signals` — 读 **goal 节点集合的激活**
  （不看指针边！`type in ("goal","reply_goal")` 的 `max(act)/3`），
  作意图亲和度信号（`continuous_cognition.py:62-65`）。由于 A.2 缺陷，
  `目标:X` 节点激活≈0 ⇒ 该信号在生产中接近恒零。
- `self_model.py:329-343` `get_goals` → `get_self_model_summary`（self_graph.py:885）
  — 读**长期目标边**（非指针），给外部 API；仓库内零调用者。
- `cognition_modes.py:281-282` `attention_context` — 读 goal 节点集合；仓库内仅测试调用。

僵尸/无读者：`self_graph.reinforce_goal`（449）零调用；
`SelfGraphManager.set_goal`（self_model.py:345）仓库内零调用；
`ActionManager.queue_goal`（1203）仅测试；`set_goal_context` 生产调用在仓库外。
`set_goal_context` docstring 声称"检测器/触发器与认知上下文都可读它"——
`cognitive_triggers.py`/`dialogue_signals.py`/`conversation_channel.py`/
`modulation.py`/`tension_field.py` 全文 grep **无任何 current goal 引用**，
文档声明与代码不符。

### A.4 目标与扩散/工作集的关系

- `diffusion_engine.py:114`（activation source 登记表注释）：
  `goal / emotion  目标与情绪注入（预留，当前未接线）`。
  全文 grep：扩散引擎**没有任何**读 goal/current_goal 的代码路径。
- 目标影响工作集的唯一既有旁路（均绕过"目标语义"、只是普通激活）：
  1. `set_goal_context` 的 mark_active（A.2：实际空转）；
  2. `autonomy.py:1511-1523` 探索缺口目标：`activation = 0.9` 地板直写 + mark_active；
  3. `autonomy.py:1760-1769` §9 目标反向驱动注意（见 C.4）。

### A.5 无目标 / 衰减 / 多目标

- 无目标：`current_goal` 返回 `{}`；消费者空跳过（autonomy.py:1623-1625、
  action_system.py:1176；test_current_goal.py:93-96 验证降级）。
- 衰减：**指针本身无 TTL、无衰减**——只有显式清除。ActionManager 停 tick 则指针永挂。
  衰减逻辑在 autonomy 层的另一套 `_goals` 清单：
  `GOAL_DEMOTE_AFTER_S=600 / GOAL_STALE_S=1800 / USER_GRACE=900`（autonomy.py:1176-1178）。
- 多目标：结构上强制单指针（换边即覆盖）。注意存在**三套同名不同义的 goal**：
  ① self_graph 指针（任务级"为什么"）；② autonomy `_goals` 执行清单（≤20 条，
  候选透传 motivation="user_goal"，1309-1338）；③ `reply_goal` 表达目标
  （continuous_cognition.py:715-752）。`action_intents.py:37` 的 `params["goal"]`
  是 MC explore_area 区域别名（诱饵）。

### A.6 生产装配形态

`fas/core/assembly.py:20-60` `build_cognitive_core` 只新建
KnowledgeGraph/DiffusionEngine/EpisodicBuffer；`action_manager`、`autonomy`、
`drive_evaluator`、`cc` 等 8 个附件全部从外部 `attachments` 取、**默认 None**。
`fas/core/facade.py` 的 perceive/decide/snapshot/propose_action/tick **零 goal 读写**；
`fas/companion/pipeline.py:20-63` 四步骨架全程零 goal。
⇒ 独立装配形态下目标系统整体缺席；完整链路依赖仓库外 app.py。

---

## B. 图谱路径可达性与语义

### B.1 schema

- `graph_model.py`：Node（189-276，`weight/activation/graph_space/label/extra_attrs`）；
  Edge（282-337：`src, dst, relation, weight(默认0.5, 夹[-2,2]), activation,
  relation_category`）。**边没有 directed 字段**——方向=src→dst 的顺序本身；
  per-relation 传播方向存在 config 本体（不在边上）。
- 方向规则：`config.py:318-327` `relation_propagation` 除 emotional 外**全部 forward**，
  注释（317 行）"不知道方向 → forward，绝不默认双向"；
  `config.py:502-514` `relation_direction` 仅 8 个对称词双向
  （相关/同一/认识/靠近/关于/涉及/参与/交互）。归一漏斗 `graph_schema.py`
  （`normalize_relation`:46 表外兜底为"关联"、`direction_for`:82、
  `global_direction_override`:95）。
- 生产图 = `data/runtime_graph.json`（gitignore，工作副本中不存在）；
  可核查快照：`FAS_Research_Experiments/baselines/run_20260928_113149/full_graph.json`
  （234 节点/269 边）。

### B.2 方向与可达性的硬事实（引原始诊断，非转述）

- `experiments/relation_direction_campaign/relation_direction_audit.json`：
  配方五关系（产生/属于/掉落/需要/需要工具）`target_sink_fraction` 全部 **1.0**，
  `global_forward_2hop_max: 0`。
- `RELATION_DIRECTION_EXPERIMENT.md:29,129-130`：
  "全部 5 种关系的 target 都是汇点；任何节点 2 步 forward 新可达 = 0。
  配方知识结构是深度 1 的星形森林"；"多输入收敛失败的根本原因是
  **关系方向语义使配方结构对 forward 扩散不可穿越**"（假设 B 成立、假设 A 排除）。
- `config.py:500` 注释实测：**全图 48% 节点是纯汇点**；
  hub 反例：`Haru` 入度 108（docs/kg_status_report_20260919.md:94-107）。
- `experiments/mechanism_campaign/MECHANISM_EXPERIMENT_REPORT.md:35-36,63`：
  "物品:* 类节点 13/13 全部是汇点"；
  "符号规划路径与激活动力学路径是彼此分离的两套机制"。

### B.3 承载状态转换的边 vs 纯语义边

**可执行语义边**（有真实域，全部由代码写入并带 provenance）：
- MC 配方层 `world_prior.py`：`配方-[需要(count)]->物品`（273-275）、
  `配方-[产生]->物品`（263）、`方块-[掉落]->物品`（307）、
  `方块-[需要工具]->工具`（315）；来源=运行时 minecraft-data 桥查证，
  "不把攻略当事实"（头注释 8-10）。
- `mc_knowledge.py`：`属于→可采资源`（85）、`造成/威胁` 后果链（102-103）等。
- 能力层 `capability_graph.py`：`概念-[需要]->能力`（133-147）、
  `能力-[实现于]->载体`（88-95）、`状态-[诱发]->概念`（148-167）、
  `条件-[抑制]->能力`（171-176）。
- 行动结果 `action_system.py:1041,1062-1121`：`-[结果]->行动结果:{...}`
  边权 = 极性（失败 **-0.8** / 成功 +0.5~0.9）——**失败证据的可信度通道已存在**。
- 状态层 `minecraft/perception.py`：`Haru-[当前状态]->当前Minecraft状态-[状态项]->槽位`。

**纯语义关联边**：`关联/关于/涉及/参与/表达方式/名字叫/喜欢/感受/记得/发生时间`
（生产图 Top 分布：表达方式 70、属于 66；快照实测）。占多数，承载回忆扩散，
**不承载状态转换**。

### B.4 既有路径搜索基础设施

- 无 networkx（requirements.txt 仅 numpy+jieba）；`KnowledgeGraph` 无 path API，
  只有 `get_out_edges/get_in_edges`（graph_model.py:618-624）。
- **`world_prior.next_step`（678-881）：生产已接线的符号规划器**——
  从目标物品**沿入边反向爬链**（利用汇点的入边，对扩散 forward 语义是"死边"，
  对规划器是活边），≤14 跳，返回 `{action: done|craft|smelt|gather|explore, chain}`，
  带背包感知代价 `_chain_cost`（577-663）、证据分级 `_evidence_rank`、环罚。
  调用者：`autonomy.py:1750/1908/1944`（生产）；闭包重建 `autonomy.py:1697`（10 分钟/次）。
- 有向 BFS 工具：`paper_audit/relation_direction_audit.py:18-35` `forward_bfs_levels`；
  双向有界 BFS：`graph_integrity_audit.py:151-160`（注意其 BFS 忽略方向，
  度量结构发散 ≠ 语义可达，不可混用）。

### B.5 裁决

当前图谱**只在 MC 物品/配方域**支持"状态→目标"的可执行路径搜索，且靠的是
专用反向爬链器，不是通用图搜索。目标-材料结构对扩散 forward 遍历**零可达**。
自标进度、目标→子目标层（self_graph）无操作算子语义。
对话/经历域的"路径"只能是语义关联，**不得伪装为可执行路径**。

---

## C. 扩散与工作集（Top-k）完整流程

### C.1 激活初始化 — `activate_from_inputs`（diffusion_engine.py:684-934）

- 种子强度：相似度在 `[floor 0.5, 1]` 线性映射 × 量程（753-760）；
  无相似度（LLM 抽取实体）= `input_default_bonus 0.5 × a_max`（757）；
  × `_forget_factor`（久未访问衰减，只降唤起强度不改权重，761-764）；
  cap `activation_max=5.0`；登记 `_sources`（来源免扣发射，776）。
- 出入边同时 +`max(0.1, 0.5×sim)` 边激活，cap 到 r_cap（817-836）。
- 锁介入：blocking 节点不给种子（736-739）。

### C.2 传播 — `diffuse_step`（940-1200）

- 有效边权 `w̃ = w + min(r, r_cap=1.0)` **加性、有界、永不回写静态 w**（360-368）。
- 遍历活跃前沿（稀疏域），方向判定 `_edge_direction`（370-386）：
  正向走全部出边；反向只沿 8 个对称关系入边回溯、强度 ×0.5（1078）。
- 贡献 `= a(u)·w̃·β·gain / Σw̃₊`（1045），负权重发抑制、不进分母（L1-DFU-01 修复，
  1026-1035）；发射预算 `= a × ratio(0.5，活动语境 +0.15) × param_gain`
  （`_emission_budget` 1276-1286），超预算整体缩放（1097-1104）；
  **发射即转移**（发出量从自身扣除，`emission_transfer=1.0`；来源节点免扣，
  1109-1126）；fire-once（1129，一轮至多发射一次）；每步衰减（diffuse_round 1345-1350）。

### C.3 Top-k — `get_topk`（526-571）

- 候选域 = 活跃前沿（非全图！前沿外激活已吸附 0）；
- 排序键 `(activation 降序, 点亮序 新者胜, -入图序)`（545-551）；
- non_blocking 锁过滤输出（543-544）；边=top 节点出入边按 `_seq` 排。
- 生产消费者：`fas/core/facade.py:103`（k=20）、`dialogue_decision.py:189`（k=15）、
  `:376`（k=10）、`continuous_cognition.py:397`（**k=8**，表达上下文）、
  `:500`（k=width）、`cognition_modes.py:261`；实验消费者
  `experiments/cross_episode_recomb/run_llm.py:72-80`（k=8，节点 id 直接序列化）。
- **注意**：可达 ≠ 可见。节点在可达集合内但激活低于前沿 eps 或排在 8 名之外，
  对决策头不存在（persistent_state_controls_revision 预检实测：失败证据节点
  按权重排序排第 43，8 槽截断 → 0-run 停止）。

### C.4 生产中的"目标路径偏置"雏形（先例，设计必须与之对齐）

`autonomy.py:1760-1783`（§9 目标反向驱动注意）：
1. 目标物品节点 `activation = 0.9 地板直写 + touch`（1762-1769）；
2. `mark_active([物品:target] + 物品:chain[:4])`（1775-1783）——注意 chain 节点
   **只有已有激活 ≥ eps 才真正入前沿**（mark_active 语义），否则是空转；
3. 路径本身来自 `wp.next_step`（符号规划），**不是图搜索从激活里发现**。
即："目标→路径→激活直写→工作集"的通路在 MC obtain 域**已部分存在**，
其形态是：符号层找路、动力学层只是把终点抬到地板值。

### C.5 机制级风险点（路径强化若介入会碰到什么）

- 直接改边 `weight` = 违反设计原则 4（静态本体 vs 运行时增量分离，22-23 行）；
  改 `edge.activation` 会同时改**传播增益**和 Hebbian 记录（1050-1053）——副作用面大。
- 直写 `node.activation`+`mark_active`（autonomy §9 式）是最小侵入通道：不动边、
  随回合衰减自然清除、可用现有公开接口实现。
- 零和预算：k=8 内路径节点多进一个，就有别的节点（可能是失败证据，
  极性 -0.8 边挂在事件节点上）被挤出——cross_episode_recomb 与
  controls T3 审计都指认了这个挤占方向。
- 无既有机制表达"路径可信度"于激活层：`_evidence_rank`/provenance confidence
  只活在 world_prior/next_step 输出里，不进气氛/激活数学。

---

## D. 现有失败实验的适用范围（对候选机制的含义）

| 实验（真实文件） | 负/零结果 | 失败环节（原文） | 路径强化机制**可能**影响 | **不可能**解决 |
|---|---|---|---|---|
| core_incremental_value（`experiments/core_incremental_value/FINAL_REPORT.md`, analysis.json） | 4/4 主族 ΔJCG<0 反向显著（Holm p=1.51e-9） | 判别信号被**预算归一化与地板干扰吞噬**；非机制不运行 | 无关（比的是扩散 vs flat 检索） | 稀释权衡本质 |
| cross_episode_recomb（FINAL_REPORT.md） | H1/H3/H4/H6 全反向拒绝；G3 0/30 | working-set ✗ + **serialization ✗✗**（"失败层级不是 spreading activation 机制层"） | 提高路径节点 recall@8（机制层） | 事件节点不可读、无叙事——消费者层不修，可见≠可用 |
| 行为汇聚 I（capability_gap_v2 EXPERIMENT_REPORT.md:90-94；architecture_diagnostic/I_FINDINGS.md；Holm p=0.041 基线胜；rep 0/30） | FAS 0-2/10 vs LLM 原始流 10/10 | PRIMARY=**Interface/Representation**（序列化丢时序/关系语义） | 无 | 叙事式图上下文——非激活问题 |
| mechanism_campaign（MECHANISM_EXPERIMENT_REPORT.md） | PROBE FAILED，未跑正式 campaign | 图本体：13/13 汇点、2-hop 可达=0，"问题不在扩散引擎" | **正中靶心**：路径强化=把规划器的路径事实注入激活 | 需先有可搜的路径语义（仅 MC 域满足） |
| 持续意图 C（capability_gap_v2 EXPERIMENT_REPORT.md:29-33；McNemar p=0.0039 正结果） | "persistent intention"归因被零经历对照**证伪** | 重定性为 relational working-set salience（先验闭包+观测触发） | 机制解释可被路径偏置进一步检验 | 归因问题要靠对照，不靠加机制 |
| relation_direction_campaign（RELATION_DIRECTION_EXPERIMENT.md） | F 图 reach2=0；B 投影正向（r=0.886, p=0.002）但双向=实验语义非生产建议 | 方向语义使配方结构不可穿越；**假设 A（引擎问题）排除** | 反向路径搜索正是对"汇点死边"的功能性绕行（world_prior 已示范） | 无条件忽略方向会毁掉方向治理成果（kg_status_report P0） |
| capability_gap_v2 PRECHECK（PRECHECK_REPORT.md + 附录 C/D） | F 消融钩子 no-op；`current_goal()` 0 读取者 | 目标数据流"写而不读"（架构性） | **正中靶心**：本机制将成为 current_goal 的第二个真实读取者 | LLM 决策头对弱信号不敏感 |
| routing v2（core_routing_v2/EXPERIMENT_REPORT.md；HANDOFF_routing_v2_repair.md） | T4 优势 19/20 vs 15/20 p=.046 **未过 Bonferroni（≈1）**，仅方向性；token 2.1-3.7×；T3 更慢 | 任务全可观察+成本；v1 系 0 边 INVALID ASSEMBLY | 分层表现检验（可达性×拓扑）可直接复用其 harness 教训 | 若任务无信息不对称，任何可见性提升都不转化为成功率 |
| ablation matrix（FAS_Research_Experiments/ablation/matrix_summary.json） | 除 −GoalFormation 全失败外**全部零差分** | 评测致盲：达成层对激活无感（C18 修正后口径） | **警示**：在闭包 MC 任务上做本机制实验，预期得到零差分而非证据 | 必须选达成层对信息可见性敏感的 task |
| diffusion B / B2 / hebbian / longchain（FAS_Research_Experiments/*/failure_analysis.md） | 行为层零差分/天花板；Hebb 亚阈 +0.074；L3 0/5（先验缺失） | U1"扩散不驱动行动选择"；消费者可辨阈值 | 路径偏置若走激活直写通道，同样受"亚阈→决策无感"约束：**强度必须可标定** | L3 类失败缺的是任务先验，不是可见性 |

**元结论**（FINAL_DIAGNOSIS.md E1，逐字口径）：没有任何一条负结果归因于
"扩散算法本身坏掉"。负结果集中在四个下游环节：图本体方向语义、
Top-k 预算截断、序列化/consumer 接口、目标数据流消费缺失，外加评测器致盲。
⇒ 候选机制**对症的是环节 1（对结构知识）与环节 4（给目标以读者）**；
对环节 2/3 无效甚至有害；在环节 5 的域上做实验会白做。

---

## E. 根因假设表

| # | 假设 | 支持证据 | 反证/不确定 | 置信 |
|---|---|---|---|---|
| H1 | current_goal 写而不读是真实缺陷，且目标节点对 Top-k 完全不可见（A.2：mark_active 空转） | COGNITIVE_MODULE_STATUS.md:86；PRECHECK 附录 D；本次读码确认 set_current_goal 不写 activation | v7 门控消费者已存在（0/5→5/5），说明"有读者就有差分"可证 | 高 |
| H2 | 配方/结构知识对 forward 扩散零可达，路径信息只存在于符号规划器 | relation_direction_audit.json（sink fraction=1.0、2hop=0）；mechanism_campaign PROBE FAILED；r=0.886 方向对照显著 | 无已知反证 | 高 |
| H3 | 把路径节点注入激活（不修序列化）能提高 recall@8，但**不必然**转化为决策改善 | cross_episode_recomb "机制✓工作集✗序列化✗✗"；U1 行为零差分；ablation 致盲 | A10 beacon 域（信息不对称）中可见性→成功率有正证（20/20 vs 0/20） | 中-高 |
| H4 | 挤占效应真实存在：路径节点进 Top-k 会把失败证据/其他证据挤出（零和 8 槽） | controls T3 ADDENDUM（polarity 挤出、第 43 名截断）；controls_revision 0-run | 尚无直接实验量化"错误路径强化率"——本实验应补 | 中 |
| H5 | 序列化/消费者层是更上游的瓶颈，路径机制不触及 | I_FINDINGS PRIMARY=IF；rep k16/k32/rich 0/30 | 与 H3 互补不冲突 | 高 |
| H6 | 在闭包 MC obtain 任务上测本机制得到不了证据（达成层对激活无感） | ablation matrix 零差分；diffusion B "结构保证的负结果"；next_step 已把答案直接给候选层 | 需选任务使"路径可见性"成为信息瓶颈 | 高 |
| H7 | 激活直写（autonomy §9 式）比改边权是更低风险的偏置通道 | 设计原则 22-23 行；r_cap/Hebbian 副作用面；已有先例代码 | 直写值不随路径质量分级，需自建衰减 | 中 |

---

## F. 对最终三问的当前回答（待实验证伪/证实）

1. **改善了什么**：预期改善的是"目标路径节点的 Top-k 可见性"（机制层），
   决策质量与任务成功率是否跟涨取决于任务是否信息不对称（H3/H6）——
   生产先例 §9 已占掉 MC 域的大部分边际收益。
2. **收益来源**：路径搜索（world_prior 式反向爬链）与激活偏置二者可分消融；
   可执行性检查（白名单关系+状态锚点验证）预计是**避免强化错误路径**的前提
   而非收益来源。
3. **何处无效/更差**：闭包可达任务（零差分）；纯语义关联域（路径不可信）；
   小 k 预算下挤占失败证据（可能净负）；调制链未接线的装配形态（CEN 通道无效）。
