# FAS-Cognitive 认知层报告

日期：2026-10-08 · 基线：拆仓首 commit（de6e8bd）· 姊妹文档：`COMPANION_REPORT.md`（FAS-Companion 仓）
实验状态唯一台账：**`docs/COGNITIVE_MODULE_STATUS.md`**（本报告不复制其结论，只引用；冲突以台账+原始报告为准）

---

## 1. 定位与边界

FAS-Cognitive 是两轨制中的**认知线**：FAS 真正要长期保留、实验验证的核心机制。
四条硬边界（前三条有测试自动守护）：

1. **零 LLM 依赖可运行**。70 个根模块全部只在参数注入处接触语言层，无模块级 import
   陪伴/LLM 侧代码；`fas/core` 有 AST 纯度红线测试防回潮（禁 import
   nlp_processor / prompt_templates / llm_provider / ollama_backend / app / flask）。
2. **状态入口收口**：外部对认知的一切写入只走 `CognitiveCore.perceive / record_memory /
   propose_action / tick`；陪伴层不得再直写 kg._lock / activation / mark_active（存量违例登记 §6）。
3. **验证纪律**：代码存在 ≠ 机制成立。每个机制带状态标签
   （validated / partially_validated / failed / bugged_experiment / untested / hypothesis）
   和证据路径；负结果照实记录，不包装。
4. **重构护栏**：拆仓/解耦不触碰算法、参数与已归档 run 数据
   （Research validity > architecture purity > code elegance）。

## 2. 仓内地图（2638 文件）

```
核心动力学        graph_model / graph_schema / diffusion_engine / cognitive_field /
                  tension_field / drive_field / cognitive_networks / modulation*
记忆与学习        episodic_buffer / experience(CausalLearner.promote_to_kg 写回)
驱力与好奇        drive_engine / curiosity_engine
自我模型          self_model / self_graph（goal_attention consumer 10-02 才接入）
决策与行动        dialogue_decision(零 LLM 竞争头) / autonomy / action_system /
                  action_space / action_concepts / action_resolver / safety_kernel /
                  skills(世界技能) / minecraft(reflex/感知/桥) / Action / actions
调节              cognitive_regulation / cognitive_locks / cognitive_triggers / state_monitors
内部状态          internal_state（需求/激素/性格唯一数值真源）/ disposition_store /
                  personality_baseline
语言输入分析      compound_phrase_handler(短语→图谱关系) / cognitive_context(七分区上下文+
                  发言提纲+compile_for_language) / speech_act_graph
解耦层 fas/       contracts(跨界数据结构) / protocols(稳定接口) / core(门面+独立装配) /
                  companion(语言后端包装+Charon通道) / registry(槽位台账)
工程             config(双侧共享真源，拆分属登记债务) / json_store / fas_log /
                  embedding_manager(bge+FAISS 可选) / experiment_mode|recorder
研究资产          FAS_Research_Experiments(18M) / experiments(13M) / research_audit /
                  experiment_dynamic_revalidation / paper_audit / docs(架构+设计文档)
测试              tests/ 105 个文件（pytest 式 + 脚本式 conftest 自动分类）
```

规模：根级 Python 约 **38k 行**（不含实验目录）。

## 3. 认知侧实际具备的能力（按证据强度排序）

**机制层证据较硬的：**
- **扩散汇聚**：机制本身健康——663-run 独立证伪（纯 stdlib 参考实现、预注册统计）
  证实 H_join SUPPORTED（多输入 r@1=MRR=1.0）；但**相对 flat 检索的行为增量被
  34,016-run 预注册实验 REJECTED**（4/4 主条件 ΔJCG<0），行为层"−扩散更快"REFUTED。
  结论边界：扩散是**访问层机制**（相关性加权再激活），不是行动驱动器。
- **写回/学习**：B1/B2 写回隔离 VALID（0 vs 13 节点）、账本迁移 C 行为级 VALID
  （改变"如何"不改变"是否"）；A10 信标战役 80/80 收官，fas_full 20/20 vs
  llm_direct 0/20（p=2e-06）——记忆价值在信息不对称域成立。
- **标量调制**：C-emo 剂量反应 VALID（限 gain 通道），R2 14 靶点 PASS。
- **统一 KG**：结构/持久化经反复审计（空图覆写事故后三重守卫）；**表征价值无行为实验**，
  且 40% 边是"涉及"共现 fabric（治理方案已出、待裁决）。

**有首证但脆弱的：**
- **self-model**：v6 曾被证明"写而不读"（current_goal 生产零读取者）；10-02 v7 修复后
  才有首个行为差分（派生目标 0/5→5/5）。novel 条件仍 0/5。
- **行动选择**：事件框架沙箱差分 5/5，但生产默认关（config experience_eventframe=False），
  决策头 I 实验 **failed**（FAS 0–2/10 vs LLM 原始流 10/10——基线完胜，如实记录）。

**代码在跑但从未验证的：** curiosity 提问、reflection、disposition、personality、
locks/regulation——全部只有单元测试级。`untested` ≠ 无效，≠ 有效。

**死路径/负结果（不粉饰）：** episodic 自动晋升从未生效（mark_accessed 零调用）；
Hebbian F 通道亚阈；C34 路由 v1 是 bugged_experiment（作废保留）、v2 仅方向性；
前瞻记忆 NOT_IMPLEMENTED；100 周期协议下知识巩固未触发（消融为空操作）。

## 4. 认知内部的 LLM 触点（现状全走注入面）

四个运行时触点全部只经 `CognitiveLanguageAccess` 最小面
（**llm / chat_llm / ask / system_prompt** 四成员），且各有降级：
curiosity→规则兜底问题、reflection→代码把关候选、free thought→预算门、
主动表达→预算不足即沉默。**FAS 自建语言机制：NOT_IMPLEMENTED**（研究问题，非缺陷）。
拆仓当日修复：三处模块不再直接 `import prompt_templates`，模板经 `system_prompt(task)`
取（缺席回退旧直连，逐字等价）——测试 `test_continuous_cognition` 暴露、已修。

## 5. 独立运行与验证状态

- **独立装配**：`fas.core.assembly.build_cognitive_core(config=...)` 不依赖 Flask/LLM
  （复用测试沙箱裸构造模式）；这是"半年后认知机制实验成功→单点接入"的落点。
- **当日测试**：pytest **100 passed**（含 18 项架构解耦集成测试：双后端替换、
  炸芯降级、契约纯度红线）；脚本式抽测 4/4 全过（含原先失败的 _express 路径）。
- **依赖**：核心只用 stdlib+numpy；faiss/sentence-transformers/jieba 可选，
  缺席自动跳过语义召回路径。

## 6. 认知侧登记债务（与陪伴侧报告 §7 互补）

1. **存量直写违例**（在认知仓内）：`eye 写图路径`、`minecraft/perception`、`mc_knowledge`、
   `expression_feedback`（kg._lock/add_node/add_edge/mark_active 直用）、`dialogue_decision`
   原地改 activation——收口到 façade 需先给 `MemoryEvent` 补 frame/edge_type 字段。
2. **config.py 单点共享**：1954 行 dict 同时是认知参数与陪伴运维真源，5 个模块绕过注入
   直接 import——切分涉及热更 API，单独立项。
3. **FAS_IDENTITY 进认知任务模板**：解析/抽取/反思的 system prompt 带陪伴人设；
   拆分它=改提示词=实验回归，属研究侧决策，刻意未动。
4. **mark_accessed 死路径**：自动晋升 driver 未启用（A4 观测已接线，决策待窗口）。
5. **40% "涉及" fabric 边**：治理方案 design_fabric_governance_A3 待裁决。
6. cc↔autonomy↔action_manager 环形互引、busy 握手——随 process_nlp 迁移一并解决。

## 7. 研究下一步（从台账缺口直接推出，非拍脑袋）

| 优先 | 事项 | 台账依据 |
|---|---|---|
| P0 | 把"陪伴期"观测数据攒起来：真实运行 1–2 周的事件流，为 A2 事件框架生产开启做裁决窗口 | experience_eventframe 默认关、待观测 |
| P1 | 决策头重设计或降级定位：I 实验基线完胜、路由 p 不存活——要么找对表示，要么承认它只配做仲裁 | 台账 §9 failed |
| P1 | 扩散的行为条件补测：唯一正向例外是共享枢纽拓扑，值得一个预注册的行为层 follow-up | 增量 REJECTED + 枢纽 30/30 |
| P2 | episodic 自动晋升 driver 启用 + 前后对照（现在是死路径，启用本身就是新实验） | L1-MEM-01 |
| P2 | self-model v7 差分扩展到 novel 条件（现在 0/5） | REPAIR_TEST_RESULTS |
| P3 | curiosity/reflection/disposition/personality 各补最小对照实验 | 全部 untested |

## 8. 一句话总结

这层现在**能跑、干净、可拆**，但"能跑"不等于"被验证"：
证据最硬的是访问层机制（扩散汇聚、写回隔离、A10 记忆价值），
最软的是行为决策（决策头 failed、self-model 首证脆弱）。
两轨制的意义就在于：陪伴功能照常跑的同时，这些缺口按上表逐个用实验补，
补实一个，就在 `fas/registry.py` 把对应槽位从"借来"改成"FAS 自建+validated"。
