#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LPDDR4 (JESD209-4) Figure 15 复刻：Bus Preconditioning and DBI States for Read

输入：用户给的截图（LPDDR4 标准里的 Fig.15 位图，无文本层，2015x1092）
输出：Visio 可编辑的 SVG + 与原图并排的对照 HTML

⚠️ 与其它 test-cases 的区别（重要，别搞混）
   这不是「自动读图」的产物。这张图超出了三个解析器的能力边界：
     · 没有文本层 → pdf_trace.py 用不了
     · 数据区是**彩色状态块**（橙/黄/淡青）编码 DBI 状态，不是灰底电平带
       → auto_trace.py 的灰底填充率判据检不出（实测直接报「没有一条轨道能提取出电平」）
     · 4 字符/时钟 + T 标号有跳号（T1→T8、T12→T17 是省略断口）
       → 与工具「1 bit = 2 字符」的网格假设不兼容
   所以本脚本走的是**人工反解 + 几何测量**：所有坐标都从原图像素量出来
   （见下方「测量依据」），再用技能自带的 wavejson2svg 渲染 + 叠一层厂商标注。

测量依据（全部实测，非目测；探针脚本见 /tmp/lpddr/probe*.py）
   · 图尺寸 2015x1092；左侧标签列 y 带定位出 10 行信号
   · CK 周期 = 109.5 px；CK 跳变沿等距 54.75 px
   · C[7:0] 梯形格间距 54.7 px（= 半个时钟）；三个 READ 框恒为 99 px 宽
     （橙 387..485 / 黄 606..704 / 淡青 824..922）
   · T 标号中心 408,516,627,736,845,954,1063,1173,1282,1392,1501,1610,1719,1829
     → 等距 109.5 = 1 个时钟；且正好压在 CK 跳变沿上
   · 数据格 D0..D7 间距 27.4 px = 1/4 时钟；8 格 = 2 个时钟
   · WDQS_t 突发 x 655..1795；RDQS_t 突发 x 965..1795；DQS 周期 54.7 = 半个时钟
   · RL 箭头两条：y=289 跨 408..1502；y=344 跨 626..1283
   · 底部引线 x = 408 / 628 / 846（正好是 T0 / T8 / T10，即三个 READ）
   · 原图取色：橙 #f3d0b5  黄 #f7f794  淡青 #b1d6e1

坐标换算：char = 27.35 px（原图）＝ 1/4 个时钟；N = 64 chars；T 标号在 char 8,12,…,60
"""
import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "..", ".workbuddy", "skills", "wave2visio")
sys.path.insert(0, os.path.abspath(os.path.join(SKILL, "scripts")))

import wavejson2svg as W  # noqa: E402

# ---------------------------------------------------------------- 版面常量
N = 64           # 字符数（每字符 = 1/4 时钟）
CELL = 22.0      # 每字符像素宽
ROW = 56.0       # 每行高
LABEL_W = 190.0  # 左侧信号名列宽
GRID_STEP = 4    # 竖虚线步长（字符）＝ 1 个时钟

# 原图色值（直接采样）
C_ORANGE = "#f3d0b5"
C_YELLOW = "#f7f794"
C_CYAN = "#b1d6e1"
C_WHITE = "#ffffff"

# T 标号：char 8,12,16,...,60 —— 14 个（T2..T7 / T13..T16 被省略号折叠）
T_NAMES = ["T0", "T1", "T8", "T9", "T10", "T11", "T12",
           "T17", "T18", "T19", "T20", "T21", "T22", "T23"]
T_FIRST_CHAR = 8

# READ 命令：char 起点（各占 4 字符 = 1 个时钟）
READS = [(7, "3", C_ORANGE), (15, "4", C_YELLOW), (23, "5", C_CYAN)]

# 数据格标签
D_LABELS = [f"D{i}" for i in range(8)]


def ruler_labels():
    """16 格（每格 4 字符）的标尺文字，只在 T 出现的格上写字。"""
    out = [""] * (N // GRID_STEP)
    for i, name in enumerate(T_NAMES):
        out[(T_FIRST_CHAR + i * GRID_STEP) // GRID_STEP] = name
    return out


# ---------------------------------------------------------------- 波形构造
def c_bus():
    """C[7:0]：梯形格总线。格边界落在**奇**字符上（原图如此，T 标号线正好穿过格中央）。"""
    w = ["0"] * N
    c = 1
    while c < N - 1:
        w[c] = "2"
        w[c + 1] = "."
        c += 2
    for st, digit, _ in READS:
        w[st] = digit
        for i in range(st + 1, st + 4):
            w[i] = "."
    return "".join(w)


def data_row(hatch_len, first_block_flat=0, tail_flat=8, solid_mid=None,
             solid_tail=None):
    """Odd/Even Bytes 与 DBIac 三行的共同骨架。

    hatch_len    : 前面 Don't Care 斜纹的长度（字符）
      其后接 first_block_flat 个字符的空闲低电平，然后：
      8 个 D0..D7 格（各 1 字符）→ tail_flat 个字符空闲 → 一个 4 字符的 D7 宽块
      → 8 个 D0..D7（黄）→ 8 个 D0..D7（淡青）→ 收尾
    solid_mid    : 若非 None，(起, 长) —— 用一条**不细分**的实心色块替换「4 字符 D7 宽块」
    """
    w, data, colors = [], [], []

    def emit_block(digit, length, label, color):
        w.append(digit)
        w.extend(["."] * (length - 1))
        data.append(label)
        colors.append(color)

    # 前面的 Don't Care 斜纹（x = 未知态；config.x_style="hatch" 画成斜纹）
    w.extend(["x"] * hatch_len)
    w.extend(["0"] * first_block_flat)

    # 第一组 D0..D7（橙）
    for i, lbl in enumerate(D_LABELS):
        emit_block("6", 1, lbl, C_ORANGE)
    w.extend(["0"] * tail_flat)

    # 中间那条宽块（Odd/Even 是一个带 "D7" 字样的块；DBIac 是实心橙块）
    if solid_mid:
        emit_block("7", 8, "", C_ORANGE)
    else:
        emit_block("7", 4, "D7", C_ORANGE)

    # 第二组 D0..D7（黄）
    for lbl in D_LABELS:
        emit_block("8", 1, lbl, C_YELLOW)

    # 第三组 D0..D7（淡青）
    for lbl in D_LABELS:
        emit_block("9", 1, lbl, C_CYAN)

    # 收尾：DBIac 多一条实心淡青块
    rest = N - len(w)
    if solid_tail:
        emit_block("7", rest, "", C_CYAN)
        w = w[:N]
    else:
        w.extend(["0"] * rest)

    assert len(w) == N, f"数据行长度 {len(w)} != {N}"
    return "".join(w), data, colors


def dqs(solid_burst_start, solid_burst_len):
    """差分 DQS 一对：t = 实线，c = 虚线（未驱动时恒为 t 的反相）。

    solid_burst_start/l en : 实线那一相的突发区间（字符）
    """
    pre = solid_burst_start
    body = solid_burst_len
    post = N - pre - body
    wt = "0" * pre + "01" * (body // 2) + "0" * post
    wc = "1" * pre + "10" * (body // 2) + "1" * post
    assert len(wt) == N and len(wc) == N
    return wt, wc


def build_wavejson():
    sig = []
    # ---- 时钟（实线方波；原图 CK_c / CK_t 各占一行）
    sig.append({"name": "CK_c", "wave": "0011" * (N // 4)})
    sig.append({"name": "CK_t", "wave": "1100" * (N // 4)})

    # ---- C[7:0] 命令总线
    cb = c_bus()
    cb_data = []
    cb_colors = []
    # 逐块对齐（与 data_row 里 emit_block 的顺序一致）：空闲 2 字符块 / READ 4 字符块
    i = 0
    while i < N:
        if cb[i] in "23456789":
            j = i + 1
            while j < N and cb[j] in ".=":
                j += 1
            hit = next((c for c, _, _ in READS if c == i), None)
            if hit is None:
                cb_data.append("")
                cb_colors.append(C_WHITE)
            else:
                cb_data.append("READ")
                cb_colors.append(next(c for s, _, c in READS if s == i))
            i = j
        else:
            i += 1
    sig.append({"name": "C[7:0]", "wave": cb, "data": cb_data, "colors": cb_colors})

    # ---- 两条留白行：原图在 C[7:0] 与 WDQS 之间有 ~163px 的空白，专门放 RL 箭头
    sig.append({"name": "", "wave": "0" * N, "blank": True})
    sig.append({"name": "", "wave": "0" * N, "blank": True})

    # ---- 两组差分 DQS。原图 WDQS 先动（Bus Preconditioning），RDQS 后动（读数据）
    wt, wc = dqs(17, 42)
    sig.append({"name": "WDQS_c", "wave": wc, "dash": True})
    sig.append({"name": "WDQS_t", "wave": wt})
    rt, rc = dqs(28, 32)
    sig.append({"name": "RDQS_c", "wave": rc, "dash": True})
    sig.append({"name": "RDQS_t", "wave": rt})

    # ---- 三行数据/状态
    odd_w, odd_d, odd_c = data_row(16, first_block_flat=8, tail_flat=4)
    sig.append({"name": "Odd Bytes Data", "wave": odd_w, "data": odd_d, "colors": odd_c})

    even_w, even_d, even_c = data_row(22, first_block_flat=2, tail_flat=4)
    sig.append({"name": "Even Bytes Data", "wave": even_w, "data": even_d, "colors": even_c})

    dbi_w, dbi_d, dbi_c = data_row(22, first_block_flat=2, tail_flat=0,
                                   solid_mid=True, solid_tail=True)
    sig.append({"name": "Internal DBIac State", "wave": dbi_w,
                "data": dbi_d, "colors": dbi_c})

    return {
        "head": {"text": ""},
        "config": {
            "ruler": ruler_labels(),
            "ruler_step": GRID_STEP,
            "ruler_offset": 0,     # 标尺压在格的左边界 = 原图的时钟沿位置
            "ruler_pad": 0,        # 与 renderer.js 保持一致（铁律 8）
            "grid_step": GRID_STEP,
            "x_style": "hatch",    # Don't Care 画斜纹，不用淡灰底
            "x_line": False,       # Don't Care 区只留斜纹带 + 边界，不画电平中线
        },
        "signal": sig,
    }


# ---------------------------------------------------------------- 标注层
def cx(c):
    return LABEL_W + c * CELL


def annotation_layer(h_body, body_top, label_h):
    """厂商图特有的标注：RL 箭头 / 省略断口 / 底部注释 / Don't Care 图例 / 图题。

    h_body = 波形区底边（renderer 的 top0 + bodyH）
    """
    p = []
    # 省略断口：原图 x≈580 / 1130 → char 14.3 / 34.4
    for c in (14.3, 34.4):
        x = cx(c)
        y1, y2 = body_top - label_h + 6, h_body
        p.append(f'<line x1="{x-3:.1f}" y1="{y1:.1f}" x2="{x+3:.1f}" y2="{y2:.1f}" '
                 f'stroke="#111" stroke-width="1.6"/>')
        p.append(f'<line x1="{x+2:.1f}" y1="{y1:.1f}" x2="{x+8:.1f}" y2="{y2:.1f}" '
                 f'stroke="#111" stroke-width="1.6"/>')

    # RL = 10 箭头：与原图同跨度（char 8→48 与 16→40）
    for (a, b, lab_c, ty) in ((8, 48, 20, 224.0), (16, 40, 28, 280.0)):
        xa, xb = cx(a), cx(b)
        p.append(f'<line x1="{xa:.1f}" y1="{ty:.1f}" x2="{xb:.1f}" y2="{ty:.1f}" '
                 f'stroke="#111" stroke-width="1"/>')
        for (hx, sgn) in ((xa, 1), (xb, -1)):
            p.append(f'<path d="M {hx:.1f},{ty:.1f} L {hx+8*sgn:.1f},{ty-3.6:.1f} '
                     f'L {hx+8*sgn:.1f},{ty+3.6:.1f} Z" fill="#111"/>')
        p.append(f'<text x="{cx(lab_c):.1f}" y="{ty-6:.1f}" text-anchor="middle" '
                 f'font-family="Helvetica, Arial, sans-serif" font-size="12.5" '
                 f'fill="#111">RL = 10</text>')

    # 底部注释：原图引线 x = 408 / 628 / 846 = T0 / T8 / T10（即三个 READ）
    callouts = [(8, ["First READ", "After DBIac", "reset"]),
                (16, ["Non-seamless", "READ"]),
                (24, ["Seamless", "READ"])]
    y_lead0, y_lead1 = h_body + 6, h_body + 66
    for c, lines in callouts:
        x = cx(c)
        p.append(f'<line x1="{x:.1f}" y1="{y_lead0:.1f}" x2="{x:.1f}" y2="{y_lead1:.1f}" '
                 f'stroke="#111" stroke-width="1"/>')
        p.append(f'<path d="M {x:.1f},{y_lead0:.1f} L {x-3.6:.1f},{y_lead0+8:.1f} '
                 f'L {x+3.6:.1f},{y_lead0+8:.1f} Z" fill="#111"/>')
        for k, ln in enumerate(lines):
            p.append(f'<text x="{x:.1f}" y="{y_lead1+18+k*17:.1f}" text-anchor="middle" '
                     f'font-family="Helvetica, Arial, sans-serif" font-size="12.5" '
                     f'fill="#111">{ln}</text>')

    # Don't Care 图例（右下角；原图在 x 1700..1950 / y 875..915 → char 55.2）
    lx, ly = cx(55.2), y_lead1 + 4
    for s in W.hatch_segments(lx, ly, 24, 15):
        p.append(f'<line x1="{s[0]:.1f}" y1="{s[1]:.1f}" x2="{s[2]:.1f}" y2="{s[3]:.1f}" '
                 f'stroke="#9aa0a6" stroke-width="0.9"/>')
    p.append(f'<rect x="{lx:.1f}" y="{ly:.1f}" width="24" height="15" fill="none" '
             f'stroke="#111" stroke-width="1"/>')
    p.append(f'<text x="{lx+30:.1f}" y="{ly+12.5:.1f}" font-family="Helvetica, Arial, '
             f'sans-serif" font-size="12.5" fill="#111">Don\'t Care</text>')

    # 图题
    p.append(f'<text x="{LABEL_W + N*CELL/2:.1f}" y="{ly+52:.1f}" text-anchor="middle" '
             f'font-family="Helvetica, Arial, sans-serif" font-size="14" font-weight="bold" '
             f'fill="#111">Figure 15 &#8212; Bus Preconditioning and DBI States for Read</text>')
    return "\n".join(p)


def inject(base_svg, w, h_old, h_new, layer):
    """把画布加高并把标注层插到 </svg> 之前。

    ⚠️ 不能用 f'width="{w:.0f}"' 去匹配 —— renderer 的 W/H 是浮点，写出来是
    width="1622.0"，四舍五入的串根本匹配不上，replace 会静默失败（第一版就踩了，
    标注被 SVG 的 overflow:hidden 裁掉，看图才发现）。这里直接按属性名替换。
    """
    svg = re.sub(r'(<svg[^>]*?)\bwidth="[^"]*"', rf'\1width="{w}"', base_svg, count=1)
    svg = re.sub(r'(<svg[^>]*?)\bheight="[^"]*"', rf'\1height="{h_new}"', svg, count=1)
    svg = re.sub(r'(<svg[^>]*?)\bviewBox="[^"]*"',
                 rf'\1viewBox="0 0 {w} {h_new}"', svg, count=1)
    svg = svg.replace(
        "</svg>",
        f'<rect x="0" y="{h_old}" width="{w}" height="{h_new - h_old}" fill="#ffffff"/>\n'
        f'<g id="vendor-annotations">\n{layer}\n</g>\n</svg>', 1)
    return svg


def main():
    wj = build_wavejson()
    sigs = wj["signal"]
    head_h, lbl_h, foot_h = 8.0, 20.0, 8.0
    body_h = ROW * len(sigs)
    top0 = head_h + lbl_h
    w = LABEL_W + N * CELL + 24
    h_base = top0 + body_h + foot_h
    body_bottom = top0 + body_h

    base = W.render(wj, cell=CELL, row_h=ROW, label_w=LABEL_W,
                    show_grid=True, grid_step=GRID_STEP, grid_labels=True)

    extra = 175.0
    h_new = h_base + extra
    layer = annotation_layer(body_bottom, top0, lbl_h)
    svg = inject(base, w, h_base, h_new, layer)

    out_svg = os.path.join(HERE, "lpddr4-fig15-bus-preconditioning.svg")
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"✓ {out_svg}  ({len(svg)} bytes, {int(w)}x{int(h_new)})")

    wj_path = os.path.join(HERE, "lpddr4-fig15.wavejson.json")
    with open(wj_path, "w", encoding="utf-8") as f:
        json.dump(wj, f, ensure_ascii=False, indent=1)
    print(f"✓ {wj_path}")

    # 与原图并排的对照 HTML（单文件，图片 base64 内嵌 —— 预览面板不映射相对路径）
    ref_html = ""
    cand = None
    for c in (LPDDR_SRC, "/tmp/lpddr/fig15_rgb.png"):
        if os.path.exists(c):
            cand = c
            break
    if cand:
        b64 = base64.b64encode(open(cand, "rb").read()).decode()
        ref_html = (f'<figure><figcaption>原图（JESD209-4 Figure 15 截图，'
                    f'{os.path.basename(cand)}）</figcaption>'
                    f'<img src="data:image/png;base64,{b64}" alt="original"></figure>')
    svg64 = base64.b64encode(svg.encode()).decode()
    html = COMPARE_TPL.format(ref=ref_html, svg=svg64)
    out_html = os.path.join(HERE, "lpddr4-fig15-compare.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ {out_html}  ({len(html)} bytes)")


LPDDR_SRC = os.path.join(HERE, "figs", "lpddr4-fig15-bus-preconditioning-source.png")

COMPARE_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>LPDDR4 Fig.15 复刻对照</title>
<style>
 body{{margin:0;background:#eef0f3;font:14px/1.6 -apple-system,"PingFang SC",Helvetica,Arial,sans-serif;color:#1a1a1a}}
 header{{padding:18px 26px;background:#fff;border-bottom:1px solid #d8dbe0}}
 h1{{margin:0 0 4px;font-size:17px}}
 .sub{{color:#5a6270;font-size:12.5px}}
 main{{padding:22px 26px 60px;display:flex;flex-direction:column;gap:26px}}
 figure{{margin:0;background:#fff;border:1px solid #d8dbe0;border-radius:8px;padding:14px;overflow:auto}}
 figcaption{{font-size:12.5px;color:#5a6270;margin-bottom:10px;font-weight:600}}
 img,object{{display:block;width:100%;height:auto}}
 .note{{background:#fff8e6;border:1px solid #f0d9a0;border-radius:8px;padding:12px 16px;font-size:13px}}
 .note b{{color:#8a5a00}}
 code{{background:#eef0f3;padding:1px 5px;border-radius:4px;font-size:12.5px}}
</style></head><body>
<header>
  <h1>LPDDR4 JESD209-4 Figure 15 —— 复刻对照</h1>
  <div class="sub">「Bus Preconditioning and DBI States for Read」· 复刻件是由像素测量反解结构后重绘的矢量图，可进 Visio 编辑</div>
</header>
<main>
  <div class="note">
    <b>注意：这不是自动读图的产物。</b>该图属于工具的已知能力边界之外
    （无文本层、彩色状态块、4 字符/时钟、T 标号跳号），三个解析器都处理不了。
    本复刻是<b>人工反解 + 几何测量</b>的结果：所有坐标从原图像素量出，
    再用 <code>wavejson2svg.py</code> 渲染并叠一层厂商标注。
  </div>
  <figure style="padding:0"><figcaption style="padding:14px 14px 0">逐项差异清单（诚实交代，别当成「一模一样」）</figcaption>
  <table style="border-collapse:collapse;width:100%;font-size:13px">
   <tr style="background:#f5f6f8;text-align:left">
     <th style="padding:8px 14px;border-top:1px solid #e3e6ea">项目</th>
     <th style="padding:8px 14px;border-top:1px solid #e3e6ea">原图</th>
     <th style="padding:8px 14px;border-top:1px solid #e3e6ea">复刻件</th></tr>
   <tr><td style="padding:7px 14px">时钟 / 总线 / 数据块形状</td>
       <td style="padding:7px 14px">斜边梯形</td>
       <td style="padding:7px 14px"><b>直角矩形</b>（本渲染器的既定风格；更利于 Visio 里改）</td></tr>
   <tr style="background:#fafbfc"><td style="padding:7px 14px">T0 / T8 / T10 三个 READ 的位置</td>
       <td style="padding:7px 14px">框内偏左 0.77 字符</td>
       <td style="padding:7px 14px">对齐到 T 网格线（差 ≈ 1/4 时钟周期）</td></tr>
   <tr><td style="padding:7px 14px">WDQS_c / RDQS_c（虚线反相）</td>
       <td style="padding:7px 14px">与 t 相紧贴，呈差分对</td>
       <td style="padding:7px 14px">独立成行、满幅度（四行各自有名字，更好读）</td></tr>
   <tr style="background:#fafbfc"><td style="padding:7px 14px">D0…D7 格内文字</td>
       <td style="padding:7px 14px">上行 "D" 下行数字</td>
       <td style="padding:7px 14px">合并为 "D0"…"D7" 一行</td></tr>
   <tr><td style="padding:7px 14px">数据格宽度</td>
       <td style="padding:7px 14px">≈ 30px（原图 2015px 宽）</td>
       <td style="padding:7px 14px">= 1 字符 = 27.35px（同尺度下末端累计差 &lt; 1 格）</td></tr>
   <tr style="background:#fafbfc"><td style="padding:7px 14px">斜纹 Don't Care / 省略断口 / RL 箭头 / 图例</td>
       <td style="padding:7px 14px">—</td>
       <td style="padding:7px 14px"><b>位置按原图实测坐标复刻</b>（含两处断口 x≈580 / 1130）</td></tr>
  </table></figure>
  {ref}
  <figure><figcaption>复刻件（SVG · Visio 可 <code>File→Open</code> 导入编辑）</figcaption>
    <object type="image/svg+xml" data="data:image/svg+xml;base64,{svg}"></object>
  </figure>
  <div class="note">
    <b>进 Visio 怎么用：</b>Visio 2024+ → <code>File → Open</code> 直接选这个 SVG →
    右键 <b>Ungroup</b> 即可逐条改文字/改颜色（全是 <code>&lt;path&gt;/&lt;rect&gt;/&lt;text&gt;</code>，
    没有位图、没有 CDN 依赖、没有 SVG pattern）。
    波形语义源在 <code>lpddr4-fig15.wavejson.json</code>，改 JSON 后重跑
    <code>build_lpddr_fig15.py</code> 即可再生成。
  </div>
</main></body></html>
"""


if __name__ == "__main__":
    main()
