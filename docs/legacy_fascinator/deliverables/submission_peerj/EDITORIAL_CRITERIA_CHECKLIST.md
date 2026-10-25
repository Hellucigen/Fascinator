# EDITORIAL_CRITERIA_CHECKLIST.md — PeerJ CS Editorial Criteria 自检(2026-10-05)

> 核对方式说明:官方三页为 JS 渲染,直接抓取失败(见 REPRO_REPORT §0);
> 要点经官方搜索片段确认(作者封面页第一页、在线信息一致、author-year
> 参考文献按 作者/年份/标题 排序、代码与原始数据经仓库+DOI 可得、报告
> 规范清单)+ 任务书给定要点执行。投稿前应人工过一遍官网页面(TODO #7)。

## A. Basic reporting(基础报告)

| # | 检查项 | 状态 | 证据位置 |
|---|---|---|---|
| A1 | 标准章节结构(Abstract/Intro/M&Ms/Results/Discussion/Conclusions),偏离须有理由 | ✅(1 处偏离,理由已写) | peerj_main.tex;偏离理由:INTEGRATION_NOTES "PeerJ 章节方案" |
| A2 | 摘要准确概括研究 | ✅(含全部核心数字与负结果) | peerj_main.tex Abstract |
| A3 | Author Cover Page 为手稿第一页;与在线信息一致 | ⚠ 草稿已备,单位/邮箱/ORCID 待作者确认 | deliverables/submission_peerj/Author_Cover_Page.md |
| A4 | 行号 | ✅ | peerj_main.pdf(lineno,连续行号) |
| A5 | 参考文献完整、无未引用文献;author-year;按 作者/年份/标题 排序 | ✅/⚠ | peerj_main.pdf(natbib+plainnat,author-year;排序为 plainnat 的 author-year-label,与"标题"第三关键字有微小差异 — REPRO_REPORT §1 差异表) |
| A6 | 图表编号、引用自洽;图注独立可读 | ✅ | 编译 0 未解析引用;图注含来源小节 |
| A7 | 数据/代码可用性声明 | ✅ 草稿(DOI 占位) | peerj_main.tex 声明区;TODO #3(Zenodo 上传) |
| A8 | 报告规范声明 | ✅(预注册规范;无 ARRIVE/PRISMA 适用,如实说明) | peerj_main.tex "Reporting guidelines" 段;补充 S14–S16 |

## B. Experimental design(实验设计)

| # | 检查项 | 状态 | 证据位置 |
|---|---|---|---|
| B1 | 研究问题/假设明确 | ✅ | §4.3(H3)、§5.6(H1/H3/H5)、PSA 预注册 |
| B2 | 预注册、设计冻结、偏差报告 | ✅ | preregistration/ 包内记录;§4.2;S15–S16 |
| B3 | 样本量与功效说明 | ✅(n=10 功效限制显式声明) | §4.1、§7 限制 (4)、P_VALUE_AUDIT 口径 |
| B4 | 对照组恰当 | ✅(含空对照、保结构对照;其呈现不等价已如实标注为局限) | §5.5–5.6、§7 (20) |
| B5 | 统计方法恰当并声明校正 | ✅ | §4.2 "统计口径";audit/P_VALUE_AUDIT.md(13 族逐项) |
| B6 | 实验可复现(环境、种子、代码) | ✅ | 复现包;干净目录验证 5 组关键数字全部重现(REPRO_REPORT §3) |
| B7 | 确定性/端点限制说明 | ✅ | §5.4(S10) |

## C. Validity of the findings(结论有效性)

| # | 检查项 | 状态 | 证据位置 |
|---|---|---|---|
| C1 | 结论与证据强度匹配 | ✅(负结果与归因边界显式;无 L4/通用能力主张) | §6.1 已证明/未证明清单;§7 |
| C2 | 局限性全面 | ✅(20 条编号局限 + (18)(19)(20) 的最新归因) | §7 |
| C3 | 统计显著性不与效应大小混淆;n=10 最小 p 注明 | ✅ | §5.6、P_VALUE_AUDIT |
| C4 | 数据完整性(无 cherry-picking;修复批次单独归档) | ✅ | S16 run 记账段;508/390 可由复现包重算 |
| C5 | 归因不超出对照设计 | ✅(图结构/激活独立贡献标记"未检验";修订对照门槛停止如实写入) | §5.8 (T3)、§7 (20) |

## 风险清单(不满足/待确认)

1. Author Cover Page 的单位/邮箱/ORCID/声明内容未定(A3)。
2. 摘要已压缩到 342 词(≤350;数字与结论未变,删改清单见 REPRO_REPORT §7)。(已解决)
3. 官方 peerj.cls 未使用(结构合规版);正式投稿需在 Overleaf 导入官方模板换壳(TODO #1)。
4. plainnat 参考文献排序与官方"作者/年份/标题"第三关键字有微小差异(REPRO_REPORT §1)。
5. 图的色盲友好度(绿/橙编码)未做正式验证(TODO #8 可选)。
