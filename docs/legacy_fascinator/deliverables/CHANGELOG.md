# changelog.md — 重构变更记录(按阶段)

基线:deliverables/baseline_snapshot/(main.tex/main_zh.tex/main.pdf/main_zh.pdf,2026-10-01 快照)。
最终稿:FAS_Paper_I/{main,main_zh,supplementary,supplementary_zh}.{tex,pdf}(EN 主文 13 页、ZH 主文 12 页、EN 补充 12 页、ZH 补充 11 页)。

## 阶段〇 勘察与基线
- 定位工具链:MiKTeX(E:/LaTeX/MiKTeX)、Python(E:/Miniforge.envs/Fascinator,pymupdf 1.28.2)。
- 基线扫描(修复前命中,详见 deliverables/SCAN_REPORT.md):向量级 EN A7 B18 C62 / ZH A6 B14 C54;文字级 EN 6 / ZH 4。
- 基线数字清单:deliverables/audit/baseline_en.json(1667 tokens)、baseline_zh.json(1670)。

## 阶段一 重定位叙事
- 新标题:From Embodied Experience to Reusable Relational Knowledge: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access(3 选 1,见 decisions.md D1)。
- 摘要压缩至 ~215 词,保留 5 组核心数字;34,016 runs 移入方法/摘要外;贡献 4 条→3 条。
- 两个命题 (a) 持久关系复用有行为收益、(b) 激活必要性未支持 全文显式分离。

## 阶段二 精简与去内部化
- 正文删除内部代号(A10、C20e/C20g、B2 双义、D-CI、L0/L3、T1–T4 混用等)、文件路径、审计日期、PAPER_FACT_DATABASE.json 字样;代号映射表入补充材料 S2。
- 主线四块:beacon(5.1)/ 写回隔离与持久化(5.2)/ 预注册边界分析(5.3)/ 局限性(7);新增 "Additional observations"(5.4)压缩长链、P0、Hebbian、情感、意图、路由、实况、闭包掩蔽。
- 证据等级 L1–L4 与协议层 P1–P4 合并为一张小表(正文表 1 简版 + 补充材料 S1 全版)。
- relation-direction 降级为诊断性分析:正文一句(讨论 6.5 与 5.3 末段),明确"深度 1 星形森林、目标全为汇点、前向两跳结构性不可达;加反向边的改善属设计层面验证",完整数据移补充材料 S9。
- 全文统一 Fascinator / FAS。
- 新增简短 Related Work(第 2 节,全部复用既有 references.bib 条目)。

## 阶段三 统计表述降调
- 方法 4.1:明示"确定性沙盒+合成拓扑;配对种子≠真实世界方差;检验量化方向一致性而非总体效应"。
- 信标 5.1:0/20 基线改述为"任务设计内置的存在性验证",非独立统计发现。
- 关系方向:p=0.001953 注明为 n=10 可得最小 p,仅证方向一致。
- 局限性新增:(1) 沙盒方差限定、(2) 存在性验证、(3) 未做外部环境验证、(12) 扫描局限于合成拓扑与闭式替身、(14) 远程端点位级确定性仅重跑验证。

## 阶段四 补充实验(全部先写设计文档、后运行、程序化提取)
- **共享枢纽参数扫描**(deliverables/experiments_new/shared_hub_sweep/):设计冻结(DESIGN.md,v1.1 修订记录在案——d 定义修正发生在任何数据产生前,预检按设计失败后修正);84 格(w×k×d)× 30 配对种子 + O3 复现格,共 2,550 run,确定性零 LLM。结果:O3 复现 FAS 30/30 vs 0/30(McNemar 1.9e-9);FAS 严格占优 11/84 格(全部 w≤0.5 且 d≤1)、平坦占优 9/84(全部 w≥0.7 且 d≥1)、平手 64;w 轴上平坦恰在 w=0.6 追平。写入正文 5.3 + 表 4 末行 + 新图 fig:sweep + 补充材料 S8(胜/负格全表)。
- **embedding 基线**(emb_flat_check/):核实 D-flat 本就是真实句向量检索(本地公开模型 BAAI/bge-small-zh-v1.5,import 级验证);新做零 LLM 可达性检验:20 种子装配一致,44 节点中 oak_planks 排第 2、oak_log 第 4,均在 Top-8。写入正文 5.1 与补充材料 S6;CIV 的 B2 在方法 4.3 明确改述为"闭式近似(非嵌入检索器)"。
- **确定性重跑**(beacon_rerun/):5 种子 × 4 条件经真实 LLM 端点重跑对比归档——诚实负结果:success 20/20 一致,完整动作序列仅 7/20 一致(远程端点温度 0 亦非位级确定)。写入正文 5.5 + 补充材料 S10;方法 4.1 的"逐字节复现"主张限定为零 LLM 族。
- **外部环境验证(Crafter)**:评估为工作量过大,不做(任务书允许);摘要不提及,局限性保留"未做"。

## 阶段五 可复现性与公开
- deliverables/REPRODUCE.md:一键复现脚本清单与命令(零 LLM 部分数分钟内完成)。
- deliverables/ZENODO_METADATA.md:Zenodo 描述元数据草稿(数据集类型、许可、预注册指针、敏感内容声明)。
- Claim→Evidence→Source 对照表:补充材料 S14(19 条主张逐条映射归档来源)。

## 阶段六 语言与格式
- EN 全文重写润色:去口语化、长句拆分、每段先结论后证据;冗余括号堆叠清理。
- 主文保留 5 图(ontology、act-schematic、loop、boundary、sweep)+ 4 表(evidence、beacon、boundary、无);其余 7 图 8 表移入补充材料(decisions.md D9)。
- 通用模板排版保持(期刊模板待定刊切换,decisions.md D8)。

## 阶段七 图表排版修复(EN 与 ZH 全部镜像)
- 逐项修复任务书 6 个已知问题(走廊绕行、entity 重排、strut、面板标题上移、marker/标签坐标、verdict 列宽 0.155→0.165),另修复扫描揭示的隐藏问题:s1 节点与 epi 重叠(旧稿即存在)、反馈线穿 env 文字、fit 标签溢出、CJK 悬挂括号、\xrightarrow glyph 重叠、matplotlib marker 双绘、证据矩阵文字溢出。全程 EN/ZH 同步。
- 新图 fig_sweep 按同标准设计并一次通过扫描。修复前后命中对比见 deliverables/SCAN_REPORT.md。

## 阶段八 验证
- 四份 PDF 编译(pdflatex×2+bibtex)零致命错误、零未解析引用(仅一条无害字体 shape 警告)。
- 双扫描清零:四份 PDF + 三张 matplotlib 图向量级/文字级全部 0(见 SCAN_REPORT.md)。
- ASCII 位图抽验:本体论图页全图判读 + 过程中 6 轮局部判读。
- 数字差异审计:deliverables/audit/NUMBER_DIFF_AUDIT.md——消失数字 174/211 种迁入补充材料,余为坐标/千分位拆分/重复合并/引用键年份;新增数字仅来自阶段四实验;131 项关键声称数字 EN/ZH 并集零缺失(初查遗漏的 1.61/2.12/0.35/0.079 已补回)。
- 清理 _ 前缀临时文件与 v2 副本;规范名转正(main.tex/main_zh.tex/supplementary.tex/supplementary_zh.tex)。

## 阶段九 投稿材料(deliverables/submission/)
- cover_letter.md(含占位符:[JOURNAL NAME] 与按刊适配句)。
- highlights.md(5 条,均 ≤85 字符)。
- journal_table.md:6 个候选(含 1 个已停刊排除项),期刊政策全部联网核实并标注核实日期 2026-10-01;APC 现值与 WoS/Scopus 收录状态标注"待确认,投稿日复核"。
- submission_checklist.md:预警名单/SCIE 状态/预印本政策/作者贡献/利益冲突/数据可用性五类检查项。

## 第二轮整合(2026-10-05):数字核对 + 措辞重写 + persistent-state 实验

### 数字核对(NUMBERS_AUDIT.md)
- 总条数 ≈40;不一致 4 条;全部已修正或列入更正。
- 摘要 "ten extra"→"five extra"(重算 7.7−2.8≈4.9)。
- controls 四均值 3.1/7.5/11.1/11.1→2.8/7.7/12.0/11.7(快照残留)。
- INTERPRETATION "C3/C4 优于 C2" 方向修正。
- 其余 ≈36 条全部一致。

### 新增内容
- 主文 5.7 节 "Audit-driven corrections and negative results"(EN+ZH)。
- 主文 Limitations (18)-(20)(PSA 限制/sham 表面性/对照呈现不等价)。
- 主文摘要:加权衡句("persistent state resumes... 9/10 vs 0/10... five extra failed attempts")。
- 主文标题:Persistent Experience-Derived State in an Auditable Cognitive Architecture: Formation, Persistence, and Measured Behavioral Effects。
- 补充材料 S15(战役 v2)+S16(持久状态优势与对照表)(EN+ZH)。
- [PENDING-REVISION-CONTROLS] 占位(主文 5.7 + INTEGRATION_NOTES)。

### 术语变更
- 标题移除 "Reusable Relational Knowledge" 和 "Activation-Based Access"。
- 摘要/正文 "reusable knowledge"→"persistent, experience-derived state"。
- "consolidation"(机制主张处)→"continuous reinforcement"。
- "continual learning"→"persistent learning across episodes"。
- "persistent intention"(机制解释)→删除,改写为 relational working-set salience。

### 页数变化
- main: 13→14 页;main_zh: 12→14 页;supplementary: 12→13 页;supplementary_zh: 11→12 页。

### 双扫描(修改后)
- 四份 PDF + 补充:向量级 0 / 文字级 0(ZH 主文用 pymupdf 直查绕过 pdftotext CJK 限制)。

## 第三轮(2026-10-05,任务书 9 项):矛盾/数字/渲染修正 + persistent-state 接入

旧版备份:deliverables/paper_backup_pre_task9/(四份 .tex,修改前快照)。

### 1. Limitation (20) 重写 + 同步检查
- 位置:main_zh 限制(20)/main.tex 限制(20)。
- 旧:"…与 FAS 等效;图结构与扩散的独立贡献仅在失败信息行为(T3)上被证明…"
- 新:"T2 未检出差异(各 10/10,n=10,功效有限);T3 优势归因失败证据可见性;图结构/激活独立贡献未被证明;修订对照待完成 [PENDING-REVISION-CONTROLS]"。
- 原因:与 T3 事后审计一致(对照把失败信息排除出上下文,"等效/已证明"均越界)。
- 同步检查:§5.8 审计节(T3 条,本就正确,无需改)、6.1(未证明清单加入"图结构与激活相对保结构呈现等价对照的独立贡献")、结论(加入归因边界句)、摘要(加入"独立贡献未定")。补充 S16 解读段同改(EN+ZH)。

### 2. 渲染 bug(根因:heredoc 双引号吞反斜杠)
- main_zh.tex 6 处 `\textbf`→TAB+"extbf"(L432/459/464/468/472/476)、1 处 `$\rightarrow$`→LF+"ightarrow"(L433)、1 处字面 →(U+2192)在 PDF 中丢字形("gathers 1.06.0")→ 全部修复为 `\textbf` / `$\rightarrow$`。
- 修复过程中自引入 `\$` 事故 1 处 → 再修复。
- 其余三源文件检测 0 损坏。修复一律改用 Edit 工具/chr(92) 脚本;编译后 PDF 全文残留扫描(extbf/ightarrow/9/9/360/104/five extra)= 0;逐页视觉验证(重点页 zh p1/p11/p12、en p1/p12、szh p11)。

### 3. 摘要三处
- (a) "全历史基线 0/10"→加"短历史状态下"限定 + "更长含失败情节历史流中基线 10/10 追平"(T2b 归档);与限制(17)一致。
- (b) "约五次失败尝试"(EN "five extra")→"平均重复失败动作 10.5 次 vs 基线 1.0 次"(E 批实测;7.7−2.8≈4.9 是 PSA-T3 另一对照,不得混用——第二轮的 five extra 即此混用,本轮纠正)。
- (c) 20/20 vs 0/20 后加注"该 0/20 是闭卷门控下任务设计内置的存在性验证"。

### 4. 新增 §5.6"上下文移除条件下的持久状态检验"(EN+ZH)
- H1:T2 10/10 vs reset 0/10,McNemar p=0.00195(注明 n=10 最小可达、仅证方向);H3:vs direct 0/10;H5:T3 2.8 vs 7.7,Wilcoxon p=0.00098。
- 快照不一致处理:采用重算值 2.8/7.7(FINAL_REPORT 叙述行 3.1/7.5 不采用)。
- 必含限定四条:空对照只证持久性整体因果作用;sham 10/10(重算值;旧稿 9/9 修正)+预算曲线无诊断性(库存回显泄漏);History/RAG 持平(H2 不成立);n=10 单任务族。
- 同步:6.1 已证明列表加 (vi);摘要加一句;限制(18) 加最小 p 注;S14 主张表加两行(EN+ZH)。

### 5. 回归数统一
- §4.5 + S13(EN+ZH):"104 项回归测试"→"pytest 82 项通过;回归脚本运行器 108/108 通过"(本轮实跑)。

### 6. I/B 数字核实与批次标注
- I:"0–2/10"标注为主批 n=10(I1–I3 0/10、I4 2/10、I5 10/10、I6 8/10);预算 k16/k32/rich 0/10 标注为表示研究批(30 run)。
- B:统一为逐档表述(0/32/80s 库存侧各 10/10,160s 0/10;80s self-success 0/10),标注机制批 40 run;"≤32s 100%"与"80s 内 10/10"同源同批,无冲突。

### 7. 巩固术语三分
- §3.3 加入术语约定句:持续强化(Hebbian 亚阈值)/情节回放整合(未在行为层验证)/结构晋升(阈值化写入);"巩固"仅作问题设定总称。
- 引言中间路线句:consolidation→"经历写回(持续强化+结构晋升两层)"。
- §5.5 J 段调和:短程任务内 Hebbian 强化已在 PSA(§5.6)自然复现(10 条先验闭包边);未检验的是长程(百周期跨情节)连续强化。
- 3.3 阈值晋升已是"晋升/promotion",无需改。

### 8. 标题与摘要措辞
- 候选与选择见 INTEGRATION_NOTES.md;选定:"From Embodied Experience to Persistent Experience-Derived State: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access"(ZH:从具身经历到持久的经验派生状态:可审计的统一图谱架构与基于激活访问的预注册边界分析)。
- 替换第二轮标题;摘要"可复用的关系知识/持久关系复用得到支持"→"持久经验派生状态具有行为效应得到支持,激活必要性未得支持"。标题/摘要不再暗示图/关系机制的必要性。

### 9. 全量数字重审
- deliverables/audit/NUMBERS_AUDIT.md 重写(含新节 A/B/C 表 + D 沿用表 + E 回归实测 + F 摘要清单 + G 跨语言 diff + H 十条修正 + I 无法追溯清单=空)。
- 本轮新发现并修正:战役总数"360 run"不可溯源→实测 508(另 390 修复/混淆批单独归档),改 4 处;S16 表 C3 均值 11.1→12.0;EN §5.5 T 段残留重复句"entirely."×2 删除;两处过时 DRAFT 注释清理。

### 页数与验证(本轮终态)
- main 14→16 页;main_zh 14→15 页;supplementary 13 页;supplementary_zh 12→13 页。
- 编译 0 错误;向量级+文字级双扫描 4 份 PDF 全 0;EN/ZH 数字 token 集合差为空(唯一残差为 ZH 图注硬编码 5.3 vs EN \ref,同值)。
- [PENDING-REVISION-CONTROLS] 占位保留 10 处(main×4、main_zh×4、supp×2),未猜测结果。

## 定稿轮(2026-10-05,任务书 9 项):占位符替换 + p 值审计 + 收尾

旧版备份:deliverables/paper_backup_pre_final/(四份 .tex)。

### 1. [PENDING-REVISION-CONTROLS] 10 处全部替换
- 位置:main ×4(§5.6 限定 (i)、§5.8 (T3) 条、限制 (20)、结论)、main_zh ×4(同)、supplementary ×1(S16 解读)、supplementary_zh ×1(同)。
- 旧:"等价呈现的修订版对照待完成/pending ([PENDING-REVISION-CONTROLS])"。
- 新(按 PAPER_IMPACT_REVISION.md 弱化分支):"修订对照已尝试,但在呈现等价门槛处停止——朴素 2 跳规则下失败证据仍被截断,呈现等价的图对照未能实现,独立贡献仍未检验";§5.8(T3) 条与 S16 给出完整预检账户(2 跳集 51 节点、排位 43、发现边权 0.5 对第 8 槽 0.8、字符比 0.349/0.753、0 LLM run)。
- 编译后全文搜索:占位符残留 0。
- 不写成对图结构有利/不利的任何行为证据;H_R1–H_R4 写明"全部未回答"。

### 2. 方法学补充
- §5.8(T3) 条重写为"(T3) 呈现等价与门槛停止":距离 × 排序权重 × 预算三通道合取;信息等价 ≠ 呈现等价;预注册停止规则按设计生效。
- 补充 S16:同一账户的完整版 + run 记账段(见 5)。

### 3. ADDENDUM"1 跳不可达"的论文引用更正
- 论文中没有逐字沿用"1 跳不可达"的句子(ADDENDUM 原文未改);凡涉及 C4 失效机制的表述(§5.8、S16)一律写为"距离、排序权重与预算共同作用"。CHANGELOG 记录于此。

### 4. 局限补充与同步
- 限制 (20) 追加:(a) 预检只覆盖 Phase-1 基线存储 step-0 上下文;(b) C1 上下文含附加段(22 行对 10 行),上下文结构不完全对齐;(c) 需新的独立预注册。
- 6.1 未证明清单改为"(未检验:呈现等价的图对照尚未实现)";结论加"留给未来独立的预注册工作"一句。
- 方法 §4.2 新增"统计口径"句(各比较族 m、单侧仅限预注册声明处、n≤25 精确)。

### 5. p 值审计(见 audit/P_VALUE_AUDIT.md,13 族)
- 关系方向 p=0.001953:实现为双侧(scipy 默认),原"单侧最小 p"表述错误 → 改"双侧最小 p(双侧精确 Wilcoxon)"(EN/ZH 主文 + S9,共 4 处)。
- E2 修复 p=0.011:原值为单侧正态近似(0.0108);与同族 T 的精确法统一后改报单侧精确 p=0.0098(重算溯源),共 6 处。
- T 段补记 n=9 有效配对(1 个 harness 无效 run 按预注册规则排除)。
- 其余 10 族(beacon 2e−6、战役 Holm 1.5e−9 单侧、C/Holm 0.0117、I/Holm 0.041、PSA H1 0.00195 双侧精确、H5 0.00098 单侧、controls Bonf .0156、路由探索性、D-flat 0.72)实现与表述一致。
- 停止条件检查:两处不符均可由原始数据与实现解释,不触发。

### 6. FAS-sham 溯源
- raw_results.jsonl:sham T2 共 10 行(种子 0–9)、10 成功、0 error、无排除——最终数据 10/10;run_full.log 证实"9/9"为运行中途(前 9 个种子)的进度快照,非有效性排除。已写入 S16 run 记账段。

### 7. 批次说明(S16 run 记账段,EN+ZH)
- 正式批 508:A 55、B 40、C 30、E 70、F 30、I 102、J 10、K 83、T 54、T2 30、T-mech 4。
- 修复/混淆批 390:C 门控伪影 40 + C 开卷 30、E 修复前 30、F 修复变体 210、I 门控伪影 39、K 设计惰性 36、T 演练 5。
- 引用规则:头条数字只用正式批;修复批仅作审计史,绝不合并。

### 8. 数字复核与验证(终态)
- NUMBERS_AUDIT.md 追加 J 节(8 条新增/改动数字,全部溯源);P_VALUE_AUDIT.md 新建。
- EN/ZH 数字 token 集合差为空(ZH 图注 5.3 vs EN \ref 为唯一已知残差,同值)。
- 四份 PDF 编译 0 错误、0 未解析引用;渲染残留扫描(extbf/ightarrow/PENDING/0.011)0 命中;向量级+文字级双扫描 0。
- 页数:main 16;main_zh 15;supplementary 13;supplementary_zh 13(与上一轮相同)。

## 投稿准备轮(2026-10-05):PeerJ CS 投稿包

- 官方三页 JS 渲染抓取失败;要点经官方搜索片段+任务书双重确认;官方 peerj.cls(Overleaf/GitHub/CTAN)不可达 → 按任务书授权生成结构合规版 peerj_main.tex/peerj_supplementary.tex(article+lineno+natbib author-year+声明区),编译 0 错误、0 未解析引用;author-year 引用验证("(Anderson et al., 2004)")。
- 章节方案:Architecture+Evaluation Protocol→Materials and Methods;Limitations→Discussion 子节;Related Work 保留独立(偏离理由已记录);Conclusion→Conclusions。科学内容/数字变动 0。
- Author Cover Page 草稿(单位/邮箱/ORCID 等留 TODO,不猜测)。
- 复现包 deliverables/zenodo_package(235MB,3329 文件)+ 脱敏副本 _sanitized(用户名/路径清零);清理扫描:真实 API key 0(3 处 sk- 为误报);llm_config 不入包。干净目录验证:H1 10/0 p=0.00195、H5 0.00098、信标 20/20 与 0/20、ΔJCG 中位差逐位一致(Holm 1.36e-9 vs 论文 1.5e-9,scipy/冻结实现近似差,已在 README 注明)、508/390 逐文件一致 —— 全部重现,无停止条件触发。
- 新文档:REPRO_REPORT.md、METADATA_AND_LICENSE_OPTIONS.md(许可三选项,未擅自选定)、EDITORIAL_CRITERIA_CHECKLIST.md、TODO_FOR_AUTHOR.md。
- 图表:正文图全矢量(PDF/tikz),字体子集嵌入;色盲友好度列为可选改进。
- NUMBERS_AUDIT 追加 K 节;paper_final 同步 peerj 版文件。

## 收尾核对轮(2026-10-05,第二轮):Holm 口径/脱敏验证/第三方清单/摘要压缩

1. 冻结分析实现(core_incremental_value/runners,原样入包,未改一行)纳入一键脚本步骤 3b:干净环境重跑与归档 analysis.json 逐位一致(Holm 1.5113858911727241e-09 = 论文 1.5e-9);实现口径=单侧正态近似 Wilcoxon(解析尾)+Holm m=4;scipy 交叉口径 1.36e-9 及差异来源(数值路径)写入包 README 与 REPRO_REPORT §8.1;论文 §4.2 统计口径句按实际实现补"单侧正态近似"。
2. sanitized 包干净目录全量复现逐项一致(0 差异,停止条件未触发);脱敏一致性:3,331 文件 REPL 重放比对,0 非预期差异;llm_config 无密钥示例已入包。
3. THIRD_PARTY_NOTICES.md:包内无第三方数据/权重/词典;无 ConceptNet 派生(唯一命中为探索脚本占位注释);4 个生产快照各含 1 处 LLM 生成 expanded_knowledge 节点(低风险);Minecraft 配方=自写代码表达的功能性事实。
4. 摘要 366→342 词(≤350):5 处删改(重复短语/限定词移入正文承载),全部数字与结论逐项保留;EN(main.tex/peerj_main.tex)与 ZH 对应删减。
5. 重编译四份 PDF,0 错误 0 未解析引用;投稿文档中"366 词"引用同步更新为 342。

## ΔJCG 方向归属核对(2026-10-05,第三轮)

核实冻结实现(analyze.py/metrics.py)与预注册(manifest.json 方向 ΔJCG>0)
后发现:实现的单侧 p 定义为双侧之半(与符号无关),p_fas_gt_b2=p_fas_lt_b2
=3.778e-10,Holm(m=4)=1.5114e-9;在全负 ΔJCG 数据上该值是反方向(B2>FAS)
尾部,预注册方向尾部=补 ≈1。论文 16 处(EN/ZH/peerj/supp)改为"反方向
Holm p=1.5e-9",§5.3/§4.2/S6 展开预注册方向与报告方向的关系(预注册方向
无正证据,尾部≈1;反方向差异显著为描述性)。数字全部取冻结实现输出,结论
(H3 拒绝)不变;peerj_main 的统计口径句同时补上了上一轮漏同步的"单侧
正态近似"措辞。复现包 README(两份)与 REPRO_REPORT §8.5、P_VALUE_AUDIT
§K、NUMBERS_AUDIT §M 记录。

## 单侧 p 调用点普查(2026-10-05,第四轮)

全仓扫描 metrics.wilcoxon_signed_rank / one_tailed / mcnemar / scipy
wilcoxon 的全部分析侧调用点(14 处,详见 P_VALUE_AUDIT §L):唯一
"方向与符号无关"实现是 core_incremental_value/runners/metrics.py,其
进入论文的唯一链路(ΔJCG 主检验)已在上轮修正;其余调用点为两尾实现
(MRR、beacon、reldir、campaign v2、controls、sweep、cross-episode
mcnemar)、方向真实的单尾(PSA H5、cross-episode greater)、方向与数据
一致且论文不引用其 p(jcg_binom、死代码 p_j1),或论文引用计数而非 p
(O3 复现、200/200)。core_routing_v2 的 p 值分析脚本未归档(会话内
计算),已在审计中记录——论文仅作探索性描述、不承载确证性主张。
无需新的论文措辞修正;冻结实现与数据零改动。

## 路由战役分析脚本补齐(2026-10-05,第五轮)

新脚本 analyze_routing_v2.py 从归档 summary.csv(520 run)重建路由战役
全部统计:比较族 280(Bonferroni 分母)、99 共享键与归档 statistics.csv
零差异、论文引用的 5 个 p 值逐位复现、token 开销 2.05–3.74×(论文
2.1–3.7×)。检验口径确认为配对双尾 Wilcoxon(scipy 默认参数)——此前
P_VALUE_AUDIT 中"分析脚本未归档"条目已改为"已归档并逐位复现"。脚本入
两个复现包并作为一键验证步骤 5;README 记录输入/输出/预期值;干净目录
(sanitized 包)验证通过。论文无需改动;停止条件未触发。

## 统计口径表入文 + 复现包版本标记(2026-10-05,第六轮)

1. 口径表入文:主文 §4.2 后新增精简表(Table 2,14 行:族/检验/侧向/配对
   n/校正 m/状态),supplement 新增 S18 完整版(17 行,含实现归档位置列);
   EN(main、peerj_main)与 ZH(main_zh、supplementary_zh、
   peerj_supplementary)镜像。唯一来源 P_VALUE_AUDIT.md;与正文既有 p 值
   表述逐处核对无冲突(ΔJCG 反方向 Holm、关系方向双侧、E2/T 单侧精确、
   路由双尾 Bonferroni(280)、PSA H1/H3 双侧精确、H5 单侧)。
2. 版本标记:package_version.py 生成 payload SHA-256 清单
   (MANIFEST.sha256,3331 文件)+ VERSION.txt;原始包
   sha256:941863f63eac3efc,脱敏包 sha256:c6d986c89a4413fd
   (derived-from 941863f6);git HEAD 4685726(工作树脏,288 文件——
   故以 payload 哈希为权威标识,README 说明);本地 tag peerj-submission-v1
   (未推送)。README 新增"Version and immutability"节(DOI 对应版本、
   只增不改);CITATION.cff version 字段并入包哈希;一键脚本输出头部
   回显 VERSION.txt。
3. 编译:main 16→17 页、main_zh 15→16、supplementary 13→15、
   peerj_supplementary 14→16、peerj_main 18、supplementary_zh 13→14;
   全部 0 错误 0 未解析引用;S18 表长路径溢出已修(llowbreak),
   页边溢出 6 份 PDF 全 0。
4. 干净目录(sanitized 包)重跑一键复现:版本头正确回显;H1 10/0
   p=0.001953、H5 0.000977、sham 10/10、信标 20/20/0/20、冻结 Holm
   1.5114e-9 逐位、508/390、路由 280 族 99 键 0 差异、全部引用 p
   match=True、token 2.05–3.74×。无数字/结论变动。

## PeerJ 模板迁移(2026-10-05,第七轮;依据用户提供的官方模板骨架与官网要求)

1. 依据 PeerJ/模板.txt(官方 wlpeerj 模板骨架)与 PeerJ/官网要求.txt(官方要求中文页),
   实现接口等价 wlpeerj.cls(官方 cls 文件不可下载:Overleaf/GitHub/CTAN 均不可达;
   替身实现模板全部接口:fleqn/10pt/lineno 选项、letterpaper+1in、Times、
   author[n]/affil[n]/corrauthor、摘要前置(environ 抓取)、keywords、plainnat
   author-year)。文件头注明替身性质与投稿时换回官方模板的方法。
2. peerj_main.tex 重建头部:documentclass 换 wlpeerj;作者块改模板语法
   (单位/邮箱留 [TODO-FOR-AUTHOR]);摘要移至 begin{document} 前;新增
   Keywords(6 词,待确认)与 Acknowledgments 节(占位,按官方规则不提资助者);
   正文零改动。peerj_supplementary.tex 同步换类。
3. 官方要求核对结论:摘要 ≤500 词/3000 字符(现 342/2645 ✓,撤回"350 词"风险条目);
   摘要无引用 ✓;排版 >35 页收费(现 18 ✓);LaTeX 投稿图可嵌入 ✓;参考文献
   作者-年份按作者/年/题 ✓;补充文件 ≤50MB ✓;数据仓库 Zenodo 推荐、pan.baidu
   禁用(记入 TODO)。
4. 独立图文件:figures_upload/Figure 1..5.pdf(各 letter 612x792,从 peerj_main.pdf
   整页提取,含图注)。
5. 复核:peerj_main 18 页、peerj_supplementary 15 页、supplementary 15、
   supplementary_zh 14,全部 0 错误 0 未解析引用;非行号字符越 1in 边距 = 0
   (S18 表 tabcolsep 修复 + 长路径 llowbreak);Table 2 单页(p8)。
   向量扫描:peerj_main p3 本体论图 'involves' 标签与走廊线 8.7pt 边缘交叉
   ——目视判定文字未被遮挡、可接受(图与 a4 版逐字节相同,不改)。
6. 干净目录重跑一键复现(sanitized 包):版本标识不变(sha256:c6d986c8…,
   论文迁移不触包 payload);H1/H5/sham/信标/冻结 Holm 1.5114e-9/508+390/
   路由 280 族 99 键 0 差异/全部引用 p match=True。无数字变动。

## 官方 wlpeerj.cls 替换(2026-10-05,第八轮;用户提供官方 cls 文件)

1. Downloads/wlpeerj.cls(Overleaf 官方版 v1.2, 2016-08-18)替换接口替身
   (替身存档为 wlpeerj_shim_backup.cls.bak,不再使用)。
2. 与官方 cls 的接口对齐(全部为版式/包管理,零内容改动):
   - preamble 去重:amsmath/graphicx/booktabs/xcolor/caption/natbib 等由
     cls 加载,文档只留 multirow/array/algorithm/tikz/hyperref;
   - \keywords 删除(官方 cls 2016-08 已移除该命令,keywords 改在网页表单填);
   - \bibliographystyle{plainnat} 删除,采用 cls 内置 apalike(author-year);
   - 官方 geometry 为左 5cm 边注版式:三张宽表(tab:evidence/beacon/boundary)
     列宽微缩 + 全局 tabcolsep 3pt → peerj_main 0 overfull;
   - peerj_supplementary 无摘要 → 文档级 \long\gdef\theabstract{} 补官方
     cls 的无条件摘要引用;补充表以 \newgeometry 放宽为对称版式(不改 cls);
     S2/S18 长斜杠词加 \allowbreak(余 1 处 1.1pt 不可见级,记录)。
3. figures_upload 重制:Figure 1-3 从 peerj_main.pdf 按绘图区裁剪至 letter
   页(150dpi 目视完整);Figure 4-5 直接用矢量原件(fig_diffusion_boundary/
   fig_sweep.pdf)。图注在系统表单单独填写(官方允许)。
4. 终态:peerj_main.pdf 18 页 0 错误 0 未解析 0 overfull;
   peerj_supplementary.pdf 14 页 0 错误 0 未解析 1×1.1pt overfull;
   非行号字符越界 0;干净目录重跑一键复现全部一致(包版本标识不变
   sha256:c6d986c8…,论文文件不在包 payload 内)。

## 一致性与表述修订(2026-10-06,任务书 12 项;不改数据/冻结实现/结论方向)

1. 转义残留:peerj_main §4.2 "Table eftab:stats"(CR 吞 )修复;根因=
   bash 双引号命令中  被转义为回车。全 tex+PDF 扫描(eftab/effig/efsec/
   CR/TAB 模式)清零;后续含反斜杠编辑一律经 Write 工具落盘。
2. "match FAS"→按数据改"match or exceed"(摘要/§5.6/§5.8×EN/ZH/peerj):
   T2 持平(10/10、10/10、9/10、10/10 对 10/10),T3 基线 0.0 低于 FAS-full 2.8。
3. E2/T 判定 post-hoc(协议 v1.0=10-01 仅 A/B/C/E/F/I/K;E2/T 于 10-02/10-03
   在 E 结果后设计);Table 2 拆行、口径句与 §5.5 正文同步;共享枢纽扫描
   保持"设计先冻结后执行"如实表述(仓库内冻结,非公共平台)。
4. 引言"程序化提取"改如实:头条数字由一键校验脚本再生,其余逐行对照归档。
5. 图 5(a) 与 evidence matrix dJCG 行补 reverse-direction 限定
   (gen_figures_new.py 重绘,数值读归档 analysis.json;目视无重叠)。
6. E2 段删 "confirming…/残余惰性属设计层" 重复与过强归因;§5.8(E)
   attributable→consistent+untested。
7. T n=9:seed 0 两次端点错误(402/连接)按 runner 失败类别排除;协议
   仅规定 smoke 级有效性,逐 run 重跑规则缺失——如实写明。
8. 装配差异:战役 E(未接线)10.5 vs 1.0 与 PSA(接线)2.8 vs 7.7 一句
   说明+摘要指向(代码证据 make_fas ef_context=True / ADDENDUM §F)。
9. §5.5 首段加代号说明(C/E/E2/F/I/B/J/T 与 T1--T3 两套编号)。
10. Related Work 改 "To our knowledge/据我们所知";四篇新文献逐条经
    arXiv abs 页核对后入 bib(HippoRAG NeurIPS 2024/GraphRAG/MemGPT/
    Voyager,均 2023-2024)并各引一句(限定在不扩写范围)。
11. 删 peerj_main Conclusions 末重复的 Data availability 段;Reporting
    guidelines 改为如实描述(无适用清单;冻结=仓库文档非公共平台)。
12. §5.6 补 Bonferroni(m=3)句(0.0059/0.0059/0.0029,冻结输出计算)。
终态:6 份 PDF 0 错误 0 未解析;peerj_main 0 overfull(其余 ≤3.1pt 不可见级);
figures_upload 按新版面重提取;残留扫描 tex/PDF 全零。

## 许可决定落地(2026-10-06,用户选定 CC-BY 4.0 + MIT)

- 两包根写入 LICENSE(双许可:code/=MIT 全文;data/preregistration/
  docs/=CC BY 4.0 引用+归属+第三方说明)与 LICENSE_OPTIONS.md 副本。
- package_version.py 更新:根级 LICENSE 纳入 payload 哈希(许可是
  不可变工件的一部分;README/CITATION/VERSION/MANIFEST/LICENSE_OPTIONS
  仍排除以防自指)。
- 版本重算:原始包 sha256:d725e5e108bb8a1b(3332 文件),脱敏包
  sha256:be68a9ddac9c0f53(derived-from: d725e5e1);README 版本块、
  License 段(改为已选定)、CITATION.cff(version/license 字段)同步;
  修复 apply 脚本的哈希拼接错误(CITATION version 尾缀残留旧哈希)。
- README 的 sanitizer 引用修正:清洗脚本含原始字符串映射表,属作者
  私有工具,不随脱敏包分发(两包均无此文件,已确认)。
- TODO #3 更新(打包方式/表单要点/DOI 只改论文侧两处)、#4 完成;
  METADATA_AND_LICENSE_OPTIONS.md 增"决定记录"节并同步两包副本。
- 干净目录复验(sanitized 包):版本头 be68a9ddac9c0f53 正确回显;
  全部关键数字一致(H1/H5/信标/冻结 Holm/508+390/路由 280 族)。

## Zenodo 发布 + DOI 回填(2026-10-06,用户授权 API 上传)

- 经 API 完成上传与发布(Zenodo 草稿 23196280):
  zip 16.6MB/3338 文件(MD5 12cfda99…与本地一致);元数据全填
  (Dataset/CC BY 4.0/版本 1.0.0+pkg.be68a9ddac9c0f53/关键词/描述);
  affiliation 按 2026-10-06 作者确认填入(Department of Computer
  Science, China University of Petroleum-Beijing at Karamay, Karamay,
  China)。
- **DOI:10.5281/zenodo.23196280**(concept 10.5281/zenodo.23196279);
  记录页 zenodo.org/records/23196280。
- 论文侧回填:peerj_main 声明区(DOI+双许可表述)、peerj_main/peerj_
  supplementary 作者单位、Author_Cover_Page(单位/DOI/许可)、main.tex
  与 main_zh 的可用性段追加 DOI 句(中英一致)。
- 编译:peerj_main 18 页 0 错误 0 未解析 0 overfull;peerj_supplementary
  14、main 17、main_zh 17 页;占位符(ZENODO-DOI/LICENSE-TO-BE-CHOSEN)
  在 PDF 中零残留;包侧文件未动(已发布,MANIFEST/哈希仍与工件一致)。
- 过程记录:网页上传的 zip 未真正落盘(API files 为空)→ 改 API 上传;
  bucket PUT 初期 504(代理瞬态)与 405(POST 误用)排查后以
  Content-Length 显式 PUT 成功;诊断脚本与降级路径(multipart POST)
  留档于 scripts/zenodo_*.py。

## ORCID 落地(2026-10-06)

作者提供 ORCID 0009-0009-6762-2684。三处同步:
- peerj_main.tex 作者块 \thanks{ORCID: …}(重编译 18 页,0 错误 0 未解析,
  封面页已渲染);
- Author_Cover_Page.md ORCID 字段与待确认表 A4;
- Zenodo 记录 23196280 creators.orcid(legacy deposit API edit 动作,
  元数据编辑,version DOI 10.5281/zenodo.23196280 不变,文件未动)。
剩余待办仅:邮箱可投递确认、Acknowledgments/四段声明文字、PeerJ 表单提交。

## 声明区定稿(2026-10-06,作者确认)

无资助/无利益冲突/单一作者全部贡献/无致谢。peerj_main.tex:Funding、
Competing interests、Author contributions 三段按单数作者措辞填入;
Acknowledgments 节删除(留注释记录)。封面页同步;TODO #5 关闭
(遗留 AI 使用声明一句待作者按实际定稿)。重编译 peerj_main 18 页,
0 错误 0 未解析,PDF 内 TODO-FOR-AUTHOR 零残留。

## AI 使用声明入文(2026-10-06)

peerj_main.tex 声明区新增 "Use of generative AI" 节(AI 仅用于代码调试
与 LaTeX 排版;科学内容/实验/分析/结论由作者完成;数字经归档与校验
脚本核对;作者负全责)。封面页同步;重编译 18 页 0 错误,PDF 内已验证
该节存在。投稿表单 AI 问题答"是"并用同一措辞。

## TODO_FOR_AUTHOR 关闭(2026-10-06)

全部跟踪项完成(逐项核对见当日会话记录;各条目状态已散见于本
CHANGELOG 与 Author_Cover_Page.md),文件按作者指示删除
(deliverables/ 与 paper_final/ 两处)。提交时的三个操作性事项
(邮箱收信确认、APC/会员、表单逐字填写+关键词+AI 声明)已整理在
Author_Cover_Page.md 的"Declarations/待确认清单"中。

## 参考文献真实性核查(2026-10-06,用户质询后)

23 条逐条核查:①4 条新增(HippoRAG/GraphRAG/MemGPT/Voyager)经 arXiv abs
页在线核对(本会话);②zacks2007event 经 PubMed 在线核对(133(2):273-293 ✓
此前存疑的 878-913 为记忆错误,bib 正确);③其余 18 条为领域经典文献,
存在性无疑、著录细节(作者/年份/期刊/卷页)与权威记录一致(cowan2001
BBS 24:87-114、collins1975 82:407-428、anderson2004 111:1036-1060、
baddeley2000 TiCS 4:417-423、itti2001 NRN 2:194-203、posner1980 QJEP
32:3-25、schacter2007 NRN 8:657-661、mnih2015 Nature 518:529-533 等);
④唯一无法在线核实细节的是 hart2008opencog 的页码(468-472;论文存在性
有 Wikipedia/agiri.org 佐证,页码经 IOS Press/dblp/Semantic Scholar 多
渠道均不可达)——已从 bib 删除该字段(apalike 允许,宁缺勿错)。
重编译 peerj_main/main 0 错误 0 未解析。结论:除已删除的 1 个不可证
字段外,全部参考文献真实存在且著录经核。

## JETAI 定稿修订(v2,2026-10-06)

- 修复 v1 生成缺陷:wlpeerj 摘要位于 \begin{document} 之前,v1 切片丢失
  摘要——v2 显式抓取并重建(验证 PDF 含摘要)。
- 摘要换 179 词版(JETAI 上限 200;数字与结论逐项保留,压缩清单见会话)。
- AI 声明按 T&F 政策点名工具:Claude (Anthropic, web)、Claude Code
  (Anthropic)、ChatGPT (OpenAI)、ZCode (Qwen3.8-flash/DeepSeek-4.1/
  GLM-5.3-flash);用途=代码调试、LaTeX 排版、文字编辑;不用于科学
  想法/实验设计/分析/结论;数字经作者以归档+校验脚本核对。
- 终态:annotated 18 页(作者信息在)、anonymous 18 页(8 个身份字符串
  零泄漏、DOI 已撤)、两版 0 错误 0 未解析引用。

## JETAI 技术审查修复(2026-10-08 退函后)

- ③ Table 3(tab:beacon)正文补引用("Table 3 reports the full grid.",
  §5.1);⑤ 两版 title page 加 Keywords 行;两版重编译 0 错误 0 未解析。
- ② cover letter 草稿(JETAI_cover_letter.md):机构邮箱、ORCID、
  期刊匹配段、技术项逐条回复;profile page 与字数方案两处留待作者。
- ④ 单位一致性:作者需在投稿系统 Authors 步骤填与手稿逐字一致的
  "Department of Computer Science, China University of Petroleum-Beijing
  at Karamay, Karamay, China",且 portal 注册邮箱=title page 邮箱。
- ① 字数:正文实测 7240 词(不含表格/图/算法环境)vs 要求 5000。
  两方案待作者选择(A 压缩移补充材料 / B 致函确认弹性)。

## JETAI 方案A 执行:正文压缩至 4982 词(2026-10-08)

三轮搬运(内容零删改,全部逐字移入补充材料 S19.1-19.13,正文留摘要句+
指向):R1=§4.3/4.4 协议细节、§5.2 事件框架段、§5.3 共享枢纽/权重阈值/
关系方向段、§5.5 I/B/J/T 段、§5.7/§5.8 整节;R2=§4.1/4.2/4.5、§5.1
D-flat 段、§5.2 账本段、§5.3 汇聚段、§5.6 不可证明段;R3=§3.6 闭环段、
§5.4 重跑段。词数 7260→4982(tex 统计,不含表格/图/算法/参考文献;
表格与图仍全部留在正文)。两版重编译:annotated 15 页、anonymous 14 页、
supplementary 20 页,0 错误 0 未解析;anonymous 身份字符串零泄漏;
Table 3 引用与 title page keywords 在位。cover letter 定稿(profile 说明
+方案A文案+字数口径声明)。
