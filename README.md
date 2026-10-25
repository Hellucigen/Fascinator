# Fascinator

<div align="center">

**扩散激活知识图谱 × 情境记忆 × 自主表达的桌面 AI 伙伴**

认知引擎自研 · 无框架 · Python + Flask · 与 [Charon](https://github.com/Hellucigen/Charon-Personal-Terminal-of-Hellucigen) 桌面终端联动

</div>

---

Fascinator 是一个"活"的系统：她有一条持续运转的认知循环——扩散激活的知识
图谱当大脑，情景记忆挂在时间链上，驱力/张力场决定她想做什么，表达闸门决定
她什么时候开口。用户不说话时她也在过日子：自己逛网页、攒课题、生成待验证
假设、在授权的时段自主探索。

**核心机制**
- 🧠 **万物皆图**：概念/经历/意图/驱力/假设全部是图节点，统一扩散激活调度
- ⏰ **时间链**：情景记忆锚定在"早于/晚于"双向时间链上，支持相对时间接地（"昨晚说啥了"能答上）
- 💬 **自主表达**：念头形成→证据资格→强度门槛→表达通道，主动找你说话而不是被动应答
- 🌙 **告别授权**："晚安，电脑不关你自己转转" → 她获得到天亮的自主探索许可
- 🎯 **满足语义**：调研过的课题兴趣水位下降、种子轮换，不重复啃同一个词
- 🖥 **双前端**：Charon 桌面端 Haru 陪伴模块（视觉小说式）+ 浏览器 companion.html

---

FAS（Fascinator）的 **Companion Track**：让系统现在就能陪用户聊天、记录经历、
在游戏里互动。这一层的语言实现是**临时借用**的成熟方案（云端 LLM / 本地 Ollama、
OCR、ASR 等），全部经适配器接入，可按
[Fascinator 接口指南](../FAS-Cognitive/docs/FAS_INTERFACE_GUIDE.md)
逐个替换为 FAS 自建机制——替换语言方案不需要修改认知层。

依赖方向单向：本仓 → **FAS-Cognitive**（同级目录，或 `FAS_COG_ROOT` 环境变量指向）。
认知机制的实验状态以 `FAS-Cognitive/docs/COGNITIVE_MODULE_STATUS.md` 为准。

## 仓库结构

```
app.py                    Flask 服务与回合主管道（/api/nlp；迁移目标形态见
                          FAS-Cognitive/fas/companion/pipeline.py）
index.html → docs/legacy_frontend/  旧版图谱观测控制台（现挂 /console）
companion.html            陪伴 UI（精简/陪伴/认知观察三视图，浏览器版；
                          桌面主入口=Charon 的 Haru 模块）
qq_channel（FAS-Cognitive）QQ 通道（OneBot v11；默认封存 qq_enabled=false，
                          出站白名单硬锁，养号后可重开）
nlp_processor.py          LLM 编排（解析/生成/抽取三类后端）
llm_provider.py           语言网关：所有云端调用物理收口于 _create() 一处
ollama_backend.py         可选本地后端（默认关）
prompt_templates.py       任务模板（含 FAS_IDENTITY 身份声明——全仓唯一 persona
                          硬编码点；无台词库，不预设说话风格）
api_guard.py              HTTP 安全（回环免token / Origin 核验 / 执行写闸门）
chat_log.py 之外：chat_log_replay.py  对话日志与事故恢复工具
ear/                      听觉（FunASR Paraformer STT + emotion2vec + YAMNet）
eye/                      屏幕感知（RapidOCR + mss + YOLO）
vision/                   物体感知（SAM2 轮廓 + DINOv2/CLIP 嵌入 + FAISS）
scripts/ tests/           陪伴侧实验脚本与测试
data/llm_config.example.json  复制为 data/llm_config.json 填入你的 api_key
```

## 快速开始

```bash
pip install -r requirements.txt
cp data/llm_config.example.json data/llm_config.json   # 填入 api_key（文件不入库）
python app.py            # http://127.0.0.1:5000
pytest tests/ -q
```

可选外部壳：**Charon / PersonalTerminal**（Go+Wails 桌面控制台）可托管本进程、
代理全部 `/api/*`，并经 Bridge(127.0.0.1:17734) 接收 FAS 推送
（utterance 事件/toast/日记）。下行通道已接线（2026-10-09）：
`FAS-Cognitive/fas/companion/charon_bridge.py` 由 app.py 装配，本仓部署默认开启
（`config.companion_charon_enabled=True`；Charon 未运行时投递仅告警不反压，
`FAS_CHARON=0` 或 PUT /api/config 可关）。主动/提问话语会在 Charon 前端弹气泡。

## 缺件登记（临时占位，待补充选型）

| 缺件 | 现状 |
|---|---|
| TTS 语音输出 | 未接入（候选：Charon 前端 Web Speech API / 本地 TTS） |
| STT 实时麦克风流 | ear/ 目前只支持手动喂音频文件 |
| 正式搜索 API | actions/web_search.py 为 HTML 抓取临时方案（已支撑回合内被动搜索 + 好奇驱动自发检索 `_curiosity_web_explorer`，带相关性闸与限速；`FAS_NO_SELF_SEARCH=1` 可关） |

## 隐私红线

`data/`（除 example）与 `logs/` 一律不入库：真实图谱、对话记录、内部状态、
LLM 密钥均只存本机。发布前经扫描闸门核查（个人标识词、密钥模式）。
