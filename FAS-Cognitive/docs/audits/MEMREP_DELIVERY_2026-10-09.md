# 记忆表示重构 — Phase-4 交付报告（2026-10-09）

配套：审计 `docs/audits/MEMREP_AUDIT_2026-10-09.md`、设计
`docs/MEMREP_DESIGN_2026-10-09.md`。生产开关：`config.memrep.enabled=False`
（默认关，关态零触碰，回归逐位一致）。

## 1. 修改文件与关键位置

| 文件 | 变更 | 性质 |
|---|---|---|
| `memrep.py`（新增） | record_fact / supersede_fact / fact_history / record_episode / enrich_action_node / get_or_create_instance / link_mentions / co_referents / serialize_working_set | 全部 additive 工具函数，无生产自动行为 |
| `config.py:369` | `实例属于` 注册进 relation_ontology | **必要**：不注册会被归一漏斗吸收成"关联"（serial_fix 实测的表示层根因） |
| `config.py`（planner 节前） | `memrep` 节（enabled=False 等默认） | 门控 |
| `action_system.py`（_write_action_memory 内） | 门控试点：行动留痕节点补 `{action, object, ts_iso}` 槽位 + timeline EPISODE 回链（ev ↔ meta.kg_node） | `if _mr.get("enabled")` 包裹；关=逐位不变 |
| `tests/test_memrep.py`（新增） | A–G 场景 19 断言 | 离线确定性 |

未动：graph_model（节点/边结构、add_edge 合并语义、归一漏斗本体）、
diffusion_engine、experience.py（零修改——结构字段放事件 meta，additive）、
perception/planner/goal_path。**协作者未提交改动
（continuous_cognition.py / temporal_awareness.py / charon_bridge.py 等）
与本工作无交集、未触碰。**

## 2. 新能力 × 测试结果（tests/test_memrep.py，19 断言全绿）

- **A 概念/实例**：`个体:篮子:厨房` 与 `个体:篮子:储藏室` 是不同节点，
  各自 `实例属于` 篮子；同区分符幂等；词表注册实测生效（边名不被归一）。
- **B 状态变化**：苹果 位于 桌子→篮子：图上只剩新位置（旧边摘除，
  不参与扩散/当前判断）；历史经 `fact_history` 恢复为区间
  （桌子 [t1~t2] 闭合、篮子 [t2~open) 当前有效）。
- **C 时间顺序**：事件流有序、`ts_iso` 含日期（补了 timeline 旧字段
  只有时分秒的缺口，additive 放 meta）。
- **D 经历重建**：事件节点结构槽位（动作/主客体/时间/来源）+
  节点 ev ↔ timeline kg_node 双向回链；参与者用已注册 `涉及` 边
  （角色在属性，不造未注册角色词）。
- **E 来源**：observed/user_stated/inferred 如实分档；非法来源降级
  "未记录"，不伪装成观察。
- **F 检索表达**：serialize_working_set 输出含身份/方向/有效期/来源
  （`个体:篮子:厨房（篮子 的个体）`、`苹果 -[位于]-> 桌子 [自…]（来源:observed）`、
  `事件 放入：苹果 放入 篮子 @…`），非裸 id；1-hop 图补全；失效边
  如实标注 `[…，已失效]`。
- **G 回归**：门关时行动节点无新槽位、旧字段逐字段一致；门开时补全+
  回链（timeline 注入式，测试用临时目录）。

## 3. 既有能力保持（回归证据）

- 全仓 pytest：当前树 100/100 与 HEAD（10dcb2b）基线 worktree 100/100 同集通过。
- 独立套件 exit 0：test_current_goal / test_cognitive_loop /
  test_activation_recall / test_goal_planner / test_goal_path_bias / test_memrep。
- 扩散/遗忘/规划/图谱读写零修改（diffusion_engine/graph_model/
  experience.py 未触碰），无需行为对照——检索质量在关态定义上不可能变化；
  开态的序列化收益已有独立对照：serial_fix 机制实验（G3 事实重构
  0% → k=16 100%，三层修复解耦）即同一表达策略的前置验证。

## 4. 数据迁移/兼容/回滚

- **迁移：不需要**——全部 additive（extra_attrs 与 timeline 追加）。
  旧图直接打开；无 validity/source 的边按"有效、来源未记录"如实降级；
  旧 timeline 事件无结构槽位时序列化 fallback，不伪造。
- **回滚**：不调用 memrep / 关 `config.memrep.enabled`；新字段成为惰性
  数据，无需要逆转的结构变更。
- **无法无损迁移的**：既有覆盖式写法（perception count 等）的历史值
  在旧数据中本就不存在——按审计如实标注"未记录"，不补造。

## 5. 退化风险与实测

- 内存/速度：新字段为稀疏 attrs；timeline FACT_CHANGE 走既有 4000 条
  环形界与原子落盘（单写者未变）；测试套件耗时无可见变化（2.25s vs 基线 3.44s 内的噪声区间）。
- 图谱规模：不新增节点类型；事件节点仅在显式 record_episode 时创建。
- 已知限制（未解决，如实）：
  1. `supersede_fact` 只覆盖"关系对象变化"型状态变化；属性型覆盖
     （count/槽位 value）的试点（perception 拥有流水）**未接线**——
     需要 timeline 注入点归 app 管，列为下一步。
  2. 同指消解只提供显式 `link_mentions`/`co_referents`，无自动判定
     （按设计：证据不足不合并）。
  3. Top-k 同池竞争（事件节点稀释）是消费者层问题，本设计未修（另案）。
  4. 时间轴骨干依赖 ExperienceTimeline 单写者约定——多进程写同一文件
     未验证（本仓单进程）。
  5. 全部验证在离线确定性环境；真实 Minecraft/生产装配未验证
     （与此前各轮相同，桥/装配在父仓）。

## 6. 设计假设检验记录

实现中修正的两处设计预期（非硬凑）：
1. `append(merge_window_s=0)` 必须显式传——否则 FACT_CHANGE 会被 2 秒
   合并窗吞掉独立时间戳（experience.py:297-326 的既有行为）。
2. `remove_edges(src, dst, relation)` 三维定位取代旧边——原设计只按
   (src,relation) 会误删同主语其他对象的边（测试 B3 捕获后修正）。
