# FINAL_REVIEW — 反向审稿（PHASE 11–12）

对编译后 PDF（main.pdf 14 页 / main_zh.pdf 14 页）的三位模拟审稿人。只采纳提高 scientific correctness / clarity 的修改；需要新实验的意见一律进 Future Work。

## Reviewer A — Cognitive Architecture

**Major**
1. "Unified graph" 的卖点需要与 OpenCog AtomSpace 更锋利的对比——目前差异（单图/单动力学/显式写回）散落在 Related Work 与 Discussion。→ 已在 Related Work 集中为三点差异。
2. 学习内容的"新颖性"依赖配方表与掉落表已在图中这一前提——审稿人会问"初始图到底有什么"。→ 已在 §5.2 明确"配方表知道什么能合成什么；动作产生变化的事实只能由做确立"。

**Minor**
3. Algorithm 3 是伪代码式概括而非逐行对应。→ 接受，正文已声明其为通道概括。
4. Eq.(1) 的归一化分母描述需与代码逐字核对。→ 已按 diffusion_engine.py:1035 书写。

**风险**：中。架构创新性偏工程化，但声明与证据对齐后无过度声称可攻。

## Reviewer B — AI / Agent Learning

**Major**
1. "Is 13 nodes learning?"——单任务族、单 seed 谱系展示。→ 已补充：隔离对照（B1=0）+ 分拣（11/15 实质）+ P0 对照（结构不存在时学不出）三层；并明确 "small in content, complete in loop" 定位。
2. 无外部 baseline（其他记忆架构在同任务上的表现）。→ Future Work（超出本文范围；不加装 baseline）。

**Minor**
3. 账本通道的 ±0.05 prior bonus 是小机制，行为差分（13 vs 16）虽确定但量级小。→ 已如实写"changes how, not whether"。
4. Hebbian 行为面为零——已作为 negative result 正文报告。

**风险**：中。 learning 声明已收窄到支架式获取，无 from scratch 表述。

## Reviewer C — Methodology / Experimental Rigor

**Major**
1. 5 seeds 确定性设计无统计推断——是否足够？→ 已声明描述性口径 + 逐种子数据全公开 + 无显著性声称；这是设计选择而非疏漏。
2. smelt simplification 是否污染长链结论？→ 已在 §4.2/§9.6 双处标记，且长链核心结论（L3→L3b 分解、−扩散更快）不依赖该环节的机制语义。
3. P0 失败的机制解释依赖一次诊断复现，归档是否完整？→ 诊断事实已写入 fact DB（P0_diagnostic）；原始归档在 prior_boundary 族。建议（已列入 README）：发布诊断复现脚本。→ artifact 已含复现入口。

**Minor**
4. "over 650 runs / 19 families" 应给精确数。→ manifest 计数入事实库（manifest_counts），正文用"more than 650"保守表述。
5. 图 2(b) 与 Table 4 的 11+4=15 关系（2 窗污染为子集）需防读数冲突。→ 表注已明确子集关系。

**风险**：低-中。协议透明度是本文强项；无隐藏失败。

## 结论

无一条意见要求新实验或机制修改。所有 "significant/causal/improves/enables/demonstrates" 类措辞已按证据等级复核：
- "causal" 仅出现于限定句（evidence-weighted regularity / causal isolation / causal footprint），均带规则化口径；
- 无 "significant/improves/enables" 类无证据声明；
- "demonstrates" 仅用于有 5/5 确定性数据支撑的句子。

**PAPER READY FOR SUBMISSION（按声明—证据对齐口径）**
