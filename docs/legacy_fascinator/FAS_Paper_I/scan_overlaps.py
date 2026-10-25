# -*- coding: utf-8 -*-
# scan_overlaps.py — glyph-level collision scan (namespace-agnostic)
# rule: x-overlap >= 0.45 * min(x-width) AND y-overlap >= 0.45 * min(y-height)
import sys
import xml.etree.ElementTree as ET


def local(el):
    return el.tag.rsplit("}", 1)[-1]


def load_words(path):
    tree = ET.parse(path)
    pages = []
    for page in tree.getroot().iter():
        if local(page) != "page":
            continue
        words = []
        for w in page.iter():
            if local(w) != "word":
                continue
            txt = (w.text or "").strip()
            if not txt:
                continue
            words.append((float(w.get("xMin")), float(w.get("yMin")),
                          float(w.get("xMax")), float(w.get("yMax")), txt))
        pages.append(words)
    return pages


def scan(words, thr=0.45):
    n = len(words)
    hits = []
    for i in range(n):
        ax0, ay0, ax1, ay1, t1 = words[i]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1, t2 = words[j]
            xo = min(ax1, bx1) - max(ax0, bx0)
            yo = min(ay1, by1) - max(ay0, by0)
            if xo <= 0 or yo <= 0:
                continue
            wmin = min(ax1 - ax0, bx1 - bx0)
            hmin = min(ay1 - ay0, by1 - by0)
            if wmin <= 0 or hmin <= 0:
                continue
            if xo >= thr * wmin and yo >= thr * hmin:
                hits.append((round(xo, 1), round(yo, 1),
                             round(xo / wmin, 2), round(yo / hmin, 2), t1, t2))
    return hits


for path in sys.argv[1:]:
    pages = load_words(path)
    print("== %s : %d pages" % (path, len(pages)))
    total = 0
    for pno, words in enumerate(pages, 1):
        hits = scan(words)
        if hits:
            total += len(hits)
            print("  page %d: %d hit(s)" % (pno, len(hits)))
            for h in hits[:12]:
                print("    xo=%.1fpt yo=%.1fpt (%.2f, %.2f) | %r <-> %r" % h)
    print("  TOTAL (glyph-level >= 0.45x0.45): %d" % total)