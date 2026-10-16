# 第二阶段交付报告：阅读能力生产接入与闭环修复（2026-10-12）

真实 LLM 调用：**0**（本轮全部离线：artifacts 回放 + 假模型）；正式预算
消耗 0；`memrep.enabled=False`、`reader.enabled=False`（实测默认配置）。

## 1. 修复前真正断裂的调用链（代码证据）

| 环节 | 断裂 | 位置 |
|---|---|---|
| 用户意图→目标 | FILE_READ 概念可理解、无执行器，宿主一律"如实拒绝" | action_concepts.py:234-239；FAS-Companion app.py 原 4322-4328 |
| 文本→抽取→写回 | 唯一抽取管线 graph_expansion 输入=既有节点名非文本、生产零调用、依赖文件不在本仓 | run_graph_expansion.py:70-77 |
| 证据分级 | memrep 来源枚举无"文本陈述"档（text_stated 缺失会降级"未记录"） | memrep.py SOURCES |
| 进度/恢复 | 全仓无来源覆盖记账 | （第一阶段已证，本轮补 API） |
| 缺口→行动 | 缺口节点 id 硬编码"用途"前缀，非 MC 域无法进同一账本 | prior_knowledge.py:225-226（修复前） |
| 抽取可靠性 | 真跑 3/6 失败**全部为输出预算截断**（u1/u5 JSON 半截、u3 可见输出 0）——模型能力与装配均排除 | artifacts_20261012_151130/llm_calls.json |

## 2. 本轮改动（每项一个目的）

FAS-Cognitive：
- `reading.py`：+salvage 解析（只留完整元素、partial 上账、空输出拒收）；
  +make_llm_extractor（有界重试 ≤1、attempt 计数）；+词级匹配器
  （fold 复数、≥4 字母强词、名字叫/同一 别名扩展）；+三态
  `evidence_pack`（sufficient/conflict/insufficient，冲突行并列+不确定
  标注，来源逐行前缀不拼接）；+`progress_report`（证据绑定）；
  +`register_gap`；+`begin_source_text`；+`open_ledger/any_active_reading`
  （sidecar 持久化单元文本，重启可恢复）。
- `memrep.py`：SOURCES += `text_stated`（additive）。
- `prior_knowledge.py`：缺口 `label` 参数（默认"用途"逐位兼容；label 置于
  签名末尾防位置参数错位——中途一次破坏被 test_prior_exploration 抓到并修复）。
- `autonomy.py`：_gap_candidates 只为 label=用途 生成具身候选（阅读缺口走
  drive 张力，不误配 inspect/试做目标）。
- `actions/file_action.py`：+read_file（白名单目录/扩展名、200KB 上限、
  消毒复用）。
- `config.py`：+reader 节（**默认关**）。

FAS-Companion（宿主，运行时未验证，见 §6）：
- `prompt_templates.py`：FILE_ACTION_EXTRACT 支持 read_file；+READER_EXTRACT
  模板并注册 `reader_extract`。
- `app.py`：FILE_READ 分支从拒绝改为真执行 read_file；reader.enabled 时
  读成功即建台账（不自动连读）；新增 reader 回合块——"读到哪了/继续读"
  通用命令模式，每拍至多 1 个抽取单元，进度经 evidence 通道进入回答。
- 两文件 py_compile + 模板加载测试通过。

## 3-4. 生产入口与缺口接入状态

- 入口：FILE_READ→read_file→台账→(继续读→1 单元/拍)→进度/证据经
  file_evidence 通道进 L2——**代码已实现，宿主链路编译通过，未运行验证**。
- 缺口：reading.register_gap → 同一探索缺口 hub（kind=read_gap,
  label=阅读）→ CuriosityDrive 张力真实消费（drive_engine.py:318 读全部
  hub gaps，label 无关，实测数据层锁定）；MC 具身候选正确跳过。

## 5. 证据匹配正反例（26 项测试全绿）

召回：复数（woods↔dark wood fold 命中）、大小写、所有格、别名（名字叫
边，端点需存在——顺带验证 add_edge 语义）、跨单元事实、CJK。
精度：stopword 反例组（"What do I owe you"等三题零命中）、dispatched/
failed 单元永不作来源、inference 不冒充 text_stated、不同来源不拼接、
冲突态双宾语并列呈现。三态均有专测。

## 6. 状态分级（严格不越级）

- 代码已实现：全部 §2。
- 调用链已接通：repo 侧（reading↔memrep↔prior_knowledge↔autonomy 过滤、
  open_ledger↔sidecar 持久化）单测接通；宿主↔repo 为编译+导入级验证，
  **宿主运行时未跑**（需要服务环境，属人工操作）。
- 模拟测试通过：26 项阅读 + 159 全仓 + 7 个独立套件。
- 真实 LLM 行为通过：**本轮 0 调用，未验证**。salvage/重试的证据基础是
  真实失败样本回放（离线），不等于新配置下真跑通过率——待验证项。

## 7. 成本与未验证清单

API 调用 0。待验证：①新提取链路（900 token+salvage+重试）真跑通过率
（预估 ≤6 次调用，独立可选验证，未获授权不跑）；②宿主 reader 块运行
时行为（需起服务）；③冲突态下回答端是否真的并列呈不确定（依赖 LLM）。

## 7b. 真实验证结果（人工批准后执行，10 调用 ≤14 预算；
`verify2_20261012_161950/`）

与宿主完全同构：system=宿主 READER_EXTRACT 模板、human=make_llm_extractor
提示（即 nlp.ask 语义）、temperature=0、max_tokens=900。

| 项 | 上一轮基线 | 本轮 |
|---|---|---|
| Inferno 前 6 单元 | 3 confirmed / **3 failed（预算截断）** | **6/6 confirmed，0 partial，0 失败** |
| 读后问答（开篇位置） | INSUFFICIENT（unit1 未入库） | state=sufficient，答 **"In a darksome wood."**（与原文一致——写回→检索→使用全链真实打通） |
| Cato 未知探针 | 旧 matcher 误判有证据 | state=**insufficient** → 缺口注册成功（不编造） |
| 冲突扫描 | 空（数据不足） | 真实报出 Dante-位于-多宾语（黑森林→山丘的行进被标为待消解冲突——诚实的保守行为，时序消解属下一阶段） |
| Alice 跨语料 | 2/2 抽取失败 | **2/2 confirmed**，问答 sufficient，答 "河岸（river bank）" |

结论升级：抽取链路与"写回→检索→回答"达到**真实 LLM 行为通过**级；
仍未验证的只剩宿主 app.py 服务内运行时（块逻辑与本轮同构，属装配
验证而非能力验证）。

## 8. 下一步最值得投入

真跑复验抽取链路（6 次调用、单问题：新预算+salvage 下 8 单元通过率与
partial 比例），然后宿主 reader 块一次端到端会话验证（读一个真实 txt→
继续读→问进度）。两者都不通过前，"Haru 能追踪式读书"只到
"机制+模拟验证"层级。
