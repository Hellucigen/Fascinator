# Fascinator — 认知图谱系统

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3+-green.svg)](https://flask.palletsprojects.com/)
[![Ollama](https://img.shields.io/badge/Ollama-LLM-orange.svg)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Prototype-red.svg)]()


> **基于转移注意力的知识图谱认知架构原型系统**
> 论文：*Fascinator: 基于统一知识图谱的认知架构* — Kailin Yan, 2025

本项目将声明性记忆（语义 + 情景）、程序性记忆与情感标记统一存储于单一知识图谱中，
通过激活扩散机制模拟人类注意力的转移与认知焦点的形成。

---

## 架构概览

```
                    ┌─────────────────────────────────┐
                    │        Fascinator 认知架构        │
                    ├─────────────────────────────────┤
  用户输入 ──────→  │  NLP 感知器 (Ollama LLM)         │
                    │  ├─ 言语行为分类 (5类)            │
                    │  ├─ 实体/关系抽取 → 三元组        │
                    │  └─ 断言子类: episodic/semantic  │
                    ├─────────────────────────────────┤
                    │  Embedding 检索 (FAISS + BGE)    │
                    │  └─ 语义相似节点 → 激活入口       │
                    ├─────────────────────────────────┤
                    │  激活扩散引擎 (Spreading Act.)    │
                    │  ├─ 注入激活值                    │
                    │  ├─ 沿边扩散传播                  │
                    │  ├─ 衰减 & Top-K 注意候选集       │
                    │  └─ 触发 procedural 节点执行      │
                    ├─────────────────────────────────┤
                    │  统一知识图谱 (JSON 持久化)        │
                    │  ├─ declarative-semantic (语义)  │
                    │  ├─ declarative-episodic (情景)  │
                    │  └─ procedural (程序性动作)      │
                    ├─────────────────────────────────┤
                    │  情景缓冲区 (Episodic Buffer)     │
                    │  └─ 遗忘/晋升/检索               │
                    └─────────────────────────────────┘
```

### 核心设计原则

1. **统一图谱存储**：三种记忆类型共享同一图谱结构，通过 label 字段区分
2. **激活扩散驱动**：认知过程均由激活扩散机制自然产生，无需硬编码逻辑
3. **显式可解释**：图谱节点/边/激活值全程可观测可追溯
4. **模块化可扩展**：Embedding 模型、LLM 后端、向量数据库均可替换

---

## 项目结构

```
Fascinator/
├── app.py                  # Flask 后端入口，所有 API 路由
├── graph_model.py          # 知识图谱数据模型：Node, Edge, KnowledgeGraph
├── diffusion_engine.py     # 激活扩散引擎：扩散/衰减/Top-K/Action Queue
├── nlp_processor.py        # NLP 感知器：Ollama LLM 驱动的言语行为解析
├── embedding_manager.py    # FAISS + BGE 语义嵌入检索层
├── episodic_buffer.py      # 情景缓冲区：短期经历存储/遗忘/晋升
├── seed_speech_acts.py     # 种子脚本：初始化基础设施节点与意图树
├── init_jieba_pos.py       # 种子脚本：从 jieba 词典导入实词节点
├── config.py               # 超参数默认配置（可运行时热更新）
├── knowledge_graph.json    # 主图谱持久化文件
├── index.html              # 前端 UI：Canvas 图谱可视化 + 控制面板
├── requirements.txt        # Python 依赖
├── bge-small-zh-v1.5/      # [本地] BGE 中文嵌入模型文件
├── data/faiss/             # FAISS 索引缓存目录
├── Knowledge/              # 外部知识库目录
├── backup/                 # 图谱备份目录
├── docs/paper/             # AGI 理论框架论文草稿（V1–V4，持续迭代中）
├── Try/                    # 实验性代码
├── prototype/              # Utopia：核心图谱引擎的清洁版原型（FastAPI 后端 + 静态前端），
│                           #   对应论文的统一知识图谱设计，是 graph_model/diffusion_engine 的先行版本
└── legacy/
    └── ear_standalone/     # "The Ear of Fascinator" 结课设计原版（听觉子系统前身），
                            #   含音乐分析流水线、Demucs 人声分离、说话人分离与 Gradio 演示；
                            #   其精简重构版已整合为 ear/ 模块并由 app.py 调用
```


---

## 快速启动

### 环境要求
- Python 3.10+
- [Ollama](https://ollama.com/)（本地运行 LLM）

### 0. 克隆仓库
```bash
git clone https://github.com/your-username/Fascinator.git
cd Fascinator
```

- 推荐模型：qwen2.5:7b-instruct-q5_k_m

### 1. 安装依赖
```bash
pip install flask flask-cors jieba langchain langchain-ollama
pip install sentence-transformers faiss-cpu numpy
```

### 2. 准备本地 BGE 模型
项目自带 bge-small-zh-v1.5/ 文件夹，无需额外下载。
自定义路径: set BGE_MODEL_PATH=D:/path/to/model

### 3. 启动 Ollama
```bash
ollama pull qwen2.5:7b-instruct-q5_k_m
```

### 4. 初始化图谱（首次）
```bash
python init_jieba_pos.py
python seed_speech_acts.py
```

### 5. 启动
```bash
python app.py
```
启动后会自动打开浏览器进入前端（http://127.0.0.1:5000）；
不需要自动打开就设环境变量 `FAS_NO_BROWSER=1`，或在 `config.py` 里把
`auto_open_browser` 设为 `false`。启动日志里同时打印前端地址与局域网地址
（后者可给同一网络下的其它设备用）。

---

## 自主认知与行动（Phase D）

Haru 能在**没有用户指令**时，从自身认知状态产生简单意图并尝试执行。
Minecraft 只是当前的具身环境：自主层只产生语义意图（observe/approach/follow/
explore/collect/rest/communicate/withdraw），由具身适配器执行并回传真实结果。
详见 [AUTONOMY.md](AUTONOMY.md)。

- 循环不新建线程：挂在持续认知循环的 tick 上（≈10s 一次），**全程零 LLM 调用**。
- 模式默认开启（`autonomy.mode_default`，可改 `off` 恢复旧行为）；模式不持久化，重启回到默认值；运行中 `/api/autonomy/mode` 随时关闭；用户交互会立刻让位并打断在飞动作（用户优先）。
- 意图必须有认知依据（图激活/驱动力/未知对象/未完成目标）；没有依据就如实 idle。
- 行动结果进图（`自主行动_*` episodic 节点）+ 情绪 + 表达抑制链 + 状态检测器。
- 不做攻击、不碰箱子/工作台等用户资产；失败原因原样上报，不假装成功。
- API：`/api/autonomy/{state,mode,pause,resume,stop,step,goals,log}`；
  前端右栏 **Auto** 标签页（状态/意图/候选评分/目标/日志 + ON/STOP/PAUSE/RESUME/STEP）。

---

## 对话通道（在哪里说话都能直接聊）

对话入口不只有前端网页：**任何"能收消息、能发消息"的环境都可以注册成通道**，
走的是同一条认知管线（通道只负责收发，认知逻辑只有一份）。

- 已内置 **游戏内聊天** 通道（`minecraft_channel.py`）：你在游戏聊天框里说的话会
  进入正常处理流程，她的回复也直接写在游戏聊天框里（清洗 Markdown、限长单行）。
- 身份判定：自己说的话过滤（否则自己回自己）；**用户的消息**走完整回合并回复；
  **其他人的消息**默认只观察不插嘴（记录在通道事件里），**被点名才回答**。
  这些都在通道画像（profile）里，不写死在代码里。
- 场合约束：非 Web 通道会自动给回复加"即时聊天场合"的约束（短、单行、不要
  Markdown），并记录 `cycle_id` 便于回溯。
- 送达诚实：bot 未连接 / 发送失败都会如实记录在通道事件里，不会"看起来发了"。
- API：`/api/channels/state`、`/api/channels/<id>`（启停）、`/api/channels/<id>/send`（测试发一句）、
  `/api/channels/recent`。前端在 **Auto** 面板的「对话通道」模块里（含启停开关与测试发送）。

---

## 扩散能量模型（发射即转移）

注意力扩散默认**能量守恒**：节点把激活值发给邻居时，自己扣掉发出的部分
（`config.emission_transfer=1.0`，每次最多发出自身激活的一半 `emission_ratio=0.5`）。
旧的"发射是复制"语义会让全网总能量每步凭空翻倍，唯一平衡点就是所有节点撞上上限
（实测空闲 40 tick 内 733 个节点全亮、374 个钉在 cap 5.0，扩散统计每 tick 完全相同）——
那不是认知，是一个卡住的固定点。

本轮由 `activate_from_inputs` 点亮的**输入节点是外部刺激源**：本轮内免于转移、
照常向外供能，因此输入相关节点与能力节点仍稳居 Top-K；回合结束清锚点
（`engine.clear_anchors()`），空闲期没有刺激源，场自然排空。

| | 修复前 | 修复后（空闲 2 分钟） |
|---|---|---|
| 活跃节点 / 满格节点 / 总能量 | 581 / 374 / ~2868 | 423 / **0** / 12.0 |

回归护栏：`tests/test_energy_conservation.py`（空闲长跑不饱和、对照组的旧语义
确实会饱和、回合内排序不被压平、锚点只在回合内有效）。

---

## 认知调节（锁 / 状态检测器 / 触发器）

三项基础认知机制：锁控制"某个认知对象是否参与某个认知过程"，状态检测器维护对象
状态并在**变化**时产生事件，触发器按**结构化条件**评估事件并派发认知动作。
三者全程确定性（无 LLM 参与运行），详情见 [COGNITIVE_REGULATION.md](COGNITIVE_REGULATION.md)。

- 锁：`blocking`（不参与扩散）与 `non_blocking`（照常传播但不进 Top-K/回答区）
  两种语义；作用范围可选 `diffusion` / `topk` / `action` / `all`。
- 状态：相同状态重复提交不产生事件；校验失败不污染当前状态。
- 触发器：条件必须是结构化表达式（如 `{"op":"gte","field":"current","value":10}`），
  支持冷却、一次性、优先级与触发记录。
- 前端：右栏 **Reg** 标签页管理三者；节点详情面板可对选中节点一键加锁。
- API：`/api/regulation/{state,locks,monitors,triggers,events}`。

---

## 核心概念

### 记忆分类 (节点 label)
| Label | 含义 | 示例 |
|-------|------|------|
| declarative-semantic | 语义记忆：客观事实/概念 | "阿司匹林" |
| declarative-episodic | 情景记忆：个人经历 | "用户参加六级考试" |
| procedural | 程序性记忆：可执行动作 | "存入记忆" |

### 激活扩散公式 (论文 5.1.1)
```
a_uv(t) = w_uv + r(u,v,t)
Δa(u→v)(t) = a(u,t) * a_uv(t) * β / |N+(u)|
a(v, t+1) = (1-λ) * a(v,t) + Σ Δa(u→v)(t)
```

### 认知循环
1. 感知: 用户输入 → LLM 解析 → Embedding 匹配
2. 注入: 匹配节点获得初始激活
3. 扩散: 激活沿边传播至稳定
4. 聚焦: Top-K 节点成为认知焦点
5. 行动: procedural 节点激活>theta_action 时执行
6. 衰减: 每步按 lambda_decay 消退


---

## API 文档

### 激活扩散
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/activate | POST | 注入激活值 |
| /api/diffuse/step | POST | 单步扩散 |
| /api/diffuse/round | POST | 完整扩散轮 |
| /api/diffuse/start | POST | 启动自动扩散 |
| /api/diffuse/stop | POST | 停止自动扩散 |
| /api/topk | GET | Top-K 候选集 |

### 节点/边 CRUD
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/nodes | GET/POST | 列出/创建节点 |
| /api/nodes/<id> | GET/PUT/DELETE | 查/改/删节点 |
| /api/edges | GET/POST/PUT/DELETE | 边增删改查 |
| /api/search | GET | 关键词搜索 |
| /api/graph | GET | 图谱渲染数据 |

### 行动队列
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/actions/queue | GET | 行动队列 |
| /api/actions/execute | POST | 执行行动 |
| /api/actions/log | GET | 执行日志 |

### NLP 感知
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/nlp | POST | 文本解析+图谱激活 |
| /api/nlp/logs | GET | 处理日志 |
| /api/nlp/answer | POST | 基于Top-K生成回答 |

### 学习模块
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/learning/expand | POST | LLM扩展关联子图 |
| /api/learning/import | POST | 审核后并入主图谱 |

### 其他
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/episodic/all | GET | 情景缓冲区快照 |
| /api/embedding/search | GET | 语义检索 |
| /api/embedding/stats | GET | 索引统计 |
| /api/config | GET/PUT | 查看/更新配置 |

---

## 超参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| lambda_decay | 0.05 | 每步激活衰减率 |
| beta_spread | 1.0 | 扩散传播增益 |
| k_top | 20 | Top-K候选集容量 |
| theta_threshold | 0.01 | 扩散终止阈值 |
| theta_action | 0.5 | procedural触发阈值 |
| max_depth | 6 | 最大扩散深度 |
| cosine_threshold | 0.6 | 语义匹配阈值 |
| auto_interval | 1.5 | 自动扩散间隔(秒) |
| edge_relation_factor | 0.75 | 关系名激活系数 |
| activation_max | 5.0 | 节点激活上限 |
| edge_decay_factor | 0.5 | 边衰减系数 |
| render_full_max_nodes | 2500 | 全图渲染上限 |
| render_neighbor_depth | 2 | 邻域渲染深度 |


---

## 模型配置

### BGE Embedding (语义检索)
使用 bge-small-zh-v1.5 (512维)，项目自带本地模型文件。

路径解析优先级:
1. 环境变量 BGE_MODEL_PATH
2. 项目根目录 bge-small-zh-v1.5/ 文件夹（已自带）
3. HuggingFace 远程: BAAI/bge-small-zh-v1.5

### NLP LLM
默认使用 Ollama 本地模型 qwen2.5:7b-instruct-q5_k_m。

### 程序性节点沙箱
execution 字段为 Python 代码，在受限沙箱执行。
可访问变量: graph, node, result
可用内置: print, len, range, min, max, sum, sorted, str, int, float, bool, dict, list, set, tuple, enumerate, zip

---

## NLP 言外行为分类

| 类别 | 说明 | 反应链 |
|------|------|--------|
| 断言类 | 陈述/描述事实 | → 知识存储 → 存入记忆 |
| 指令类 | 命令/请求/提问 | → 询问处理 → LLM回答 |
| 承诺类 | 承诺/意图/计划 | → 意图注册 → 行动计划 |
| 表达类 | 情感/态度 | → 情感记录 → 情绪节点 |
| 宣告类 | 宣告/命名/声明 | → 声明注册 → 写入图谱 |

### 意图分类树
```
ROOT
├── 断言类 → 事实陈述/经历叙述/观点表达/状态描述
├── 指令类 → 操作指令/查询指令/对话指令/控制指令
├── 询问类 → 知识询问/情景回忆/事实确认/原因分析/计划生成
│   └── 情景回忆 → 时间/人物/地点/事件线索回忆
├── 承诺类
├── 表达类
└── 宣告类
```

### 数据流示例
```
用户: "阿司匹林是什么药"
  → NLP: nodes=["阿司匹林","药"], edges=[...], speech_act="指令类"
  → Embedding: 语义匹配图谱节点 "阿司匹林"
  → Diffuse: 激活沿边传播 → Top-K: ["阿司匹林","非甾体抗炎药","LLM回答"]
  → Execute: "LLM回答" 节点触发
  → 回答: "阿司匹林是一种非甾体抗炎药..."
```

---

## 注意事项

- 图谱每次操作后自动保存到 knowledge_graph.json
- NLP 依赖 Ollama 本地模型，请确保服务运行中
- 程序性节点代码在受限沙箱中执行，仅允许白名单函数
- 图谱节点>2500时前端自动切换邻域渲染(默认2级深度)
- FAISS索引首次构建后缓存到 data/faiss/，重启无需重建
- backup/ 目录保留历史图谱版本


---

## 开发与贡献

### 目录说明

| 目录 | 用途 | Git 追踪 |
|------|------|----------|
| `Try/` | 实验性代码（LangChain, OneKE, UIE 等尝试） | ✅ 上传 |
| `backup/` | 图谱自动备份（每次保存生成） | ❌ gitignore |
| `data/faiss/` | FAISS 向量索引缓存 | ❌ gitignore |
| `Knowledge/` | 外部知识库导入目录 | ❌ gitignore |
| `knowledge_packs/` | V4 多图谱 Pack 存储 | ❌ gitignore |
| `bge-small-zh-v1.5/` | BGE 嵌入模型文件（~400MB） | ❌ gitignore |

### 首次开发设置

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/Fascinator.git
cd Fascinator

# 2. 创建虚拟环境
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 下载 BGE 模型（首次运行会自动下载，也可手动）
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"

# 5. 启动 Ollama 并拉取模型
ollama pull qwen2.5:7b-instruct-q5_k_m

# 6. 初始化图谱
python init_jieba_pos.py
python seed_speech_acts.py

# 7. 启动服务
python app.py
```

### 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### 技术报告

完整的技术架构说明请参阅 [Fascinator_技术报告.txt](Fascinator_技术报告.txt)。

---

## 许可证

本项目采用 [MIT License](LICENSE) 开源。



---

*Kailin Yan · Fascinator 认知架构原型 · 2025*
