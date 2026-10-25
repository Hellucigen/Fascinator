# -*- coding: utf-8 -*-
entry = """
## JETAI 匿名补充材料 + 浮动体归位修复(2026-10-09)

- 发现方案A三轮搬运时 fig:loop(概念循环图)与 tab:stats(统计口径表)
  被连带搬进补充材料 S19.12/S19.8,主文两处引用悬空;首次自动修复的
  贪婪正则误把 S19 大段内容搬进主文(48页/重复 label),已整体回滚到
  当日 12:02 基线后改用位置寻址精确摘取,两浮动体归还原位。
- 主文两版重编译:均 15 页,0 错误 0 未解析;正文字数与 12:02 基线
  逐词一致(同一 tokenizer 差值 0;浮动体不计入正文口径)。编号更新:
  fig:loop=3、sweep=4、boundary=5;tab:evidence=1、stats=2、beacon=3、
  boundary=4;全部表格引用走 \\ref 自动编号。
- 补充材料中 14 处指向主文 label 的 \\ref 依主文 aux 纯文化为
  "Section X / Figure N / Table N of the main text"(零内容改动),
  其中 1 处 "Fig.~\\ref{fig:loop}" 残留拗口措辞已修为 "Fig.~3 of the
  main text"。双版本重编译:20 页,0 错误,0 未解析引用。
- 新增 jetai_supplementary_anonymous.tex/pdf:剥除作者块,身份字符串
  扫描(Kailin/Yan/cupk/Karamay/Petroleum/ORCID/DOI/学号/邮箱)0 命中;
  主文匿名版仅存合规句 "repository cited (Zenodo); DOI withheld",
  不含任何可识别信息。四件 tex+pdf 已同步 paper_final。
"""
p = "../deliverables/paper_final/CHANGELOG.md"
s = open(p, encoding="utf-8").read()
if "浮动体归位修复(2026-10-09)" in s:
    print("already appended")
else:
    open(p, "w", encoding="utf-8").write(s.rstrip() + "\n" + entry)
    print("appended", len(entry), "chars")
