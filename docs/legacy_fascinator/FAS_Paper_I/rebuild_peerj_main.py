# -*- coding: utf-8 -*-
# rebuild_peerj_main.py — 用 wlpeerj.cls 接口重建 peerj_main.tex 头部
# (正文体一字不动;仅 preamble/标题块/摘要位置/新增 Acknowledgments)。
import re

SRC = r'E:\Project\Fascinator\FAS_Paper_I\peerj_main.tex'
s = open(SRC, encoding='utf-8').read()

# 1) 摘出 abstract 内容
m = re.search(r'(?s)\\begin\{abstract\}(.*?)\\end\{abstract\}', s)
abstract_body = m.group(1).strip()
s = s[:m.start()] + '@@ABSTRACT_MOVED@@' + s[m.end():]

# 2) 替换 preamble(从文件头到 \begin{document} 后到 \maketitle 区)
head_end = s.index('\\begin{document}')
old_head = s[:head_end]
new_head = r"""% ============================================================================
% PeerJ Computer Science submission — built on the official template
% interface (wlpeerj.cls; see that file's header: interface-compatible
% stand-in until pasted into the official Overleaf template).
% Review submission keeps the lineno option; remove it for camera-ready.
% ============================================================================
\documentclass[fleqn,10pt,lineno]{wlpeerj}
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
\usepackage[colorlinks=true,linkcolor=blue!60!black,citecolor=blue!60!black,urlcolor=blue!60!black]{hyperref}
\setlength{\bibsep}{2pt}
\sloppy
\setlength{\emergencystretch}{3em}

\title{From Embodied Experience to Persistent Experience-Derived State: An Auditable Unified-Graph Architecture and a Preregistered Boundary Analysis of Activation-Based Access}

\author[1]{Kailin Yan}
\affil[1]{[TODO-FOR-AUTHOR: official English name of department, university, city, country]}
\corrauthor[1]{Kailin Yan}{2024015943@st.cupk.edu.cn}
% [TODO-FOR-AUTHOR: confirm email + add ORCID; online submission metadata
%  must match this cover block EXACTLY.]

\keywords{cognitive architecture; knowledge graph; spreading activation; embodied agents; episodic memory; preregistration}

\begin{abstract}
""" + abstract_body + r"""
\end{abstract}

"""
s = new_head + s[head_end:]

# 3) \begin{document} 后:标准 maketitle 块
s = s.replace('\\begin{document}\n\\maketitle',
              '\\begin{document}\n\\maketitle\n\\thispagestyle{empty}', 1)

# 4) 新增 Acknowledgments(在声明区之前;不提资助者)
ack = r"""% ---------------------------------------------------------------------------
\section*{Acknowledgments}
[TODO-FOR-AUTHOR: acknowledgments text (per PeerJ rules, do NOT mention
funders here; do not list anyone who has not agreed to be named). If there
is nothing to acknowledge, delete this section.]

"""
i = s.index('% ---------------------------------------------------------------------------\n% PeerJ declaration block')
s = s[:i] + ack + s[i:]

open(SRC, 'w', encoding='utf-8', newline='').write(s)
print('rebuilt', SRC, len(s))
