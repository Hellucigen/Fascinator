# PAPER_RESTRUCTURE_REPORT — 投稿前最终论文重构(2026-10-01)

> 核心原则(用户指令,逐条执行):实际代码与已完成的实验结果是真实系统的唯一依据。不修改任何实验结果;不删除失败实验;不修改核心扩散算法;不改基线;不调参;不作与证据不符的显著性声称;不重跑实验"找好看的结果"。C34 v1 无效装配不得当有效结果;core incremental value 的 H3 被预注册判定拒绝(Holm p=1.5e−9)必须以负结果呈现;Beacon D-flat 结果不得解释为扩散优势;不声称 AGI/全面优越 RAG/扩散普遍优于 flat。不保护旧论文,保护研究真实性。交付:中英双语、编译通过、图表精美无错。

---

## 1. 原论文主要问题(审计结论)

原论文(`FAS_Paper_I/main_zh.tex` + `main.tex`,2026-09-30 版,14 章)已高度诚实(含装配审计、S/Q/U 声明矩阵、否定结果专章),但存在以下结构性缺陷:

| # | 问题 | 严重度 |
|---|---|---|
| P1 | **缺 core incremental value 研究**: 最新、最大样本、预注册的机制收官实验(34,016 runs,4×50 配对种子)完全未整合。这是"扩散 vs flat"问题的最强直接证据(H3 REJECTED,ΔJCG<0,0/200 反超),论文却只字未提,主线"机制与边界刻画"散见各节,读者无法判断扩散相对 flat retrieval 的增量价值 | 高 |
| P2 | 实验组织是"按实验族"而非"按科学问题": 读起来像实验流水账(§5 获取→§6 持久→§7 消费→§8 动力学→§9 否定),缺少"FAS 解决什么问题→证据链"的主线 | 高 |
| P3 | 否定结果的语义定位不足: §9 是"否定与边界"平铺,没有集中的"为什么扩散并不总是有帮助"的机制论证(flat 足够的情形、多输入稀释、共享枢纽例外各散处) | 高 |
| P4 | 缺 Production vs Experimental Path 的显式说明: 只在 §11.6"实验口径与生产口径"一段带过,读者不能在正文一处看到"哪些实验跑在完整生产系统上、哪些是机制级隔离、哪些是沙箱/装配、哪些用 LLM、哪些零 LLM" | 中 |
| P5 | Figure 集未按新叙事设计: 无 graph ontology 图、无完整真实案例图、无统一证据矩阵/森林图、无"扩散适用边界"图;共享枢纽(唯一正差分)无图 | 中 |
| P6 | Table 集不完整: 无"主要行为结果"表、"机制层结果"表、"失败/限制案例"表、"实现→声明审计"表(T6 尤其重要,用户点名) | 中 |
| P7 | 实现状态表与代码有 3 处出入: ①"激素节点架构"记为未实现,但调制器已经是图公民(modulator_subgraph.py:91-183,12 镜像点+调制目标靶点+边即系数真源); ②"外部知识获取"记为未实现,但 web_search 动作节点已在生产(actions/web_search.py:84); ③"情景缓冲器"笼统列入未实现,但 episodic_buffer.py 本体(容量/遗忘/检索/晋升)已实装 | 中 |
| P8 | 摘要与贡献未反映最新证据分层: 4 条贡献太散,未按用户指定的 4 条上限重构;摘要缺 ΔJCG 负结果与共享枢纽例外 | 低 |

**未发现的账实问题**: 逐数字核对结果(见 §3 矩阵),正文数字全部可溯源、无一篇已发表数字与实际档案冲突。用户点名的禁行声称(AGI/全面优于 RAG/diffusion 普遍更优)在现稿中均不存在。C34 v1 无效记录已如实呈现。Beacon 的 D-flat 限制已在记忆/审计中标注,但论文正文尚未包含 Beacon(新结构 §7.1 补齐)。

## 2. 新论文主线

**主题句**: FAS 的当前实证贡献是——在统一认知图谱上,具身交互经历经证据加权写回转化为持久、可复用的关系知识,并经账本/事件框架/再激活通道以可测、确定性的方式抵达行为;传播激活是这一知识访问域的运行机制,其相对 flat retrieval 的增量价值是**结构依赖的**(在共享枢纽汇聚拓扑下有方向性优势,在一般相关检索与抗噪任务上没有优势)。

**叙事弧**(不再是实验流水账):
1. 问题:长生命周期具身智能体的"日志 vs 巩固"鸿沟(§3 Problem & Design Goals)。
2. 方案:统一图谱 + 写回 + 激活访问的架构(§4),经历→知识→行为闭环(§5)。
3. 证据:持久关系知识复用(§7.1,Beacon)→ 持久与迁移(§7.2)→ 激活机制运行与极限(§7.3,四条件+JCG+ΔJCG)→ 拓扑依赖行为(§7.4,共享枢纽+关系方向)→ 系统级证据(§7.5)。
4. 边界理论化:为什么扩散并不总是有帮助(§8,flat 足够/多输入稀释/共享枢纽例外/信息不对称条件)。
5. 讨论/局限/未来(§9-11),结论(§12)。

## 3. Claim → Implementation → Experiment → Evidence 矩阵

颜色规则:GREEN=有直接实验支持、可作正文主声明;YELLOW=限定成立(局部/装配层/机制层);GRAY=未验证/仅机制现象;RED=已被实验否定(写为负结果)。证据层次:表示层(L1)/机制层(L2)/行为层(L3)。数字已逐一核对(来源文件见各单元格,"✓"=本重构期已亲核)。

### 3.1 GREEN — 直接支持(正文主声明)

| ID | 声明 | Implementation | Experiment(条件/样本) | Evidence(数字) | 来源 ✓ |
|---|---|---|---|---|---|
| G1 | 支架下经历→新动作-效果关系结构(非预写入) | episodic_buffer.py + experience.py:767 promote_to_kg(操作:/变化:节点+导致边+mark_active) | 写回隔离 B1 vs B2(同经历、单开关;8 轮实践) | B1 终图 0 个 vs B2 13 个 op/change 节点;15 条晋升=11 实质+4 退化(2 条窗污染∈11)+ | PAPER_FACT_DATABASE.json A2 ✓ |
| G2 | 学习结构跨 episode 持久并被新情境再激活 | 图 save/load 双继承(结构+激活值 graph_model.py:725-816) | G0/G1/G2 跨情境(n=5) | G0 再激活 4/12 标记;G1(扁平化)0/8;G2 0/0 | fact DB G_transfer ✓ |
| G3 | 账本通道知识改变行动选择 | internal_state 奖赏台账+自主层试做账 + 先验加成 ±0.05 | 实验 C Transfer vs No-Transfer(n=5) | 13 tick/8 动作 vs 16 tick/9;首动 birch→oak 翻转 5/5 | fact DB C_transfer_prior_campaign ✓ |
| G4 | 事件框架通道失败经验改变行动选择(装配层) | action_system.py:1033-1168 _write_event_frame;production enabled=False | D/C20e/C20g(n=5/4) | 首动 5/5 翻转;真实失败回执 17→15 tick;超时暂态统计静默下图为唯一留痕 | 实验 D 族 ✓(论文正文) |
| G5 | 多输入收敛机制真实运行 | diffusion_engine.py(机制 falsification 663-run 验证参考模型) | core incremental value(C-1..C-4,4×50 配对种子) | JCG>0 200/200;≥2 输入 MRR@1=1.0;combo 激活 0.7832>单输入 0.6265 | statistics.csv ✓ |
| G6 | 持久关系知识复用——信息不对称下行为收益 | 生产图+激活,FAS 上下文 | Beacon A10(n=20×4) | FAS 20/20;direct 0/20;D-noact 0/20;McNemar p=2e−6;首动 gather 20/20 | beacon_v1/analysis_final.json ✓ |
| G7 | 关系方向语义限制配方图传播(机制诊断) | _edge_direction(diffusion_engine.py:370-386) | 双向投影 B vs 生产图 F(3 注入×10 种子=60 runs) | ρ 0.325→0.645(p=0.001953,21 检验全该值,r=0.886);sink 1.0;reach2 0→9-12 | paired_statistics.csv ✓ |
| G8 | 标量情绪调制传播动力学且可关断 | 调制增益(生产每拍) | C-emo(n=5) | 质量 49.8/52.5/57.4 单调;禁用≡中性逐位一致 | fact DB C_emo ✓ |
| G9 | 机制表=必要支架;零先验锁定 | 机制表(配方/方块) | P0/P1/P2(n=25 episode) | P0 0/25 但 +29 节点;P1=P2 25/25 @4 | fact DB J_prior ✓ |

### 3.2 YELLOW — 限定成立或仅机制级

| ID | 声明 | 限定语 | Experiment | Evidence | 来源 ✓ |
|---|---|---|---|---|---|
| Y1 | 扩散产生独特知识访问模式(Q1) | 只声明访问层,不声明行为 | 扩散四条件(n=5) | 质量 61.5 vs 关 16.6 vs 随机 45.8 vs oracle 17.2;达成层零差分 | fact DB B2 ✓ |
| Y2 | CI 生命周期形成→滞留→衰减 | 表达极未触达(峰值 0.46<阈 0.78) | D-CI | 3-4 CI vs 0;场温 1.61-2.12≫0.35 | fact DB D_CI ✓ |
| Y3 | Hebb 加权通道因果隔离 | 行为面亚阈(+0.074 无行为变化) | F(30 episode,n=5) | 3 条白名单边单调增强 vs 禁用 0 | fact DB F_hebbian ✓ |
| Y4 | 长链首次沙箱达成(Q4) | 环境简化(smelt 即时结算);14 步单任务族 | H(L0/L1/L2/L3/L3b,n=5) | L0 5/5 @315;L3 0/5;L3b 5/5 @315;L1(-扩散)259 更快 | fact DB H_longchain ✓ |
| Y5 | 真实环境观测形态(M1/M2) | 观测证据,非因果桥 | 实机 MC 桥 25min×2 | M1 +100n/+365e;M2 +35n/+95e | fact DB(正文) ✓ |
| Y6 | **共享枢纽拓扑下扩散 > flat(§16 combo)** | 单一权重组合(w=0.5);无 sweep;机制层 | combo O3(n=30) | **FAS 30/30 vs B2 0/30**;b1 0/30;b3 5/30 | analysis.json combo ✓ |
| Y7 | 双向投影提高拓扑对齐与覆盖 | 伴随共享节点激活稀释(0.833→0.475);无行为检验 | relation direction | Gini 0.417→0.792-0.824;加性预测 0.491≈实测 0.475 | paired_statistics.csv ✓ |
| Y8 | 显式路由在信息竞争任务上有方向性正证据 | 原始 p 校正后不存活(Bonferroni 280 检验 p≈1);探索性 | C34 v2(n=20 配对,520/520 valid) | T4 19/20 vs 15/20(原始 p=0.0455);decisions p=0.029;util p=0.010 | core_routing_v2/campaign/statistics.csv ✓ |
| Y9 | 生产回答路径渲染 attention/demand 已接线 | 2026-09-30 修复;False=精确回滚 | config.py nlp_render_cognitive_context=True | harness 与生产口径已对齐 | config.py:275-280 ✓ |

### 3.3 GRAY — 未验证/仅机制现象(不得作主声明)

| ID | 声明 | 状态 |
|---|---|---|
| V1 | 语义写回节点被规划器消费 | U2:代码审计无消费路径(限制) |
| V2 | 记忆再点火因果作用 | 冷场未现(场温≫阈),U4 |
| V3 | 环境变化下账本信念修正 | 量程不足(变化被探索吸收,U5) |
| V4 | 干预式因果识别 | 全部为规则化规律,无 do-检验(U3) |
| V5 | CI 表达级行为 | 峰值 0.46<阈 0.78,未验证 |
| V6 | 随机激活对照(访问域无结构) | 机制现象:同能量随机激活不可复现结构扩散 |

### 3.4 RED — 已被实验否定(必须呈现为负结果)

| ID | 声明 | 反证(实验/数字) |
|---|---|---|
| R1 | **扩散相对 flat retrieval 有普遍增量价值(H3)** | core incremental value:ΔJCG<0 全部 4 个预注册条件(中位差 −0.402/−0.402/−0.784/−0.782),Holm p=1.5e−9,r=0.615,0/200 反超;唯一例外=R2 排除(Y6) |
| R2 | 扩散驱动行动选择(U1) | 长链 −扩散 259 vs 315 tick 更快(5/5);达成率全部淡化 |
| R3 | 双向关系普遍更优(U4) | 共享节点激活稀释 0.833 vs 0.475;无行为检验 |
| R4 | 显式路由稳健优于基线记忆/检索(U5) | C34 v2:主指标无校正后显著优势;T3 显著更慢(p=0.003/0.044 方向 = 更差);token 2.1-3.7× |
| R5 | 零先验可学习/从零学习 | P0 0/25 锁定;学习通道饥饿(非学习能力测试,但"从零学习"不成立) |
| R6 | C34 v1 任何结论 | 无效装配(0 边/521 异常吞没/80 首步空焦点),v1 全部宣告无效,不作声明依据 |
| R7 | 收敛抗噪有优势(H2 未支持) | robustness:FAS slope 0.0076 vs B2 0.0、AUC 0.0427 vs 0.04、critical_noise 0.0=0.0;无抗噪优势;MRR 全面劣于 B2(C-1..C-4 0.0435/0.0426/1.0/1.0 vs 0.5/0.5/1.0/1.0) |
| R8 | 插入序/标签/ID 偏倚影响结论 | 插入序 CV=0.0;label/id 置换 rank_median 22.5 不变;反事实 C2 无伪收敛(0.0/0.0) |

### 3.5 验证补充(R7/R8 等隐藏检查,全部真实存在)

- 隐藏 oracle 置换测试(30 seeds × label/ID):排名不变(rank_median 22.5=随机水平,证明 target 无结构特权)✓
- 插入序 10 置换 × 30 seeds:fas/b2 CV=0.0 ✓
- 反事实 C2(无 joint target):FAS 不凭空制造联合收敛(top1 0.0,4 方法一致)✓
- C3(部分共享):FAS/B1/B2 全 top1 1.0(W=1.0/1.0/1.0/0.267)✓
- 负边检验:neg 与 none 的 joint_top1 0.0333≡0.0333,无 collapse(total_act 17.4101 不变)✓
- B4 oracle 预检:T1-T4 MRR=1.0,确认 generator 无逻辑错误 ✓

## 4. 实验重新分类(新论文中的位置与定位)

| 原实验 | 新论文位置 | 新定位 |
|---|---|---|
| 写回隔离 A2/B1-B2 + 晋升分拣 | §7.1(核心) | 获取:支架下新结构出现 |
| Beacon A10 | §7.1(核心,新加入) | **持久关系知识复用的行为级证据(信息不对称)** |
| G0/G1/G2 再激活 | §7.2 | 持久与迁移:访问层 |
| 实验 C 账本 | §7.2 | 持久与迁移:行为层(闭环) |
| 实验 D 事件框架(C20e/C20g) | §7.2 | 持久与迁移:行为层(闭环,装配语义保留) |
| 扩散四条件 + 实验 B | §7.3 | 激活机制:访问域与可测性 |
| **core incremental value(JCG/ΔJCG/sweeps/counterfactuals/combo)** | **§7.3(机制)+ §7.4(拓扑)+ §8(负结果)** | **激活机制运行;flat 比较;结构依赖;H3 拒绝** |
| relation direction(B 投影) | §7.4 | 拓扑依赖:方向语义限制+稀释 |
| C34 v2 路由 | §7.5 | 系统级:LLM 决策头边界(方向性) |
| 长链 H/K/L、P0/P1/P2、Hebb F、情绪 C-emo、CI D-CI | §7.5 + §8 | 系统级与边界 |
| 实机 M1/M2 | §7.5 | 观测佐证(明确非因果桥) |
| 消融矩阵 A/B 早期 | §8 | 装配失效实例(方法学事实) |

## 5. 删除/降级内容

- **删除**:无实验结果被删除。部分表述降级:
  - 旧摘要中"我们刻意把问题收窄"的贡献 1-4 重写为 §10 的 4 条新贡献(§9)。
  - 旧 tab:claims U5 中"2.1--3.7 倍"保留(实测);"T4 未校正 p=0.046"措辞不变但进一步明确"探索性,不作任何确证声明"(§7.5/§8 双标注)。
  - 旧论文中"路由价值成立的条件是信息不对称场景"提升为 §8 的正式边界假设,并用 Beacon(§7.1)作为该条件的支持证据——注意:Beacon 的 D-flat 20/20 必须同时呈现,防止"D-flat≈full⇒扩散必要"的错误印象(新文本明确:Beacon 支持"图持久关系复用",不单独支持"扩散必要")。
- 明确继续不声称(写入 §9 讨论):AGI、开放学习、对 LLM 智能体普遍优越性、因果理解、扩散普适收益、显式路由稳健价值、Hebb 行为收益。

## 6. Future Work 内容(保持为具体实验,不写愿景)

1. 共享枢纽结构族参数化扫描(combo 目前仅 1 种权重组合 w=0.5;做 w×枢纽大小×路径深度联合面)——直接由 Y6 引出。
2. 信息不对称任务的系统设计(Beacon 扩展到更长链;部分可观察状态、延迟后果、跨会话依赖)。
3. 关系本体精修:按关系类目决定方向语义(配方类 forward、观察共现类双向),扩展 n=10→行为检验。
4. 事件框架生产默认关→独立观测窗口核查失败落图极性稳定性(C21 ignition 现场验证)。
5. 支架最小化卸载曲线(从 P1 出发逐件卸载机制表,量化边际贡献)。
6. CI 表达级激活工程(0.46→0.78 路径)与表达行为因果检验。
7. 更大图/更多种子/多领域 + 至少一个外部评价协议。
8. LLM 话语密度提高的整机评估(图持久+语言实现联合收益)。

## 7. 新 Figure 清单(全部 PDF;概念图 TikZ,数据图 matplotlib)

| # | 名称 | 类型 | 来源/状态 |
|---|---|---|---|
| Fig 1 | FAS 总体概念(架构总览闭环) | TikZ | 现有 fig:loop,保留并小改(标注 LLM 为消费/决策组件) |
| Fig 2 | **统一图谱本体图**(语义/情景/程序/自我/意图 7 类标签 + 8 类关系 + 跨空间连接) | TikZ(新画) | 新增 |
| Fig 3 | **一个完整真实案例**(wood→plank restoration:Beacon 首动 gather oak 20/20 的真实 trace→写回晋升→新情境再激活) | TikZ(新画,真实数字标注) | 新增;不虚构 |
| Fig 4 | **传播激活示意**(输入 A/B/C → 多关系路径 → 共享枢纽 → 汇聚;标注 flat 路径 vs 扩散路径,画明"汇聚于枢纽=扩散可额外贡献之处",不画扩散必赢) | TikZ(新画) | 新增(数据注:combo 实测) |
| Fig 5 | **证据矩阵/森林图**(10 实验族:样本/效应/检验/证据层/判定) | matplotlib | 新生成 fig_evidence_matrix.pdf ✓ |
| Fig 6 | **扩散适用边界**:(a)ΔJCG 4 预注册条件+combo 星标;(b)weight sweep 双双在 w=0.7 跃迁(阈值性,非 FAS 优势);(c)dilution ρ=−0.445/−0.656 | matplotlib | 新生成 fig_diffusion_boundary.pdf ✓ |
| 沿用 | 写回隔离/晋升分类、再激活、账本迁移、扩散四条件、剂量、Hebb、长链、关系方向汇总(8 张) | matplotlib/TikZ | 现有 figures/ ✓ 照用 |

## 8. 新 Table 清单

| # | 名称 | 对应用户规格 | 来源 |
|---|---|---|---|
| T1 | FAS 组件与实现状态(含 production/实验层/默认关标注) | Table 1 | 现有 tab:components + 3 处修正(激素图化/web_search/情景缓冲器分层) |
| T2 | 研究问题×实验×证据层映射 | Table 2 | 现有 tab:rqmap 扩展(core incremental value 加入) |
| T3 | 主要行为结果(Beacon/账本/事件框架/长链/P0/路由) | Table 3 | 新写 |
| T4 | 机制层结果(JCG/ΔJCG/combo/关系方向/扩散四条件/情绪/Hebb/robustness) | Table 4 | 新写(数字见 §3) |
| T5 | 失败/边界案例表(闭包遮蔽/Hebb 亚阈/稀释/路由否定/零先验/装配失效) | Table 5 | 新写 |
| T6 | **实现→声明映射审计表**(组件/代码位置/实验证据/状态)— "尤其重要" | Table 6 | 代码审计 agent 产出 ✓,并入论文附录 |

## 9. 新 Abstract(双语)

**中文**:
> 具身智能体在交互中积累大量经历,但这些经历通常以非结构化日志存续,从未被重组为可复用的知识。本文报告认知架构原型 FAS:语义、情景与程序性内容承载于同一张分型加权知识图谱,经历经证据加权归因管线写回为关系结构,传播激活构成图上可测的知识访问域,账本、事件框架与再激活通道使存储知识可测地回流到行为。证据来自确定性零 LLM 沙箱(4×50 配对种子机制战役、5 种子确定性主体实验)与 20 配对种子的真实 LLM 决策头路由战役,共 34,000+ 可复现 run、全部程序化提取。主要发现:(i) 在信息不对称的信标任务中,持久图谱上下文使 20/20 达成,而无上下文基线 0/20(McNemar p=2e−6);(ii) 该上下文优势可整体由无激活聚合(D-flat)复现——持久关系复用得到支持,扩散的必要性未得支持;(iii) 在一项对照 34,016 run 的预注册机制攻关中,多输入收敛机制确实运行(JCG>0 200/200),但其相对 flat retrieval 的增量价值在全部 4 个预注册条件下被否定(ΔJCG<0,Holm p=1.5e−9,0/200 反超),唯一系统性正差分出现在多路径经共享枢纽汇聚的组合拓扑(FAS 30/30 vs flat 0/30);(iv) 关系方向语义被证明是传播的结构限制(ρ 0.325→0.645)。据此我们把 FAS 的实证贡献定位为**持久关系知识与结构依赖的激活访问**,并明确提出其不成立的情形:flat retrieval 在大多数检索与抗噪任务上已足够,扩散收益是拓扑依赖的、有边界的。全部否定结果与装配审计作为一等发现报告。

**English**:
> Embodied agents accumulate large amounts of experience, yet this experience typically persists as unstructured logs rather than being reorganized into reusable knowledge. We present FAS, a cognitive-architecture prototype whose semantic, episodic, and procedural content lives in a single typed weighted graph: an evidence-weighted attribution pipeline writes experience back as relational structure, spreading activation forms a measurable knowledge-access field on the graph, and ledger/event-framework/re-activation channels carry stored knowledge back into behavior measurably. Evidence comes from a deterministic, LLM-free sandbox (a preregistered 4×50 matched-seed mechanism campaign and 5-seed deterministic main experiments) plus a 20-matched-seed LLM decision-head routing campaign — 34,000+ reproducible runs, every number programmatically extracted. Main findings: (i) on an information-asymmetric beacon task, persistent graph context achieves 20/20 while the no-context baseline scores 0/20 (McNemar p=2e−6); (ii) this context advantage is fully reproduced by an activation-free flat aggregation (D-flat 20/20) — persistent relational reuse is supported, activation necessity is not; (iii) in the preregistered mechanism campaign the multi-input convergence mechanism demonstrably runs (JCG>0 in 200/200 seeds), yet its incremental value over flat retrieval is rejected on all four preregistered conditions (ΔJCG<0, Holm p=1.5e−9, 0/200 reversals); the only systematic positive arises under combinational topology where multiple relevant paths converge through a shared hub (FAS 30/30 vs flat 0/30); (iv) relation-direction semantics is identified as a structural limit on propagation (ρ 0.325→0.645). We therefore position FAS's empirical contribution as persistent relational knowledge with topology-dependent activation-based access, and state explicitly where it does not help: flat retrieval suffices on most retrieval and noise-robustness tasks. All negative results and assembly audits are reported as first-class findings.

## 10. 新 Contributions(4 条,用户指定上限;无"superior retrieval/better than RAG")

1. **统一图谱基底上的持久关系知识闭环**: 单一分型加权图承载语义/情景/程序内容,经历→证据加权写回→持久→再激活→账本/事件通道行为回流(§4-5);
2. **信息不对称下持久关系复用的行为级证据**: Beacon 与账本/事件框架实验(20/20 vs 0/20;p=2e−6;13 vs 16 tick;首动翻转 5/5);同时报告激活无关一致复现(D-flat 20/20),划定"复用"与"激活必要性"两个独立声明(§7.1-7.2);
3. **结构依赖而非普适的激活优势**: 预注册 4 条件 Holm 校正拒绝(FAS 相对 flat 的 ΔJCG<0,p=1.5e−9,0/200 反超)+ 唯一正差分=共享枢纽合并拓扑(30/30 vs 0/30)+ 方向语义诊断(ρ 0.325→0.645)——机制分析证明扩散的收益有拓扑边界(§7.3-7.4、§8);
4. **可复现的诚实实验协议**: 确定性零 LLM、全归档、两次装配审计并如实报告、34,000+ run 程序化提取、全部否定结果与正结果同权呈现(§6、§8)。

## 11. 完整论文大纲(新结构,用户 §13 指定)

1. **Abstract**(§9 双语)
2. **引言**(§2 主线;四贡献;证据标准声明)
3. **问题与设计目标**: 日志 vs 巩固;FAS 设计目标列表(统一图/写回/激活访问/审计性/零 LLM 主体);非目标(不声称:通用智能/从零学习/优于 LLM 记忆)
4. **FAS 架构**: 4.1 统一认知图谱(7 标签/8 关系/双向语义/持久化;Fig 2);4.2 经验写回(归因窗/支持/置信/晋升;算法 1);4.3 持久化与双继承;4.4 传播激活(方程/衰减/增益/抑制/发射即转移;Fig 4);4.5 工作集与访问;4.6 LLM 边界(受约束预算接口;合同零 LLM)
5. **经历→知识→行为闭环(Fig 1)**: LLM 定位=消费/决策组件,不声称 FAS 脱离 LLM;生产 vs 实验路径显式说明(哪些实验跑生产栈、哪些是装配层/机制隔离)
6. **实验方法**: 6.1 RQ 与证据分层(L1/L2/L3);6.2 沙箱协议与装配审计史(两次,如实);6.3 机制战役协议(core incremental value 预注册:4 条件×50 配对、Baseline 定义、统计计划、反事实/置换/插入序/负边/隐藏 oracle 检查清单);6.4 LLM 决策头协议(C34 v2);6.5 可复现性与数据溯源
7. **结果**: 7.1 持久关系知识复用(Beacon A10: 20/20 vs 0/20 vs D-flat 20/20;图 5 矩阵);7.2 持久与迁移(写回 0/13、晋升分拣、再激活 4/12、账本 13 vs 16、事件框架 5/5);7.3 激活机制(四条件访问层分离;joint 收敛 JCG 200/200;ΔJCG 全负 Holm 校正);7.4 拓扑依赖行为(combo 30/30;关系方向 ρ 0.325→0.645+稀释;权重阈值;robustness 无效;dilution ρ=−0.445/−0.656);7.5 系统级证据(长链 L0 5/5、零先验 P0 0/25、Hebb 机制隔离、情绪剂量、CI 生命周期、路由 v2 方向性、实机观测)
8. **为什么扩散并不总是有帮助**(专章): 8.1 情形 A—普通相关检索已足够(ΔJCG 全负;MRR 劣于 flat);8.2 情形 B—多输入/高干扰稀释(ρ −0.445/−0.656;MRR 下降);8.3 情形 C—共享枢纽例外与成立条件(组合关系需要汇聚而非最近邻);8.4 与路由结果的汇合(可观察状态下上下文边际价值≈0;C34 T4 信息竞争例外);8.5 谨慎假设(不写成定律):"当任务需要关系性汇聚而非简单最近邻检索时,激活最有用"(App 中标注为需未来验证的假设)
9. **讨论**: 已证明/未证明清单;支架角色;统一图价值;机制存在≠行为改变;对架构的含义
10. **局限**(12 项,更新版:加"核心增量实验为机制级、无行为验证")
11. **未来工作**(§6 清单)
12. **结论**
- **附录**: A 逐种子结果与溯源表; B 写回示例; C 路由 v2 全量(520/520 验证表、v1 无效记录); D 关系方向全量; E core incremental value 配置与统计(4 条件数值、robustness、weight/neg/insert/oracle 全套); F 实现→声明审计表(T6)

## 12. 投稿风险点

| 风险 | 处置 |
|---|---|
| 审稿人问"ΔJCG 全负为何还主张激活有价值" | 论文主动以专章(§8)回答:价值是拓扑依赖的,flux 机制(convergence)真实运行但 flat 已足够;唯一正差分=共享枢纽;这使论文从"修复过度的 benchmark 文"变为"诚实边界刻画文",是竞争力而非弱点 |
| 审稿人问"core incremental value 不是生产系统" | §5 明确生产 vs 实验路径;机制实验是隔离受控对象(参考模型提炼自生产语义),行为证据由生产栈实验承担——两者分章呈现,不做混淆 |
| Beacon D-flat=full 被读成"扩散没用" | 文本明确:读出的是"持久关系复用"支持 + "激活非必要"的同等强度证据;两个声明并列,不隐含贬义 |
| C34 v2 原始 p 被误当最终显著性 | 全文(T7.5/§8/附录 C/表 T3)统一标注"原始 p=0.0455,Bonferroni(280 检验)后 p≈1,仅方向性" |
| 审稿人要求机制实验的行为验证 | Future Work 第 1-3 项预登记;正文不装作已验证 |
| 中文 ctex 编译/字体问题 | 本机 MiKTeX portable(pdflatex+ctexart)已实测编译通过 22 页;改稿后重编译验证 |
| "激素节点架构已实现"与旧局限冲突 | T1/T6 统一按代码审计分层:调制器图公民=已实现;激素直控行为/人格通道=未实现;局限(7)措辞修订 |
| 图 5 矩阵混量纲批评 | 图注明示:各行效应不可比,仅判定方向可比(✓/✕/△),数值逐行保留供独立检验 |
| 时间线风险 | 全部数字 2026-09-30 前归档;本重构零新增实验、零重跑、零参数修改(核心原则);未使用任何"事后重算" |

---
*本报告所有数字在 2026-10-01 前经独立核对(来源文件逐项确认);未修改任何生产代码、实验代码或已归档结果。*