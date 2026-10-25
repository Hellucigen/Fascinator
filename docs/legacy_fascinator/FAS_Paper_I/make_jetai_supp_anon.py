# -*- coding: utf-8 -*-
# make_jetai_supp_anon.py v2 — 匿名版补充材料(raw string 精确匹配 \\)。
SRC = "jetai_supplementary.tex"
DST = "jetai_supplementary_anonymous.tex"

s = open(SRC, encoding="utf-8").read()
old = (r"\author{Kailin Yan\\ \small Department of Computer Science, "
       r"China University of Petroleum-Beijing at Karamay, Karamay, China}")
assert old in s, "author block not found"
s = s.replace(old, r"\author{}")
for pat in ("Kailin", "Yan", "cupk", "Karamay", "Petroleum", "10.5281",
            "2024015943", "0009-0009"):
    assert pat not in s, "leak: " + pat
open(DST, "w", encoding="utf-8", newline="").write(s)
print("written", DST)
