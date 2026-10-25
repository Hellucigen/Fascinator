# 统计档案说明(重要,先读)

**`statistics.csv`** = 路由 v2 正式战役统计(copy 自 `experiments/core_routing_v2/campaign/statistics.csv`,
138 检验行 + 表头,含 `p_bonferroni` 列)。论文正文引用的全部路由数字(520/520 有效、
T4 19/20 vs 15/20 raw p=0.0455、校正后 p≈1 等)以此文件为准。

**`statistics_V1_INVALID.csv`** = 首版路由战役(v1)统计,cmp 验证与
`experiments/core_routing/statistics.csv` 逐字节相同。v1 已被装配审计否决
(harness 从不建边;521/521 demand 层异常吞没;80/80 首步焦点空),其数字
**不作任何声明的依据**。本文件仅作审计留痕保留,引用数字时严禁使用。

其他实验族的机器可读统计在各自 `experiments/<family>/` 目录
(beacon_v1/analysis_final.json、core_incremental_value/statistics.csv 与 analysis.json、
relation_direction_campaign/paired_statistics.csv、
research_audit/mechanism_falsification/statistics.csv 等)。