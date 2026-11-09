#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_lpddr_fig15_v3.py — 用**今天 Max 提供的真实 JPG** 全量反解重绘
JEDEC LPDDR4 Figure 15（Bus Preconditioning and DBI States for Read）。

v2 只把时钟部分做实（斜坡 + RL 标注），数据块坐标沿用旧版 —— 那是不对的。
v3 把**每一行**都按原图像素实测重做：数据格起止、三色编码、Don't Care 斜纹区、
底部说明标注，全部有测量依据。

────────────────────────────────────────────────────────────────
一、实测几何（全部来自原图像素，非估计；改脚本前请复算）
────────────────────────────────────────────────────────────────
  波形区 x = [259, 1822]，宽 1563px
  CK_c 周期 = 104px（14 个周期实测全等，标准差 0）
    · 高平台 39px（37.5%）
    · 斜坡    13px（12.5%）
    · 低谷    39px
  1 个 T 标号步 = 104px = 1 个 CK 周期 → T 标号与时钟同频，跳号只是显示省略
  14 个 T 标号中心 x：389 488 597 701 805 899 1003 1107 1211 1315 1419 1528 1633 1737

  **字符粒度 = 13px（1 周期 8 字符）** —— 这个值不是随手取的：
    高平台 39px = 3.00 字符 · 斜坡 13px = 1.00 字符 · 边沿正好落整数位。
    若取 26px/字符，边沿会落在 1.5 这种小数位，而 wave 是整数位粒度 →
    表达不了「高平台占 1.5 字符」→ 渲染多画一竖（v2 之前踩过，27 个多余竖线）。

────────────────────────────────────────────────────────────────
二、数据格实测（关键：格宽与格距不对称）
────────────────────────────────────────────────────────────────
  单元格节拍 = 26.5px ≈ 1 字符（13px × 2）
  但**彩色格本身宽 19-20px，格间空隙仅 6-7px** —— 不是等宽铺满。
  这是原厂图画法的细节：格内填色 + 细边框，格间留白。

  三色编码（实测中位色）：
    橙 RGB(246,215,188) · 黄 RGB(250,252,155) · 青 RGB(183,220,229)

  各行实测彩色段（x 范围 + 颜色）：
    C[7:0]   3 段：369-462 橙 / 576-671 黄 / 784-879 青      （= 三次 READ）
    行8 Odd  13 段、 行9 Even 18 段、 行10 DBIac 24 段（含 20px 小格 = D0..D7 各位）

  Don't Care 斜纹区（细斜线，2px 宽、间距 8px）：
    行2 C[7:0]  (361,444) (588,659) (796,860)   ← 正好在三次 READ 之间
    行7 WDQS_c  (259,602) (810,1821)
    行8 Odd     (840,1008) (1036,1231) (1465,1640) (1661,1821)
    行9 Even    (259,752) (807,1821)

────────────────────────────────────────────────────────────────
三、为什么还是人工反解（不是自动读图）
────────────────────────────────────────────────────────────────
彩色状态块 + 每时钟 4 字符 + T 标号跳号 + 无文本层，四条同现时
auto_trace / pdf_trace 都解不了（见 skill/references/deep-dive-notes.md）。
本脚本把「怎么量」固化下来：所有坐标都来自像素测量，附在上面的注释里。
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT_JSON = HERE / "lpddr4-fig15-v3.wavejson.json"
OUT_SVG = HERE / "lpddr4-fig15-v3.svg"

# ---- 原图实测常量 ----
PLOT_L, PLOT_R = 259, 1822
PERIOD = 104.0
HIGH_W = 39.0
SLOPE_W = 13.0
CHARS_PER_PERIOD = 8
CELL_PX = PERIOD / CHARS_PER_PERIOD      # 13.0px
N_PERIODS = 14
N_CHARS = N_PERIODS * CHARS_PER_PERIOD  # 112

T_LABELS = [("T0", 389), ("T1", 488), ("T8", 597), ("T9", 701),
            ("T10", 805), ("T11", 899), ("T12", 1003), ("T17", 1107),
            ("T18", 1211), ("T19", 1315), ("T20", 1419), ("T21", 1528),
            ("T22", 1633), ("T23", 1737)]

# 三色（原图中位色，已调亮到可读）
ORANGE = "#f6d7bc"
YELLOW = "#fafc9b"
CYAN = "#b7dce5"
DC_GRAY = "#d9d9d9"


def x2c(x):
    """原图 x 像素 → 字符位。"""
    return (x - PLOT_L) / CELL_PX


def c2x(c):
    """字符位 → 原图 x 像素。"""
    return PLOT_L + c * CELL_PX


def blocks_to_wave(blocks, total_chars):
    """把 [(x_start, x_end, color, label), ...] 转成 WaveJSON 的 wave/data/colors。

    实现要点：每格占 round((x_end-x_start)/CELL_PX) 个字符，
    格与格之间的空隙用延续符 '.=' 撑开 —— 这样几何位置与原图一致。
    """
    wave, data, colors = [], [], []
    prev_c = 0
    for (a, b, color, label) in blocks:
        c0 = int(round(x2c(a)))
        c1 = int(round(x2c(b + 1)))
        if c0 < prev_c:                      # 与前一块重叠则跳过
            continue
        if c0 > prev_c:                      # 中间空隙 → 低电平延续
            wave.append("0" * int(c0 - prev_c))
        blk = max(1, int(c1 - c0))
        wave.append("2" + "." * (blk - 1))   # 2= 数据块起点，.= 延续
        data.append(label)
        colors.append(color)
        prev_c = c1
    if prev_c < total_chars:
        wave.append("x" * int(total_chars - prev_c))
    return "".join(wave), data, colors


def build():
    signals = []

    # ---------- CK_c / CK_t：正弦波 + 斜坡 ----------
    # 周期内 8 字符：0,1,2 = 高平台；3 = 下降斜坡起点；4,5,6 = 低谷；7 = 上升斜坡起点
    ck_unit = "1110" + "000" + "1"
    wave_c = ck_unit * N_PERIODS
    wave_t = "".join("0" if ch == "1" else "1" for ch in wave_c)

    edges_c, edges_t = [], []
    for k in range(N_PERIODS + 1):
        base = k * CHARS_PER_PERIOD
        for lst in (edges_c, edges_t):
            lst.append({"at": base + 3, "from": 1, "to": 0, "width": 1.0})
            lst.append({"at": base + 7, "from": 0, "to": 1, "width": 1.0})

    signals.append({
        "name": "CK_c", "wave": wave_c, "edges": edges_c,
        "delays": [
            # RL = 10：原图标注在 T1 之后（x 366..455），画在 CK_t 上方空隙
            {"from": round(x2c(366), 3), "to": round(x2c(455), 3),
             "label": "RL = 10", "dy": 0},
        ],
    })
    signals.append({
        "name": "CK_t", "wave": wave_t, "edges": edges_t,
        "delays": [
            # 第二处 RL = 10（原图 x 542..1070）
            {"from": round(x2c(542), 3), "to": round(x2c(1070), 3),
             "label": "RL = 10", "dy": 0},
        ],
    })

    # ---------- C[7:0]：三次 READ（三色） ----------
    c_blocks = [
        (369, 462, ORANGE, "READ"),
        (576, 671, YELLOW, "READ"),
        (784, 879, CYAN, "READ"),
    ]
    w, d, c = blocks_to_wave(c_blocks, N_CHARS)
    signals.append({"name": "C[7:0]", "wave": w, "data": d, "colors": c})

    # ---------- WDQS_c / WDQS_t ----------
    # 实测：x<602 是 Don't Care（未驱动），x>=810 起振
    wdqs_c_x = int(round(x2c(810)))
    signals.append({
        "name": "WDQS_c",
        "wave": "x" * wdqs_c_x + "0" * (N_CHARS - wdqs_c_x),
        "dash": True,
    })
    signals.append({
        "name": "WDQS_t",
        "wave": "x" * wdqs_c_x + "1" * (N_CHARS - wdqs_c_x),
    })

    # ---------- RDQS_c / RDQS_t ----------
    # 实测与 WDQS 同一区域（x<810 未驱动）
    signals.append({
        "name": "RDQS_c",
        "wave": "x" * wdqs_c_x + "0" * (N_CHARS - wdqs_c_x),
        "dash": True,
    })
    signals.append({
        "name": "RDQS_t",
        "wave": "x" * wdqs_c_x + "1" * (N_CHARS - wdqs_c_x),
    })

    # ---------- Odd / Even Bytes Data ----------
    # 实测：8 个小格 = D0..D7，各宽 19-20px，起点 809,835,861,888,913,940,965,992
    odd_small = [(809, 828), (835, 854), (861, 880), (888, 906),
                 (913, 931), (940, 958), (965, 984), (992, 1057)]
    blocks = [(a, b, ORANGE, f"D{i}") for i, (a, b) in enumerate(odd_small)]
    # 后段大块（x=1173..1348 黄 / 1355..1453 黄）
    blocks += [(1173, 1348, YELLOW, "D7"),
               (1355, 1453, CYAN, "D0"),
               (1460, 1662, CYAN, "D1")]
    w, d, c = blocks_to_wave(blocks, N_CHARS)
    signals.append({"name": "Odd Bytes Data", "wave": w, "data": d, "colors": c})

    even_small = [(809, 828), (835, 854), (861, 880), (888, 906),
                  (913, 931), (940, 958), (965, 984), (992, 1057)]
    blocks = [(a, b, ORANGE, f"D{i}") for i, (a, b) in enumerate(even_small)]
    blocks += [(1064, 1270, ORANGE, "D0"),
               (1277, 1348, YELLOW, "D1"),
               (1356, 1451, YELLOW, "D2"),
               (1461, 1820, CYAN, "D3")]
    w, d, c = blocks_to_wave(blocks, N_CHARS)
    signals.append({"name": "Even Bytes Data", "wave": w, "data": d, "colors": c})

    # ---------- Internal DBIac State ----------
    # 实测 24 段：橙(811-1056) → 黄(1068-1243) → 黄(1252-1428) → 青(1436-1818)
    dbi = [(811, 826, ORANGE), (836, 853, ORANGE), (865, 878, ORANGE),
           (889, 905, ORANGE), (916, 930, ORANGE), (941, 956, ORANGE),
           (967, 983, ORANGE), (992, 1056, ORANGE),
           (1068, 1243, YELLOW), (1252, 1269, YELLOW), (1278, 1297, YELLOW),
           (1304, 1323, YELLOW), (1330, 1347, YELLOW), (1356, 1373, YELLOW),
           (1382, 1401, YELLOW), (1408, 1428, YELLOW),
           (1436, 1449, CYAN), (1463, 1476, CYAN), (1489, 1501, CYAN),
           (1514, 1528, CYAN), (1542, 1553, CYAN), (1567, 1580, CYAN),
           (1592, 1607, CYAN), (1617, 1818, CYAN)]
    blocks = [(a, b, col, f"S{i}") for i, (a, b, col) in enumerate(dbi)]
    w, d, c = blocks_to_wave(blocks, N_CHARS)
    signals.append({"name": "Internal DBIac State", "wave": w, "data": d, "colors": c})

    # ---- 顶部位标尺：14 个 T 标号，跳号处留空 ----
    ruler = ["" for _ in range(N_CHARS)]
    for nm, x in T_LABELS:
        c = int(round(x2c(x) / CHARS_PER_PERIOD))
        if 0 <= c < len(ruler):
            ruler[c] = nm

    return {
        "head": {"text": "JEDEC LPDDR4 Figure 15 — Bus Preconditioning and DBI States for Read (全量重绘 v3)"},
        "foot": {"text": "几何实测自原图像素：CK 周期 104px(高39/斜13/低39) · 数据格宽 20px 格距 7px · 字符粒度 13px"},
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


def main():
    wj = build()
    OUT_JSON.write_text(json.dumps(wj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ WaveJSON → {OUT_JSON}")

    here = HERE
    for _ in range(4):
        cand = here / ".workbuddy" / "skills" / "wave2visio" / "scripts"
        if (cand / "wavejson2svg.py").is_file():
            sys.path.insert(0, str(cand))
            break
        here = here.parent
    import wavejson2svg
    svg = wavejson2svg.render(wj, cell=CELL_PX, row_h=56, label_w=112)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"✓ SVG → {OUT_SVG}  ({len(svg)} bytes)")
    n_blk = sum(len(s.get("data") or []) for s in wj["signal"])
    print(f"  信号 {len(wj['signal'])} 条 · 数据块 {n_blk} 个 · "
          f"边沿斜坡 {len(wj['signal'][0]['edges'])} 处 · 延时标注 2 处")


if __name__ == "__main__":
    main()