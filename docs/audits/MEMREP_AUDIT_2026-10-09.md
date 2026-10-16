# 记忆表示重构 — Phase-1 审计报告（2026-10-09）

只读审计。两个并行深查（时间机制全景 / 事件·身份·状态覆盖）+ 此前四轮审计
（GOAL_PATH_AUDIT、PLANNER_AUDIT、FINAL_DIAGNOSIS、kg_status_report）交叉核对。
行号以当前 main 为准。**已明确区分生产代码与实验代码。**

## 1. 图谱底座（现状）

- `graph_model.py:189-337`：Node(id, weight, activation, label∈7 类
  VALID_LABELS:121-129, graph_space∈4 类:138, execution, confidence,
  extra_attrs, created, last_access)；Edge(src, dst, relation, weight∈[-2,2],
  activation, relation_category∈8 类, extra_attrs, created, last_access)。
  **无 directed 字段**（方向=src→dst 顺序 + config per-relation 方向表
  config.py:318-327/502-514，8 个对称词双向）。
- 归一漏斗 `graph_schema.py:46-67`：词表外关系**一律归一为"关联"**。
  实测后果：G3 的结构角色边 主体/客体/后继 入引擎即被吸收（serial_fix 实测）；
  `出现过`（perception.py:372-374 写入）**未注册词表 → 落成"关联"**，
  时间语义丢失。
- 同三元组合并 `graph_model.py:507-523`：默认 max 权重（负权会被吞，
  kg_status_report §2.2"抑制机制实际不存在"），force_weight 才覆盖；
  **旧权重不留档**（evolution log 的 edge_updated 只记新值，
  graph_evolution_log.py:95-99 有 old_weight 参数但该路径不用）。
- 时间字段：created/last_access="%Y/%m/%d %H:%M:%S"（graph_model.py:68-74）。
  全仓按时间过滤只有三处且全是遗忘/反思窗用途（diffusion_engine.py:300-324、
  continuous_cognition.py:1549-1557、reflection_engine.py:212-222），
  **没有任何"某时发生什么"的正向查询**。

## 2. 时间机制全景（复用点 vs 死路径）

**可复用骨干——ExperienceTimeline（experience.py:225-357）**：
唯一持久、有界（max_raw=4000）、单写者原子落盘（data/experience_timeline.json）
的事件流。事件 schema（:142-158）：`{id, ts 浮点, ts_str(仅时分秒,无日期!),
event_type∈{ACTION,OBSERVATION,SELF_STATE_CHANGE,COGNITIVE_EVENT}, actor,
subject, content, source, confidence, meta}`。写者四路已接
（action_system:684/710、embodiment:336/481、temporal_awareness:293、
expression_feedback:328）；查询 `recent/recent(n, event_type, actor, since)/
events_since`（:333-353）。append 有 2s 去重合并窗（丢重复事件独立时间戳，
:297-326）。CausalLearner（:360-851）已实现 timeline→KG 的唯一晋升通道
（`操作:x-[导致]->变化:y`，provenance 全量在节点属性）。

**其余时间设施全部不承担"经历索引"**：
- temporal_awareness.py：只此刻时钟状态（覆盖式单节点:191-200）；
  `link_event_to_bucket`(:337-348) 零生产调用。
- episodic_buffer.py：结构完好但 `mark_accessed`(:181)/`promote_to_long_term`
  (:147)/`retrieve_by_time`(:226) 全部零生产调用（L1-MEM-01 死路径确认），
  容量 100；唯一生产读者是 reflection_engine 的 retrieve_recent。
- graph_evolution_log.py：**仅内存 ring buffer（上限 1 万条），save/load
  零调用**，无 rename 记录，旧权重不留——不能当历史账本。
- graph_rotation.py：快照备份，本仓零调用（调用在陪伴仓 app.py），无 diff/
  时点查询 API。
- `发生时间` 边：词表在（config.py:368-370），**本仓零写入**（外部 app 的
  LLM 模板写，值=日期字符串节点→高入度星形枢纽病灶，kg_status_report:87）。
- activity_tracker：活动历史显式丢弃（:230-246 自注"活动是当前认知不是
  流水账"）；speech_act_graph 话语节点物理删除超 12 个（:177-192）。

## 3. 事件节点的生产真实形态（与实验不同，已分别核实）

| 创建点 | id 形态 | 结构化槽位 | 历史保留 |
|---|---|---|---|
| action_system.py:891-1029 实例级行动留痕 | `行动_{ms}`（每结算一个） | **无 subject/action 槽位**；仅 created 字符串 | 节点不删，`时间顺序` 链相连（:948-955，链头不落盘跨进程断链） |
| action_system.py:1033-1168 C21 事件框架（默认关 config:1996） | `行动经验:{atype}({sig})` 签名归并 | 无槽位；success/last_reason **就地覆盖**（注释自认"历史在 timeline"） | 计数累计、单值覆盖 |
| speech_act_graph.py:195-240 | `话语_{ts}` | type/text/言外行为… | **超 12 个物理删除** |
| reflection_engine.py:529-577 | `反思_{ts}` | 文本字段 | 无帽无清理 |
| self_graph.py:284-315 情绪事件 | `事件: {名}` | 仅 event_timestamp | 节点留档 |

结论：**没有任何生产事件节点带结构化 subject/action/object/时间槽位**
（kg_status_report §2.6 自认"槽位子图做了一半，另一半烤进节点名"）。
实验里 `事件:E4` 是 build_dataset.py:88-96 的实验构造，且角色边 主体/客体/
后继 过归一漏斗后**在引擎内全部变成"关联"**（serial_fix 实测）——
不能据此断定生产同构，生产是"扁平 attrs + 烤进 id"的另一种不完整。

## 4. 对象身份与概念/实例

- 三档身份标记：Unknown*（perception.py:129-159，**种类级不是个体级**——
  同一头 cow 两次目击共享 UnknownEntity_cow）、裸名物种（promote_species
  :308-412 晋升，保留 observed_at/first_dist/last_observed_at 计数）、
  `物品:x`（背包=概念节点+count 单值，perception.py:182-245：逐堆聚合
  in-place 覆盖、快照缺失置 0——**个体存在性/获得时间/位置/消耗序列全丢**）。
- **概念→实例的类属边（这是一个箱子）零生产写入点**；`同一` 关系在词表
  （config.py:363/474/521，双向）但**全仓生产零写入**——同指消解机制不存在
  （唯一写点在离线脚本 apply_claude_expansion.py:155）。
- 复合/别名：compound_phrase_handler 只做解析路由不合并节点；
  graph_expansion.py:404-410 同义命中复用（strip/小写级）；add_node 同 id
  静默丢弃（graph_model.py:415-416）；附近方块只是逗号串槽位值
  （perception.py:162-164），**个体方块连节点都不是**。

## 5. 状态覆盖与历史可恢复性（覆盖点清单摘要）

perception 状态槽/count/位置 in-place（:56-81/221-245/249-251）→ 图上
**不可恢复**（fas_log 流有 old/new 残影）；C21 success/last_reason 覆盖；
add_edge 权重覆盖不留旧值；disposition/话语/活动删除不可恢复。
兜底只有 graph_snapshots（粗粒度时点回滚）。遗忘机制
（_forget_factor/inter_round_decay）只动激活不动结构——**新增
validity/source 类 attrs 不会被遗忘机制删除，但也没有任何现成消费者**。
episodic_retention_days（config:1858）零读取（死配置）。

## 6. 旧实验失败的表示层归因（修正版）

| 失败 | 归因 | 判定 |
|---|---|---|
| cross_episode G3 0/30（事件稀释金实体+ids 不可读） | 事件节点无槽位+角色边被归一+Top-k 无 per-space 配额 | **表示缺陷**（serial_fix 已三层解耦实测：可达性/表示/呈现各缺则 0%） |
| mechanism_campaign 星形森林 | 需要/产生/掉落 全 forward 指向汇点 | 图本体方向语义（非引擎 bug） |
| controls T3 失败证据被挤出 | Top-k 权重排序+8 槽 | 呈现策略，非表示 |
| kg_status 291 种关系 71% 单次、日期枢纽 | 无归一前的写入失控 | **已被归一漏斗治理**，但代价是结构角色词被吸收（新发现的反例） |
| perception 逐堆覆盖真机事故 | 实现 bug | **2026-09-26 已修**（按名聚合） |

## 7. 缺陷清单（本设计要解决的，按优先级）

P1 事实无时间有效期与来源约束：关系变更是覆盖不是 supersede，
   "过去在哪/何时"图上不可表达、timeline 与图无回链。
P2 事件无结构槽位（动作/参与者/时间/来源烤进 id 或散落 attrs），
   且部分节点类型被物理清理。
P3 概念/实例不分：实例级信息（个体、个体位置）无处安放；同指消解缺失。
P4 检索输出只有 id（Top-k→序列化丢语义）。
P5 归一漏斗吸收结构角色词（出现过 已被吸收；新增关系必须先注册词表）。

## 8. 拟修改模块与回归风险（Phase-2 范围预览）

新增 `memrep.py`（事实记录/取代、事件记录、实例与同指、工作集序列化），
全部经 `config.memrep.enabled`（默认关）；试点接线
minecraft/perception.py（拥有 count 变化→FACT_CHANGE 事件）与
action_system.py:_write_action_memory（行动节点补结构槽位+timeline 回链），
均门控。experience.py 事件 schema 加可选结构字段（additive 向后兼容）。
**回归风险点**：timeline append 频率增加（2s 合并窗已缓冲）；episodic 事件
节点与 semantic 同池竞争 Top-k（既有问题，不新增节点类型则不恶化）；
perception 改动需逐位回归（goal_planner/goal_path 测试依赖 拥有 边语义）。
