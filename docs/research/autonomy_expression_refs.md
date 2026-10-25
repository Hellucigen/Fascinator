# 自主表达解封（表达闸门放宽）· 研究文献记录

> 记录日期：2026-10-24。关联改动：`FAS-Cognitive/continuous_cognition.py`
> 三处——①资格门放宽（高激活 semantic basis 算有内容）②`express_threshold`
> 0.78→0.62 + 情绪调制上限 +0.05 ③`_defer_to_interest`（暂缓的探索型意图
> 转 curiosity 兴趣水位，不再空等衰减）。
> 文献均为当日在线实际获取（摘要/正文级）；标注每处"论文结论"与"FAS 工程
> 推断"的边界。另见 `scene_participation_refs.md`、`REFERENCES_dialogue_memory.md`。

## 1. A Survey on Proactive Dialogue Systems (IJCAI 2023, paper 738)

实际获取：✅（IJCAI 官方页面，全文机制提取）。

**论文结论（用到的）**：主动系统与反应式的分界在于系统持有自己的目标并
"create or control the conversation by taking the initiative"；主动内容
由话题规划（topic planning / 事件知识图谱 / 图推理过渡路径）选择，**不
依赖新事件**；打扰控制/接受度的关键约束是过渡平滑（transition
smoothness over dialogue history），而非一刀切的静默。

→ 影响的设计判断：**主动内容可以由内部话题规划产生**（她的假设研究、
概念联想是合法的主动素材）——支撑资格门放宽；**打扰控制应靠平滑与频率
手段**（cooldown/上限），而非把表达门槛抬高到没人能过——支撑调制上限
+0.05 的封顶。

## 2. Involuntary autobiographical memories and their relation to other
   forms of spontaneous thoughts (2021, PMC7741080)

实际获取：✅（PMC 全文）。

**论文结论（用到的）**：
- 自发记忆/念头由**情境线索触发**，外部线索多于内部线索；**不需要新
  事件**——重复出现但与某单一过去事件独特关联的特征最有效。
- Mace (2004)：**抽象/语义概念线索足以独立触发**自发记忆，削弱"必须有
  具体情境相似性"的普鲁斯特式观点。
- **线索超载原理**（cue-overload）：线索能触发的概率随该线索统摄的候选
  数下降——触发靠**独特性**，泛化线索无效。
- 未解决主题/情绪唤醒可经持续启动（priming）促进自发激活。

→ 影响的设计判断：资格门新增"`semantic 且 activation≥1.0` 也算有内容"
直接对应"概念线索是合法触发"；≥1.0 的数值边界是 FAS 工程选择（对应
"烧着 vs 路过"：路过概念激活通常 <0.5），论文只给出"独特性过滤"的定性
原则；`_defer_to_interest` 的"未解决线索持续启动"对应论文 priming 机制。

## 3. Allocating Mental Effort in Cognitive Tasks (2024, ACT-R 动机模型)

实际获取：⚠ PubMed 页面拒访（cookie 墙），正文未读；以下为 **ACT-R 标准
效用机制**（Anderson et al. 的公认公式），不是该文独有结论。

**机制（用到的）**：生产式选择按期望效用 U = P·G − C 竞争（成功概率×
奖励−努力成本）；**丢弃一个念头的期望收益为零**，因此任何 P·G 为正的
低成本内部动作（记录/重温/转化）都优于直接丢弃；效用噪声支持边缘念头
偶发尝试，被奖励后效用上行。

→ 影响的设计判断：`_defer_to_interest` 把"暂缓=干等衰减出局"改为"暂缓
= 记一次兴趣信号（低成本内部动作）"。"记兴趣的 P·G 优于丢弃"是 ACT-R
框架下的工程推断，非该实验论文的直接结论。

## 4. Effective Social Chatbot Strategies for Increasing User Initiative
   (SIGDIAL 2021, aclanthology 2021.sigdial-1.11)

实际获取：✅（ACL Anthology 摘要级）。

**论文结论（用到的）**：三种策略显著提升用户主动性——①适度高频的
back-channeling（效果最佳）；②personal disclosure（机器人自我暴露/
分享）；③**用陈述句替代提问**（减少把用户推入被动应答位）。

→ 影响的设计判断：解封后的主动话语应当**分享式、陈述式**，不是连环
提问。重启后首条主动话（"想到你之前提过的杀戮尖塔和咱们深夜聊天的
习惯…有点联系"）落在该模式上；但这只是单样本，"分享>提问"的长期倾向
未被 FAS 机制显式保证（生成层无策略约束），属待观察项。

## 未读

- **Personalizing Robot Behavior for Interruption in Social HRI
  (ARSO 2014, 7020978)**：IEEE 付费墙，未获取。打扰时机个性化的问题
  本次由 IJCAI 综述的 transition-smoothness 结论 + 现有 cooldown/上限
  机制覆盖，未据它做任何设计判断。

## 验证锚点（供回溯）

- 测试：`FAS-Cognitive/tests/test_expression_decision.py` T10a/T10b/T12a/T12b。
- 实弹：2026-10-24 重启后 7 分钟，express 1 / defer 31 / duplicate-suppress 1，
  首条主动话为概念联想分享（日志 `runtime.log` 14:4x 段）。
