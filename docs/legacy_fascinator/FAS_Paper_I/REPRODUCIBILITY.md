# REPRODUCIBILITY

## 环境
- Python 3.12.13（E:/Miniforge.envs/Fascinator，`-X utf8`）；全部实验单进程确定性执行
- LLM 全程禁用：`MiMoBackend._create` 守卫在沙箱装配 import 时安装，任何调用即 raise（零 LLM 契约）
- 回归套件：`scripts/run_tests.py`（104/104 通过，写作时）

## 协议
- 每条件 5 seeds（1–5）；同 seed 逐位确定（重跑轨迹一致已验证）
- 沙箱仿真时钟 16 s/tick；技能结算、归因窗（8–120 s 环境时间）、晋升线（support≥5、Laplace conf≥0.80）均确定
- 已知例外（已记录于论文 §4.2/§9.6）：长链任务沙箱熔炼即时结算（吸收真实系统壁钟重试窗的 furnace_take 环节）

## 数据
- 全部原始 run 归档于 `FAS_Research_Experiments/<family>/run_*/`（metadata.json / events.jsonl / snapshots / metrics.json / manifest.jsonl）
- 每族机器生成 `summary.json` 与 `failure_analysis.md`（生成器 `scripts/gen_campaign_summaries.py`）
- 论文事实库：`paper_audit/PAPER_FACT_DATABASE.json`（生成器 `paper_audit/gen_fact_database.py`，只读原始归档）
- 论文图表：`paper_audit/gen_figures.py` 从事实库生成，正文无手工数字

## 复现入口
```
python paper_audit/gen_fact_database.py   # 重建事实库
python paper_audit/gen_figures.py         # 重建全部图
python scripts/run_exp_a2_reuse.py --condition B2 --seed 1   # 单实验复现
```

## 不入论文的本地细节
- LLM endpoint/密钥（gitignored data/llm_secret.json）
- Minecraft LAN 桥地址（127.0.0.1:5010）
- Windows 本地路径
