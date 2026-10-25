# -*- coding: utf-8 -*-
# compress_abstract.py — 摘要压缩到 ≤350 词(数字与结论不变;逐句删改
# 见 REPRO_REPORT §7 与 CHANGELOG)。
import re

EN_EDITS = [
    ("Embodied agents accumulate experience far faster than that experience can be written back into persistent state: action histories remain logs instead of becoming persistent, experience-derived state.",
     "Embodied agents accumulate experience far faster than they can write it back as persistent state: action histories remain logs."),
    ("(McNemar $p{=}2\\times10^{-6}$; the 0/20 is an existence verification built into the closed-book task design, not an independent statistical finding)",
     "(McNemar $p{=}2\\times10^{-6}$; the 0/20 is a closed-book design's built-in existence verification)"),
    ("A dedicated context-removal control experiment establishes that persistence itself is causally operative: after graph reset, goal resumption drops from 10/10 to 0/10 (exact McNemar $p{=}0.00195$, the minimum attainable at $n{=}10$, evidencing directional consistency only)",
     "A context-removal control experiment establishes that persistence itself is causally operative: after graph reset, goal resumption drops from 10/10 to 0/10 (exact McNemar $p{=}0.00195$, the minimum attainable at $n{=}10$)"),
    ("(508 archived runs, plus 390 repair/confounded runs archived separately) measures the trade-off directly",
     "(508 archived runs; 390 repair runs archived separately) measures the trade-off directly"),
    ("(with longer, failure-containing experience streams the baselines catch up at 10/10)",
     "(longer, failure-containing streams: baselines catch up at 10/10)"),
]
ZH_EDITS = [
    ("具身智能体积累经历的速度远快于把经历写回为持久状态的速度：行动史停留为日志，而未成为持久的经验派生状态。",
     "具身智能体积累经历的速度远快于把经历写回为持久状态的速度：行动史停留为日志。"),
    ("该 0/20 是闭卷门控下任务设计内置的存在性验证，非独立统计发现）",
     "该 0/20 是闭卷设计内置的存在性验证）"),
    ("一项专门的上下文移除对照实验确立该持久性本身对行为有因果作用",
     "一项上下文移除对照实验确立该持久性本身对行为有因果作用"),
    ("McNemar 精确 $p{=}0.00195$，为 $n{=}10$ 可得的极小 $p$，仅证方向一致）",
     "McNemar 精确 $p{=}0.00195$，为 $n{=}10$ 可得的极小 $p$）"),
    ("(508 run 正式归档,另有 390 run 修复/混淆批次单独归档)",
     "(508 run 正式归档;390 run 修复批单独归档)"),
]


def apply(f, edits):
    s = open(f, encoding='utf-8').read()
    for old, new in edits:
        assert old in s, (f, old[:60])
        s = s.replace(old, new)
    open(f, 'w', encoding='utf-8', newline='').write(s)
    print('updated', f)


apply('main.tex', EN_EDITS)
apply('peerj_main.tex', EN_EDITS)
apply('main_zh.tex', ZH_EDITS)

s = open('main.tex', encoding='utf-8').read()
m = re.search(r'(?s)\\begin\{abstract\}(.*?)\\end\{abstract\}', s)
ab = re.sub(r'\\[a-zA-Z]+|\$[^$]*\$|[{}~]', ' ', m.group(1))
words = [w for w in ab.split() if re.search(r'[A-Za-z0-9]', w)]
print('new EN abstract words:', len(words))
