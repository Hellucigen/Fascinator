# -*- coding: utf-8 -*-
# 对比摘要块: 12:02 基线 vs 当前(两版主文)
import re

def abstract(path):
    t = open(path, encoding="utf-8").read()
    m = re.search(r"\\begin\{abstract\}.*?\\end\{abstract\}", t, re.S)
    return m.group(0) if m else None

base = {f: abstract("../deliverables/paper_final/" + f)
        for f in ("jetai_main_annotated.tex", "jetai_main_anonymous.tex")}
for f in ("jetai_main_annotated.tex", "jetai_main_anonymous.tex"):
    cur = abstract(f)
    words = len(re.findall(r"\w+", re.sub(r"\\[a-zA-Z]+|[{}&\\%~$]", " ", cur)))
    print(f, "| abstract identical to baseline:", cur == base[f],
          "| chars:", len(cur), "| ~words:", words)
