# DESIGN — LLM 决策头复跑确定性检验(beacon rerun determinism)

日期:2026-10-01(运行前冻结)。状态:**设计冻结 → 执行**。

## 1. 背景与假设

- 论文方法部分主张:决策头战役 temperature=0、逐字节可复现,但没有直接的重跑证据。
- 本检验:在**新输出目录**重跑信标战役的 5 配对种子 × 4 条件(fas_full / D-noact / D-flat /
  llm_direct),与归档战役(experiments/beacon_v1/raw_results_final80.jsonl)同种子同条件逐行对比。
- 假设 H:success / decisions / steps_to_craft / first_action / 动作序列完全一致。
  LLM 端点温度为 0,但端点本身不保证确定性;若出现不一致,如实报告为
  "重跑层确定性未能建立",并回退论文中"identical seeds reproduce bit-identical
  trajectories"对决策头战役的表述(主体实验不受影响,其零 LLM 且已有重跑验证)。

## 2. 条件(冻结)

- 代码路径与装配:scripts/run_exp_beacon.py,不改一行(唯一差异 = 新 out 目录)。
- 种子 {0,1,2,3,4};4 条件全跑;max_tokens=200 等与归档战役相同的装配修订。
- 对比字段:success, decisions, steps_to_craft, first_action, acts 序列。

## 3. 样本量与判据(冻结)

- 5 配对种子 × 4 条件 = 20 run。
- 判据:20/20 run 全字段一致 → 通过;否则报告不一致 run 数与首个分歧字段。

## 4. 运行

- `run_rerun.sh`:调用 run_exp_beacon.py --out deliverables/experiments_new/beacon_rerun --seeds 0,1,2,3,4
- `compare.py`:与归档逐行对比,输出 analysis.json。
