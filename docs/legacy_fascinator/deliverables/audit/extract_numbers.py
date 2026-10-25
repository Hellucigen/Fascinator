# -*- coding: utf-8 -*-
# extract_numbers.py — 数字差异审计:从 LaTeX 源提取全部数值 token(带上下文)。
# 用法: python extract_numbers.py <file.tex> <out.json>
# 规则: 去注释 -> 去命令名/标签 -> 正则提取数值(含千分位、小数、负号、指数),
#       保留前 28 字符上下文供人工分类。仅做纯词法提取,不做任何解释。
import json
import re
import sys

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?")


def strip_comments(s):
    out = []
    for line in s.split("\n"):
        # 去掉非转义 % 之后内容
        i = 0
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                break
            i += 1
        out.append(line[:i] if i < len(line) else line)
    return "\n".join(out)


def extract(path):
    src = open(path, encoding="utf-8").read()
    src = strip_comments(src)
    # 去掉命令名与其后的非数字参数首字母占位干扰:把 \command 保留为空格
    src = re.sub(r"\\[A-Za-z@]+\*?", " ", src)
    nums = []
    for m in NUM.finditer(src):
        tok = m.group(0)
        ctx = src[max(0, m.start() - 28):m.start()].replace("\n", " ")
        nums.append({"v": tok, "ctx": ctx[-28:]})
    return nums


def main():
    path, out = sys.argv[1], sys.argv[2]
    nums = extract(path)
    json.dump({"file": path, "n": len(nums), "numbers": nums},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%s -> %d numeric tokens" % (path, len(nums)))


if __name__ == "__main__":
    main()
