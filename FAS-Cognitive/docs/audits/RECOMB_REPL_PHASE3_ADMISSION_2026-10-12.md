# Cross-Episode MEMREP Phase-3 Harness — 准入审计（2026-10-12）

依据：PREREGISTRATION.md v3.1（锁定 commit `dc8d6773db6ed652d6a18d2a53b45f319b4d9306`）、
RECOMB_REPL_FINAL_REVIEW_2026-10-12.md §7 准入清单。本轮零 LLM 调用、零预算消耗。

## A. 实现摘要

| 文件 | 职责 | 预注册对应 |
|---|---|---|
| `experiments/.../harness.py`（新增） | 7 臂锁定配置+verify_arms 硬校验、图加载/哈希、忠实/R2 激活域、旧 ids 序列化（原格式逐字复刻，含 Relations 段）、memrep 序列化、BudgetTracker（成功≤210 硬限，尝试/重试/成功/无效分计）、call_with_retry（初始+≤3 重试，backoff 2/4/6s 可注入）、A4 输入哈希断言（不一致即 raise）、逐 run JSONL 记录、A/B/C/D 四阶段诊断、memrep 开关记录 | §1 条件表、§3.1、§5、§6 |
| `experiments/.../scoring.py`（新增） | PROMPT 与 check_answer **逐字移植**（源 run_llm.py:20-31/83-96，diff 可审计），exact_success 二元 | §3 评分器复用 |
| `experiments/.../stats.py`（新增） | 多数票/不可判定规则、有效题目集合 N、Δ/C、联合探索性信号、精确符号检验（参考）、Holm 附报（注明恒不可拒绝）、CP 方向比例区间、各臂 run 级 Wilson、种子不一致率、基础设施失败率三分类、generate_report | §3 统计设计全部条目 |
| `tests/test_recomb_harness.py`（新增） | 33 项验收测试（纯本地假调用器） | §5.1/§5.2 |

未修改：生产代码、评分器判定逻辑、历史实验、锁定预注册、他人未提交改动。

## B. 测试结果

- 本套件：**33 通过 / 0 失败 / 0 跳过**（`pytest tests/test_recomb_harness.py`）。
- 全仓回归：**133 通过 / 0 失败**（含既有 100 项 + memrep 19 + harness 33
  中重叠计数口径；无回归）。
- 关键故障注入结果：预算耗尽恰在限额处停止（calls==5）；重试耗尽→
  infra_failed + attempts=4 + D 阶段 not_applicable_infra；空回答无异常→
  非基础设施、计 0 分；A4 哈希不一致→ContextMismatchError 硬失败；
  日志写入失败→异常向上传播（不吞）；配置突变→ArmConfigError 硬失败。
- 真实编排演练（假调用器）：210 run 全流程完成，A2/A4 全 30 对上下文
  哈希一致，统计报告可生成且含探索性定位与 holm_note。

## C. 12 项准入清单

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| 1 | 锁定 commit 与工作区状态 | **通过** | 任务开始实测 HEAD=dc8d677；工作区他人改动保持原样（git status 快照见对话记录） |
| 2 | 生产 MEMREP 开关关闭 | **通过** | config.py:1935 `enabled: False`（本轮实测）；逐 run 记录 `memrep_switch=False`（test_memrep_switch_recorded_false） |
| 3 | 实验隔离 | **通过** | harness 内 kg.save 被禁用、全内存图；不触 data/runtime_graph.json；测试零生产写入 |
| 4 | 7 臂与预注册一致 | **通过** | LOCKED_ARMS 表 + verify_arms 硬校验（test_verify_arms_*） |
| 5 | 配置及版本快照 | **通过** | cfg_snapshot（臂表/图哈希/commit/memrep 开关/重试参数）+ 每 run arm_config/graph_hash/code_commit 字段（test_row_traceability_fields） |
| 6 | R2 无答案泄漏 | **通过** | r2_ignition_ids=全部 13 事件节点固定全集、签名无问题参数（test_r2_ignition_*、test_r2_builders_take_no_gold_arguments） |
| 7 | A4 哈希断言 | **通过** | run_single 硬断言（test_a4_hash_mismatch_raises）+ 全 6 题×字节相等（test_a2_a4_context_bytes_identical_all_questions）+ 全编排 30 对哈希相等 |
| 8 | 逐 run 可追溯 | **通过** | 20 个追溯字段断言（test_row_traceability_fields）；raw_runs.jsonl 逐行留档 |
| 9 | 预算与重试规则 | **通过**（含一项解释声明） | 预算测试（test_budget_cap_blocks_and_raises、test_run_all_budget_exhaustion_stops_everything）；重试测试（test_retry_*）。**解释声明**：预注册"每调用 ≤3 次重试"按字面实现=初始+3 重试=至多 4 次尝试（backoff 2/4/6s），与原 LLMHead 的 3 次总尝试不同，已登记 |
| 10 | 无提前停止 | **通过** | run_all 无任何基于结果的停止分支；仅预算耗尽（预注册 §6）与无效臂暂停（§6 规则） |
| 11 | 探索性结论边界 | **通过** | generate_report positioning 字段强制含"探索性"；holm_note 恒不可拒绝声明；§7 措辞规则在统计模块注释与报告物中固化 |
| 12 | 其余锁定审核要求 | **通过** | 评分器逐字移植（scoring.py）；三分类（test_*_classified）；端到端度量与 N 规则（test_delta_c_*、test_N0_*、test_majority_*） |

## D. 预算与安全证明

- 是否调用真实 LLM：**否**（全部测试用 ScriptCaller/Fake；OpenAICaller
  仅惰性定义，测试中从未实例化）。
- 正式实验预算消耗：**0**（210 上限未动）。
- 生产开关：`memrep.enabled=False`（实测）；`goal_path`/`planner`/
  `experience_eventframe` 亦均为 False。
- 是否修改生产代码：**否**（本轮仅新增实验目录文件与测试文件）。
- 是否触碰历史数据：**否**（cross_episode_recomb/ 原档只读）。
- 他人工作区改动：**原样保留**（未 add、未还原、未提交）。

## E. 最终结论

**1. Harness 实现完成，准入检查全部通过，等待人工批准启动 Phase-3。**

附带声明：①重试次数按锁定文本字面义实现（初始+3 重试），与原 LLMHead
不同，已登记；②A7 的嵌入检索在测试中以 monkeypatch 验证编排（真实嵌入
模型已于 2026-10-09 独立实测可用）；③正式运行前还需人工确认执行预算
与密钥可用性（data/llm_secret.json 在父仓）。
