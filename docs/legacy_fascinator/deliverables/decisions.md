# decisions.md — 决策记录(决策点、选项、所选项、理由)

日期:2026-10-01。全部决策由执行代理按任务书默认规则自主做出。

## D1 标题(阶段一)
- 选项:
  1. Fascinator: An Auditable Unified-Graph Memory Architecture with a Preregistered Protocol for Bounding When Spreading Activation Helps
  2. From Embodied Experience to Reusable Relational Knowledge: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access(✅采用)
  3. Experience into Structure: Persistent Relational Reuse on a Unified Cognitive Graph, with Preregistered Boundaries on Spreading Activation
- 所选:候选 2。
- 理由:保留与旧稿的连续性(经验→可复用关系知识);明确"可审计统一图架构"+"预注册边界分析"两大支柱;activation-based access 从卖点降为被界定的对象。候选 1 把架构名放最前但更像系统论文;候选 3 文学化但"Experience into Structure"对检索不友好。

## D2 摘要数字(阶段一)
- 保留 5 组核心数字:beacon 20/20 vs 0/20(McNemar p=2e-6)、D-flat 20/20、ΔJCG<0(Holm p=1.5e-9、0/200 反超)、shared-hub 30/30 vs 0/30、shared-hub 扫描结论(阶段四产出的定性一句话,不给新数字)。
- 34,016 runs、520 routing runs 等移入方法部分。

## D3 贡献列表
- 压缩为 3 条:(1) 可审计统一图记忆架构+证据加权写回(经验→可复用关系知识);(2) 预注册评估协议与如实报告的负结果(H3 被拒、D-flat 复现收益);(3) 激活价值的边界刻画(shared-hub 例外+参数扫描曲面+关系方向结构诊断)。

## D4 embedding 检索基线(阶段四-1)
- 事实核查结果:beacon/routing 的 D-flat(`run_exp_routing_v2.FASContext.flat_focus`)**已经**是真实句向量检索——`embedding_manager.EmbeddingProvider` 加载本地公开模型 **BAAI/bge-small-zh-v1.5**(路径 E:/Models/bge-small-zh-v1.5,sentence-transformers 格式,公开可本地运行),对全图节点 id 编码后与任务文本做余弦 Top-k,无激活、无传播。
- 所选:不重复造基线;以"零 LLM 检索可达性检验"(20 配对种子,程序化验证 D-flat 检索确实把配方链节点送入 Top-8)作为补充实验,并把 CIV 战役中的 B2 明确改写为"闭式路径乘积近似"(正文已区分)。bge-small-zh-v1.5 为中文优化的双语模型,对本文短 id 文本英文查询可行(原战役 20/20 即在该模型上取得)。
- 理由:任务书要求"真正的 embedding 检索基线";核实发现其已存在,按铁律 1 如实核实并补一个程序化检验比再造一个不同的基线更诚实。

## D5 shared-hub 参数扫描设计(阶段四-2)
- 设计文档先写死(experiments_new/shared_hub_sweep/DESIGN.md),运行前冻结:联合扫描 边权 w ∈ {0.3,0.4,0.5,0.6,0.7,0.8,0.9} × 汇聚输入数 k ∈ {2,3,4,6} × 枢纽到目标的路径深度 d ∈ {1,2},每个格 30 配对种子,主指标 success(FAS 多输入收敛使联合目标进 Top-1 的比例)与 MRR,对照 B2 闭式路径乘积与 B1 直注入;分析方案(逐格 McNemar/精确二项 + 曲面汇总)同文档冻结。
- 复用 core_incremental_value/generator.py + methods.py,不触碰其已归档代码,新增参数化 hub 拓扑生成器放 experiments_new/。

## D6 阶段四-3/4 可选实验
- 外部环境验证(Crafter):评估为工作量过大(需引入新依赖、重写任务桥、且环境确定性无法保证),**不做**;摘要不提及,局限性保留原声明并注明"未做"。
- 随机性稳健性检查:采用"LLM 端点温度 0 + 重跑 5 种子 × 4 条件信标子集,验证逐字节可复现"作为稳健性/复现性检查(不改环境代码,工作量可控,直接支撑论文的可复现主张)。若 LLM 端点不可用则记 blockers 并回退为"未做"。
- **执行结果(2026-10-01)**:端点可用并完成重跑;结果为诚实负结果——success 20/20 一致,完整动作序列仅 7/20 逐字节一致(远程端点温度 0 亦非位级确定)。按设计文档判据,论文 4.1 节的位级复现主张限定为零 LLM 族,5.5 节如实报告该负结果。

## D7 文字级扫描清零策略(阶段七)
- pdftotext 的 \xrightarrow 上标标签与长箭头 glyph 框天然重叠(基线 6 处 EN/4 处 ZH 全部属于此类)。
- 所选:凡是带标签的 \xrightarrow 一律改为 TikZ node 标签位于箭头上方(图内)或 "leads-to (w=conf)" 平文叙述(表格/正文),保证提取框不相交。
- 理由:不改任何文字主张,只改排版原语。

## D8 目标排版模板(阶段六)
- 先用通用 article/ctexart 模板(现用),期刊模板待作者定刊后再切换。理由:任务书指定。

## D9 图表取舍(阶段六)
- 主文保留 5 张:fig:ontology、fig:loop、fig:act-schematic、fig:boundary(含新扫描面板)、fig:writeback。
- 移入补充材料:fig:case、fig:diffusion、fig:reactivation、fig:ledger、fig:evidence_matrix、fig:reldir(仍需同样修复,任务书第 7 阶段说明)。

## D10 期刊候选核实方式(阶段九)
- 仅采用联网核实的期刊政策(核实日期标注);核实失败者标"待确认",不凭印象填写。
