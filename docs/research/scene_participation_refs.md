# 说话场景参与认知与表达 · 研究文献记录

> 记录日期：2026-10-20。关联改动：`FAS-Cognitive/continuous_cognition.py` 的
> `SCENES / scene_for_ci / build_proactive_user`（主动表达定调参与）。
> 书目元数据以任务书给定值为基础整理；**未逐篇在线核对作者全名与页码**
> （本地项目约束不产生额外网络请求），标 ⚠ 的字段待将来引用前对照官方页核实。
> 另见 `docs/REFERENCES_dialogue_memory.md`（对话记忆与调制机制两批文献）。

## 每篇真正研究了什么 · 与 FAS 的关系

**1. Zwaan & Radvansky (1998), Psychological Bulletin 123(2): 162–185.**
情境模型（situation model）综述：语言理解产出的不是字面命题的堆栈，而
是一个包含"此时、此地、谁、在做什么"的心理情境；后续加工（推理、记忆、
一致性判断）都由当前情境模型引导，事件边界（时间/空间/主角/意图切换）
会触发记忆更新代价。
→ FAS 关系：本次改动把"这次说话落在哪个情境"（刚遇到的小事 / 接着用户
的话 / 空闲随想）作为生成前的显式情境，取代"材料全平铺、模型自行编织"。
文献结论支持**情境影响语言加工**；"给陪伴体生成侧注入情境定调能降低无
依据升华"是 FAS 自己的假设（待观察）。

**2. Zheng, Milic-Frayling & Zhou (2023), ACL 2023: 7822–7839.** ⚠页码待核
Contextual Knowledge Learning：把对话所处上下文中习得的知识注入生成模型，
使回复随语境变化而非只用参数化常识。
→ FAS 关系：同方向先例——上下文信息应当**参与生成**而不是只当展示标签。
FAS 的场景判定读的是图谱已有数据（CI basis、节点 source、对话原文），
等价于"从当前上下文取知识再说话"。

**3. Tang et al. (2024), INLG 2024: 371–383. CADGE.**
上下文感知的对话生成 + 图结构化知识聚合：按当前对话上下文对知识图邻域做
聚合，决定哪些结构化知识真正进入回复。
→ FAS 关系：与本项目最接近的已发表机制——"上下文条件的图取数"。FAS 的
basis/激活前沿 + 本次的场景判定构成同一思路的极简实现：场景（浏览偶遇/
聊天延续）决定这批图素材按什么深浅讲。CADGE 证明的是检索聚合可行；FAS
的"场景决定表达深度"未经文献证明。

**4. Park, Joo, Kim & Kim (2024), EMNLP 2024: 21167–21182.**
生成式子图检索（KG 接地的对话生成）：由对话历史与目标回复联合决定检索
哪个子图，而非固定拓扑规则。
→ FAS 关系：支持"对话单位级的子图选择"这一环。FAS 已有近似物（CI basis
= 为这次话留的证据子图）；本次改动补的是另一半——子图选定后，**讲多深**
由场景而非激活度决定。激活度与表达深度解耦是 FAS 假设。

**5. Zhang et al. (2018), ACL 2018 (P18-1102).** ⚠作者全名待核
控制神经回复生成的**具体度**（specificity）：模型可被引导在"泛泛而谈/
具体回应"之间选择，且具体度是可学习/可控的维度。
→ FAS 关系：这次修的正是它的反面问题——Haru 逢小事必升抽象（具体度失控）。
文献用训练手段控制；FAS 用 prompt 条件化实现近似功能（场景块 + 定调句），
未训练，效果依赖模型对条件的服从度。

**6. Gupta, Jhamtani & Bigham (2022), Findings of NAACL 2022.** ⚠作者全名待核
目标引导的回复生成：结合常识知识与数据增广，让回复朝一个显式目标（要表
达什么）收敛，减少漫无边际的发散。
→ FAS 关系：定调句本质是给这次话一个显式目标（"说这次遇到本身"），把
"被看见/霍桑效应"这类旧背景标注为记忆而非本次结论——目标先行，联想自由。

## BibTeX（供论文引用）

```bibtex
@article{zwaan1998situation,
  author  = {Zwaan, Rens A. and Radvansky, Gabriel A.},
  title   = {Situation Models in Language Comprehension and Memory},
  journal = {Psychological Bulletin},
  volume  = {123}, number = {2}, pages = {162--185}, year = {1998},
  doi     = {10.1037/0033-2909.123.2.162},
  url     = {https://pubmed.ncbi.nlm.nih.gov/9522683/} }

@inproceedings{zheng2023contextual,
  author    = {Zheng, Wanqiu and Milic-Frayling, Natasa and Zhou, Kun},
  title     = {Contextual Knowledge Learning for Dialogue Generation},
  booktitle = {Proceedings of ACL 2023}, pages = {7822--7839}, year = {2023},
  doi       = {10.18653/v1/2023.acl-long.433},
  url       = {https://aclanthology.org/2023.acl-long.433/} }

@inproceedings{tang2024cadge,
  author    = {Tang, Chong and Zhang, Haotian and Loakman, Thomas and
               Yang, Baosong and Goetze, Stefan and Lin, Chin-Yew},
  title     = {{CADGE}: Context-Aware Dialogue Generation Enhanced with
               Graph-Structured Knowledge Aggregation},
  booktitle = {Proceedings of INLG 2024}, pages = {371--383}, year = {2024},
  doi       = {10.18653/v1/2024.inlg-main.31},
  url       = {https://aclanthology.org/2024.inlg-main.31/} }

@inproceedings{park2024subgraph,
  author    = {Park, Jisu and Joo, Minsup and Kim, Jin-Man and Kim, Hyoung Joong},
  title     = {Generative Subgraph Retrieval for Knowledge
               Graph-Grounded Dialog Generation},
  booktitle = {Proceedings of EMNLP 2024},
  pages     = {21167--21182}, year = {2024},
  doi       = {10.18653/v1/2024.emnlp-main.1179},
  url       = {https://aclanthology.org/2024.emnlp-main.1179/} }

@inproceedings{zhang2018specificity,
  author    = {Zhang, Jiacheng and others},
  title     = {Learning to Control the Specificity in Neural Response Generation},
  booktitle = {Proceedings of ACL 2018}, year = {2018},
  url       = {https://aclanthology.org/P18-1102/} }

@inproceedings{gupta2022target,
  author    = {Gupta, Ankur and Jhamtani, Hitarth and Bigham, Jeffrey P.},
  title     = {Target-Guided Dialogue Response Generation Using Commonsense
               and Data Augmentation},
  booktitle = {Findings of NAACL 2022}, year = {2022},
  url       = {https://aclanthology.org/2022.findings-naacl.97/} }
```

> ⚠：`others` / 全名不确定的两条，正式引用前必须对照 ACL Anthology 官方页补全。

## 文献已有 vs FAS 假设（不得混写）

- 已有结论：情境模型引导语言加工（#1）；上下文/目标/具体度可以调控回复
  内容与风格（#2/#5/#6）；对话条件的图检索+聚合有效（#3/#4）。
- FAS 假设（未经验证，需本项目自己观测）：①从图谱既有数据派生的场景判
  定足以给语言层定调；②场景定调能降低"逢小事必升华"而不误伤真实关联的
  深入展开；③把场景写进 CI 留痕（`extra_attrs.scene` + 气泡 refs）可审计
  并支撑后续统计。验收以 Haru 实际话语与气泡记录为准，不以上述论文背书。
