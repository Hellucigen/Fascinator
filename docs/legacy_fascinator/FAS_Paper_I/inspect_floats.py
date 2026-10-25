# -*- coding: utf-8 -*-
# 检查 restore_floats 实际搬运内容:主文/补充材料的 figure、table 环境清单
import re

for f in ("jetai_main_annotated.tex", "jetai_main_anonymous.tex",
          "jetai_supplementary.tex", "jetai_supplementary_anonymous.tex"):
    t = open(f, encoding="utf-8").read()
    print("=" * 20, f, "| figs:", t.count(r"\begin{figure}"),
          "| tables:", t.count(r"\begin{table}"), "| chars:", len(t))
    for m in re.finditer(r"\\caption\{([^{}]{0,80})", t):
        print("   caption:", m.group(1).replace("\n", " ")[:80])
    for m in re.finditer(r"\\label\{(fig|tab):([a-z0-9]+)\}", t):
        print("   label:", m.group(0))
    print("   pages hint: lines =", t.count("\n"))
