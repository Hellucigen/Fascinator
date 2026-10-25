# -*- coding: utf-8 -*-
# peerj_migrate_supp.py — supplementary 的 PeerJ 版(preamble 替换,章节不动)
SRC = r"E:\Project\Fascinator\FAS_Paper_I\supplementary.tex"
DST = r"E:\Project\Fascinator\FAS_Paper_I\peerj_supplementary.tex"

s = open(SRC, encoding="utf-8").read()
body_start = s.index("\\begin{document}")
body = s[body_start:]

PREAMBLE = r"""% ============================================================================
% PeerJ Computer Science submission — Supplementary Material (S1--S17).
% Structure-compliant equivalent; swap to official peerj.cls at submission
% (see TODO_FOR_AUTHOR #1). Table/figure/section numbering keeps the S prefix.
% ============================================================================
\documentclass[10pt,a4paper]{article}
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{array}
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}
\usepackage{xcolor}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,fit,backgrounds,calc}
\usepackage{caption}
\sloppy
\setlength{\emergencystretch}{3em}
\captionsetup{font=small,labelfont=bf}
\usepackage[round,authoryear]{natbib}
\setlength{\bibsep}{2pt}
\usepackage[colorlinks=true,linkcolor=blue!60!black,citecolor=blue!60!black,urlcolor=blue!60!black]{hyperref}
\renewcommand{\thetable}{S\arabic{table}}
\renewcommand{\thefigure}{S\arabic{figure}}
\renewcommand{\thesection}{S\arabic{section}}

\title{\bfseries Supplementary Material for\\
``From Embodied Experience to Persistent Experience-Derived State:\\
An Auditable Unified-Graph Architecture and a Preregistered\\
Boundary Analysis of Activation-Based Access''}
\author{Kailin Yan}
\date{}

\begin{document}"""

s2 = PREAMBLE + body[body.index("document}") + len("document}"):]
open(DST, "w", encoding="utf-8", newline="").write(s2)
print("written", DST, len(s2))
