# -*- coding: utf-8 -*-
# scan_residue.py — 扫描 tex 源与 PDF 文本中的转义吞命令残留。
# 模式: CR(0x0d)/TAB(0x09) 字符、eftab/effig/efsec/eqref 残体(\r 被吞)、
# 制表吞掉的 extbf 类、字面 "ef{" 。
import glob
import os
import re
import sys

PAPER = r'E:\Project\Fascinator\FAS_Paper_I'
TEX = ['main.tex', 'main_zh.tex', 'peerj_main.tex', 'supplementary.tex',
       'supplementary_zh.tex', 'peerj_supplementary.tex']
PATTERNS = {
    'CR_char': re.compile('\r'),
    'ef-ref': re.compile(r'(?<![A-Za-z\\])ef\{(tab|fig|sec|eq):'),
    'eftab': re.compile(r'eftab:'),
    'effig': re.compile(r'effig:'),
    'efsec': re.compile(r'efsec:'),
    'TAB+cmd': re.compile('\t' + r'[a-z]{3,}'),
}
bad = 0
for f in TEX:
    p = os.path.join(PAPER, f)
    if not os.path.isfile(p):
        continue
    raw = open(p, 'rb').read()
    s = raw.decode('utf-8', errors='replace')
    for name, pat in PATTERNS.items():
        for m in pat.finditer(s):
            ln = s.count('\n', 0, m.start()) + 1
            ctx = s[max(0, m.start() - 40):m.end() + 40].replace('\r', '<CR>').replace('\t', '<TAB>')
            print('%s L%d [%s]: %s' % (f, ln, name, ctx))
            bad += 1
print('tex residue hits:', bad)

import pymupdf
PDFS = ['main.pdf', 'main_zh.pdf', 'peerj_main.pdf', 'supplementary.pdf',
        'supplementary_zh.pdf', 'peerj_supplementary.pdf']
for f in PDFS:
    p = os.path.join(PAPER, f)
    if not os.path.isfile(p):
        continue
    doc = pymupdf.open(p)
    hits = []
    for pno in range(doc.page_count):
        t = doc[pno].get_text()
        for pat in ('eftab:', 'effig:', 'efsec:', 'Table ef', 'Fig. ef', 'Section ef'):
            if pat in t:
                hits.append((pno + 1, pat))
    print(f, 'pdf hits:', hits)
