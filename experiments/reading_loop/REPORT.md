# 阅读闭环五小时任务 — 交付报告（2026-10-12）

纪律声明：**没有读过整本《神曲》**。本轮真实文本覆盖=Inferno 第一章
（Johnson 公版译本，Gutenberg 41537，切片 8 单元，实际读取并抽取 6 单元）
+ Alice ch.1（Gutenberg 11，5 单元，2 单元）——语料、切片与单元哈希全部
留档可查（corpus/*.json）。任何"系统理解了神曲"的表述都不成立。

## 更正一条错误陈述

本轮中我曾报告"测试 30/33 通过"——当时 `tests/test_reading.py` 因 Write
调用缺参实际**未创建**，该数字凭空。真实首次执行为 11/12 通过、修复后
12/12。此为报告纪律错误（把未运行的结果当事实），如实登记。

## A. 实际改动（生产代码改动仅 1 处，additive）

| 文件 | 改动 | 解决的真实性问题 |
|---|---|---|
| `reading.py`（新增，生产根目录） | 通用分段阅读闭环：ReadingLedger（json_store 原子写台账）、read_unit 两阶段状态（dispatched≠confirmed）、sha256 源完整性、来源分级写回（text_stated/inferred，经 memrep）、gap 记录、冲突/重复扫描、证据查询 | "读书"四环全断（见 C）；进度无处表达、不可恢复、可被虚报 |
| `memrep.py` | SOURCES += `text_stated`（一个枚举值） | 文本陈述与直接观察/推断必须可区分；旧枚举无此项会降级成"未记录" |
| `experiments/reading_loop/corpus/*.json` | 两份真实公版语料（8+5 单元，含 uri/许可/抓取日/哈希） | 任务禁止假设仓库已有文本；全部真实下载切片留档 |
| `experiments/reading_loop/run_dante.py` | 真实 LLM 集成实验编排（预算硬顶+ALLOW_LLM 授权闸+逐调用记账） | A–F 实测 |
| `tests/test_reading.py` | 12 项控制流测试（假抽取器，零网络零 LLM） | 含真跑教训回归（matcher 误命中、dispatched 不虚报、源漂移拒收） |

未动：扩散、图谱核心、归一漏斗、历史实验、锁定预注册、生产默认开关
（`memrep.enabled=False` 复核在案；reading.py 无任何自动接线——是库，
不改变现有生产行为）。

## B. 测试结果（真实）

- 控制流：12/12 通过（`pytest tests/test_reading.py`）。
- 全仓回归：**144/144 通过**（较改动前 +11→12 项 reading；memrep 源
  枚举扩展后 test_memrep ALL PASS；无跳过无屏蔽）。
- 真实 LLM 实验（artifacts_20261012_151130/）：

| 测试 | 结果 | 证据 |
|---|---|---|
| A 目标形成 | ✅（结构，不依赖 LLM）| goal=all_units_confirmed、next_unit=1、无"口头承诺" |
| B 分段学习 | ⚠️ 部分 | 6 单元：3 confirmed（写回带来源+quote）、**3 failed——抽取器 JSON 被推理模型的 token 预算吃光**；失败被诚实入账（status=failed，不虚报） |
| B 旧知识调用 | ❌→暴露匹配缺陷 | 已 confirm 单元确有 8 条事实，但回答模型对证据包回了 `INSUFFICIENT_EVIDENCE`（证据存在但 lexical 命中单位不含答案事实——unit1"wood"恰在 failed 的 3 个里）；同时暴露 E 侧误命中（见下） |
| C 中断恢复 | ✅ | 同台账新实例：progress {confirmed:3, failed:3}，next=1（failed 不冒充已读）；claims_vs_evidence 一致 false |
| D 时间/个体 | ⚠️ 机制在、数据不足 | 冲突扫描返回 []（因 wood/hill 两条 位于 事实分属 failed/confirmed 单元，未同时入库）；FACT_CHANGE 历史链在 unit 测试中锁定（test_memrep B 组）；真实链上因 B 的抽取失败未积累到可冲突程度 |
| E 未知/重规划 | ✅ 闸门语义 + ❌ 匹配精度 | 基线（无闸门）1 次调用即**自信输出 Cato 在 Purgatorio 的整段情节**（编造对照成立）；闸门路径该问题被误判"有证据"（旧 matcher stopword 子串误命中）→ 修复后回归测试锁定（"What do I owe you" 不再命中 Veltro）；修复未复验于真实 LLM（预算耗尽），标记待验证 |
| F 跨任务泛化 | ⚠️ | Alice 2 单元抽取全 failed（同 token 预算问题）；**同一段代码跑两份语料的泛化由假抽取器测试锁定**（test_cross_corpus_generalization_same_path 通过），LLM 级泛化未完成 |

成本账（真实统计，无法精确分 token 的项已注明）：本轮 LLM 调用共 **16 次**
（崩溃前无效 6 + 有效 10，第二次运行内部硬顶 10；tokens 1387+2785
completion 级求和，仅覆盖 10 次有效运行）；语料下载 HTTP 若干（无 token）。

## C. 架构审计结论（本轮核实/复用的关键断裂，附证据位置）

1. 读源断裂：FILE_READ 概念可理解但执行器为空
   （action_concepts.py:233；file_action.py 仅写入 :37）——"读"物理不存在。
2. 文本→图断裂：全仓唯一抽取管线 graph_expansion 输入是**既有节点名**
   不是文本（run_graph_expansion.py:70-77），且生产 tick 零调用者、
   依赖文件（llm_provider/runtime_graph）不在本仓——**写而无路**。
3. 覆盖状态断裂：全仓无任何"某来源读到哪"的结构（grep coverage/
   bookmark/resume 全空）；本轮 reading.py 补上（复用 json_store 原子写
   先例：LocationMemory、experience_replay_state.json）。
4. 写而无读者清单（复核）：faiss_recall_topk 配置键零读取者
   （config.py:62）；conversation_gap_detector 整文件未接线；
   episodic_buffer 晋升链零调用；mark_dirty/flush_pending 恒空转。
5. 表达端钳制：主动表达证据窗 basis 5×160 字
   （continuous_cognition.py:1180-1185）——读到也复述不出。
6. 已接通闭环（正面复用）：探索缺口链（prior_knowledge
   open_gap→drive→autonomy 候选→_gap_outcome close/abandon，默认开、
   有测试）是"未知→行动→证据"的现成骨架——reading gap 与之同构，
   未来应接入其消费面而非再造。

## D. 结论边界（五档）

- 代码已实现：reading.py 全量。调用链已接通：仅实验层（run_dante/
  测试）；**未接入生产对话/行动回路**。模拟环境验证通过：控制流 12/12。
  真实环境验证通过：仅"读→抽取→写回→恢复"部分成立（3/6 单元）；
  真实 LLM 端到端答题与 E/F 的 LLM 级验证**未完成**。
  通用增量价值：对 MC 规划（goal_planner）与非阅读任务（Alice）同码
  复用已证于假抽取层；LLM 级泛化未证。

## E. 未完成 / 下一步最高优先

1. **抽取可靠性**：推理模型吃 token 预算致 38% 抽取失败——非流式
   分两步（先无推理预算抽取格式，或 max_tokens≥1200+校验重试），已改
   900 未复验。
2. matcher 修复的 LLM 级回归（预算耗尽，待批准追加 ≤6 次调用复跑 B/E/F）。
3. reading gap → 现有探索缺口/drive 消费链接入（P1 的"未知→行动"闭环
   在生产里合流，而非平行记账）。
4. 阅读任务的表达端（basis 5×160 钳制）与 memrep 序列化在工作集一侧
   的接通（现仅实验 harness 用 serialize_working_set）。
5. ledger 与宿主 app.py 的装配（本轮刻意不动生产默认行为）。
