# -*- coding: utf-8 -*-
# compare_numbers.py — 对比两份数字清单,输出差异(新增/消失/计数变化)。
# 用法: python compare_numbers.py <old.json> <new.json> <report.md>
import json
import sys
from collections import Counter


def load(p):
    d = json.load(open(p, encoding="utf-8"))
    return [x["v"] for x in d["numbers"]], d


def norm(v):
    # 千分位统一去掉逗号,便于 34,016 == 34016
    return v.replace(",", "")


def main():
    oldp, newp, outp = sys.argv[1], sys.argv[2], sys.argv[3]
    oldv, oldd = load(oldp)
    newv, newd = load(newp)
    oc = Counter(norm(v) for v in oldv)
    nc = Counter(norm(v) for v in newv)
    removed = oc - nc
    added = nc - oc
    lines = ["# 数字差异审计", "",
             "- 旧版: %s (%d tokens)" % (oldp, len(oldv)),
             "- 新版: %s (%d tokens)" % (newp, len(newv)), ""]
    lines.append("## 消失(旧有新无) %d 种 / %d 处" % (len(removed), sum(removed.values())))
    for v, c in sorted(removed.items(), key=lambda x: -x[1]):
        ctxs = [x["ctx"] for x in oldd["numbers"] if norm(x["v"]) == v][:6]
        lines.append("- `%s` ×%d | 旧上下文: %s" % (v, c, " || ".join(ctxs)))
    lines.append("")
    lines.append("## 新增(新有旧无) %d 种 / %d 处" % (len(added), sum(added.values())))
    for v, c in sorted(added.items(), key=lambda x: -x[1]):
        ctxs = [x["ctx"] for x in newd["numbers"] if norm(x["v"]) == v][:6]
        lines.append("- `%s` ×%d | 新上下文: %s" % (v, c, " || ".join(ctxs)))
    open(outp, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("report -> %s (removed %d kinds, added %d kinds)"
          % (outp, len(removed), len(added)))


if __name__ == "__main__":
    main()
