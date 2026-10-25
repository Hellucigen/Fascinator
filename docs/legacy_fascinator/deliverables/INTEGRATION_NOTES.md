# INTEGRATION_NOTES.md — 论文整合说明(2026-10-05,第三轮更新)

## 标题选择(第三轮定稿;取代第二轮)

**选定:**
EN: "From Embodied Experience to Persistent Experience-Derived State:
An Auditable Unified-Graph Architecture and a Preregistered Boundary
Analysis of Activation-Based Access"
ZH: "从具身经历到持久的经验派生状态:可审计的统一图谱架构与基于
激活访问的预注册边界分析"

候选与理由:
1. (第二轮旧稿)"Persistent Experience-Derived State in an Auditable
   Cognitive Architecture: Formation, Persistence, and Measured
   Behavioral Effects" — 含核心词但不含"边界分析"这一方法学主张,
   且未回指协议贡献;落选。
2. (选定)"From Embodied Experience to Persistent Experience-Derived
   State: … Preregistered Boundary Analysis of Activation-Based
   Access" — 同时满足任务书两条:强调持久经验派生图状态(已被
   PSA 空对照实验确立因果作用)+ 边界分析(预注册拒绝与 84 格
   扫描);从 X 到 Y 的句式保留叙事;不再出现"可复用的关系知识"。
3. "When Experience Persists: …"(疑问式)— 更短,但疑问式标题在
   目标期刊风格不确定时风险高;落选。

约束核查:标题与摘要均不暗示图结构/关系机制的必要性——
"Persistent Experience-Derived State" 描述被证明的对象(持久性),
"Boundary Analysis of Activation-Based Access" 明示激活价值是
被界定而非被主张的对象;摘要中"激活的必要性未得支持""图结构与
激活的独立贡献则未定"与之呼应。

## 中心表述

持久经验派生状态 = 已证因果核心(reset 空对照 10/0、失败重复
2.8 vs 7.7);激活/图结构独立贡献 = 未定(呈现不等价混杂,修订
对照待完成);压缩与目标维持 = 条件性收益;非替代外部记忆检索。

## [PENDING-REVISION-CONTROLS] 占位——**已解决(2026-10-05 定稿轮)**

> **修订对照分支已定为:"无法判定-弱化版"。**修订对照实验
> (persistent_state_controls_revision)在呈现等价预检处按预注册
> 停止(0 LLM run):C4b/C4c 在朴素 2 跳规则下失败证据仍被 8 槽
> 预算截断,呈现等价的图对照未能实现;C3b 通过门槛但按协议不得
> 单独放行;H_R1–H_R4 全部未回答。10 处占位已全部替换为
> "已尝试、门槛停止、仍未检验"表述,编译后残留 0。
> 未来若重开该问题,必须走新的独立预注册。

原三分支(存档,供历史参考):
- **"确认失败可见性解释"**(等价呈现后 C1 优势消失):
  上述 10 处改为"the T3 advantage is fully attributable to
  failure-evidence visibility";限制(20)删"pending"从句;
  §5.6 限定 (i) 与 S16 解读同步定稿;摘要"独立贡献未定"可
  升级为"未获支持";6.1 未证明清单不变。
- **"图结构仍有差异"**(等价呈现后 C1 仍优):
  10 处改为"presentation-equivalent controls confirm an
  independent contribution of graph structure/activation";
  限制(20)改写为正向结论并保留 n=10 功效声明;6.1 已证明列表
  加 (vii);摘要可加入该正向归因(仅限 T3 失败信息行为域);
  注意此分支不改变 H1(空对照)的表述。
- **"无法判定"**(功效不足/结果混合):
  10 处改为"results remain inconclusive under
  presentation-equivalent conditions";限制(20)加"修订对照
  亦未判定";其余不动。
不猜测:在结果文件出现前,任何一处都不得先行改写方向。

## 数字变更日志(累计,第三轮)

| 位置 | 旧值 | 新值 | 原因 |
|---|---|---|---|
| 摘要(二轮→三轮)| ten extra→five extra | 10.5 vs 1.0 对照 | 二轮 five extra 混用了 PSA-T3 差值;摘要讲 E 批应用 E 批数 |
| 摘要/§5.5/S15 ×4 | 360 run | 508 run(另 390 修复批单独归档)| 360 无法追溯;逐文件行数实测 |
| 限制(19) | FAS-sham 9/9 | 10/10 | raw_results 去重重算 |
| S16 表 C3 T3 | 11.1 | 12.0 | raw_controls 重算 |
| §4.5/S13 ×4 | 104 回归 | pytest 82 + 运行器 108/108 | 实跑 |
| PSA 叙述 | 3.1/7.5 | 2.8/7.7 | 快照残留(论文一律用重算值)|

## 术语变更(累计)

| 旧 | 新 | 原因 |
|---|---|---|
| consolidation(机制主张处)| 持续强化 / 结构晋升(§3.3 三分约定)| 只有连续强化+晋升有行为证据;回放整合未验证 |
| persistent intention(机制解释)| relational working-set salience | C 的机制归因修正 |
| "等效"(限制 20)| "未检出差异,功效有限" | 10/10 vs 10/10 不是等效性检验 |
| "仅在 T3 被证明"(限制 20)| "归因失败证据可见性;独立贡献未证明" | T3 事后审计 |
| continual learning | persistent learning across episodes | 避免暗示通用能力 |

## 新增正式内容(累计)

1. §5.6"上下文移除条件下的持久状态检验"(EN+ZH,本轮)——
   H1/H3/H5 + 四条不可证明清单。
2. §5.8(原 5.7)"审计驱动的更正与负结果"(C/E/F/T3 四更正)。
3. 限制(18)(19)(20)重写(最小 p 注、sham 10/10、可见性归因)。
4. §3.3 术语约定句;§5.5 J 段与 PSA Hebbian 观测调和句。
5. 补充 S15(战役 v2)、S16(PSA+对照表,解读段重写)、
   S14 主张表新增 2 行(持久性因果、保结构对照)。
6. [PENDING-REVISION-CONTROLS] 占位 10 处(见上)。

## PeerJ 章节方案(2026-10-05 投稿准备轮)

目标刊 PeerJ Computer Science;标准章节 = Abstract/Introduction/
Materials and Methods/Results/Discussion/Conclusions。迁移稿
peerj_main.tex 的最小改动:

| 原节 | 迁移稿 | 改动 |
|---|---|---|
| 1 Introduction | Introduction | 不变 |
| 2 Related Work | **Related Work(保留独立节——偏离标准结构)** | 理由:本文方法学核心是"与平坦检索/既有记忆路线的预注册对照",相关路线的分类与定位是呈现预注册问题的前提;并入引言会弱化该对照结构的呈现。PeerJ 允许偏离但要求清晰度理由,此即记录 |
| 3 Architecture + 4 Evaluation Protocol | Materials and Methods(4 降为其小节 "Evaluation protocol",其下小节降为 subsubsection) | 归并,零内容改动 |
| 5 Results | Results | 不变 |
| 6 Discussion | Discussion | 不变 |
| 7 Limitations | Discussion 内子节 Limitations | 层级变化 |
| 8 Conclusion | Conclusions | 仅改名 |

新增声明区:Funding / Competing interests / Author contributions /
Data and code availability / Reporting guidelines(占位见 TODO_FOR_AUTHOR)。
supplement 对主文章节的引用经编译验证全部有效(0 未解析引用);
正文所有 "Supplementary Material Sxx" 引用与补充材料节号一致。
