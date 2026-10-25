# -*- coding: utf-8 -*-
# make_jetai_supp.py — jetai_supplementary.tex:与 peerj_supplementary
# 内容相同,换标准 article 基类(去 PeerJ 品牌)。
SRC = r"E:\Project\Fascinator\FAS_Paper_I\peerj_supplementary.tex"
DST = r"E:\Project\Fascinator\FAS_Paper_I\jetai_supplementary.tex"

s = open(SRC, encoding="utf-8").read()
head_end = s.index("\\begin{document}")
body = s[head_end:]

NEW_HEAD = r"""\documentclass[10pt]{article}
\usepackage[letterpaper,margin=1in]{geometry}
\usepackage{mathptmx}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{array}
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}
\usepackage{xcolor}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,fit,backgrounds,calc}
\usepackage{caption}
\captionsetup{font=small,labelfont=bf}
\usepackage[round,authoryear,sort&compress]{natbib}
\setlength{\bibsep}{2pt}
\usepackage[colorlinks=true,linkcolor=blue!60!black,citecolor=blue!60!black,urlcolor=blue!60!black]{hyperref}
\sloppy
\setlength{\emergencystretch}{3em}
\renewcommand{\thetable}{S\arabic{table}}
\renewcommand{\thefigure}{S\arabic{figure}}
\renewcommand{\thesection}{S\arabic{section}}

\title{\bfseries Supplementary Material for\\
``From Embodied Experience to Persistent Experience-Derived State: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access''}
\author{Kailin Yan\\ \small Department of Computer Science, China University of Petroleum-Beijing at Karamay, Karamay, China}
\date{}

"""

body = body.replace("\\maketitle\n\\thispagestyle{empty}", "\\maketitle", 1)
open(DST, "w", encoding="utf-8", newline="").write(NEW_HEAD + body)
print("written", DST)
