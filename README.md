# Fascinator

<div align="center">

**扩散激活知识图谱 × 情境记忆 × 自主表达的桌面 AI 伙伴**

**Haru** 的认知引擎 —— 扩散激活知识图谱驱动她形成念头、攒出表达、
在授权时段自主探索。无框架 · Python + Flask

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

## 能力与扩展（全部默认关，开启需授权）

图谱以"一切皆图"记录她能做什么——每项能力是一个接 Self 的原子能力节点
（`capability_registry`），她能自述、可被语义召回。近期新增能力默认全部关闭，
关闭态与"从未接入"逐字节等价（零网络、零副作用、零计费，可从账本证伪）。

- **多模态感知**（`llm_provider` 网关，总闸 `multimodal_enabled` + 子闸）：
  视觉语义理解（看图表/界面，比 OCR 进一步）、音频理解、图文混合输入。
  复用现有 Qwen 凭证，无新依赖。
- **桌面操作**（`ui_desktop` + `click_policy` 三层白名单，总闸 `desktop_control_enabled`）：
  🟢 安全（白名单应用内语义点击/窗口操作）可自动，🟡 位置（像素点击）与
  🔴 敏感（非白名单 / 命中删除·付款·发送·登出等词 / 打字）**必须你在前端批准**。
  视觉定位点击闭环 `POST /api/desktop/locate_click` 结构性强制走待批——不存在无人
  复核的自动执行。fail-closed：判不了即拒。执行成功原子记一条 ACTION 经历进她的自我叙述。
- **插件协议**（`docs/PLUGINS.md`）：感知/事件插件（`POST /api/activate` 喂图）、
  生活活动插件（`data/activities_plugins/`）、技能插件（`data/skill_plugins/`，需授权）。
- **QQ 通道**（OneBot v11，`qq_enabled`）：白名单硬锁 + 同文去重 + 主动镜像只放行
  proactive；当前因风控养号封存中。
- **语音**：本地 kokoro-onnx TTS（日语双轨）、ear/ FunASR 中文 ASR + emotion2vec。

> ⚠️ 上述"能操作电脑/能上云"的能力默认一律关闭——她的默认状态是只读陪伴，
> 越界动作每一步都要你点头。这是有意为之，不是没做完。

## 缺件登记（临时占位，待补充选型）

| 缺件 | 现状 |
|---|---|
| STT 实时麦克风流 | ear/ 以文件/分段喂入为主，持续实时流待打磨 |
| 正式搜索 API | actions/web_search.py 为 HTML 抓取临时方案（已支撑回合内被动搜索 + 好奇驱动自发检索 `_curiosity_web_explorer`，带相关性闸与限速；`FAS_NO_SELF_SEARCH=1` 可关） |

## 隐私红线

`data/`（除 example）与 `logs/` 一律不入库：真实图谱、对话记录、内部状态、
LLM 密钥均只存本机。发布前经扫描闸门核查（个人标识词、密钥模式）。
