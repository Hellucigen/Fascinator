# Haru 全栈陪伴一体化 · 实施记录（2026-10-12）

> 一轮交付：P0-P5 直接实施 + 全部测试真实结果。只读审计见 HARU_FULLSTACK_COMPANION_AUDIT_2026-10-12.md（本文不重复审计，只记"改了什么、跑出了什么、还欠什么"）。
> 纪律自查：未重启生产（当时无进程）；未覆盖工作区未提交修改（全部增量编辑）；两仓保持独立（认知层同进程动态调用，零复制）；密钥未入源码/日志。

## 0. 基线修正（侦察发现的两个与假设不符的事实）

1. **认知仓 2026-10-12 已把 planner/reader/memrep/taskloop 四段出厂置 True**（认知侧 ENABLEMENT 自录，"运行时未测"）——审计与陪伴侧旧文档写的"默认关"已过时。P4 的适配器据此把 mode 词表分为 `production_in_use / enabled_wired_runtime_unverified / flag_off` 三态，绝不混用。
2. **ear/ 的 FunASR 在运行环境不可用**：Fascinator env 缺 funasr/sounddevice 等全部语音包；默认模型路径指向不存在的 `E:/Models/Paraformer`（实际在 `E:/Models/nlp/`）。P1 因此走独立轻量栈（Silero+faster-whisper+kokoro-onnx），不动 ear/。

## 1. P0 基础修复（全部完成）

| 问题 | 修法 | 落点 | 验证 |
|---|---|---|---|
| 配置重启即丢 | 新增 `config_store.py`：`data/config_overlay.json` 覆盖文件（原子写），启动重放、PUT 类型安全更新；bool "false"→True 的强转 bug 一并修复 | FAS-Companion/config_store.py；app.py:128-143, 8255-8300 | tests/test_config_store.py **30/30** |
| 启动强覆盖开关 | `companion_charon_enabled`/`companion_self_search_enabled` 改为"overlay 未显式改过才置默认"；env 硬开关优先级保留 | app.py:150-186 | 同上 |
| 新键无法经 API 开启（`if k in config`） | 认知仓 config.py 补 `interaction_planner` 段（此前该段两仓都不存在，模块永远开不了）+ voice/screen/steam/预算 全部新键出厂声明 | FAS-Cognitive/config.py:287+ | 测试含断言 |
| LLM 无超时/无恢复 | openai client 显式 `timeout=120s(可 env)`+`max_retries=0`；`_create` 加 failover（瞬时故障→环境变量在场的另一供应商，注册表 `_KNOWN_BACKEND_CLASSES`；400/401/代码错误原样上抛不掩盖） | llm_provider.py:64-260 | tests/test_llm_recovery.py **12/12** |
| 错误串冒充话语 | `[回答生成失败:…]` 不再进响应/Charon/chat_log/结局记账；降级为人设内致歉 + `llm_degraded` 标记 + `outcome=llm_failed` | app.py:5560 区/5486 区 | 编译+冒烟 |
| 好奇检索重启即忘 | `_searched` 持久化 `data/self_searched.json`（500 条 FIFO）；搜索记录节点 id 改毫秒（同秒覆盖小修） | app.py:363-460 | 冒烟 |
| 生活循环质量门（实锤误报复现） | ① topic/查询种子分离（`concept` 键+`_clean_topic` 剥「」与前缀，"数熵」"类残迹绝版）② 相关性改整词/首末双碎片闸（字典页误报被拒）③ 页面内容过同闸（残片页不算发现）④ 日预算 `count_web_call` 真正接线（每搜/每页+1）⑤ 耗尽概念水印（paused-exhausted/abandoned 不重开；`real_knowledge_gap` 传账本 acted 集不再传空集）⑥ waiting 活动新预算日自动恢复 | living_loop.py:143-533 | tests/test_living_quality_gates.py **23/23**（含误报复现与拒绝）；experiments/living_v3/test_production_entry.py 13/13 |
| 测试污染生产账本（本次又实锤一次） | `FAS_LIVING_DATA_DIR` 隔离环境变量 + test_production_entry T5 改用之 + 新增 T5c"首拍不污染"断言；已清掉本次测试写入的 `life_1791797074` | living_loop.py; 认知仓 experiments/living_v3/test_production_entry.py | 复跑后生产账本零新增 ✓ |

## 2. P1 日语语音闭环（链路与后端全接通；设备待用户实机开）

- 新模块 `voice_io.py`：**麦克风(16k)→Silero VAD（不可用自动退化能量门）→分段→faster-whisper small(int8,CPU)→/api/nlp 同一主管道（test_client 复用，无第二条管线，照 _channel_turn_runner 先例）→双轨：显示=原文、播报=日语译文（LLM 翻译，mustache 模板纪律）→kokoro-onnx 日语女声 jf_alpha→sounddevice 播放**。
- **打断**：说话期间检出用户语音→停播+`epoch` 作废在飞识别/生成/播放（旧任务不得覆盖新对话）；`avatar_state` 同步 interrupted。
- **输入/输出语言分开**：ASR `language=auto` 不假设用户说什么；播报语言 ja；中文输入不会被强改成日语（只翻译她要说的话）。
- **隐私**：`voice_listen_enabled` 在 `PRIVACY_EPHEMERAL_KEYS`——可热开/热关但**永不落盘，重启必回未监听**；原始音频不落盘不上云（只有转录文本进既有 chat_log 持久化路径）。
- **状态可见**：`GET /api/voice/status`（state/backends 真实可用性/stats/reason）；开关、出声测试、wav 注入通道 `/api/voice/feed`；Web UI 新增 **Body 面板**（语音/屏幕/Steam/形象/认知/预算六个卡片+按钮）。
- **模型资产（本机新增，未动 ear/FunASR）**：`models/tts/kokoro-v1.0.onnx`（量化 87MB）+ 自拼 `voices.bin`（5 个日语音色 npz；官方逐音色 bin 非 npz，`np.load` 拒读，已按 (510,1,256) 规范重建）；faster-whisper small 权重 461MB 进 HF 缓存。依赖新增：`sounddevice silero-vad faster-whisper kokoro-onnx soundfile`（均装于 Fascinator env；requirements.txt 未动，见 §9 待办）。
- **日语 ASR/TTS 依据**（用户要求先核日语自然度）：kokoro-onnx 官方音色表含 jf_alpha/jf_gongitsune/jf_nezumi/jf_tebukuro/jm_kumo（Apache-2.0 权重，本机合成实测 11.65s 音频/36.1s CPU RTF≈3.1——首包慢，见 §8 已知问题）；faster-whisper multilingual 覆盖 ja；本机 Windows SAPI 无日语语音（仅 zh-CN Huihui/en-US Zira），排除。
- 逻辑测试 tests/test_voice_loop.py：A 层（双轨/仲裁/分段/epoch/热开关/无声降级）**19 项离线全绿**；B 层真实模型回环（本机 CPU 实测，2026-10-12）：
  - **B1/B2 通过**：kokoro-onnx 量化模型加载+日语合成（11.65s 音频/11.3s，RTF≈0.97——首次单独测 36s 含模型冷启动）。
  - **B3/B4 通过（机制）**：faster-whisper small int8 CPU 加载 34.9s、转录 11.65s 日语耗时 3.8s（RTF 0.33）、lang 检出 ja、输出全日文字符。
  - **B 层质量红线（如实）**：回环内容不匹配——输入「今日はいい天気ですね、お出かけしますか？」识别为「どういう天気予報…」：ASR 抓住了"天気"（证明 kokoro 日语发音真实），但整句精度不足。**结论：端到端机制成立（声音进→日语文字→主管道→日语声音出），识别/合成质量组合未达可用**；优化路径已列 §9（better whisper 档/云 ASR 兜底/试听 wav 定音色）。样本已存 `C:/Users/Hellucigen/AppData/Local/Temp/haru_ja_sample.wav` 供你试听。
  - **真机抓到的两个 bug（测试的价值所在，均已修+注释在案）**：
    1. kokoro-onnx 0.6.1 `create()` **同步返回 (audio,sr)**，初版误用 `asyncio.run` 包装 → 直接失败；回环抓到，改同步调用（voice_io.py TtsBackend.synthesize）。
    2. `avatar_state.release()` 持锁调 `set_state()`，而 `threading.Lock` 不可重入 → **进程冻死**（CPU 0 卡 15 分钟）；改 `RLock`（avatar_state.py 注释在案）。
  - **官方指标≠本机实测**的具体例证：kokoro "首包 150ms" 是 GPU/优化数字；本机 CPU 整句 RTF≈1.13（11.6s 音频合成 13.2s）。报告全程用本机数，不引用厂商峰值。

## 3. P2 形象（接口先行，未锁定皮）

- 比较结论（沿用审计报告 §4.2 已核实项，无新增支出）：主推 Live2D 小窗（Wails webview+pixi-live2d-display+emotionMap+TTS 振幅口型）；MVP=静态立绘+表情；VTube Studio=封装备选（外部进程绑架）。**未下载素材、未购买模型**。
- 已实现：`avatar_state.py` 六态状态机（idle/listening/thinking/speaking/**interrupted**/**error**）+ 优先级仲裁（高态不被低态抢占、非持有者不能释放）+ 迁移历史 + pusher 异常隔离；**推送接 Charon 事件总线**（`POST /api/events` topic=`fas.avatar_state`——渲染端将来只读订阅，换皮不重写对话）；语音/表达/故障写入方已接入；`GET /api/avatar/state` + Body 面板展示。

## 4. P3 屏幕观察与情境（默认关已实现并验证）

- `screen_watch.py`：`screen_observe_enabled` **出厂关 + 隐私 ephemeral（重启必关，PUT 不落盘）**；开启=显式 POST `/api/screen`；**采集期持续可见状态**（每次观察发 `fas.screen_state` 事件；开启/关闭 toast；面板显示状态/小时计数）；一键停止；限频（间隔+每小时上限，实测修掉"load 覆盖小时计数"的顺序 bug）；内容 hash 去重（同屏不重复入图/不重复表达）；截图字节即抛（走既有 `recognize_text` 只回文本）。
- 观察→表达：复用 `salient_texts→inject_observation→engine.mark_active` 既有管线，**值不值得说由既有表达决策**——屏幕观察不新增任何一条 LLM 调用/发言出口。
- `steam_status.py`：GetPlayerSummaries 只读轮询；事件语义（game_started/stopped/offline）+指纹去抖；缺 key 如实报因。**需要你的 STEAM_API_KEY+steam_id 才能真跑**（§9）；`/api/steam/tick|status`+面板按钮+`_context_poller` 线程（flag 热自查）。
- Minecraft 核实：工具链/桥/通道在认知仓 `minecraft/`，`bridge.py/channel.py` 完好；**生产激活前提=用户在 config 填服务器/账号并启动 bot**——本次未擅自连接任何服务器（不伪造"陪玩"能力）。FO4：仅保留审计结论（截图/UIA 路线，F4SE 注入落地前必查），无代码。

## 5. P4 认知层动态接通（重点，含真实 E2E 证明）

- `cognitive_adapter.py`：薄门面（不复制认知逻辑）——组件白名单 `cc/autonomy/kg/engine/nlp/…`，`call(cap,method,*args)` 错误隔离+耗时；`availability()` 三态词表诚实清单（production_in_use / enabled_wired_runtime_unverified / flag_off，并如实传递认知侧自己的"运行时未验证/消费端仍缺"注记）；端点 `GET /api/cognition/capabilities`、`POST /api/cognition/call`、`GET|POST /api/goals`。冒烟实测清单端点正常、能力模式正确。
- 修复的真实断点（侦察确认存在于当前代码，非旧结论）：
  1. `goal_planner.attach_goal` **生产零调用** → 经 `/api/goals` 提供稳定入口（计划推演按 reality 返回 unreachable，不假装）。
  2. `reading.register_gap` **生产零调用** → 开书即注册"阅读"域缺口（CuriosityDrive 消费方本就在，app.py:4518-4527）。
  3. 分享候选**只写不读**（详见 P5）。
- **端到端证明** `scripts/e2e_cognitive_consumption.py`（临时目录装配真实 kg/engine/nlp/cc，生产零接触）：**12/12 PASS**。关键结果：注入一条模拟环境观察事件（"工作区出现《神曲》地狱篇文档"）→ 真实 cc 节拍形成 CI 且 basis 引用该节点（E1）→ v2 四轴评估留痕（E1b）→ 真实 LLM 渲染表达：**「对了，我看到你工作区里有份《神曲》的文档，写到的是地狱篇那段——你是在读但丁吗？」**（E3：话语必须含主题字面词才算过）→ attach_goal/状态查询/白名单拒绝未知能力（E4a-d）→ 能力清单三态不混用（E5a-e）。
- 陪伴层独立状态边界：会话摘要/chat_log/生活账本/分享候选/语音 stats 全在陪伴仓 data/；认知层状态仍只在图谱真源（`_save` 单写入器）+ 各 JSON 账本；适配器只做"读+受控写入口"，无双向同步环。

## 6. P5 生活循环产品面

- 分享候选消费：`run_living_loop_daemon(..., deliver_fn=_living_share_deliver)`——SocialDecider 判 share 的候选经**既有 Charon proactive 通道**（气泡/SPEAK/便签）投递 + 进 `_living_queue` 由 `/api/proactive/poll` 收走；每拍最多 1 条、`delivered` 标记幂等（重启不重发）、`cc._busy` 让位返回 False 延后；队列积压护栏 8 条。
- 用户控制：`GET /api/living` 账本视图（活动/尝试/发现/分享决定/预算余量）；`POST /api/living` pause/resume/abandon（abandoned 不复活，resume 仅合法态）。

## 7. 测试总账（真实结果）

| 套件 | 结果 |
|---|---|
| FAS-Companion tests/test_config_store.py | **30/30** |
| tests/test_living_quality_gates.py | **23/23** |
| tests/test_llm_recovery.py | **12/12** |
| tests/test_context_io.py | **21/21** |
| tests/test_interaction_planner.py（既有） | 10 组全 PASS（exit 0） |
| tests/test_voice_loop.py（A 离线逻辑 + B 真模型回环） | **36/36 PASS** |
| 认知仓 pytest tests -q | **161 passed** |
| 认知仓脚本测试 expression/taskloop/goal_planner/memrep/reading | 全部 exit 0 |
| living_v3/test_production_entry.py（生产入口，含新 T5c 防污染） | 13/13 |
| scripts/e2e_cognitive_consumption.py | **12/12（真实 LLM）** |
| 冷启动冒烟（隔离 5099，FAS_CHARON=0/FAS_NO_SELF_SEARCH=1/隔离数据） | 装配日志全绿；7 个新端点全响应；overlay 测试写入已清理；实例已杀 |

## 8. 未实测清单（诚实分界：代码存在≠设备实测）

1. **真麦克风采集/扬声器输出/打断**：本会话无设备验证条件——逻辑层（分段/epoch/停播/热开关）已全绿，`/api/voice/feed` 提供 wav 等效通道供你实机验收；开麦需你在 Body 面板点"开麦监听"（重启自动关）。
2. **回环语音质量/延迟**：kokoro CPU 合成 RTF≈3.1（11.65s 音频耗时 36.1s——**当前非实时**；GPU/优化或换 edge-tts 前，出声会慢半拍）；whisper small CPU 转录 11.65s 日语耗时见 B 层测试数字。
3. 屏幕观察真机一次（需你在 Body 面板显式开启后点"观察一次"）；OCR 依赖 mss/RapidOCR 已装但未在本会话实跑截屏。
4. Steam：需 `STEAM_API_KEY`（环境变量）+ `steam_id`（config）——待你提供后测。
5. MC 陪伴激活：需 bot 连接真实/本地服务器（不擅自连）。
6. Live2D/立绘渲染：皮与素材待你定投入（§9-1）；状态协议已可用。

## 9. 待你处理（唯一需要你出手的清单）

1. **形象投入决策**：静态立绘+表情（零采购）vs Live2D（购模型+确认 Expandable Application 条款）。协议已就绪，任何皮都只订阅 `fas.avatar_state`。
2. **Steam**：注册免费 API key（https://steamcommunity.com/dev/apikey）→ 设 `STEAM_API_KEY` 环境变量 + config `steam_id`，再开 `steam_poll_enabled`。
3. **开麦验收**：重启 Haru（Charon 或直跑 app.py）→ Body 面板 → 启用语音+开麦监听 → 对它说一句日语/中文。
4. **音色试听与 ASR 质量决策**：日语样本已合成 `C:/Users/Hellucigen/AppData/Local/Temp/haru_ja_sample.wav`（jf_alpha）；其余 4 音色改 config 选择即可。回环测试显示 **whisper small int8 CPU 对本机合成日语的整句精度不足**（机制通、质量未达）——三条可选路：① 本机试 `large-v3` int8（显存/内存有余量，需一次权重下载授权）② 云 ASR 兜底（你有 Groq/OpenAI/Deepgram 任一 key 即可接）③ 真人语音实测（合成语音≠真实语音，whisper 对真人日语可能明显更好——这条只能你开麦验）。
5. **预算**：在 Body 面板设 `llm_monthly_budget_cny`（价格表 `llm_price_table` 需按 MiMo 实际单价填一次才能算钱；当前为 0=记账不拦截）。
6. requirements.txt 追加建议（未代改，避免无谓 diff）：`sounddevice silero-vad faster-whisper kokoro-onnx soundfile`。

## 10. 改动文件清单

**新增（FAS-Companion）**：config_store.py / usage_ledger.py / voice_io.py / avatar_state.py / screen_watch.py / steam_status.py / cognitive_adapter.py / scripts/e2e_cognitive_consumption.py / tests/{test_config_store,test_living_quality_gates,test_llm_recovery,test_context_io,test_voice_loop}.py
**修改（FAS-Companion）**：app.py（配置重放+PUT 持久化+错误串拦截+好奇持久化+living deliver 接线+语音/形象/屏幕/Steam/认知/用量端点+context-poller/voice-sync 线程+reader 缺口注册）/ living_loop.py（质量闸门+living_tick_once 可测化+daemon 重构）/ llm_provider.py（超时+failover+账本挂钩）/ index.html（Body 面板）
**修改（FAS-Cognitive）**：config.py（新增 voice/screen/steam/interaction_planner/预算 全部键声明）/ experiments/living_v3/test_production_entry.py（T5 隔离+T5c 防污染断言）
**数据**：models/tts/*（87MB onnx+2.4MB voices）；HF 缓存 whisper small 461MB；data/living_ledger.json 清除测试残留 life_1791797074

---

# 追加（2026-10-13）：前端统一迁移到 Charon + Steam key 验证 + UKAago 选型

## A1 前端统一（用户入口只此一家 = Charon）

- **Charon Fascinator 控制台新增 BODY 页**（`E:\Project\Charon\frontend\src\modules\Fascinator.tsx`）：语音（启用/开麦/出声测试/后端可用性/stats）、屏幕观察（开关/观察一次/本小时计数/重启必关声明）、形象状态（实时六态+迁移史）、生活循环（预算余量/ON-OFF/逐活动暂停·继续·放弃/分享投递状态）、Steam（开关/立即轮询/key与steamid 就绪显示）、云端用量+预算阈值设定、认知能力清单（●在用/◐接线未实测/○关 三色直读 `GET /api/cognition/capabilities`）。全部经既有 `FascinatorService.Call` REST 代理，**后端零新增协议**。
- **App.tsx 常驻存在感徽标**（右上角）：订阅桥事件 `fas.avatar_state`（聆听/思考/说话/被打断…带色点）+ `fas.screen_state`（"眼睛采集中"警示徽标，采集期持续亮、关即灭）——隐私指示从"设置页里查"升级为"永远看得见"。
- **app.py 退出用户前端**：`auto_open_browser` 默认翻为关（启动不再弹浏览器；`FAS_OPEN_BROWSER=1`/config 可恢复）；`index.html` 保留但降级为开发者控制台（显式访问 127.0.0.1:5000 才看得到）。Flask 本体仍是后端心脏（Charon 托管+代理，/api/nlp 是语音管线的复用点），"取消前端"取消的是**入口地位**，不是把后端拆了——128 个既有页面函数没有一夜重写的必要。
- Charon 已重新 `wails build -s`（见下）。

## A2 Steam key 验证与接线

- `5CF2D3A5…` **确认有效**：对 `ISteamWebAPIUtil/GetSupportedAPIList` 真实调用返回 HTTP 200 + 接口清单。
- 落盘 `data/steam_secret.json`（**gitignored**，与 llm_secret 同纪律，不进源码/日志/账本）；`steam_status._api_key()` 读取链 = 环境变量 > secret 文件。
- `steam_poll_enabled` 已写 overlay 持久化开启；缺 steam_id 时轮询线程零网络直接回报"待提供"（测试同步更新隔离真实 key 文件，21/21 仍全绿）。
- **仍差一步（只有你能给）**：steam 个人资料公开 + 把 `steam_id`（主页地址里 7656… 那串）告诉我或在 CONFIG 页 `PUT /api/config {"steam_id":"…"}` 设上——之后她就知道你在玩什么了。

## A3 语言供应商切换：千问（qwen3.8-flash）上线（2026-10-13）

- **发现**：Qwen 通道其实已在 2026-10-12 建好（`llm_provider.QwenBackend`：OpenAI 兼容 base_url `https://maas.qianwenaiapi.com/compatible-mode/v1`，failover 注册表首位；`nlp_processor` 的 qwen/qianwen/tongyi 分支齐备；`data/llm_config.json` 已指向 qwen/qwen3.8-flash）——本轮做的不是"改写"，是**接上密钥并端到端验证**。
- **密钥**：用户提供 key 已存入 `data/llm_secret.json`（**gitignored 实测确认**，绝不进 git/源码/日志；读取优先级 secret 文件 > env——因此 Charon 托管重启、无 shell 环境变量时照常生效）。env 回退链补上 `QWEN_API_KEY/DASHSCOPE_API_KEY`（app.py 命名与官方文档对齐）。
- **实测**：① 原始 curl 调用 qwen3.8-flash → 真实回复（该模型为思考模型，reasoning_content 与可见输出共享预算——沿用 16384 大预算分支，无 finish_reason=length）；② 生产实例重启日志 `provider=qwen, model=qwen3.8-flash`；③ 真实回合 success、无降级；④ **用量账本入账 `Qwen/qwen3.8-flash` 12 次调用 0 失败**——千问确实在驱动全链（解析/抽取/fast 档/回答都走它）。
- **failover 现状（如实）**：主=Qwen；瞬时故障自动换 MiMo/DeepSeek **需要其 key 在环境变量**（`_failover` 按 env 发现凭证）——旧供应商 key 若不再持有，failover 会诚实记录"无备选"并上抛（由 P0-3 降级路径兜住，不会静默）。
- **测试污染修复（实锤）**：`test_llm_recovery` 的假供应商曾把 `FakePrimary/fake-p` 写进生产 `usage_ledger.jsonl`——测试改注入临时目录（根治）+ 账本清除 4 行假数据（余 20 行均真实）。复跑 12/12。
- 预算联动：`llm_price_table` 尚无 qwen 单价（0=只记账不拦截）；你从千问控制台看到实际单价后告诉我/在 BODY 页设 `llm_monthly_budget_cny` 即可启用拦截。

## A4 Steam 实接（2026-10-13 用户 steamid 到位）

- steam_id `76561198271164497` 经 PUT /api/config 持久化（overlay）。真实轮询验证：`GetPlayerSummaries` 通了（当前 personastate=0=不在线，去抖正常——第二次轮询 changed=false）。
- **实测发现的间歇超时 + 应对**：本机对 `GetPlayerSummaries` 间歇 HTTP=000 而 `GetRecentlyPlayedGames` 稳定 200（同域不同端点、同刻一成一败，CDN 边缘问题）。故 `steam_status.tick_once` 升级为**双通道**：实时 summaries 优先（observed）；失败退回 recently-played **playtime 增量推断**（"榜首游戏时长在轮询间增长→正在玩它"，trust=**inferred**，如实标注非实时观测）。基线首拍不发事件；离线单测 4 场景全过（基线/增量/无变化/换游戏）。
- 真实数据样例（近 2 周，实测取回）：Delta Force 48.8h、Fallout 4 31.4h、RimWorld 12h、VPet 10.2h…… 情境入图后，表达管线自行决定要不要提（如"又在打辐射4？"级别的 CI）。

## A5 UKAago（伺か/SSP）调研结论——形象候选，暂缓执行

（github 直连不可达，经 gh 代理/raw/HF 镜像实测取证，2026-10-13）

- **生态真相**：原"UKAServer/Shirotora"独立开源仓库今天已找不到（**别按"UKAServer 开源"立项**）；实际存活的是 **SSP 基件**（ssp.shillest.net，免费软件但**本体闭源**，最新 2.9.13 仍在发版）+ **ukatech 开源周边**：satoriya SHIORI 对话引擎（**BSD-2**，本月活跃）、csaori 插件库、jsstp 客户端（WTFPL）、官方多语言包 ssp-i18n（**简体中文在列**，CI 维护）、文档 MCP（SSP 维护者本人，MIT）。
- **为什么它其实很合 Haru 的胃口**：原生贴桌透明置顶精灵+气泡对话+表情状态机（shell surfaces/dressup）+可拖拽；**SSTP over HTTP 官方规范——`POST localhost:9801/api/sstp/v1` 一行文本请求就能让它说话**（ SEND 指令，`notranslate` 原样播报），我们现成的 `avatar_state` pusher / `fas.utterance` 直接映射过去，零逆向零注入；人格词典引擎开源 → **Haru 的"脑子"可以留在 FAS，SSP 只做嘴脸**（SHIORI 侧挂我们的后端即可）；显存远低于 Live2D webview 方案；自绘 shell 资产 = 零第三方版权、零购买。
- **代价/风险**：基件闭源 freeware（使用免费、商用分发需打招呼）；**无逐窗 click-through**（只有全局 kiosk 模式）；多屏有已知边角问题（官方提供重置开关）；角色社区包逐包谈授权（但自绘可完全绕开）。
- **判定**：**需改造后接入，成熟度是"桌面存在感"路线里最高的**。接入工作量小（avatar_state pusher 加一个 SSTP 适配器 + 自绘一套 Haru shell 立绘）。Live2D 与它不互斥，你哪天想要"会动的二次元身体"再回来补。
- 本轮**未装 SSP、未动形象层代码**（你说先缓缓）——只留此结论。

---
*追加部分与上文同为本实施记录；改动均已 py_compile 通过，相关测试复跑全绿。Charon 新 exe 构建结果与端到端验证见交付对话。*
