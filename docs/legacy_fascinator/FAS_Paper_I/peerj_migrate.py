# -*- coding: utf-8 -*-
# peerj_migrate.py — 生成 PeerJ 提交版 main.tex 结构迁移稿(内容零改动,仅
# preamble/标题层级/声明区)。官方 peerj.cls 无法下载(Overleaf/GitHub/CTAN
# 均不可达),按任务书授权生成"结构合规版";拿到官方模板后只需换
# documentclass(TODO_FOR_AUTHOR 记录)。
import re

SRC = r"E:\Project\Fascinator\FAS_Paper_I\main.tex"
DST = r"E:\Project\Fascinator\FAS_Paper_I\peerj_main.tex"

s = open(SRC, encoding="utf-8").read()

# 1) 定位正文起点(\begin{document}),替换整个 preamble + 标题块
body_start = s.index("\\begin{document}")
body = s[body_start:]

PREAMBLE = r"""% ============================================================================
% PeerJ Computer Science submission draft — structure-compliant equivalent.
% NOTE: the official peerj.cls / peerj.bst ship with the PeerJ Overleaf
% template (https://www.overleaf.com/latex/templates). At submission time,
% import this body into the official template and swap the preamble
% (TODO_FOR_AUTHOR #1). Section names, author-year citations, line numbers,
% and the declaration block below follow the official structure.
% ============================================================================
\documentclass[10pt]{article}
\usepackage[margin=2.5cm]{geometry}
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

\title{\bfseries From Embodied Experience to Persistent Experience-Derived State: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access}
% [TODO-FOR-AUTHOR: affiliations, ORCID, corresponding author — must match
%  the online submission metadata EXACTLY (PeerJ requirement).]
\author{Kailin Yan\thanks{Corresponding author: \texttt{2024015943@st.cupk.edu.cn} [TODO-FOR-AUTHOR: confirm affiliation wording and ORCID]}}
\date{}

\begin{document}"""

s2 = PREAMBLE + body[body.index("document}") + len("document}"):]

# 2) 章节归并(只改标题层级,内容不动)
s2 = s2.replace("\\section{The Fascinator Architecture}",
                "\\section{Materials and Methods}")
s2 = s2.replace("\\section{Evaluation Protocol}",
                "\\subsection{Evaluation protocol}")
# Evaluation protocol 之后、Results 之前的 subsection 降为 subsubsection
i_ep = s2.index("\\subsection{Evaluation protocol}")
i_res = s2.index("\\section{Results}")
seg = s2[i_ep:i_res]
seg = seg.replace("\\subsection{", "\\subsubsection{")
seg = seg.replace("\\subsubsection{Evaluation protocol}",
                  "\\subsection{Evaluation protocol}", 1)
s2 = s2[:i_ep] + seg + s2[i_res:]

s2 = s2.replace("\\section{Limitations}", "\\subsection{Limitations}")
s2 = s2.replace("\\section{Conclusion}", "\\section{Conclusions}")

# 3) PeerJ 声明区(占位;内容待作者确认)插入到 bibliography 之前
DECL = r"""
% ---------------------------------------------------------------------------
% PeerJ declaration block (all fields are author-confirmation TODOs)
% ---------------------------------------------------------------------------
\section*{Funding}
[TODO-FOR-AUTHOR: state funding or ``The authors received no external funding for this work.'']

\section*{Competing interests}
[TODO-FOR-AUTHOR: state competing interests or ``The authors declare no competing interests.'']

\section*{Author contributions}
[TODO-FOR-AUTHOR: CRediT roles, e.g. ``KY conceived, designed, implemented, and wrote the work.'']

\section*{Data and code availability}
All experiments are deterministic and fully archived; the complete reproducibility package --- raw run outputs, graph snapshots, statistics files, source code, preregistration records, and a one-command verifier that recomputes the paper's key numbers without an LLM --- is openly available on Zenodo at [ZENODO-DOI] under [LICENSE-TO-BE-CHOSEN]. Preregistrations are included in the package (also Supplementary Material S14--S16). LLM decision-head replications require an anonymized endpoint configuration that is not redistributed; they reproduce at the outcome level rather than bit-identical trajectories (Section~\ref{sec:res-rerun}).

\section*{Reporting guidelines}
The study follows preregistered-experiment reporting: preregistration records for the mechanism campaign, the persistent-state experiment and controls, and the presentation-equivalence revision (including its gate-stopped preflight) ship with the reproducibility package and are summarized in Supplementary Material S14--S16. No animal or human subjects were involved; no ARRIVE/PRISMA/STROBE checklist applies. [TODO-FOR-AUTHOR: confirm.]

"""

i_bib = s2.index("\\bibliographystyle")
s2 = s2[:i_bib] + DECL + s2[i_bib:]

open(DST, "w", encoding="utf-8", newline="").write(s2)
print("written", DST, len(s2), "chars")
