# cross_episode_recomb 复验 — Phase-1 审计报告（2026-10-09）

只读。为预注册 `cross_episode_recomb_memrep_replication_v1` 提供事实基础。
历史实验的代码/数据/结果/报告零改动。

## 1. 原始实验解剖（真实代码位置）

**任务与数据**：`experiments/cross_episode_recomb/`
- 13 条经历（EPISODES，build_dataset.py:26-40，如 E4 苹果-放入->篮子）、
  6 个预注册问题（experiment_config.json questions，含 gold_chain/
  gold_actions/gold_episodes）、三张图（isolated/shared/eventframe，
  graph_*.json 存档可加载）。
- 泄漏/捷径审计产物齐备（leakage_audit.json/shortcut_audit.json）。

**7 条件**（run_llm.py:16-17 CONDS；build_context :40-81）：
- B0-direct：无上下文；B1-history：全部 13 行经历流；
- B2-retrieval：**嵌入**检索 top-6 经历行（EmbeddingProvider，
  embedding_manager.py:61-76，本地 bge-small-zh-v1.5 @ E:/Models
  ——**本机实测可加载**，512 维，无阻塞）；
- FAS-G1/G2/G3：图+`activate_from_inputs(seeds)`+`diffuse_round(max_steps=4)`
  +`get_topk(8)`+**ids 序列化**（"- id" 行 + topk 内部边 ≤10 条，
  run_llm.py:64-81）；
- FAS-G3-nospread：复用机制探针行的 top8（mechanism_results.json）。

**调用配置**：v2.LLMHead（父仓 run_exp_routing_v2.py:70-106），MiMo 后端
temperature=0、max_tokens=300、**每次调用新建 LLMHead**、重试 3。
原始逐 run 记录含 answer/错误/各分项（raw_results.jsonl），可审计。

**评分器**（run_llm.py:83-96 check_answer，确定性字符串匹配）：
- exact_success = 中间实体（chain[1:-1]）全部出现 ∧ 链实体提及≥2；
- partial_success = ≥1 中间实体；path_validity = 提及实体在链上相邻；
- relation_validity = 任一 gold 动作词出现。

**统计口径**（analyze.py）：配对单位=(question,seed)，每条件 30 run；
McNemar 精确（自实现 :22）用于 H1-H6；Wilcoxon（scipy）用于 H5/H6
计分版（exact×2+partial）。原始结果：B2 16/30、B1 14/30、G1/G2 9/30、
G3 0/30、B0 7/30（FINAL_REPORT）。

## 2. 四环节（A 事实在图 / B 检索 / C 序列化 / D 推理）的原始证据定位

- **A**：G2 图含全部 gold 三元组（动作在直连边关系名上）；G3 图
  **不含动作**（事件节点无属性，build_dataset.py:88-96；角色边
  主体/客体/后继 过归一漏斗后引擎内变"关联"，serial_fix 实测）。
- **B（决定性新证据）**：mechanism_results.json 实测——G3 spread 臂
  top8=`['厨房','苹果']`（Q1），**事件节点当年就没进过检索结果**
  （实体种子在 G3 方向语义下不可达事件节点：事件→实体方向、实体是汇点）。
  含事件节点的是 nospread 探针臂。⇒ 原始 G3 0/30 的第一性原因是
  **检索停摆（B 环节）**，序列化问题在 G3 spread 臂上甚至没机会表现；
  "事件稀释"叙事属于 nospread 臂与 G1 臂。
- **C**：ids 序列化对 G2 语义充分（G2 9/30>0 证明边行可读）；对 G3
  不可用（无可读内容）。serial_fix 机制层实测：G3+repfix+叙事序列化
  事实重构 k=16 100%/k=8 61.5%，G2+叙事 69.2%（k=8）。
- **D**：B2 16/30 说明同模型同评分器下，可读上下文可被正确推理；
  下游推理不是主要瓶颈（原报告同结论）。

## 3. serial_fix 覆盖范围确认（不得夸大）

- 机制层：4 条件（G3-ids / G3-narr±repfix / G2-narr）× 2 激活域 × k∈{8,16}，
  **零 LLM**；产出事实重构率分层结论。
- 行为层：**未完成**。54 调用的 run 被用户中止，`campaign_l/` 留有部分
  调用记录——按纪律标记为**废弃预实验数据，不入任何结论**，本次复验
  不复用其中的任何数值。

## 4. MEMREP 实现与接线的真实性核查

- `memrep.py` 提供的事实/事件/实例/序列化均为**工具函数，无生产自动
  行为**；唯一生产接线 action_system._write_action_memory 的槽位补全
  由 `config.memrep.enabled` 门控（默认 False）。
- **关态逐位保持旧路径**：test_memrep.py G1/G3 断言（门关时行动节点
  无新槽位、旧字段逐字段一致）+ 全仓 pytest 100/100 与 HEAD 基线
  worktree 同集通过（本轮复验前已运行）。
- 实验环境接线：本次复验将使用**隔离实验适配层**（独立目录内的
  build/serialize 函数，显式选择新旧路径），不改任何生产默认值。
- 信息完整性差异（必须声明的对照前提）：实验数据集**无真实时间戳与
  来源字段**——新表示的时间信息只能是经历序号（seq），来源只能按
  "系统自身经历=observed" 统一标注。新旧路径在时间/来源维度**信息对等**
  （旧的也没有），不构成不公平优势；对象身份维度 G3 均为共享实体
  （canonical，人工对齐），个体实例化在数据集上无区分符证据，**不启用**
  （启用即伪造身份信息）。

## 5. 差异与风险清单

| 项 | 原实验 | 本次复验 | 定性 |
|---|---|---|---|
| 模型 | MiMo（当时默认） | mimo-v2.6-flash（现默认） | 需声明；三条件同模型则内部比较有效 |
| max_tokens | 300 | **400**（统一） | 有意偏离：goal_path_bias v1 实证 300 会被推理消耗截断致空回答（INVALID_HARNESS 记录）；对所有条件统一 |
| 激活域（G3 臂） | 实体种子（停摆） | 忠实域（复现停摆，作对照锚）+ 情节新近域（R2，事件均匀点火，与问题无关无泄漏） | 设计内对比，非偷换 |
| B2 检索 | 嵌入 top-6 | 同（嵌入本机可用） | 忠实复用 |
| 评分器/提示词 | 原版 | 原版逐字复用（PROMPT 模板同） | 不变 |
| LLMHead 每调用重建 | 是 | 是 | 不变 |

风险：①推理模型对 300 token 的截断风险（已用 400 缓解并声明）；
②R2 域是**实验构造的激活状态**，不代表生产检索已解决——其结果只说明
"检索给定后表示/序列化的贡献"，结论边界必须如此写；③小样本
（30/条件）对 <20pp 效应功效有限（原实验同等规模，沿用并声明探索性）。

## 6. 阻塞项

**无硬阻塞**。嵌入模型本机可用（实测）；父仓 LLMHead 可用（前轮实测）；
历史数据齐备。唯一流程性前提：预注册获批前不发起任何 LLM 调用（本报告
即门槛一交付，随后停止）。
