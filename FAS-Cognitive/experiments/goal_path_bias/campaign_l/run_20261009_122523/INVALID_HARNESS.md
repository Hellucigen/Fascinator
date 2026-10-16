# INVALID HARNESS（保留不删，routing v1 先例口径）
本 run 的决策头 max_tokens=120 被推理模型的 reasoning 消耗吃光：
A 条件 25/30 空回答（completion_tokens=120 截断于输出 STEP 行之前），
B/C 空回答 5/4。失败层级 = 实验装配（输出预算），非机制层。
处置：同模型/温度/预算参数全条件统一 max_tokens=400 后整体重跑一次
（预注册 §族L 基础设施条款；本次重跑是新数据生成前唯一允许的一次）。
本目录数据保留作审计证据，不入任何结论。
