# Haru 自主生活深化 v2：图谱驱动实施报告（2026-10-14）

## 断点与修复总表

| 断在哪 | 原状（硬规则） | 现状（图谱量） |
|---|---|---|
| 念头→行动 | 三档固定分 0.95/0.90/0.60 + 0.35 激活阈值 | `_graph_strength()`：持续性(边权/承诺)×注意力(激活)×新近性(72h 半衰)×成本(历史失败进分母) 连续函数，候选同池竞争谁大做谁 |
| 持续 | 承诺边只挂着不参与决策 | 承诺强度=目标边权×(0.5+0.5×激活)：激活跌只减半不消失（失焦≠遗忘）；重启后边在强度在 |
| 搁置恢复 | **72 小时时间锁** + 一次复活硬顶 | 证据消费模型：暂停之后出现且未被消费过的新信息命中其概念 ⇒ 立刻可复活（10 分钟也行）；同证据不重复触发；反复失败由 penalty 降竞争力，记忆永不清 |
| 结果→知识 | found 只留情景经历（标题+摘要） | `_internalize_found()`：正文→`extract_assertion_graph`→`_auto_consolidate` 既有漏斗（名称归并/去重/保守边权），source=research:url、w_scale=0.6 折扣、Node.confidence 原生字段；已内化缺口在求助竞争里自然衰减（答过≠新需求） |
| 知识联系 | 无 | `_emerge_hypotheses()`：高激活概念对+共同邻居锚点+无直接边→待验证假设（episodic、weight 0.3、confidence 0.3、可追溯 anchor），进候选池参选；每拍≤1、同对不重建、有边不长假设 |
| 分享 | 被拒一次永久封箱 | 复审≤2 次：首拒可因情境（对话正热），二拒才安静；投递失败保留候选下拍重试 |
| 目标边卫生 | state 单槽记边→孤儿边泄漏 | 账本为唯一真相：凡 dst≠当前承诺的目标边一拍清光（自愈，不依赖记忆） |

## 修改文件
- `activities.py`：`_graph_strength`/`_emerge_hypotheses`/`_internalize_found`/`_consume_evidence`/`_reconcile_goal` 自愈版；候选行删尽常量。
- `living_loop.py`：72h 时锁与次数硬顶删除；`_fresh()` 新鲜度函数；缺口合并=同池按 priority 竞争（`max`，非位置）；`social_step` 复审制；耗尽统一 paused。
- `app.py`：`_auto_consolidate_curiosity_knowledge(source=, w_scale=)` 参数化（好奇心路径默认逐位不变）；`_life_ctx` 传 gaps/nlp/buffer/consolidate_fn（延迟绑定修 10:50 加载竞态 NameError）。

## 验证
- `tests/test_life_continuity.py` v2 **32/32**（C 连续承诺 E 证据消费 H 假设 K 内化 F 新鲜度 G 生题+切换 Q 安静 S 复审）。
- 全量回归：life_driven 20/20、taskloop 48/48、activities 17/17、context_io 21/21、quality_gates 23/23、config_store 30/30、llm_recovery 12/12、planner ✓；认知层 pytest **161 passed**。
- 生产：10:26 起强度呈连续值（0.52/0.33/0.24，非档位）；10:36 图谱提名"元认知"自开活动（chat_log 无此引号——纯图谱生题活体）；11:02 陈旧目标边自愈日志 `[Act] 摘除陈旧目标边 1 条（承诺=元认知）`；NameError 竞态修复后节拍稳定。

## 已生产验证 vs 仅沙盒
- 生产验证：连续强度、图谱生题、承诺推进、目标边自愈、安静语义、预算闸。
- 仅沙盒：证据消费复活（生产还没产生新证据命中搁置概念）、知识内化（等一次真实 found——元认知研究两次查询不相关，被如实搁置着）、假设浮现（当前无满足结构条件的高激活对；出现前不虚构是纪律）、分享复审。

## 保留的工程边界（非认知规则）
日网络预算/单活动 6 次、每拍 1 条分享、REEVAL 90s 合并、THRESHOLD 0.12 底线、living_loop_enabled 热停、read_page 限长/超时、相关判定 `_concept_match`。

## 风险与回滚
- 假设节点会进图谱：每拍≤1、低权重、episodic 标签，即使质量不佳也只贡献弱激活，可 `graph_doctor` 扫尾。
- 内化每次 done 一次小模型调用（正文≤1500 字，qwen3.8-flash ≈¥0.001/次）；`knowledge_ingested` 幂等防重烧。
- 回滚：全部为工作区未提交修改（三文件）；恢复上一版即回退，无数据迁移。行为级止血：把 `living_loop_daily_web_budget` 设 0 可整体静默研究而不影响其他通道。
