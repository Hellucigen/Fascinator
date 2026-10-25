# 参考文献记录：对话记忆 / 状态跟踪 / 认知记忆架构

> 用途：FAS / Haru 陪伴认知系统研发过程中实际核验过的文献，供后续写论文引用。
> 核验方式说明：以下条目在 2026-10-19 的研究对照审查（见会话审计记录）中**逐条访问官方页面并核对摘要级内容**；未通读全文、未复现实验。论文引用时请以"摘要级核验"为界标注你的使用依据，正式引用前建议再对照 PDF 正文。
> 关联工程改动：每条附"本仓库对应物"，方便写 related work / ablation 时回链证据。

## 一、对话状态跟踪与历史选择

### [1] DiCoS-DST — Beyond the Granularity: Multi-Perspective Dialogue Collaborative Selection for Dialogue State Tracking
- 作者：Jinyu Guo, Kai Shuang, Jijie Li, Zihan Wang, Yixuan Liu
- 出处：ACL 2022（60th Annual Meeting, Long Papers），pp. 2320–2332
- URL：https://aclanthology.org/2022.acl-long.165/
- 核心主张（摘要级）：不同 slot 需要不同历史粒度；按 slot 用三视角（slot 名显式关联 / 与当前轮相关 / 隐式提及推理）协作筛选历史，仅选定内容进入 State Generator；MultiWOZ 2.1/2.2 当时 SOTA。
- 对 FAS 的意义："给候选选相关历史"而非固定最近 N 条——本项目 said_recent/近期对话 从纯近因改为相关性优先时引用的思想来源（该改动尚未实施，属设计依据）。
- 局限提示：slot-based DST 面向任务型对话，与 Haru 的开放域认知架构不同构，只能借"粒度选择"机制，不能借其状态本体。

### [2] "Do you follow me?" — A Survey of Recent Approaches in Dialogue State Tracking
- 作者：Léo Jacqmin, Lina M. Rojas Barahona, Benoit Favre
- 出处：SIGDIAL 2022（23rd Annual Meeting），pp. 336–350；DOI: 10.18653/v1/2022.sigdial-1.33
- URL：https://aclanthology.org/2022.sigdial-1.33/
- 核心主张（摘要级）：text-to-text 范式主导；泛化性（generalizability）仍欠探索。
- 对 FAS 的意义：作为"为什么不建独立 DST 状态机"的反面依据——本项目图谱原生状态（focus 指针、表达事件、回应边）承担同样职责。

## 二、长程对话记忆评测

### [3] LoCoMo — Evaluating Very Long-Term Conversational Memory of LLM Agents
- 作者：Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal, Francesco Barbieri, Yuwei Zhang*（页面署名 Yuwei Fang）
- 出处：ACL 2024（62nd, Long Papers），Bangkok，pp. 13851–13870
- URL：https://aclanthology.org/2024.acl-long.747/
- 核心主张（摘要级）：LoCoMo 数据集（单会话约 600 轮 / 16K token、最多 32 个会话），基准任务=QA、事件摘要、多模态对话生成；长上下文与 RAG 有改善但显著落后人类。
- 对 FAS 的意义：证明"堆材料进 prompt"救不了长程一致性——支撑本项目"表达来源约束+账本"路线而非扩上下文窗口。
- ⚠️ 重要辨析：**本项目的任务书曾把 LongMemEval 误记为本文的基准。LongMemEval 是另一个独立工作**（Wu et al., ICLR 2025，"LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory"，arXiv:2410.10813——此条本轮未访问核验，引用前请自行对照官方页面），LoCoMo 与 LongMemEval 常被后续论文并用（见 [5][6][7] 均同时报两者结果）。

## 三、记忆管理与记忆架构

### [4] RMM — In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents
- 作者：Zhen Tan, Jun Yan, I-Hung Hsu, Rujun Han, Zifeng Wang, Long Le, Yiwen Song, Yanfei Chen, Hamid Palangi, George Lee, Anand Rajan Iyer, Tianlong Chen, Huan Liu, Chen-Yu Lee, Tomas Pfister
- 出处：ACL 2025（63rd, Long Papers），Vienna，pp. 8416–8439
- URL：https://aclanthology.org/2025.acl-long.413/
- 核心主张（摘要级）：固定记忆粒度与固定检索都失配；前瞻反思=utterance/turn/session 多粒度摘要入库，回看反思=按 LLM 引用证据在线 RL 修检索；较无记忆管理基线 >10% 准确率。
- 对 FAS 的意义："回看修正检索"与本项目 ExprFB（回应关系后验建立）同方向；RL 组件未借鉴（架构代价），借鉴点在多粒度组织——FAS 已有 episodic buffer（轮级）/反思（会话级）粗对应。

### [5] Zhou & Han — A Simple Yet Strong Baseline for Long-Term Conversational Memory of LLM Agents
- 作者：Sizhe Zhou, Jiawei Han
- 出处：arXiv:2511.17208（v1 2025-11-21，v2 2025-12-11）
- URL：https://arxiv.org/abs/2511.17208
- 核心主张（摘要级）：neo-Davidsonian 事件语义——"event-like propositions"（参与者+时间线索+最小局部上下文捆成短命题）、会话拆 enriched EDU、异构图、可选图传播聚合证据；在 LoCoMo/LongMemEval 以短 QA 上下文达到或超过强基线。
- 对 FAS 的意义：与"图谱即记忆"路线最同构的验证性工作；本项目 话语_/表达_ 节点就是它的"命题"，其字段捆扎方式（时间入命题、参与者显式）是表达事件字段化的依据。

### [6] TSM — Beyond Dialogue Time: Temporal Semantic Memory for Personalized LLM Agents
- 作者：Miao Su, Yucan Guo, Zhongni Hou, Long Bai, Zixuan Li, Yufei Zhang, Guojun Yin, Wei Lin, Xiaolong Jin, Jiafeng Guo, Xueqi Cheng
- 出处：arXiv:2601.07468（v1 2026-01-12，v2 2026-09-02）
- URL：https://arxiv.org/abs/2601.07468
- 核心主张（摘要级）：现有记忆按"对话时间"而非"事件时间"组织，且偏时点记忆丢持续信息；TSM 建语义时间轴、把时间连续+语义相关的内容并成 durative memory、检索带时间意图；LongMemEval/LoCoMo 绝对提升最高 12.2%。
- 对 FAS 的意义：理论化了本项目同季修的两处——MEMORY_EXTRACT 的"当下意愿 vs 稳定偏好"区分（时点 vs 持续态）、事件节点 event_time 字段与时间桶挂接（temporal_awareness）。

### [7] CogMem — From Retrieval to Reconstruction: Constructing Evolvable Cognitive Memory for Long-Term Dialogue
- 作者：Zirui Liao, Zhengxian Wu, Zhuohong Chen, Yunyao Yu, Xiaoyu Liu, Yifan Xu, Haoqian Wang
- 出处：arXiv:2610.11314（2026-10-08），EMNLP 2026 main conference（21 页；页面含代码链接 github.com/Silent-Rain02/CogMem）
- URL：https://arxiv.org/abs/2610.11314
- 核心主张（摘要级）：PEC²F 图式（Person-Event-Concept-Claim-Fact 分离）；RAG 把记忆当被动的根因=分不清主观主张与客观记录、跨会话证据断链；增量入图带 provenance、归并出高层事实、冲突归入带时间域的 Claim 视图；检索时用四算子（anchoring / traversal / intersection / evidence grounding）**重建**上下文；LoCoMo/LongMemEval 强结果（多跳/时序/知识更新尤显）。
- 对 FAS 的意义：与本项目哲学最接近——"检索→重建"即"图谱真参与决策而非拼文本"；claim≠fact 的分离正是"知道≠经历、说过≠做过"不变量的文献对应物。写论文时可作为架构同源工作重点对表。

## 四、本项目产生的可引用工程结论（非文献，供 discussion 段回链）

- 表达来源三不变量的实现教训（2026-10 系列审计）：①第一人称心理活动节点若与情景记忆共用标签体系，渲染兜底会把"念头"标成"经历"，诱发 confabulation（12:47 实例：思考节点→〔经历片段〕→"我刚才在Minecraft里闲逛"，当日无任何 Minecraft 活动记录）；②"没记录=没发生"的完整性声明恰在空账本时被整段省略——最缺证据的时刻声明消失；③去重必须按内容身份（材料戳）而非时间窗——固定窗被认知重铸周期绕过（六连换皮实例）。
- 相关数据/测试锚点：`logs/prompt_capture.jsonl`（逐字材料取证）、`FAS-Cognitive/tests/test_episodic_provenance.py`（17 项）、`tests/test_rekindle_evidence_filter.py`、`FAS-Cognitive/tests/test_echo_gate.py`、`data/living_ledger.json` 的 consumed_evidence 自消费实锤。

## 使用提醒

- [1]-[4][7] 元数据（作者/页码/venue）来自 ACL Anthology 页面，可信度高；[5][6][7] 的"核心主张"截至摘要，正文实验细节未核。
- LongMemEval 条目按记忆给出、未访问核验（标 ⚠️），引用前必须自查。
- 若论文中要引本项目作为系统案例：以上页面访问日期统一记 **2026-10-19**。

---

# 第二部分 · 调制机制与情绪-行动文献（2026-10-19 追加，调制审计轮）

> 追加原因：调制机制审计（A-J 报告）与最小验证实验需要与文献对表；六篇均本轮实际核验，核验等级逐条注明。上一轮实验记录见文末 E3。

## 书目（全部本轮访问核验）

1. **Ridderinkhof, K.R. (2017). Emotion in Action: A Predictive Processing Perspective and Theoretical Synthesis.** *Emotion Review* 9(4):319–325. DOI 10.1177/1754073916661765；PMC5652650（**全文级**：摘要+IMPPACT 机制+引句）。Frijda 行动准备性 × 前向模型：评价→动机→初级运动捕捉→代价/收益估值→PE 更新激励值；明确否认硬连线 S-R。
2. **Lee, K.M., Ferreira-Santos, F., & Satpute, A.B. (2021). Predictive processing models and affective neuroscience.** *Neuroscience & Biobehavioral Reviews* 131:211–228（在线 2021-09-10；任务书标 2022，官方记录以 Crossref/PMC 为准）。PMC9074371（**全文级摘要**）。精度=逆方差加权；反向推断与退化性批判。
3. **Reisenzein, Hudlicka, Dastani, Gratch, Hindriks, Lorini & Meyer (2013). Computational Modeling of Emotion: Toward Improving the Inter- and Intradisciplinary Exchange.** *IEEE Trans. Affective Computing*, 2013-07. DOI 10.1109/T-AFFC.2013.14（**元数据级**：Crossref 确认作者/刊名/日期；正文付费墙未读，不引其具体论点）。
4. **Broekens, DeGroot & Kosters (2008). Formal models of appraisal: Theory, specification, and computational model.** *Cognitive Systems Research*. DOI 10.1016/j.cogsys.2007.06.007（**元数据级**：S2 确认；摘要空、正文未读）。
5. **Pezzulo, Parr & Friston (2024). Active inference as a theory of sentient behavior.** *Biological Psychology*. DOI 10.1016/j.biopsycho.2023.108741（**元数据+摘要级**：OpenAlex 确认；全文未读）。综述谱系 Helmholtz→预测编码→层级生成模型。
6. **Castellanos, Osuna Cuen, Padilla & Rodríguez (2026). Systematic guidelines for extending the appraisal process in computational models of emotion.** *Cognitive Systems Research* 96, 2026-04. DOI 10.1016/j.cogsys.2026.101442（**存在性确认**：Crossref 记录在；**内容不可得**——一切结论不以其为据）。

## 三类内容严格分层（本轮结论的证据归属）

**文献明确支持的（读到的部分）：** 情绪通过改变候选行动的**估值地形**参与选择而非触发固定反应（Ridderinkhof，全文级）；精度加权是"信号影响力≠信号内容真实性"的正式概念（Lee et al.，全文级摘要）。其余四篇仅到元数据/摘要级，不得引具体主张。

**FAS 代码已实现+已测试的事实（file:line 见审计记录）：**
- 调制=混合式：图表达关联（调制边真源、删边回收系数），过程级解释器执行（ModulationLayer/NetworkField/SN/graph_biases）；参数全为过程级（扩散预算/阈值/topk/温度），不针对语义。
- 情绪→行为是**竞争式**（激素增益 0.6-1.4 只缩放表现性行为分、affordance 边、驱力偏置）——与 Ridderinkhof 的"改估值不改接线"结构对应；FAS **没有**恐惧→逃跑式硬编码（grep 级事实）。
- **情绪/激活/激素对事实置信度零写入**（全库 confidence 写点穷举+运行时探针）——即 Lee et al. 区分的 precision/confidence 分离，FAS 在数据层已满足。
- 受体敏感度是真实计算（倒U曲线+计数敏化+习惯化+不应期，internal_state 对象侧）。
- 行为学习只缩放学习率（reward 红线），期待值+RPE 已存在（ALPHA_EXPECT=0.15）——主动推断的"预期vs结果"原语有，生成模型没有；**不得声称实现主动推断**。
- 缺口（代码事实）：行动评分无后果预测项（无 forward model）；情绪形成无显式目标评价步骤（共振检测≠appraisal，对照 Broekens 的问题域）。

**工程推论（无文献直接背书）：** FAS 架构选择"保留、不重构"；僵尸清理/投影刷新/P4P5 去重为低成本项。

**待验假设：** 喜欢边自然膨胀速率在生产会话长度下的实际幅度（实验只证机制，速率未标定）；intero 通道生产有效性；行动前向模型（IMPPACT-lite）与评价层的收益。

## E3 · 最小验证实验记录（2026-10-19，全部离线/内存/临时文件）

| | 假设 | 方法 | 结果 | 可复现 |
|---|---|---|---|---|
| A | Hebbian 封顶跨会话稳定（旧 docstring） | 真实 `_hebbian` × 30 次"重启"（Edge 构造往返），200 共激活/会话 | **证伪**：0.4→每会话精确×1.5→2.30；基线只在运行时 | `FAS-Cognitive/tests/test_hebbian_bounds.py`（钉修复后行为：10 重启封顶 0.6） |
| B | 喜欢边纯共激活可无界抬欲望 | 同上，relation=喜欢、零兑现 | **证实机制**：0.5→2.30；appeal 直读该边权 | 同上（封顶 0.75）；速率未在生产标定 |
| C | 情绪不改事实置信 | 恐惧满激活 40 轮真实 `diffuse_step`，前后快照 confidence | **支持**：零漂移；情绪通道只进激活/排序 | 临时脚本（/tmp/exp_conf.py，可丢弃） |

**修复（实验驱动）**：`diffusion_engine._hebbian`——首见基线持久化 `edge.extra_attrs["hebb_w0"]`（to_dict/from_dict 全量往返）+ 绝对钳 ±2 + `a_u<=0` 早退 + docstring 改实话。存量已膨胀边原地钉死（测试覆盖）。白名单**保留** emotional_relation（1.5× 封顶内=合理联想强化；无界才是病灶——任务原则"区分自然偏好形成与无界膨胀"）。

**未修（记录）**：P3 启动投影（影响限于会话中图编辑，低频）；P4 兴趣双计/P5 激活双注入（调参决策，先测幅度再动）；P7 `/api/actions/execute` 遗留端点（受信手动工具定性）；P8/P9/P11 僵尸通道（行为中性）；因果晋升无降级（设计悬案，待 graph_doctor 数据）。
