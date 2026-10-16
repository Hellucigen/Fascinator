# 目标导向路径强化 — 最小机制设计（DRAFT，待确认后才动生产代码）

状态：**设计稿，未实施**。前置：`docs/audits/GOAL_PATH_AUDIT_2026-10-09.md`。
原则：默认关闭、可独立消融、不回写长期边权、不伪装语义边为可执行路径。

## 1. 两阶段交付（第一阶段零生产修改）

### Phase 0 — 只读路径审计（先行，可立即做）
新脚本 `experiments/goal_path_bias/path_audit.py`，对固定图集合
（快照 `FAS_Research_Experiments/baselines/run_20260928_113149/full_graph.json`、
knowledge_packs 三包、mechanism_campaign Graph F）做**只读**统计：
- 每个 goal/物品:X 节点的反向可达集（沿 `产生/掉落/需要/需要工具/属于(→可采资源)/拥有` 白名单入边爬链，仿 `world_prior` 读边方式，不依赖 minecraft-data 桥）；
- 与 forward 扩散可达集对比；汇点/星形/孤立比例；路径深度分布；
- current_goal 指针（若存在）能否解析到可执行路径。
产出 `path_audit_report.json`——为"图谱没有足够状态转换语义的部分不实现偏置"
提供逐图证据。

### Phase 1 — 机制模块（确认后实施）
新模块 `goal_path_bias.py`（生产根目录，默认不导入即零影响），两个可分开关：

```
config:
  goal_path:
    enabled: false          # 总开关（默认关）
    search: false           # 仅搜索+记录，不施加偏置（审计模式）
    bias: false             # 施加激活偏置（依赖 search）
    max_hops: 8             # 与 world_prior.MAX_DEPTH 对齐
    max_paths: 3
    max_nodes: 12           # 偏置节点数预算
    floor_scale: ...        # 偏置强度（标定实验决定，见预注册）
    relations: [...]        # 白名单（见 §2.2）
```

## 2. 算法（复用现有数据结构，不改扩散引擎）

### 2.1 步骤
1. **取目标**：`self_graph.current_goal(kg)`；解析目标锚点节点：
   优先 `物品:<名>` 子串匹配（与 autonomy._obtain_goals 同一口径，避免第二套解析器），
   其次目标节点自身 label 在图中的出边指向的状态节点。解析失败 ⇒ NO_TARGET，不偏置。
2. **取当前状态锚点集**：`Haru-[当前状态]->…-[状态项]->` 槽位 +
   `Haru-[拥有]->物品:*` 边（背包）；无具身层时退化为"拥有边+活跃前沿内物品"。
3. **反向搜索**：从目标锚点沿**白名单关系的入边**（dst→src）BFS，
   visited 集合防环，深度 ≤ max_hops，产出候选路径（终点=某状态锚点或 `可采资源` 类叶子）。
   —— 方向语义与 `world_prior` 一致：利用汇点的入边，**不忽略边方向、不改 config 双向表**。
4. **路径质量**（第一版只用图上已有事实，不新增知识）：
   `quality = f(链长, min(边静态权 w), provenance confidence, 是否落在真实状态锚点)`；
   未通过基本有效性检查（无状态锚点落地、含未知 provenance 边、环）⇒ 丢弃并记录 REJECTED 原因。
5. **偏置施加（只走现有公开通道，autonomy §9 先例）**：
   对 top-1 路径节点 `n`，若 `n.activation < bias_value(quality)`：
   `n.activation = bias_value; n.touch()`，随后 `engine.mark_active([n…])`。
   bias_value 随距目标跳数衰减（如 `floor × γ^hop`，γ<1）。
   **不写 edge.weight、不写 edge.activation、不注册 _sources。**
6. **交现有消费者**：Top-k/diffuse_round 照常（路径节点进前沿后按正常动力学参与）。
7. **清除**：偏置是普通激活直写 ⇒ 现有 `decay_step`/回合衰减自然清除；
   另提供显式 `clear_bias(kg, engine)`（记录本次写过的节点，置回写前值）用于
   目标切换/测试与"可关闭可清除"验收。
8. **失败证据保护**：偏置预算 max_nodes 用尽即截断；若某节点同时挂有
   近期 `结果:-0.8` 失败边，记入遥测（不屏蔽——第一版只观测不改规则）。
9. **推进判定（只读记录，v1 不做闭环控制）**：动作执行后比较
   背包/状态锚点变化，记录 `goal_progress` 事件到实验日志——供行为实验指标 2。

### 2.2 关系白名单（可执行语义最小集）
`产生`、`需要`（含 count）、`掉落`、`需要工具`、`属于`（→可采资源）、`拥有`。
`关联/关于/涉及/参与/表达方式/可实现为` 等一律**不得**进路径
（前者纯语义；后者是抽象映射不是转换）。跨出 MC 域时白名单搜索为空
⇒ 机制自动降级为 NO_PATH，不伪造。

### 2.3 消融矩阵（search / bias 独立开关）
| search | bias | 行为 |
|---|---|---|
| off | off | 基线（生产逐位不变，回归测试保证） |
| on | off | 只读审计：路径质量记日志，零激活写入 |
| on | on | 完整机制 B 条件 |
| off | on | **禁止组合**：启动时报错退出（偏置必须来自真实搜索） |
C 条件（可执行性检查）= bias on 且开启 `require_state_anchor: true`
（路径必须落在真实状态/背包锚点才偏置）——v1 用白名单+锚点检查实现，
**不新增规划器**；完整规划器交互（next_step 级）列为后续实验。

## 3. 涉及文件清单（Phase 1）

| 文件 | 动作 | 说明 |
|---|---|---|
| `goal_path_bias.py` | 新增 | 全部新逻辑；不导入即零影响 |
| `config.py` | +小段 | 新 `goal_path` 节，默认全关 |
| `autonomy.py` | ≤5 行接线 | `_obtain_candidates`/tick 内可选调用（gate 默认关；关时逐位不变） |
| `tests/test_goal_path_bias.py` | 新增 | 见 TEST_PLAN §1-2 |
| `diffusion_engine.py` / `self_graph.py` / `world_prior.py` / `graph_model.py` | **不改** | 只用公开接口 |
| `experiments/goal_path_bias/` | 新增 | path_audit.py、run_mech.py、run_llm.py、遥测与快照 |

风险与回滚：
- 挤占失败证据/其他证据（H4）→ 预算上限 + 遥测指标 5，行为实验有 guard 指标；
- 强化错误路径（低置信 provenance）→ 白名单 + 锚点检查 + REJECTED 日志；
- 非预期生产变化 → 关开关后跑 `tests/test_cognitive_loop.py` 等全量回归，
  与基线逐位比对（同种子、同配置）；
- 回滚 = 删 config 节 + 去接线行，无数据结构迁移、无落盘格式变化。
