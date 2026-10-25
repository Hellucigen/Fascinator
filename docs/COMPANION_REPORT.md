# FAS-Companion 陪伴层报告

日期：2026-10-08 · 基线：拆仓首 commit（66bd2e7）· 上游文档：`FAS-Cognitive/docs/ARCHITECTURE_AUDIT.md`、`ARCHITECTURE_PLAN.md`、`COGNITIVE_MODULE_STATUS.md`

---

## 1. 定位与边界

FAS-Companion 是两轨制中的**陪伴层**：目标是"现在就能陪用户"，允许一切成熟外部
方案作为**临时实现**存在。三条硬边界：

1. **依赖单向**：Companion → Cognitive。本仓通过 app.py 头部 bootstrap 找同级仓
   `FAS-Cognitive`（或环境变量 `FAS_COG_ROOT`）；认知仓不 import 本仓任何模块
   （由 `fas/core` 纯度测试守护）。
2. **不反向污染**：陪伴不得直写认知内部状态（kg._lock / activation / mark_active）。
   新代码一律经 `CognitiveCore.perceive/record_memory/propose_action`；存量违例见 §7。
3. **不假装能力**：FAS 自有语言机制仍是研究问题（NOT_IMPLEMENTED）。本层只解决
   "能自然交流"；`prompt_templates.py:277` 明文禁止预设说话风格，全仓无台词库，
   唯一 persona 硬编码是 `FAS_IDENTITY` 身份声明（21–29 行）。

## 2. 现在实际具备的能力

| 能力 | 状态 | 实现路径（本仓内） |
|---|---|---|
| 对话聊天 | ✅ 可用 | `POST /api/nlp`（app.py:3025 起，约 2350 行回合主管道）：解析→激活扩散→沉默决策→语言实现→应答 |
| 先行动后说话 | ✅ 可用 | 反射快路径（游戏命令"过来/跟着"零 LLM 直达 ActionManager），回复受发言提纲 `must/must_not` 硬约束（动作没做完不许说做完了） |
| 主动消息 | ✅ 可用 | 认知仓 `ContinuousCognition._express` 产话语 → Charon 生产侧投递（气泡/SPEAK/便签）；2026-10-09 补：NO_SPEAK 沉默哨兵（来源无具体话题时不硬凑"我不知道说啥"，CI 终态不重试）+ inbox 快照过滤 haru 回声便签 + 好奇驱动自发上网检索（`_curiosity_web_explorer`，带相关性闸） |
| 记忆经历 | ⚠️ 半自研 | 对话日志 `chat_log.py`（图谱外 JSON，回读进认知上下文）；记忆抽取 = LLM MEMORY_EXTRACT 临时通道，写回 KG 属认知仓 |
| 游戏陪伴 | ✅ 可用 | `minecraft/`（mineflayer 子进程 + HTTP 桥，bot 名 Haru/offline）；通道消息经 ChannelHub 回环 `/api/nlp`（app.py `_channel_turn_runner`） |
| 屏幕/物体/听觉感知 | ⚠️ 手动 | `eye/`（RapidOCR+mss+YOLO）、`vision/`（SAM2 未启用缺 CUDA、DINOv2 已加载）、`ear/`（FunASR Paraformer + emotion2vec + YAMNet）——默认禁用，手动喂样本，实时流缺件 |
| 桌面具身 | ✅ 可用 | `Action/wasd.py`（ctypes 键盘）、`actions/file_action.py`（白名单目录）、语音坐标解析 |
| 多 LLM 热切换 | ✅ 可用 | UI LLM 面板 → `/api/llm/switch`；provider/model 存 `data/llm_config.json`，key 单独存 `data/llm_secret.json`（均 gitignore） |
| Charon 外壳 | ✅ 已接线（2026-10-09） | Charon 托管本进程 + REST 代理全部 163 条路由；FAS→Charon 下行通道 `fas/companion/charon_bridge.py`（17734 token Bridge，utterance/diary/notes）已挂上两个话语出口（`/api/nlp` 回合回复、`/api/proactive/poll` 主动消息），陪伴仓部署默认开（`FAS_CHARON=0`/PUT /api/config 可关）；Charon 实况 config.json `fascinator_app` 已指本仓，前端已上 `EventsOn('fas.utterance')` 气泡（proactive/question 弹泡，reactive 由聊天 UI 承接不重复弹） |

**运行验证（拆仓当日）**：陪伴侧 13 个脚本式测试全过（含离线闭环验收
`test_offline_chain_acceptance`、世界状态 grounding、叙事抽取）；
完整冒烟启动 452 节点新图，认知三触点注入断言全绿。

## 3. 借来的 vs FAS 自己的（验收问题 D 的陪伴侧答案）

| 环节 | 提供者 | 性质 |
|---|---|---|
| **该不该说/做什么** | `dialogue_decision`（零 LLM 行为竞争）、`autonomy`、图谱激活 | **FAS 认知**（但注意：决策头 I 实验 failed、扩散增量价值 REJECTED，状态见认知仓台账） |
| **说什么内容** | 认知状态编译 + 发言提纲 + 图谱 topk | FAS 认知供给 |
| **怎么措辞** | MiMo/DeepSeek/Ollama LLM | **借**（TemporaryLLMBackend，整体可换） |
| **语言理解（输入解析）** | LLM NLP_PARSE/PARSE_FAST | **借** |
| **记忆抽取成三元组** | LLM MEMORY_EXTRACT | **借**（未来 FAS RelationalMemory 替换位） |
| 听（STT） | FunASR/YAMNet 本地模型 | 借 |
| 看（OCR/物体） | RapidOCR/YOLO/SAM2/CLIP | 借 |
| 游戏身体 | mineflayer Node bot | 借（reflex/世界知识入图部分属 FAS） |
| 搜索 | Bing/Baidu HTML 抓取 | 借（临时） |
| 人格/心情措辞层 | `_mood_band` 中文档位词 + mood_context | 表演性底色，无实验验证（untested） |

一句话：**"她为什么不回答/为什么做这件事"是 FAS 的认知；"她的每句话长什么样"目前 100% 是借的。**

## 4. 跨仓契约（本仓实际使用面）

- app.py 装配处创建 `TemporaryLLMBackend(nlp)`，认知模块只拿到
  `CognitiveLanguageAccess` 最小面：**llm / chat_llm / ask / system_prompt** 四成员。
  认知内 LLM 触点：curiosity 提问、reflection 分析、free thought、主动表达。
- 拆仓当日修复：三处认知模块不再直接 `import prompt_templates`
  （模板经 `system_prompt(task)` 取，缺席回退旧直连，逐字等价、行为不变）。
- 换语言方案 = 只换 app.py:754 一个注入对象 + `fas/companion/assembly.py` 一个
  build 分支；认知模块零改动。

## 5. 仓库结构

```
app.py 8609 行 / 163 路由     Flask 单体：回合主管道 + 观测 API（图谱/内稳/自主/通道…）
index.html                    单文件 UI（聊天 + 开发者面板，3s/12s 轮询）
nlp_processor.py 语言编排    llm_provider.py 网关（云端流量物理收口 _create() 一处，
                              fas_log 带 purpose 归因）  ollama_backend.py 可选本地
prompt_templates.py           15 任务模板 + FAS_IDENTITY
api_guard.py                  回环免 token / 非回环 token / Origin 核验 / 执行写闸门
chat_log_replay.py            空图事故恢复工具（安全规则：只回放 user_input）
ear/ eye/ vision/             感知外设（手动样本；写图路径属存量违例）
tools/analyze_logs.py         日志分析（--trace/--cycle/--llm）
data/（gitignore）            llm_config.json·llm_secret.json·chat_log.json·runtime_graph.json…
tests/ scripts/               陪伴侧脚本式测试与实验脚本（bootstrap 自动挂认知仓路径）
```

本地 `E:\Project\Fascinator` 保留为开发档案（历史 `.git` + 原始数据），不再是运行目标。

## 6. 安全与隐私现状

- **密钥**：`api_key` 永不写入 llm_config.json（存 llm_secret.json）；两文件均在
  `.gitignore`（`data/*` + 显式排除清单，clone 首 commit 时验证过 stage 里只有 example）。
  默认配置 `api_token: ""`：本机零摩擦，非回环访问自动签发 token。
- **对话数据**：chat_log/runtime_graph/internal_state 等全部 data/ 下，不入库。
- **发布消毒**：prompt 示例中的真实校名→通用示例（其余 26 文件令牌置换）；
  图谱导出快照、运行日志、个人经历词未进仓；扫描闸门命中即中止。
- ⚠️ 待办：曾用于 CI 操作的 GitHub fine-grained token 在聊天中明文出现过一次，
  **应已撤销重发**（见主对话）。

## 7. 已知债务（陪伴侧登记，均不影响当前可用性）

1. `process_nlp` ~2350 行单体未迁移——契约化目标形态已有（`fas/companion/pipeline.py::run_turn`），
   逐段迁移每步用 fas_log 差分对拍。
2. 存量直写图违例：`eye/screen_ocr.py:322–353`、`vision/vision_graph_bridge.py`、
   `minecraft/perception`、`mc_knowledge`（认知仓内）等未走 `core.record_memory/perceive`。
   `MemoryEvent` 需先补 frame/edge_type 字段再收口。
3. `FAS_IDENTITY` 前置进认知任务模板（解析/抽取/反思也带人设）——拆分它需要提示词
   回归，属研究侧决策（架构计划 §6.4），刻意未动。
4. 回合↔后台 busy 握手、`app.test_client()` 通道回环、config 单文件双侧共享：
   拆分遗留，迁移 process_nlp 时一并解决。
5. `mark_accessed` 死路径（认知侧修复项，与本层无关）。

## 8. 缺件与下一步

| 优先 | 事项 | 说明 |
|---|---|---|
| P0 | 真实日常跑通 | 把 FAS-Companion 当主运行环境跑 1–2 周（Charon fascinator_app 已指过来），确认陪伴体验无回归 |
| ~~P1~~ | ~~Charon 前端监听~~ | ✅ 2026-10-09 已完成：`EventsOn('fas.utterance')` 气泡组件（Charon App.tsx），exe 已重编 |
| P1 | TTS 选型 | Web Speech API（零依赖）或本地模型；输出通道走 ExpressionChannel |
| P2 | STT 实时流 | ear/ 现只手动喂文件；需麦克风采集 + VAD |
| P2 | 搜索 API | 替换 HTML 抓取 |
| P3 | process_nlp 迁移 | 按 §7.1 逐段切到 façade |
