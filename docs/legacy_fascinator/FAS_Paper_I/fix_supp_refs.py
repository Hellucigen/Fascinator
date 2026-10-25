# -*- coding: utf-8 -*-
# fix_supp_refs.py — 把补充材料中指向主文 label 的 \ref/\FigTab 替换为
# 主文实际编号(从 jetai_main_annotated.aux 读取),消除 14 个 undef。
import re

# 1) label -> number from main aux
aux = open("jetai_main_annotated.aux", encoding="utf-8", errors="ignore").read()
num = dict(re.findall(r"\\newlabel\{([^}]+)\}\{\{([^}]+)\}", aux))
# figures/tables in aux are numbered as plain ints
def show(k):
    v = num.get(k, "??")
    return v

MAIN_KEYS = ("fig:loop", "fig:sweep", "fig:boundary", "tab:evidence",
             "tab:stats", "sec:arch-llm", "sec:res-reuse", "sec:res-persist",
             "sec:res-boundary", "sec:res-rerun", "sec:res-campaign",
             "sec:res-psa", "sec:res-system", "sec:audit-negative",
             "sec:limits", "sec:method-civ", "sec:method-routing",
             "sec:method", "sec:arch-wb", "sec:intro", "sec:discussion",
             "sec:arch")
for k in MAIN_KEYS:
    print("%-22s -> %s" % (k, num.get(k, "-")))

REPL = {
    "Figure~\\ref{fig:loop}": "Figure %s of the main text" % num["fig:loop"],
    "Figure~\\ref{fig:sweep}": "Figure %s of the main text" % num["fig:sweep"],
    "Figure~\\ref{fig:boundary}": "Figure %s of the main text" % num["fig:boundary"],
    "Fig.~\\ref{fig:boundary}": "Fig. %s of the main text" % num["fig:boundary"],
    "Fig.~\\ref{fig:sweep}": "Fig. %s of the main text" % num["fig:sweep"],
    "Table~\\ref{tab:evidence}": "Table %s of the main text" % num["tab:evidence"],
    "Table~\\ref{tab:stats}": "Table %s of the main text" % num["tab:stats"],
}
# section refs
for lab in ("sec:arch-llm", "sec:res-reuse", "sec:res-persist",
            "sec:res-boundary", "sec:res-rerun", "sec:res-campaign",
            "sec:res-psa", "sec:res-system", "sec:audit-negative",
            "sec:limits", "sec:method-civ", "sec:method-routing",
            "sec:method", "sec:arch-wb", "sec:intro", "sec:discussion",
            "sec:arch"):
    if lab in num:
        REPL["Section~\\ref{%s}" % lab] = "Section %s of the main text" % num[lab]
        REPL["\\S\\ref{%s}" % lab] = "\\S %s of the main text" % num[lab]

for f in ("jetai_supplementary.tex", "jetai_supplementary_anonymous.tex"):
    s = open(f, encoding="utf-8").read()
    n = 0
    for old, new in REPL.items():
        c = s.count(old)
        if c:
            s = s.replace(old, new)
            n += c
    # 剩余任何指向主文的裸 \ref{sec:/fig:/tab:非s-*}
    def mres(m):
        k = m.group(1)
        if k in num:
            return "Section/Fig/Table %s of the main text" % num[k]
        return m.group(0)
    s = re.sub(r"\\ref\{(sec:[^}]+|fig:(?!s-)[^}]+|tab:(?!s-)[^}]+)\}", mres, s)
    open(f, "w", encoding="utf-8", newline="").write(s)
    print("fixed", f, "replacements:", n)
