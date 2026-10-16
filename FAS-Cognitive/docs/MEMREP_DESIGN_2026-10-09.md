# 记忆表示设计说明与关键取舍（2026-10-09，Phase-1 交付之二）

前置：`docs/audits/MEMREP_AUDIT_2026-10-09.md`。原则：能复用不新建；
additive 优先；默认关；不破坏既有唯一三元组不变量、归一漏斗、扩散、遗忘。

## 一、八个设计问题的回答

**1. 哪些信息继续作为普通节点和边保存？**
绝大多数：概念、实例、类属、当前有效的关系（位置/拥有/需要/产生…）、
当前状态槽位。图仍然只表示"当前认知上为真的东西"——这是它擅长且
已被验证的形态（扩散/检索/规划都基于它）。

**2. 哪些经历需要独立事件表示，哪些只记关系变化？**
判据（通用，非按对象类型）：**凡需要保留"动作+多个参与者+结果/意图"
的信息记事件；凡可以表达为单个关系真值变化的信息记关系事实**。
- 事件：`record_episode()`——创建 事件 节点（label=declarative-episodic），
  槽位放节点属性（action/subject/object/source/ts_iso/seq），图边只连
  已注册词表的关系（涉及/导致/发生于），**不再新造 主体/客体 这类会被
  归一吸收的角色词**（审计 §5-P5 的直接教训）。
- 事实：`record_fact()/supersede_fact()`——只动边属性 + timeline 流水，
  不建节点。
不预设所有经历建事件节点（准则 5）：perception 的 count 变化、状态槽
翻转都是事实级；planner 的行动结算、用户复杂指令是事件级。

**3. 时间轴如何关联图谱而不成为第二套记忆？**
**复用 ExperienceTimeline 作为唯一时间轴**（审计确认它是唯一持久、
有界、可查 since 的时序存储，且已有四路写者与落盘）。双向回链：
- 图→轴：事实/事件节点 attrs 带 `ev=<timeline 事件 id>`；
- 轴→图：事件 meta 带图谱节点 id 列表。
新增 `FACT_CHANGE` 事件类型（additive 常量）：`{subject, relation, object,
valid_from, valid_until, source}`——**取代/失效记录进轴，不进图**。
不做独立时间索引节点（日期节点星形枢纽是已知的病灶，不再造）；
不做时间戳字符串节点。
对 timeline 的最小补强：事件补 `ts_iso`（含日期，现 ts_str 只有时分秒）、
可选结构字段（action/subject/object），append 兼容旧字段。

**4. 如何区分概念、实例和同一对象的不同提及？**
- 概念节点：现状所有类级节点（篮子、mc_knowledge 物种、配方）——不动。
- 实例：`memrep.get_or_create_instance(kg, concept, disc)` → id
  `个体:{概念}:{disc}`（通用命名，不区分苹果/篮子/工具），attrs
  `{instance_of: concept, discriminator, source, created}`，边
  `个体 -[实例属于]-> 概念`（**新关系，注册进 relation_ontology**——
  P5 教训：不注册即被归一毁掉）。同概念多实例天然不合并（不同 id）。
- 提及消解：**v1 不做自动合并**（审计：同一 关系零生产使用、同名判据
  全无）。提供 `link_mentions(a, b, conf, source)` 显式写 `同一` 边
  （词表已有、双向、带 provenance）；证据不足 = 不建边（保留不确定性）。
  自动消解列为后续实验（需要共指证据积累，超出本轮）。
- Unknown*→个体：promote_species 既有晋升通道保持；个体实例化仅在
  有区分符证据时发生（SimEnv/感知提供 disc），无证据不虚构实例。

**5. 如何保留历史状态，同时避免旧状态污染当前判断？**
- 图边 = 当前有效（唯一三元组不变量不破坏）。
- 变更时 `supersede_fact()`：旧值+时间+来源写入 timeline FACT_CHANGE
  （valid_from→valid_until 闭区间），然后按既有语义更新图边。
  旧状态**不**以同等效力留在图里参与扩散/当前判断（回答"过去在哪"走
  timeline 查询，不靠图上残留旧边）。
- timeline FACT_CHANGE 查询：`memrep.fact_history(kg, subject, relation)`
  → 从 timeline 过滤（events_about 复用）。
- 覆盖点改造是**渐进**的：v1 只试点 perception 的 拥有 count 变化
  （最高频、真机事故史）；其余覆盖点列后续。

**6. 如何避免扩散把时间索引/结构性节点当重要记忆？**
时间轴不在图里（无索引节点可被点亮）；事件节点不新增类型（复用
declarative-episodic + 现有 episodic 空间规则：decay 0.15/cap 3.0，审计
确认其沉底行为）；`实例属于` 是 semantic 正常关系（实例应当可被联想，
这是特性不是 bug）；序列化器对 episodic 事件节点做签名级去重渲染。
Top-k 同池竞争（cross_episode 量化的稀释）**不在本轮修**——那是
消费者层配额问题，另案。

**7. 如何兼容现有图谱、写入与规划模块？**
- 全部 additive：新 attrs（ev/valid_from/valid_until/source/instance_of）
  不被 add_edge 合并、upsert 深合并、遗忘、reattach_graph 破坏
  （审计 §6 逐机制核实过）。
- 归一漏斗：新关系先注册（实例属于 补进 relation_ontology）。
- 旧数据兼容：无 validity 字段 = 视为"有效、来源未记录"（序列化如实
  标注，不伪造）；timeline 旧事件无结构槽位 = 序列化 fallback 到
  content 字符串。**不回填、不伪造缺失信息**（准则/任务八）。
- 回滚：`config.memrep.enabled=False` 单开关；新字段成惰性数据，无
  结构迁移需要逆转。

**8. 哪些复杂度当前需要，哪些留待验证？**
需要：FACT_CHANGE 流水、事件属性化、实例/实例属于、同指显式边、
序列化器。留待：自动共指消解、per-space Top-k 配额、快照 diff 查询、
evolution_log 持久化（另案，各需独立验证）。

## 二、新增接口一览（memrep.py，全部确定性、零 LLM）

```python
record_fact(kg, tl, src, rel, dst, source, confidence)  # 首建/更新边+流水
supersede_fact(kg, tl, src, rel, dst, new_dst|None, source)  # 失效+新值
fact_history(tl, subject, relation=None)                # 历史查询
record_episode(kg, tl, action, subject, object, source, ts=None)  # 事件节点+回链
get_or_create_instance(kg, concept, disc, source)       # 实例
link_mentions(kg, a, b, conf, source)                   # 同一（显式同指）
serialize_working_set(top_nodes, edges, kg, tl)         # F 场景表达层
```
来源枚举：`observed / user_stated / inferred / action_result`（E 场景）。
所有写点门控 `config.memrep.*`。

## 三、试点接线（各一处，门控）

1. `minecraft/perception.py` 拥有 count 变化 → `record_fact` +
   变更幅度 FACT_CHANGE（开着才有流水；关=现状逐位）。
2. `action_system.py:_write_action_memory` 行动节点补
   `{action, subject, object, ts_iso}` 槽位 + `ev` 回链（数据取自
   action 本身，不新增语义）。

## 四、迁移/兼容/回滚

- 数据：无 schema 变更（全部 extra_attrs/timeline 追加）；旧图打开即用，
  缺字段如实降级。timeline 旧事件保留原样。
- 迁移脚本：不需要（additive）。验证：tests/test_memrep.py 含
  "旧格式数据加载后新查询不崩、如实标注来源未记录"用例。
- 回滚：config 单开关；试点文件改动均为 `if enabled:` 包裹的增量路径。

## 五、测试计划（Phase-3，对应任务 A-G）

tests/test_memrep.py：
A 概念/实例：两实例不同 id、均 实例属于 概念、概念单节点、同 id 不重复。
B 状态变化：位于 桌子→篮子 supersede 后：图边=篮子；fact_history 含
   桌子区间（valid_until 非 None）与篮子区间（valid_until None）。
C 时间顺序：events_between/events_since 排序；ts_iso 含日期。
D 经历重建：record_episode 后可从 attrs+ev 回链恢复对象/动作/时间/来源。
E 来源：三来源记录与序列化标记区分；inferred 不伪装 observed。
F 检索表达：serialize_working_set 输出含 身份/方向/时间/来源 要素，
   非"-" 裸 id；1-hop 补全；事件签名去重。
G 回归：gate off 全零触碰（快照比对）；关闭态跑 perception/act 相关
   既有测试 + 全仓 pytest 与基线一致。
数字断言状态迁移与流水内容，不只查无异常。
