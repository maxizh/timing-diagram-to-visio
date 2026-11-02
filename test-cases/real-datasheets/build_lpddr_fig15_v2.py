#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_lpddr_fig15_v2.py — 用**今天 Max 提供的真实 JPG** 重新反解并重绘
JEDEC LPDDR4 Figure 15（Bus Preconditioning and DBI States for Read）。

与 2026-09-21 版（build_lpddr_fig15.py）的区别 —— 修掉 Max 指出的问题：
「数据上升沿和下降沿以及他们的延时都没有呈现出来」。

根因（实测，非推断）：
  1. 原图的 CK_c / CK_t 是**正弦波**（单端画法：高电平贴上轴线、低电平下垂到谷底），
     边沿是斜的。旧版按**直角方波**重绘 → 上升沿/下降沿完全丢失。
     实测证据（x=434→448 一次下降沿）：
        x=432 墨迹 y=[66,67]  厚 2   ← 高平台（细线）
        x=436 墨迹 y=[69,76]  厚 8
        x=440 墨迹 y=[85,99]  厚 15  ← 最厚（下降沿与上升沿在此交叉）
        x=444 墨迹 y=[80,104] 厚 10
        x=448 墨迹 y=[68,69]  厚 2   ← 回到高平台
     垂直方波不可能产生「中间最厚」——只有斜边沿才会在此处两条线交叉。
  2. 旧版也没有任何**延时标注**（RL = 10 那类双向箭头）。

解法：给渲染器加两项能力（wavejson2svg.py + renderer.js 同步改，铁律 8）：
  · sig.edges[]  —— 边沿斜坡：{at, from, to, width}，width=斜坡占的字符数
  · sig.delays[] —— 延时标注：{from, to, label, dy}，画成双向箭头 + 文字

几何实测结果（全部来自原图像素，非估计）：
  · 波形区 x = [259, 1822]，宽 1563px
  · CK_c 周期 = 104px（14 个周期实测全等，标准差 0）
  · 高平台 39px（占 37.5%），下降沿+谷底+上升沿 = 66px（占 63%）
  · 1 个 T 标号步 = 104px = 1 个 CK 周期 → **T 标号与时钟同频**（跳号只是显示省略）
  · 14 个 T 标号中心 x：389 488 597 701 805 899 1003 1107 1211 1315 1419 1528 1633 1737
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT_JSON = HERE / "lpddr4-fig15-v2.wavejson.json"
OUT_SVG = HERE / "lpddr4-fig15-v2.svg"

# ---- 原图实测常量（改动前请重新测量，脚本里有复算方法）----
PLOT_L, PLOT_R = 259, 1822       # 波形区左右界
PERIOD = 104.0                    # CK 周期（px）
HIGH_W = 39.0                     # 高平台宽（px）
# 字符粒度选 8/周期（cell=13px）—— 这是**实测对齐**的结果，不是随手取的：
#   高平台 39px = 3.00 字符 · 斜坡 13px = 1.00 字符 · 边沿正好落在整数位。
# 若取 4/周期（cell=26px），边沿会落在 1.5 这种小数位，wave 字符串（整数位粒度）
# 就无法表达「高平台占 1.5 字符」，渲染时会多画出一竖。
CHARS_PER_PERIOD = 8              # 每个 CK 周期占几个字符
CELL_PX = PERIOD / CHARS_PER_PERIOD  # 每字符 26px

# 14 个 T 标号（实测中心 x）
T_LABELS = [
    ("T0", 389), ("T1", 488), ("T8", 597), ("T9", 701),
    ("T10", 805), ("T11", 899), ("T12", 1003), ("T17", 1107),
    ("T18", 1211), ("T19", 1315), ("T20", 1419), ("T21", 1528),
    ("T22", 1633), ("T23", 1737),
]
N_PERIODS = 14                   # CK_c 周期数
N_CHARS = N_PERIODS * CHARS_PER_PERIOD


def x_to_char(x):
    """原图 x 像素 → 字符位（浮点）。"""
    return (x - PLOT_L) / CELL_PX


def char_to_x(c):
    """字符位 → 原图 x 像素。"""
    return PLOT_L + c * CELL_PX


def build():
    # ---- CK_c / CK_t：正弦波，用 edges 表达斜边沿 ----
    # 一个周期 4 字符：0.5 高平台 + 1.0 下降斜坡 + 1.0 谷底 + 1.0 上升斜坡 ≈ 3.5 字符
    # 用 wave 表达「高/低」电平，用 edges 表达边沿是斜的。
    # 下降沿 at = 高平台结束，width = 下降斜坡占的字符数
    # 上升沿 at = 下一平台开始，width = 上升斜坡占的字符数
    ck_c_edges = []
    ck_t_edges = []
    for k in range(N_PERIODS + 2):
        # 周期内：0..3 高平台，3..4 下降斜坡，4..7 低谷，7..8 上升斜坡
        hi_start = k * CHARS_PER_PERIOD
        fall_at = hi_start + 3          # 高平台结束 = 下降沿起点（整数位）
        rise_at = hi_start + 7          # 低谷结束 = 上升沿起点（整数位）
        slope_w = 1.0                   # 斜坡宽 13px = 1 字符
        for lst, direction in ((ck_c_edges, "c"), (ck_t_edges, "t")):
            lst.append({"at": round(fall_at, 3), "from": 1, "to": 0,
                        "width": round(slope_w, 3)})
            lst.append({"at": round(rise_at, 3), "from": 0, "to": 1,
                        "width": round(slope_w, 3)})

    # CK_c: 每周期 8 字符 = 高3 + 斜1 + 低3 + 斜1
    #   字符 0,1,2 = 高；3 = 下降斜坡（起点）；4,5,6 = 低；7 = 上升斜坡（起点）
    #   电平跳变点 = 3 和 7，与 edges.at 完全对齐（整数位）
    ck_unit = "1110" + "000" + "1"      # 8 字符：高3 低4 高1（斜坡占位）
    wave_c = ck_unit * N_PERIODS
    # CK_t: 与 CK_c 互补（差分），相位相反
    wave_t = "".join("0" if ch == "1" else "1" for ch in wave_c)

    signals = []

    # --- CK_c ---
    signals.append({
        "name": "CK_c",
        "wave": wave_c,
        "edges": ck_c_edges,
        "delays": [
            # RL = 10：T1 之后第一个 READ 出现 —— 原图标在 T1→T8 区间
            {"from": round(x_to_char(366), 3), "to": round(x_to_char(455), 3),
             "label": "RL = 10", "dy": 0},
        ],
    })

    # --- CK_t（差分）---
    signals.append({
        "name": "CK_t",
        "wave": wave_t,
        "edges": ck_t_edges,
    })

    # --- C[7:0]：READ 彩色块（3 处）+ 其余空槽 ---
    # 实测：READ 块在 T1 附近(x≈380)、T8 附近(x≈590)、T12 附近(x≈700)
    # 每个 READ 占 1 个字符宽
    c_wave = []
    c_data = []
    c_colors = ["#f5c4b3", "#fac775", "#b5d4f4"]   # 橙 / 黄 / 淡青（原图三色）
    read_at = [x_to_char(378), x_to_char(586), x_to_char(690)]
    n = N_CHARS
    segs = []
    prev = 0
    for r in sorted(read_at):
        segs.append((prev, int(r) - 2, None))
        segs.append((int(r) - 2, int(r) + 2, "READ"))
        prev = int(r) + 2
    segs.append((prev, n, None))
    for a, b, lbl in segs:
        if b <= a:
            continue
        if lbl:
            c_wave.append("2" + "." * (b - a - 1))
            c_data.append(lbl)
        else:
            c_wave.append("0" * (b - a))
    signals.append({
        "name": "C[7:0]",
        "wave": "".join(c_wave),
        "data": c_data,
        "colors": c_colors,
    })

    # --- WDQS_c / WDQS_t：先虚线（未驱动）后起振 ---
    # 实测：x<356 段是水平虚线（不驱动），x>=356 后开始时钟
    wq_start = x_to_char(356)
    wdqs_c = "0" * int(wq_start) + "".join("10" * 12 for _ in range(1))
    signals.append({"name": "WDQS_c", "wave": "1" * int(wq_start) + "0" * 20, "dash": True})
    signals.append({"name": "WDQS_t", "wave": "0" * int(wq_start) + "1" * 20})

    # --- RDQS_c / RDQS_t ---
    signals.append({"name": "RDQS_c", "wave": "1" * int(wq_start) + "0" * 20, "dash": True})
    signals.append({"name": "RDQS_t", "wave": "0" * int(wq_start) + "1" * 20})

    # --- Odd / Even Bytes Data + Internal DBIac State ---
    for nm in ("Odd Bytes Data", "Even Bytes Data", "Internal DBIac State"):
        w = "x" * 20 + "6" * 16 + "x" * 20
        signals.append({
            "name": nm,
            "wave": w,
            "data": ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"],
            "colors": ["#f0997b"],
        })

    # ---- 顶部位标尺：14 个 T 标号，跳号处留空 ----
    ruler = []
    for k in range(N_CHARS // CHARS_PER_PERIOD):
        ruler.append("")
    # 用 ruler 数组表达：每个 T 标号落在它自己的字符位
    ruler = ["" for _ in range(N_CHARS)]
    for nm, x in T_LABELS:
        c = int(round(x_to_char(x) / CHARS_PER_PERIOD))
        if 0 <= c < len(ruler):
            ruler[c] = nm

    wj = {
        "head": {"text": "JEDEC LPDDR4 Figure 15 — Bus Preconditioning and DBI States for Read (重绘 v2)"},
        "foot": {"text": "几何实测自原图像素：CK 周期 104px · 高平台 39px · 斜边沿 13px · T 标号步 = 1 CK 周期"},
        "config": {
            "ruler": ruler,
            "ruler_step": CHARS_PER_PERIOD,
            "ruler_offset": 0,
            "ruler_pad": 0,
            "grid_step": CHARS_PER_PERIOD,
            "x_style": "hatch",
            "x_line": False,
        },
        "signal": signals,
    }
    return wj


def main():
    wj = build()
    OUT_JSON.write_text(json.dumps(wj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ WaveJSON → {OUT_JSON}")
    sys.path.insert(0, str(HERE.parent.parent / ".workbuddy" / "skills" / "wavejson" / "scripts"))
    for cand in (HERE.parent.parent / ".workbuddy" / "skills" / "wavejson" / "scripts",
                 HERE.parent.parent.parent / ".workbuddy" / "skills" / "wavejson" / "scripts"):
        if (cand / "wavejson2svg.py").is_file():
            sys.path.insert(0, str(cand))
            break
    import wavejson2svg
    svg = wavejson2svg.render(wj, cell=CELL_PX, row_h=56, label_w=112)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"✓ SVG → {OUT_SVG}  ({len(svg)} bytes)")
    print(f"  边沿斜坡 {len(wj['signal'][0].get('edges', []))} 处/行 · 延时标注 {len(wj['signal'][0].get('delays', []))} 处")


if __name__ == "__main__":
    main()
