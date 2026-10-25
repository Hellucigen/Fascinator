# -*- coding: utf-8 -*-
# 精确摘取补充材料中的 fig:loop 图环境与 tab:stats 表环境,放回两版主文原位。
# 方法: 定位 label 字符串,向前找最近的 \begin{figure|table},向后找对应 \end。
import re

def extract_env(text, label, kind):
    i = text.index(r"\label{%s}" % label)
    begin = text.rfind(r"\begin{%s}" % kind, 0, i)
    end = text.index(r"\end{%s}" % kind, i) + len(r"\end{%s}" % kind)
    # 吃掉紧随其后的换行
    while end < len(text) and text[end] in "\r\n":
        end += 1
    return begin, end, text[begin:end]

supp = open("jetai_supplementary.tex", encoding="utf-8").read()
fb, fe, fig_block = extract_env(supp, "fig:loop", "figure")
tb, te, tab_block = extract_env(supp, "tab:stats", "table")
print("fig block lines:", fig_block.count("\n"), "| tab block lines:", tab_block.count("\n"))
print("fig starts:", repr(fig_block[:40]), "ends:", repr(fig_block[-40:]))
print("tab starts:", repr(tab_block[:40]), "ends:", repr(tab_block[-40:]))

# 先删靠后的 tab 再删 fig(下标不失效): 但两区间不相交,按位置从大到小删
for b, e in sorted([(fb, fe), (tb, te)], reverse=True):
    supp = supp[:b] + supp[e:]
open("jetai_supplementary.tex", "w", encoding="utf-8").write(supp)
print("supp cleaned | fig:loop in supp:", "fig:loop" in supp,
      "| tab:stats in supp:", "tab:stats" in supp)

ANCHOR = "Full paragraph: Supplementary Material~S19.12.\n\n"
RES = "\\section{Results}"
for f in ("jetai_main_annotated.tex", "jetai_main_anonymous.tex"):
    m = open(f, encoding="utf-8").read()
    assert m.count(ANCHOR) == 1, (f, "fig anchor", m.count(ANCHOR))
    assert m.count(RES) == 1, (f, "Results", m.count(RES))
    m = m.replace(ANCHOR, ANCHOR + fig_block + "\n")
    m = m.replace(RES, tab_block.rstrip() + "\n\n" + RES)
    open(f, "w", encoding="utf-8").write(m)
    print("main fixed:", f, "| figs:", m.count(r"\begin{figure}"),
          "| tab:stats labels:", len(re.findall(r"\\label\{tab:stats\}", m)),
          "| fig:loop labels:", len(re.findall(r"\\label\{fig:loop\}", m)))
