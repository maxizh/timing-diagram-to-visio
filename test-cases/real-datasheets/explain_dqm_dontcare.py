#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 dqm-dontcare.html —— 「驼峰到底是什么」的图解（单文件，图片 base64 内嵌）。

起因：ISSI p54 的 DQM 行里，除了那块盖满两个整槽的大灰带，还在**每个时钟沿上**
画了一个窄灰梯形（我叫它「驼峰」）。要回答的是：**驼峰该不该让输出变成 `x`？**

本页摆三样东西对质：

  ① 大灰带 —— 覆盖整槽              → 真 DON'T CARE（输出 xx）
  ② 驼峰   —— 半槽宽、压在时钟沿上   → tCMS/tCMH 的建立/保持窗，不是逻辑值
  ③ CKE 行 —— 同一套画法，但它在这张图里**显然恒高**（没有 clock suspend）
               → 最硬的反证：驼峰不能被当成「值不确定」

顺带看清了这套画法的语义（有 CKE 做对照才敢下结论）：
**灰梯形 = 「这个窗口里信号可能跑到对面轨去」，那条横贯全图的线才是真实电平。**
CKE 线在高轨、梯形朝**下**挂；DQM 线在低轨、梯形朝**上**凸 —— 同一个意思。

排版约定（都是踩出来的）：
  · 面板分三段：**原图 / 标注带 / 输出条**。标注一律放在图下方白带里，
    用引线指上去 —— 压在原图上会把要看的东西挡住；
  · 字号必须按「面板宽度 / 参考宽度」缩放，否则窄面板里的字会被放得特别大；
  · T 标号放图顶、占位最小。

输出落在 skill 库之外（要内嵌厂商图）。用法：python3 explain_dqm_dontcare.py
"""
import base64
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, ".workbuddy", "skills", "wave2visio", "scripts"))

import pymupdf                                              # noqa: E402
import pdf_trace as pt                                      # noqa: E402
import auto_trace as at                                     # noqa: E402
import numpy as np                                          # noqa: E402

PAGE = 54
DPI = 600
REF_W = 220.0        # 字号参考宽度（pt）：面板越宽字号同比放大，视觉大小才一致


class Geo:
    """一次性把要用的几何都算好：行带 / 位网格 / 灰底列 / 电平线 / 灰底顶端。"""

    def __init__(self, pdf):
        self.pdf = pdf
        self.res, _ = pt.analyse(pdf, PAGE)
        g = self.res["grid"]
        self.n, self.pitch = g["n"], g["pitch"]
        self.centers, self.bounds = g["centers"], g["bounds"]
        self.scale = DPI / 72.0
        png, _ = pt.render_page(pdf, PAGE, dpi=DPI)
        gray, dark = at.load_dark(png)
        d2 = at.long_run_mask(dark, max(12, gray.shape[1] // 60))
        self.gray, self.dark = gray, d2
        self.plot_l, self.plot_r = at.wave_span(d2)
        row_px = pt._median(np.diff(sorted(r["y_center"] for r in self.res["rows"]))) * self.scale
        self.half = max(4, int(row_px * 0.45))

    def band(self, name):
        yc = next(r for r in self.res["rows"] if r["name"].startswith(name))["y_center"]
        yc *= self.scale
        return int(yc - self.half), int(yc + self.half)

    def dc_cols(self, name):
        y0, y1 = self.band(name)
        return pt._dontcare_cols(self.gray, y0, y1, self.plot_l, self.plot_r)

    def level_line(self, name):
        y0, y1 = self.band(name)
        sub = self.dark[y0:y1 + 1, self.plot_l:self.plot_r + 1]
        return (y0 + int(sub.sum(axis=1).argmax())) / self.scale

    def gray_top(self, name):
        y0, y1 = self.band(name)
        b = self.gray[y0:y1 + 1, self.plot_l:self.plot_r + 1]
        isg = (b > pt.DARK) & (b < 0.92)
        tops = [np.where(isg[:, i])[0][0] for i in range(isg.shape[1]) if isg[:, i].any()]
        return (y0 + (int(np.median(tops)) if tops else 0)) / self.scale

    def slot_frac(self, name, k):
        dc = self.dc_cols(name)
        a = int(round((self.centers[k] - self.pitch / 2) * self.scale - self.plot_l))
        b = int(round((self.centers[k] + self.pitch / 2) * self.scale - self.plot_l))
        return float(dc[max(0, a):max(1, b)].mean())

    def hump_at(self, name, x, above=True, win=20.0):
        """量 x(pt) 附近 win(pt) 内的「驼峰」：灰底伸出电平线之外的连续列。

        above=True → 灰底跑到电平线**上方**（DQM 线在低轨、梯形朝上凸）；
        above=False → 灰底挂到电平线**下方**（CKE 线在高轨、梯形朝下挂）。
        返回 (起, 止, 中心, 底宽) 或 None。**不用「猜边上有没有梯形」** —— 量的。
        """
        y0, y1 = self.band(name)
        line = self.level_line(name)
        b = self.gray[y0:y1 + 1, :]
        isg = (b > pt.DARK) & (b < 0.92)
        lp = line * self.scale - y0                 # 电平线在行带内的行号
        th = 3.0 * self.scale                       # 至少伸出 3pt 才算
        cols = []
        for c in range(int((x - win) * self.scale), int((x + win) * self.scale)):
            w = np.where(isg[:, c])[0]
            if not w.size:
                continue
            if (w[0] < lp - th) if above else (w[-1] > lp + th):
                cols.append(c)
        if len(cols) < 20:
            return None
        return (round(cols[0] / self.scale, 1), round(cols[-1] / self.scale, 1),
                round((cols[0] + cols[-1]) / 2 / self.scale, 1),
                round((cols[-1] - cols[0]) / self.scale, 1))

    def humps(self, name, above=True):
        """逐条位槽边界找驼峰，只留下「半槽宽、且确实压在边界上」的那些。

        挡掉两类假阳性：
          · 大灰带（盖满整槽，底宽 ≈ 一个整周期）——DQM 头两槽就是它；
          · 行标签文字/标注线（会让量出的中心偏离边界好几 pt）。
        """
        out = []
        for b in self.bounds:
            h = self.hump_at(name, b, above=above)
            if not h:
                continue
            if not (self.pitch * 0.42 <= h[3] <= self.pitch * 0.78):   # 半个周期左右
                continue
            if abs(h[2] - b) > 6.0:                                    # 中心要压在边界上
                continue
            out.append((b, h[2], h[3]))
        return out

    def crop(self, x0, y0, x1, y1):
        doc = pymupdf.open(self.pdf)
        pm = doc[PAGE - 1].get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY,
                                      clip=pymupdf.Rect(x0, y0, x1, y1))
        return "data:image/png;base64," + base64.b64encode(pm.tobytes("png")).decode()


# ------------------------------------------------------- SVG 小工具（fs = 字号缩放）
def _tw(s, size):
    """粗估文字宽度（pt）：CJK 按 1.0×字号，拉丁按 0.55×。"""
    return size * sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in s)


def txt(x, y, s, size, fill="#111", anchor="middle", weight="700"):
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}" '
            f'font-family="PingFang SC,Helvetica,sans-serif">{s}</text>')


def chip(x, y, s, size, fill="#111", anchor="middle", bg="#ffffff", op=0.95):
    """带底色的标签（放白带上，所以底色纯白即可）。"""
    w = _tw(s, size)
    x0 = x - w / 2 - size * 0.35 if anchor == "middle" else x - size * 0.35
    return (f'<rect x="{x0:.2f}" y="{y - size * 0.95:.2f}" width="{w + size * 0.7:.2f}" '
            f'height="{size * 1.3:.2f}" rx="{size * 0.28:.2f}" fill="{bg}" fill-opacity="{op}"/>'
            + txt(x, y, s, size, fill, anchor))


def vline(x, y0, y1, color="#2563eb", w=1.0, dash=None, op=1.0):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x:.2f}" y1="{y0:.2f}" x2="{x:.2f}" y2="{y1:.2f}" '
            f'stroke="{color}" stroke-width="{w:.2f}" opacity="{op}"{d}/>')


def hline(y, x0, x1, color="#2563eb", w=1.0, dash=None, op=1.0):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x0:.2f}" y1="{y:.2f}" x2="{x1:.2f}" y2="{y:.2f}" '
            f'stroke="{color}" stroke-width="{w:.2f}" opacity="{op}"{d}/>')


def box(x0, y0, x1, y1, color="#dc2626", w=1.0, fill="none", rx=1.0, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" '
            f'rx="{rx}" fill="{fill}" stroke="{color}" stroke-width="{w:.2f}"{d}/>')


def dot(x, y, r, color):
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{color}"/>'


def leader(x0, y0, x1, y1, color="#b91c1c", w=1.0, dash=None, op=1.0):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" '
            f'stroke="{color}" stroke-width="{w:.2f}" opacity="{op}"{d}/>')


# ---------------------------------------------------------------- 面板
def panel(g, x0, y0, x1, y1, wave, labels, caption, extra=None):
    """三段式面板：原图（含槽线） / 标注带（引线指上去） / 输出波形条。

    labels = [(文字, 颜色, 引线目标 x, 引线目标 y, 标签在面板内的 x)]，坐标都是绝对 pt。
    """
    W, Hc = x1 - x0, y1 - y0
    fs = W / REF_W
    LH = 10.5 * fs          # 标注带高
    SH = 9.5 * fs           # 输出条高
    H = Hc + LH + SH

    o = [f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
         f'<image href="{g.crop(x0, y0, x1, y1)}" x="0" y="0" '
         f'width="{W}" height="{Hc}" preserveAspectRatio="none"/>']

    # 位槽边界（细实线）、位槽中心（虚线 + T 标号）
    for b in g.bounds:
        if x0 - 1 <= b <= x1 + 1:
            o.append(vline(b - x0, 0, Hc, "#2563eb", 0.5 * fs, op=0.40))
    for i, c in enumerate(g.centers):
        if x0 <= c <= x1:
            o.append(vline(c - x0, 0, Hc, "#2563eb", 0.5 * fs,
                           f"{2.2 * fs} {2.0 * fs}", 0.35))
            o.append(txt(c - x0, 6.0 * fs, f"T{i}", 5.2 * fs, "#2563eb"))
    if extra:
        o.append(extra(x0, y0, x1, y1, fs))

    # 标注带：引线从标签顶拉到目标点（斜线，一眼看出指向哪个特征）
    for s, col, tx, ty, lx in labels:
        y = ty - y0
        o.append(leader(lx, Hc, tx, y, col, 0.5 * fs, f"{2.4 * fs} {2.0 * fs}", 0.75))
        o.append(dot(tx, y, 1.1 * fs, col))
        o.append(chip(lx, Hc + LH * 0.68, s, 5.6 * fs, col))

    # 输出波形条：每个槽两个字符格
    cw = g.pitch / 2
    sy = Hc + LH
    for k in range(g.n):
        if not (x0 <= g.centers[k] <= x1):
            continue
        a = g.centers[k] - g.pitch / 2
        for j in range(2):
            ch = wave[k * 2 + j]
            red = ch == "x"
            bx = a + j * cw - x0
            o.append(box(bx + 0.5, sy + 0.8 * fs, bx + cw - 0.5, sy + SH - 0.8 * fs,
                         "#dc2626" if red else "#059669", 0.9 * fs,
                         "#fee2e2" if red else "#d1fae5", 0.7 * fs))
            o.append(txt(bx + cw / 2, sy + SH - 2.6 * fs, ch, 5.0 * fs,
                         "#b91c1c" if red else "#065f46"))
    return (f'<figure><figcaption>{caption}</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" width="100%" '
            f'style="display:block;background:#fff;border-radius:8px">'
            f'{"".join(o)}</svg></figure>')


def main():
    pdf = os.path.abspath(os.path.join(HERE, "dl", "issi_sdr.pdf"))
    if not os.path.exists(pdf):
        raise SystemExit(f"找不到 {pdf}")

    g = Geo(pdf)
    dqm_line, dqm_top = g.level_line("DQM"), g.gray_top("DQM")
    cke_line = g.level_line("CKE")
    dqm_wave = "xxxx" + "00" * 8
    frac = [g.slot_frac("DQM", k) for k in range(g.n)]
    BAND = (95.03, 191.0)                     # 实测大灰带横向范围（盖满槽 0/1）
    hun_dqm = g.humps("DQM", above=True)      # 实测：DQM 的驼峰在哪
    hun_cke = g.humps("CKE", above=False)     # 实测：CKE 的驼峰在哪
    hun = [b for b, _, _ in hun_dqm]
    # 底宽用中位数：bounds[3] 那个和灰带尾巴粘在一起，量出来 31pt，是假宽
    wmed = float(np.median([w for _, _, w in hun_dqm]))

    print(f"DQM：电平线 {dqm_line:.1f}pt（低轨）  灰底顶端 {dqm_top:.1f}pt（= 高轨）")
    print(f"CKE：电平线 {cke_line:.1f}pt（高轨）")
    print("DQM 逐槽灰底占比:", " ".join(f"{f:.2f}" for f in frac))
    print(f"DQM 驼峰 {len(hun_dqm)} 个（底宽 ≡ 半周期 {g.pitch / 2:.1f}pt）:")
    for b, c, w in hun_dqm:
        print(f"    边沿 {b:7.2f}  中心 {c:7.2f}（偏离 {c - b:+.1f}）  底宽 {w}")
    print(f"CKE 驼峰 {len(hun_cke)} 个，逐个对齐 DQM：",
          all(any(abs(b - b2) < 1.0 for b2, _, _ in hun_cke) for b, _, _ in hun_dqm))
    print("    边沿:", [b for b, _, _ in hun_cke])

    def ov_dqm(x0, y0, x1, y1, fs):
        """DQM 行：红框圈出大灰带 + 每条驼峰的边沿一条红虚线。"""
        o = [box(BAND[0] - x0, dqm_top - 1.5 - y0, BAND[1] - x0, dqm_line + 1.5 - y0,
                 "#dc2626", 1.2 * fs, "none", 1.2 * fs, f"{4 * fs} {2.4 * fs}")]
        o += [vline(b - x0, dqm_top - 4 - y0, dqm_line + 2 - y0, "#b91c1c",
                    1.0 * fs, f"{3.2 * fs} {2.0 * fs}", 0.95)
              for b in hun if x0 + 2 < b < x1 - 2]
        return "".join(o)

    def ov_cke(x0, y0, x1, y1, fs):
        """CKE 行：绿虚线标出电平线（高轨）+ 它自己的驼峰边沿，便于和 DQM 逐条对齐。"""
        o = [hline(cke_line - y0, 0, x1 - x0, "#16a34a", 1.0 * fs,
                   f"{4 * fs} {2.4 * fs}", 0.9)]
        o += [vline(b - x0, 0, y1 - y0, "#15803d",
                    0.9 * fs, f"{3.0 * fs} {2.2 * fs}", 0.85)
              for b, _, _ in hun_cke if x0 + 2 < b < x1 - 2]
        return "".join(o)

    AX0, AX1 = 88, 400          # 面板 A（C 同宽）
    BX0, BX1 = 400, 560         # 面板 B
    bA = hun[0]                                              # A 里指第一个驼峰
    mid = [b for b, _, _ in hun_dqm if BX0 < b < BX1]
    bB = mid[min(1, len(mid) - 1)]                           # B 里指中间那个

    pA = panel(g, AX0, 196, AX1, 234, dqm_wave,
               [("大灰带：盖满整槽 → x", "#b91c1c", (BAND[0] + BAND[1]) / 2 - AX0,
                 dqm_line, (BAND[0] + BAND[1]) / 2 - AX0 - 15),
                (f"驼峰：{wmed:.0f}pt＝半周期，压在时钟沿上",
                 "#b91c1c", bA - AX0, dqm_top - 1, 168)],
               "<b>左边：两种灰同框</b> —— 红框里那块<b>盖满整槽</b>的灰带是「逻辑 DON'T CARE」；"
               "右边红虚线的<b>窄梯形（驼峰）</b>不是。下面的输出条（红= x，绿= 0）就是按这个判据出来的。",
               extra=ov_dqm)

    pB = panel(g, BX0, 196, BX1, 234, dqm_wave,
               [("每个时钟沿一个，一个不多一个不少 →", "#b91c1c", bB - BX0, dqm_top - 1, 60)],
               "<b>右边</b> —— 同样的驼峰一路排下去，<b>每个时钟沿一个</b>。"
               "若把驼峰当 DON'T CARE，DQM 后半段就会变成一长串 x。",
               extra=ov_dqm)

    pC = panel(g, AX0, 142, AX1, 180, "1" * (2 * g.n),
               [(f"CKE 的驼峰：{len(hun_cke)} 个，位置和 DQM 逐条重合",
                 "#15803d", hun_cke[3][0] - AX0, cke_line, 150)],
               "<b>对照：CKE 行是同一套画法</b> —— 一条电平线 + 每周期一个灰梯形（绿虚线标出的就是它们）。"
               "但 CKE 在这张图里<b>恒高</b>（普通写操作，没有 clock suspend）。"
               "所以灰梯形不可能表示「值不确定」—— 真那样的话 CKE 也该是 x。",
               extra=ov_cke)

    tr = []
    for k in range(g.n):
        isx = frac[k] >= pt.DC_SLOT
        tr.append(f'<tr class="{"x" if isx else ""}"><td>T{k}</td><td>{frac[k]:.2f}</td>'
                  f'<td>{"灰底盖满整槽 → 值不确定" if isx else "灰底只有零头 → 取电平线的值（低）"}</td>'
                  f'<td class="wv">{dqm_wave[k * 2]}{dqm_wave[k * 2 + 1]}</td></tr>')

    html = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>DQM 的「驼峰」到底是什么 · ISSI p54</title>
<style>
  :root {{ --bg:#0f1115; --fg:#e6e8ee; --dim:#98a2b3; --line:#2a2f3a; --acc:#7cc4ff;
           --red:#f87171; --grn:#4ade80; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:30px 26px 70px; background:var(--bg); color:var(--fg);
         font:15px/1.75 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif; }}
  h1 {{ font-size:23px; margin:0 0 8px; }}
  h2 {{ font-size:16px; margin:34px 0 10px; }}
  .lead {{ color:var(--dim); max-width:1060px; margin:0 0 12px; }}
  .lead b, p b {{ color:var(--fg); }}
  figure {{ margin:0 0 14px; background:#fff; border:1px solid var(--line);
            border-radius:12px; padding:10px; }}
  figcaption {{ color:#475467; font-size:13px; margin:2px 0 10px; }}
  figcaption b {{ color:#111827; }}
  .q {{ border-left:3px solid var(--acc); padding:8px 0 8px 14px; margin:14px 0 24px;
        color:var(--dim); max-width:1060px; }}
  .q b {{ color:var(--fg); }}
  .key {{ display:flex; gap:20px; flex-wrap:wrap; color:var(--dim); font-size:13px;
          max-width:1060px; margin:0 0 24px; }}
  .sw {{ display:inline-block; width:11px; height:11px; border-radius:3px;
         margin-right:6px; vertical-align:-1px; }}
  table {{ border-collapse:collapse; width:100%; max-width:1060px; font-size:13.5px; }}
  th, td {{ border:1px solid var(--line); padding:6px 10px; text-align:left; }}
  th {{ background:#171b23; color:#fff; }}
  tr.x td {{ background:#2a1a1c; }}
  tr.x td:nth-child(3) {{ color:var(--red); }}
  td.wv {{ font-family:ui-monospace,Menlo,monospace; letter-spacing:1px; }}
  .concl {{ margin-top:26px; padding:16px 18px; border:1px solid #1f6f4a;
            background:#0f1f18; border-radius:12px; max-width:1060px; }}
  .concl h2 {{ margin:0 0 8px; color:var(--grn); }}
  .concl b {{ color:#fff; }}
  code {{ background:#1b2028; padding:1px 6px; border-radius:5px; color:var(--acc); }}
  footer {{ color:var(--dim); font-size:12.5px; margin-top:26px; }}
</style>

<h1>DQM 的「驼峰」到底是什么 —— ISSI IS42S16400J p54</h1>
<p class="lead">
  我把 DQM 那一行放大标出来了。<b>「驼峰」= 那一排窄窄的、顶平的灰梯形</b>
  （图里红虚线标出的就是它们的中心）。它和左边那块盖满两个整槽的大灰带
  <b>不是同一种东西</b>。
</p>
<div class="q">
  <b>为什么这事要紧：</b>如果驼峰也算 DON'T CARE，DQM 就会从
  <code>{dqm_wave}</code> 变成一长串 <code>x</code>。所以得先弄清它到底是不是「值不确定」。
</div>
<div class="key">
  <span><i class="sw" style="background:#2563eb"></i>蓝实线 = 位槽边界（两条 T 线中点）</span>
  <span><i class="sw" style="background:repeating-linear-gradient(90deg,#2563eb 0 3px,transparent 3px 5px)"></i>蓝虚线 + T0..T9 = 厂商自己的标号竖线 = 时钟<b>上升沿</b></span>
  <span><i class="sw" style="background:#dc2626"></i>红虚线 = 驼峰中心 = 时钟<b>下降沿</b></span>
  <span><i class="sw" style="background:repeating-linear-gradient(90deg,#dc2626 0 3px,transparent 3px 5px)"></i>红框 = 大灰带</span>
  <span><i class="sw" style="background:#16a34a"></i>绿虚线 = CKE 的驼峰边沿</span>
  <span><i class="sw" style="background:#d1fae5;border:1px solid #059669"></i>绿格 = 输出 0/1</span>
  <span><i class="sw" style="background:#fee2e2;border:1px solid #dc2626"></i>红格 = 输出 x</span>
</div>

{pA}

{pB}

{pC}

<h2>上面那几条，都是量出来的</h2>
<p class="lead">
  这张图里「时钟沿落在哪、驼峰压在哪」很容易看错（我上一轮就说错过一次），所以下面这几条全部按像素/矢量量过：
</p>
<table>
  <thead><tr><th>量什么</th><th>结果</th><th>怎么量的</th></tr></thead>
  <tbody>
    <tr><td>CLK 占空比与边沿</td>
        <td>50%（每段 {g.pitch / 2:.1f}pt）· 上升沿在 <b>厂商 T 竖线上</b>，下降沿在<b>两条 T 线中点</b></td>
        <td>按高/低两条电平轨逐列判电平，再压成连续段</td></tr>
    <tr><td>驼峰底宽</td>
        <td><b>{wmed:.1f}pt ≡ 半个周期</b>（{g.pitch / 2:.1f}pt）</td>
        <td>灰底伸出电平线之外的连续列，量其宽度（取中位数；与灰带粘连那个量出 31pt，是假宽）</td></tr>
    <tr><td>驼峰个数与位置</td>
        <td>DQM <b>{len(hun_dqm)} 个</b>（压在 {', '.join(f'{b:.0f}' for b, _, _ in hun_dqm[:3])} … 上）·
            CKE <b>{len(hun_cke)} 个</b>，两行 x <b>逐条重合</b></td>
        <td>逐条位槽边界开一个 ±20pt 的窗口去找，中心偏离边界 &gt; 6pt 的丢掉</td></tr>
    <tr><td>大灰带 vs 驼峰</td>
        <td>逐槽灰底占比 <b>{frac[0]:.2f} / {frac[1]:.2f}</b> 对 <b>{min(frac[2:]):.2f}~{max(frac[2:]):.2f}</b></td>
        <td>每个位槽内灰底列占比（阈值 <code>{pt.DC_SLOT}</code>）</td></tr>
    <tr><td>旁边标的字</td>
        <td>COMMAND 行上下写着 <code>tCMS</code>/<code>tCMH</code>，地址行写着 <code>tAS</code>/<code>tAH</code></td>
        <td>PDF 文本层（y≈173 / 202 / 232 …）</td></tr>
  </tbody>
</table>
<p class="lead" style="margin-top:10px">
  <b>更正一下我上一轮的说法：</b>当时写「驼峰落在 bounds[1..8]」——位置（bounds）没说错，
  但索引数错了，实测是 <b>bounds[3..10] 共 {len(hun_dqm)} 个</b>；而且 bounds 是<b>下降沿</b>，
  厂商自己的 T0..T9 竖线才在上升沿上。结论不变。
</p>

<h2>逐槽覆盖率与输出</h2>
<p class="lead">
  判据：<b>一个位槽里灰底列占比 ≥ 0.60 才算整槽 DON'T CARE</b>。实测两簇分得很开 ——
  被大灰带盖满的槽 0/1 是 <b>{frac[0]:.2f} / {frac[1]:.2f}</b>，
  其余槽只有 <b>{min(frac[2:]):.2f}~{max(frac[2:]):.2f}</b>（那是驼峰伸进来的零头）。
</p>
<table><thead><tr><th>槽位</th><th>灰底占比</th><th>判定</th><th>输出 2 字符</th></tr></thead>
<tbody>{''.join(tr)}</tbody></table>

<div class="concl">
  <h2>结论：驼峰不该变成 x，现在的输出是对的</h2>
  <p style="margin:0 0 8px">
    <b>大灰带</b>（<b>盖满整槽</b>、底宽一个整周期以上）＝ 逻辑上的 DON'T CARE → 输出 <code>xx</code>；<br>
    <b>驼峰</b>（底宽<b>半个</b>周期、压在时钟下降沿上）＝ 厂商标的 <code>tCMS</code>/<code>tCMH</code> 之类的<b>建立/保持窗</b>，
    <b>线才是值</b> → DQM 在这张图里始终走那条低电平线 → 输出 <code>0</code>。
  </p>
  <p style="margin:0">
    结果 <code>{dqm_wave}</code> = 前 2 槽 DON'T CARE + 后 8 槽低，与原图一致。
    我原来把它列成「待定夺」是读图不够；<b>CKE 那条对照把它证死了</b>，判据不用改。
  </p>
</div>

<footer>ISSI IS42S16400J datasheet p54 · 厂商图源不入技能库（本页在 test-cases/ 下，不进分发 zip）<br>
生成脚本：<code>explain_dqm_dontcare.py</code></footer>
</html>"""

    out = os.path.join(HERE, "dqm-dontcare.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ {out}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
