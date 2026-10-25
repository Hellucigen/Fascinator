# DESIGN — D-flat embedding 检索基线核实与零 LLM 检索可达性检验(embedding flat check)

日期:2026-10-01(运行前冻结)。状态:**设计冻结 → 执行**。

## 1. 背景与假设

- 论文重构阶段发现:信标/路由战役中的 flat 对照(条件名 D-flat)**已经**是真实句向量检索:
  `run_exp_routing_v2.FASContext.flat_focus` 调用 `embedding_manager.EmbeddingProvider`
  (本地公开模型 **BAAI/bge-small-zh-v1.5**,sentence-transformers 格式,路径 E:/Models/bge-small-zh-v1.5),
  对全图节点 id 编码,与任务文本做余弦相似度 Top-k,无激活、无传播、无路径结构。
- 因此本实验不另造基线,做两件事:
  - **核实(import 级)**:程序化确认 flat_focus 的实现路径与模型身份,输出到 verification.json。
  - **零 LLM 检索可达性检验(新数字来源)**:在信标装配(生产建图路径 + 配方闭包)上,
    对任务文本 "Obtain 1 oak_planks in inventory." 计算全图节点 embedding 相似度排序,
    记录 物品:oak_planks 与 物品:oak_log 的名次,并对 20 个配对种子逐个重建装配后重复测量。
- 假设 H:排序把 物品:oak_planks 送入 Top-8(信标战役 k=8)——这是 D-flat 20/20 的使能条件。
- 失败判据:若任一种子装配下 oak_planks 不在 Top-8,则"D-flat 经由 embedding 检索解锁配方链"
  的机制解释需要修正,如实记录。

## 2. 条件(冻结)

- 图装配:与信标战役 step-0 完全一致(SandboxWorld + install_fake_bridge + BeaconFASContext,
  配方闭包经生产建图路径;20 配对种子各自重建,测量 step-0 状态,不注入任何观测/动作)。
- 查询文本:与战役相同的目标文本;编码与相似度计算调用与 flat_focus 相同的
  EmbeddingProvider 实例与归一化余弦。
- 指标:oak_planks / oak_log 节点在全图相似度排序中的名次(1-based)、Top-8 是否命中、
  以及Top-8 列表内容。20 种子图相同则结果应逐种子一致(图构建确定性)。

## 3. 样本量与检验(冻结)

- n = 20(与信标战役配对种子数一致);纯描述性可达性测量,无统计检验
  (确定性沙盒,单一装配状态,不构成方差推断——与论文阶段三的表述降调一致)。

## 4. 运行与提取

- 运行:`run_check.py`(零 LLM;输出 verification.json + raw_ranks.jsonl + analysis.json)。
- 提取:`extract.py` 程序化产出论文引用的全部数字。
