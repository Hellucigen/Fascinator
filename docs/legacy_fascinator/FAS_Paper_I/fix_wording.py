# -*- coding: utf-8 -*-
# S19.12 段首 "Fig.~Section/Fig/Table 3 of the main text" → "Fig.~3 of the main text"
OLD = "Fig.~Section/Fig/Table 3 of the main text shows"
NEW = "Fig.~3 of the main text shows"
for f in ("jetai_supplementary.tex", "jetai_supplementary_anonymous.tex"):
    s = open(f, encoding="utf-8").read()
    assert s.count(OLD) == 1, (f, s.count(OLD))
    open(f, "w", encoding="utf-8", newline="").write(s.replace(OLD, NEW))
    print("fixed", f)
