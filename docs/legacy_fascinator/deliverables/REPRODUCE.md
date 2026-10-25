# REPRODUCE.md — 一键复现指南

## 范围
论文全部声称数字来自归档运行输出。归档零 LLM 实验可完整复现;LLM 决策头实验复现结果级(非轨迹级,见论文 S10)。

## 环境
- Python ≥3.10(开发环境:E:/Miniforge.envs/Fascinator,Python 3.12)
- 依赖:numpy、scipy、matplotlib、sentence-transformers、torch(cpu 可)、pymupdf(仅扫描工具)
- 嵌入模型:BAAI/bge-small-zh-v1.5(本地路径 E:/Models/bge-small-zh-v1.5 或 HF 自动下载)

## 一键复现(零 LLM,约几分钟)

```bash
# 1) 共享枢纽参数扫描(84 格 × 30 种子 + O3 复现格;~2 分钟)
python deliverables/experiments_new/shared_hub_sweep/run_sweep.py
python deliverables/experiments_new/shared_hub_sweep/extract.py   # 生成 paper_numbers.json(论文 S8/正文数字)

# 2) 嵌入基线零 LLM 可达性检验(20 种子;~1 分钟,含模型加载)
python deliverables/experiments_new/emb_flat_check/run_check.py

# 3) 图形生成(论文全部 matplotlib 图)
python paper_audit/gen_figures_new.py
python paper_audit/gen_fig_sweep.py

# 4) 论文编译(需 MiKTeX/TeX Live)
cd FAS_Paper_I
pdflatex main_v2 && bibtex main_v2 && pdflatex main_v2 && pdflatex main_v2
pdflatex main_zh_v2 && bibtex main_zh_v2 && pdflatex main_zh_v2 && pdflatex main_zh_v2
pdflatex supplementary_v2 && pdflatex supplementary_zh_v2

# 5) 排版扫描(必须双清零)
python FAS_Paper_I/_vec_scan2.py FAS_Paper_I/main_v2.pdf FAS_Paper_I/main_zh_v2.pdf \
    FAS_Paper_I/supplementary_v2.pdf FAS_Paper_I/supplementary_zh_v2.pdf
cd FAS_Paper_I && for f in main_v2 main_zh_v2 supplementary_v2 supplementary_zh_v2; do
  pdftotext -bbox $f.pdf _$f.xml && python scan_overlaps.py _$f.xml; done
```

## 归档复现(不需要重跑)
- 机制战役(34,016 run):`experiments/core_incremental_value/`(raw_results.jsonl、statistics.csv、analysis.json、manifest.json 预注册)。
- 证伪战役(663 run):`research_audit/mechanism_falsification/`。
- 信标战役(80 run):`experiments/beacon_v1/`(analysis_final.json)。
- 路由战役(520 run):`experiments/core_routing_v2/`(statistics.csv;v1 已标 INVALID)。
- 关系方向(60 run):`experiments/relation_direction_campaign/`。
- 主体实验族(494 run):`FAS_Research_Experiments/` 各子目录。

## LLM 决策头复现(可选)
需要 `data/llm_secret.json`(投稿工件中匿名化/移除)。复现信标 5 种子子集:
```bash
python scripts/run_exp_beacon.py --out deliverables/experiments_new/beacon_rerun --seeds 0,1,2,3,4
python deliverables/experiments_new/beacon_rerun/compare.py   # 预期:success 20/20 一致,轨迹部分一致(见 S10)
```

## 回归测试
```bash
python -m pytest tests/ -q   # 写作时 104 项通过
```
