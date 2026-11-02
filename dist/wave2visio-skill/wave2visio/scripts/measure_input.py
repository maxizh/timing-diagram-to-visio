#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_input.py — 从「原图」里量出时钟对齐线该画在哪，落盘成 clk-overlay.json。

设计原则（对应铁律 0：原图不可修改）：
  * 本脚本**只读**原图，绝不写回、绝不重画。原图是基准，不是产物。
  * 叠加线位置不靠人手算，而是**从原图自身的 SCLK 时钟边沿量出来** ——
    这样任何人对原图的改动都会让叠加线对不上，且能被 selftest 发现。
  * 量出来的结果存 `assets/clk-overlay.json`，网页/报告只消费这份 JSON。

量什么：
  1. 绘图区左右边界（看哪两列在整幅图高度上都是深色 → 坐标轴竖边框）
  2. 面板堆叠的上下边界（近满宽的深色行 → 横边框）
  3. SCLK 面板里的电平跳变 → 取上升沿 = 每个 SCLK 周期的起点
  4. 位边界 = 8 个上升沿 + 末尾再加一个周期

依赖：matplotlib（读 PNG）+ numpy。仅在需要重新测量时运行。
用法：
  python3 scripts/measure_input.py            # 重新测量并写入 assets/clk-overlay.json
  python3 scripts/measure_input.py --print    # 只打印，不落盘
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_PNG = os.path.join(ROOT, "assets", "test-input-spi.png")
DEFAULT_OUT = os.path.join(ROOT, "assets", "clk-overlay.json")

# 检测参数
DARK = 0.45          # 灰度阈值：低于此视为深色（信号线 / 边框）
SPINE_COL = 0.75     # 整列深色比例 > 此值 → 竖直边框
SPINE_ROW = 0.80     # 整行深色比例 > 此值 → 横边框
JUMP = 20            # 电平跳变判定：上下端像素差 > 此值


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _group(vals, gap):
    out, cur = [], []
    for v in vals:
        if cur and v - cur[-1] > gap:
            out.append(cur)
            cur = []
        cur.append(v)
    if cur:
        out.append(cur)
    return out


def measure(png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import numpy as np

    im = mpimg.imread(png_path)[..., :3]
    H, W = im.shape[:2]
    g = im.mean(axis=2)
    dark = g < DARK

    # --- 1. 面板横边框 ---
    rf = dark.mean(axis=1)
    spine_rows = [y for y in range(H) if rf[y] > SPINE_ROW]
    row_groups = _group(spine_rows, 4)
    if len(row_groups) < 8:
        raise SystemExit(f"只找到 {len(row_groups)} 条横边框，期望 8 条（4 个面板）")

    # 相邻两条组成一个面板： (top, bottom)
    panels = [(row_groups[i][0], row_groups[i + 1][-1])
              for i in range(0, len(row_groups) - 1, 2)]
    stack_top, stack_bot = panels[0][0], panels[-1][1]

    # --- 2. 绘图区左右边界 ---
    band = dark[stack_top:stack_bot + 1, :]
    cf = band.mean(axis=0)
    spine_cols = [x for x in range(W) if cf[x] > SPINE_COL]
    col_groups = _group(spine_cols, 4)
    if len(col_groups) < 2:
        raise SystemExit("找不到绘图区左右边框")
    plot_l, plot_r = col_groups[0][0], col_groups[-1][-1]

    # --- 3. SCLK 面板的跳变（第 2 个面板） ---
    assert len(panels) >= 2, "面板数不足 2，无法定位 SCLK"
    py0, py1 = panels[1]
    inner = dark[py0 + 2:py1 - 1, :]
    top_of = {}
    nz = inner.argmax(axis=0)         # 每列第一个深色像素的相对行号
    has = inner.any(axis=0)
    for x in range(plot_l, plot_r + 1):
        if has[x]:
            top_of[x] = int(nz[x])

    jumps = []
    for x in range(plot_l + 3, plot_r - 2):
        if x - 3 in top_of and x + 3 in top_of:
            if abs(top_of[x - 3] - top_of[x + 3]) > JUMP:
                jumps.append(x)
    jump_groups = _group(jumps, 8)
    edges = [int(round(sum(gr) / len(gr))) for gr in jump_groups]

    # 上升沿 = 顶端像素变小（电平升高）
    rises = []
    for e in edges:
        a, b = top_of.get(e - 4), top_of.get(e + 4)
        if a is not None and b is not None and b < a:
            rises.append(e)

    if len(rises) < 2:
        raise SystemExit(f"只找到 {len(rises)} 个 SCLK 上升沿")

    period = (rises[-1] - rises[0]) / (len(rises) - 1)
    boundaries_px = rises + [rises[-1] + period]

    out = {
        "source_png": os.path.basename(png_path),
        "sha256": sha256(png_path),
        "size": [W, H],
        "plot_x": [plot_l, plot_r],
        "panel_stack_y": [stack_top, stack_bot],
        "panels_y": [list(p) for p in panels],
        "sclk_edges_px": edges,
        "sclk_rises_px": rises,
        "sclk_period_px": round(period, 3),
        "boundaries_px": [round(v, 3) for v in boundaries_px],
        "boundaries_frac": [round(v / W, 6) for v in boundaries_px],
        "line_y_frac": [round(stack_top / H, 6), round(stack_bot / H, 6)],
        "_note": "由 scripts/measure_input.py 从原图实测；原图本身未被修改",
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default=DEFAULT_PNG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--print", dest="do_print", action="store_true")
    a = ap.parse_args()

    data = measure(a.png)
    print(f"原图 {data['source_png']}  {data['size'][0]}x{data['size'][1]}")
    print(f"  sha256      {data['sha256']}")
    print(f"  绘图区 x    {data['plot_x']}")
    print(f"  面板堆叠 y  {data['panel_stack_y']}")
    print(f"  SCLK 上升沿 {data['sclk_rises_px']}")
    print(f"  SCLK 周期   {data['sclk_period_px']} px")
    print(f"  位边界(px)  {data['boundaries_px']}")
    print(f"  位边界(%)   {[round(f*100, 3) for f in data['boundaries_frac']]}")

    if not a.do_print:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 已写入 {a.out}")


if __name__ == "__main__":
    main()
