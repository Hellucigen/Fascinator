# 投稿前检查清单(Submission Checklist)

投稿目标期刊确定后逐项执行;每项标注状态与日期。

## A. 期刊与政策
- [ ] **预警/停刊核查**:在 Web of Science Master Journal List 确认目标刊 SCIE 收录且非 On Hold/Ceased;在 Scopus Source List 复核;对照 Clarivate/高校图书馆预警名单。(状态:TCDS/JAAMAS/JAIR/Adaptive Behavior/Neurocomputing 均为主流出版商,初核无预警;**待投稿日复核**)核实日期:____
- [ ] **APC 路径确认**:选择订阅制(免 APC)路径投稿;cover letter 无 OA 排版承诺。(状态:五刊均有免 APC 路径,见 journal_table.md)核实日期:2026-10-01
- [ ] **预印本政策**:确认目标刊的预印本政策(JAIR/Neurocomputing/Springer/IEEE/SAGE 均普遍允许 arXiv 预印本;以刊页为准)。若准备发 arXiv,在 cover letter 中声明。(状态:**待确认**,确定期刊后核实)
- [ ] **格式模板切换**:通用模板(article/ctexart)→ 目标刊模板;核对双栏/单栏、引用格式、图表位置要求、字数/页数限制。
- [ ] **补充材料规范**:当前 supplementary 为独立 PDF(S1–S14);按刊要求可能需拆分"online supplement"与"appendix"。

## B. 作者与声明
- [ ] **署名与单位**:EN 版作者块为 "Kailin Yan, Department of Computer Science, 2024015943@st.cupk.edu.cn";ZH 版 "颜凯临,计算机科学系"。**作者须核对**:正式英文单位全称(如CUPK 全称)、是否加 ORCID、通讯作者标注、邮箱是否为主用邮箱。
- [ ] **作者贡献声明(CRediT)**:单一作者;建议写 "Conceptualization, Methodology, Software, Investigation, Data curation, Writing – original draft, Writing – review & editing: K.Y."
- [ ] **利益冲突声明**:无 competing interests(正文与 cover letter 已含)。
- [ ] **数据可用性声明**:正文 "Data and code availability" 段已含;按刊要求改为指定句式,并附 DOI 占位。
- [ ] **伦理声明**:不涉及人类/动物受试者(合成沙盒环境);按刊模板填写"Not applicable"。
- [ ] **资助声明**:若有基金须列;无则 "No funding was received for this research."
- [ ] **AI 使用声明**:按刊 2025+ 惯例如实披露写作工具使用(作者决定具体表述)。

## C. 稿件自检(技术)
- [ ] 双版本编译零致命错误、零未解析引用(main_v2/main_zh_v2、supplementary_v2/supplementary_zh_v2)。(状态:**已完成**,2026-10-01)
- [ ] 向量级+文字级排版双扫描清零(四份 PDF)。(状态:**已完成**,2026-10-01)
- [ ] 数字差异审计通过:新增数字仅来自阶段四实验。(状态:**已完成**,见 deliverables/audit/NUMBER_DIFF_AUDIT.md)
- [ ] 所有图表引用顺序正确、caption 自足(已含样本量与来源)。
- [ ]参考文献核对:19 条引用均在 references.bib;补齐 hart2008opencog 等的卷期页(投稿前人工核对)。
- [ ] anonymity:若投双盲刊,移除作者块/致谢并匿名化 llm_secret 等配置。

## D. 数据与代码公开
- [ ] 代码仓库:去除 llm_secret.json(保留 example)、清理运行时数据后公开;README 指向 deliverables/REPRODUCE.md。
- [ ] Zenodo:按 ZENODO_METADATA.md 建 deposition,上传归档(注意体积,可分层:核心统计文件 vs 全部原始 run);拿到 DOI 后回填正文数据声明。
- [ ] Claim→Evidence 对照表随工件提交(补充材料 S14)。
- [ ] 预注册记录:core_incremental_value/manifest.json + 新实验 DESIGN.md 一并归档。

## E. Cover letter 与 Highlights
- [ ] cover letter 填入目标刊名与适配句(占位符 [JOURNAL NAME] / [按刊调整一句])。
- [ ] highlights 3–5 条,每条 ≤85 字符(Elsevier 必需;其他刊可选)。(状态:已备,见 highlights.md)
- [ ] 建议审稿人(可选):3–5 名非合作者,附邮箱与理由。
