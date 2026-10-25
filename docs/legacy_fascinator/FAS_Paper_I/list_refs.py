# -*- coding: utf-8 -*-
import re
pat = re.compile(r"\\(?:ref|Cref|autoref)\{([^}]+)\}")
for f in ("jetai_supplementary.tex", "jetai_supplementary_anonymous.tex"):
    s = open(f, encoding="utf-8").read()
    print(f, "->", sorted(set(pat.findall(s))))
