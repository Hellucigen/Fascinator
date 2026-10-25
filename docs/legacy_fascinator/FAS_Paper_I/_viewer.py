# -*- coding: utf-8 -*-
# _viewer.py — 渲染 PDF 指定区域,按字符密度输出 ASCII 位图,便于人工判读几何关系。
# 用法: python _viewer.py <pdf> <page> <x0> <y0> <x1> <y1> [chars/width]
import subprocess
import sys
from PIL import Image

PDFTOPPNM = "E:/LaTeX/MiKTeX/texmfs/install/miktex/bin/x64/pdftoppm.exe"
ENV = os_env = subprocess.check_output("echo %PATH%", shell=True).decode("gbk", "replace") or ""


def main(pdf, page, x0, y0, x1, y1, cw=140, dpi=300):
    pad = 0
    wpt, hpt = x1 - x0, y1 - y0
    px = int(x0 * dpi / 72); py = int(y0 * dpi / 72)
    pw = int(wpt * dpi / 72); ph = int(hpt * dpi / 72)
    out = "_view_tmp"
    subprocess.run([PDFTOPPNM, "-f", str(page), "-l", str(page), "-r", str(dpi),
                    "-x", str(px), "-y", str(py), "-W", str(pw), "-H", str(ph),
                    "-png", "-singlefile", pdf, out], env=ENV if False else None, check=True)
    im = Image.open(out + ".png").convert("L")
    W, H = im.size
    ch = int(H / (W / cw * 2))  # 2:1 字符纵横比
    sx, sy = W // cw, H // ch
    if sx < 1: sx = 1
    if sy < 1: sy = 1
    def shade(cnt):
        tot = sx * sy
        if cnt == 0: return " "
        r = cnt / tot
        return "." if r < 0.10 else ("o" if r < 0.35 else ("#" if r < 0.65 else "@"))
    print("# %s p%s x%.0f..%.0f y%.0f..%.0f  (%d x %d chars; %s px/char)" %
          (pdf, page, x0, x1, y0, y1, cw, ch, sx))
    for by in range(ch):
        line = []
        for bx in range(cw):
            xa, xb = bx * sx, min((bx + 1) * sx, W)
            ya, yb = by * sy, min((by + 1) * sy, H)
            cnt = 0
            pix = im.load()
            for yy in range(ya, yb):
                for xx in range(xa, xb):
                    if pix[xx, yy] < 128:
                        cnt += 1
            line.append(shade(cnt))
        print("".join(line))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    pdf, pg, x0, y0, x1, y1 = args[0], int(args[1]), float(args[2]), float(args[3]), float(args[4]), float(args[5])
    cw = int(args[6]) if len(args) > 6 else 140
    main(pdf, pg, x0, y0, x1, y1, cw)