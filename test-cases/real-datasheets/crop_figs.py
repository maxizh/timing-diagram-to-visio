#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从真实 datasheet PDF 里精确切出时序图。

切图边界不靠猜，两种确定性定位：
  1. frame  —— 图有外框：取页面上最大的那个矩形（图框本身就是矢量对象）
  2. band   —— 图没外框：用「上一张图注的底」到「本张图注的底」夹出来
"""
import os
import pymupdf
from PIL import Image, ImageChops

OUT = "figs"
os.makedirs(OUT, exist_ok=True)

def page_img(pdf, pg, dpi=400):
    p = pymupdf.open(pdf)[pg - 1]
    pix = p.get_pixmap(dpi=dpi)
    return p, Image.frombytes("RGB", (pix.width, pix.height), pix.samples), dpi / 72.0

def trim_white(im, pad=16):
    g = im.convert("L").point(lambda v: 0 if v < 246 else 255)
    bb = ImageChops.invert(g).getbbox()
    if not bb: return im
    l, t, r, b = bb
    return im.crop((max(0, l - pad), max(0, t - pad),
                    min(im.width, r + pad), min(im.height, b + pad)))

def cut(pdf, pg, out, y0_pt, y1_pt, xf=(0.045, 0.955), dpi=400):
    p, im, s = page_img(pdf, pg, dpi)
    W, H = im.size
    im = im.crop((int(W * xf[0]), int(y0_pt * s), int(W * xf[1]), min(H, int(y1_pt * s))))
    im = trim_white(im)
    im.save(os.path.join(OUT, out), dpi=(dpi, dpi))
    print(f"  {out:<36} {im.size[0]}x{im.size[1]}")

def frame(pdf, pg, out, **kw):
    """取页面上最大的矩形 = 图框。"""
    p = pymupdf.open(pdf)[pg - 1]
    rects = [d["rect"] for d in p.get_drawings()]
    big = [r for r in rects if r.width > p.rect.width * 0.5 and r.height > 80]
    if not big:
        raise SystemExit(f"{pdf} p{pg} 没找到图框")
    r = max(big, key=lambda r: r.width * r.height)
    cut(pdf, pg, out, r.y0 - 4, r.y1 + 4, **kw)

def band(pdf, pg, out, caption, prev=None, head=None, top=34.0, **kw):
    """用图注夹：上边界 = 上一张图注底（或小节标题底），下边界 = 本张图注底。
    两个锚点都找不到时退回 `top`（点），默认 34 —— 正好在页眉横线之下。"""
    p = pymupdf.open(pdf)[pg - 1]
    c = p.search_for(caption)
    if not c: raise SystemExit(f"{pdf} p{pg} 找不到图注 {caption!r}")
    y0 = top
    if prev:
        pr = p.search_for(prev)
        if pr: y0 = pr[0].y1 + 6
    elif head:
        h = p.search_for(head)
        if h: y0 = h[0].y1 + 6
    cut(pdf, pg, out, y0, c[0].y1 + 10, **kw)

print("AD7606 (ADI · 8ch 16bit ADC)")
band("dl/ad7606.pdf", 9, "ad7606-fig2-convst-after.png",  "Figure 2.", head="Timing Diagrams")
band("dl/ad7606.pdf", 9, "ad7606-fig4-parallel-cs-rd.png", "Figure 4.", prev="Figure 3.")
print("ADS8482 (TI · 18bit 1MSPS ADC)")
band("dl/ads8482.pdf", 17, "ads8482-fig33-auto-read.png", "Figure 33.", head="TIMING CHARACTERISTICS")
print("ISSI IS42S16400J (SDR SDRAM)")
frame("dl/issi_sdr.pdf", 54, "issi-sdr-alternating-bank-write.png")
frame("dl/issi_sdr.pdf", 55, "issi-sdr-write-page-burst.png")
frame("dl/issi_sdr.pdf", 48, "issi-sdr-p48.png")
