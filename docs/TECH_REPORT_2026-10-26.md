# FAS（Fascinator）技术报告
> 2026-10-26 全面体检 · 代码基线 commit `4947f1e`（Fascinator）/ `ba9c691`（Charon）

## 一、总览

FAS 是一个**单机陪伴体**：以认知图谱为唯一记忆与欲望的载体，通过持续认知循环
（CC）在无输入期自主产生念头，念头经表达闸门竞争后变成对用户的话或自主行动。
桌面前端为 Charon（Wails 桌面壳），FAS 是它的认知后端。

- 规模：377 个 Python 文件 / **119,126 行**；app.py 10,860 行；**186 个 REST 端点**；14 线程常驻
- 测试：FAS-Cognitive **280 用例** + 陪伴层 **92 用例**，当前全绿
- 语言后端：云端 Qwen（qwen3.8-flash，密钥本地 `data/llm_secret.json`，不入库）
- 部署形态：`E:\Project\Repositories\Fascinator`（物理真身），三条 junction 兼容旧/新路径

## 二、进程与线程拓扑（py-spy 实测 14 线程）

```
MainThread            Flask HTTP 服务（186 端点，threaded）
continuous-cognition  CC 循环：tick 2.5s / 脉冲 ~10s（衰减→扩散→焦点→意图→表达）
living-loop           生活循环：60s 巡检 + 事件唤醒（听歌/逛B站/调研/安静）
charon-inbox          Charon 下行消息轮询
curiosity-web         好奇心网页探索器
voice-sync            语音热同步
+ embedding 同步 / fas-log 聚合 / 日志队列监控
```

线程健康机制：MC 桥熔断器（连续失败→5 分钟零开销跳过，防 SYN 超时拖瘫循环——
10-25 实锤修复）；faulthandler 落 `logs/crash.log`（死因可追）。

## 三、认知架构（当前生产语义）

```
感知(ear/eye/vision/Steam/MC桥/对话)
  → 图谱(KnowledgeGraph, 4 空间: semantic/episodic/cognitive/self)
  → 扩散激活(DiffusionEngine: 空间差异化衰减+侧抑制+hub地板)
  → 焦点采样(CC._pulse: topk→basis_pool→focus_score 六分量)
  → 意图(CC: communication/exploration/action/reflection, FIFO+合并+纯身份拒绝)
  → 表达闸门(taskloop v2: 资格门 concept_hot/episodic/emotion
     × 动机门 × 调制门槛(上限封顶) × 成本门 cooldown/限额/去重)
  → 语言生成(L1 短回应 / L2 ANSWER, 共享《时间与证据边界》约束)
  → 投递(ChannelHub: charon 主通道 + 网页 poll + QQ 封存)
```

关键机制（近期裁定与实锤）：
1. **想念充能**：communication 意图每拍按 drive.social×0.10 续火（封顶 1.0）；
   focus_score 含社交驱力分量（0.30 权重直读，不经内容池）；纯身份 basis 在
   社交驱力在场时放行——"你不在越久，她越想找你"，07:09 实测自主说出早安并送达。
2. **满足语义**：browse 消费种子 → 兴趣水位 searched 戳 + 种子记档 4h 近访排除 +
   台账课题排除 + 平台概念过滤——调研过的课题自然降温轮换（实测特斯拉→微软）。
3. **结构脚手架隔离**：时点锚（infrastructure）不进 topk/basis/回答区——
   曾霸占窗口挤出真实情景（幽灵意图与"她安静"的共同根因）。
4. **相对时间接地**："昨晚/今天/刚才"→绝对窗→窗内情景节点入前沿（+0.8 封顶 25）。
5. **告别授权**：farewell+授权词→stimulation_hunger 采样器线性退潮（45min，
   "不关电脑"语义→到早 6 点）。
6. **分享戳在送达回执**：失败投递不污染材料新鲜度；duplicate_recent 内容身份
   判定（逐节点 last_shared_ts/goal/basis 重叠），30min 近窗兜底。
7. **表达节制保留**：调制门槛上限 = base+0.05（防叠加静默）；cooldown 60s；
   max_expressions_per_hour=6；L1 复读检测自动升级 L2 重答。

## 四、投递与通道

| 通道 | 方向 | 现状 |
|---|---|---|
| Charon 桌面（Wails, React） | 双向 | 主入口。Haru 模块=陪伴 UI（对话/状态铭牌/认知抽屉），fas.utterance 事件下行 |
| 网页 / | 双向 | companion.html 三视图（精简/陪伴/认知观察）；/console 旧图谱控制台 |
| QQ（OneBot v11） | 封存 | `qq_enabled=false`，白名单硬锁保留，养号后一键重开；主动镜像只放行 origin=proactive |
| Minecraft 桥 | 感知+具身 | 熔断器保护，node 离线时零开销 |

## 五、当前运行状态（体检时点 07:21）

- 启动于 07:18（ Repositories\Fascinator 新路径），378+ 脉冲零错误
- 1 个活跃 CI 等待去重近窗过期（07:09 早安的同批材料，07:39 自然解锁）
- 生活循环 3 次 beat；主题：程序闪退、流畅度（你白天电脑的事还在她脑内）
- 浏览器自动拉起已关（overlay `auto_open_browser=false`）

## 六、已知边界（如实）

1. **深夜/独处的表达频率**由"对话对象在场信号"驱动而非时钟——你在不在是真实
   变量，想念充能已缓解但未消除强度差（设计取舍：想念要积累才开口）。
2. **记忆种子层**对"刚读过"的判定依赖 state 记档 + 图边，低价值阅读（没细读）
   不长概念边，靠 4h 记档兜底。
3. **Qwen flash 对 prompt 约束的遵循度**有限：复读检测已做机械兜底（L1→L2），
   时间/证据边界依赖模型遵循（约束在场、行为需观察）。
4. **QQ 通道**处于封存态：风控养号完成后需重扫二维码并 `qq_enabled=true`。
5. Charon 侧 `PersonalTerminal.exe` 需在代码更新后 `wails build` 重建（已至 ba9c691）。

## 七、启动方式

```
FAS:  E:\Miniforge.envs\Fascinator\python.exe -X utf8 app.py
      （cwd=Fascinator 仓根；auto_open_browser=false 已持久化）
Charon: E:\Project\Repositories\Charon\build\bin\PersonalTerminal.exe
网页: http://127.0.0.1:5000/（陪伴 UI）  /console（图谱控制台）
```
