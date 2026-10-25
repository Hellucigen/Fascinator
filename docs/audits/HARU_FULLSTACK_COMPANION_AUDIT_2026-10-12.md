# Haru 全技术栈能力盘点与下一代多模态陪伴系统改造规划（2026-10-12）

> 状态：v0.9 初稿。代码审计、硬件实测、认知监测阶段发现、以及上一轮已核实的行业调研（SillyTavern/Letta/Mem0/Graphiti/OpenClaw/Open-LLM-VTuber/主动对话研究）已并入；
> 三路新调研（虚拟形象、语音栈、屏幕/游戏/桌面自动化）均已返回并整合进 §4–§7。调研环境 github.com/huggingface.co/GitHub API/Wayback 不可达，实际验证改走 raw.githubusercontent / jsDelivr / PyPI JSON / hf-mirror / modeldocs 官方站；文中数字均按**官方 / 估计 / 实测**三级标注，无标注的估计值需期 2 实机复核。
> 环境实测：Windows，RTX 4070 Laptop **8GB**（当前占用 1.3GB），32GB RAM。审计时生产进程未运行（5000/17734 无监听）。

---

## 1. 一页式结论

**Haru 现在是一个"有后台生活、没有身体"的陪伴**：大脑（认知图谱+对话主管道）与神经系统（主动表达、生活循环、桌面壳 Charon）都是真实运行的，但她**看不见（无持续屏幕感知）、听不见（语音管线默认关且无实时流）、说不出话（零 TTS）、没有脸（无虚拟形象）、不能坐在你旁边看你打游戏（游戏陪伴只有 Minecraft 一条腿）**。

**改造主线**：不是把认知架构做复杂，而是**给她接上身体**——一个统一的事件驱动 I/O 层（麦克风/扬声器/屏幕/游戏/热键）+ 一个低成本的视觉存在感（形象层）+ 一条可打断的实时语音链路。认知侧降级为可选能力提供方。

**第一件该做的事**（垂直切片，体验收益最大）：
**热键说话 → 本地 ASR → 现有对话主管道 → 本地 TTS 出声 → 可随时打断** ——这一条链跑通，Haru 从"聊天窗口里的程序"变成"房间里的存在"。其余（形象、屏幕、游戏）都挂在这条事件总线上增量扩展。

## 2. 当前技术栈完整盘点（含证据）

### 2.1 输入
| 能力 | 状态 | 证据 |
|---|---|---|
| 文本（网页聊天） | ✅ 真实运行 | index.html（128 个前端函数），/api/nlp |
| 文本（Charon SPEAK 页） | ✅ 真实运行（今晚全链验证） | social_decider→气泡/SPEAK/便签 |
| 文本（Minecraft 游戏内聊天） | ⚠️ 已实现未连接 | channel_hub，minecraft_chat available=false |
| **麦克风实时流** | ❌ 无。ear/ 有完整 FunASR 管线但 `_enabled=False`、手动喂文件、无 VAD、无流式 | ear/ear_processor.py:55；/api/ear/process |
| 热键/系统事件 | ❌ 无（全仓无 hotkey/tray/foreground 代码） | grep 零命中 |
| 屏幕（授权观察） | ⚠️ 手动截屏 OCR 已实现（RapidOCR+YOLO→图谱），无持续/按需观察、无窗口上下文（UIA 未用） | /api/eye/capture，eye/screen_ocr.py |
| 摄像头 | ❌ pose.py 存在但依赖注释未接 | requirements.txt |

### 2.2 输出
| 能力 | 状态 | 证据 |
|---|---|---|
| 文本回复 | ✅ | 主管道 |
| 桌面气泡/便签/播报候选 | ✅（Charon，今晚验证） | living_loop→share_candidate |
| **语音合成** | ❌ **完全不存在** | 全仓 grep 零命中 |
| 虚拟形象/表情/口型 | ❌ 无 | — |
| 游戏内行动 | ⚠️ MC bot 完整工具链（mineflayer/bridge/反思）但需手动连服 | app.py:1306-1358，cognitive/minecraft/ |
| 桌面操作 | ⚠️ 有 Action/wasd.py(ctypes键盘)+file_action(白名单) 原语，无编排层 | 拆仓报告 §2 |

### 2.3 运行时与集成
| 能力 | 状态 | 证据 |
|---|---|---|
| 桌面壳 | ✅ Charon（Wails）：进程托管/REST 代理/收养语义/气泡/SPEAK | v3.4 交付 |
| 后台自主运行 | ✅ 生活循环 daemon（600s 心跳+缺口驱动+预算+账本恢复） | living_ledger 首个完整生命周期 |
| 配置持久化 | ❌ PUT 热改重启即丢 | 10-11/10-12 两次实锤 |
| 消息幂等 | ❌ 无去重表 | grep 零命中 |
| LLM 路由 | ⚠️ 单供应商 MiMo+ollama 可选，无 failover | llm_provider.py |
| 本地模型 | bge-small（常驻 1.3GB 显存）；FunASR/YOLO/DINOv2 零件在库中基本停用 | requirements/实测 |
| 托盘/自启/单实例 | ❌ 全无（单实例仅靠端口冲突） | — |

## 3. 认知监测阶段（v3.4）发现——已并入本规划

1. ✅ 生活循环首个完整生命周期真实跑通：`life_1791732282`（搞清楚「冯诺依曼代数熵」）→3 次真实网络调用→found→done→分享候选登记。**后台自主活动机制成立**。
2. ⚠️ **首个"发现"是误报**：查询改写带引号残留（`数熵」`）+相关性检查过宽→"数"字字典页被判相关。**质量门不足，此类候选绝不能发**——多模态化后此问题会放大（对着垃圾证据说话比沉默更伤信任）。
3. ⚠️ 每日预算计数未接线（daily 恒空）；flag 热开/热停已修好并验证。
4. 内省独白问题（10/10 自由思考产物无行动价值）与"缺口只在陪伴侧缺层"的判断，见同日 COMPANION_HUMANLIKE_GAP_AUDIT。

## 4. 行业技术亮点（三路调研全部返回；数字按官方/估计/实测标注）

### 4.1 已核实（上一轮调研，链接/许可证均实测确认）
- **Open-LLM-VTuber**（MIT）：事件总线+可取消 asyncio task 实现**语音打断**（`[Interrupted by user]` 写入记忆）；主动话语带 `skip_memory` 元数据；**display_text 与 tts_text 双轨**（说的≠想的）。→ Haru 实时链路与主动消息防污染的蓝本。
- **OpenClaw**：心跳完整 agent 轮+**NO_REPLY 显式沉默协议**+activeHours+忙时推迟+flood guard（30s 间隔/60s 5 次）+投递三模式。→ 主动交互产品化范式（living_loop 已同构，缺用户控制面）。
- **SillyTavern**：递归摘要链+向量 RAG 召回旧经历+generate_interceptor 输出整形。→ 连续性与输出质量门。
- **Letta core memory blocks**：小而常驻可编辑身份块，**编辑工具只挂后台进程**。→ 人格层的正确形态。
- **主动对话实证**：CHI 2025（arXiv:2410.04596）主动发言增益取决于与用户当前上下文关联；arXiv:1712.07120 预测无人响应则不发。**红线**：Replika 系列审计（arXiv:2606.04431 等）——主动性不得以留存为目标。

### 4.2 虚拟形象层（✅ 已核实，来源实测抓取；github 直连间歇超时改用 raw/官网/文档站）
- **Neuro SDK**（VedalAI/neuro-sdk，MIT）：**不是 Neuro 本体**——是官方"让 Neuro 玩游戏"的 WebSocket 协议+Unity/Godot SDK+社区多语言实现；AI 核心不开源。对 Haru 适配度低，仅借鉴"协议化角色接入"思路。
- **VTube Studio API**（DenchiSoft/VTubeStudio 文档 MIT）：`ws://localhost:8001`+token 授权；热键/模型移动/自定义参数注入（≥1Hz，可喂口型表情）/事件订阅；Python 客户端 pyvts、coovts 存在。VTS 本体 Steam 付费、企业需商业许可。**封装即得渲染零成本**，但产品被外部进程绑架。
- **Live2D Cubism**：SDK 开发免费、发布需签 Publication License；**官方条款明确 "Expandable Application"（含 AI/chatbot 界面）不豁免**——Haru 属此类，费用需联系（缺口）。社区渲染：**pixi-live2d-display**（guansss，MIT，v0.4.0，Cubism 2/3/4，维护活跃度存疑）；**Wails webview 天然可跑**——与 Haru 现有桌面壳直接契合。
- **透明置顶+点击穿透小窗**的成熟先例：Open-LLM-VTuber（桌面宠物模式：透明/置顶/穿透/可拖拽，README 核实）与 **AIRI**（moeru-ai/airi，Electron，Live2D+VRM，自述开源复刻 Neuro-sama）。
- **口型**：Rhubarb Lip Sync（MIT，wav→viseme 时间轴 JSON，离线）适合"每句 TTS 预生成嘴型"；实时路线=Python 算 TTS 音频 RMS→IPC 写 MouthParam（或 VTS InjectParameterData）。
- **情绪→动作状态驱动**：Open-LLM-VTuber 的 **emotionMap 协议**（LLM 输出内嵌 `[anger]` 标签→表情索引映射，仅 Cubism 3-5）——真实可抄的实现，且天然满足"动作由行为状态驱动而非随机"。
- **VRM**（pixiv/three-vrm MIT 活跃）：3D 表现力上限高，但小窗 2D 场景管线成本不划算（估计）。

**形象层选型结论**：主推 **Live2D 桌面小窗（Wails webview + pixi-live2d-display + OVT 的 emotionMap 标签协议 + TTS 振幅口型）**；并行备选封装 VTube Studio（pyvts）；MVP 可先"静态立绘+表情切换"（成本约 1/10，估计）。风险：Live2D 商用条款需确认、模型资产需购买并遵守厂商 License。

### 4.3 屏幕感知 / 游戏陪伴 / 桌面自动化（✅ 已核实部分；GitHub/HF/F4SE 站不可达项已标注"待二次核实"）

**屏幕与窗口上下文**：
- 推荐 **uiautomation**（PyPI 2.0.29，2025-08，Apache-2.0，活跃）做"读界面不读像素"的前台窗口/控件树/标题获取；pywinauto（BSD-3）长期停更后复活但节奏弱。纯 CPU 零显存。限制：高完整性窗口（管理员进程）需 UIAccess 签名（官方文档）。
- **OmniParser**（arXiv:2408.00203）：截图→结构化可交互元素（检测+语义 caption），增强纯视觉代理——可作 YOLO+RapidOCR 的升级候选；显存/许可**待二次核实**（GitHub/HF 不可达）。
- **OCR 不换 PaddleOCR**：RapidOCR 已是 PP-OCR 权重 ONNX 部署（Apache-2.0），迁移收益有限；若需 PP-OCRv6 精度再重导 ONNX。
- **本地 VLM 首选 Qwen2.5-VL 3B（int4）**（arXiv:2502.13923 官方自述可作交互视觉代理、OCR 强；8GB 可行性为**参数量化常识估计**，7B bf16 超 8GB）；Florence-2 许可近期有变更**无法核实，用前必查**。
- **隐私范式以 Windows Recall 为反面教材**（社区广泛报道：默认全时截屏引发抵制→改默认关+加密+需 Hello）：Haru 原则=按需截屏+本地推理+显式授权+可暂停+原始截图不落盘。

**游戏陪伴四级阶梯（MC/FO4 具体路径）**：
| 级 | Minecraft | 辐射4 | 红线 |
|---|---|---|---|
| L1 看画面聊天 | ✅ 截图+Qwen2.5-VL+OCR（客户端合法） | ✅ 同左（纯截图无注入） | 联机强反作弊游戏（EAC/BattlEye/Vanguard）禁止注入/读内存 |
| L2 读结构化状态 | ✅ **mineflayer 已有**（坐标/背包/聊天/血量，协议级非注入） | ⚠️ UIA 窗口标题+OCR 读 HUD（安全、信息有限） | — |
| L3 合法 API 互动 | ✅ 服务器/插件事件+指令（已验证方向） | ❓ F4SE/Creation Kit 路线**本环境无法核实，落地前必查** | FO4 注入类 mod 有存档兼容/法律灰区 |
| L4 自主操作 | 意义不大（已有原生 bot） | 风险高，不建议 | 联机游戏一律禁止 |
- **Steam Web API（官方核实）**：IPlayerService.GetOwnedGames/GetRecentlyPlayedGames（playtime_forever/2weeks）、ISteamUser.GetPlayerSummaries 的 `gameextrainfo`（当前正在玩）——**游戏无关的零侵入事件源**，Haru 可合法知道"你在玩什么、玩了多久"，需免费 API key+资料公开。
- Voyager/MineDojo（arXiv 核实为学术框架，仓库维护状态不可达）——与实时陪伴产品不同路，仅借鉴；FO4"ChatGPT 伴侣 mod"仅社区传闻，**不作为承诺依据**。

**桌面自动化与工具**：
- 浏览器层：**Playwright**（1.63.0，Apache-2.0，活跃，**内置 MCP server**）成熟；原生 App 交给 UIA。
- **MCP**（modelcontextprotocol.io 官方开放标准）：作为 Haru 的统一工具总线接入现成 server（文件/剪贴板/系统），权限需管控；系统级 server 清单**待二次核实**。
- GUI Agent：UI-TARS（arXiv:2501.12326，OSWorld 24.6@50步）、Agent-S（框架）——8GB 本地端到端 GUI agent 不现实；**务实组合=Qwen2.5-VL 3B + UIA/OmniParser 混合**（基于可达论文的组件推断）。

### 4.4 语音栈选型（✅ 已核实；GitHub/HF 主站不可达，经 raw.githubusercontent / jsDelivr / PyPI JSON / hf-mirror / 官方文档验证）

**推荐组合表**（8GB 约束下需与 bge-small≈0.4GB、LLM 云端共存；数字标"官方"=厂商文档，"估计"=无官方数据）：

| 环节 | 首选 | 核实依据 | 备选 |
|---|---|---|---|
| ASR | **FunASR Paraformer-zh-streaming（220M）+ fsmn-vad + ct-punc** | 代码 MIT、权重按卡；官方 README：SenseVoice-Small（234M）"CPU 可行"，官方发布 Windows CUDA llama.cpp 二进制；2026-09 仍发版（PyPI 1.4.16）；**无官方流式 RTF**（官方警告勿引用旧社区计时） | faster-whisper（官方表：large-v2 fp16 4525MB / int8 2926MB 显存；PyPI 停更在 1.2.1@2025-10，"归档横幅"未能核实）；whisper.cpp（MIT、Windows CUDA、stream 示例 0.5s 切片，边界偏钝） |
| VAD | **Silero v6.2.3（MIT）** | 官方：30ms 音频单 CPU 线程 <1ms；训练覆盖 6000+ 语言；2026-09 活跃（PyPI） | FunASR fsmn-vad（免额外依赖） |
| TTS | **CosyVoice2 / Fun-CosyVoice3-0.5B** | 代码 Apache-2.0；权重经 hf-mirror 核实均 apache-2.0（"改协议"传闻不实）；官方 README：双向流式、**首包低至 150ms**、CER/WER 开源领先；显存无官方数→估计 fp16≈2–3GB | Kokoro-82M（Apache 权重、官方中文音色 4F4M、CPU 可跑——**适合先验证链路**）；GPT-SoVITS（**已改 MIT**，AGPL 传闻过时；无官方显存数→估计） |
| 实时框架 | **pipecat（BSD-2）** | v1.12.0@2026-09；官方服务表含 FunASR/Kokoro/Silero/Smart Turn 本地集成；官方打断文档：用户开口→bot 立即停、在途任务取消、管线就绪 | LiveKit Agents（Apache，v1.8.6@2026-10；中文语义轮次可用，**但 turn 模型许可限定只能随其框架使用**、增强降噪依赖 LiveKit Cloud、无官方 faster-whisper 插件[PyPI 404]） |

**三档端到端方案**（首包为估计值，未计 LLM 延迟）：
- **A 全本地（推荐起步）**：pipecat + Silero(CPU) + Paraformer-streaming(GPU≈1–2GB 估计) + CosyVoice2(≈2–3GB 估计) + bge-small≈0.4GB → 总显存约 4–6GB，链路首包估计 0.5–1s。
- B 本地 ASR + 云 TTS：省 TTS 显存至≈2GB，但"边放边停"需取消云流、打断延迟不可控（估计）；Edge-TTS 仅在线（README）非 SLA。
- C 全云端：本机仅 VAD，质量最好但隐私/网络依赖。**Haru 仓内已有 FunASR 原型 → 直接走 A，TTS 先用 Kokoro(CPU) 打通链路再换 CosyVoice2。**

**打断与回声消除（AEC）**：两家框架文档一致的标准链路=VAD 检出用户语音→flush TTS 缓冲停播→同一 ASR 流继续收新输入；再叠**语义 endpointing** 降误断（Smart Turn：BSD-2、Whisper-Tiny 骨干、支持中文、官方"仅在静音段运行"）。LiveKit 官方文档明说外放回声"会干扰 turn detection 与转写"——对策：戴耳机零成本；浏览器/WebRTC 内置 echoCancellation（MDN 核实）；桌面外放需参考信号 AEC（SpeexDSP/AEC3，Python 现成 Windows 包少→工程量大，估计）。**1v1 陪伴用半双工+语义轮次即可，全双工强依赖 AEC，不建议第一期做。**

**许可红线**：❌ 禁商用：ChatTTS（代码 AGPLv3+ / 模型 CC BY-NC；官方：30s 音频≥4GB 显存、4090 RTF≈0.3；tag 停在 v0.2.5）、Fish S2-Pro（Research License，商用需另购；其 RTF 0.195/TTFA 100ms 系 H200 数据，4B 不适配 8GB）。✅ 可商用：Silero/FunASR 代码/whisper.cpp/faster-whisper（MIT）、pipecat（BSD-2）、Kokoro/CosyVoice/LiveKit-Agents（Apache）。注意：FunASR 部分权重有单独开源协议卡；GPT-SoVITS/ChatTTS 声音克隆的训练数据来源合规自担（呼应 §9-2 音色决策）。

## 5. 全技术栈能力矩阵（三路调研已全部返回并整合；✅=已核实选型）

| 领域 | 当前 | 体验影响 | 候选技术 | 难度 | 8GB 可行性 | 隐私风险 | 决策 |
|---|---|---|---|---|---|---|---|
| 语音输入 | ❌ | ★★★★★ | FunASR Paraformer-zh-streaming+Silero VAD（pipecat 编排）✅ | 中 | ✅（220M，CPU/GPU 皆可） | 麦克风常开需指示灯/热键 | **做，第一优先** |
| 语音输出 | ❌ | ★★★★★ | Kokoro-82M(CPU) 打通链路→CosyVoice2-0.5B 换装 ✅ | 中 | ✅（Kokoro CPU；CosyVoice2 估计 2–3GB） | 音色克隆授权 | **做，第一优先** |
| 实时对话/打断 | ❌ | ★★★★ | pipecat 打断（VAD flush+在途任务取消）+ Smart Turn 语义轮次；半双工起步 ✅ | 中 | ✅ | — | **做，第一优先** |
| 虚拟形象 | ❌ | ★★★★ | Live2D 小窗（Wails+pixi-live2d-display+emotionMap 协议+振幅/Rhubarb 口型）；MVP=静态立绘+表情 ✅ | 中 | ✅（渲染轻） | Live2D 商用条款+模型资产许可 | 做（投入级别待期 3 定） |
| 屏幕感知 | ⚠️手动 | ★★★★ | uiautomation 窗口上下文（纯 CPU）+按需截屏+RapidOCR（保留）+Qwen2.5-VL 3B int4 ✅ | 中 | ✅（VL 估计可行，需实测） | **高**：授权/指示灯/范围控制（Recall 教训） | 做（授权式） |
| 游戏陪伴-MC | ⚠️有工具链 | ★★★★ | mineflayer（已有）L2/L3 结构化状态+事件订阅 | 低（激活即可） | ✅ | 反作弊（MC 安全） | **激活+扩展** |
| 游戏陪伴-FO4 | ❌ | ★★★ | 四级阶梯 L1 截图+L2 UIA/OCR 路线（F4SE 注入路线调研环境无法核实，落地前必查）✅ | 中（L1/L2 低） | ✅ | 单机无反作弊问题 | 做 L1/L2，注入路线缓 |
| 摄像头 | ❌ | ★★ | MediaPipe（CPU）/按需 Qwen2.5-VL | 中 | ✅ | **极高**：默认关+物理提示 | 缓 |
| 主动交互 | ⚠️机制有 | ★★★★ | OpenClaw 协议+质量门（§3-2 教训） | 低 | ✅ | 打扰 | 做（补控制面+质量门） |
| 长期运行 | ⚠️ | ★★★ | 配置持久化+幂等+failover+托盘自启 | 低 | ✅ | — | **做（地基）** |
| 多模态协调 | ❌ | ★★★★ | 统一事件总线（单进程多线程起步） | 中 | ✅ | — | 随各层增量 |
| 用户控制 | ❌ | ★★★★ | 设置面板+权限开关+静默段 | 低 | ✅ | — | **做** |
| 部署架构 | ✅ | — | 见 §7 | — | — | — | — |

## 6. 架构方案比较与推荐

| | A 现有增强 | **B 渐进式多模态重构（推荐）** | C 陪伴侧重建 |
|---|---|---|---|
| 内容 | 只补 TTS/ASR 挂到现有 Flask | 新增**统一事件总线+I/O 适配层**（麦克风/扬声器/屏幕/游戏/热键/托盘），对话主管道与认知层作为总线消费者保持不动；形象层独立小窗；可靠性三件套 | 重写陪伴主路径为多模态 agent 框架 |
| 收益 | 能说话，但打断/形象/屏幕各自为政 | 所有模态共享轮次/打断/状态/授权模型；认知侧零改动 | 理论最优 |
| 风险 | 低但天花板低 | 中：增量接线，旧路径可回滚 | 高：重走 app.py 迁移欠账，评测体系未建 |
| 工作量 | 2-3 周 | 8-12 周分 4 期 | 6 月+ |

**推荐 B**。理由：① 本 session 已证明"接线工程"路线有效（生活循环/Charon/表达链全是接线成果）；② 认知图谱与业界时序图谱方案同构（Graphiti），不需要动；③ 多模态的难点在**协调层**（打断、轮次、授权、状态一致），恰好是加一层而非重写。

### B 的目标架构（分层）
```
[用户交互层]  托盘/热键/设置面板/悬浮窗(形象)  ← Charon 扩展或独立小窗
[形象层]      Live2D 小窗：口型←TTS 流；表情←行为状态事件（非随机）
[输入适配层]  麦克风(VAD+ASR)│文本│屏幕(授权捕获)│游戏事件(MC桥/FO4 mod)│系统事件
      ↓ 统一事件总线（进程内队列；事件={kind, payload, source, ts, trust}）
[感知上下文层] ASR 文本/OCR/UIA 窗口/游戏状态 → 上下文装配器（视觉按需：Qwen2.5-VL 3B int4）
[陪伴行为层]  对话编排(现 process_nlp 收敛)│表达裁决(SocialDecider 统一)│主动(生活循环+心跳)
[模型服务层]  LLM 路由(MiMo+ollama+failover)│ASR│TTS│VL按需  ← 显存调度器(8GB 预算表)
[执行集成层]  工具白名单│MC bot│Playwright+MCP 浏览器层│UIA 原生 App（分级授权）
[持久状态层]  配置覆盖文件★│生活账本│chat_log+摘要链│身份块(Letta 式)
[可靠性层]    消息幂等│任务取消│断线重连│崩溃恢复(账本已有)│日志分级
[权限控制层]  麦克风/屏幕/摄像头/文件/执行 各自独立开关+采集指示+静默段
```
关键决策：**单进程多线程起步**（拒绝微服务）；**认知侧最小依赖面**＝解析/检索/写回/反思四 API；**网页 UI 保留为开发者视图**，用户面逐步迁到形象小窗+托盘。

## 7. 8GB 显存部署方案（数字标估计/实测）

常驻：bge-small ~0.3GB（实测在跑）+ 当前 LLM 占用 1.3GB（实测）→ 空闲约 6.4GB。
语音链路预算（✅ 已核实厂商数字 + 估计，见 §4.4）：Silero VAD 纯 CPU（官方 <1ms/30ms 音频）；Paraformer-streaming 220M（GPU≈1–2GB 估计，亦可 CPU）；CosyVoice2-0.5B（估计 fp16 2–3GB，官方首包 150ms）。**Kokoro-82M 可全程 CPU 跑**——链路验证阶段显存零增量。按需加载+用完卸载由显存调度器管理，语音峰值+bge 合计 ≤6GB 留余量。
LLM 维持云端（MiMo）——本地 8GB 跑对话模型质量不达标，不建议。
三档对比（§4.4 已核实）：**A 全本地（推荐起步：pipecat+Silero+Paraformer+Kokoro→CosyVoice2，总显存估计 4–6GB）** vs B 本地 ASR+云 TTS（省 2–3GB，但打断延迟不可控、Edge-TTS 在线非 SLA） vs C 全云端（质量最好、隐私/网络依赖）。ChatTTS/Fish S2-Pro 因许可与显存红线出局。
待实测项：Paraformer 流式与 CosyVoice2 在本机 4070Laptop-8GB 的 RTF/共存显存（无官方数据，期 2 第一件事就是量它）。

## 8. 分阶段实施（每期独立可回滚）

| 期 | 内容 | 验收（垂直切片） | 工作量 | 依赖 |
|---|---|---|---|---|
| **1 地基** | 可靠性三件套（配置持久化/幂等/LLM failover）+事件总线骨架+权限模型 | 重启不丢配置；重放注入不重复发言 | 1-2 周 | 无 |
| **2 声音** | 麦克风+Silero VAD→FunASR Paraformer→主管道→Kokoro(CPU 先行)→CosyVoice2 TTS 流式播放→**pipecat 打断（半双工+语义轮次）**；热键 PTT；本机实测 RTF/显存定档 | "按热键说话→她回答→出声→中途插话她能停"全链实测 | 2-3 周 | 期1（选型已定 §4.4） |
| **3 脸与存在感** | Live2D 小窗（或 MVP 静态立绘+表情，§9-1 决策）+口型←TTS 流+表情←状态事件；托盘/自启 | 她说话时嘴动、被夸时表情变化（状态驱动非随机） | 2-3 周 | 期2 |
| **4 眼睛与游戏** | 授权式屏幕观察（窗口上下文+按需 OCR/VL）+MC 陪伴激活+主动交互控制面+**表达质量门**（§3-2 教训） | "授权看当前窗口→她评论真实内容"；分享候选误报率评测 <阈值 | 3-4 周 | 期1-2 |
| 暂缓 | 摄像头（隐私成本）、桌面自动操作（风险高）、FO4 F4SE 注入路线（调研环境无法核实，落地前必查）、全双工语音（强依赖 AEC）、本地 LLM | — | — | — |

## 9. 需要项目所有者决策

1. 形象投入级别：静态立绘+表情切换（1 周）vs Live2D 小窗（3 周+模型资产）——取决于你要的"存在感"强度。
2. 音色：Haru 的"嗓子"是产品定义的一部分——TTS 音色选型/是否克隆/授权来源需你定。
3. 屏幕观察默认策略：建议"永远按需+窗口标题栏采集指示+全局快捷键一键关"。
4. 麦克风常开 vs 按住说话（PTT）：建议先 PTT（隐私简单），稳定后再评估常开。
5. 预算红线：云端 LLM 月成本上限与"断网降级行为"。

## 10. 证据缺口（明确未核实项）

三路调研已全部返回，剩余缺口为**物理环境限制导致的不可远程核实项**：

- **本机 RTF/显存共存实测**：Paraformer-streaming 流式、CosyVoice2-0.5B fp16、Qwen2.5-VL 3B int4 在 4070Laptop-8GB 上与 bge-small+LLM 的共存数字均为厂商数据或估计，**无本机实测**——期 2 第一件事就是量它。
- **打断链路端到端延迟**：pipecat 官方文档描述了机制，但未给出硬件基准；"外放 vs 耳机"体验差异需实测（AEC 工程量大为估计）。
- **FO4 F4SE 注入路线**：调研环境无法访问 mod 社区核实接口现状与稳定性，**不得作为承诺依据**；L1/L2（截图+UIA/OCR）不依赖它。
- **faster-whisper 归档横幅**：PyPI 显示停更（1.2.1@2025-10），但"归档"声明未能直接核实（GitHub 不可达）。
- **Live2D Expandable Application 商用条款**：文档可达但条款适用性需法务确认。
- **MCP 系统级 server 清单**、**Voyager/MineDojo 仓库维护状态**：主站不可达，仅二手来源。
- **生活循环长期质量**（误报率/预算执行）：样本 1（含 1 个误报，见 §3-2），需 ≥7 天运行数据。
- **FunASR 权重卡协议细节**：代码 MIT 已核实，具体权重文件的协议卡需在选定时逐卡核对（hf-mirror 可达但未逐卡展开）。

---
*本文档为只读审计产物；未修改任何生产代码/配置/进程。配套：COMPANION_HUMANLIKE_GAP_AUDIT_2026-10-12.md（认知/社交层差距）、HARU_EXEC_SUMMARY_FULLSTACK_2026-10-12.md（一页纸执行摘要）。*
