# 图谱内探索（暂缓意图播种扩散）· 研究文献记录

> 记录日期：2026-10-24。关联改动：`continuous_cognition.py`
> `_defer_to_interest` 增加第二步——探索型意图暂缓时经 `engine.mark_active`
> 把概念播种进活跃前沿（每意图一次），复用既有扩散激活/侧抑制/时间衰减
> 与生活拍的共锚点假设生成器完成图谱内探索。
> 当日在线实际获取 2 篇；2 篇 403 未读，如实标注。

## 实读

**1. Synapse: Empowering LLM Agents with Episodic-Semantic Memory via
Spreading Activation (ACL 2026 Findings, 1108)** — ✅ 摘要级（ACL 页面，
全文 PDF 未拉）。
结论（用到的）：记忆是动态图，相关性经**扩散激活在线涌现**（episodic↔
semantic 节点间沿边传播）；噪声过滤靠**侧抑制 + 时间衰减**；检索超越静态
向量，用**基于激活的图遍历**实现多跳。
→ 影响：`_defer_to_interest` 的播种即"activation-based traversal"的入口
复用——FAS 的扩散引擎本就带侧抑制/时间衰减（Synapse 所列两过滤器为
既有机制，非本次新写），缺的只是"暂缓概念进入活跃前沿"这一个触发。
推测vs事实标注：Synapse 页面未提供该机制——FAS 的分野由既有假设节点
（confidence 0.3、"待验证联想"、hypothesis_leg 无新证据不强化门）承担，
**这是 FAS 自己的设计，不归因该文**。

**2. CoaKG: A Contextualized Knowledge Graph Approach for Exploratory
Search and Decision Making (TGDK 3.1.4, 2025)** — ✅ 摘要级。
结论（用到的）：探索式搜索须被 **purpose 驱动的情境化查询框定**而非开放
遍历；真值相对化（DOWA：真伪取决于声明上下文与任务）。
→ 影响：确认"不造自由遍历器"——图谱内探索被三个既有边界框住：每意图
播种一次、生活拍假设生成器每拍 max_new=1、扩散自身的衰减/抑制。
"purpose=暂缓的探索型意图"是 FAS 工程对应，非该文机制。

## 未读（403）

- **Cognitive Network Science Review (2019, Wiley)**：403。文中引用的
  spreading activation 标准做法（激活源/衰减/路径限制）未经该综述核对，
  本次实现全部依赖 FAS 既有扩散引擎参数，未据该综述调任何数值。
- **Reviving Inert Knowledge (2009 Cognitive Science, Wiley)**：403。
  "共关联结构唤起惰性知识"的方向与既有共锚点假设生成器一致，但本次未据
  它做设计判断——生成器是 2026-10-16 已有实现，本次只是接入触发。

## 验证锚点

- 测试：`test_expression_decision.py` T12a-d（兴趣水位、播种前沿、
  每意图一次、沟通类不转）。
- 既有复用（未改动）：`activities.py::_emerge_hypotheses`（共锚配对，
  防回声室锚点过滤）、`research_beat`（假设按图强度参选调研课题）、
  `_internalize_found`（调研成果内化为语义知识）。
- 实弹：2026-10-24 重启后 4 分钟内未出现新的探索型意图暂缓事件（间歇
  触发），播种路径由单测覆盖；长期频率待观察。
