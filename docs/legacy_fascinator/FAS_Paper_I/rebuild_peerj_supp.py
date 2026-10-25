# -*- coding: utf-8 -*-
# rebuild_peerj_supp.py — peerj_supplementary.tex 换用 wlpeerj.cls
# (正文零改动;仅 preamble/标题块)。
import re

SRC = r'E:\Project\Fascinator\FAS_Paper_I\peerj_supplementary.tex'
s = open(SRC, encoding='utf-8').read()

head_end = s.index('\\begin{document}')
new_head = r"""% ============================================================================
% PeerJ Computer Science submission — Supplementary Material (S1--S18),
% built on the official template interface (wlpeerj.cls; see its header).
% ============================================================================
\documentclass[fleqn,10pt]{wlpeerj}
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
\usepackage[colorlinks=true,linkcolor=blue!60!black,citecolor=blue!60!black,urlcolor=blue!60!black]{hyperref}
\setlength{\bibsep}{2pt}
\sloppy
\setlength{\emergencystretch}{3em}
\renewcommand{\thetable}{S\arabic{table}}
\renewcommand{\thefigure}{S\arabic{figure}}
\renewcommand{\thesection}{S\arabic{section}}

\title{Supplementary Material for\\
``From Embodied Experience to Persistent Experience-Derived State: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access''}

\author[1]{Kailin Yan}
\affil[1]{[TODO-FOR-AUTHOR: official English name of department, university, city, country]}
\corrauthor[1]{Kailin Yan}{2024015943@st.cupk.edu.cn}

"""
s = new_head + s[head_end:]
s = s.replace('\\begin{document}\n\\maketitle',
              '\\begin{document}\n\\maketitle\n\\thispagestyle{empty}', 1)
open(SRC, 'w', encoding='utf-8', newline='').write(s)
print('rebuilt', SRC)
