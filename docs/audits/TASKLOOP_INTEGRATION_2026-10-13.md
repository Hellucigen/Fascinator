# Haru 自主目标与行动闭环 · 宿主接入记录（2026-10-13）

> 任务：把 FAS-Cognitive 已实现的 TaskLoop 闭环接入 Companion 真实宿主。
> 原则执行：零复制、零重写——认知算法一行没改，只补了宿主缺的"接口与权限"。

## 一、原本就有的（沿调用链核实过消费者，不是看文件在就算数）

| 能力 | 所在 | 真实状态 |
|---|---|---|
| TaskLoop 状态机（差距→规划→执行一步→**重观测核验**→拉黑→重规划→台账→完成/受阻/部分判定） | taskloop.py | ✅ 生产级（161 项测试覆盖，含"谎报回执被拆穿"的对抗测试） |
| 自然语言目标解析+严格校验（reject/ask/ok 三态，丢约束硬检） | taskloop.parse_goal/validate_goal_spec/constraints_preserved | ✅ 真实 LLM 质量今早已按 V1-V5 计划实测（enablement_verify_20261013_*，5 次调用：正常→受理、禁项→约束保留、不足→ask 零行动、故障注入→拉黑不虚报） |
| 回合内接线 `taskloop_host.handle`（进度查询/继续任务/新任务三入口） | app.py:4613（turn 2a-pre.4c 块） | ✅ 在跑，但有下述三个真问题 |
| 执行环境适配器：files（真实磁盘 mv）/ sandbox（确定性房间世界）/ reading（走 reader 台账） | experiments/general_loop/*_env.py | ✅ 离线验证级 |
| mc_env（第四适配器） | experiments/general_loop/mc_env.py | ⚠️ 文件在，**从未接进 host**；且自述"物理复用 SimEnv，与真实 Minecraft 无关" |
| Charon 交互入口 | index.html/BODY 页 | ❌ 无任务相关面（本轮不重做 UI，SPEAK 文本已可全程驱动，见"五"） |

## 二、本轮发现并修复的真问题（都有证据）

1. **每条聊天都在白付 goal_parse 的钱**（生产日志实锤：14:53/14:57/15:21…连"出声测试"句子都被送去解析并 reject；12:40 一条消息被解析成任务后以"任务受阻"**截胡了正常回复**）。→ 修复：`_TASKLIKE_RE` 预闸——非"任务样"消息不进解析直接回旧路径（闲聊零成本，验收 8；生产冒烟复验：闲聊轮次 0 次 goal_parse 调用）。
2. **`继续任务` 状态回滚 bug**：continue 分支从不回写 env_state → 每次"继续"都从最初状态重放，多步任务永远走不完。→ 修复：步进后回写（测试 T6d 防回归）。
3. **没有取消**：任务一旦建立无用户终止手段。→ 修复：`取消任务` 指令（index+台账双标记）；取消后"继续任务"/idle 步进/批准通道全部拒动（T5a-d 验证，验收 7）。
4. **没有背景推进**：任务只在用户说话时被动走一步。→ 修复：`idle_step`（挂进既有 context-poller，60s 一拍，每拍至多一步）；**`autopilot_enabled` 默认 False**——不擅自开新执行权限；busy（用户在对话）让位（T6 验证）。
5. **终态没有学习**：任务完成/受阻只留在 JSON 台账，认知层不知道。→ 修复：poller 捕获终态 → **图谱写 `Task_*` 情景节点**（类型 task_outcome，字段全部来自台账观测：goals_met/steps/replans/verify_misses/unmet，零 LLM 编造）+ mark_active + `_save`；并发一条主动分享走既有 Charon+网页双通道（只在终态发，天然限频）。
6. **mc 域有环境无路由**：→ 修复：`minecraft任务：…` 显式域前缀（谓词必须全落 mc 词表，拒绝借道）+ `_build_env/_rebuild_env` mc 分支（env_state 携构造参数）。**默认 adapters 白名单不含 minecraft**——T10a 验证：未启用时明确拒绝执行不擅开。
7. **没有自主目标的合法入口**：→ 新增 `propose_goal`（P1）：候选与用户指令走**同一条**解析/校验/路由/白名单管线，但只进 `pending_approval`——批准前零副作用（不建环境不写台账，T7b 验证）；`批准任务` 后才登记并可执行（T7e-f）。重复候选去重（T7c）。

## 三、修复后 TaskLoop 从 Companion 的真实调用路径

```
用户消息 ──→ process_nlp 回合 ──→ taskloop_host.handle(text, ctx)
                 │  闲聊 → 预闸挡下（0 成本，旧路径原样）
                 │  "任务进度/继续/取消/批准/任务样指令"
                 ├─ parse_goal(nlp.ask "goal_parse")  ←── 认知层现有语言后端（千问）
                 ├─ validate + constraints_preserved ←── 认知层现有实现
                 ├─ _route → adapters 白名单 → _build_env(files 真实磁盘/sandbox)
                 └─ TL.TaskLoop.step()：plan→execute→重观测→拉黑/重规划→台账
空闲推进 ──→ _context_poller(60s) → _tl_idle_tick()
                 ├─ 提案文件队列 data/taskloop_proposals.json → propose_goal
                 ├─ 生活循环 done 调研 → 写 workspace 笔记 → propose（真实自主源）
                 ├─ idle_step（autopilot 默认关；busy 让位；每拍一步）
                 └─ 终态 → 图谱 Task_* 节点（观测字段）+ 主动分享一条
认知不可用 → handle 内部异常如实报错、不回退旧执行器；enabled=false 一律 None（T9）
```
陪伴层独立状态（chat_log/living 账本）与认知状态（图谱/taskloop 台账）边界：台账只属认知层，companion 只经 handle/idle_step/propose_goal 三入口触碰——无第二份目标数据库。

## 四、验收测试结果（§五 逐条对应）

| 验收项 | 结果 | 层级 |
|---|---|---|
| 1 自然语言→解析→校验→TaskLoop | T1a-d 过（沙盒 4 步完成，多步证据链在台账）；T4a-c 过（files 真实磁盘 mv，完成时文件真在 archive） | 模拟+真实磁盘 |
| 2 无效/缺约束被拒或澄清 | T2a-c（未知域静默、信息不足 ask 零行动、结构非法 reject 不猜）；今晨 V1-V5 真实 LLM 同场景已过 | 模拟+真实 LLM |
| 3 执行结果影响下一步 | T3a-c：谎报回执被观测拆穿→verify_miss 记账→算子拉黑→REPLAN，不盲重复 | 模拟 |
| 4 成功按实际观测结束 | T1c/T4c（snapshot/磁盘直读判定） | 模拟+真实磁盘 |
| 5 失败重规划/等待/终止 | T3c + enablement V4；step_cap/拉黑上限在核 | 模拟 |
| 6 持久化+恢复 | T1/T5（每个 handle/continue 都是全新进程内重建，纯文件台账） | 模拟 |
| 7 取消后不再发起动作 | T5a-d（含 idle_step 通道） | 模拟 |
| 8 聊天/语音/表达/生活循环不破坏 | T8a-b（闲聊零解析）+ 生产冒烟（17:19 闲聊正常回复、0 goal_parse）+ 认知仓 161 pytest 全绿（含 phase3 修订 p13） | 代码+生产冒烟 |
| 9 认知产物改变后续行为 | **生产实链**：17:17 生活循环完成的调研（旧会话遗留 done 活动）→ 自动写笔记 `research_eb7bacfc.md` → propose → 真实千问解析 → `pending_approval` 入索引 → "任务进度"如实播报待批准任务。认知状态（账本+图谱）确实产出了新的待办行动与表达 | **真实环境** |
| 10 认知层不可用陪伴照常 | T9a-b（异常如实报错、开关关零介入）；chat/voice 不依赖 taskloop（poller 段独立 try） | 代码+模拟 |

新增测试文件：`FAS-Companion/tests/test_taskloop_loop.py`（36 项断言，全离线临时目录，`python tests/test_taskloop_loop.py`）。

## 五、当前仍不能做到的（如实清单）

1. **真实 Minecraft 未验证**：mc_env 物理是 SimEnv 替身（其文件头自述），且离线端到端 T10b 也没走通（配方闭包需完整 world_prior 图谱注入，最小 mock 世界造不出木板→如实 blocked）。真接 MC 还缺：① 活着的 bot/服务器；② McTaskEnv 改接 `minecraft/bridge.py` 的 get_state/call（观测与执行都要换成真桥）；③ 执行白名单安全评审（现在 bridge 一个口全权）。**本轮不碰真服，权限默认关**。
2. 自动执行（autopilot）默认关——开不开是用户决定；开了也只推 pending 之外的 active 任务且让位对话。
3. 多任务并发仍按"最早一个"推进/查询（认知仓报告已自declare，本轮沿用未扩）。
4. 提醒/定时类目标未接（无现成调度设施，任务书明确不为它重建）。
5. Charon BODY 页尚无任务卡（SPEAK 里说"任务进度/继续任务/取消任务/批准任务"即完整可用——文本通道今天全通；UI 化留给你点头后下一步，改动量很小）。

## 六、改动文件清单

**FAS-Cognitive**：`taskloop_host.py`（预闸/取消/批准/显式 mc 域/idle_step/propose_goal/env_state 回写修复，约 +200 行，TaskLoop 核零改动）· `config.py`（taskloop 段 +autopilot_enabled）· `tests/test_taskloop_phase3.py`（p13 用例适配预闸，语义等价）
**FAS-Companion**：`app.py`（turn ctx 加 busy、poller 接 `_tl_idle_tick`、新增任务宿主编排段：提案队列/生活→候选/终态入图+分享，约 +180 行）· `tests/test_taskloop_loop.py`（新增）
**数据面**：`data/taskloop_proposals.json`（提案队列文件，任何模块可投递候选）· `data/task_workspace/inbox/research_*.md`（Haru 的调研笔记，真实产物）· 任务台账沿用既有 `data/taskloop_ledger.json`/`taskloop_tasks.json`

回归总账：认知仓 **161 passed** + taskloop 脚本 ALL PASS；companion：任务闭环 **36/36**、生活闸门 23/23、情境 21/21、语音 36/36（早前）——全绿。生产实例已带新代码运行（PID 34076），真实链已验证（第四节验收 9）。
