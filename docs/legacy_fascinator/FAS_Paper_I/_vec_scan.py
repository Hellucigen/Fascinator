# -*- coding: utf-8 -*-
# _vec_scan.py — 向量元素级重叠扫描(补文字框扫描器的盲区):
#   A. 文字外溢: 文字主体位于填充矩形内,但伸出版本框 >=1.5pt
#   B. 线划穿文字: 长度>=12pt 的描边线段与文字框 y-重叠 >=50%(标签浮在线上的正常排版不触发)
#   C. 填充矩形互叠: 两个填充路径 rect 相交 >=25% 较小者
#   D. 文字-文字 已由 scan_overlaps.py 覆盖,此处只做填充/描边相关
import sys
import pymupdf

THR = {
    "overflow_pt": 1.5,     # 文字伸出填充框的容忍量
    "line_len": 12.0,       # 线最短长度
    "line_yoverlap": 0.5,   # 线与文字 y 重叠比例
    "rect_area": 0.25,      # 填充矩形交叠阈值(较小者比例)
    "text_in_overlap": 0.40 # 文字与矩形相交面积比例(判断文字主体位置)
}


def main(pdf, pageno, debug=False):
    doc = pymupdf.open(pdf)
    page = doc[pageno - 1]
    words = page.get_text("words")  # x0,y0,x1,y1,word,... ; y 原点=顶部
    draws = page.get_drawings()
    fills, strokes = [], []
    for d in draws:
        rect = d["rect"]
        items = d["items"]
        if d["fill"] and d["fill"] != (0, 0, 0):
            fills.append(rect)
        for it in items:
            kind = it[0]
            if kind in ("l", "re", "qu", "c"):
                lw = max(0.5, d.get("width") or 0.5)
                if kind == "l":
                    r = pymupdf.Rect(it[1], it[2])
                    strokes.append((r, lw))
                elif kind == "c":
                    pts = it[1:]
                    xs = [p.x for p in pts]; ys = [p.y for p in pts]
                    strokes.append((pymupdf.Rect(min(xs), min(ys), max(xs), max(ys)), lw))
                elif kind == "re":
                    strokes.append((it[1], lw))
                elif kind == "qu":
                    strokes.append((it[1].rect, lw))
    # ---- A: 文字外溢 ----
    print("## A: text overflow beyond filled rects (page %d)" % pageno)
    na = 0
    for r in fills:
        for (x0, y0, x1, y1, w, *_) in words:
            wr = pymupdf.Rect(x0, y0, x1, y1)
            inter = r & wr
            if inter.is_empty or inter.get_area() <= 0:
                continue
            inter_frac = inter.get_area() / wr.get_area()
            if inter_frac < 0.30:
                continue  # 文字主体不在框内,不是"溢出"情形
            # 伸出部分
            out_l = max(0, r.x0 - x0); out_r = max(0, x1 - r.x1)
            out_t = max(0, r.y0 - y0); out_b = max(0, y1 - r.y1)
            overflow = max(out_l, out_r, out_t, out_b)
            if overflow >= THR["overflow_pt"]:
                na += 1
                print("  [%.0f%% in] '%s' box(%.1f,%.1f,%.1f,%.1f) sticks out of fill(%.1f,%.1f,%.1f,%.1f) by %.1fpt(%s)"
                      % (100 * inter_frac, w, x0, y0, x1, y1, r.x0, r.y0, r.x1, r.y1,
                         overflow, "r" if out_r >= THR["overflow_pt"] else
                         ("l" if out_l >= THR["overflow_pt"] else
                          ("b" if out_b >= THR["overflow_pt"] else "t"))))
    if na == 0:
        print("  (none)")
    # ---- B: 线划穿文字 ----
    print("## B: long stroke crossing text body (page %d)" % pageno)
    nb = 0
    for (x0, y0, x1, y1, w, *_) in words:
        wr = pymupdf.Rect(x0, y0, x1, y1)
        wh = y1 - y0
        if wh <= 0:
            continue
        for (r, lw) in strokes:
            if r.is_empty or max(r.width, r.height) < THR["line_len"]:
                continue
            inter = r & wr
            if inter.is_empty:
                continue
            yov = inter.height / wh
            xov = inter.width / (x1 - x0)
            # 线横穿文字中部: y 重叠大 或 线在文字带内水平贯穿
            if yov >= THR["line_yoverlap"] and xov >= 0.15:
                nb += 1
                print("  '%s'(%.1f,%.1f,%.1f,%.1f) crossed by line(%.1f,%.1f,%.1f,%.1f) w=%.2f  yov=%.2f xov=%.2f"
                      % (w, x0, y0, x1, y1, r.x0, r.y0, r.x1, r.y1, lw, yov, xov))
                break
    if nb == 0:
        print("  (none)")
    # ---- C: 填充矩形互叠 ----
    print("## C: filled rects overlapping (page %d)" % pageno)
    nc = 0
    for i in range(len(fills)):
        for j in range(i + 1, len(fills)):
            inter = fills[i] & fills[j]
            if inter.is_empty:
                continue
            amin = min(fills[i].get_area(), fills[j].get_area())
            if amin <= 0:
                continue
            frac = inter.get_area() / amin
            if frac >= THR["rect_area"]:
                nc += 1
                print("  fill(%.1f,%.1f,%.1f,%.1f) x fill(%.1f,%.1f,%.1f,%.1f)  overlap %.0f%% of smaller"
                      % (fills[i].x0, fills[i].y0, fills[i].x1, fills[i].y1,
                         fills[j].x0, fills[j].y0, fills[j].x1, fills[j].y1, 100 * frac))
    if nc == 0:
        print("  (none)")


for pdf in ("main.pdf", "main_zh.pdf"):
    doc = pymupdf.open(pdf)
    print("================ %s (%d pages) ================" % (pdf, doc.page_count))
    for pn in range(1, doc.page_count + 1):
        main(pdf, pn)
    doc.close()