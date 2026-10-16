# 生产启用记录（2026-10-12，逐项按证据）

启用原则（任务原文）：只有经过验证的路径才被开启；每项标注证据等级、
回退方式与已知残余风险。启用后全仓回归：**161/161**，独立套件
taskloop/phase3/goal_planner/reading/memrep 全 ALL PASS。

| 开关 | 状态 | 证据等级 | 回退 | 残余风险（如实） |
|---|---|---|---|---|
| `memrep.enabled` | **ON** | 真实 LLM 行为通过（verify2：6/6 抽取、问答接地、Cato 拒答、跨语料）+ 26 项离线测试 | 改 False（纯 additive 字段变惰性） | enrich 后 ev 回链暂无消费者（已登记） |
| `reader.enabled` | **ON** | 真实 LLM 行为通过（同上 + 台账恢复/进度诚实 26 测）+ 沙盒链路端到端 | 改 False（宿主块整体跳过，FILE_READ 回到如实拒绝态需注意：read_file 执行器现已存在，属 file_action 能力非 reader 门内） | 宿主块运行时未起服验证；一次性截断故障可在重试下恢复（min_verify 的 retry=0 失败为脚本缺陷）；真实模型偶发 900 tok 截断 → 依赖重试，未测重试后的通过率 |
| `taskloop.enabled + parse_enabled + adapters=[files,sandbox]` | **ON** | 离线集成 35 断言全绿 + **真实解析 V2 通过**（中英混合指令禁铁约束保留 + 歧义转 ask） | 改 False（handle 立即 None） | **V1/V3/V4/V5 真实链路因调用预算耗尽未记录**（两次脚本缺陷浪费 8 次预算，已如实入账）；真实解析的约束表达格式漂移（"iron_ore" vs "have:iron_ore"）——匹配语义需下一轮收紧；完整 FastAPI 起服未测 |
| `planner.enabled` | **ON** | 控制环 SimEnv 23 测全绿（含崩溃恢复/五分支/拉黑式核验） | 改 False（不装钩子、tick 零触碰） | **真实 Minecraft 运行时从未验证**（无活桥）；宿主 set_goal_context 若在活动会话被触发，计划派发将真实生效——建议首个真实会话前人工盯一次 |
| `goal_path.enabled` | **保持 OFF（刻意例外）** | 唯一被证据否决的开关：族 L 行为实验零收益+哨兵层方向性负，其自身 FINAL_REPORT 判定"不达标、不应默认开启" | 不适用 | 用户"全部启用"与本仓证据冲突时按证据优先；如仍要开需明示覆盖本记录 |

## 调用预算账（本轮诚实记账）
计划 ≤10：实际 10（第 1 次 enablement_verify 崩溃耗 4 无落档；第 2 次崩在
语料路径耗 4 无落档——两次均为**我的脚本缺陷造成的预算浪费**，第 3 次
min_verify 2 次有完整落档）。V1/V3/V4/V5 若要补齐，需新增预算授权。

## 教训登记
①验证脚本必须先跑"零成本冒烟"（文件存在性、ledger 存在性）再进调用段；
②任何中途异常路径都要落盘已完成的分步结果；③结果未落盘的调用不得计入
证据（本次即因此 V1/V3/V4/V5 只能记"未验证"而非"通过"）。

## 追加（同日）：语言供应商切换到千问 qwen3.8-flash

- `FAS-Companion/llm_provider.py`：新增 `QwenBackend`（OpenAI 兼容，
  base_url https://maas.qianwenaiapi.com/compatible-mode/v1，
  env 覆盖 QWEN_API_KEY/QWEN_BASE_URL），注册进 create_backend（**默认
  provider 改为 qwen**）与 failover 注册表（MiMo/DeepSeek 保留为备援）。
- `nlp_processor.py`：主/expand/chat/fast 四类后端与 set_provider 映射
  全部补 qwen 分支（qwen3.8-flash 按思考模型给预算）。
- `app.py`：默认 provider 兜底 "qwen"。
- 密钥：新 Key 只写入 gitignore 的 `data/llm_secret.json["api_key"]`
  （该文件已确认不被 git 跟踪）；旧 MiMo Key 保留在
  `["mimo_api_key"]`。钉死 MiMo 的锁定实验/验证脚本（recomb harness、
  run_dante/verify2/min_verify/enablement_verify）已加
  `mimo_api_key or api_key` 回退——**Cross-Episode 预注册锁定的模型
  仍是 MiMo，不因本次切换漂移**。
- 冒烟（真实调用 2 次）：裸端点回 "QWEN OK"；`NLPProcessor(provider=
  qwen)` 装配成功（backend=QwenBackend，main/chat=qwen3.8-flash），
  goal_parse 真实解析："把 board_a 移到 workshop，不许碰别的东西" →
  preds=[loc:board_a:workshop]、forbid 含 other、判 ask（模型带澄清问，
  保守分支正常）。
- 宿主重启后生效（app.py 读 llm_config.json 已更新为 provider=qwen）。

## 追加（10-13）：V1-V5 千问真实验证结果 + Phase-3 启动

V1–V5 补跑完成（千问 qwen3.8-flash，5 次调用，档案
`experiments/general_loop/enablement_verify_20261013_124117/`）：

| 项 | 结果 | 判定 |
|---|---|---|
| V1 正常归档指令 | 模型转 **ask**（追问"是否删除源文件/根目录在哪"）| 保守安全，未乱执行；过度澄清倾向登记为模板待调 |
| V2 含禁项指令 | **task 执行**，台账 constraints 含 `consume:iron_ore`、`touch:storage:*` | **约束保留通过**（files 域启用主判据） |
| V3 模糊指令"把那个文件弄过去" | **reject**，preds 非法不执行、零行动 | 通过（不猜补） |
| V4 目标冲突（archive 已有同名） | mv 被环境拒 → invalid 记账 1，status=active，**未谎报完成** | 通过 |
| V5 "任务进度" | 纯台账读数（0 新 LLM 调用），数字与 V4 台账逐项一致 | 通过 |
| 阅读链冒烟 | 单元 1 confirmed（3 关系入库），进度台账真实 | 通过 |

过程失误如实记两条：①前两轮 V 运行因脚本自身 bug（计数器形态、
**脚本 CLIENT 仍指 MiMo 端点配千问 Key → 401**）浪费约 0 次真实调用
（本地异常，未达 API）但结果两次未落盘；②V3 的 no_env_built 度量因
测试共用 tmp 目录而失真（结论不受影响，kind=reject+零行动为直接证据）。

taskloop 生产启用判据升级：V2 约束保留 + V3-V5 全过 → **files/sandbox
域维持启用有真实行为证据**。V1 的过度澄清列为模板改进项（不动判据）。

Cross-Episode Phase-3 已于 10-13 12:32 人工批准后启动（后台，
`campaign_l/phase3_20261013_123212/`，逐 run 落盘，预算 210）。

## 追加（10-13 晚）：Cross-Episode Phase-3 完成 + Phase-4 报告

210/210 成功调用完成（零 infra / 零 error / 零不可判定；中断两次经
断点续跑补齐，A7 经 BGE_MODEL_PATH 指向迁移后的同一模型续跑）。
正式报告：`experiments/cross_episode_recomb_memrep_replication_v1/PHASE4_REPORT.md`。

要点（均为探索性结论）：
- 联合探索性信号（Δ≥20pp 且 C≥5/6）**四项主对比全部未达到**；
  序列化贡献方向性 +16.7pp（A2 0% → A3/A5 17%）。
- **操纵检查揭出装配缺陷**：A3 与 A5 的 LLM 输入 30/30 逐字节相同
  （rep_fix 写事件属性，但序列化器只认 `type=="episode"`，表示操纵
  为空操作）→ "表示贡献"本轮**未被检验**，非负结果；需修复契约后
  以 v2 重验。
- 锚点：A6（G2 动作在边上+新序列化）50%、A7（B2 嵌入）60%；
  A1（忠实域+ids）0/30 且事件进 Top-k 计数 0/30——检索停摆复现。
- 行为诊断：G3 臂错答呈"事件邻接捏造连通"，G2/B2 臂呈保守弃权。
- 对生产开关无影响：goal_path 维持关；taskloop/reader/memrep/planner
  启用证据不变（本实验是复验装置，不是新机制上线）。
