# 测试计划（机制层先行，LLM 行为层最后）

## 1. 单元测试（固定小图，无 LLM）
1.1 无目标：`goal_path.enabled=True` 但 current_goal 为空 ⇒ 零激活写入（逐位不变）。
1.2 目标不可达：白名单关系不足/目标为孤立汇点 ⇒ NO_PATH，无偏置、日志有记录；**不得伪造路径**。
1.3 循环图：A→B→C→A 配方环 ⇒ visited 防环，有限时间收敛（断言耗时上界）。
1.4 方向语义：`关联/关于` 边不得成为路径边；`需要/产生` 只沿入边方向被使用；
   断言生成的 chain 与 `world_prior.next_step` 在同图同目标下一致（一致性交叉验证）。
1.5 开关与清除：bias on→off 后调 `clear_bias`，节点激活回到写前值；
   关掉 `goal_path` 全节后 `tests/test_cognitive_loop.py / test_current_goal.py /
   test_cognitive_field.py` 全量通过，且与关闭基线 run 逐位一致。
1.6 长期权不变式：偏置前后 `edge.weight` 与 `kg` 序列化快照逐字节相同；
   `edge.activation` 不被本模块写入（断言 diff 只在 node.activation 且 ≤ max_nodes）。
1.7 Top-k 可观测性：注入后 `get_topk(k=8)` 名次记录；预算截断可观测（>max_nodes 候选时只偏置前 N）。
1.8 失败证据遥测：带 `结果(-0.8)` 边的节点被路径命中 ⇒ 日志记录 conflict 事件，信息不被屏蔽。

## 2. 机制级实验（无 LLM，确定性）
- 固定图集：Phase-0 path_audit 输出 + Graph F/B 结构（relation_direction_campaign 口径）+
  合成拓扑分层（星形/链/环/双目标竞争/目标在语义域）。
- 主要机制指标：正确路径 recall@8、错误路径强化率（低 provenance 路径被偏置的比例）、
  失败证据 recall@8 留存率、搜索耗时（ms）、前沿膨胀量。
- 配对 seed（噪声点火序），Wilcoxon + Holm；效应量+95%CI。
- 停止条件：若 B 条件在机制层都无法提高 recall@8（≤基线+1pp 且 CI 含 0），不进入行为层。

## 3. 行为实验（LLM 决策头）— 见 PREREGISTRATION_DRAFT.md
在机制层 SUPPORTED 后才跑；同一批固定图先过 §1-2 全绿。
