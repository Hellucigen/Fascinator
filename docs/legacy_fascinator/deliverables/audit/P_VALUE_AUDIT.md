# P_VALUE_AUDIT.md — 论文 p 值逐项审计(2026-10-05,定稿轮)

方法:对论文中出现的每个 p 值,记录检验方法、单/双侧、预注册声明、
校正方式与 m、实现来源(分析脚本行号)、原始数据来源,并用原始数据
重算核对。口径:p 值均为原始 p(除显式标注 Holm/Bonferroni 处);
单侧检验仅在预注册声明处使用;精确方法用于 n≤25。
该口径已写入正文方法节(EN §4.2 / ZH §4.2 "Statistical conventions /
统计口径")。

## 审计表

| # | 论文位置 | 声称 | 检验方法 | 侧向 | 预注册声明 | 校正 | 实现来源 | 重算 | 判定 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 摘要/§5.1 信标 | 20/20 vs 0/20,p=2e−6 | McNemar 精确 | 双侧 | 信标战役预注册 | 无 | scripts/analyze_beacon.py::exact_mcnemar(尾部×2) | 2×2^−20=1.9e−6 ✓ | 一致 |
| 2 | §5.1 D-flat 行 | p=1.0(McNemar);决策 Wilcoxon p=0.72 | McNemar 精确;Wilcoxon | 双侧 | 同上 | 无 | analyze_beacon.py + wilcoxon_signed_rank(默认两尾) | ✓ | 一致 |
| 3 | §5.3 机制战役 | ΔJCG 全负;**反方向 Holm p=1.5e−9**,r=0.615 | Wilcoxon | 单侧(实现为双侧之半,与符号无关) | 预注册声明单侧,方向 ΔJCG>0(FAS>B2) | Holm m=4(仅主族) | analyze.py:114-119(one_tailed=True;p_fas_gt_b2=p_fas_lt_b2=3.778e-10)+ metrics.holm_correct | 冻结输出逐位一致(1.5113858911727241e-09);预注册方向尾部=补尾≈1 | **方向归属已修正**(见 §K) |
| 4 | §5.3 关系方向 | 21 检验 p=0.001953,"n=10 可得的最小 p" | Wilcoxon(精确) | **双侧**(scipy 默认) | 声明为 21 检验单族,未声明侧向 | 无(单族描述) | scripts/run_exp_reldir.py:366(无 alternative 参数=two-sided) | 双侧最小=2×2^−10=0.001953 ✓ | **表述错误已改正**:原"单侧最小 p"→"双侧最小 p(双侧精确 Wilcoxon)"(EN/ZH 主文+补充 S9) |
| 5 | §5.5 C 段 | 9/10 vs 0/10,McNemar p=0.0039;Holm p=0.0117 | McNemar 精确 | 双侧 | 战役 v2 协议 | Holm(实验内) | capability_gap_v2/analyze_campaign.py::mcnemar_exact(尾部×2)+holm | 2×2^−9=0.0039 ✓ | 一致 |
| 6 | §5.5 E2 段/§5.8(E)/S15 表 | 10.5→7.2,p=0.011 | Wilcoxon | 单侧 | 战役 v2 协议(方向性) | 无 | **原值=单侧正态近似**(method=approx):0.010784≈0.011;单侧精确=0.009766 | 重算单侧精确 0.0098 ✓ | **方法混用已统一**:与 T 的精确法统一后改报单侧精确 p=0.0098(4 处:EN/ZH 主文 §5.5+§5.8、S15 表);原 approx 值 0.011 在此存档 |
| 7 | §5.5 T 段 | 12.0→7.8,p=0.002 | Wilcoxon(精确) | 单侧 | 同上 | 无 | 会话内计算(归档脚本未含 T 族);本轮由 raw_T.jsonl P2.fail_gathers 重算 | n=9 有效配对,单侧精确=0.001953 ✓ | 一致;正文补记 "$n{=}9$ 有效配对"(10 计划,1 个 harness 无效 run 按预注册有效性规则排除) |
| 8 | §5.5 I 段 | I3 vs I5,Holm p=0.041 | Wilcoxon | 双侧 | 战役 v2 协议 | Holm(实验内) | analyze_campaign.py::paired_wilcoxon(alternative="two-sided") | ✓ | 一致 |
| 9 | §5.7 路由(探索性) | 19/20 vs 15/20 未校正 p=0.046;4.15 vs 2.3/2.8,p=0.003/0.044;校正后 ≈1 | 见 core_routing_v2 报告 | 未声明 | 探索性(预注册外的方向性观察) | 战役 280 检验 Bonferroni(正文声明) | core_routing_v2/EXPERIMENT_REPORT.md | — | 一致(探索性,不承载主张;正文无侧向声明) |
| 10 | §5.6 PSA H1/H3 | 10/0,McNemar p=0.00195 | McNemar 精确 | 双侧(min(1,2·尾)) | PSA 预注册(主假设 α=.05) | 无 | persistent_state_advantage/analyze_psa.py::mcnemar | 2×2^−10=0.00195 ✓ | 一致(正文"精确 McNemar…最小 p"与双侧实现相符) |
| 11 | §5.6 PSA H5 | 2.8 vs 7.7,p=0.00098 | Wilcoxon | **单侧**(alternative="greater") | PSA 预注册 | 无 | analyze_psa.py:80 | 0.000977 ✓ | 一致 |
| 12 | S16 对照表 | T2 McNemar p=.00195→Bonf .0156;T3 Wilcoxon p=.00195→.0156 | McNemar 精确;Wilcoxon | 双侧 | controls 预注册(m=8) | Bonferroni m=8 | persistent_state_controls/analyze_controls.py(alternative="two-sided") | ✓ | 一致 |
| 13 | §5.4 重跑 | 无 p 值(20/20 一致性计数) | — | — | — | — | — | — | 不适用 |

## 结论

- 审计族数:13;**不一致 2 处**,均已按原始数据重算并统一:
  1. 关系方向 p=0.001953 的"单侧最小"标注(实为双侧,scipy 默认)
     → 表述错误,改正文(EN/ZH 主文 + 补充 S9,共 4 处)。
  2. E2 的 p=0.011 为单侧正态近似值,与同族 T 的单侧精确法混用
     → 统一为单侧精确 p=0.0098(重算可溯源),共 6 处替换。
- 停止条件检查:两处不符均可由原始数据与实现代码完全解释
  (一处为默认参数的双侧、一处为 approx/exact 方法差异),
  属表述/方法统一问题,不构成"无法由原始数据解释"的停止条件。
- 机制战役单侧声明(analyze.py one_tailed=True)与论文表述相符;
  beacon/对照/PSA-H1 的双侧实现与论文"精确 McNemar"表述相符
  (双侧精确下 10/0 的最小 p=0.00195,论文已注明)。

## K. ΔJCG 检验方向归属核对(2026-10-05,第三轮)

- 预注册(manifest.json):primary_family 方向 = ΔJCG>0(FAS>B2),单尾。
- 冻结实现:单侧 p = 双侧之半(与符号无关)→ p_fas_gt_b2 = p_fas_lt_b2
  = 3.7784647279318103e-10(n=50,四条件相同);Holm(m=4)挂名义预注册
  方向字段 → 1.5113858911727241e-09。
- 归属:全负数据上该数值 = 反方向(B2>FAS)尾部;预注册方向尾部 = 补 ≈1。
- 论文修正:16 处(摘要/贡献 2/图 2 注/§5.3/表 3/图 5a 注/§4.2 口径句/
  S6/S14 及全部 ZH 镜像)改为"反方向 Holm p=1.5e-9",§5.3 与 §4.2 展开说明
  预注册方向尾部 ≈1;H3 被拒绝的结论不变。数字全部取冻结实现输出。
- 停止条件检查:实现行为与字段名的关系可从代码完全解释(单侧=双侧之半),
  不构成"无法解释的矛盾"。

## L. 单侧 p 函数调用点普查(2026-10-05,第四轮)

方法:全仓检索 `wilcoxon_signed_rank|one_tailed|mcnemar|wilcoxon(` 的全部
分析侧调用点(experiments/、scripts/、deliverables/experiments_new/;
生成侧 runner 不计),逐点记录:实现口径、预注册方向、数据实际方向、
论文引用位置。

| # | 调用点 | 实现口径 | 预注册方向 | 数据实际方向 | 论文引用 | 判定 |
|---|---|---|---|---|---|---|
| L1 | core_incremental_value/runners/analyze.py:114-119(主检验 + p_fas_gt_b2/p_fas_lt_b2)| metrics.wilcoxon_signed_rank,one_tailed=True = **双侧之半、与符号无关** | ΔJCG>0(FAS>B2) | 全负(FAS<B2) | 摘要/贡献2/图2注/§5.3/表3/图5a/S6/S14——已在上轮修正为"反方向 Holm 1.5e-9" | 已修正 |
| L2 | analyze.py:136 `p_mrr = wilcoxon_signed_rank(mrr_b, mrr_f)`(S_{label}_mrr,secondary)| **两尾默认**(无 one_tailed)| 无方向预注册(描述性)| FAS MRR<B2 | 论文引用 MRR 数字(0.0435/0.0426 vs 0.5/0.5)**不带 p**(§5.3、表 3、S6)| 无需修正 |
| L3 | analyze.py:138 `p_j1`(one_tailed=True,diffs=FAS 的 JCG−0)| 单尾=双侧之半 | 名义方向 JCG>0 | JCG 全正(200/200)| **计算后未存储、未使用**(analysis.json 无该字段;死代码)| 无影响,记录 |
| L4 | analyze.py summary `jcg_binom_p_gt_half` = metrics.exact_binomial_gt0(精确二项,方向 JCG>0.5,方向定义明确)| 单尾,方向真实 | JCG>0.5 | 200/200 全正(方向一致,取值无歧义)| 论文引用率(200/200)**不引用 p** | 无需修正 |
| L5 | scripts/analyze_beacon.py:117 → research_audit/mechanism_falsification/metrics.py:120 `wilcoxon_signed_rank(d1,d2)` | **两尾**(该版本签名无 one_tailed 参数)| 无(描述性)| — | p=0.72 等;论文无侧向声明 | 一致 |
| L6 | analyze_beacon exact_mcnemar(尾部×2)| 双侧精确 | 无声明 | — | p=2e-6 | 一致 |
| L7 | persistent_state_advantage/analyze_psa.py:80 H5(scipy alternative="greater",x=reset,y=full)| 单尾,**方向真实** | reset_fails>full_fails | reset 7.7>full 2.8(方向一致)| "单侧 Wilcoxon p=0.00098" | 一致 |
| L8 | analyze_psa mcnemar(min 尾×2)/ controls analyze(同式 + scipy two-sided)| 双侧 | 无声明 | — | 0.00195/Bonf .0156 | 一致 |
| L9 | capability_gap_v2/analyze_campaign(mcnemar_exact ×2;scipy two-sided)| 双侧 | C/Holm 等无侧向声明 | — | 0.0039/0.0117/0.041 | 一致 |
| L10 | scripts/run_exp_reldir.py:366(scipy 默认 two-sided)| 双侧 | 21 检验单族,无侧向声明 | B 图 ρ/可达性全面高于 F 图(方向与叙述一致)| 0.001953(已改"双侧最小")| 一致 |
| L11 | cross_episode_recomb/analyze.py:99(scipy alternative="greater",diffs=G3−baseline 分数)| 单尾,**方向真实** | G3>baseline | 反向(G3 更差)→ wilcoxon p=1.0(H5s/H6s,正确);mcnemar 两尾 | 论文只表述"跨经历行为优势不成立"**不引用 p** | 一致 |
| L12 | shared_hub_sweep/extract.py(mcnemar_exact ×2;scipy two-sided exact)| 双侧 | 无侧向声明 | O3 格 FAS 30/30 vs 0/30 | 论文引用计数(30/30 vs 0/30)**不引用 p**(1.9e-9 仅存于实验报告)| 一致 |
| L13 | core_routing_v2(p=0.046/0.003/0.044/0.064/0.265)| **已归档分析脚本 analyze_routing_v2.py(2026-10-05 补)**:配对双尾 Wilcoxon(scipy 默认),族 m=280(10 条件对×4 任务×7 指标),Bonferroni;与归档 statistics.csv 99 个共享键 0 个 round-6 差异;全部引用 p 逐位复现(0.0455/0.003156/0.044277/0.064142/0.265405);token 开销 vs direct 2.05–3.74×(论文 2.1–3.7×)| 无侧向声明(两尾,无需)| — | 论文"未校正 p=0.046"、"校正后 ≈1"(0.046×280→1.0)、S11 描述性 | **已归档并逐位复现** |
| L14 | relation_direction S9 "dual input p=0.002"(supp L328/L326)| 即 paired_statistics.csv I3/spearman_score_act 行,**两尾**(scipy 默认)| 无侧向声明 | mean_F 0.325 < mean_B 0.645(方向与叙述一致)| "(dual input: p=0.002)" 描述性 | 一致 |

**结论**:唯一具有"方向与符号无关"性质的实现是
core_incremental_value/runners/metrics.py 的 wilcoxon_signed_rank;其进入
论文的唯一链路(L1)已在上轮修正。本轮普查的其余调用点均为两尾实现、
方向真实的单尾实现、方向与数据一致且论文未引用其 p、或论文引用计数
而非 p——**无需新的论文措辞修正**。冻结实现未改动;无数据改动。

## P. 一致性与表述修订轮(2026-10-06,任务书 12 项)

- E2/T 预注册判定(时间线证据):战役协议 v1.0 冻结于 2026-10-01,实验卡仅
  A/B/C/E/F/I/K;修订记录 v1.1(10-01,K/I/B)、v2(10-02,F 重做+I 表示研究)
  均未纳入 E2/T;raw_E.jsonl/run_E2.log=10-02、raw_T.jsonl/run_T.log=10-03
  均在 E 结果之后 → **E2/T 为 post-hoc**(方向在设计时固定,非预注册)。
  Table 2 战役行已拆分为 C/I/B(pre)与 E2/T(post)两行;§4.2 口径句与 §5.5
  正文同步标注。
- T 的 n=9:fas-ef 组 seed 0 两次端点错误(HTTP 402 配额、连接错误)被
  runner 标记 harness_valid=False/failure_class=ERROR 并排除;协议 §19 规定
  smoke 级有效性与失败即停,未规定逐 run 端点错误重跑规则——正文如实写明。
- H1/H3/H5 Bonferroni(m=3,由冻结 statistics.json 计算):
  0.001953→0.0059、0.001953→0.0059、0.000977→0.0029,三者均 < .05;
  已写入 §5.6。
- "match FAS"→"match or exceed":T2 持平(10/10 组)、T3 基线失败重复
  0.0 低于 FAS-full 2.8(摘要/§5.6/§5.8,EN+ZH+peerj)。
- 装配差异声明:战役 E 的 10.5 vs 1.0(未接线)与 PSA 的 2.8 vs 7.7
  (装配层接入负极性通道)为不同装配,正文一句+摘要指向(代码证据:
  PSA make_fas 设 ef_context=True;战役 E1 未接线——ADDENDUM §F)。
- 新增文献(全部经 arXiv abs 页核对,2026-10-06):HippoRAG(Gutiérrez
  et al. 2024, NeurIPS 2024, arXiv:2405.14831)、GraphRAG(Edge et al.
  2024, arXiv:2404.16130)、MemGPT(Packer et al. 2023, arXiv:2310.08560)、
  Voyager(Wang et al. 2023, arXiv:2305.16291);Related Work 措辞改
  "To our knowledge/据我们所知"。
- Reporting guidelines 如实化:删除非标准名称 "preregistered-experiment
  reporting",改为"无适用清单;实际做法=执行前冻结仓库设计文档
  (非公共注册平台)+确定性零 LLM 重跑+全量归档"。
- 图内文字:fig_diffusion_boundary (a) 与 fig_evidence_matrix dJCG 行
  补 reverse-direction 限定(gen_figures_new.py 重绘,数值读归档
  analysis.json;目视无重叠)。
