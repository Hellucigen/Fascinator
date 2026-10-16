# Cross-Episode MEMREP Phase-3 启动前审计（只读，2026-10-12）

审计方式：纯只读（git/cat/grep/pytest 假调用器重跑）。零 LLM 调用、零预算
消耗、零文件修改、零 git 操作。

## 1. 最终结论

**A——可以申请启动授权**（仅此而已；不构成启动授权本身）。
12 项准入全部复核通过；唯一需人工在批准启动时一并确认的事项：
重试口径的意图确认（见 §2，判定为字面合规、非阻塞）。

## 2. 重试规则裁决

| 源 | 位置 | 原文 |
|---|---|---|
| ① 锁定预注册 v3.1 | PREREGISTRATION.md:183（§6） | "上限 210 次成功调用（7 臂×30）+ **每调用 ≤3 次指数退避重试**" |
| ② 最终审核记录 | RECOMB_REPL_FINAL_REVIEW §7 第 9 项 | "210 调用上限、每调用 ≤3 重试…"（复述，未裁决尝试口径） |
| ③ Harness | harness.py:57 `MAX_RETRIES=3`、:294 `range(1 + max_retries)` | 初始 1 + ≤3 重试 = **至多 4 次尝试** |
| ④ 原 LLMHead | 父仓 run_exp_routing_v2.py:90 `for attempt in range(3)` | **3 次总尝试** |

**裁决**：①是唯一锁定规则源。"重试"的标准语义=失败后的再次尝试，不含
初始调用 ⇒ "每调用 ≤3 次重试"唯一确定地为"初始+≤3 重试=≤4 次尝试"，
③合规；④是被替代的旧实现，不属于锁定规则集，不能推翻①。
依据裁决原则第一条（预注册明确写重试语义 → 字面合规）。
**残余事项（非阻塞）**：若任务所有者的真实意图是"3 次总尝试"，改动仅为
harness.py:57 `MAX_RETRIES=2` 一行——请在批准启动时一并确认口径。

**预算计数核对**：210 上限按**成功调用**计（BudgetTracker.register_success
超限即 raise，harness.py:254-258；调用前双闸 can_call：run_all:455 与
run_single:377）；尝试/重试/无效分别计数、不入成功上限；重试不消耗成功
预算但计入 attempts（可审计）。无并发路径（单进程顺序编排）。

## 3. 12 项准入复核表（对照当前代码与测试）

| # | 项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 锁定 commit/工作区 | 通过 | HEAD=dc8d677（`git cat-file -t` 确认为 commit）；`git diff dc8d677 -- PREREGISTRATION.md` 为空=与锁定版逐字节一致；harness 4 文件为未跟踪新文件 |
| 2 | 生产开关关闭 | 通过 | config.py:1935 实测 `enabled: False`；测试断言 run 级 memrep_switch=False |
| 3 | 实验隔离 | 通过 | harness 内 kg.save 禁用、全内存图；测试无生产写入；openai 惰性导入（harness.py:266，模块导入不触网） |
| 4 | 7 臂一致 | 通过 | LOCKED_ARMS 锁定表+verify_arms 硬失败（test_verify_arms_*）；A6/A7 仅描述性（统计对比族只含 H1-H4） |
| 5 | 配置快照 | 通过 | cfg_snapshot（臂表/图哈希/commit/开关/重试）+ 每 run 20 字段（test_row_traceability_fields） |
| 6 | R2 无泄漏 | 通过（审计范围：静态数据流） | r2_ignition_ids(kg) 仅从图节点取全集（=13 事件，test 断言）、签名无问题参数；ids/memrep 序列化只读图与 topk；gold 仅出现在评分与事后诊断。**范围声明**：静态代码路径级审计，未做动态污点分析 |
| 7 | A4 哈希断言 | 通过 | 全 6 题 ctx 字节相等（test）+ 全编排 30 对哈希相等（test_full_orchestration）+ 不一致 raise（test_a4_hash_mismatch_raises）。哈希在 ctx 层；完整 prompt=同模板+同问题 ⇒ 逐字节相等可推导。**区分**：输入构造确定性已证；模型输出确定性属运行期观测，未证 |
| 8 | 逐 run 可追溯 | 通过 | 20 字段断言 + raw_runs.jsonl 落盘 |
| 9 | 预算与重试 | 通过（附 §2 残余事项） | test_budget_cap_blocks_and_raises、test_run_all_budget_exhaustion_stops_everything（恰在第 5 次成功停止）、test_retry_* |
| 10 | 无提前停止 | 通过 | 编排循环无结果分支（grep 核验）；仅预算耗尽与无效臂暂停（预注册 §6 规则） |
| 11 | 探索性边界 | 通过 | generate_report 定位字段强制"探索性"；holm_note 恒不可拒绝声明；测试断言 |
| 12 | 其余锁定要求 | 通过 | 评分器逐字移植、三分类（test_*_classified）、N 规则（test_delta_c_*、test_N0_*）、多数票平票（test_majority_*）、error 字段保留（test_*_classified）、日志失败传播（test_log_write_failure_propagates） |

## 4. 测试证据可信度

- 本轮**重跑并绑定当前代码**：harness 33/33、全仓 133/133，零跳过
  （pytest 输出见对话记录；无 mock 掩盖关键路径：A4 断言、预算、
  重试、不可判定均为真实控制流+故障注入）。
- 测试零网络：openai 仅惰性导入；A7 嵌入在测试中 monkeypatch。
- 纯本地重跑结论可与当前工作树绑定（harness 文件未提交——提交与否
  由任务所有者决定，不影响测试绑定关系）。

## 5. 剩余风险（仅列影响合规/可复现/解释的实际项）

1. 重试口径：字面合规已裁定，但若所有者意图为 3 次总尝试，启动前一行
   修改（MAX_RETRIES=2）——需在批准时确认。
2. 预算计数为内存态：进程重启即清零。预注册未要求持久化；边界=
   正式运行须单进程一次完成 210 成功调用，中断重启需人工登记已消耗额。
3. R2 泄漏审计为静态数据流级（未做动态污点分析）。
4. 模型输出确定性未证（A4 断言只保证输入确定）——运行期若 A4 答案
   分歧，按预登记规则记录为 LLM 非确定性实测。
5. harness 4 文件未提交：正式运行前建议提交以绑定代码版本（任务所有者决定）。

## 6. 下一步最小动作

1. 人工确认重试口径（4 次尝试 vs 3 次总尝试）。
2. 人工批准启动 Phase-3（单独明确批准；本报告不构成授权）。
3. （建议）提交 harness 文件以绑定代码版本。

## 7. 安全状态

本轮：真实 LLM 调用 **0**；正式预算消耗 **0**；生产代码修改 **0**；
预注册修改 **0**；git 提交/重置/清理 **0**。
