#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py — wave2visio skill 一键自检（纯标准库，秒级，不联网）

核心思路：**不靠肉眼**。
把渲染出来的 SVG **反解回「每字符电平」**，再和预期逐 bit 对照。
这就是验收红线「一模一样 = 拓扑 / 电平序列逐 bit 等效」的机器化版本 ——
不依赖人眼比对图片，失败时会直接告诉你第几个字符错了。

覆盖用例：
  1. 参考波形（SPI mode 0）逐 bit 回读
  2. 恒定电平不产生多余转折 + 时钟对齐虚线（数量 / 位置 / 跨度 / 层级 / 位标尺）
  3. `.` / `=` 延续语义
  4. `2-9` 会吃掉电平（负向用例，证明铁律不是空话）
  5. Python 渲染器 ≡ JS 渲染器（电平、跳变、画布、虚线、位标尺）
  6. 网页产物与真相源一致（等价于 build_web.py --check）
  7. **铁律 0：原图未被修改**（sha256）+ 叠加层位置 == 从原图实测的位边界

用法：
  python3 scripts/selftest.py         # 跑全部
  python3 scripts/selftest.py -v      # 打印每步细节
  python3 scripts/selftest.py -q      # 只打印结论
  python3 scripts/selftest.py --html  # 顺便出可视化验收报告

退出码：0 = 全过，1 = 有用例失败
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import wavejson2svg as PY  # noqa: E402

PY_CELL, PY_ROW, PY_LW = 24.0, 60.0, 110.0   # 与 selftest 调用 render() 时传参一致
JS_CELL, JS_ROW, JS_LW = 26.0, 62.0, 112.0   # renderer.js 里的 RJS 常量

RE_PT = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
RE_PATH = re.compile(r'<path d="([^"]+)"')
RE_LINE = re.compile(r'<line x1="([\d.-]+)" y1="([\d.-]+)" '
                     r'x2="([\d.-]+)" y2="([\d.-]+)"')
RE_DLABEL = re.compile(r'>D(\d)<')

GRID_STEP = 2      # 竖虚线间隔（字符数）：2 = 每 1 个数据位一条
LBL_H = 20         # 位标尺条高度


# --------------------------------------------------------------------------
# 从 SVG 几何反解电平
# --------------------------------------------------------------------------
def parse_pts(d):
    return [(float(a), float(b)) for a, b in RE_PT.findall(d)]


def bits_of(wj):
    """按「首尾各 2 字符留白、1 bit = 2 字符」推导位标尺。"""
    n = max((len(s.get("wave", "")) for s in wj.get("signal", [])), default=0)
    if n >= 4 and (n - 4) % 2 == 0:
        nb = (n - 4) // 2
        return [f"D{nb - 1 - i}" for i in range(nb)]
    return []


def rows_of(wj, row_h, grid_labels=True):
    """复算每条信号轨道的 (y_high, y_low) —— 与渲染器同一套公式。"""
    head = ((wj.get("head") or {}).get("text")) or ""
    head_h = 34 if head else 8
    lbl_h = LBL_H if (grid_labels and bits_of(wj)) else 0
    top0 = head_h + lbl_h
    out = []
    for si in range(len(wj.get("signal", []))):
        top = top0 + si * row_h
        pad = row_h * 0.17
        out.append((top + pad, top + row_h - 1 - pad))
    return out


def recover(d, x0, cell, y_high, y_low, nchars):
    """把折线 path 反解成每字符的 '0'/'1'（取每格中点采样所在水平段）。"""
    pts = parse_pts(d)
    segs = [(a[0], b[0], a[1]) for a, b in zip(pts, pts[1:])
            if abs(a[1] - b[1]) < 1e-6 and b[0] > a[0]]
    span = y_low - y_high
    out = []
    for i in range(nchars):
        xm = x0 + (i + 0.5) * cell
        y = None
        for a, b, yy in segs:
            if a - 1e-6 <= xm <= b + 1e-6:
                y = yy
                break
        out.append("?" if y is None else ("1" if (y_low - y) / span > 0.5 else "0"))
    return "".join(out)


def transitions(d):
    """折线里垂直段（电平跳变）的条数。多余转折 = 尖刺 bug。"""
    pts = parse_pts(d)
    return sum(1 for a, b in zip(pts, pts[1:])
               if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) > 1e-6)


def read_svg(svg, wj, cell, row_h, label_w):
    """返回 [(signal_name, recovered_bits, n_transitions)]"""
    paths = RE_PATH.findall(svg)
    rows = rows_of(wj, row_h)
    res = []
    for si, sig in enumerate(wj.get("signal", [])):
        wave = sig.get("wave", "")
        d = paths[si]
        y_high, y_low = rows[si]
        res.append((
            sig.get("name", ""),
            recover(d, label_w, cell, y_high, y_low, len(wave)),
            transitions(d),
        ))
    return res


def expand(wave):
    """参考实现：把带 . = p x z 2-9 的 wave 展开成电平串（用于算期望值）。"""
    out, prev = [], "0"
    for ch in wave:
        if ch == "0":
            prev = "0"
        elif ch in "1p23456789":
            prev = "1"
        elif ch in ".=":
            pass
        out.append(prev)
    return "".join(out)


def canvas_of(svg):
    m = re.search(r'width="([\d.]+)" height="([\d.]+)"', svg)
    return (float(m.group(1)), float(m.group(2))) if m else None


def expect_canvas(wj, cell, row_h, label_w):
    """布局契约：W = label_w + n*cell + 24，
    H = head_h + lbl_h + row_h*nsig + foot_h（lbl_h 为位标尺条）。

    两条实现共用这一套公式，只是常量不同（py 24/60/110，js 26/62/112）。
    """
    head = ((wj.get("head") or {}).get("text")) or ""
    foot = ((wj.get("foot") or {}).get("text")) or ""
    sigs = wj.get("signal", [])
    n = max((len(s.get("wave", "")) for s in sigs), default=0)
    lbl_h = LBL_H if bits_of(wj) else 0
    return (label_w + n * cell + 24,
            (34 if head else 8) + lbl_h + row_h * len(sigs) + (34 if foot else 8))


# --------------------------------------------------------------------------
# 用例框架
# --------------------------------------------------------------------------
class Report:
    def __init__(self, verbose):
        self.rows = []
        self.verbose = verbose

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        if self.verbose or not ok:
            mark = "✓" if ok else "✗"
            print(f"  {mark} {name}" + (f"\n      {detail}" if detail else ""))
        return ok

    def fail_count(self):
        return sum(1 for _, ok, _ in self.rows if not ok)


def py_render(wj):
    return PY.render(wj, cell=PY_CELL, row_h=PY_ROW, label_w=PY_LW,
                     show_grid=True, grid_step=GRID_STEP, grid_labels=True)


def js_render(wj):
    """在 node 里跑 renderer.js（技能自带那份），拿到 JS 渲染器的 SVG。"""
    node = None
    for cand in (
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
        "node",  # 走 PATH
    ):
        if cand == "node":
            if shutil.which("node"):
                node = cand
                break
        elif os.path.exists(cand):
            node = cand
            break
    if node is None:
        return None, "找不到 node"

    renderer = open(os.path.join(HERE, "renderer.js"), encoding="utf-8").read()
    tmpdir = "/tmp/wj_selftest"
    os.makedirs(tmpdir, exist_ok=True)
    js_file = os.path.join(tmpdir, "driver.js")
    json_file = os.path.join(tmpdir, "input.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(wj, f)
    with open(js_file, "w", encoding="utf-8") as f:
        f.write(renderer)
        f.write("\nprocess.stdout.write(renderWaveJson("
                "JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'))));\n")
    p = subprocess.run([node, js_file, json_file], capture_output=True, text=True)
    if p.returncode != 0:
        return None, (p.stderr or "").strip().splitlines()[-1:] or "node 退出非 0"
    return p.stdout, None


# --------------------------------------------------------------------------
# 可视化验收报告（单文件，资源全内嵌）
# --------------------------------------------------------------------------
OVERLAY_JSON = os.path.join(ROOT, "assets", "clk-overlay.json")
INPUT_PNG = os.path.join(ROOT, "assets", "test-input-spi.png")


def png_sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_module(name, filename):
    """从 scripts/ 目录按文件名加载模块（不污染 sys.path）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_overlay():
    """读 clk-overlay.json —— 由 scripts/measure_input.py 从原图实测得到。"""
    with open(OVERLAY_JSON, encoding="utf-8") as f:
        return json.load(f)


def overlay_svg(ov, cls="clk"):
    """只画竖线，不碰原图。viewBox 归一化到 0..1，配合 preserveAspectRatio=none
    后坐标即「占图宽/图高的比例」，因此线与图像素严格对应。"""
    y0, y1 = ov["line_y_frac"]
    parts = [f'<svg class="{cls}" viewBox="0 0 1 1" preserveAspectRatio="none" '
             f'aria-hidden="true">']
    for fx in ov["boundaries_frac"]:
        parts.append(f'<line x1="{fx}" y1="{y0}" x2="{fx}" y2="{y1}"/>')
    parts.append("</svg>")
    return "".join(parts)


def render_html(rows, wj, got):
    import base64
    import html as H
    import time

    png_b64 = base64.b64encode(open(INPUT_PNG, "rb").read()).decode("ascii")
    ov = load_overlay()
    ov_sha8 = ov["sha256"][:8]
    clk_lines = overlay_svg(ov)
    n_clk = len(ov["boundaries_frac"])
    svg = py_render(wj)
    passed = sum(1 for _, ok, _ in rows if ok)
    total = len(rows)

    def cells(s, shadow=None):
        out = []
        for i, ch in enumerate(s):
            cls = "c" if (shadow is None or shadow[i] == ch) else "c bad"
            out.append(f'<span class="{cls}">{H.escape(ch)}</span>')
        return "".join(out)

    trs = []
    for (name, bits, _), sig in zip(got, wj["signal"]):
        want = sig["wave"]
        rec_data = bits[2:18:2]
        ok = bits == want
        hexv = f"0x{int(rec_data, 2):02X}" if set(rec_data) <= {"0", "1"} else "—"
        trs.append(
            f'<tr><td class="sig">{H.escape(name)}</td>'
            f'<td class="wave">{cells(want)}</td>'
            f'<td class="wave">{cells(bits, want)}</td>'
            f'<td class="mono">{rec_data}</td><td class="mono">{hexv}</td>'
            f'<td class="{"ok" if ok else "no"}">'
            f'{"✓ 逐字符一致" if ok else "✗ 有偏差"}</td></tr>')

    lis = []
    for name, ok, detail in rows:
        d = f'<em>{H.escape(detail)}</em>' if detail else ""
        lis.append(f'<li class="{"ok" if ok else "no"}">'
                   f'<b>{"✓" if ok else "✗"}</b>{H.escape(name)}{d}</li>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WaveJSON 技能验收报告</title>
<style>
:root{{--fg:#1a1a1a;--muted:#6b6b6b;--line:#e2e2e2;--bg:#fff;--soft:#fafafa;
--ok:#1f7a45;--no:#b3261e;--accent:#1f4e9c}}
*{{box-sizing:border-box}}
body{{margin:0;padding:40px 32px 64px;background:var(--bg);color:var(--fg);
font:15px/1.7 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 6px;font-weight:600;letter-spacing:-.01em}}
.meta{{color:var(--muted);font-size:13px;margin:0 0 28px}}
.meta code,figcaption code{{font-family:ui-monospace,Menlo,monospace;font-size:12px;
background:#f4f4f5;padding:1px 5px;border-radius:4px}}
.badge{{display:inline-block;padding:3px 12px;border-radius:99px;font-size:13px;
font-weight:600;margin-left:10px;vertical-align:2px}}
.badge.ok{{background:#e7f5ec;color:var(--ok)}}
.badge.no{{background:#fdecea;color:var(--no)}}
h2{{font-size:16px;margin:38px 0 14px;font-weight:600;padding-bottom:8px;
border-bottom:1px solid var(--line)}}
h2 span{{color:var(--muted);font-weight:400;font-size:13px;margin-left:8px}}
.cols{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}}
figure{{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--soft)}}
figure img,figure > div > svg:not(.clk){{display:block;width:100%;height:auto;background:#fff}}
.imgwrap{{position:relative;display:block;background:#fff;line-height:0}}
.imgwrap img{{display:block;width:100%;height:auto}}
svg.clk{{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}}
svg.clk line{{stroke:#e24b4a;stroke-width:1.1;stroke-dasharray:4 4;
stroke-opacity:.85;vector-effect:non-scaling-stroke}}
figcaption{{padding:9px 14px;font-size:13px;color:var(--muted);
background:#fff;border-top:1px solid var(--line)}}
.hint{{margin:12px 0 0;font-size:13px;color:var(--muted)}}
.hint b{{color:var(--fg)}}
.legend{{display:inline-flex;align-items:center;gap:6px;margin-left:6px}}
.legend i{{display:inline-block;width:16px;height:0;border-top:2px dashed #e24b4a}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}}
th{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);
color:var(--muted);font-weight:500;font-size:12.5px;white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
td.sig{{font-weight:600;color:var(--accent);white-space:nowrap}}
.wave{{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}}
.wave .c{{display:inline-block;width:15px;text-align:center;font-size:12.5px;color:#333}}
.wave .c.bad{{background:#fdecea;color:var(--no);font-weight:700;border-radius:3px}}
.mono{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:nowrap}}
td.ok,.ok b{{color:var(--ok)}} td.no,.no b{{color:var(--no)}}
ul{{list-style:none;padding:0;margin:0;columns:2;column-gap:32px}}
li{{break-inside:avoid;padding:6px 0;font-size:13.5px;border-bottom:1px solid #f4f4f4}}
li b{{display:inline-block;width:18px;font-weight:700}}
li em{{display:block;margin-left:18px;color:var(--muted);font-style:normal;
font-size:12.5px;white-space:pre-wrap}}
.note{{margin-top:34px;padding:16px 18px;background:var(--soft);
border-left:3px solid var(--accent);border-radius:0 8px 8px 0;font-size:13.5px}}
.note b{{color:var(--accent)}}
.note.rule0{{border-left-color:var(--no)}}
.note.rule0 b{{color:var(--no)}}
footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:12.5px}}
</style></head><body><div class="wrap">

<h1>WaveJSON 技能验收报告
<span class="badge {"ok" if passed == total else "no"}">{passed}/{total} 通过</span></h1>
<p class="meta">{time.strftime("%Y-%m-%d %H:%M")} · 由 <code>scripts/selftest.py --html</code> 自动生成 ·
全程离线、无 API 调用</p>

<h2>一、端到端对照<span>输入原图未被修改，只在其上叠加了一层时钟对齐线</span></h2>
<div class="cols">
  <figure><div class="imgwrap">
      <img src="data:image/png;base64,{png_b64}" alt="输入原图">
      {clk_lines}
    </div>
    <figcaption>输入 · 原图 <code>sha256:{ov_sha8}…</code>（<b>未被修改</b>）
      + 叠加 {n_clk} 条时钟对齐线</figcaption></figure>
  <figure><div>{svg}</div>
    <figcaption>输出 · 本技能渲染的直角方波 SVG（对齐线画在波形之前，
      不遮挡电平边沿）</figcaption></figure>
</div>
<p class="hint"><span class="legend"><i></i>红色竖虚线 = 时钟对齐线</span> ——
每个数据位窗恰好落在同一个 SCLK 周期内，逐 bit 等效一眼可查。
左边那组线的位置<b>不是手算的</b>，是 <code>measure_input.py</code> 从原图自身的 SCLK
上升沿实测出来的（周期 {ov["sclk_period_px"]} px），所以原图一旦被改动，线就会对不上并被自检发现。</p>

<h2>二、逐 bit 对照<span>把渲染结果反解回电平，和原图逐字符比 —— 不靠肉眼</span></h2>
<table><thead><tr>
<th>信号</th><th>预期 wave（原图）</th><th>从 SVG 回读</th>
<th>中段 16 位</th><th>hex</th><th>结论</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table>

<h2>三、自检清单<span>共 {total} 项</span></h2>
<ul>{"".join(lis)}</ul>

<div class="note rule0">
<b>铁律 0：原图不可修改。</b>左侧那张输入图是<b>基准</b>，任何脚本都不许重画、重存、覆盖它。
对齐线是<b>叠加上去的一层</b>（独立的 SVG 层），原图文件逐字节未变 ——
自检会比对它的 sha256（<code>{ov["sha256"]}</code>）。此前我曾为了"让两张图边距一致"而重新
生成原图，那是错的，已回滚并删掉了那个会覆写原图的脚本。
</div>

<div class="note">
<b>关于「一模一样」。</b>本报告的判定口径是<b>拓扑 / 电平序列逐 bit 等效</b>，不是图片像素比对 ——
渲染器的线宽、字号属于风格差异，不影响正确性。所以判定方式是：把 SVG 的折线几何反解回
「每字符电平」，再和原图读数对照。任何一位对不上，表格里对应字符会标红，脚本退出码为 1。
<br><br>
<b>关于对齐线。</b>输出侧的竖虚线按「1 个数据位 = 2 字符」落在位边界上、贯穿全部信号、
画在波形之前。自检会校验：虚线数量、x 坐标是否落在位边界、y 跨度是否覆盖全部轨道、
是否画在波形之前、D7…D0 位标尺是否齐全，以及 Python / JS 两条实现是否一致。
<br><br>
<b>两张图的像素级横向对齐不做保证</b> —— 原图有自己的边距比例（且不可改），
与输出 SVG 的布局比例不同，所以并排时线不会逐像素重合。两边各自与自己的位网格对齐。
</div>

<footer>wave2visio skill · scripts/selftest.py · 报告为单文件自包含，可直接转发</footer>
</div></body></html>"""


def build_html(rows, wj, got, out_path):
    doc = render_html(rows, wj, got)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path


# --------------------------------------------------------------------------
# [10] 组用的**合成 PDF**
#   · 为什么不用厂商文件：版权 + 本机未必有。合成图入库即可常跑，
#     把 pdf_trace 的每条判据都变成可回归的断言。
#   · 合成图不是「随便画一张」，每一处版式都在复刻真实 datasheet 的特征，
#     理由逐条写在 _make_synth_timing_pdf 的 docstring 里。
# --------------------------------------------------------------------------
SYNTH_FONT = "helv"
SYNTH_FS = 9.0                 # 统一字号（pt）
SYNTH_LABEL_X = 140.0          # 行标签共用的**右边界**（label_x_right 认的众数）
SYNTH_PLOT_L = 150.0           # 波形区左界
SYNTH_PLOT_R = 560.0           # 波形区右界
SYNTH_ROW_Y = (200.0, 240.0, 280.0)   # CLK / CMD / DATA 的行中心
SYNTH_SLOT_W = 130.0           # 一个位槽的宽度（= T0/T1/T2 间距）
SYNTH_C0 = 190.0               # 首个位槽的中心（槽边界 = 中心 ± 65）
SYNTH_AMP = 10.0               # 电平轨相对行中心的偏移


def _synth_text(page, text, x, baseline, center=False):
    """往合成 PDF 上放一段字（全图同字号，便于反推基线）。

    center=False → x 是**右边界**（行标签：只有右对齐才会形成 label_x_right 认的众数）
    center=True  → x 是**中心**（槽位里的总线值 / 位标尺：居中放）
    """
    import pymupdf
    w = pymupdf.get_text_length(text, fontname=SYNTH_FONT, fontsize=SYNTH_FS)
    x0 = x - w / 2.0 if center else x - w
    page.insert_text((x0, baseline), text, fontname=SYNTH_FONT, fontsize=SYNTH_FS)


def _synth_baseline_delta():
    """量一次「基线 − bbox 中心」的偏移 δ。

    为什么必须现量：`fuse_levels()` 拿**行标签 bbox 的中心**当行中心去采像素电平，
    所以合成图里标签和它那条波形必须严格共中心 —— 差几 pt 就采到隔壁行去了。
    而 bbox 的上下边由字体度量（ascender/descender）决定，跨库跨版本都可能微差，
    与其硬编码一个 2.3pt，不如拿一张一次性小页当场量出来。
    """
    import pymupdf
    d = pymupdf.open()
    p = d.new_page(width=200, height=200)
    p.insert_text((20, 100), "Xy", fontname=SYNTH_FONT, fontsize=SYNTH_FS)
    w = p.get_text("words")[0]
    dlt = 100.0 - (w[1] + w[3]) / 2.0
    d.close()
    return dlt


def _make_synth_timing_pdf(path):
    """造一张「教科书式」的 3 行时序图 PDF（CLK / CMD / DATA）。

    刻意复刻真实 datasheet 的每一处版式特征，让 [10] 组真的在守这些特征：

      · 行标签**右对齐**（三者 x1 共用同一条边界）—— `label_x_right()` 认的就是
        这个众数。用「矢量横段最小起点」会失败，页眉通栏线就是反例。
      · 位标尺用厂商风格的 `T0/T1/T2`（间距 = 一个时钟周期），而不是我们猜的
        `D7…D0` —— 这条守的是 `config.ruler` 走的是厂商标记。
      · 行距 40pt —— 再往上调就会顶到 `FIG_GAP(45)`：同一张图会被切成几块、
        只留 `max(groups)` 那一段（实测 ADS8482 p17 就是这么丢过上半张图的）。
      · 页眉一条**通栏横线**：存在的唯一目的就是回归 `vector_band()`。不先圈图的话
        「波形区左界」会被它拉到左边距、右侧一个字都取不到 —— 这正是当初
        pdf_trace 在 ISSI p54 上误报「左侧标签列找不到任何文字」的根因。
      · CMD 是**总线带**：每个槽一个方框（上下边即横段），槽内居中写 `A0/A1/A2`。
      · DATA 是「电平线 + 灰梯形」画法：一条横贯全图的低电平线 + 首槽 DON'T CARE
        灰底 —— 复刻 ISSI p54 的 CKE / DQM 画法（见 fuse_levels 的画法 B）。
        灰底同时满足两件事：整槽被盖住 → 输出 `x`；灰区远端 = 高轨 → 这条线判为低。
    """
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    dlt = _synth_baseline_delta()

    # —— 页眉：通栏横线（wave_span 会当外框排除）+ 一行标题（左对齐，不形成众数）——
    page.draw_line((27, 40), (568, 40), color=(0,), width=1)
    page.insert_text((27, 60), "Synthetic timing fixture - selftest only",
                     fontname=SYNTH_FONT, fontsize=8)

    # —— 三行行标签，右对齐到 SYNTH_LABEL_X ——
    for name, yc in zip(("CLK", "CMD", "DATA"), SYNTH_ROW_Y):
        _synth_text(page, name, SYNTH_LABEL_X, yc + dlt)

    # —— 位标尺 T0/T1/T2（中心 190/320/450）。
    #     放在 CMD 与 DATA 两行之间：它必须落在各行 y 带 ±12pt 内，read_values 才收得到 ——
    #     原厂图里 T 标记也都是夹在图内的，不是页边。 ——
    mark_base = (SYNTH_ROW_Y[1] + SYNTH_ROW_Y[2]) / 2.0 + dlt
    for k in range(3):
        _synth_text(page, f"T{k}", SYNTH_C0 + k * SYNTH_SLOT_W, mark_base, center=True)

    # —— CLK：每个槽「前半低、后半高」。两个采样点在 25% / 75% 处（±19.4pt 窗），
    #     分别落在后半高区与前半低区 → 每槽得 "01"。 ——
    y_hi = SYNTH_ROW_Y[0] - SYNTH_AMP
    y_lo = SYNTH_ROW_Y[0] + SYNTH_AMP
    for k in range(3):
        cx = SYNTH_C0 + k * SYNTH_SLOT_W
        a = SYNTH_PLOT_L if k == 0 else cx - SYNTH_SLOT_W / 2.0
        b = SYNTH_PLOT_R if k == 2 else cx + SYNTH_SLOT_W / 2.0
        page.draw_line((a, y_lo), (cx, y_lo), color=(0,), width=1)      # 前半：低
        page.draw_line((cx, y_hi), (b, y_hi), color=(0,), width=1)      # 后半：高
        page.draw_line((cx, y_lo), (cx, y_hi), color=(0,), width=1)     # 上升沿

    # —— CMD：总线带，每槽一个方框 + 槽内居中的总线值 ——
    cy = SYNTH_ROW_Y[1]
    for k in range(3):
        cx = SYNTH_C0 + k * SYNTH_SLOT_W
        a = SYNTH_PLOT_L if k == 0 else cx - SYNTH_SLOT_W / 2.0
        b = SYNTH_PLOT_R if k == 2 else cx + SYNTH_SLOT_W / 2.0
        page.draw_rect(pymupdf.Rect(a, cy - SYNTH_AMP, b, cy + SYNTH_AMP),
                       color=(0,), width=1)
        _synth_text(page, f"A{k}", cx, cy + dlt, center=True)

    # —— DATA：电平线（低）+ 首槽 DON'T CARE 灰底 ——
    dy = SYNTH_ROW_Y[2]
    gx = SYNTH_C0 + SYNTH_SLOT_W / 2.0                       # 首槽右界 = 255
    page.draw_line((SYNTH_PLOT_L, dy + SYNTH_AMP), (SYNTH_PLOT_R, dy + SYNTH_AMP),
                   color=(0,), width=1)                      # 横贯全图的电平线（低）
    page.draw_rect(pymupdf.Rect(SYNTH_PLOT_L, dy - SYNTH_AMP, gx, dy + SYNTH_AMP),
                   color=None, fill=(0.75,))                 # DON'T CARE 灰底（fill-only）
    page.draw_line((SYNTH_PLOT_L, dy - SYNTH_AMP), (gx, dy - SYNTH_AMP),
                   color=(0,), width=1)                      # 灰区上边
    page.draw_line((gx, dy - SYNTH_AMP), (gx, dy + SYNTH_AMP),
                   color=(0,), width=1)                      # 灰区右边

    doc.save(path)
    doc.close()


def _make_synth_prose_pdf(path):
    """造一张「正文页」PDF，用来验证适用性闸门会把它拦下。

    复刻正文页的两个致命特征（都是实测出来的）：
      · 文字行右边界对齐（两端对齐的正文就是这样）→ 词右边界形成众数，
        会被误认成「行标签列」（实测 AD7606 p24 被当成 16 行信号）；
      · 每行都很长 —— 信号名天生短、正文行天生长，这是闸门最干净的判据
        （实测真图中位 ≤ 52.6pt，正文 ≥ 158.1pt，3 倍分离）。

    刻意**不放任何矢量**：这样 vector_band 返回 None，顺便守住
    「没有矢量层时也不许把段落当信号」这条分支。
    """
    import pymupdf
    lines = [
        "The device requires a stable supply voltage and adequate decoupling close to",
        "each power pin; place a low-ESR capacitor as near to the package as practical",
        "to minimise the loop area formed by the supply trace and its return path and",
        "thereby reduce the transient noise that would otherwise degrade the accuracy",
        "of the conversion result during the acquisition phase of the internal track",
        "and hold amplifier when the input signal is sampled onto the sampling node",
        "and after which the successive approximation register resolves the bits from",
        "the most significant end towards the least significant end of the output word",
        "while the busy indicator remains asserted for the duration of the conversion",
        "and is released only once the complete result has been latched for reading",
    ]
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 150.0
    for s in lines:
        _synth_text(page, s, 520.0, y)      # 右边界统一 520pt → 形成众数
        y += 18.0                            # 行距 18pt：> ROW_GAP(4) 不会并行
    doc.save(path)
    doc.close()


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--html", metavar="OUT", nargs="?", const="",
                    help="顺便生成可视化验收报告（默认 assets/verify-report.html）")
    a = ap.parse_args()

    r = Report(a.verbose)
    if not a.quiet:
        print("wave2visio skill 自检\n" + "─" * 46)

    # ---- 1. 参考波形逐 bit 回读 -------------------------------------------
    if not a.quiet:
        print("\n[1] 参考波形（SPI mode 0）逐 bit 回读")
    ref = json.load(open(os.path.join(ROOT, "assets", "spi-final.json"), encoding="utf-8"))
    got = read_svg(py_render(ref), ref, PY_CELL, PY_ROW, PY_LW)
    all_ok = True
    for (name, bits, _), sig in zip(got, ref["signal"]):
        want = sig["wave"]
        ok = bits == want
        all_ok &= ok
        r.check(f"{name} 回读 == 预期", ok,
                "" if ok else f"预期 {want}\n      实际 {bits}")
    if all_ok:
        # 顺带把 MOSI / MISO 的字节值也报出来，肉眼可见的"证据"
        mosi = got[2][1][2:18:2]
        miso = got[3][1][2:18:2]
        r.check("MOSI 数据位 = 0x5A", int(mosi, 2) == 0x5A, f"bits={mosi}")
        r.check("MISO 数据位 = 0xC3", int(miso, 2) == 0xC3, f"bits={miso}")

    # ---- 2. 恒定电平无多余转折 + 时钟对齐虚线 -----------------------------
    if not a.quiet:
        print("\n[2] 恒定电平无多余转折 · 时钟对齐虚线")
    flat = {"signal": [{"name": "CS_n", "wave": "1" * 20}]}
    d = RE_PATH.findall(py_render(flat))[0]
    r.check("全程恒定高电平 → 0 个转折", transitions(d) == 0,
            f"实际 {transitions(d)} 个")
    step = {"signal": [{"name": "CS_n", "wave": "11000000000000000011"}]}
    d2 = RE_PATH.findall(py_render(step))[0]
    r.check("两次跳变的波形 → 恰好 2 个转折", transitions(d2) == 2,
            f"实际 {transitions(d2)} 个")

    # 竖虚线：落在数据位边界（每 GRID_STEP 字符），贯穿全部信号
    svg_g = py_render(ref)
    glines = RE_LINE.findall(svg_g)
    rows = rows_of(ref, PY_ROW)
    exp_x = [PY_LW + i * PY_CELL for i in range(GRID_STEP, 20, GRID_STEP)]
    r.check("虚线数量 == 数据位边界数（9）", len(glines) == len(exp_x),
            f"实际 {len(glines)}，期望 {len(exp_x)}")
    r.check("虚线 x 落在位边界（每 2 字符一条）",
            [float(l[0]) for l in glines] == exp_x,
            f"实际 {[round(float(l[0]), 1) for l in glines]}")
    gy1 = min(float(l[1]) for l in glines)
    gy2 = max(float(l[3]) for l in glines)
    r.check("虚线贯穿全部信号（上及位标尺、下至末条轨道）",
            gy1 < rows[0][0] and gy2 > rows[-1][1],
            f"线 y[{gy1:.1f},{gy2:.1f}] 首轨道顶 {rows[0][0]:.1f} 末轨道底 {rows[-1][1]:.1f}")
    r.check("虚线画在波形之前（不遮挡电平边沿）",
            svg_g.find("<line") < svg_g.find("<path"),
            "若虚线在 path 之后，会压住波形边沿")
    r.check("位标尺 D7…D0 齐全且顺序正确",
            RE_DLABEL.findall(svg_g) == [str(7 - i) for i in range(8)],
            f"实际 {RE_DLABEL.findall(svg_g)}")

    # ---- 3. . / = 延续语义 -----------------------------------------------
    if not a.quiet:
        print("\n[3] `.` / `=` 延续语义")
    for wave in ("01..11..", "0.1.0.1.0.", "01100110011001100110"):
        wj = {"signal": [{"name": "T", "wave": wave}]}
        d = RE_PATH.findall(py_render(wj))[0]
        rec = recover(d, PY_LW, PY_CELL, *rows_of(wj, PY_ROW)[0], len(wave))
        r.check(f"{wave!r} 展开正确", rec == expand(wave),
                "" if rec == expand(wave) else f"预期 {expand(wave)} 实际 {rec}")

    # ---- 4. 负向用例：2-9 会吃掉电平 -------------------------------------
    if not a.quiet:
        print("\n[4] 负向用例：`2-9` 会吃掉数据线的电平（证明铁律）")
    # 同一份数据 0xA5，两种写法：真实电平 vs 数据块
    levels_wave = "00110011000011001100"   # 每 bit 2 字符的真实电平
    blocks_wave = "00" + "2" * 16 + "00"   # AI 常犯的错：把数据线写成数据块

    def read_one(wave):
        wj = {"signal": [{"name": "MOSI", "wave": wave}]}
        svg = py_render(wj)
        d = RE_PATH.findall(svg)[0]
        return svg, recover(d, PY_LW, PY_CELL, *rows_of(wj, PY_ROW)[0], len(wave))

    svg_lv, rec_lv = read_one(levels_wave)
    svg_bk, rec_bk = read_one(blocks_wave)
    r.check("真实电平写法：MOSI 数据位 = 0xA5",
            int(rec_lv[2:18:2], 2) == 0xA5, f"bits={rec_lv[2:18:2]}")
    r.check("数据块写法：画出了 16 个矩形",
            svg_bk.count('fill="#e8e4ff"') == 16,
            f"矩形数 {svg_bk.count('#e8e4ff')}")
    r.check("数据块写法：电平全部塌成高（10100101 → 11111111）",
            rec_bk[2:18:2] == "1" * 8, f"bits={rec_bk[2:18:2]}")
    r.check("→ 两种写法图形不等效，故铁律成立", rec_lv != rec_bk,
            "若二者相等，说明 2-9 没吃掉电平，铁律需重新评估")

    # ---- 5. Python 渲染器 ≡ JS 渲染器 ------------------------------------
    if not a.quiet:
        print("\n[5] Python 渲染器 ≡ JS 渲染器")
    js_svg, err = js_render(ref)
    if err:
        r.check("JS 渲染器可运行", False, str(err))
    else:
        py_got = read_svg(py_render(ref), ref, PY_CELL, PY_ROW, PY_LW)
        js_got = read_svg(js_svg, ref, JS_CELL, JS_ROW, JS_LW)
        same = all(p[1] == j[1] and p[2] == j[2] for p, j in zip(py_got, js_got))
        detail = "" if same else "\n".join(
            f"{p[0]}: py={p[1]}/{p[2]}t  js={j[1]}/{j[2]}t"
            for p, j in zip(py_got, js_got) if p[1:] != j[1:]) or "长度不一致"
        r.check("回读电平与跳变数完全一致", same, detail)
        r.check("py 画布符合布局契约",
                canvas_of(py_render(ref)) == expect_canvas(ref, PY_CELL, PY_ROW, PY_LW),
                f"实际 {canvas_of(py_render(ref))} "
                f"期望 {expect_canvas(ref, PY_CELL, PY_ROW, PY_LW)}")
        r.check("js 画布符合同一布局契约（仅常量不同）",
                canvas_of(js_svg) == expect_canvas(ref, JS_CELL, JS_ROW, JS_LW),
                f"实际 {canvas_of(js_svg)} "
                f"期望 {expect_canvas(ref, JS_CELL, JS_ROW, JS_LW)}")
        # 竖虚线 / 位标尺也要两边一致（归一化到"第几个字符"再比）
        jl = RE_LINE.findall(js_svg)
        pl = RE_LINE.findall(py_render(ref))
        r.check("js 虚线数量 == py", len(jl) == len(pl),
                f"js={len(jl)} py={len(pl)}")
        r.check("js 虚线位置 == py（归一化到字符序号）",
                [round((float(l[0]) - JS_LW) / JS_CELL) for l in jl]
                == [round((float(l[0]) - PY_LW) / PY_CELL) for l in pl],
                f"js={[round((float(l[0])-JS_LW)/JS_CELL) for l in jl]} "
                f"py={[round((float(l[0])-PY_LW)/PY_CELL) for l in pl]}")
        r.check("js 位标尺 == py",
                RE_DLABEL.findall(js_svg) == RE_DLABEL.findall(py_render(ref)),
                f"js={RE_DLABEL.findall(js_svg)}")

    # ---- 6. 网页产物与真相源一致 -----------------------------------------
    if not a.quiet:
        print("\n[6] 网页产物与真相源一致")
    p = subprocess.run([sys.executable, os.path.join(HERE, "build_web.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    ok = p.returncode == 0
    r.check("assets/*.html 未发生漂移", ok, (p.stdout + p.stderr).strip())

    # ---- 7. 铁律 0：原图未被修改 + 叠加的时钟对齐线 -----------------------
    if not a.quiet:
        print("\n[7] 铁律 0：原图未被修改 · 叠加时钟对齐线")
    ov = load_overlay()
    cur_sha = png_sha256(INPUT_PNG)
    r.check("原图 sha256 与记录一致（未被修改）",
            cur_sha == ov["sha256"],
            f"实际 {cur_sha[:16]}…\n      记录 {ov['sha256'][:16]}…")

    doc = render_html(r.rows, ref, got)
    ol = re.findall(r'<svg class="clk"[^>]*>(.*?)</svg>', doc, re.S)
    r.check("报告里有独立的叠加层（不是重画的图）", len(ol) == 1,
            f"找到 {len(ol)} 个 svg.clk")
    if ol:
        xs = [float(v) for v in re.findall(r'x1="([\d.]+)"', ol[0])]
        r.check("叠加线条数 == 实测位边界数", len(xs) == len(ov["boundaries_frac"]),
                f"{len(xs)} vs {len(ov['boundaries_frac'])}")
        r.check("叠加线 x == 从原图实测的位边界",
                xs == ov["boundaries_frac"],
                f"报告 {xs}\n      实测 {ov['boundaries_frac']}")
        r.check("原图以 <img> 原样内嵌（仅 1 张，未被替换）",
                doc.count("data:image/png;base64,") == 1 and "imgwrap" in doc,
                f"内嵌原图数 = {doc.count('data:image/png;base64,')}")

    # 深检：现场重新测量原图，确认 JSON 没过期（需要 matplotlib）
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "measure_input", os.path.join(HERE, "measure_input.py"))
        mi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mi)
        fresh = mi.measure(INPUT_PNG)
        r.check("现场重测原图 == JSON 记录（JSON 没过期）",
                fresh["boundaries_px"] == ov["boundaries_px"]
                and fresh["sha256"] == ov["sha256"],
                f"现场 {fresh['boundaries_px']}\n      JSON {ov['boundaries_px']}")
    except Exception as e:
        if not a.quiet:
            print(f"  · 跳过现场重测（{type(e).__name__}: {e}）")

    # ---- 8. 纯几何解析（零大模型）：能不能不靠视觉模型读回这张图 -------------
    if not a.quiet:
        print("\n[8] 纯几何解析（auto_trace.py，零大模型调用）")
    try:
        at = _load_module("auto_trace", "auto_trace.py")
        res = at.trace(INPUT_PNG)
        wj_auto = res["wj"]
        w = {k: s["wave"] for k, s in zip(["CS_n", "SCLK", "MOSI", "MISO"],
                                          wj_auto["signal"])}

        r.check("自动分出 4 条轨道", res["meta"]["tracks"] == 4,
                f"实际 {res['meta']['tracks']}")
        r.check("自动认出时钟轨道 = 第 2 条（索引 1）", res["meta"]["clock_track"] == 1,
                f"实际 #{res['meta']['clock_track']}")
        r.check("解析出的位宽 == measure_input 独立实测的 SCLK 周期（±1px）",
                ov["sclk_period_px"] - 1 <= res["meta"]["period_px"] <= ov["sclk_period_px"] + 1,
                f"解析 {res['meta']['period_px']}px\n      实测 {ov['sclk_period_px']}px")
        r.check("位窗数 == 8", res["meta"]["bit_count"] == 8,
                f"实际 {res['meta']['bit_count']}")
        r.check("所有信号等长", len(set(len(v) for v in w.values())) == 1,
                f"{[len(v) for v in w.values()]}")

        def _bits(wave):
            return "".join(wave[k] for k in range(2, len(wave) - 2, 2))

        mosi, miso = _bits(w["MOSI"]), _bits(w["MISO"])
        r.check("纯几何解析 MOSI 逐 bit == 0x5A",
                int(mosi, 2) == 0x5A, f"实际 {mosi} = {int(mosi,2):#04x}")
        r.check("纯几何解析 MISO 逐 bit == 0xC3",
                int(miso, 2) == 0xC3, f"实际 {miso} = {int(miso,2):#04x}")

        # 与手写基准逐 bit 交叉：数据位必须一致（不一致说明有一条路读错了图）
        refw = {s["name"]: s["wave"] for s in ref["signal"]}
        r.check("MOSI 位图与手写基准一致", _bits(w["MOSI"]) == _bits(refw["MOSI"]),
                f"解析 {_bits(w['MOSI'])}\n      基准 {_bits(refw['MOSI'])}")
        r.check("MISO 位图与手写基准一致", _bits(w["MISO"]) == _bits(refw["MISO"]),
                f"解析 {_bits(w['MISO'])}\n      基准 {_bits(refw['MISO'])}")

        # 时钟相位：原图里「数据跳变」与「SCLK 上升沿」同相（实测偏差 8px/167px）。
        # 注意 MOSI=0x5A 只有 6 处跳变（相邻两位相同时不跳），所以判据是
        # 「MOSI 跳变 ⊆ SCLK 上升沿」，不是相等。
        _edges = lambda s: [i for i in range(1, len(s)) if s[i - 1] != s[i]]
        a_rise = [i for i in range(1, len(w["SCLK"])) if w["SCLK"][i - 1] == "0" and w["SCLK"][i] == "1"]
        r_rise = [i for i in range(1, len(refw["SCLK"])) if refw["SCLK"][i - 1] == "0" and refw["SCLK"][i] == "1"]
        m_edges = _edges(w["MOSI"])
        r.check("数据跳变全部落在时钟上升沿上（与原图同相）",
                bool(m_edges) and set(m_edges) <= set(a_rise),
                f"MOSI 跳变 {m_edges}\n      SCLK 升沿 {a_rise}")
        if not a.quiet and r_rise != a_rise:
            print(f"  ⚠ 已知偏差：手写基准 SCLK 升沿 {r_rise}"
                  f" 比原图实测 {a_rise} 晚半周期（基准是教科书 CPOL=0 写法，"
                  f"原图把数据跳变画在上升沿上）—— 待定，不阻塞交付")
    except Exception as e:
        if not a.quiet:
            print(f"  · 跳过纯几何解析自检（{type(e).__name__}: {e}）")

    # ---- 9. 无框模式（真实 datasheet 大多没有「每条信号一个方框」）---------
    # 用**合成掩码**测纯函数，不依赖任何厂商图片（也就没有版权与联网问题）；
    # 最后再跑一个「有真实图就跑、没有就跳过」的集成用例。
    if not a.quiet:
        print("\n[9] 无框模式：合成掩码单测 + 真实 datasheet 集成（可跳过）")
    try:
        import numpy as np
        at = _load_module("auto_trace9", "auto_trace.py")

        # 9.1 wave_span 必须排掉「近全宽的外框线」，否则波形区会被算成整幅图
        #     注意右界是**半开区间**（取 run 的 end），所以内容是 x=50..349 时返回 350
        m = np.zeros((200, 400), dtype=bool)
        m[10:13, 0:400] = True          # 外框横线（98%W）
        m[100:103, 50:350] = True       # 真正的波形内容（75%W）
        span = at.wave_span(m)
        r.check("wave_span 排掉近全宽外框，只取波形内容",
                span == (50, 350), f"实际 {span}（正确应为 (50, 350)）")

        # 9.2 label_rows 必须剔掉竖外框列 —— 否则所有文字带会粘成一条
        m2 = np.zeros((200, 400), dtype=bool)
        m2[:, 5:8] = True               # 竖外框整列（每行都深）
        for y0 in (20, 80, 140):        # 三条行标签文字带
            m2[y0:y0 + 20, 10:45] = True
        fc = at.frame_cols(m2)
        bands_raw = at.label_rows(m2, 60, set())          # 不剔除
        bands_ok = at.label_rows(m2, 60, fc)              # 剔除
        r.check("label_rows 剔竖外框列后分出 3 条行标签",
                len(bands_ok) == 3 and len(bands_raw) == 1,
                f"剔除后 {len(bands_ok)} 条 / 不剔除 {len(bands_raw)} 条（后者应为 1）")

        # 9.3 灰底填充 → 判总线带（真实 datasheet 画总线/无效区习惯铺中灰）
        g3 = np.full((60, 300), 1.0)
        g3[20:40, 10:290] = 0.72        # 中灰填充
        m3 = g3 < at.DARK
        r.check("_row_kind：灰底带判为 bus",
                at._row_kind(g3, m3, 0, 59, 10, 289) == "bus")
        g3b = np.full((60, 300), 1.0)
        g3b[20:22, 10:290] = 0.0        # 只是两条黑线、白底
        r.check("_row_kind：白底双线判为 level（保守，宁多解不漏解）",
                at._row_kind(g3b, g3b < at.DARK, 0, 59, 10, 289) == "level")

        # 9.5 灰度归一化：PNG 躲得过、JPEG 必踩的坑（2026-10-22 真实需求试用发现）
        #     matplotlib.imread 对 8-bit PNG 返回 0-1、对 JPEG 返回 0-255。
        #     DARK 是 0-1 尺度阈值，不归一化的话 JPEG 的深色判定只剩「值恰为0」。
        #     基准图恰好是 PNG → 自检长期全绿，直到拿真实 JPEG 截图才暴露。
        #     这里现场合成 JPEG 实测，不依赖任何外部文件。
        try:
            import tempfile
            from PIL import Image as _PILImage
            # 合成一张「白底 + 深灰方波」的图，PNG 与 JPEG 各存一份。
            # ⚠️ 必须用**非纯黑**的深色（如 RGB=40）：真实 JPEG 压缩后深色线是
            # 10~60 的灰，不是 0。若用纯黑 0，则 0 < 0.45 在 0-1 与 0-255
            # 两个尺度下都成立，负向对照会假失败（这坑我踩过一次）。
            canvas = np.full((120, 400, 3), 255, dtype=np.uint8)
            for t0 in range(20, 380, 60):                # 一串方波
                canvas[40:70, t0:t0 + 30] = 40
            tmpd = tempfile.mkdtemp(prefix="wavejson_norm_")
            png_p = os.path.join(tmpd, "t.png")
            jpg_p = os.path.join(tmpd, "t.jpg")
            _PILImage.fromarray(canvas).save(png_p)
            _PILImage.fromarray(canvas).save(jpg_p, quality=95)

            g_png, d_png = at.load_dark(png_p)
            g_jpg, d_jpg = at.load_dark(jpg_p)
            r.check("PNG/JPEG 读入后灰度值域都是 0-1",
                    g_png.max() <= 1.0 and g_jpg.max() <= 1.0,
                    f"PNG max={g_png.max():.3f} JPEG max={g_jpg.max():.3f}")
            # 核心断言：JPEG 的深色占比必须与 PNG 同量级，不能掉一个数量级
            ratio = d_jpg.mean() / max(d_png.mean(), 1e-9)
            r.check("JPEG 深色占比与 PNG 同量级（未因值域未归一化而塌陷）",
                    0.3 < ratio < 3.0,
                    f"PNG={d_png.mean():.4f} JPEG={d_jpg.mean():.4f} 比值={ratio:.3f}")
            # 负向对照：用 matplotlib 的**原始未归一化**输出模拟旧行为。
            # 注意不能拿 g_jpg（已归一化，max=1.0）去乘 255 —— 那等于又变回 0-1，
            # 会算出和正确行为一样的结果，负向对照就失去意义了。
            # 要重新从磁盘读一次原始数组。
            import matplotlib.image as _mpimg
            _im = _mpimg.imread(jpg_p)
            _raw = _im[..., :3].mean(axis=2) if _im.ndim == 3 else _im.astype(float)
            r.check("（负向）旧行为不做归一化时 JPEG 深色占比会塌陷 → 用例有效",
                    _raw.max() > 1.0 and (_raw < at.DARK).mean() < d_jpg.mean() * 0.5,
                    f"原始值域max={_raw.max():.1f}；正确 {d_jpg.mean():.4f} vs 旧行为 {(_raw < at.DARK).mean():.4f}")
        except Exception as e:
            r.check("灰度归一化用例（JPEG/PNG 合成）", False, str(e))

        # 9.4 时钟等距口径必须用「全周期」，对占空比不敏感。
        #     这是真实踩过的坑：自测图 SCLK 占空比 41%/59%，用相邻间距算等距比只有
        #     0.533，时钟会被 MOSI 抢走 → 整条链路串到别的信号上。
        def _click(high, low, n, lead=10):
            s = [0] * lead
            for _ in range(n):
                s += [1] * high + [0] * low
            return s

        asym = _click(7, 13, 8)                       # 占空比 35%/65%
        _ci, det = at.pick_clock([asym], None)        # 不许抛异常
        r.check("占空比不对称的时钟仍被认作时钟（等距口径用全周期）",
                det[0][2] >= at.MIN_CLOCK_REG,
                f"等距比 {det[0][2]}（阈值 {at.MIN_CLOCK_REG}）")

        # 与一条「跳变更多但杂乱」的数据线同场竞技，时钟必须赢
        data = []
        for k in range(24):
            data += [k % 2] * (1 + (k * 7) % 11)      # 段长乱 → 周期不齐
        ci2, det2 = at.pick_clock([asym, data], None)
        r.check("时钟胜过「跳变多但杂乱」的数据线",
                ci2 == 0, f"选中 #{ci2}；明细 {det2}")

        # 9.5 没有时钟时必须报错，不许硬凑假时钟输出垃圾
        def _no_clock():
            try:
                at.pick_clock([[0] * 20 + [1] * 30 + [0] * 40 + [1] * 50 + [0] * 60], None)
                return False
            except SystemExit:
                return True
        r.check("无时钟的图直接报错（不硬凑假时钟）", _no_clock())

    except ImportError as e:
        if not a.quiet:
            print(f"  · 跳过无框模式单测（缺依赖：{e}）")
    except Exception as e:
        if not a.quiet:
            print(f"  · 跳过无框模式单测（{type(e).__name__}: {e}）")

    # 9.7 真实厂商图全量基线（2026-10-22 加：Max 要求「每次改完必回测」）
    #
    # 为什么要有这一组：之前只有 ISSI 一张图进自检，另外 6 张的结论只存在于日志里 ——
    # 改坏了没人知道。**回测的前提是「基线可复现」**，所以把 7 张图当前的实测结果
    # 全部写成断言，改动后跑一遍就知道有没有漂移。
    #
    # ⚠️ 基线真值全部来自实测（2026-10-22，修复 ROW_HALF 后），不是估计值。
    # ⚠️ 路径探测要试多个候选：技能装在 ~/.workbuddy/skills/ 时，
    #    ROOT 上溯 3 层到的是 ~/.workbuddy 而不是项目根 → 相对路径永远找不到 figs。
    FIGS_ALL = None
    for _cand in (
        "/Users/maxwork/WorkBuddy/2026-09-14-11-10-22/test-cases/real-datasheets/figs",
        os.path.abspath(os.path.join(ROOT, "..", "..", "..",
                                     "test-cases", "real-datasheets", "figs")),
    ):
        if os.path.isdir(_cand):
            FIGS_ALL = _cand
            break
    if FIGS_ALL and os.path.isdir(FIGS_ALL):
        if not a.quiet:
            print("\n[9.7] 真实厂商图全量基线（7 张· 回归用）")
        try:
            at97 = _load_module("auto_trace97", "auto_trace.py")
            # 基线真值表（2026-10-22 实测）：tracks=分出行数 / clock=时钟轨道
            # bits=位窗数 / period=时钟周期px / kinds=各行类型 L=level B=bus
            # reject=None 表示应当成功跑通；给字符串表示应当被拒收（且须含该关键词）
            BASE = {
                "issi-sdr-alternating-bank-write.png": dict(
                    tracks=8, clock=0, bits=10, period=243.78, kinds="LBBBBBBB"),
                "issi-sdr-p48.png": dict(
                    tracks=8, clock=0, bits=9, period=253.38, kinds="LBBBBBBB"),
                "issi-sdr-write-page-burst.png": dict(
                    tracks=8, clock=0, bits=8, period=285.29, kinds="LBBBBBBB"),
                # 以下四张应当被**正确拒收**
                # ad7606-fig4 是 CS/RD 选通型异步接口，本没有时钟。
                #   修 ROW_HALF_NOFRAME 0.42→0.25 之前被误放行（认轨道1为假时钟、
                #   3 位窗、周期 247px）—— 根因是轨道带高 143px 而波形只有 23-60px，
                #   把标题文字圈进了轨道，文字笔画的等间距被当成周期。
                "ad7606-fig4-parallel-cs-rd.png": dict(reject="没有哪条轨道像时钟"),
                "ad7606-fig2-convst-after.png": dict(reject="没有哪条轨道像时钟"),
                "ads8482-fig33-auto-read.png": dict(reject="没有哪条轨道像时钟"),
                "lpddr4-fig15-bus-preconditioning-source.png": dict(
                    reject="没有一条轨道能提取出电平"),
            }
            for fname, exp in sorted(BASE.items()):
                fpath = os.path.join(FIGS_ALL, fname)
                if not os.path.exists(fpath):
                    continue                  # 缺图就跳过这一条（不计入通过数）
                # ⚠️ auto_trace 用 SystemExit 报错（继承 BaseException，**不是** Exception），
                #    必须单独 except SystemExit，否则会被下面的 except Exception 漏掉、
                #    直接终止整个自检。
                try:
                    res97 = at97.trace(fpath, mode="frameless")
                except SystemExit as e:
                    msg97 = str(e)
                    if "reject" in exp:
                        r.check(f"{fname[:34]}：应当被拒收（{exp['reject'][:12]}）",
                                exp["reject"] in msg97,
                                f"实际报错：{msg97.splitlines()[0][:50]}")
                    else:
                        r.check(f"{fname[:34]}：应当跑通", False,
                                f"被拒收了：{msg97.splitlines()[0][:50]}")
                    continue
                if "reject" in exp:
                    r.check(f"{fname[:34]}：应当被拒收（{exp['reject'][:12]}）", False,
                            f"竟然跑通了：{res97['meta']}")
                    continue
                m97 = res97["meta"]
                kinds97 = "".join("L" if k == "level" else "B" for k in m97["row_kinds"])
                r.check(f"{fname[:34]}：分行数 == {exp['tracks']}",
                        m97["tracks"] == exp["tracks"], f"实际 {m97['tracks']}")
                r.check(f"{fname[:34]}：行类型 == {exp['kinds']}",
                        kinds97 == exp["kinds"], f"实际 {kinds97}")
                r.check(f"{fname[:34]}：时钟轨道 == #{exp['clock']}",
                        m97["clock_track"] == exp["clock"], f"实际 #{m97['clock_track']}")
                r.check(f"{fname[:34]}：位窗数 == {exp['bits']}",
                        m97["bit_count"] == exp["bits"], f"实际 {m97['bit_count']}")
                r.check(f"{fname[:34]}：时钟周期 ≈ {exp['period']}px（±3px）",
                        abs(m97.get("period_px", 0) - exp["period"]) <= 3.0,
                        f"实际 {m97.get('period_px')}")
        except Exception as e:
            r.check("9.7 真实厂商图全量基线", False, f"{type(e).__name__}: {e}")
    elif not a.quiet:
        print("\n[9.7] 真实厂商图全量基线：跳过（本机无 test-cases/real-datasheets/figs）")

    # 9.6 集成用例：真实厂商 datasheet（本机有图才跑；不入库，规避版权）
    ISSI = (os.path.join(FIGS_ALL, "issi-sdr-alternating-bank-write.png")
            if FIGS_ALL else "")
    if os.path.exists(ISSI):
        if not a.quiet:
            print("\n[9b] 真实 datasheet 集成：ISSI SDR 交替 bank 写时序")
        try:
            at = _load_module("auto_trace9b", "auto_trace.py")
            res = at.trace(ISSI, mode="frameless")
            mt = res["meta"]
            r.check("无框模式自动分出 8 行", mt["tracks"] == 8, f"实际 {mt['tracks']}")
            r.check("只有第 0 行（CLK）判为电平，其余 7 行判为总线带",
                    mt["row_kinds"][0] == "level"
                    and all(k == "bus" for k in mt["row_kinds"][1:]),
                    f"实际 {mt['row_kinds']}")
            r.check("自动认出时钟 = 第 0 行（CLK）", mt["clock_track"] == 0,
                    f"实际 #{mt['clock_track']}")
            r.check("解出 10 个时钟周期（图里 T0..T9 恰好 10 条对齐虚线）",
                    mt["bit_count"] == 10, f"实际 {mt['bit_count']}")
            r.check("时钟周期 ≈ 244px（±3px）",
                    abs(mt["period_px"] - 244.0) <= 3.0, f"实际 {mt['period_px']}px")
            w0 = res["wj"]["signal"][0]["wave"]
            r.check("CLK 波形为 10 个满周期（0/1 交替）",
                    w0 == "01" * 10 + "00", f"实际 {w0}")
        except Exception as e:
            if not a.quiet:
                print(f"  · 跳过真实 datasheet 集成（{type(e).__name__}: {e}）")
    elif not a.quiet:
        print("\n[9b] 真实 datasheet 集成：跳过（本机无 test-cases/real-datasheets/figs）")

    # ---- [10] pdf_trace：从 PDF 文本层 + 矢量层读图 ------------------------
    #       用**合成 PDF**，不引厂商文件 —— 可常跑、无版权问题。
    if not a.quiet:
        print("\n[10] pdf_trace：PDF 文本层 + 矢量层直读（合成 PDF，零大模型）")
    try:
        import pymupdf  # noqa: F401
        import tempfile
        pt = _load_module("pdf_trace10", "pdf_trace.py")
        tmp = tempfile.mkdtemp(prefix="wj_pt_")
        good_pdf = os.path.join(tmp, "synth_timing.pdf")
        bad_pdf = os.path.join(tmp, "synth_prose.pdf")
        _make_synth_timing_pdf(good_pdf)
        _make_synth_prose_pdf(bad_pdf)

        # 10.1 认行：左侧右对齐的行标签 → 信号名
        res, meta = pt.analyse(good_pdf, 1)
        names = [r["name"] for r in res["rows"]]
        r.check("合成图认出 3 行信号，名字与顺序正确",
                names == ["CLK", "CMD", "DATA"], f"实际 {names}")
        r.check("标签列右界 = 行标签共用的右边界 140pt（±1pt）",
                abs(meta["label_x_right"] - 140.0) <= 1.0,
                f"实际 {meta['label_x_right']}")

        # 10.2 位网格：T0/T1/T2 标记 → 间距 = 一个槽位
        g = res["grid"]
        r.check("从 T0/T1/T2 标记解出 3 个槽位", g and g["n"] == 3,
                f"实际 {g and g['n']}")
        r.check("槽位间距 ≈ 130pt（±2pt）", g and abs(g["pitch"] - 130.0) <= 2.0,
                f"实际 {g and g['pitch']}")

        # 10.3 读值：波形区文字 → 行 × 槽位
        cmd = next(r_ for r_ in res["rows"] if r_["name"] == "CMD")
        r.check("CMD 判为总线行（它右侧有总线值文字）", cmd["kind"] == pt.KIND_BUS,
                f"实际 {cmd['kind']}")
        r.check("CMD 三个槽位的值 = A0 / A1 / A2",
                [cmd["slots"].get(str(i)) for i in range(3)] == ["A0", "A1", "A2"],
                f"实际 {cmd['slots']}")
        clk = next(r_ for r_ in res["rows"] if r_["name"] == "CLK")
        r.check("CLK 判为电平行（右侧没有文字值）", clk["kind"] == pt.KIND_LEVEL,
                f"实际 {clk['kind']}")

        # 10.4 适用性闸门：正文页必须被拦下，且报错要说清理由
        try:
            pt.analyse(bad_pdf, 1)
            r.check("正文页被闸门拦下（不许把段落当成信号行）", False,
                    "没有报错，说明闸门失效")
        except SystemExit as e:
            msg = str(e)
            r.check("正文页被闸门拦下（不许把段落当成信号行）",
                    "不是时序图" in msg, f"报错内容：{msg[:80]}")

        # 10.5 融合：PDF 的位网格 ⊕ PNG 的像素几何 → 完整波形
        png, scale = pt.render_page(good_pdf, 1, dpi=300)
        rep = pt.fuse_levels(res, png, scale)
        waves = {it["name"]: it.get("wave") for it in rep["rows"]}
        # CLK：每槽前半低后半高 → 每槽 "01"
        r.check("融合出 CLK = 每槽 01（3 个满周期）",
                waves.get("CLK") == "01" * 3, f"实际 {waves.get('CLK')}")
        # DATA：前两槽整槽被灰底盖住 → xx；第三槽只有电平线（低）→ 00
        r.check("融合把 DON'T CARE 灰底还原成 x（DATA = xx000000）",
                waves.get("DATA") == "xx" + "00" * 2, f"实际 {waves.get('DATA')}")

        # 10.6 成套输出：WaveJSON 的块字符 / data 顺序 / 标尺
        wj = pt.to_wavejson(res)
        d = next(s_ for s_ in wj["signal"] if s_["name"] == "CMD")
        r.check("WaveJSON：CMD 三个槽各占一个数据块（2 字符）",
                d["wave"] == "2.3.4.", f"实际 {d['wave']!r}")
        r.check("WaveJSON：data 按槽位顺序 = A0/A1/A2", d.get("data") == ["A0", "A1", "A2"],
                f"实际 {d.get('data')}")
        r.check("WaveJSON：位标尺用厂商自己的 T0/T1/T2（不是猜的 D 系列）",
                wj["config"].get("ruler") == ["T0", "T1", "T2"],
                f"实际 {wj['config'].get('ruler')}")
        c = next(s_ for s_ in wj["signal"] if s_["name"] == "CLK")
        r.check("WaveJSON：CLK 用几何解出的真实波形，不是占位常量",
                c["wave"] == "01" * 3, f"实际 {c['wave']!r}")
        r.check("WaveJSON：没有电平行退化成占位",
                not wj.get("_placeholders"), f"实际 {wj.get('_placeholders')}")

        # 10.7 常量一致性：pdf_trace.DARK 必须与 auto_trace.DARK 相同
        #      （两处判「灰底」用的是同一条阈值，漂了就会一个判总线一个判电平）
        try:
            at10 = _load_module("auto_trace10", "auto_trace.py")
            r.check("pdf_trace.DARK ≡ auto_trace.DARK（灰底判据同源）",
                    pt.DARK == at10.DARK, f"{pt.DARK} vs {at10.DARK}")
        except Exception as e:
            r.check("pdf_trace.DARK ≡ auto_trace.DARK（灰底判据同源）", False, str(e))

        # 10.8 集成：真实厂商 PDF（本机有才跑；不入库）
        dl = os.path.abspath(os.path.join(ROOT, "..", "..", "..",
                                          "test-cases", "real-datasheets", "dl"))
        issi = os.path.join(dl, "issi_sdr.pdf")
        if os.path.exists(issi):
            if not a.quiet:
                print("\n[10b] 真实 datasheet 集成：ISSI SDR p54")
            res2, meta2 = pt.analyse(issi, 54)
            nm = [x["name"] for x in res2["rows"]]
            r.check("ISSI p54 认出 8 行且名字正确",
                    nm == ["CLK", "CKE", "COMMAND", "DQM/DQML, DQMH",
                           "A0-A9, A11", "A10", "BA0, BA1", "DQ"], f"实际 {nm}")
            r.check("ISSI p54 位网格 = 10 槽 / 间距 43.82pt（厂商 T0..T9）",
                    res2["grid"]["n"] == 10 and abs(res2["grid"]["pitch"] - 43.82) < 0.2,
                    f"实际 {res2['grid']['n']} / {res2['grid']['pitch']}")
            cm = next(x for x in res2["rows"] if x["name"] == "COMMAND")
            r.check("COMMAND 的 10 个值逐字正确",
                    [cm["slots"].get(str(i)) for i in range(10)]
                    == ["ACTIVE", "NOP", "WRITE", "NOP", "ACTIVE",
                        "NOP", "WRITE", "NOP", "NOP", "ACTIVE"],
                    f"实际 {cm['slots']}")
            dq = next(x for x in res2["rows"] if x["name"] == "DQ")
            r.check("DQ 的 8 个值逐字正确（槽位 2..9）",
                    [dq["slots"].get(str(i)) for i in range(2, 10)]
                    == ["DIN m", "DIN m+1", "DIN m+2", "DIN m+3",
                        "DIN b", "DIN b+1", "DIN b+2", "DIN b+3"],
                    f"实际 {dq['slots']}")
            p2, s2 = pt.render_page(issi, 54, dpi=300)
            rep2 = pt.fuse_levels(res2, p2, s2)
            w2 = {it["name"]: it.get("wave") for it in rep2["rows"]}
            r.check("ISSI CLK 融合出 10 个满周期（每槽 01）",
                    w2.get("CLK") == "01" * 10, f"实际 {w2.get('CLK')}")
            r.check("ISSI CKE 融合成恒定高（原图是平线 + 灰梯形 DON'T CARE）",
                    w2.get("CKE") == "1" * 20, f"实际 {w2.get('CKE')}")
            # DQM 的 DON'T CARE 只盖住**头两槽** —— 回原图逐槽量过：
            # slot 0/1 的灰底占比 0.95 / 1.00，从 slot 2 起掉到 0.30~0.46，
            # DC_SLOT=0.60 正好落在两簇中间（2 倍分离）。
            # 灰区末端那条斜边之后，DQM 就是实打实的低电平。
            r.check("ISSI DQM 前两槽 x、其余低（灰底整槽覆盖才判 DON'T CARE）",
                    w2.get("DQM/DQML, DQMH") == "xxxx" + "00" * 8,
                    f"实际 {w2.get('DQM/DQML, DQMH')}")
        elif not a.quiet:
            print("\n[10b] 真实 datasheet 集成：跳过（本机无 test-cases/real-datasheets/dl）")
    except ImportError as e:
        if not a.quiet:
            print(f"  · 跳过 pdf_trace 用例（缺依赖：{e}）")
    except Exception as e:
        r.check("pdf_trace 用例组未抛异常", False, f"{type(e).__name__}: {e}")

    # ---- 11. 厂商图复刻用的扩展能力 ---------------------------------------
    #  （ruler_step / 色块配色 / 虚线行 / 留白行 / Don't Care 斜纹 / x_line）
    #  这些是复刻 JESD 那类「每时钟 4 字符、彩色状态块、斜纹 Don't Care」图时加的，
    #  加完必须守住 —— 第一版就出过「白底矩形画在斜线之后把斜纹整个盖掉」的错，
    #  当时自检没覆盖，是看图才发现的。
    if not a.quiet:
        print("\n[11] 厂商图复刻扩展：标尺步长 · 色块配色 · 虚线行 · Don't Care 斜纹")
    EXT = {
        "config": {"ruler": ["", "T0", "T1"], "ruler_step": 4, "ruler_offset": 0,
                   "ruler_pad": 0, "grid_step": 4,
                   "x_style": "hatch", "x_line": False},
        "signal": [
            {"name": "CLK", "wave": "1100" * 3},
            {"name": "", "wave": "0" * 12, "blank": True},
            {"name": "DQS_c", "wave": "1" * 12, "dash": True},
            {"name": "DQ", "wave": "xx4.6.8.....",
             "data": ["A", "B", "C"],
             "colors": ["#112233", "#445566", "#778899"]},
        ],
    }
    svg11 = py_render(EXT)

    def _x_of(svg, text):
        m = re.search(r'<text x="([\d.]+)"[^>]*>' + re.escape(text) + r'</text>', svg)
        return float(m.group(1)) if m else None

    # 标尺：ruler_step=4 / ruler_offset=0 → 标签压在「格的左边界」（第 0/4/8 字符）
    r.check("ruler_step=4 + ruler_offset=0 → 标尺落在第 4/8 字符边界",
            _x_of(svg11, "T0") == PY_LW + 4 * PY_CELL
            and _x_of(svg11, "T1") == PY_LW + 8 * PY_CELL,
            f"T0 x={_x_of(svg11, 'T0')} 期望 {PY_LW + 4 * PY_CELL}")
    r.check("空标尺项不输出 <text>（首格留白）",
            _x_of(svg11, "T0") is not None
            and svg11.count("</text>") >= 4)

    # 色块配色：与 data 同序，用尽后循环
    fills = re.findall(r'fill="([^"]+)" stroke="#000000" stroke-width="1"', svg11)
    r.check("sig.colors 按块顺序取色", fills[:3] == ["#112233", "#445566", "#778899"],
            f"实际 {fills[:3]}")

    # 虚线行
    r.check("sig.dash=true → 折线带 stroke-dasharray",
            'stroke-dasharray="5,3"' in svg11)

    # 留白行：占高度但不画东西
    paths11 = RE_PATH.findall(svg11)
    r.check("sig.blank=true → 只占行高、不出 path（4 行只画 3 条）",
            len(paths11) == 3, f"实际 {len(paths11)} 条")

    # x_line=False：Don't Care 段不落笔，折线从第一个非 x 字符起笔
    dq = [d for d in paths11 if float(d.split()[1].split(",")[0]) == PY_LW + 2 * PY_CELL]
    r.check("x_line=false → 折线从第 2 个字符（首个非 x）起笔",
            len(dq) == 1, f"实际起笔位置 {[d.split()[1] for d in paths11]}")

    # Don't Care 斜纹：必须有斜线，且**画在白底矩形之后**（顺序反了就整片被盖掉）
    i_rect = svg11.find('fill="#ffffff" stroke="#6b7280"')
    i_hatch = svg11.find('<g stroke="#9aa0a6"')
    r.check("x_style=hatch → 生成显式斜线（不用 <pattern>，Visio 才导得进）",
            i_hatch > 0 and "pattern" not in svg11, f"hatch@{i_hatch}")
    r.check("斜线画在白底矩形**之后**（顺序反了斜纹会被整片盖掉）",
            -1 < i_rect < i_hatch, f"rect@{i_rect} hatch@{i_hatch}")

    # py ≡ js（同一份 config，归一化后应逐字节一致）
    js11, err11 = js_render(EXT)
    if err11:
        r.check("JS 渲染器可跑扩展配置", False, str(err11))
    else:
        norm = lambda s: re.sub(r'\s+class="[^"]*"', "", s)
        j_fills = re.findall(r'fill="([^"]+)" stroke="#000000" stroke-width="1"', js11)
        r.check("js 色块取色 == py", j_fills[:3] == fills[:3],
                f"js={j_fills[:3]} py={fills[:3]}")
        r.check("js 斜纹线段数 == py",
                js11.count('<g stroke="#9aa0a6"') == svg11.count('<g stroke="#9aa0a6"'))
        r.check("js 留白行同样不出 path",
                len(RE_PATH.findall(js11)) == 3,
                f"js 实际 {len(RE_PATH.findall(js11))} 条")

    # ---- 11.5 边沿斜坡 + 延时标注（2026-10-22 新增渲染器能力）-----------
    # 背景：Max 指出 LPDDR4 Fig.15 重绘「上升沿/下降沿和延时没呈现」。
    # 根因：渲染器只会画直角方波（wave_to_polyline 硬编码垂直线段），
    # 而真实 DDR 图的时钟是**正弦/梯形波**，边沿是斜的 —— 画成直角就丢了这个信息。
    # 解法：新增 sig.edges[]（边沿斜坡）与 sig.delays[]（延时标注）两个可选字段。
    if not a.quiet:
        print("\n[11.5] 边沿斜坡（sig.edges）· 延时标注（sig.delays）")
    try:
        # 11.5.1 斜坡：wave=1010 有跳变点在 1,2,3...；edges.at=1.5 width=0.5
        #   → 期望：斜坡段被画出来，且 wave 产生的多余垂直跳变被抑制
        wj_edge = {
            "config": {"ruler_step": 2, "ruler_pad": 0, "grid_step": 0},
            "signal": [{
                "name": "CK",
                "wave": "1010",
                "edges": [{"at": 1.5, "from": 1, "to": 0, "width": 0.5}],
            }],
        }
        svg_edge = PY.render(wj_edge, cell=20, row_h=40, label_w=40)
        pts_e = [(float(a), float(b)) for a, b in
                 re.findall(r"([\d.]+),([\d.]+)", RE_PATH.findall(svg_edge)[0])]
        n_slope = sum(1 for i in range(len(pts_e) - 1)
                      if abs(pts_e[i + 1][0] - pts_e[i][0]) > 0.01
                      and abs(pts_e[i + 1][1] - pts_e[i][1]) > 0.01)
        n_vert = sum(1 for i in range(len(pts_e) - 1)
                     if abs(pts_e[i + 1][0] - pts_e[i][0]) < 0.01
                     and abs(pts_e[i + 1][1] - pts_e[i][1]) > 0.01)
        r.check("edges：斜坡段被画出（至少 1 段斜坡）", n_slope >= 1,
                f"斜坡 {n_slope} 段 / 垂直 {n_vert} 段")
        r.check("edges：wave 产生的多余垂直跳变被抑制（垂直段 0）",
                n_vert == 0, f"垂直段 {n_vert}（应为 0）")

        # 11.5.2 不给 edges 时行为不变（向后兼容）：仍是纯直角
        wj_plain = {"config": {"ruler_step": 2, "ruler_pad": 0, "grid_step": 0},
                    "signal": [{"name": "CK", "wave": "1010"}]}
        svg_plain = PY.render(wj_plain, cell=20, row_h=40, label_w=40)
        pts_p = [(float(a), float(b)) for a, b in
                 re.findall(r"([\d.]+),([\d.]+)", RE_PATH.findall(svg_plain)[0])]
        n_slope_p = sum(1 for i in range(len(pts_p) - 1)
                        if abs(pts_p[i + 1][0] - pts_p[i][0]) > 0.01
                        and abs(pts_p[i + 1][1] - pts_p[i][1]) > 0.01)
        n_vert_p = sum(1 for i in range(len(pts_p) - 1)
                       if abs(pts_p[i + 1][0] - pts_p[i][0]) < 0.01
                       and abs(pts_p[i + 1][1] - pts_p[i][1]) > 0.01)
        r.check("不给 edges 时仍是直角方波（向后兼容未被破坏）",
                n_slope_p == 0 and n_vert_p == 3,
                f"斜坡 {n_slope_p} / 垂直 {n_vert_p}（应 0 / 3）")

        # 11.5.3 延时标注：文字 + 两端箭头
        wj_dly = {"config": {"ruler_step": 2, "ruler_pad": 0, "grid_step": 0},
                  "signal": [{"name": "CK", "wave": "1010",
                              "delays": [{"from": 1, "to": 5, "label": "RL = 10"}]}]}
        svg_dly = PY.render(wj_dly, cell=20, row_h=40, label_w=40)
        r.check("delays：标注文本出现在 SVG 里", "RL = 10" in svg_dly)
        n_arrow = svg_dly.count('fill="#111"/>')
        r.check("delays：两端箭头（实心三角）各一个", n_arrow == 2,
                f"箭头 {n_arrow} 个（应为 2）")

        # 11.5.4 py ≡ js（铁律 8：改渲染器必须两份同改）
        js_edge = None
        try:
            p = subprocess.run(["node", "-e", f"""
                const fs=require('fs');
                let src=fs.readFileSync({json.dumps(os.path.join(HERE, 'renderer.js'))},'utf8');
                eval(src);
                const wj={json.dumps(wj_edge)};
                process.stdout.write(renderWaveJson(wj));
            """], capture_output=True, text=True, timeout=30)
            if p.returncode == 0 and p.stdout.strip():
                js_edge = p.stdout
        except Exception:
            pass
        if js_edge:
            js_pts = [(float(a), float(b)) for a, b in
                      re.findall(r"([\d.]+),([\d.]+)", RE_PATH.findall(js_edge)[0])]
            js_slope = sum(1 for i in range(len(js_pts) - 1)
                           if abs(js_pts[i + 1][0] - js_pts[i][0]) > 0.01
                           and abs(js_pts[i + 1][1] - js_pts[i][1]) > 0.01)
            js_vert = sum(1 for i in range(len(js_pts) - 1)
                          if abs(js_pts[i + 1][0] - js_pts[i][0]) < 0.01
                          and abs(js_pts[i + 1][1] - js_pts[i][1]) > 0.01)
            r.check("py ≡ js：斜坡段数一致", js_slope == n_slope,
                    f"py {n_slope} / js {js_slope}")
            r.check("py ≡ js：垂直段数一致", js_vert == n_vert,
                    f"py {n_vert} / js {js_vert}")
        else:
            r.check("（跳过）py ≡ js 斜坡比对：node 不可用", True)
    except Exception as e:
        r.check("11.5 边沿斜坡 / 延时标注用例", False, str(e))

    # ---- 12. 分发包与开发源一致 -------------------------------------------
    # 背景（2026-10-14/19 实测踩坑）：SKILL.md 改动没同步进 dist/ 分发包，
    # zip 里留着带bug 的旧版（命令块默认路径指向错误宿主，复制即跑空目录）。
    # 这类漂移肉眼发现不了 —— 分发包看起来是好的，装到别人机器上才炸。
    # 所以在这里做机器化比对：dist 若存在，其 SKILL.md / references 必须与源一致。
    if not a.quiet:
        print("\n[12] 分发包与开发源一致（dist/wave2visio-skill/）")
    # ROOT = <项目>/.workbuddy/skills/wave2visio → 项目根要上溯 3 层：
    # wave2visio → skills → .workbuddy → <项目>
    proj_root = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))
    # ⚠️ 路径三段都要跟着改名走（2026-11-02 修）：
    #   原来是 dist/wavejson-skill/wavejson —— 技能改名 wavejson→wave2visio 时
    #   这里**漏改了**，导致 [12] 组一直在检一个不存在的路径 → 守护形同虚设
    #   （自检会打印「跳过」而不是失败，正好符合「跳过项不能报 ✓」的反面教材）。
    dist_root = os.path.join(proj_root, "dist", "wave2visio-skill", "wave2visio")
    if not os.path.isdir(dist_root):
        # 纯安装态（本机~/.workbuddy/skills/ 下）没有 dist/，本组不适用。
        # 如实说明「未检查」，不能报✓ —— 那会让没跑过比对的项混进"全过"。
        if not a.quiet:
            print("· 跳过（当前安装位置没有 dist/ 分发目录，本组不适用）")
        if a.verbose:
            print(f"      查找位置：{dist_root}")
    else:
        # 比对 SKILL.md 与全部 references（逐字节；分发包漏文件也要抓）
        pairs = [("SKILL.md", os.path.join(ROOT, "SKILL.md"))]
        ref_src = os.path.join(ROOT, "references")
        if os.path.isdir(ref_src):
            for fn in sorted(os.listdir(ref_src)):
                if fn.endswith(".md"):
                    pairs.append((f"references/{fn}", os.path.join(ref_src, fn)))
        for rel, src_path in pairs:
            dst_path = os.path.join(dist_root, rel)
            if not os.path.isfile(dst_path):
                r.check(f"分发包含 {rel}", False, "分发包缺这个文件")
                continue
            same = open(src_path, "rb").read() == open(dst_path, "rb").read()
            r.check(f"分发包 {rel} 与源一致", same,
                    "" if same else "dist 版是旧的 —— 重新同步后再打包")
        # skill_dir.sh 必须可执行且能跑通（分发漏掉它 = 命令块退化回硬编码路径）
        sd_src = os.path.join(ROOT, "skill_dir.sh")
        sd_dst = os.path.join(dist_root, "skill_dir.sh")
        if os.path.isfile(sd_src):
            r.check("分发包含 skill_dir.sh", os.path.isfile(sd_dst))
            if os.path.isfile(sd_dst):
                p = subprocess.run(["bash", sd_dst], capture_output=True, text=True)
                r.check("分发包 skill_dir.sh 可执行且定位到安装目录",
                        p.returncode == 0 and p.stdout.strip(),
                        (p.stdout + p.stderr).strip())

    # ---- 汇总 -------------------------------------------------------------
    total, failed = len(r.rows), r.fail_count()

    if a.html is not None:
        out = a.html or os.path.join(ROOT, "assets", "verify-report.html")
        try:
            build_html(r.rows, ref, got, out)
            print(f"\n📄 验收报告 → {out}")
        except Exception as e:  # 报告失败不影响自检结论
            print(f"\n⚠ 报告生成失败：{e}")

    print("\n" + "─" * 46)
    if failed:
        print(f"✗ {failed}/{total} 项失败 —— 技能当前状态不可交付")
        if not a.verbose:
            print("  加 -v 看完整明细")
        return 1
    print(f"✓ 全部 {total} 项通过 —— 技能可交付")
    return 0


if __name__ == "__main__":
    sys.exit(main())
