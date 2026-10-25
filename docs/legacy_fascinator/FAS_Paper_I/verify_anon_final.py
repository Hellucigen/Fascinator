# -*- coding: utf-8 -*-
# 终验: 匿名两 PDF 身份字符串扫描 + 主文正文字数复核(与 4982 同口径)
import subprocess, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PATS = ["Kailin", "Yan", "cupk", "Karamay", "Petroleum", "China University",
        "0009-0009", "10.5281", "zenodo", "Zenodo", "2024015943", "@st."]

for pdf in ("jetai_supplementary_anonymous.pdf", "jetai_main_anonymous.pdf"):
    out = subprocess.run(["pdftotext", pdf, "-"], capture_output=True,
                         text=True, errors="replace").stdout
    norm = re.sub(r"\s+", " ", out)
    hits = []
    for p in PATS:
        for m in re.finditer(re.escape(p), norm):
            ctx = norm[max(0, m.start() - 30):m.end() + 30]
            hits.append((p, ctx))
    print(pdf, "| hits:", len(hits))
    for p, c in hits:
        print("   ", repr(p), "->", c)

# 主文字数: 剥除注释/浮动体/ preamble,统计正文词数(既有口径)
def body_words(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"\\begin\{(figure|table)\}.*?\\end\{(?:figure|table)\}", " ", t, flags=re.S)
    t = re.sub(r"\\begin\{comment\}.*?\\end\{comment\}", " ", t, flags=re.S)
    t = re.sub(r"(?<!\\)%.*", " ", t)
    t = t[t.index(r"\begin{document}"):t.index(r"\bibliography")]
    t = re.sub(r"\\[a-zA-Z@]+\*?", " ", t)
    t = re.sub(r"[{}&\\]", " ", t)
    return len(re.findall(r"[A-Za-z0-9][\w'\-\u00b1\.=/@]*", t))

for m in ("jetai_main_annotated.tex", "jetai_main_anonymous.tex"):
    print(m, "body words ~", body_words(m))
