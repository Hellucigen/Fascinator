# -*- coding: utf-8 -*-
# restore_floats.py — 把误随段落搬走的两个浮动体放回主文:
#  fig:loop(figure 环境)-> 主文 §3.6 摘要段后;
#  tab:stats(table 环境)-> 主文 \section{Results} 前。
# 并从两版补充材料的 S19.12/S19.8 中删除它们。
import re

FIG_RE = re.compile(r"(?s)\\begin\{figure\}.*?\\label\{fig:loop\}.*?\\end\{figure\}\n?")
TAB_RE = re.compile(r"(?s)\\begin\{table\}.*?\\label\{tab:stats\}.*?\\end\{table\}\n?")

MAINS = ("jetai_main_annotated.tex", "jetai_main_anonymous.tex")
SUPPS = ("jetai_supplementary.tex", "jetai_supplementary_anonymous.tex")

fig = tab = None
for f in SUPPS:
    s = open(f, encoding="utf-8").read()
    mf = FIG_RE.search(s)
    mt = TAB_RE.search(s)
    if mf:
        fig = fig or mf.group(0)
        s = s.replace(mf.group(0), "", 1)
    if mt:
        tab = tab or mt.group(0)
        s = s.replace(mt.group(0), "", 1)
    open(f, "w", encoding="utf-8", newline="").write(s)
    print("supp cleaned:", f, "| fig:", bool(mf), "tab:", bool(mt))

assert fig and tab, "floats not found in supp"

for f in MAINS:
    s = open(f, encoding="utf-8").read()
    # fig:loop 放回 §3.6 摘要句后
    anchor = "Full paragraph: Supplementary Material~S19.12.\n\n"
    assert anchor in s, f
    s = s.replace(anchor, anchor + fig + "\n", 1)
    # tab:stats 放回 \section{Results} 前
    i = s.index("\\section{Results}")
    s = s[:i] + tab + "\n" + s[i:]
    open(f, "w", encoding="utf-8", newline="").write(s)
    print("main restored:", f)
print("done")
