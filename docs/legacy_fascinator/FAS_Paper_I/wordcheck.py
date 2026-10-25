# -*- coding: utf-8 -*-
# 与 verify_anon_final.py 完全同口径,对比 12:02 基线 vs 当前主文字数
import re

def body_words(t):
    t = re.sub(r"\\begin\{(figure|table)\}.*?\\end\{(?:figure|table)\}", " ", t, flags=re.S)
    t = re.sub(r"\\begin\{comment\}.*?\\end\{comment\}", " ", t, flags=re.S)
    t = re.sub(r"(?<!\\)%.*", " ", t)
    t = t[t.index(r"\begin{document}"):t.index(r"\bibliography")]
    t = re.sub(r"\\[a-zA-Z@]+\*?", " ", t)
    t = re.sub(r"[{}&\\]", " ", t)
    return len(re.findall(r"[A-Za-z0-9][\w'\-\u00b1\.=/@]*", t))

for f in ("jetai_main_annotated.tex", "jetai_main_anonymous.tex"):
    old = body_words(open("../deliverables/paper_final/" + f, encoding="utf-8").read())
    new = body_words(open(f, encoding="utf-8").read())
    print(f, "| baseline(12:02):", old, "| current:", new,
          "| delta:", new - old)
