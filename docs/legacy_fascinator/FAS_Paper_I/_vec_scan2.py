# -*- coding: utf-8 -*-
# _vec_scan2.py — 精确版向量级重叠扫描:
#   A. 文字外溢填充框(纯几何,阈值 1.5pt)
#   B. 线段真实穿过文字: 点到线段距离 < 1.2pt 且重叠长度 >= 40% 文字宽度或 >=3pt
#   C. 节点矩形互叠: 两个【带描边】填充路径 rect 互叠 >=25% 较小者
#   D. 文字 vs 文字: 已由 scan_overlaps.py 覆盖
import pymupdf

def pt_seg_dist(p, a, b):
    # 点到线段距离
    ax, ay = a.x, a.y; bx, by = b.x, b.y; px, py = p.x, p.y
    vx, vy = bx - ax, by - ay
    if vx == 0 and vy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * vx, ay + t * vy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def seg_rect_overlap(a, b, r):
    # 线段与矩形(平展): 覆盖比例 x 与 y
    ax, ay = a.x, a.y; bx, by = b.x, b.y
    # 线段参数化求与矩形的重叠区间
    vx, vy = bx - ax, by - ay
    if vx == 0 and vy == 0:
        return 0.0
    tus = []
    for v, lo, hi in ((vx, r.x0, r.x1), (vy, r.y0, r.y1)):
        if abs(v) < 1e-9:
            if not (lo <= (ax if v is vx else ay) <= hi):
                return 0.0
        else:
            t0, t1 = (lo - (ax if v is vx else ay)) / v, (hi - (ax if v is vx else ay)) / v
            tus.append((min(t0, t1), max(t0, t1)))
    t_start = max(tu[0] for tu in tus)
    t_end = min(tu[1] for tu in tus)
    if t_end <= t_start:
        return 0.0
    return (t_end - t_start) * ((vx ** 2 + vy ** 2) ** 0.5)


def main(pdf, verbose=False):
    doc = pymupdf.open(pdf)
    print("================ %s (%d pages) ================" % (pdf, doc.page_count))
    for pno in range(1, doc.page_count + 1):
        page = doc[pno - 1]
        words = page.get_text("words")
        draws = page.get_drawings()
        # 节点矩形(带描边); 纯填充(colorbox)单独存
        nodes, fills_only, segs = [], [], []
        for d in draws:
            has_stroke = d["type"] in ("s", "fs", "ss", "fss")
            has_fill = d["type"] in ("f", "fs", "ff", "fsf")
            if has_fill:
                (nodes if has_stroke else fills_only).append(d["rect"])
            for it in d["items"]:
                if it[0] == "l":
                    segs.append((it[1], it[2], max(0.4, d.get("width") or 0.4)))
        na = nb = nc = 0
        # A
        for r in nodes:
            for (x0, y0, x1, y1, w, *_) in words:
                wr = pymupdf.Rect(x0, y0, x1, y1)
                inter = r & wr
                if inter.is_empty or inter.get_area() <= 0:
                    continue
                if inter.get_area() / wr.get_area() < 0.30:
                    continue
                out = max(0, r.x0 - x0, x1 - r.x1, r.y0 - y0, y1 - r.y1)
                if out >= 1.5:
                    na += 1
                    if verbose:
                        print("  A p%d '%s' out of node(%.1f,%.1f,%.1f,%.1f) by %.1fpt"
                              % (pno, w, r.x0, r.y0, r.x1, r.y1, out))
        # B
        for (x0, y0, x1, y1, w, *_) in words:
            wr = pymupdf.Rect(x0, y0, x1, y1)
            for (a, b, lw) in segs:
                dist = min(pt_seg_dist(pymupdf.Point(x0, y0), a, b),
                           pt_seg_dist(pymupdf.Point(x1, y0), a, b),
                           pt_seg_dist(pymupdf.Point(x0, y1), a, b),
                           pt_seg_dist(pymupdf.Point(x1, y1), a, b),
                           pt_seg_dist(pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2), a, b))
                if dist > lw / 2 + 0.8:
                    continue
                ov = seg_rect_overlap(a, b, wr)
                if ov > 3.0 or ov > 0.35 * (x1 - x0):
                    nb += 1
                    if verbose:
                        print("  B p%d '%s'(%.1f,%.1f,%.1f,%.1f) crossed by seg(%.1f,%.1f)->(%.1f,%.1f) w=%.2f ov=%.1fpt"
                              % (pno, w, x0, y0, x1, y1, a.x, a.y, b.x, b.y, lw, ov))
                    break
        # C
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                inter = nodes[i] & nodes[j]
                if inter.is_empty:
                    continue
                amin = min(nodes[i].get_area(), nodes[j].get_area())
                if amin <= 0:
                    continue
                frac = inter.get_area() / amin
                if frac >= 0.25:
                    nc += 1
                    if verbose:
                        print("  C p%d nodes overlap %.0f%%: (%.1f,%.1f,%.1f,%.1f) x (%.1f,%.1f,%.1f,%.1f)"
                              % (pno, 100 * frac, nodes[i].x0, nodes[i].y0, nodes[i].x1, nodes[i].y1,
                                 nodes[j].x0, nodes[j].y0, nodes[j].x1, nodes[j].y1))
        tag = []
        if na: tag.append("A%d" % na)
        if nb: tag.append("B%d" % nb)
        if nc: tag.append("C%d" % nc)
        if tag or verbose:
            print("  p%-2d: %s" % (pno, " ".join(tag) if tag else "clean"))
    doc.close()


if __name__ == "__main__":
    import sys
    for pdf in sys.argv[1:]:
        main(pdf, verbose=True)