#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_trace.py — 纯几何「读图」：从时序图 PNG 直接反解电平序列，**零大模型调用**。

⚠️ 实验性模块（EXPERIMENTAL）。用来证明一件事：
   对「机绘波形图」（datasheet / EDA 导出 / matplotlib 画的那种），不需要视觉大模型
   —— 几何解析更准、更快、可复现。

和现有链路的关系：
   现有：  图片 --[视觉大模型]--> WaveJSON --> wavejson2svg.py --> SVG
   本模块：图片 --[几何解析]----> WaveJSON --> wavejson2svg.py --> SVG
   ↑ 只替换第一步，后面完全复用。

两种分行模式（--mode）：

   frame      每条信号有独立方框时，靠「配对横边框」分行（自测图是这种）
   frameless  真实 datasheet 一条方框都没有 —— 靠左侧「行标签文字块」分行
              （人读图就是这么读的）。实测 ISSI 8/8、AD7606 Fig4 4/4、Fig2 5/5 全对
   auto       先试 frameless，失败退回 frame（默认）

原理（四步，全是确定性算法）：
   1. 分行      ：frameless = 文字带；frame = 配对横边框
   2. 认时钟    ：「跳变次数多 + 全周期等距」的轨道 = 时钟（可 --clock 手动指定）
   3. 定位窗     ：时钟的相邻上升沿之间 = 1 个 bit 窗
   4. 采电平     ：每条轨道在每个位窗的 25% / 75% 处各取一次电平 → 正好 2 字符/bit
                  采样用「窗口内中位数」而不是单点，规避原图自带的细毛刺

用法：
   python3 scripts/auto_trace.py --png assets/test-input-spi.png            # 打印结果
   python3 scripts/auto_trace.py --png datasheet.png -v                     # 无框模式，看分行
   python3 scripts/auto_trace.py --png x.png --rows level,level,bus,level   # 手工指定行类型
   python3 scripts/auto_trace.py --png x.png --out x.json --svg x.svg       # 落盘
   python3 scripts/auto_trace.py --png x.png --clock 1 --verbose            # 手动指定时钟轨道
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

DARK = 0.45          # 灰度阈值
SPINE_ROW = 0.75     # 整行深色比例 > 此值 → 横边框
SPINE_COL = 0.75     # 整列深色比例 > 此值 → 竖边框
RAIL_TOL = 0.45      # 判定「贴近某条电平轨」的容差（占轨道高度的比例）
MIN_RUN = 4          # 去毛刺：短于此长度的电平段被并掉

# —— 无框模式参数 ——
FRAME_COL = 0.80     # 整列深色比例 > 此值 → 竖外框（做行标签投影时必须剔除）
FRAME_RUN = 0.90     # 横段长 > 此值×图宽 → 外框线（算波形区时必须剔除）
LABEL_GAP = 14       # 行标签文字带之间的最小空白行数（> 此值即断行）
LABEL_MIN_H = 10     # 文字带最小高度
# ⚠️ **无框 / 有框必须用不同的值**（2026-10-22 实测踩出来的）：
#   无框模式：行边界靠左侧文字标签的 y 投影猜，猜不准就会把**相邻的文字**
#     （图标题、标注说明）圈进轨道 → 文字笔画的等间距被当成周期时钟。
#     实测 7 张真实厂商图：ROW_HALF_NOFRAME=0.25 时「三张 ISSI 全过 + 四张无时钟图全拒收」；
#     0.42 时 AD7606 Fig4 与 ADS8482 Fig33 被误放行（假时钟 / 行带重叠）。
#   有框模式：边界由方框线给出，本来就准；收窄反而会切掉框内波形 ——
#     实测 0.25 时基准 SPI 图（test-input-spi.png，有框）在 frame 模式下读不出时钟。
ROW_HALF_NOFRAME = 0.25   # 无框模式行带半高 = 行距 × 此值（7 图实测唯一全对窗口）
ROW_HALF_FRAME = 0.42     # 有框模式行带半高（有框边界本就准，不宜收窄）
ROW_HALF = ROW_HALF_NOFRAME   # 兼容旧引用
BUS_FILL = 0.05      # 行带内灰底填充率 >= 此值 → 判为总线带

# —— 时钟硬门槛（防「无时钟的图被硬凑出假时钟」）——
MIN_CLOCK_EDGES = 6  # 时钟至少要 6 次跳变
MIN_CLOCK_REG = 0.60 # 且等距比例 >= 0.60
MIN_BIT_WINDOWS = 3  # 等距过滤后至少要 3 个位窗（= 3 个时钟上升沿）


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def _group(vals, gap):
    """把一列整数按间隔 > gap 切成若干组。"""
    out, cur = [], []
    for v in vals:
        if cur and v - cur[-1] > gap:
            out.append(cur)
            cur = []
        cur.append(v)
    if cur:
        out.append(cur)
    return out


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def load_dark(png_path):
    """读图 → (灰度 float 数组 **0-1**, 深色布尔掩码)。

    ⚠️ **灰度必须归一化到 0-1**（2026-10-22 修，JPEG 输入必崩的根因）。

    背景：`DARK` 等全部判据常数都是 0-1 尺度的（如 DARK=0.45 判「深色」）。
    但 `matplotlib.image.imread` 的返回**取决于文件格式**：
      - 8-bit PNG  → float64，值域已是 0.0~1.0
      - JPEG      → float64，值域是 **0.0~255.0**
    原代码直接 `gray < DARK`，于是 JPEG 的深色判定只剩「值恰为 0」的像素成立，
    整幅图几乎全被判成白色 → 深色占比掉到 0.2% → wave_span 退回 [0, W-1]
    → 标签列范围 x<0 为空 → 报「只找到 0 个行标签」。
    **PNG 输入恰好躲过这个 bug，所以自检一直是绿的**，直到拿真实 JPEG 截图试。

    修法：在读进来的当场按实际值域归一化，让 DARK 的语义（0-1）在所有格式下统一。
    判据常数一律不动 —— `pdf_trace.DARK ≡ auto_trace.DARK` 是跨模块硬约定。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    im = mpimg.imread(png_path)
    if im.ndim == 3:
        gray = im[..., :3].mean(axis=2)
    else:
        gray = im.astype(float)          # 已经是单通道灰度
    # 值域归一化：>1.0 说明是 0-255 整数尺度（matplotlib 对 JPEG/BMP 就是这样）
    mx = float(gray.max())
    if mx > 1.0:
        gray = gray / 255.0
    return gray, gray < DARK


# --------------------------------------------------------------------------
# 第 1 步：找轨道
# --------------------------------------------------------------------------
def find_tracks(dark):
    H, W = dark.shape
    rowf = dark.mean(axis=1)
    spine_rows = [y for y in range(H) if rowf[y] > SPINE_ROW]
    groups = _group(spine_rows, 4)
    if len(groups) < 4:
        raise SystemExit(
            f"只找到 {len(groups)} 条横边框，不足以分出轨道。\n"
            "本模块目前只支持「每条信号有独立方框」的机绘图；\n"
            "没有方框的图请先手工加框，或改用大模型那条路。")

    # 相邻两条边框组成一条轨道
    tracks = [(groups[i][0], groups[i + 1][-1]) for i in range(0, len(groups) - 1, 2)]

    # 绘图区左右边界：在整条轨道堆叠范围内看列深色比例
    top, bot = tracks[0][0], tracks[-1][1]
    cf = dark[top:bot + 1, :].mean(axis=0)
    cols = [x for x in range(W) if cf[x] > SPINE_COL]
    cg = _group(cols, 4)
    if len(cg) < 2:
        raise SystemExit("找不到绘图区左右边框")
    # ⚠️ 必须取边框**内侧**：整幅高的竖边框会被「最上方深色像素」法误判成
    #    电平跳变（实测：原图右边框 x=1614..1619，会被当成第 9 个时钟上升沿）
    return tracks, cg[0][-1] + 1, cg[-1][0] - 1


# --------------------------------------------------------------------------
# 第 1 步（无框版）：真实 datasheet 大多没有「每条信号一个方框」
# --------------------------------------------------------------------------
# 为什么另起一套：真实厂商图（TI / ADI / ISSI）的特征是
#   ① 一条信号一个方框的**没有** —— find_tracks 靠配对边框，直接失效；
#   ② 总线带（梯形/菱形 + 文字）贡献大量长横线，被误当电平轨；
#   ③ 图底部还有一堆 tRCD/tRRAS 标注尺寸线，也是长横线；
#   ④ 有的信号（如 RD 的低电平平台）横段太短，够不到 10%W 阈值。
# 实测（AD7606 Fig4）：16 条「长横线」里只有 3 条是真电平轨。
#
# 所以无框模式改走**人读图的那条路**：每条信号行左侧都有一个文字标签，
# 垂直居中于该行 —— 用文字带分行。
#   实测命中：ISSI 8带→8行 / AD7606 Fig4 4带→4行 / AD7606 Fig2 5带→5行，全对。
def frame_cols(dark):
    """整列深色比例 > FRAME_COL 的列 → 竖外框。

    ⚠️ 做行标签投影前**必须**剔掉这些列。外框每一行都是深的，会把所有
       文字带粘成一条（实测：ISSI 不剔除时 8 带 → 1 带，全错）。
    """
    import numpy as np
    f = dark.mean(axis=0)
    return set(int(x) for x in np.where(f > FRAME_COL)[0])


def wave_span(dark, min_frac=0.10, frame_frac=FRAME_RUN):
    """波形区左右边界 x = [最左长横段起点, 最右长横段终点]。

    ⚠️ 必须排除「近全宽的横线」= 图的外框：它就是最长的那条横线，起点在最左，
       不排除的话波形区会被算成整幅图（实测 ISSI 误得 x=[16,2916]，正确是 [356,2878]）。
       取 1/99 分位而非极值，抗单点噪声。
    """
    import numpy as np
    H, W = dark.shape
    ml, fl = int(W * min_frac), int(W * frame_frac)
    xs0, xs1 = [], []
    for y in range(H):
        row = dark[y]
        if not row.any():
            continue
        for s, e in _runs1d(row):
            if ml <= e - s < fl:
                xs0.append(int(s))
                xs1.append(int(e))
    if not xs0:
        return 0, W - 1
    return int(np.percentile(xs0, 1)), int(np.percentile(xs1, 99))


def _runs1d(vec):
    """一维 bool → [(start, end)]（半开区间，end 不含）。"""
    import numpy as np
    d = np.diff(np.concatenate(([0], vec.view(np.int8), [0])))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def _bands(mask, gap, min_h=1):
    out, cur = [], None
    for i, v in enumerate(mask):
        if not v:
            continue
        if cur is None:
            cur = [i, i]
        elif i - cur[1] <= gap:
            cur[1] = i
        else:
            out.append(tuple(cur))
            cur = [i, i]
    if cur:
        out.append(tuple(cur))
    return [(a, b) for a, b in out if b - a + 1 >= min_h]


def label_rows(dark, x_to, fcols, gap=LABEL_GAP, min_h=LABEL_MIN_H):
    """用左侧「行标签文字块」分行，返回 [(y_top, y_bot)]。

    每个信号行左侧有一个文字标签，垂直居中于该行。把标签列里的深色像素做
    y 方向投影，一段文字 = 一条信号行。
    多行标签（"DATA:\\nDB[15:0]"）靠 gap 合并成一段。
    """
    import numpy as np
    cols = [x for x in range(max(1, x_to)) if x not in fcols]
    if not cols:
        return []
    prof = dark[:, cols].sum(axis=1)
    return _bands(prof > 0, gap, min_h)


def frameless_tracks(gray, dark, fcols=None, verbose=False):
    """无框模式：返回 (tracks, plot_l, plot_r, kinds)。

    tracks = [(y_top, y_bot)] 每行一条；kinds = 每行的 ['level'|'bus']。
    """
    fcols = frame_cols(dark) if fcols is None else fcols
    plot_l, plot_r = wave_span(dark)
    rows = label_rows(dark, plot_l, fcols)
    if len(rows) < 2:
        raise SystemExit(
            f"无框模式只找到 {len(rows)} 个行标签，无法分行。\n"
            "可能是：图太小 / 标签不在左侧 / 没有文字标签。\n"
            "可试 --mode frame（要求每条信号有独立方框），或手工裁一行出来。")

    centers = [(a + b) // 2 for a, b in rows]
    pitch = int(_median([centers[i + 1] - centers[i] for i in range(len(centers) - 1)]))

    tracks, kinds = [], []
    for a, b in rows:
        yc = (a + b) // 2
        half = max(8, int(pitch * ROW_HALF_NOFRAME))
        y0 = max(0, yc - half)
        y1 = min(dark.shape[0] - 1, yc + half)
        tracks.append((y0, y1))
        kinds.append(_row_kind(gray, dark, y0, y1, plot_l, plot_r))
    if verbose:
        print(f"无框模式：波形区 x=[{plot_l},{plot_r}] 行距 {pitch}px  {len(tracks)} 行")
        for i, ((y0, y1), k) in enumerate(zip(tracks, kinds)):
            print(f"   行{i}  y=[{y0},{y1}]  {k}")
    return tracks, plot_l, plot_r, kinds


def _row_kind(gray, dark, y0, y1, plot_l, plot_r):
    """判这一行是「电平信号」还是「总线带（含 DON'T CARE 阴影）」。

    判据 = **灰底填充率**：真实 datasheet 画总线带 / 无效区时习惯铺一层中灰
    （ISSI 的梯形总线带、DON'T CARE 图例都是这么画的），而电平信号是纯白底。

    实测灰底填充率（阈值 0.05）：
        ISSI 行0 CLK（电平） = 0.019  |  行1..7（总线带）= 0.101 ~ 0.287   ← 5~15 倍分离
        AD7606 Fig2 全 5 行（都是电平）= 0.005 ~ 0.015                    ← 零误报

    刻意选这个**保守**判据，理由是失败方向：
      · 拿不准时报 'level' —— 会多解一行，工程师一眼看出是垃圾，删掉即可；
      · 报错成 'bus' 则会**静默丢信号**，代价大得多。
    已知局限：AD7606 Fig4 的 DB[15:0] 总线带是**白底黑边**（不铺灰），
    这里检不出来 —— 属于「解出来不完美」而非「丢数据」，可接受。
    要精确控制就手工指定：--rows level,level,bus,level
    """
    import numpy as np
    band_g = gray[y0:y1 + 1, plot_l:plot_r + 1]
    fill = float(((band_g > DARK) & (band_g < 0.92)).mean())
    return "bus" if fill >= BUS_FILL else "level"


def long_run_mask(dark, min_len):
    """只保留「长横向深色段」的像素 —— 也就是导线本身。

    为什么必须这一步：轨道里常常有**文字标注**（原图 CS_n 面板里就有
    "CS active (LOW)"）。文字笔画产生的横向段只有十几像素，而真实导线
    每段至少几十像素。不过滤的话，「最上方深色像素」会在文字处读到假跳变
    （实测原图 CS_n 在 x=814..925 被文字骗出 6 个假沿）。
    """
    import numpy as np
    H, W = dark.shape
    mask = np.zeros_like(dark)
    for y in range(H):
        row = dark[y]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            if e - s >= min_len:
                mask[y, s:e] = True
    return mask


def track_profile(dark, y0, y1, plot_l, plot_r):
    """每列「最上面那个深色像素的相对行号」；没有深色像素则为 None。

    信号在 HIGH 时导线靠近轨道顶部 → 行号小；LOW 时靠近底部 → 行号大。
    所以行号小 = 高电平。
    """
    inner = dark[y0 + 2:y1 - 1, :]
    span = inner.shape[0]
    prof = [None] * dark.shape[1]
    for x in range(plot_l, plot_r + 1):
        col = inner[:, x]
        idx = col.argmax()
        if col[idx]:
            prof[x] = int(idx)
    return prof, span


def find_rails(prof, x_from, x_to):
    """把每列行号做直方图，取出现最多的两个峰 = 高/低电平轨。"""
    vals = [prof[x] for x in range(x_from, x_to + 1) if prof[x] is not None]
    if not vals:
        return None, None
    hist = {}
    for v in vals:
        hist[v] = hist.get(v, 0) + 1
    peaks = sorted(hist.items(), key=lambda kv: -kv[1])
    hi = peaks[0][0]
    # 低电平轨：离 hi 足够远的次高峰
    lo = None
    for v, c in peaks[1:]:
        if abs(v - hi) > 6:
            lo = v
            break
    if lo is None:
        return hi, None
    return min(hi, lo), max(hi, lo)      # (高电平行号, 低电平行号)


# --------------------------------------------------------------------------
# 第 2 步：认时钟
# --------------------------------------------------------------------------
def level_series(prof, hi, lo, plot_l, plot_r):
    """把行号序列转成干净的 0/1 序列（None 用前后填充，再去毛刺）。"""
    h = (lo - hi) or 1
    tol = h * RAIL_TOL
    raw = []
    for x in range(plot_l, plot_r + 1):
        v = prof[x]
        if v is None:
            raw.append(None)
        elif abs(v - hi) <= tol:
            raw.append(1)
        elif abs(v - lo) <= tol:
            raw.append(0)
        else:
            raw.append(None)
    # 填充 None
    last = next((v for v in raw if v is not None), 0)
    for i, v in enumerate(raw):
        if v is None:
            raw[i] = last
        else:
            last = v
    # 去毛刺：把短于 MIN_RUN 的段并进邻居
    out = list(raw)
    i = 0
    while i < len(out):
        j = i
        while j < len(out) and out[j] == out[i]:
            j += 1
        if (j - i) < MIN_RUN and 0 < i and j < len(out):
            for k in range(i, j):
                out[k] = out[i - 1]
        i = j
    return out


def transition_positions(series):
    """返回电平翻转处的列号（相对 series 起点的偏移）。"""
    return [i for i in range(1, len(series)) if series[i] != series[i - 1]]


def pick_clock(series_list, spans):
    """时钟 = 「跳变次数多 + 跳变等距」的那条。

    ⚠️ 等距口径必须用**全周期**（相邻两段间距之和），不能用相邻跳变间距。
       为什么：真实时钟的占空比常常不是 50%。实测自测图的 SCLK 是
       高 69px / 低 98px（占空比 41%/59%）—— 用相邻间距算，中位 70 而 98 偏离
       40%，等距比只有 0.533，时钟就被误判掉了（实测会被 MOSI 抢走）。
       用全周期 69+98=167 则所有周期都等于 167，等距比 ≈ 1.0。

    score = 跳变数 × (全周期落在中位 ±25% 内的比例)

    另外设三道**硬门槛**（MIN_CLOCK_EDGES / MIN_CLOCK_REG / MIN_BIT_WINDOWS）。
    为什么必须有：真实 datasheet 里很多图根本没有时钟 —— 是 CS/RD 这类**选通脉冲**
    控制的异步接口。没有门槛时，算法会硬凑出一条「2 个沿、周期 1272px」的假时钟，
    然后输出一屏垃圾。实测：AD7606 Fig2、ADS8482 Fig33 都因此被正确拦下。
    """
    best, best_score, detail = None, -1.0, []
    for i, s in enumerate(series_list):
        pos = transition_positions(s)
        if len(pos) < MIN_CLOCK_EDGES:
            detail.append((i, len(pos), 0.0))
            continue
        gaps = [pos[k + 1] - pos[k] for k in range(len(pos) - 1)]
        pers = [gaps[k] + gaps[k + 1] for k in range(len(gaps) - 1)]
        m = _median(pers)
        reg = sum(1 for g in pers if m and abs(g - m) <= 0.25 * m) / len(pers)
        score = len(pos) * reg
        detail.append((i, len(pos), round(reg, 3)))
        if reg >= MIN_CLOCK_REG and score > best_score:
            best, best_score = i, score
    if best is None:
        raise SystemExit(
            ("没有哪条轨道像时钟（要求跳变 >= %d 次且等距比例 >= %.2f）。\n"
             % (MIN_CLOCK_EDGES, MIN_CLOCK_REG))
            + "排查方向：\n"
            "  1) 这张图可能本来就没有时钟（CS/RD 这类选通型异步接口）——"
            "本工具是按「时钟周期 = 位窗」设计的，对无时钟图不适用；\n"
            "  2) 时钟没被正确分行 —— 看看 --verbose 的行划分对不对；\n"
            "  3) 确实是时钟但被判成总线带了 —— 用 --rows 把它标成 level；\n"
            "  4) 已知道是第几条轨道，直接 --clock N 指定。\n"
            "各轨道实测（轨道序号, 跳变数, 等距比例）：\n  "
            + ("\n  ".join(str(d) for d in detail) if detail else "（无可用轨道）"))
    return best, detail


def bit_boundaries(series, offset, clock_index=None):
    """时钟的相邻上升沿 = 位边界。返回 (rises_x, period)。

    上升沿 = 序列由 0 变 1（在图像里就是电平升高）。

    再兜一道「等距一致性」过滤：取间距中位数，只保留落在 ±25% 内的连续链。
    这是为了防住「图像边缘 / 残留边框」被误当成沿 —— 真实的时钟不可能突然
    多出一个间距不一样的沿。
    """
    pos = transition_positions(series)
    rises = [p for p in pos if series[p] == 1]
    if len(rises) < 2:
        raise SystemExit(f"时钟轨道只找到 {len(rises)} 个上升沿，不够定位位窗")

    xs = [p + offset for p in rises]

    # 等距一致性过滤：保留最长的一条「间距稳定」的链
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    m = _median(gaps)
    best_a, best_b, a = 0, 0, 0
    for i, g in enumerate(gaps):
        if abs(g - m) <= 0.25 * m:
            if i - a + 1 > best_b - best_a:
                best_a, best_b = a, i + 1
        else:
            a = i + 1
    chain = xs[best_a:best_b + 1]
    if len(chain) < 2:
        raise SystemExit("时钟上升沿间距极不规律，可能不是时钟轨道（试试 --clock）")

    period = (chain[-1] - chain[0]) / (len(chain) - 1)
    return chain, period


# --------------------------------------------------------------------------
# 第 4 步：采样
# --------------------------------------------------------------------------
def level_at(series, offset, x_abs, half_win):
    """在 x_abs 附近 ±half_win 列取中位数电平（抗毛刺）。"""
    a = int(round(x_abs - offset - half_win))
    b = int(round(x_abs - offset + half_win))
    a = max(0, min(a, len(series) - 1))
    b = max(0, min(b, len(series) - 1))
    if b < a:
        a, b = b, a
    return int(_median(series[a:b + 1]))


def char_for(series, offset, x0, w):
    """一个位窗 → 2 个字符（25% 与 75% 处各采一次）。"""
    hw = max(1, int(w * 0.15))
    c1 = level_at(series, offset, x0 + 0.25 * w, hw)
    c2 = level_at(series, offset, x0 + 0.75 * w, hw)
    return f"{c1}{c2}"


def trace(png_path, clock_override=None, verbose=False, text_filter=True,
          pad_right=None, mode="auto", rows_override=None):
    """mode: 'auto' | 'frameless' | 'frame'

    auto  = 先试无框（真实 datasheet 都是无框的），失败再退回方框模式。
    rows_override = ['level','bus',...] 手工指定每行的类型，覆盖自动判定
                    （总线带靠灰底填充自动判定，白底黑边的总线带检不出来，用它兜底）
    """
    gray, dark = load_dark(png_path)
    H, W = gray.shape

    kinds, used = None, None
    # ⚠️ 必须先置 None（2026-10-22 修）：`--mode frame` 时下面 if 块根本不进，
    #    旧代码没初始化 tracks → `if tracks is None` 直接抛 UnboundLocalError。
    #    这条路径以前就是坏的，只是从来没人显式用过 --mode frame。
    tracks = None
    plot_l = plot_r = None
    if mode in ("auto", "frameless"):
        try:
            tracks, plot_l, plot_r, kinds = frameless_tracks(gray, dark, verbose=verbose)
            used = "frameless"
        except SystemExit:
            if mode == "frameless":
                raise
            tracks = None
    if tracks is None:
        tracks, plot_l, plot_r = find_tracks(dark)
        used = "frame"
        if verbose:
            print(f"方框模式：{len(tracks)} 条轨道  绘图区 x=[{plot_l},{plot_r}]")

    # 滤掉面板内的文字标注，只留导线像素
    if text_filter:
        src = long_run_mask(dark, min_len=max(12, W // 60))
    else:
        src = dark

    profs, series_all, rails_all = [], [], []
    effective_kinds = []
    for tidx, (y0, y1) in enumerate(tracks):
        k = kinds[tidx] if kinds is not None else "level"
        if rows_override and tidx < len(rows_override):
            k = rows_override[tidx]
        effective_kinds.append(k)
        # 已知是总线带的，不解电平 —— 总线带的「上边框」会被「最上方深色像素」法
        # 当成一条电平轨，解出来必然是一串错的 0/1。
        if k != "level":
            series_all.append(None)
            profs.append(None)
            rails_all.append((None, None))
            continue
        prof, span = track_profile(src, y0, y1, plot_l, plot_r)
        hi, lo = find_rails(prof, plot_l, plot_r)
        if lo is None:
            series_all.append(None)
            profs.append(prof)
            rails_all.append((hi, lo))
            continue
        profs.append(prof)
        rails_all.append((hi, lo))
        series_all.append(level_series(prof, hi, lo, plot_l, plot_r))

    valid = [(i, s) for i, s in enumerate(series_all) if s]
    if not valid:
        raise SystemExit("没有一条轨道能提取出电平")

    if clock_override is not None:
        ci = clock_override
    else:
        # ⚠️ pick_clock 的「没有哪条轨道像时钟」也是 **frameless 失败的一种**
        #    （2026-10-22 修）：auto 模式必须在这里也能回退到 frame 模式。
        #    旧代码只把 frameless_tracks() 的失败当回退条件，而 pick_clock 是在
        #    轨道定好之后才抛的 —— auto 走到这一步已经过了回退点，
        #    结果「有框图」被当成「无框图处理失败」而整体报错。
        #    实测：基准 SPI 图（有框）auto 模式直接报「没有哪条轨道像时钟」，
        #    而同样的图显式 --mode frame 完全正常（4 行 / 8 位窗 / 167.3px）。
        try:
            ci, detail = pick_clock([s for _, s in valid], None)
        except SystemExit:
            if mode == "frameless":
                raise
            if verbose:
                print("frameless 认不出时钟，回退到方框模式")
            return trace(png_path, clock_override, verbose, text_filter,
                         pad_right, "frame", rows_override)
        if verbose:
            print("时钟候选打分（轨道序号, 跳变数, 等距比例）:")
            for d in detail:
                print("   ", d)
        ci = valid[ci][0]

    cseries = series_all[ci]
    bs, period = bit_boundaries(cseries, plot_l, ci)

    # 硬门槛：等距过滤之后**仍然**凑不出 3 个位窗，说明这条"时钟"站不住脚。
    # 必须放在过滤之后 —— 原始逐列序列上的毛刺跳变不算数。
    # 实测：AD7606 Fig4 的 FRSTDATA 被初选成时钟，但过滤后只剩 2 个沿 → 在这里拦下。
    if len(bs) < MIN_BIT_WINDOWS:
        raise SystemExit(
            f"轨道 #{ci} 被初选成时钟，但等距过滤后只剩 {len(bs) - 1} 个位窗"
            f"（要求 >= {MIN_BIT_WINDOWS - 1}）。\n"
            "说明这张图没有可用的周期性时钟（或该行不是时钟）。\n"
            "   · 确认时钟是第几条轨道后，可用 --clock N 强制指定；\n"
            "   · 用 --verbose 看每条轨道的跳变数/等距比例，判断时钟是否被漏掉。")

    if verbose:
        print(f"时钟轨道 = #{ci}，上升沿 {len(bs)} 个，位宽 {period:.1f}px")
        print(f"位边界 x = {[int(v) for v in bs]}")

    # 位边界：首个上升沿 → 每个周期一条，末尾补一条
    bounds = list(bs) + [bs[-1] + period]

    # 左右空档：从绘图区边界到首个/末个上升沿，按「半位」折成字符数
    left_slots = int(round((bounds[0] - plot_l) / (period / 2)))
    raw_right = int(round((plot_r - bounds[-1]) / (period / 2)))

    # 渲染器的位标尺公式是 nb = (n-4)/2，即假设「首尾各 2 字符」。
    # 原图的真实几何是「左 2 右 0」→ 18 字符 → 标尺会少标一个（D7 丢失）。
    # 默认把右边距补到和左边距等宽（只补空闲电平，不动任何数据位），
    # 这样 n = 2 + 2*nb + 2，标尺正好 D(nb-1)…D0。要原样保留就传 pad_right=0。
    if pad_right is None:
        right_slots = max(raw_right, left_slots)
    else:
        right_slots = pad_right
    right_pad_extra = right_slots - max(raw_right, 0)

    signals = []
    for idx, (y0, y1) in enumerate(tracks):
        s = series_all[idx]
        if not s:
            continue
        wave = ""
        for k in range(left_slots):
            x = plot_l + (k + 0.5) * (period / 2)
            wave += str(level_at(s, plot_l, x, max(1, int(period * 0.10))))
        for k in range(len(bounds) - 1):
            wave += char_for(s, plot_l, bounds[k], bounds[k + 1] - bounds[k])
        for k in range(right_slots):
            if k < raw_right:
                x = bounds[-1] + (k + 0.5) * (period / 2)
            else:                                   # 补出来的边距：沿用最后一列电平
                x = plot_r
            wave += str(level_at(s, plot_l, x, max(1, int(period * 0.10))))
        signals.append({"name": f"sig{idx}", "wave": wave})

    return {
        "wj": {"signal": signals, "config": {"hscale": 1}},
        "meta": {
            "mode": used,
            "tracks": len(tracks),
            "row_kinds": effective_kinds,
            "skipped_bus": sum(1 for k in effective_kinds if k != "level"),
            "clock_track": ci,
            "clock_rises": len(bs),
            "bit_count": len(bounds) - 1,
            "period_px": round(period, 2),
            "plot_x": [plot_l, plot_r],
            "left_slots": left_slots,
            "right_slots_raw": raw_right,
            "right_slots": right_slots,
            "right_pad_extra": right_pad_extra,
            "n_chars": len(signals[0]["wave"]) if signals else 0,
        },
    }


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default=os.path.join(ROOT, "assets", "test-input-spi.png"))
    ap.add_argument("--out", help="输出 WaveJSON 到文件")
    ap.add_argument("--svg", help="顺手渲染成 SVG")
    ap.add_argument("--clock", type=int, default=None, help="手动指定时钟轨道序号")
    ap.add_argument("--names", help="逗号分隔的信号名，按轨道顺序")
    ap.add_argument("--pad-right", type=int, default=None,
                    help="右侧补几个字符的边距（默认补到与左侧等宽，保证位标尺完整；0=原样保留）")
    ap.add_argument("--no-text-filter", dest="text_filter", action="store_false",
                    help="关掉长横段过滤（面板内含文字的图会读错，别关）")
    ap.add_argument("--mode", choices=["auto", "frameless", "frame"], default="auto",
                    help="auto=先试无框再退回方框（默认）；frameless=强制无框；frame=强制要求每条信号有方框")
    ap.add_argument("--rows", help="手工指定每行类型，逗号分隔，如 level,level,bus,level"
                                   "（覆盖自动判定；总线带白底黑边时自动判不出来，用它兜底）")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    ro = [s.strip() for s in a.rows.split(",")] if a.rows else None
    res = trace(a.png, a.clock, a.verbose, a.text_filter, a.pad_right, a.mode, ro)
    wj = res["wj"]
    if a.names:
        for s, n in zip(wj["signal"], a.names.split(",")):
            s["name"] = n.strip()

    print(f"图片   {a.png}")
    for k, v in res["meta"].items():
        print(f"  {k:12s} {v}")
    print()
    for s in wj["signal"]:
        print(f"  {s['name']:8s} {s['wave']}")

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(wj, f, ensure_ascii=False, indent=2)
        print(f"\n✓ WaveJSON → {a.out}")
    if a.svg:
        import wavejson2svg
        with open(a.svg, "w", encoding="utf-8") as f:
            f.write(wavejson2svg.render(wj))
        print(f"✓ SVG → {a.svg}")


if __name__ == "__main__":
    main()
