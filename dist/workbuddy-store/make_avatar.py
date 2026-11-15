#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 WorkBuddy 技能商店头像（512x512 PNG，≤500KB）。

设计意图：头像就是技能实际产物的缩影 —— 白底图纸 + 直角方波 + 落在位边界的
时钟对齐虚线。市场里头像常缩到 64px，所以只用高对比大色块，不放任何文字。

用法：python3 dist/workbuddy-store/make_avatar.py
依赖：Pillow（仅发布辅助工具需要；技能包内的脚本全部是纯标准库）。
"""
import pathlib

from PIL import Image, ImageDraw

S = 512
OUT = pathlib.Path(__file__).with_name("wave2visio-avatar.png")

img = Image.new("RGB", (S, S))
d = ImageDraw.Draw(img)

# 背景：深蓝渐变
for y in range(S):
    t = y / (S - 1)
    d.line([(0, y), (S, y)],
           fill=(int(14 + 12 * t), int(32 + 31 * t), int(58 + 46 * t)))

# 白色图纸卡片
d.rounded_rectangle((48, 88, 464, 424), radius=32, fill=(248, 251, 255))

X0, X1 = 112, 424
ROWS = [(172, (13, 148, 148)),    # CLK  青
        (256, (232, 135, 58)),    # CS   橙
        (340, (26, 54, 93))]      # DATA 深蓝

# 位边界虚线：必须画在波形之前，且落在每个数据位边界（技能铁律之一）
for k in range(1, 8):
    x = int(round(X0 + (X1 - X0) * k / 8))
    for yy in range(136, 380, 16):
        d.line([(x, yy), (x, min(yy + 8, 380))], fill=(220, 229, 239), width=2)


def square(yc, color, levels, width=9, half=26):
    """画一条直角方波；levels 是逐位电平（1 高 / 0 低）。"""
    hi, lo = yc - half, yc + half
    step = (X1 - X0) / len(levels)
    prev = None
    for i, lv in enumerate(levels):
        xa = int(round(X0 + i * step))
        xb = int(round(X0 + (i + 1) * step))
        y = hi if lv else lo
        d.line([(xa, y), (xb, y)], fill=color, width=width)
        if prev is not None and prev != y:
            d.line([(xa, prev), (xa, y)], fill=color, width=width)
            r = width // 2
            d.ellipse((xa - r, prev - r, xa + r, prev + r), fill=color)
            d.ellipse((xa - r, y - r, xa + r, y + r), fill=color)
        prev = y
    # 首尾圆帽，消掉 butt cap 留下的缺口
    r = width // 2
    for xx, lv in ((X0, levels[0]), (X1, levels[-1])):
        yy = hi if lv else lo
        d.ellipse((xx - r, yy - r, xx + r, yy + r), fill=color)


square(*ROWS[0], [1, 0, 1, 0, 1, 0, 1, 0])       # 时钟
square(*ROWS[1], [1, 0, 0, 0, 0, 0, 0, 1])       # 片选
square(*ROWS[2], [0, 1, 1, 0, 1, 0, 0, 1])       # 数据 0x5A 风格

# 左侧信号标识圆点
for yc, col in ROWS:
    d.ellipse((76, yc - 8, 92, yc + 8), fill=col)

# 底部品牌 accent
d.rounded_rectangle((112, 396, 300, 404), radius=4, fill=(13, 148, 148))
d.rounded_rectangle((308, 396, 356, 404), radius=4, fill=(198, 216, 230))

img.save(OUT, "PNG", optimize=True)
print(f"{OUT}  {img.size[0]}x{img.size[1]}  {OUT.stat().st_size} bytes")
