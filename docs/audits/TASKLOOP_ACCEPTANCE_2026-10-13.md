# Haru 自主目标闭环 · 验收与最小补齐报告（2026-10-13 下午）

> 上接 TASKLOOP_INTEGRATION_2026-10-13.md。本轮=验收十问 + 只补有证据的缺口。
> 纪律执行：未重启生产进程、未开 autopilot、未连真实游戏服务器、未覆盖工作区修改、TaskLoop 核心算法零改动、无新平行系统。

## A. 已有能力（本轮重新核验，无需修改的明说）

| 十问 | 结论 | 证据方式 |
|---|---|---|
| 1 生活→候选去重 | **已满足** | 代码链 `_tl_propose_from_living`（mark 文件按活动 id 去重）+ propose_dupe 测试（T7c/C5）+ 生产日志单次 proposed 无重复 |
| 2 解析/约束/校验/白名单 | **已满足** | 同一条 `_start_new_task`/`propose_goal` 管线（T2/T7a）；真实 LLM 解析质量今晨 V1-V5 已过（5 调用，约束保留硬检通过） |
| 3 未批准零副作用 | **已满足（本轮补强一处）** | T7b：无台账/无索引/无环境构造；**本轮新发现**：`mark_active` 前沿不变量被违反导致写回节点实际"进不了注意力"（见 B-3，属写回质量而非审批问题） |
| 4 批准后登记/执行/持久/恢复 | **已满足** | T7e/f；恢复能力本轮拿到**跨进程硬证据**（C3：新 python 子进程读同一台账/磁盘 → 零重复动作直接确认完成） |
| 5 idle 受 busy/取消/权限/开关约束 | **已满足** | T5c/T6a-c（默认关、busy 让位、取消后 idle 不动） |
| 6 终态写回认知图谱 | **本轮修复** | 见 B-1/B-3 |
| 7 写回结果影响后续行为 | **本轮证明** | 因果链 C1→C3（台账=持久记忆 → 第二次执行零重放）+ C2（节点进 get_topk 注意力前沿=回合可消费）+ C4b（失败历史阻止盲重试）。"影响"的证据是**确定性行为差异**，不是 LLM 口述 |
| 8 生产无重复提案/重放/并发覆盖 | **部分满足→本轮补齐** | 生产日志核验无重复提案/无重放/台账单调（好）；但**并发锁缺失是真实风险**（回合 handle 与 poller idle_step 可对同一任务同时读改写）→ B-1 修复 |
| 9 重启一致性 | **已满足** | mark/index/ledger/workspace/queue 全磁盘；C3 跨进程实证；生产实例当天多次重启后待批准任务仍完整（现存 `task-files-bdff8f3cc8 pending_approval`） |
| 10 聊天/语音/生活/任务互不阻塞 | **本轮修复** | 发现 goal_parse（30-70s，V1-V5 实测）会卡在语音回合里（违反 P0.8）→ B-2 修复 |

## B. 发现的问题（全部有证据；分类标注）

1. **[代码缺陷] 终态写回只挂 poller 一路**：用户说"继续任务"打到终态时不写回不分享（行为不一致）。→ 修：host 三处返回加 `terminal/status/report`，app 统一 `_tl_on_terminal()` 供回合/队列/idle 三路径共用。
2. **[代码缺陷·违反 P0.8] 语音回合同步背 goal_parse**：语音说"把 X 移到 Y"→ 整轮卡 30-70s 无声（打断/识别全部积压）。→ 修：`queue_async` 通道——语音回合任务样消息立即回"记下了"，`drain_queue` 在 poller 一拍一条起步（ask/reject 也会回话，不让用户的话没下文）。文本回合保持同步（起步即回进度是合理交互）。
3. **[代码缺陷] `mark_active` 前沿不变量被违反（我自己上一轮写的两处注入都中招）**：`mark_active` 的语义是"调用方**先直写 activation**，它只负责同步进前沿"；`_tl_on_terminal`/`_inject_steam_event` 都建了 activation=0 的节点直接 mark → 节点被前沿排除，**写了等于没写**（e2e C2 首跑暴露：topk=[]）。→ 修：写回时直写 activation（终态 0.8/Steam 0.6，低于实时感知 5.0）+ 生产同构代码路径。**任务书 §4 警告的"仅仅图谱多了一个节点不算数"被本次验收当场抓出**。
4. **[代码缺陷·防御性] index/台账读改写无并发保护**：回合线程与 poller 可同时步进同一任务（读-改-写互相覆盖 env_state/decisions）。锁前无法用测试稳定复现（窗口小）但真实存在；4 线程并发"继续任务"的 steps_log 连续性测试（T13c）作为回归探针。→ 修：host `_IO_LOCK` 串行化全部任务入口（毫秒级操作，代价可忽略）。
5. **[设计限制·不修，如实报告] 白名单外候选永久跳过**：`propose_skipped`（如 files 域未启用时）已标 mark，此后不重试。理由：白名单变更属用户显式动作，重提可从回合下达。若不同意改法很小（skip 分支不写 mark 即可）。
6. **[环境阻塞] 真实 Minecraft 未接入**（见 E 下方 §5 清单）。
7. **[环境阻塞] `mc_env` 离线端到端也没走通**：T10b 如实 SKIP——最小 mock 世界缺完整 world_prior 配方闭包，造不出 planks → blocked。**不以此判任务系统不行**（blocked 判定本身正确=系统按设计拒绝不可达目标）。

## C. 实际改动（逐文件）

| 文件 | 改动 | 必要性 |
|---|---|---|
| FAS-Cognitive/taskloop_host.py | `_IO_LOCK`；`_start_new_task` 抽取；`queue_async`+`_enqueue_goal`+`drain_queue`（一拍一条）；三处返回补 `terminal/status/report` | B1/B2/B4 |
| FAS-Companion/app.py | 回合 taskloop 块：语音判定 `queue_async`、终态走 `_tl_on_terminal`；`_tl_idle_tick`：drain+ask/reject 回话+统一终态处理；`_tl_on_terminal`/`_inject_steam_event` 补 activation 直写 | B1/B2/B3 |
| FAS-Companion/tests/test_taskloop_loop.py | +T11 队列全语义（排队零副作用/消费/幂等）、T12 一拍一条、T13 并发连续 4 线程、T14 回合终态贯通（含"首步只核验、终态在下一拍"的核设计如实断言） | 新契约验证 |
| FAS-Companion/scripts/e2e_goal_loop.py | 新增：A-F 要求的端到端因果案例（7 断言） | §4 |

未动：taskloop.py/TaskLoop 核心、planner、图谱、语音/生活/其他既有套件。

## D. 测试证据（分层级）

| 层级 | 内容 | 结果 |
|---|---|---|
| 离线确定性（mock nlp） | test_taskloop_loop.py | **48/48** |
| 真实磁盘 | C1/C3/C4（文件移动、重启后观测、缺文件判阻） | 全过 |
| 真实 LLM | 解析质量=今晨 enablement V1-V5（5 调用）；本轮**零新增 LLM 开销** | 已覆盖，不重烧 |
| 真实生产宿主 | 17:15-17:20 实例：生活→proposed 真实链、闲聊 0 解析、进度零 LLM、无重复/重放/重放迹象 | 过（但生产实例**尚未含本轮 B1-B4 修复**——按任务书未授权重启，待下次重启生效） |
| 模拟游戏 | T10a 路由/权限闸（过）；T10b 离线配方闭包不通（如实 SKIP，见 B-7） | 部分 |
| 真实 Minecraft | **未验证**（零连接） | — |

回归总账：认知仓 **161 passed** + test_taskloop/test_goal_planner ALL PASS；companion：config_store 30/30、生活闸门 23/23、LLM 恢复 12/12、情境 21/21、e2e 认知消费 12/12（早前）。

## E. 端到端案例（§4 要求的完整因果，全部确定性断言）

**输入**："把 goal_a.md 移到 archive"（workspace 真实存在该文件；FileEnv=真实磁盘）。
**状态变化**：handle 起步（mv 核验通过，CONTINUE）→"继续任务"→ 观测确认 **COMPLETED**（terminal=True, report.met=1/1, steps=1）。
**实际行动**：磁盘断言——文件真在 archive、inbox 里没有（不信任何自述）。
**观测证据**：台账 steps_log[0].verified=True + unexpected_changes=0。
**图谱写回**：`Task_completed_*` 节点（extra_attrs 数字全部来自台账）+ activation 0.8 → **`engine.get_topk(20)` 实测包含该节点**（=回合认知上下文可消费的入口）。
**后续行为变化**（三段因果）：
  - C3：同一指令在**全新 python 子进程**再下达 → steps 仍=1、直接判 completed——**历史使系统拒绝重做**（这是"避免重复"的行为级证据，非日志措辞）；
  - C4：不存在的 ghost.txt → 观测判 **blocked**（零谎报）+ 决策含不可达原因；再"继续任务" → **零新动作**（失败历史阻止盲目重试）；
  - C5：生活循环对已存在目标（含 blocked）再提候选 → propose_dupe，不重复立项。
**§5 MC 只读核查结论**：桥接口面（bot.js ~20 端点，bridge.call 失败如实 ok:False、get_state 失败 None、TIMEOUT=3s）足以支撑观测型适配器；差异与阻塞项——① 桥**无 /craft 端点**（合成类目标在真世界不可执行，需先在 bot.js 加 craft+权限）；② McTaskEnv 的 universe/ops 由配方闭包生成，真桥需把 `find_blocks/inventory` 映射为快照谓词（have:X#k/loc）——映射面已在离线代码中，缺的是换 execute 到 bridge.call 白名单；③ 最小动作白名单设计：`dig / goto / pickup / drop / place(需授权) / craft(桥端点尚缺)`——**禁止通用 bridge.call 直进任务系统**（它能达 attack/chest_*/equip 全端点）；④ 失败语义可直接复用（ok/reason 形状一致）；⑤ 验收方案：本地临时世界 → 一个"挖 3 个橡木原木"目标走全链（解析→计划→dig→/inventory 观测核验→写回）后，才允许谈 adapters 白名单放行 minecraft。**当前判断：接口准备差一个 /craft + 一个薄适配器类（~80 行），无架构性阻塞。**

## F. 下一步（只一件）

**重启一次生产实例**（新代码含 B1-B4：语音不阻塞、终态全路径写回、并发锁、activation 修正），然后你在语音里说一句"把某某文件归档"验证：立即回"记下了"、下一拍 Charon 弹出起步进展、`任务进度` 可查——这是今天全部补齐在真实宿主上的最后一块验收。
（MC 的 /craft 端点与薄适配器留作重启验收之后的独立小步。）

---
*本报告随附代码均在两仓工作区未提交状态（与上一轮一致，未覆盖任何既有修改）。*
