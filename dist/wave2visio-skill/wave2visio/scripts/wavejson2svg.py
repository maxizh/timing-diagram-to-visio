#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wavejson2svg.py — 把 WaveJSON 渲染成「原厂时序图风格」的 SVG。

与 WaveDrom 官方渲染的关键差异（这三点正是芯片工程师要求"和原图一模一样"的核心）：
  1. 电平过渡是**垂直直角**，不是斜边梯形；
  2. **连续相同电平之间不会产生多余的转折记号**
     （WaveDrom 用 "0000" 这类显式重复会画出多余的尖刺，CS_n 会变成一排小尖峰）；
  3. 单 bit 只需 1 个字符宽度即可呈现完整方波（不再需要 4 字符撑平台）。

输出为白底黑线的纯 <path>/<text> SVG，Visio 2024+ 可直接 File→Open 导入并编辑。

依赖：仅 Python 标准库。
用法：
  python3 wavejson2svg.py input.json [-o out.svg] [--cell 24] [--row 60]
                                     [--no-grid] [--label-width 110]
"""
import argparse
import json
import math
import sys

# ---------- 主题（浅色，便于导入 Visio 后编辑） ----------
C_BG = "#ffffff"
C_LINE = "#000000"
C_LABEL = "#1f4e9c"
C_TITLE = "#111111"
C_GRID = "#c9ccd1"
C_HATCH = "#9aa0a6"   # Don't Care 斜纹线色
FONT = "Helvetica, Arial, sans-serif"

# ---------- wave 字符 -> 电平 ----------
#  0 / 1  : 低 / 高
#  . / =  : 延续前一状态
#  p      : 时钟脉冲（本渲染器将其视为"该字符为高"）
#  x      : 未知态（画中间灰线 + 淡色底；config.x_style="hatch" 时画斜纹 = Don't Care）
#  z      : 高阻（画中间线）
#  2-9    : 数据块（画矩形 + 数值文字；色块颜色见 sig["colors"]）
#
# ---------- 可选扩展字段（都是向后兼容的，不给就保持老行为） ----------
#  config.ruler_step    : 位标尺 / 竖虚线的步长（字符数）。默认 2 = 1 bit 2 字符。
#                         4 = 每个时钟 4 字符的 DDR 图（T0..T23 那种）。
#  config.ruler_offset  : 标尺文字相对"该格起点"的偏移（字符）。默认 ruler_step//2，
#                         即居中于格；填 0 则压在格左边界（配厂商自己画在时钟沿上的 T 标号）。
#  config.x_style       : "tint"（默认，淡灰底）| "hatch"（斜纹 —— 原厂图里的 Don't Care）
#  config.x_line        : false = 未定义态区间内**不画电平线**。原厂图把 Don't Care 画成
#                         「上下边界夹一条斜纹带」，中间是没有电平线的；默认 true（画中线）。
#  sig["colors"]        : 与 sig["data"] 一一对应的色块填充色，用尽后循环。默认 #e8e4ff
#  sig["dash"]          : true = 该行折线画成虚线（未驱动 / 未激活的 DQS、CS 等）
#  sig["blank"]         : true = 只占一行高度、不画任何东西（用于分组留白）
LEVEL_LOW, LEVEL_HIGH, LEVEL_MID, LEVEL_X = 0, 1, 0.5, None


def decode_wave(wave):
    """把 wave 字符串解码为逐字符的 (level, kind) 列表。

    kind: 'lv' 普通电平 / 'blk' 数据块(2-9) / 'x' 未知 / 'z' 高阻
    """
    out = []
    prev = LEVEL_LOW
    for ch in wave:
        if ch == "0":
            out.append((LEVEL_LOW, "lv"))
        elif ch == "1":
            out.append((LEVEL_HIGH, "lv"))
        elif ch in ".=":
            out.append((prev, "lv"))
        elif ch == "p":
            out.append((LEVEL_HIGH, "lv"))
        elif ch == "x":
            out.append((LEVEL_X, "x"))
        elif ch == "z":
            out.append((LEVEL_MID, "z"))
        elif ch in "23456789":
            out.append((LEVEL_HIGH, "blk"))
        else:  # 未知字符，按低电平兜底
            out.append((LEVEL_LOW, "lv"))
        prev = out[-1][0] if out[-1][0] is not None else prev
    return out


def hatch_segments(x, y, w, h, spacing=7.0):
    """在矩形内生成 45°「/」斜纹线段（返回 [(x1,y1,x2,y2), ...]）。

    为什么不用 <pattern>：Visio 对 SVG pattern 的导入支持不可靠（可能整块丢失成
    纯色/空白），而这份 SVG 的用途就是「进 Visio 继续编辑」。显式 line 几何 100% 可导入。
    直线参数化用 u = X + Y = c（图像坐标 y 向下，故 u=c 即「/」方向）。
    """
    segs = []
    x0, y0, x1, y1 = x, y, x + w, y + h
    c = math.floor((x0 + y0) / spacing) * spacing
    while c <= x1 + y1:
        pts = []
        for ex in (x0, x1):
            ey = c - ex
            if y0 <= ey <= y1:
                pts.append((ex, ey))
        for ey in (y0, y1):
            ex = c - ey
            if x0 <= ex <= x1:
                pts.append((ex, ey))
        uniq = []
        for pt in pts:
            if not any(abs(pt[0] - q[0]) < 1e-6 and abs(pt[1] - q[1]) < 1e-6 for q in uniq):
                uniq.append(pt)
        if len(uniq) >= 2:
            uniq.sort()
            segs.append((uniq[0][0], uniq[0][1], uniq[-1][0], uniq[-1][1]))
        c += spacing
    return segs


def wave_to_polyline(levels, x0, cell, y_low, y_high, edges=None):
    """生成折线点。

    默认行为：仅在电平变化处插入**垂直**线段（直角方波，原厂时序图风格）。

    edges（可选，向后兼容）：边沿斜坡表，描述「边沿不是垂直的」。
        每项 = {"at": 字符位, "from": 0|1, "to": 0|1, "width": 斜坡宽度(字符数)}
        at    = 边沿**起点**所在字符位（**可以是小数**，如 1.5）
        from/to = 边沿前的电平 / 边沿后的电平
        width = 斜坡的水平跨度（字符数）。0 或缺省 = 垂直

    为什么要这个：真实 DDR/LPDDR 厂商图的时钟是**正弦/梯形波**（有上升/下降时间），
    边沿是斜的；画成直角就丢掉了「上升沿/下降沿在哪、占多宽」这个信息。
    实测（JEDEC LPDDR4 Fig.15）：CK_c 高平台 39px、斜坡 13px，
    墨迹在边沿处由细(2px)→粗(15px)→细 —— 垂直方波不可能产生「中间最厚」。

    ⚠️ **edges 是权威的**（2026-10-22 实测踩坑后定下的设计）：
    wave 字符串只能表达**整数位**的电平，而正弦波的边沿常落在「高平台占 1.5 字符」
    这种非整数位置。若 edges.at=1.5 而 wave 在整数位 1、2 都跳变，就会多画一竖。

    规则：wave 只提供「哪段高、哪段低」；每个 edge 认领它区间内的**第一个**跳变点，
    用斜坡代替那个垂直跳变；其余跳变照原样画垂直线。
    """
    def y_of(lv):
        if lv is None:
            return (y_low + y_high) / 2.0
        return y_low - lv * (y_low - y_high)

    # 解析 edges（at 可以是小数），按 at 排序
    es = []
    for e in (edges or []):
        try:
            at = float(e["at"])
            w = float(e.get("width", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if w > 0:
            es.append((at, w, e))
    es.sort(key=lambda t: t[0])

    # wave 的跳变点
    jumps = []
    for i in range(1, len(levels)):
        if abs(y_of(levels[i]) - y_of(levels[i - 1])) > 1e-9:
            jumps.append(i)

    # 每个 edge 认领它区间内的**第一个**跳变点；
    # 同时**抑制**区间两侧相邻整数位的跳变 —— 因为斜坡本身已经跨越了那段，
    # 若不抑制，wave 在区间前后产生的垂直跳变会与斜坡重复画。
    # 例：wave=1010（跳变点 1,2,3），edge(at=1.5,w=0.5) 覆盖 [1.5,2.0]
    #   → 认领跳变点 2 画斜坡；跳变点 1 与 3 被抑制 → 垂直段 0
    edge_for_jump = {}
    suppressed = set()
    for at, w, e in es:
        for i in jumps:
            if i in edge_for_jump or i in suppressed:
                continue
            if at - 1e-6 <= i <= at + w + 1e-6:
                edge_for_jump[i] = (at, w, e)
                # 抑制斜坡前后各一个整数位的跳变
                for j in (i - 1, i + 1):
                    if j in jumps and j not in edge_for_jump:
                        suppressed.add(j)
                break

    pts = [(x0, y_of(levels[0]))]
    for i in jumps:
        x = x0 + i * cell
        y_prev, y = y_of(levels[i - 1]), y_of(levels[i])
        if i in edge_for_jump:
            at, w, e = edge_for_jump[i]
            pts.append((x0 + at * cell, y_of(e.get("from", levels[i - 1]))))
            pts.append((x0 + (at + w) * cell, y_of(e.get("to", levels[i]))))
        elif i in suppressed:
            continue          # 由斜坡覆盖，不画垂直线
        else:
            pts.append((x, y_prev))
            pts.append((x, y))
    pts.append((x0 + len(levels) * cell, y_of(levels[-1])))
    return pts


def polyline_runs(levels_and_kinds, x0, cell):
    """把逐字符状态切成若干「非 x」连续段，返回 [(起 x, 电平列表)]。

    用于 config.x_line=False：Don't Care（斜纹）区间里不落笔，画出来就是
    「上下边界 + 中间一条斜纹带」，与原厂图画法一致（原先会多出一条中线）。
    """
    segs, cur, cur_x = [], [], None
    for i, (lv, kind) in enumerate(levels_and_kinds):
        if kind == "x":
            if cur:
                segs.append((cur_x, cur))
                cur = []
            cur_x = None
        else:
            if cur_x is None:
                cur_x = x0 + i * cell
            cur.append(lv)
    if cur:
        segs.append((cur_x, cur))
    return segs


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(wj, cell=24, row_h=60, label_w=110, show_grid=True,
           grid_step=2, grid_labels=True):
    """WaveJSON -> SVG。

    grid_step   ：竖虚线间隔（字符数）。2 = 每 1 个数据位一条（1 bit = 2 字符）。
                  0 或配合 show_grid=False 可关闭。
    grid_labels ：在波形上方输出位标尺。默认按「首尾各 2 字符留白」推导 D7…D0；
                  若 config.ruler 给了标签列表（例如从 PDF 里读到的 T0..T9），
                  就照它显示 —— **用厂商自己的网格名**比我们猜的 D7 更可信。
    config.ruler_pad ：位 0 之前的留白字符数（默认 2，配 PDF 融合时传 0）。
    """
    signals = wj.get("signal", [])
    head = (wj.get("head") or {}).get("text", "")
    foot = (wj.get("foot") or {}).get("text", "")
    cfg = wj.get("config") or {}

    # 位标尺 / 竖虚线的步长（字符数）；ruler_offset = 标尺文字相对格起点的偏移
    ruler_step = int(cfg.get("ruler_step", 2) or 2)
    if ruler_step < 1:
        ruler_step = 2
    _ro = cfg.get("ruler_offset", None)
    ruler_off = (ruler_step // 2) if _ro is None else int(_ro)
    x_style = str(cfg.get("x_style", "tint"))
    # config.grid_step 可以覆盖命令行 --grid-step（厂商图往往要求虚线落在自己的网格上）
    if "grid_step" in cfg:
        grid_step = int(cfg["grid_step"])

    n = max((len(s.get("wave", "")) for s in signals), default=0)
    wave_w = n * cell

    # 位 0 之前的留白字符数（决定标尺/虚线画在哪一格）
    pad = int(cfg.get("ruler_pad", 2))
    if pad * 2 >= n:
        pad = 0

    # 位标尺：优先用外部给的标签（PDF 的 T0..T9），否则按「首尾留白 + 1bit=2字符」推导
    bits = []
    ruler = cfg.get("ruler")
    if ruler and grid_labels:
        bits = [str(x) for x in ruler]
    elif grid_labels and n - 2 * pad >= 2 and (n - 2 * pad) % 2 == 0:
        nb = (n - 2 * pad) // 2
        bits = [f"D{nb - 1 - i}" for i in range(nb)]

    head_h = 34 if head else 8
    foot_h = 34 if foot else 8
    lbl_h = 20 if bits else 0
    body_h = row_h * len(signals)
    top0 = head_h + lbl_h                     # 第一条信号轨道的顶
    W = label_w + wave_w + 24
    H = top0 + body_h + foot_h

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" class="WaveJSON-Visio">'
    )
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{C_BG}"/>')

    if head:
        parts.append(
            f'<text x="{W/2:.1f}" y="{head_h*0.62:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" font-weight="bold" '
            f'fill="{C_TITLE}">{esc(head)}</text>'
        )

    x0 = label_w

    # ---------- 1. 轨道分隔底色（先铺底，虚线要压在它上面） ----------
    for si in range(len(signals)):
        if si % 2 == 1:
            top = top0 + si * row_h
            parts.append(
                f'<rect x="0" y="{top:.1f}" width="{W}" height="{row_h}" '
                f'fill="#000" fill-opacity="0.022"/>'
            )

    # ---------- 2. 贯穿全部信号的时钟对齐虚线 ----------
    #    画在波形之前，所以不会盖住任何电平边沿；
    #    一条线同时穿过 CS_n / SCLK / MOSI / MISO，用于肉眼确认
    #    「第 k 个数据位 == 第 k 个 SCLK 周期」。
    if show_grid and grid_step and grid_step > 0:
        gy1 = (top0 - lbl_h + 5) if lbl_h else (top0 + 4)
        gy2 = top0 + body_h - 4
        i = grid_step
        while i < n:
            gx = x0 + i * cell
            parts.append(
                f'<line x1="{gx:.1f}" y1="{gy1:.1f}" x2="{gx:.1f}" y2="{gy2:.1f}" '
                f'stroke="{C_GRID}" stroke-width="0.7" stroke-dasharray="3,3"/>'
            )
            i += grid_step

    # ---------- 3. 位标尺，按 ruler_step / ruler_offset 摆放 ----------
    for k, lbl in enumerate(bits):
        cx = x0 + (pad + ruler_step * k + ruler_off) * cell
        if not str(lbl).strip():
            continue
        parts.append(
            f'<text x="{cx:.1f}" y="{head_h + lbl_h*0.70:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11.5" fill="#6b7280">{esc(lbl)}</text>'
        )

    # ---------- 4. 每条信号 ----------
    for si, sig in enumerate(signals):
        if sig.get("blank"):
            continue
        top = top0 + si * row_h
        pad_v = row_h * 0.17                 # 轨道内上下留白
        y_high = top + pad_v
        y_low = top + row_h - 1 - pad_v

        levels_and_kinds = decode_wave(sig.get("wave", ""))
        levels = [lv for lv, _ in levels_and_kinds]

        # 未知态底色（tint 淡灰底 / hatch 斜纹 = Don't Care）
        #   连续 x 合并成**一个**区域：hatch 模式下给它一圈边界线 + 显式斜线
        #   （原厂图 Don't Care 区就是「上下边界 + 斜纹带」），逐字符画会多出内部竖线
        x_fill = ('#ffffff' if x_style == "hatch" else "#c9ccd1")
        x_op = '' if x_style == "hatch" else ' fill-opacity="0.30"'
        x_stroke = (' stroke="#6b7280" stroke-width="1"' if x_style == "hatch" else '')
        i = 0
        while i < len(levels_and_kinds):
            if levels_and_kinds[i][1] != "x":
                i += 1
                continue
            j = i
            while j < len(levels_and_kinds) and levels_and_kinds[j][1] == "x":
                j += 1
            rx, rw = x0 + i * cell, (j - i) * cell
            # ⚠️ 顺序不能反：白底矩形必须先画，斜线画在它上面。
            #    第一版把 rect 放在 <g> 之后，白色填充把斜线整个盖掉（图上是空框）。
            parts.append(
                f'<rect x="{rx:.1f}" y="{y_high:.1f}" width="{rw:.1f}" '
                f'height="{y_low-y_high:.1f}" fill="{x_fill}"{x_op}{x_stroke}/>'
            )
            if x_style == "hatch":
                segs = hatch_segments(rx, y_high, rw, y_low - y_high)
                parts.append(f'<g stroke="{C_HATCH}" stroke-width="0.9">')
                for sxa, sya, sxb, syb in segs:
                    parts.append(f'<line x1="{sxa:.1f}" y1="{sya:.1f}" '
                                 f'x2="{sxb:.1f}" y2="{syb:.1f}"/>')
                parts.append('</g>')
            i = j

        # 波形折线（sig["dash"]=True 画虚线：未驱动的 DQS / 反选中的 CS）
        #          config.x_line=False 时，x 区间跳过不画（Don't Care 只留斜纹带）
        dash_attr = ' stroke-dasharray="5,3"' if sig.get("dash") else ""
        if cfg.get("x_line", True):
            stroke_runs = [(x0, levels)]
        else:
            stroke_runs = polyline_runs(levels_and_kinds, x0, cell)
        for sx, lvs in stroke_runs:
            # 斜坡边沿（sig["edges"]）：只在完整的一段上应用（x_line=False 时按段偏移）
            seg_edges = None
            if sig.get("edges"):
                if sx == x0:
                    seg_edges = sig["edges"]
                else:
                    # 非 x 段：把边沿的字符位平移到本段起点
                    off = (sx - x0) / cell if cell else 0
                    seg_edges = []
                    for e in sig["edges"]:
                        try:
                            at = float(e["at"]) - off
                        except (KeyError, TypeError, ValueError):
                            continue
                        e2 = dict(e)
                        e2["at"] = at
                        seg_edges.append(e2)
            pts = wave_to_polyline(lvs, sx, cell, y_low, y_high, edges=seg_edges)
            d = "M " + " L ".join(f"{px:.2f},{py:.2f}" for px, py in pts)
            parts.append(
                f'<path d="{d}" fill="none" stroke="{C_LINE}" stroke-width="1.6" '
                f'stroke-linejoin="miter" stroke-linecap="butt"{dash_attr}/>'
            )

        # 数据块（2-9）：矩形 + 数值文字
        #   · `2..` 里的 `.` / `=` 是**延续**，要把整块拉宽（不是每个字符一个小方块）
        #   · 文字优先取 sig["data"]（WaveDrom 语义：按块出现顺序消费，用尽后循环），
        #     没有 data 时退回显示块字符本身（兼容老行为）
        #   · 填充色取 sig["colors"]（与 data 同序；不给则用默认淡紫）
        wave = sig.get("wave", "")
        data = sig.get("data") or []
        colors = sig.get("colors") or []
        blk_idx, i = 0, 0
        while i < len(wave):
            if wave[i] not in "23456789":
                i += 1
                continue
            j = i + 1
            while j < len(wave) and wave[j] in ".=":
                j += 1
            bx, by = x0 + i * cell, y_high
            bh, bw = (y_low - y_high), (j - i) * cell
            fill = colors[blk_idx % len(colors)] if colors else "#e8e4ff"
            parts.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                f'fill="{fill}" stroke="{C_LINE}" stroke-width="1"/>'
            )
            label = data[blk_idx % len(data)] if data else wave[i]
            # 字号自适应：既要装得下 cell*0.55 的字高，也要装得下这段文字的总宽。
            # 系数 1.85 = 1/0.54（Helvetica 平均字宽 ≈ 0.54×字号），留一点安全边。
            # 原先取 1.45 过于保守，`COLUMN m(2)` 会被缩到 6px 不可读。
            fs = min(11.0, cell * 0.55,
                     bw / max(1, len(str(label))) * 1.85) if str(label) else 0
            if str(label):
                parts.append(
                    f'<text x="{bx+bw/2:.1f}" y="{by+bh*0.68:.1f}" text-anchor="middle" '
                    f'font-family="{FONT}" font-size="{fs:.1f}" '
                    f'fill="#222">{esc(label)}</text>'
                )
            blk_idx += 1
            i = j

        # 信号名（右对齐到标签区右边界）
        if str(sig.get("name", "")).strip():
            parts.append(
                f'<text x="{label_w-10}" y="{(y_high+y_low)/2+4:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="14" font-weight="bold" '
                f'fill="{C_LABEL}">{esc(sig.get("name",""))}</text>'
            )

        # ---------- 延时标注（sig["delays"]）----------
        #   画在信号行**上方**的空隙里：横线 + 两端箭头 + 居中文字。
        #   原厂图用它标注「RL = 10」这类读延时、以及边沿之间的间隔。
        #   格式：{"from": 字符位, "to": 字符位, "label": "RL = 10", "dy": 额外上移(px)}
        #   from/to 都是**字符位**（可带小数），直接换算成 x 坐标。
        for d in (sig.get("delays") or []):
            try:
                fa = float(d["from"])
                ta = float(d["to"])
            except (KeyError, TypeError, ValueError):
                continue
            if ta <= fa:
                continue
            dx = x0 + fa * cell
            tx = x0 + ta * cell
            # 标注画在本行顶之上；dy 可再上移（叠多条标注时用）
            dy = float(d.get("dy", 0) or 0)
            ay = y_high - 9 - dy
            lbl = str(d.get("label", "") or "")
            parts.append(
                f'<line x1="{dx:.1f}" y1="{ay:.1f}" x2="{tx:.1f}" y2="{ay:.1f}" '
                f'stroke="#111" stroke-width="1"/>'
            )
            # 两端箭头（实心三角，指向两端）
            for ax, sgn in ((dx, 1), (tx, -1)):
                parts.append(
                    f'<path d="M {ax:.1f},{ay:.1f} L {ax+sgn*8:.1f},{ay-3.6:.1f} '
                    f'L {ax+sgn*8:.1f},{ay+3.6:.1f} Z" fill="#111"/>'
                )
            if lbl:
                parts.append(
                    f'<text x="{(dx+tx)/2:.1f}" y="{ay-4:.1f}" text-anchor="middle" '
                    f'font-family="{FONT}" font-size="12.5" fill="#111">{esc(lbl)}</text>'
                )

    if foot:
        parts.append(
            f'<text x="{label_w + wave_w/2:.1f}" y="{H - foot_h*0.36:.1f}" '
            f'text-anchor="middle" font-family="{FONT}" font-size="12.5" '
            f'fill="{C_TITLE}">{esc(foot)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="WaveJSON -> 直角方波 SVG（Visio 友好）")
    ap.add_argument("input", help="WaveJSON 文件路径（或 - 从 stdin 读）")
    ap.add_argument("-o", "--out", help="输出 SVG 路径（默认 stdout）")
    ap.add_argument("--cell", type=float, default=24, help="每字符宽度 px（默认 24）")
    ap.add_argument("--row", type=float, default=60, help="每信号行高 px（默认 60）")
    ap.add_argument("--label-width", type=float, default=110, help="左侧信号名区宽度")
    ap.add_argument("--no-grid", action="store_true", help="完全不画竖虚线")
    ap.add_argument("--grid-step", type=int, default=2,
                    help="竖虚线间隔（字符数）。2 = 每 1 个数据位一条（默认）")
    ap.add_argument("--no-grid-labels", action="store_true",
                    help="不画顶部 D7…D0 位标尺")
    a = ap.parse_args()

    raw = sys.stdin.read() if a.input == "-" else open(a.input, encoding="utf-8").read()
    wj = json.loads(raw)
    svg = render(wj, cell=a.cell, row_h=a.row, label_w=a.label_width,
                 show_grid=not a.no_grid, grid_step=a.grid_step,
                 grid_labels=not a.no_grid_labels)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"✓ {a.out}  ({len(svg)} bytes)")
    else:
        sys.stdout.write(svg)


if __name__ == "__main__":
    main()
