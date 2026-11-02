#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf_trace.py — 从 datasheet PDF 的**文本层 + 矢量层**直接读时序图，零光栅、零大模型。

为什么要有这个：`auto_trace.py` 读的是 PNG，几何能数电平，但**认不出信号名、
读不出总线里的文字**（`ACTIVE` / `NOP` / `Din m`）。而 PDF 里这些恰恰是**真文字**，
坐标精确 —— 比任何 OCR 都准，而且是厂商原始数据。

所以要干的事只有三件（都确定性）：
   1. 分区   ：横段的最小 x = 「标签列 | 波形区」分界
   2. 认行   ：左侧文字按 y 聚成行 → **信号名**（多行标签自动合并）
   3. 读值   ：波形区里的文字 → 该行该槽位的**总线值**（时序标注 `tCK` 之类整带丢弃）
   4. 定位网格：`T0..T9` 这类标记给出**位网格**（间距 = 一个时钟周期）

和 PNG 几何的关系 —— 各取所长，都是确定性的：
   · PDF → 信号名 + 总线值 + 位网格（认字）
   · PNG → 电平行的高低电平序列（数电平，见 auto_trace.py）

用法：
   python3 scripts/pdf_trace.py --pdf dl/issi_sdr.pdf --page 54
   python3 scripts/pdf_trace.py --pdf x.pdf --page 54 --json rows.json
   python3 scripts/pdf_trace.py --pdf x.pdf --page 54 --wavejson out.json --svg out.svg

依赖：PyMuPDF（`pip install pymupdf`）
"""
import argparse
import json
import os
import re
import sys

# 融合要用同目录的 auto_trace / wavejson2svg，先把自己所在目录塞进 import 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 时序标注词：t + 大写字母（tCK / tRCD / tAS / tWR …）
# 时序标注词：`t` + 字母（ISSI 写 tCK / tRCD / tAS；TI 写 tsu5 / th1 / td5 —— 全是小写）
# 判据放宽到大小写都收：这类词的代价是「少读一个值」，收漏的代价是「读进一个假值」，
# 后者更难发现。实测 ISSI `tRCD - BANK 0` 若不丢，就会变成 A0-A9 行的一个假值。
RE_ANN = re.compile(r"^t[A-Za-z]")
# 位网格标记：T0 / T1 / T2 …
RE_MARK = re.compile(r"^T\d+$")
# 图号说明行（"Figure 33." / "Table 5."）—— 是图的标题，不是信号行
RE_CAPTION = re.compile(r"^(?:Figure|Fig\.|Table|Chart)\b", re.I)

ROW_GAP = 4.0        # 同一行标签内部的行距容差（pt）——小于此值视作换行标签
FIG_GAP = 45.0       # 两个「图」之间的最小 y 间隔（pt）
#   为什么是 45 而不是更小的值：实测同一张图内部的行间隔也可能很大 ——
#   ADS8482 Fig 33 的 "RD = 0" 到 "DB[17:12]" 之间隔了 38.75pt，
#   用 30 会把同一张图切成两块，丢掉上半部分的行。
#   而真正跨图的间隔要大得多（ISSI 图底 406.2 → 注释 412.5 = 81pt）。
X_TOL = 1.5          # 判定「这个词属于标签列」的 x 容差
WORD_JOIN = 4.0      # 同一行内两个词合并成一个值的最大间隔（pt）
#   实测 ISSI p54 的同一行相邻词间距分布呈完美分层：
#     词组内（`ENABLE`→`AUTO`、`BANK`→`0`、`DIN`→`m`）  ≤ 2.14pt  ← 就是空格的宽度
#     跨值（`NOP`→`ACTIVE`、`m+2`→`DIN`）                 ≥ 15.70pt
#   7 倍空档，4.0 落在正中间。太小会把 `ENABLE AUTO PRECHARGE` 切成三块，
#   每个碎块各自落到不同槽位（第一版就是这个毛病）。
KIND_BUS = "bus"
KIND_LEVEL = "level"

# —— 划界参数（先圈出「图」，再在图里找标签列）——
BAND_GAP = 40.0      # 矢量横段在 y 上间隔 > 此值 → 不是同一个图
BAND_PAD = 20.0      # 行标签垂直居中于自己的行，允许超出矢量带一点点
MIN_LABEL_WORDS = 3  # 标签列至少要有这么多词共用右边界，才认这个分界
X_BIN = 1.0          # 词右边界归并精度（pt）
BASE_TOL = 1.5       # 文字行聚类容差（pt）——按**基线**聚，见 _cluster_lines

# —— 适用性闸门：先证明「这页真的是一张时序图」，再动手 ——
# 判据全部来自实测（ISSI p54 真图 vs AD7606/ADS8482/ADS1256/ADS131M08 的正文页、
# 引脚表、引脚图）：
#   行标签宽度中位   真图 <= 52.6pt   非时序图 >= 158.1pt   ← 3 倍分离，最干净的一条
#   行标签对齐占比   真图 0.14~0.64   正文 0.04~0.27
#   右侧有波形的行   真图 0.43~0.55   正文 0.00~0.03（引脚图 0.43，见已知局限）
GATE_ROWS_MIN = 3       # 至少 3 行才叫时序图（实测真图 7~8 行；
#   2 行放行会让引脚图的残片混进来：ADS1256 p17 的引脚图正好残留 2 行）
GATE_LABEL_W = 100.0    # 行标签宽度中位上限（pt）—— 信号名天生短，正文行天生长
GATE_WAVE_ROWS = 2      # 至少这么多行的右侧有波形
GATE_ALIGN = 0.30       # 行标签对齐占比下限
GATE_WAVE_FRAC = 0.25   # 「右侧有波形」的行占比下限
WAVE_SEG_MIN = 3        # 一行右侧至少这么多横段才算「有波形」


# --------------------------------------------------------------------------
def load_page(pdf, page_no):
    import pymupdf
    doc = pymupdf.open(pdf)
    if not (1 <= page_no <= doc.page_count):
        raise SystemExit(f"页码 {page_no} 越界（该 PDF 共 {doc.page_count} 页）")
    return doc, doc[page_no - 1]


def words_of(page, y0=None, y1=None):
    """取词表 (x0,y0,x1,y1,text)。PyMuPDF 的 y 轴原点在左上。"""
    out = []
    for w in page.get_text("words"):
        if y0 is not None and w[1] < y0:
            continue
        if y1 is not None and w[3] > y1:
            continue
        out.append((float(w[0]), float(w[1]), float(w[2]), float(w[3]), w[4]))
    return out


def stroke_segments(page):
    """矢量层里的水平 / 竖直线段。

    ⚠️ 必须把 `re`（矩形）和 `qu`（四边形）也拆成边，不能只看 `l`（线段）。
       实测 ISSI p54 的图元构成是 {l:770, c:392, qu:22, re:19} —— **总线带和
       DON'T CARE 阴影区是矩形/四边形，不是线段**。只看 `l` 的话 A10 / BA / DQ
       三行的「右侧横段数」全是 0，看起来像「这三行右边没有东西」。
    """
    hs, vs = [], []

    def add(x0, y0, x1, y1):
        if abs(y1 - y0) < 0.6 and abs(x1 - x0) > 1.0:
            hs.append((round((y0 + y1) / 2, 2), min(x0, x1), max(x0, x1)))
        elif abs(x1 - x0) < 0.6 and abs(y1 - y0) > 1.0:
            vs.append((round((x0 + x1) / 2, 2), min(y0, y1), max(y0, y1)))

    def corners(pts):
        # 闭合多边形 → 逐边
        for a, b in zip(pts, pts[1:] + pts[:1]):
            if a is None or b is None:
                continue
            add(a.x, a.y, b.x, b.y)

    for g in page.get_drawings():
        for it in g.get("items", []):
            k = it[0]
            if k == "l":
                (x0, y0), (x1, y1) = it[1], it[2]
                add(x0, y0, x1, y1)
            elif k == "re":
                r = it[1]
                add(r.x0, r.y0, r.x1, r.y0)
                add(r.x0, r.y1, r.x1, r.y1)
                add(r.x0, r.y0, r.x0, r.y1)
                add(r.x1, r.y0, r.x1, r.y1)
            elif k == "qu":
                # PyMuPDF 的 Quad 是 (ul, ur, ll, lr)；按顺时针串起来当多边形
                q = it[1]
                corners([q.ul, q.ur, q.lr, q.ll])
            # `c`（三次贝塞尔）不拆：总线带是 `qu`/`re`，斜边是 `c` 或斜 `l`，
            # 都不是水平/垂直轨，拆了只会往 hs/vs 里灌噪声。
    return hs, vs


def vector_band(hs):
    """图区 y 范围 = 矢量横段最密集的那一段。

    为什么必须先圈图：datasheet 每页都有页眉 / 页脚的通栏横线，起点就在左边距上
    （实测 ISSI p54 = 36.0pt）。不排掉它们，「波形区左界」会被算成 36pt，
    右侧一个字都取不到 —— 这就是第一版在 ISSI p54 上报
    「左侧标签列找不到任何文字」的真正原因。
    """
    ys = sorted(s[0] for s in hs)
    if not ys:
        return None
    clusters, cur = [], [ys[0]]
    for v in ys[1:]:
        if v - cur[-1] > BAND_GAP:
            clusters.append(cur)
            cur = []
        cur.append(v)
    clusters.append(cur)
    best = max(clusters, key=len)
    return best[0], best[-1]


def in_band(w, band):
    if band is None:
        return True
    return band[0] - BAND_PAD <= w[1] and w[3] <= band[1] + BAND_PAD


def label_x_right(words, band=None):
    """「标签列 | 波形区」分界 x = 行标签**共用的右边界**。

    为什么是「众数」而不是「矢量横段的最小起点」（第一版的做法）：
      行标签是**右对齐**的，所以它们的 x1 会精确重合（实测 ISSI p54：9 个词
      共用 x1 = 92.64）；而波形区的左界根本不唯一 —— 母线、刻度线、引线各自
      起点不同，取最小那个毫无意义。众数还自带排除页面杂项的能力：页眉、
      正文注释、页脚都是左对齐的，不会形成众数。

    返回 None 表示找不到可信的分界（调用方据此区分「没有文字层」和「格式不认识」）。
    """
    bins = {}
    for w in words:
        if not in_band(w, band):
            continue
        k = round(w[2] / X_BIN) * X_BIN
        bins[k] = bins.get(k, 0) + 1
    cands = [(x, n) for x, n in bins.items() if n >= MIN_LABEL_WORDS]
    if not cands:
        return None
    # 词数最多者胜；并列时取更靠左的（标签列一定在图的最左侧）
    return min(cands, key=lambda t: (-t[1], t[0]))[0]


def _cluster_lines(words, tol=None):
    """把词按**基线** y1 聚成文字行。

    为什么按基线，不按中心、也不按「上一个词的下边界」——
    先后踩过两个坑，都是实测出来的：

    ① 按中心聚：`tAS`（中心 257.49）和 `ENABLE AUTO PRECHARGE`（中心 260.53）
       只差 3.05pt，被判成同一行 → 该行含 `tAS` 被当标注整带丢弃，
       A10 行丢掉两个值（实测 ISSI p54）。
    ② 按边界差聚：多行标签是**垂直重叠**排版的 —— `DQM/` 下边界 217.78、
       `DQML,` 上边界 215.80，重叠 2pt，会被并成一行，再按 x 排序拼名字
       就变成 "DQML, DQMH DQM/"（顺序全乱）。

    基线则是排版学上的硬事实：**同一视觉行共享基线**。实测同行的基线差
    ≤ 0.22pt，而上面那两行差 3.05pt —— 10 倍分离度，阈值 1.5 很稳。
    """
    if not words:
        return []
    if tol is None:
        hh = sorted(w[3] - w[1] for w in words)
        tol = max(BASE_TOL, hh[len(hh) // 2] * 0.18)
    ws = sorted(words, key=lambda w: (w[3], w[0]))
    out, cur, ref = [], [], None
    for w in ws:
        if cur and w[3] - ref > tol:
            out.append(cur)
            cur = []
        if not cur:
            ref = w[3]
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _row_label(lines):
    """多行标签拼成一个名字。

    换行处怎么拼：上一行以 `/ - _` 结尾 → 直接接（`DQM/` + `DQML,` = `DQM/DQML,`）；
    否则补一个空格（`DATA:` + `DB[15:0]` = `DATA: DB[15:0]`）。
    """
    parts = []
    for ln in lines:
        seg = " ".join(w[4] for w in sorted(ln, key=lambda w: w[0]))
        if parts and parts[-1][-1:] not in "/-_":
            parts.append(" ")
        parts.append(seg)
    return "".join(parts).strip()


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def _row_evidence(hs, xr, rows):
    """每行「右侧是否有波形」。

    时序图的行标签右边**一定有矢量** —— 电平轨、总线带的上下边、刻度引线。
    正文段落右边什么都没有；表格行右边是表格线（但那种页会先被标签宽度挡掉）。

    窗口按行距放宽 ±0.45×pitch：行标签比它所属的波形带**窄**（标签只有 8.9pt 高，
    总线带高约 20pt），不放宽的话总线带行的上下边框落在标签窗口外，
    会被误判成「右侧没波形」（实测 ISSI：A0-A9 / A10 / DQ 三行）。
    """
    cs = sorted(r["y_center"] for r in rows)
    pitch = _median([cs[i + 1] - cs[i] for i in range(len(cs) - 1)]) if len(cs) > 1 else 20.0
    pad = max(2.0, pitch * 0.45)
    out = []
    for r in rows:
        y0, y1 = r["y_band"][0] - pad, r["y_band"][1] + pad
        n = sum(1 for s in hs
                if y0 <= s[0] <= y1 and max(s[1], xr) < s[2] - 3)
        out.append(n)
    return out


def read_rows(page, verbose=False):
    """返回 (rows, x_label_right, meta)。

    rows = [{name, y_center, y_band, x_span, has_wave, lines, items}]

    末尾有「适用性闸门」：证据不足就报错并**把证据打出来**，不猜。
    见 GATE_* 常量与 `_gate_evidence`。
    """
    words = words_of(page)
    hs, _ = stroke_segments(page)
    band = vector_band(hs)

    xr = label_x_right(words, band)
    if xr is None:
        if not words:
            raise SystemExit(
                "这一页**没有文本层**（PyMuPDF 取到 0 个词）。\n"
                "可能是扫描件，或厂商把文字转成了矢量轮廓（实测 ADI 的 AD7606 就是 —— "
                "`t1..t29` 全是有路径无文字）。\n"
                "这种图只能走像素几何路线：先按 dpi 渲染成 PNG，再用 auto_trace.py。")
        raise SystemExit(
            f"找到 {len(words)} 个词，但没有「行标签列」"
            f"（要求同一条右边界上至少 {MIN_LABEL_WORDS} 个词）。\n"
            "可能是这张图的行标签不是右对齐的，或者这一页根本没有时序图。\n"
            "可试：换一页 / 换一个图；或先用 datasheet-figure-extract 裁出图区。")

    left = [w for w in words if w[2] <= xr + X_TOL and in_band(w, band)]
    if not left:
        raise SystemExit(
            f"标签列右界算出 x={xr:.1f}pt，但它左边一个词都没有。\n"
            "说明这个「右对齐词簇」不是行标签列 —— 这一页大概率没有时序图。")
    lines = _cluster_lines(left)

    # 把文字行按「图」分组：同一个图内的相邻行间隔 ≤ FIG_GAP
    groups, cur = [], []
    for ln in lines:
        if cur and min(w[1] for w in ln) - max(w[3] for w in cur[-1]) > FIG_GAP:
            groups.append(cur)
            cur = []
        cur.append(ln)
    if cur:
        groups.append(cur)
    if not groups:
        raise SystemExit("左侧标签列里没有可用的文字行，无法成图")
    fig = max(groups, key=len)

    rows = []
    for ln in fig:
        y0 = min(w[1] for w in ln)
        y1 = max(w[3] for w in ln)
        rows.append({"name": _row_label([ln]), "y_center": (y0 + y1) / 2,
                     "y_band": [y0, y1], "lines": [ln], "items": []})

    # 相邻两行若间隔很小（多行标签被切开了）就合并
    merged = []
    for r in rows:
        if merged and r["y_band"][0] - merged[-1]["y_band"][1] <= ROW_GAP:
            m = merged[-1]
            m["lines"].append(r["lines"][0])
            m["name"] = _row_label(m["lines"])
            m["y_band"] = [m["y_band"][0], max(m["y_band"][1], r["y_band"][1])]
            m["y_center"] = sum(m["y_band"]) / 2
        else:
            merged.append(dict(r))
    rows = merged
    for r in rows:
        r["x_span"] = round(max(w[2] for ln in r["lines"] for w in ln)
                            - min(w[0] for ln in r["lines"] for w in ln), 2)

    for r, n in zip(rows, _row_evidence(hs, xr, rows)):
        r["has_wave"] = n

    # 图上方的图号说明行不是信号行（实测 ADS8482 p17 的 "Figure 33." 会被当第 8 行）
    rows = [r for r in rows if not RE_CAPTION.match(r["name"])]
    if len(rows) < 2:
        raise SystemExit(f"剔掉图号说明行后只剩 {len(rows)} 行，不足以成图")

    # —— 适用性闸门 ——
    n_left_all = sum(1 for w in words if in_band(w, band) and w[0] < xr)
    ratio = len([w for w in words if in_band(w, band) and abs(w[2] - xr) <= X_BIN])
    ratio /= max(1, n_left_all)
    widths = sorted(r["x_span"] for r in rows)
    med_w = widths[len(widths) // 2]
    n_wave = sum(1 for r in rows if r["has_wave"] >= WAVE_SEG_MIN)
    frac = n_wave / max(1, len(rows))

    meta = {"label_x_right": round(xr, 2), "n_words": len(words),
            "figure_band": [round(band[0], 2), round(band[1], 2)] if band else None,
            "n_left_words": len(left),
            "label_align_ratio": round(ratio, 3),
            "label_width_median": med_w,
            "rows_with_wave": n_wave,
            "rows_with_wave_frac": round(frac, 3)}

    evidence = (f"   行数 {len(rows)}   标签宽度中位 {med_w:.1f}pt   "
                f"对齐占比 {ratio:.3f}   右侧有波形 {n_wave}/{len(rows)} ({frac:.2f})\n"
                + "".join(f"     {r['name'][:30]:<32s} 宽 {r['x_span']:6.1f}pt  "
                          f"右侧横段 {r['has_wave']:3d}\n" for r in rows))

    if not (len(rows) >= GATE_ROWS_MIN and med_w <= GATE_LABEL_W
            and n_wave >= GATE_WAVE_ROWS
            and (ratio >= GATE_ALIGN or frac >= GATE_WAVE_FRAC)):
        raise SystemExit(
            "**这一页看起来不是时序图**，闸门没放行（宁可不做，不可瞎做）。\n"
            "证据：\n" + evidence
            + f"\n放行条件是四条全满足：\n"
              f"  · 行数 >= {GATE_ROWS_MIN}                                  （实测 {len(rows)}）\n"
              f"  · 行标签宽度中位 <= {GATE_LABEL_W}pt                    （实测 {med_w:.1f}）\n"
              f"    ↑ 信号名天生短，正文行天生长：实测真图 <= 52.6pt，正文页 >= 158.1pt\n"
              f"  · 右侧有波形的行数 >= {GATE_WAVE_ROWS}                        （实测 {n_wave}）\n"
              f"  · 行标签对齐占比 >= {GATE_ALIGN} 或 有波形行占比 >= {GATE_WAVE_FRAC}"
              f"（实测 {ratio:.3f} / {frac:.2f}）\n"
              "\n可试：\n"
              "  1) 换到真正画时序图的那一页；\n"
              "  2) 用 datasheet-figure-extract 先定位图号（Caption 'Figure N.'），再回来；\n"
              "  3) 这张图若本来就没有文本层（ADI 常见），走 PNG 几何：auto_trace.py。")

    # 过闸之后，把「右侧确实没有任何矢量」的行剔掉 —— 那多半是图注/脚注，不是信号行。
    # 实测 ADS8482 p17 剔掉 "†Signal internal / to device" 这类脚注。
    #   阈值取 2 而不是 1：只有 1 条横段的「行」基本是脚注
    #   （实测 ADS8482 p17 的 "†Signal internal / to device"）。
    kept = [r for r in rows if r["has_wave"] >= 2]
    if len(kept) >= 2:
        dropped = [r["name"] for r in rows if r["has_wave"] < 2]
        if dropped and verbose:
            print(f"   剔掉无波形的行：{dropped}")
        rows = kept

    if verbose:
        print(f"图区 y=[{band[0]:.2f},{band[1]:.2f}]pt   标签列右界 x={xr:.2f}pt   "
              f"（全页 {len(words)} 词，带内左侧 {len(left)} 词）")
        print(evidence.rstrip())
    return rows, xr, meta


def read_values(page, rows, xr):
    """波形区里的文字 → 行 × 槽位的值。时序标注整带丢弃。"""
    words = [w for w in words_of(page) if w[0] > xr + X_TOL]
    y_lo = min(r["y_band"][0] for r in rows) - 12
    y_hi = max(r["y_band"][1] for r in rows) + 12
    words = [w for w in words if y_lo <= w[1] and w[3] <= y_hi]

    marks, bands = [], []
    for ln in _cluster_lines(words):
        txt = [w[4] for w in ln]
        if any(RE_ANN.match(t) for t in txt):
            # 带里出现 tCK/tRCD 这类标注 → 整带是时序标注，不是总线值
            continue
        if all(RE_MARK.match(t) for t in txt):
            marks.extend(ln)
            continue
        bands.append(ln)

    # 带内按 x 合并相邻词 → 一条总线值
    values = []
    for ln in bands:
        cur = []
        for w in sorted(ln, key=lambda w: w[0]):
            if cur and w[0] - cur[-1][2] > WORD_JOIN:
                values.append(cur)
                cur = []
            cur.append(w)
        if cur:
            values.append(cur)
    values = [{"x0": min(w[0] for w in v), "x1": max(w[2] for w in v),
               "yc": sum(w[1] + w[3] for w in v) / (2 * len(v)),
               "text": " ".join(w[4] for w in sorted(v, key=lambda w: w[0]))}
              for v in values]

    # 分配给最近的行
    for v in values:
        r = min(rows, key=lambda r: abs(r["y_center"] - v["yc"]))
        r["items"].append(v)

    grid = None
    marks = [{"x": (m[0] + m[2]) / 2, "text": m[4]} for m in sorted(marks, key=lambda m: m[0])]
    if len(marks) >= 2:
        xs = [m["x"] for m in marks]
        pitch = (xs[-1] - xs[0]) / (len(xs) - 1)
        bounds = [xs[0] - pitch / 2] + [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)] \
                 + [xs[-1] + pitch / 2]
        grid = {"marker": marks[0]["text"], "n": len(xs),
                # ⚠️ centers / bounds 的语义（2026-09-18 在 ISSI SDR p54 上量实）：
                #   centers = 厂商 T0..T9 **文字标号**的 x，也正是它竖虚线的位置
                #             = 时钟**上升沿** = COMMAND 换值处 = 我们所定义「位槽的中点」
                #   bounds  = 相邻标号的中点 = 时钟**下降沿** = 位槽边界
                # 别把两者混用：ISSI 的 DQM/CKE 灰梯形「驼峰」压在 bounds 上（下降沿），
                # 而位槽的 25%/75% 采样点（fuse_levels 用的）之间正好夹着 centers 的上升沿。
                "centers": [round(x, 2) for x in xs], "pitch": round(pitch, 2),
                "bounds": [round(b, 2) for b in bounds]}
    return grid


def _slot_of(grid, x):
    """x 落在第几个位槽（无网格则返回 None）。"""
    if not grid:
        return None
    for i in range(len(grid["bounds"]) - 1):
        if grid["bounds"][i] <= x < grid["bounds"][i + 1]:
            return i
    return None


def analyse(pdf, page_no, verbose=False):
    doc, page = load_page(pdf, page_no)
    rows, xr, meta = read_rows(page, verbose=verbose)
    grid = read_values(page, rows, xr)

    for r in rows:
        r["items"].sort(key=lambda v: v["x0"])
        for v in r["items"]:
            v["slot"] = _slot_of(grid, (v["x0"] + v["x1"]) / 2)
        r["kind"] = KIND_BUS if r["items"] else KIND_LEVEL

    return {"pdf": os.path.abspath(pdf), "page": page_no,
            "page_size": [round(page.rect.width, 1), round(page.rect.height, 1)],
            "figure_y": [round(min(r["y_band"][0] for r in rows), 2),
                         round(max(r["y_band"][1] for r in rows), 2)],
            "label_x_right": xr, "grid": grid,
            "rows": [{"name": r["name"], "kind": r["kind"],
                      "y_center": round(r["y_center"], 2),
                      "y_band": [round(v, 2) for v in r["y_band"]],
                      "slots": {str(k): v["text"] for k, v in
                                sorted(((v["slot"], v) for v in r["items"]),
                                       key=lambda t: (t[0] is None, t[0]))},
                      "items": [{"slot": v["slot"], "x": round((v["x0"] + v["x1"]) / 2, 2),
                                 "x0": round(v["x0"], 2), "x1": round(v["x1"], 2),
                                 "text": v["text"]} for v in r["items"]]}
                     for r in rows]}, meta


# --------------------------------------------------------------------------
# 融合：PDF 认字 ⊕ PNG 数电平
# --------------------------------------------------------------------------
def render_page(pdf, page_no, dpi=300, out_png=None):
    """把某一页渲染成灰度 PNG。返回 (png 路径, 缩放系数)。

    缩放系数 = dpi / 72 —— PDF 用**点**（1/72 英寸），位图用**像素**。
    这个系数是把 PDF 坐标（行中心、位网格）搬到像素坐标系的唯一桥梁，
    弄错就会让「行」和「波形」对不上。
    """
    import pymupdf
    import tempfile
    doc = pymupdf.open(pdf)
    page = doc[page_no - 1]
    if out_png is None:
        fd, out_png = tempfile.mkstemp(suffix=".png", prefix="pdf_trace_")
        os.close(fd)
    page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).save(out_png)
    return out_png, dpi / 72.0


DC_FILL = 0.25       # 列内灰底像素占比 >= 此值 → 该列落在 DON'T CARE 区
# 灰度阈值。**必须与 auto_trace.DARK 一致** —— auto_trace 判总线带用的是同一条
# 判据（灰度落在 DARK ~ 0.92 之间）。这里不 import auto_trace 是为了让 pdf_trace
# 的「只读 PDF」路径不依赖 matplotlib/numpy；一致性由自检用例守着。
DARK = 0.45
WEDGE_FRAC = 0.15    # 行内灰底列占比 >= 此值 → 这行是「电平线 + 灰梯形」画法
DC_SLOT = 0.60       # 一个槽位里灰底列占比 >= 此值 → 该槽位整个是 DON'T CARE


def _dontcare_cols(gray, y0, y1, plot_l, plot_r):
    """逐列判「是不是 DON'T CARE 灰底」。"""
    import numpy as np
    band = gray[y0:y1 + 1, plot_l:plot_r + 1]
    g = (band > DARK) & (band < 0.92)
    cnt = g.sum(axis=0)
    h = max(1, band.shape[0])
    return cnt >= DC_FILL * h


def _wedge_far_row(gray, y0, y1, plot_l, plot_r, dc, line_row):
    """灰梯形「远端」的行号（相对行带顶 y0）。

    梯形的远端就是**对面的电平轨** —— 用它才能判断那条横贯全图的电平线
    到底代表高还是低。实测：
        CKE  线在行带第 24 行，梯形向下展开到 ~70 行 → 线 = 高
        DQM  线在行带第 68 行，梯形向上展开到 ~20 行 → 线 = 低
    取灰底列里「离电平线更远的那一端」的中位数，抗噪。
    """
    import numpy as np
    is_gray = (gray[y0:y1 + 1, plot_l:plot_r + 1] > DARK) \
        & (gray[y0:y1 + 1, plot_l:plot_r + 1] < 0.92)
    far = []
    for i in np.where(dc)[0]:
        g = np.where(is_gray[:, i])[0]
        if not len(g):
            continue
        far.append(g[-1] if abs(g[-1] - line_row) > abs(g[0] - line_row) else g[0])
    if len(far) < 5:
        return None
    return int(np.median(far))


def _level_line_row(dark, y0, y1, plot_l, plot_r):
    """行带里**最长的水平线**所在行号 —— 那就是电平线。

    为什么用「最长水平线」而不是「最上方深色像素的众数」：
    有灰梯形的行里，梯形上边也是一条深色线，按「最上方」会把它当电平线
    （实测 DQM 于是被读成高电平，实际是低）。而**最长的那条**必然是横跨
    整幅图的电平线 —— 梯形的斜边每行只有几个像素。
    """
    import numpy as np
    sub = dark[y0:y1 + 1, plot_l:plot_r + 1]
    return sub.sum(axis=1)


def fuse_levels(res, png, scale, verbose=False):
    """用像素几何给「电平行」补上高低电平波形。

    分工：
      · PDF  → 信号名、总线值、**位网格**（厂商自己画的 T0..T9，最可信）
      · PNG  → 电平行的高低（几何解，不认字）

    两种画法要分开处理 —— 这是本工具最反直觉的一处：

    【A】普通电平行（CLK）：两条轨，逐列取最上方深色像素 → 高低序列。
    【B】「电平线 + 灰梯形」行（ISSI 的 CKE / DQM）：一条**横贯全图的电平线**
        加若干灰梯形。灰梯形表示「这些窗口 DON'T CARE」，而梯形的**远端就是
        对面的电平轨**，用它才能判断那条线是高还是低。整个槽位都被灰底盖住时
        输出 `x`。

    踩过的坑（都是实测）：
      · 只看「细线列」找两条轨 → 两条轨落在同一条线上，整行恒一个电平；
      · 用「最上方深色像素」→ DQM 的梯形上边被当成高轨，读成高电平（应为低）；
      · 用「墨迹厚度」判灰底 → 被压在同一行带里的 `tCK/tCL/tCH` 标注线骗到；
      · 用「灰度跨度」判 → 梯形轮廓的零星灰点会把跨度撑满，误判。
    """
    import auto_trace as at
    import numpy as np
    gray, dark = at.load_dark(png)
    H, W = gray.shape
    dark = at.long_run_mask(dark, max(12, W // 60))       # 滤掉文字标注笔画
    plot_l, plot_r = at.wave_span(dark)

    grid = res["grid"]
    if not grid:
        raise SystemExit(
            "PDF 里没找到 T0/T1… 这类位网格标记，没法把像素采到槽位上。\n"
            "退路：直接用 auto_trace.py 读 PNG（它自己会认时钟、切位窗）。")

    n, pitch = grid["n"], grid["pitch"]
    centers_px = [c * scale for c in grid["centers"]]
    pitch_px = pitch * scale

    cs = sorted(r["y_center"] for r in res["rows"])
    row_px = _median([cs[i + 1] - cs[i] for i in range(len(cs) - 1)]) * scale
    half_px = max(4, int(row_px * 0.45))     # 行带半高按**行距**算，不是按位宽

    report = {"scale": scale, "pitch_pt": pitch, "pitch_px": round(pitch_px, 1),
              "row_px": round(row_px, 1), "plot_x": [plot_l, plot_r],
              "label_x_right_px": round(res["label_x_right"] * scale, 1),
              "rows": []}

    for r in res["rows"]:
        if r["kind"] != KIND_LEVEL:
            continue
        yc = r["y_center"] * scale
        y0, y1 = int(yc - half_px), int(yc + half_px)
        if not (0 <= y0 < y1 < H):
            report["rows"].append({"name": r["name"], "error": "行窗口越界"})
            continue

        dc = _dontcare_cols(gray, y0, y1, plot_l, plot_r)
        dc_frac = float(dc.mean()) if len(dc) else 1.0
        rowsum = _level_line_row(dark, y0, y1, plot_l, plot_r)
        line_row = int(rowsum.argmax())
        line_width = int(rowsum.max())

        if line_width < (plot_r - plot_l) * 0.3:
            # 连一条像样的水平线都没有 → 这行没有可读的电平
            r["wave"] = "xx" * n
            r["dont_care"] = 1.0
            report["rows"].append({"name": r["name"], "wave": r["wave"],
                                   "dont_care": 1.0, "note": "行内找不到电平线"})
            continue

        if dc_frac >= WEDGE_FRAC:
            # —— 画法 B：电平线 + 灰梯形 ——
            opp = _wedge_far_row(gray, y0, y1, plot_l, plot_r, dc, line_row)
            if opp is None or abs(opp - line_row) < 4:
                mode = "wm"      # 灰梯形的远端没找到，退回按「线在行带上下半」定
                level = "1" if line_row < (y1 - y0) / 2 else "0"
            else:
                mode = "wl"
                level = "1" if line_row < opp else "0"
            wave = ""
            for k in range(n):
                xa = centers_px[k] - pitch_px / 2
                a = max(0, min(int(round(xa - plot_l)), len(dc) - 1))
                b = max(0, min(int(round(xa + pitch_px - plot_l)), len(dc)))
                seg = dc[a:b]
                wave += "xx" if (len(seg) and seg.mean() >= DC_SLOT) else level * 2
            r["wave"] = wave
            r["dont_care"] = round(dc_frac, 3)
            report["rows"].append({"name": r["name"], "wave": wave,
                                   "dont_care": round(dc_frac, 3),
                                   "mode": mode, "line_row": line_row,
                                   "opp_row": opp, "level": level})
            continue

        # —— 画法 A：普通双轨电平（CLK）——
        prof = at.track_profile(dark, y0, y1, plot_l, plot_r)[0]
        hi, lo = at.find_rails(prof, plot_l, plot_r)
        if hi is None:
            r["wave"] = "xx" * n
            report["rows"].append({"name": r["name"], "wave": r["wave"], "mode": "none"})
            continue
        if lo is None:
            ser, base = None, ("1" if hi < (y1 - y0) / 2 else "0")
        else:
            ser, base = at.level_series(prof, hi, lo, plot_l, plot_r), None
        wave = ""
        for k in range(n):
            xc = centers_px[k]
            for frac in (0.25, 0.75):
                x = xc - pitch_px / 2 + frac * pitch_px
                hw = max(1, int(pitch_px * 0.15))
                wave += (str(at.level_at(ser, plot_l, x, hw)) if ser is not None else base)
        r["wave"] = wave
        r["dont_care"] = round(dc_frac, 3)
        report["rows"].append({"name": r["name"], "wave": wave, "mode": "two-rail",
                               "rails": (hi, lo), "dont_care": round(dc_frac, 3)})

    if verbose:
        print(f"融合：scale={scale:.3f}  位间距 {pitch}pt = {pitch_px:.1f}px  "
              f"行距 {row_px:.1f}px  波形区 x=[{plot_l},{plot_r}]")
        for it in report["rows"]:
            if "error" in it:
                print(f"   {it['name']:<22s} ✗ {it['error']}")
            else:
                print(f"   {it['name']:<22s} [{it.get('mode','?'):<9s}] "
                      f"灰底 {it.get('dont_care', 0)*100:5.1f}%  wave={it['wave']}")
    return report

def _slot_span(grid, x0, x1):
    """一段文字横跨了哪几个槽位（闭区间 [a, b]）。

    为什么需要：厂商画总线值时，**文字有多宽就占几个槽** ——
    实测 ISSI 的 `ENABLE AUTO PRECHARGE` 宽 104pt，横跨 T1~T3 三个槽；
    一律压进中心那一个槽的话，渲染时字号要缩到 3.6px 才装得下（不可读）。
    """
    b_ = grid["bounds"]
    n = grid["n"]
    a = next((i for i in range(n) if b_[i + 1] > x0), n - 1)
    z = next((i for i in range(n - 1, -1, -1) if b_[i] < x1), a)
    return a, max(a, z)


def to_wavejson(res):
    """把结果转成 WaveJSON。

    · 总线行：每个有值的槽位 = 1 个数据块（块字符 + `.` 延续，共 2 字符），
      值来自 PDF 文本层；没有值的槽位写 `x`（未驱动）——
      原厂图里那些区域本来就是 DON'T CARE 灰底。
    · 电平行：用 `fuse_levels()` 从像素几何解出来的 wave；
      没做过融合就退回占位（并在返回值里标出来，别当它是真的）。
    · config.ruler：用**厂商自己画的 T0..T9** 当标尺，比我们猜的 D7…D0 可信。
    """
    grid = res["grid"]
    n = grid["n"] if grid else max((len(r["items"]) for r in res["rows"]), default=0)
    sig, blk = [], "23456789"
    placeholders = []
    for r in res["rows"]:
        if r["kind"] != KIND_BUS:
            wave = r.get("wave")
            if not wave:
                wave = "0" * (2 * n)
                placeholders.append(r["name"])
            sig.append({"name": r["name"], "wave": wave})
            continue
        slots = {}
        for it in r["items"]:
            if it["slot"] is not None:
                slots[it["slot"]] = it["text"]
        # 每个值按它文字**实际覆盖的槽位范围**铺块（厂商就是这么画的）；
        # 若目标范围已被别的值占掉，退回只占中心那一个槽。
        cells = [None] * n
        for it in sorted(r["items"], key=lambda v: v.get("x0", 0)):
            if it["slot"] is None:
                continue
            a, b = _slot_span(grid, it.get("x0", 0), it.get("x1", 0)) if grid else (it["slot"], it["slot"])
            if any(cells[i] is not None for i in range(a, b + 1)):
                a = b = it["slot"]
            if cells[a] is not None:
                continue
            cells[a] = it["text"]
            for i in range(a + 1, b + 1):
                cells[i] = ""            # 空串 = 该槽是上一个块的延续
        wave, data = "", []
        for s in range(n):
            if cells[s] is None:
                wave += "xx"
            elif cells[s] == "":
                wave += ".."
            else:
                wave += blk[len(data) % len(blk)] + "."
                data.append(cells[s])
        rec = {"name": r["name"], "wave": wave}
        if data:
            rec["data"] = data
        sig.append(rec)

    cfg = {"hscale": 1, "ruler_pad": 0}
    if grid:
        prefix = grid["marker"].rstrip("0123456789") or "T"
        cfg["ruler"] = [f"{prefix}{i}" for i in range(n)]

    out = {"head": {"text": f'{os.path.basename(res["pdf"])}  p{res["page"]}'},
           "signal": sig, "config": cfg}
    if placeholders:
        out["_placeholders"] = placeholders
    return out


def main():
    ap = argparse.ArgumentParser(description="从 datasheet PDF 文本层读时序图（零大模型）")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--page", type=int, required=True, help="页码（从 1 开始）")
    ap.add_argument("--json", help="结构化结果落盘")
    ap.add_argument("--wavejson", help="转成 WaveJSON 落盘")
    ap.add_argument("--svg", help="顺手渲染成 SVG（需要 wavejson2svg.py）")
    ap.add_argument("--no-fuse", action="store_true",
                    help="只出 PDF 侧（信号名 + 总线值），不做像素融合求电平")
    ap.add_argument("--png", help="已有 PNG 就直接用；不给则按 --dpi 渲染页面")
    ap.add_argument("--dpi", type=int, default=300, help="渲染页面用的 dpi（默认 300）")
    ap.add_argument("--keep-png", help="把渲染出的 PNG 存到这个路径（便于核对）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="打印图区/标签列等中间量")
    a = ap.parse_args()

    res, meta = analyse(a.pdf, a.page, verbose=a.verbose)

    fuse_report = None
    if not a.no_fuse and (a.wavejson or a.svg):
        png, scale = (a.png, None) if a.png else render_page(
            a.pdf, a.page, dpi=a.dpi, out_png=a.keep_png)
        if scale is None:
            # 用已有 PNG 时，缩放系数只能从 PDF 页面宽度和 PNG 宽度反推
            import auto_trace as at
            g, _ = at.load_dark(png)
            doc, page = load_page(a.pdf, a.page)
            scale = g.shape[1] / page.rect.width
            if not a.quiet:
                print(f'用已有 PNG {png}  →  scale = {scale:.3f}（由 图宽/页宽 反推）')
        fuse_report = fuse_levels(res, png, scale, verbose=a.verbose)

    if not a.quiet:
        print(f'{os.path.basename(res["pdf"])}  p{res["page"]}   '
              f'页面 {res["page_size"][0]}x{res["page_size"][1]}pt   '
              f'图区 y={res["figure_y"]}')
        print(f'标签列右界 x = {res["label_x_right"]}pt'
              f'（图区矢量带 {meta.get("figure_band")}，全页 {meta.get("n_words")} 词）')
        if res["grid"]:
            g = res["grid"]
            print(f'位网格：{g["n"]} 个槽位（{g["marker"]} 起），间距 {g["pitch"]}pt')
        else:
            print("位网格：未找到 T0/T1… 这类标记，只能按 x 排序输出值")
        print()
        for i, r in enumerate(res["rows"]):
            tag = "BUS" if r["kind"] == KIND_BUS else "LVL"
            print(f'  [{i}] {r["name"]:<22s} y={r["y_center"]:7.2f}  {tag}')
            for it in r["items"]:
                slot = "-" if it["slot"] is None else str(it["slot"])
                print(f'        slot {slot:>2s}  x={it["x"]:7.2f}  {it["text"]!r}')
            if r.get("wave"):
                print(f'        wave = {r["wave"]}')
        print(f'\n共 {len(res["rows"])} 行，'
              f'{sum(1 for r in res["rows"] if r["kind"] == KIND_BUS)} 行是总线带')
        if fuse_report:
            lv = [it for it in fuse_report["rows"] if "wave" in it]
            ok = [it for it in lv if len(it["wave"]) == 2 * res["grid"]["n"]]
            print(f'像素融合：{len(ok)}/{len(lv)} 条电平行取到波形'
                  f'（位间距 {fuse_report["pitch_pt"]}pt ≈ {fuse_report["pitch_px"]}px）')

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"✓ 结构化结果 → {a.json}")
    if a.wavejson or a.svg:
        wj = to_wavejson(res)
        if a.wavejson:
            with open(a.wavejson, "w", encoding="utf-8") as f:
                json.dump(wj, f, ensure_ascii=False, indent=2)
            print(f"✓ WaveJSON → {a.wavejson}")
        if a.svg:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import wavejson2svg
            with open(a.svg, "w", encoding="utf-8") as f:
                f.write(wavejson2svg.render(wj))
            print(f"✓ SVG → {a.svg}")


if __name__ == "__main__":
    main()
