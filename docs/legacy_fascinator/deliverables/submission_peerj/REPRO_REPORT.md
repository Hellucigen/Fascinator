# REPRO_REPORT.md — 投稿准备报告(PeerJ CS;2026-10-05)

## 0. 官方要求核对方式

- 官方三页(peerj.com/about/{author-instructions,editorial-criteria,policies-and-procedures}/cs)为 JS 渲染,直接抓取与 web.archive.org 均失败。
- 官方模板(peerj.cls/peerj.bst)分发渠道 Overleaf、GitHub、CTAN 在本环境均不可达。
- 处置:关键要求(封面页第一页、在线信息一致、author-year 引用按 作者/年份/标题 排序、代码+原始数据经不可变仓库+DOI+开放许可+元数据、报告规范清单、行号、标准章节)经官方搜索片段与任务书要点双重确认;模板按任务书授权生成**结构合规版**,差异见 §1。TODO #7(人工过官网)保留。

## 1. 模板迁移:最终方案与差异

**方案**:peerj_main.tex / peerj_supplementary.tex(article 基类 + lineno 行号 + natbib [round,authoryear] + plainnat + PeerJ 式声明区)。编译 0 错误、0 未解析引用;引用渲染为 author-year(如 "(Anderson et al., 2004)")。main 18 页(含行号),supp 14 页。

**与官方模板的差异(拿到官方模板后一键换壳)**:
| 差异 | 说明 |
|---|---|
| 文档类 | 非 peerj.cls(官方 Overleaf 模板);TODO #1:把正文粘贴进官方模板 |
| 参考文献排序 | plainnat 按 author-year-label;官方要求 author-year-title。对现有 15 条文献逐条核对:同作者同年无多条,排序结果与官方规则一致(差异实际不触发) |
| 行号分布 | lineno 按段落;官方模板连续行号。审稿不受影响;换官方 cls 后自动修正 |
| 声明区字段名 | 按官方常见字段(Funding/Competing interests/Author contributions/Data and code availability/Reporting guidelines);换官方模板后用其宏 |

**科学内容/数字变动:0**(迁移脚本只改 preamble 与标题层级;数字与正文逐字未动)。

## 2. 章节结构方案(写入 INTEGRATION_NOTES,此处为摘要)

- Introduction ✓;Results ✓;Discussion ✓;Conclusions ✓(仅改名)。
- **Materials and Methods** = 原 §3 架构 + §4 评估协议合并(§4 降为其小节)。
- **Related Work 保留为独立节(偏离)**,理由:本文方法学核心是"与平坦检索/既有记忆路线的预注册对照",相关工作提供该对照的分类与定位,并入引言会弱化预注册问题的呈现;PeerJ 允许偏离但需清晰度理由,已记录。
- Limitations 并入 Discussion 作为其子节(PeerJ 常规做法)。
- Supplement 引用(正文 \ref 与文字 "Supplementary Material Sxx")经编译验证全部有效(0 未解析)。

## 3. 复现性验证(干净目录,sanitized 包)

- 环境:Windows 独立临时目录(C:\Users\...\Temp\peerj_repro_test),仅 Python 3.12 + numpy/scipy;零 LLM、零网络。
- 命令:`python scripts/reproduce_key_numbers.py .`
- 结果(与论文逐项对照):

| 关键数字 | 论文值 | 干净目录重算 | 判定 |
|---|---|---|---|
| H1(FAS-full vs reset,T2)| 10/0,McNemar p=0.00195;10/10 vs 0/10 | 10/0,p=0.001953;10/10 vs 0/10 | ✅ 逐位一致 |
| H5(T3 失败重复)| 2.8 vs 7.7,p=0.00098(单侧)| 2.8 vs 7.7,p=0.000977 | ✅ |
| FAS-sham T2 | 10/10 | 10/10 | ✅ |
| 信标(n=20×4)| fas_full 20/20;D-flat 20/20;D-noact 0/20;direct 0/20 | 同 | ✅ |
| 机制战役 ΔJCG | 中位差 −0.402/−0.402/−0.784/−0.782;Holm p=1.5e−9;0/200 反超 | 中位差逐位一致;Holm p=1.358e−9(scipy approx);0/200 | ✅(p 值第 4 位数字差异为 scipy 与冻结实现的近似差,量级一致;归档 analysis.json 为权威源,已在 README 注明) |
| run 记账 | 508 正式 / 390 修复混淆 | 逐文件一致(508=55+40+30+70+30+102+10+83+54+30+4;390=40+30+30+210+39+36+5) | ✅ |

- **停止条件检查:未触发**(无不可重现数字)。

## 4. 清理扫描与脱敏

- 工具:`scripts/scan_package_secrets.py`(只读,模式:绝对路径/API key/token/邮箱/用户名)。
- 原始包命中:绝对路径 411、用户名 2,810(主要在 tests 与 minecraft 会话快照)、API key 0(3 处 `sk-` 为 "ta**sk-completion**" 误报;`api_key=""` 为空串)。
- **脱敏副本** `zenodo_package_sanitized/`(原始包保留不动):`scripts/sanitize_package.py` 生成,用户名→`player_main`、路径→`<REPO_ROOT>` 等占位;复扫全部为 0。**投稿上传用 sanitized 包**。
- 排除项:`data/llm_config.json`(端点配置)不入包;个人知识图谱/Knowledge 与 faiss 索引不入包。
- 第三方版权数据:无(嵌入模型仅按名引用)。

## 5. 体积评估

- 包总体积 235 MB、3,329 文件;最大单文件 22.6 MB(`core_incremental_value/raw_results.jsonl`)。
- Zenodo 无需分卷(限额远大于此);Zenodo 单文件上限 50 GB ✅。

## 6. 报告规范与补充材料

- 本文遵循:**预注册报告**(机制战役、持久状态实验、对照实验、修订对照四份冻结预注册随包;摘要见补充 S14–S16)。
- 不适用如实声明:无人类/动物受试者,无 ARRIVE/PRISMA/STROBE 适用(正文 Reporting guidelines 段)。
- 补充材料整理(S14 主张-证据映射、S15 战役协议与批次、S16 持久状态与对照+run 记账、检验口径表 audit/P_VALUE_AUDIT.md 并入补充 S14 末尾说明)已在 peerj_supplementary.tex 生效。

## 7. 图表检查

| 图 | 格式 | 分辨率/字体 | 备注 |
|---|---|---|---|
| fig_sweep.pdf、fig_diffusion_boundary.pdf(正文图 4/5)| 矢量 PDF,纯绘图对象,无位图 | 字体子集嵌入(DejaVuSans)| 分辨率无限;色盲友好度(绿/橙编码)未做正式验证 → TODO #8 可选改进(加 hatch/明度差) |
| 其余正文图(tikz:ontology、schematic、loop)| 矢量 | 文档字体 | 无风险 |
| PNG 副本(figures/*.png)| 300 dpi 备用 | — | 仅 supplement 旧版引用;peerj 版正文全部用 PDF 矢量 |
| 图注自洽 | — | — | 图注数字与正文/表一致(第 3 轮已核);PeerJ 版无编号冲突 |

## 8. 收尾核对轮(2026-10-05,第二轮)

### 8.1 Holm p 值口径(冻结实现)

- 冻结实现定位:`experiments/core_incremental_value/runners/analyze.py` +
  `metrics.py`(生成归档 analysis.json 的脚本,**原样**纳入复现包
  `code/core_incremental_value/runners/`,未改一行)。其检验方式:
  **单侧正态近似 Wilcoxon**(基于符号秩,z=(W−μ)/σ,解析 erfc 尾),
  Holm 校正 **m=4**(仅 4 条 confirmatory ΔJCG);实现中 p_fas_gt_b2 与
  p_fas_lt_b2 都报告为 p_two/2(双侧之半),冻结如 是,如实记录。
- 一键脚本新增 **步骤 3b**:把 `data/core_incremental_value/raw_results.jsonl`
  复制到临时目录后原样运行冻结实现,与归档 analysis.json 逐位比对——
  **holm_p = 1.5113858911727241e-09、median −0.402259/−0.402259/−0.784316/−0.782302、
  r = 0.6154 全部逐位一致**(即论文引用的 1.5e-9)。冻结实现仅依赖
  Python 标准库(json/csv/math/statistics),干净环境可运行 ✓。
- scipy 交叉口径(步骤 3,`wilcoxon(alternative='less', method='approx')`
  + Holm):1.3579e-9。差异来源:同为单侧正态近似 Wilcoxon、同一批
  per-seed 差值;raw p 3.78e-10 vs 3.39e-10(约 10%)完全来自两个实现
  的数值路径(解析 erfc vs scipy 内部近似管道),与数据、侧向、校正无关。
  归档 analysis.json 为权威源;论文引用冻结实现值。
- 论文方法句已补(EN §4.2 / ZH §4.2 统计口径):"单侧正态近似 Wilcoxon
  (基于秩、解析尾)+ Holm"——按实际实现表述,未选更有利的措辞
  (正态近似而非精确,照实写)。

### 8.2 脱敏副本验证(sanitized 包,干净目录)

- 在 `zenodo_package_sanitized` 上重新运行一键脚本(干净临时目录):
  H1 10/0 p=0.001953;H5 2.8 vs 7.7 p=0.000977;sham 10/10;信标
  20/20、20/20、0/20、0/20;ΔJCG 中位差逐位一致;scipy Holm 1.358e-9;
  冻结实现 Holm 1.5114e-9(逐位);508/390 逐文件一致。**逐项全部一致,
  无差异 → 停止条件未触发。**
- **脱敏一致性比对方法**:对 3,331 个文件逐一比对——文本文件用
  `sanitize_package.py` 的 REPL 列表(经 AST 提取,避免手抄转义错误)
  重放到原始包内容后与脱敏副本逐字节比对;二进制文件比对 SHA-256。
  结果:**300 个文件含预期内的替换差异,0 个非预期差异**(2,531 个
  二进制/未变更文件哈希一致)。
- **llm_config 依赖**:包内 7 个脚本引用 `llm_config/llm_secret`
  (均为 LLM 决策头实验路径,一键验证器不依赖);已加入
  `data/llm_config.example.json`(`api_key` 为空)作为无密钥示例,
  README 已说明 LLM 族复现需自备匿名化端点配置。

### 8.3 第三方内容清单

见 `deliverables/THIRD_PARTY_NOTICES.md`:包内无第三方数据/权重/词典
分发;无 ConceptNet 派生内容(唯一命中为探索脚本的路径占位注释);
4 个生产会话快照含 LLM 生成的 expanded_knowledge 节点(逐快照 1 处,
低风险);Minecraft 配方为自写代码表达的功能性事实。**无隐私或版权
不明数据,停止条件未触发。**

### 8.4 摘要压缩(366 → 342 词;数字与结论未变)

逐句删改(EN;ZH 做对应删减):
1. 首句删 "instead of becoming persistent, experience-derived state"
   (与后文 "Persistent experience-derived state is therefore supported"
   重复;术语在后文出现)。
2. 信标括号:"an existence verification built into the closed-book task
   design, not an independent statistical finding" → "a closed-book
   design's built-in existence verification"(存在性验证限定保留;
   "非独立统计发现"的完整表述在 §5.1 与限制 (2))。
3. PSA 句:"A dedicated context-removal control experiment" →
   "A context-removal control experiment";删 ", evidencing directional
   consistency only"(该限定完整保留在 §5.6 与限制 (18);"minimum
   attainable at n=10" 已表达小样本含义)。
4. 战役括号:"(508 archived runs, plus 390 repair/confounded runs
   archived separately)" → "(508 archived runs; 390 repair runs
   archived separately)"。
5. 追平括号:"(with longer, failure-containing experience streams the
   baselines catch up at 10/10)" → "(longer, failure-containing streams:
   baselines catch up at 10/10)"。
全部数字(20/20、0/20、2e−6、10/10→0/10、0.00195、n=10、2.8、7.7、
0.00098、4×50、1.5e−9、0/200、30/30、11/9/64、508、390、9/10、0/10、
10/10、10.5、1.0)与全部结论(持久性因果、激活必要性未支持、独立
贡献未定)逐项保留。

### 8.5 ΔJCG 检验方向归属核对(第三轮,2026-10-05)

- **预注册**(core_incremental_value/manifest.json):primary_family =
  4 条 ΔJCG = JCG_FAS − JCG_B2 的**单尾 Wilcoxon,方向预注册 ΔJCG>0
  (FAS>B2)**;H3 = "扩散的 JCG 超过平坦"。
- **冻结实现事实**(analyze.py + metrics.py,未改动):单侧 p 被实现为
  **双侧 p 之半、与符号无关**——因此 p_fas_gt_b2 与 p_fas_lt_b2 两个
  字段数值恒等(每条件均为 3.7784647279318103e-10,n=50);Holm(m=4)
  挂在名义"预注册方向"字段(p_pos)序列上,输出 1.5113858911727241e-09。
- **方向归属结论**:在本文全负 ΔJCG 数据上,报告的 3.778e-10 / Holm
  1.51e-9 在数值上量化的是**反方向(B2>FAS)的尾部**;预注册方向
  (FAS>B2)的单侧尾部为其补,**p≈1**(即预注册方向上无任何正证据)。
  论文此前把 1.5e-9 直接作为检验结果而未标注方向——已修正:全文
  16 处改为"反方向 Holm p=1.5e-9"并区分"预注册方向的检验结果
  (H3 被拒绝:方向相反且预注册方向尾部≈1)"与"反方向差异的显著性
  (描述性,Holm 1.5e-9)"。H3 被拒绝的结论不变(且更保守)。
- 论文 §4.2 统计口径句与 §5.3 结果段已写明该关系;数字全部取自冻结
  实现输出,未重算替代。修正不改变任何数字与结论。

## 9. 统计口径表入文与复现包版本标记(2026-10-05,第六轮)

### 9.1 口径表
- 主文 §4.2 新增精简表(Table 2,14 行);补充材料新增 S18 完整版
  (Table S15,17 行,含"实现(归档)"列);EN/ZH 全镜像。唯一来源
  P_VALUE_AUDIT.md;与正文既有 p 值表述逐处核对,无冲突、无数字变动。
- 排版:6 份 PDF 0 错误 0 未解析引用;长路径 \texttt 溢出以
  \allowbreak 修复,页边溢出全 0;表页目视抽查通过。

### 9.2 版本标记
- 生成工具:`scripts/package_version.py`(payload = data/ code/
  preregistration/ scripts/;README/CITATION/VERSION/MANIFEST 排除,
  避免自指)。
- 标识:原始包 `sha256:941863f63eac3efc`(3331 文件,MANIFEST.sha256
  逐文件哈希);脱敏包 `sha256:c6d986c89a4413fd`,VERSION.txt 内
  `derived-from: sha256:941863f63eac3efc`。
- git 状态:HEAD 468572655ad2d14d8c56517bc8b24cd67e58b0ec,工作树脏
  (288 文件)——VERSION.txt 明确注明"以 payload SHA-256 为权威标识,
  非 git commit"。本地 tag `peerj-submission-v1` 已创建,未推送。
- 写入位置:两包 README"Version and immutability"节(Zenodo DOI 对应
  本版本;任何后续修改必须发布为新版本,不得覆盖)、CITATION.cff
  `version: 1.0.0+pkg.<hash>`、一键脚本输出头部回显 VERSION.txt。
- DOI 仍为 [ZENODO-DOI] 占位,未伪造。

### 9.3 干净目录复验(sanitized 包)
版本头回显 `sha256:c6d986c89a4413fd`;H1 10/0 p=0.001953、H5 0.000977、
sham 10/10、信标 20/20 与 0/20、冻结实现 Holm 1.5114e-9 逐位、
508/390、路由族 280/99 键 0 差异、全部引用 p match=True、
token 2.05–3.74×。全部一致。

## 10. 官方模板迁移(2026-10-05,第七轮)

用户提供官方模板骨架(模板.txt)与官网要求(官网要求.txt)后完成迁移:
- wlpeerj.cls 接口等价替身(官方 cls 不可下载;替身实现模板全部宏接口,
  文件头与 TODO_FOR_AUTHOR #1 注明投稿时粘贴进 Overleaf 官方模板换回);
- peerj_main/peerj_supplementary 换 \documentclass[fleqn,10pt,lineno]{wlpeerj},
  letterpaper+1in+Times,作者块/摘要前置/Keywords/Acknowledgments 按模板结构;
  正文与全部数字零改动。
- 官方要求核对:摘要 342 词/2645 字符(限 500/3000 ✓,撤回 350 词风险);
  18 页(<35 页收费线 ✓);LaTeX 投稿图可嵌入 ✓;另备 figures_upload/
  Figure 1..5.pdf(letter 整页)供系统上传;pan.baidu 禁用提醒。
- 复核:4 份 PDF 0 错误 0 未解析;非行号越界字符 0;Table 2 单页;
  p3 involves 标签边缘交叉目视可接受(图与 a4 版相同,不改)。
- 干净目录重跑:包版本标识不变(sha256:c6d986c8…),全部关键数字一致。

## 11. 官方 wlpeerj.cls 替换(2026-10-05,第八轮)

用户提供官方 cls(Overleaf v1.2)后完成替换:接口对齐(删 \keywords——
官方 2016 已移除;apalike 由 cls 设置;包去重)、左 5cm 版式下三张宽表
列宽微缩 + tabcolsep 3pt → peerj_main 0 overfull;supp 补 \theabstract
空定义 + \newgeometry 对称版式 + 长路径断行。figures_upload 重制
(1-3 裁剪至 letter 页、4-5 矢量原件)。终态:peerj_main 18 页、
peerj_supplementary 14 页,均 0 错误 0 未解析;干净目录重跑一键复现
全部一致,包版本标识不变(sha256:c6d986c89a4413fd)。
