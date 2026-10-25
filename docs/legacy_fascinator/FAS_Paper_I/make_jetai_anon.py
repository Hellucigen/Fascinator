# -*- coding: utf-8 -*-
# make_jetai_anon.py v2 — 修复:wlpeerj 摘要在 \begin{document} 之前,
# v1 切片丢失摘要。现显式抓取 abstract 块并放入 article 版 preamble。
import re

SRC = r"E:\Project\Fascinator\FAS_Paper_I\peerj_main.tex"
s = open(SRC, encoding="utf-8").read()

m = re.search(r"(?s)\\begin\{abstract\}(.*?)\\end\{abstract\}", s)
assert m, "abstract not found in source"
ABSTRACT = m.group(1).strip()

BODY = s[s.index("\\begin{document}"):]
BODY = BODY.replace("\\maketitle\n\\thispagestyle{empty}", "\\maketitle", 1)
BODY = BODY.replace("% bibliographystyle is set by the class (apalike, author--year)",
                    "\\bibliographystyle{apalike}")

NEW_HEAD = r"""\documentclass[10pt]{article}
\usepackage[letterpaper,margin=1in]{geometry}
\usepackage{mathptmx}
\usepackage[mathlines]{lineno}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{array}
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}
\usepackage{xcolor}
\usepackage{algorithm}
\usepackage{algpseudocode}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,fit,backgrounds,calc}
\usepackage{caption}
\captionsetup{font=small,labelfont=bf}
\usepackage[round,authoryear,sort&compress]{natbib}
\setlength{\bibsep}{2pt}
\usepackage[colorlinks=true,linkcolor=blue!60!black,citecolor=blue!60!black,urlcolor=blue!60!black]{hyperref}
\sloppy
\setlength{\emergencystretch}{3em}
\linenumbers
"""

TITLE = ("From Embodied Experience to Persistent Experience-Derived State: "
         "An Auditable Unified-Graph Architecture and a Preregistered "
         "Boundary Analysis of Activation-Based Access")

ann = (NEW_HEAD
       + "\\title{\\bfseries " + TITLE + "}\n"
       + "\\author{Kailin Yan\\thanks{ORCID: 0009-0009-6762-2684}\\\\\n"
       + "\\small Department of Computer Science, China University of "
       + "Petroleum-Beijing at Karamay, Karamay, China\\\\\n"
       + "\\small \\texttt{2024015943@st.cupk.edu.cn}}\n"
       + "\\date{}\n"
       + "\\begin{document}\n\\maketitle\n\\begin{abstract}\n"
       + ABSTRACT + "\n\\end{abstract}\n"
       + BODY[len("\\begin{document}\n\\maketitle"):])
open(r"E:\Project\Fascinator\FAS_Paper_I\jetai_main_annotated.tex",
     "w", encoding="utf-8", newline="").write(ann)

anon = (NEW_HEAD
        + "\\title{\\bfseries " + TITLE + "}\n"
        + "\\author{}\n\\date{}\n"
        + "\\begin{document}\n\\maketitle\n\\begin{abstract}\n"
        + ABSTRACT + "\n\\end{abstract}\n"
        + BODY[len("\\begin{document}\n\\maketitle"):])
anon = anon.replace("Kailin Yan conceived and designed the study",
                    "The author conceived and designed the study")
anon = anon.replace(
    "is openly available on Zenodo (DOI: 10.5281/zenodo.23196280) under a split license (data, archives, and documentation: CC BY 4.0; source code: MIT).",
    "is deposited in a public repository (Zenodo); the DOI is withheld from this anonymized version and will be restored in the accepted manuscript.")
for pat in ("Kailin", "Yan", "cupk", "Karamay", "Petroleum", "0009-0009",
            "10.5281", "2024015943"):
    assert pat not in anon, "identifier leak: " + pat
open(r"E:\Project\Fascinator\FAS_Paper_I\jetai_main_anonymous.tex",
     "w", encoding="utf-8", newline="").write(anon)
print("v2 written, abstract preserved")
