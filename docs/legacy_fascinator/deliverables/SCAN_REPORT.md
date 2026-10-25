# 图表扫描报告(修复前后对比)

工具:`_vec_scan2.py`(向量级:A 文字外溢填充框 / B 线段穿文字 / C 描边填充矩形互叠)
与 `scan_overlaps.py`(文字级 glyph 框互叠,阈值 0.45×0.45)。基线 PDF:`deliverables/baseline_snapshot/`。
阈值说明:两类扫描均未修改判定规则;清零全部来自对图/表的实际排版修复。

## 修复前(基线,2026-10-01 快照)

| PDF | 向量级 | 文字级 |
|-----|--------|--------|
| main.pdf(EN) | A7 B18 C62(p4 A4B8C4, p5 B1C2, p6 A4B5C1, p9 B1, p10 C30, p11 C20, p13 A3B3C5, p14 B12) | 6(\xrightarrow 标签×箭头 glyph×4、参考文献×2) |
| main_zh.pdf(ZH) | A6 B14 C54 | 4 |

## 修复后(2026-10-01,最终版)

| PDF | 向量级 | 文字级 |
|-----|--------|--------|
| main.pdf(EN,13 页) | **0** | **0** |
| main_zh.pdf(ZH,12 页) | **0** | **0** |
| supplementary.pdf(EN,12 页) | **0** | **0** |
| supplementary_zh.pdf(ZH,11 页) | **0** | **0** |
| figures/fig_sweep.pdf(新图) | **0** | **0** |
| figures/fig_diffusion_boundary.pdf | **0** | **0** |
| figures/fig_evidence_matrix.pdf | **0** | **0** |

## 主要修复(对应任务书问题表)

1. **fig:ontology**:跨域边全部改为上/下走廊绕行(rc.north→ac 上走廊;ae.south→ch 下走廊 y=-4.15;it.west→ac 左走廊 x=-7.35),不再穿中央 G 节点;`modulates` 标签移出 G;`belongs` 标签移至短边上部(pos=0.30);fit 框与 G 零互叠;域标签置于框外留隙(south/东南向,含 3pt 间隙)。
2. **fig:act-schematic**:entity a/b 竖直等距重排((2.0,1.8)/(2.0,0.4),垂直距 1.4 > 直径 1.0);flat:nearest 标签改为独立 node(anchor=east);Top-1 平坦路径改为 y=-0.45 走廊并缩短终点(5.35,1.60)避免插入目标节点框。
3. **fig:loop**:两行节点第二行统一加 \strut;s1 脚手架节点移出与 epi 的重叠(below left of ev);反馈线改为 `-- (env.south)` 水平进入,不再穿 env 内部文字;两处共用箭头到达点错开(yshift=-2.5pt)。
4. **fig:reldir(移入补充材料 S9,同样修复)**:(b)(c) 面板标题移至轴线上方(轴 y=-1.75/-4.05,标题 y=-2.15/-4.45),12 处轴线穿字消除。
5. **fig:boundary(生成器 paper_audit/gen_figures_new.py)**:星形 marker 与 combo 标签错位(marker y=0.62,文字 va=top);刻度竖线穿 'sweep' 字(tick length=0 + pad=3,底脊隐藏);marker 改单路径(mfc=none)消除 C 类自叠。
6. **实验矩阵(fig_evidence_matrix)**:verdict 列宽 0.155→0.165;四处词溢出(McNemar/structure/over)通过换行与措辞微调消除;新增 84 格扫描行(内容同步去内部代号)。
7. **文字级清零策略**:所有带标签的 \xrightarrow 改为平文叙述("leads-to 边(权重 = 置信度)")或独立 node 标签;千分位/省略号 glyph 重叠(\vdots→...)消除;CJK 行尾悬挂括号两处通过措辞调整消除。
8. **新图 fig_sweep**:入版前即按双扫描标准设计(色块单路径、图例文字最终移除并交由 caption 承担),一次通过。

## 附:抽验
对本体论图、机制图、循环图、关系方向图所在页用 `_viewer.py` ASCII 位图判读(修复过程中迭代 6 轮);最终版本体论图页全图 ASCII 判读无文字-线段交叠。
