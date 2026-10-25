# THIRD_PARTY_NOTICES.md — 复现包内第三方内容清单(2026-10-05;只列事实与许可风险,不做许可选择)

范围:`deliverables/zenodo_package/`(与 `_sanitized/` 同构)。逐项为
"包内形式 + 来源 + 已知许可 + 风险"。

## 1. 直接随包分发的第三方内容

**1.1 无。**包内不含任何第三方数据文件、词典、模型权重或二进制资产:
- 嵌入模型(BAAI/bge-small-zh-v1.5):仅在 `code/embedding_manager.py`、
  `code/config.py` 中按名引用;权重不入包(运行时由使用者自行下载)。
- 语音/视觉模型(ear/ 子系统:YAMNet、Paraformer/FunASR、emotion2vec、
  YOLOv8-pose):仅调用代码与本地路径占位;权重不入包。
- ConceptNet:`code/Try/come.py` 是一个独立的探索脚本,只有 CSV 路径
  占位(`INPUT_CSV = None`),包内不含任何 ConceptNet 数据;它不在论文
  任何数字的生成链路上。
- 词法工具 jieba(MIT):代码依赖(import),非分发内容;不在论文数字
  生成链路上。

## 2. 包内数据的第三方派生内容(事实核查结果)

**2.1 ConceptNet 派生:无。**全部图谱快照与实验数据中未检出
ConceptNet/WordNet/Wikidata 派生字段。检索方式:对包内文本文件做
`conceptnet|wordnet|wikidata|dbpedia` 不区分大小写检索,唯一命中为
上述 `Try/come.py` 的路径占位注释。

**2.2 LLM 生成的公共知识节点("expanded_knowledge")。**4 个生产
Minecraft 会话快照
(`data/FAS_Research_Experiments/minecraft/run_20260928_*/snapshots/graph_*.json`,
每个 1 处)含 `type: expanded_knowledge` 节点:2026-09-22 一次性任务中
由 LLM 公共知识扩展出的语义概念节点(`code/graph_expansion.py`,
prompt 驱动、"宁可少加,不要幻觉"约束)。来源:LLM 生成;许可风险:
低(LLM 输出的公共常识性短概念,无长片段复制)。这些快照支撑论文
§5.7 实况观察的图增长数字;论文数字不受影响。

**2.3 Minecraft 配方/方块知识。**实验世界(`code/experiments/
capability_gap_v2/run_experiment.py` 等)内置配方字典(oak_log→
oak_planks、iron_ore→stone_pickaxe 需工具等)。来源:Minecraft 游戏
内的功能性事实(配方关系),以作者自写的代码字典表达。许可风险:低
(游戏机制事实本身不受版权保护;未复制任何受版权保护的文本、材质或
数据文件)。

**2.4 LLM 决策头输出(运行记录)。**信标/战役 v2/持久状态/路由等族的
raw 数据含 LLM(远程端点,温度 0)生成的决策文本。性质:实验运行
记录(附时间戳、token 计数、种子),非第三方受版权作品的再分发。
涉及端点见 `data/llm_config.example.json`(示例,`api_key` 为空)。

**2.5 学术引用。**论文引用的 15 篇文献(references.bib)为正常学术
引用,不随包再分发其内容。

## 3. 许可风险小结(供作者决策,不替你选定)

| 项 | 风险 | 说明 |
|---|---|---|
| BGE/ear 模型权重(不入包) | 无(未分发) | 若使用者按 README 下载,BGE 为 MIT;YAMNet Apache-2.0;YOLOv8 为 **AGPL-3.0**——仅在用户自行运行 ear/ 视觉代码时触发,论文数字链路不使用它 |
| ConceptNet(未使用) | 无(未分发、未派生) | 若未来启用 `Try/come.py`,ConceptNet 数据为 CC-BY-SA 4.0,需注意 share-alike |
| expanded_knowledge 节点 | 低 | LLM 生成的公共概念短词;如需绝对稳妥可在发布版快照中剥离该 4 个节点(属实验数据,本次未动) |
| Minecraft 事实 | 低 | 功能性事实 + 自写表达 |
| LLM 决策输出 | 低 | 运行记录;提供方品牌名出现在元数据与示例配置中(事实陈述) |

**结论:未发现"含隐私或版权不明的数据"——停止条件未触发。**
(隐私维度见 REPRO_REPORT §4:用户名/路径已脱敏,复扫为 0。)
