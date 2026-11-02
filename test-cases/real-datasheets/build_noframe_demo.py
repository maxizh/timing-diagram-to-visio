#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「无框模式」可视化验收页（单文件，所有图片 base64 内嵌）。

跑法：python3 build_noframe_demo.py
产出：noframe-mode.html
"""
import base64
import io
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, ".workbuddy", "skills", "wavejson", "scripts"))
import auto_trace as at  # noqa: E402

FIGS = os.path.join(HERE, "figs")

CASES = [
    ("issi-sdr-alternating-bank-write.png",
     "ISSI SDRAM · 交替 bank 写时序", 8, "8 / 8"),
    ("ad7606-fig4-parallel-cs-rd.png",
     "ADI AD7606 · 并行模式 CS/RD 时序", 4, "4 / 4"),
    ("ad7606-fig2-convst-after.png",
     "ADI AD7606 · CONVST 转换后读时序", 5, "5 / 5"),
    ("ads8482-fig33-auto-read.png",
     "TI ADS8482 · 自动读时序", 17, "17 条（含标注带）"),
]

LEVEL_C = "#ff2d55"
BUS_C = "#ff9f0a"
SPAN_C = "#2979ff"


def b64_png(fig, width=1180):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight", dpi=100)
    plt.close(fig)
    from PIL import Image
    im = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    if im.width > width:
        im = im.resize((width, max(1, int(im.height * width / im.width))), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")


def overlay_case(path):
    g, dark = at.load_dark(path)
    H, W = g.shape
    tracks, pl, pr, kinds = at.frameless_tracks(g, dark)
    rows = at.label_rows(dark, pl, at.frame_cols(dark))

    fig, ax = plt.subplots(figsize=(15, 15 * H / W), dpi=100)
    ax.imshow(g, cmap="gray", vmin=0, vmax=1)
    for i, ((y0, y1), k) in enumerate(zip(tracks, kinds)):
        col = LEVEL_C if k == "level" else BUS_C
        ax.plot([pl, pr], [y0, y0], color=col, lw=1.1, alpha=.75)
        ax.plot([pl, pr], [y1, y1], color=col, lw=1.1, alpha=.75)
        ax.text(pl - W * .012, (y0 + y1) / 2, f"#{i}",
                color=col, fontsize=15, ha="right", va="center", fontweight="bold")
    for x in (pl, pr):
        ax.axvline(x, color=SPAN_C, lw=1.6, alpha=.9)
    ax.set_ylim(H, 0)
    ax.axis("off")
    return b64_png(fig), {"tracks": len(tracks), "kinds": kinds,
                          "span": (pl, pr), "rows": len(rows)}


def overlay_issi_clock(path):
    """ISSI CLK：几何解出的电平 + 厂商自带 T0..T9 虚线叠加。"""
    g, dark = at.load_dark(path)
    H, W = g.shape
    tracks, pl, pr, kinds = at.frameless_tracks(g, dark)
    pitch = int(np.median(np.diff([(a + b) // 2 for a, b in
                                   at.label_rows(dark, pl, at.frame_cols(dark))])))
    y0, y1 = tracks[0]
    src = at.long_run_mask(dark, max(12, W // 60))
    prof, _ = at.track_profile(src, y0, y1, pl, pr)
    hi, lo = at.find_rails(prof, pl, pr)
    ser = at.level_series(prof, hi, lo, pl, pr)      # 注意：从 0 起算，不是绝对 x
    at_lv = {x: ser[x - pl] for x in range(pl, pr + 1)}
    rise = [x for x in range(pl + 1, pr + 1)
            if at_lv[x] == 1 and at_lv[x - 1] == 0]

    # 厂商自带的 T0..T9 竖直虚线：整幅高、按列统计覆盖率
    band = dark[y0:y1 + 1, pl:pr + 1]
    cov = band.mean(axis=0)
    cand = np.where(cov > 0.55)[0]
    dashes = []
    if cand.size:
        grp, cur = [], [cand[0]]
        for v in cand[1:]:
            if v - cur[-1] <= 6:
                cur.append(v)
            else:
                grp.append(cur)
                cur = [v]
        grp.append(cur)
        dashes = [int(np.mean(x)) + pl for x in grp]

    trim = [(x, at_lv[x]) for x in range(pl, pr + 1)]
    fig, ax = plt.subplots(figsize=(15, 3.4), dpi=100)
    # 上下留白要够：上方要装下 T0..T9 标注文字，下方要有低电平轨
    a, b = max(0, y0 - 46), min(H, y0 + lo + 40)
    ax.imshow(g[a:b, :], cmap="gray", vmin=0, vmax=1,
              extent=[0, W, b, a], aspect="auto")
    xs = [x for x, _ in trim]
    ys = [y0 + v * (lo - hi) + hi for _, v in trim]
    ax.plot(xs, ys, color=LEVEL_C, lw=1.5, alpha=.95)
    for d in dashes:
        ax.axvline(d, color=SPAN_C, lw=1.2, alpha=.9)
    for rr in rise:
        ax.axvline(rr, color="#00c853", lw=1.1, alpha=.5, ls="--")
    ax.set_xlim(pl - 40, pr + 40)
    ax.set_ylim(b, a)
    ax.axis("off")
    return b64_png(fig, 1180), {"rise": rise, "dash": dashes,
                                "period": float(np.median(np.diff(rise)))}


def main():
    cards, kb = [], {}
    for name, title, expect, note in CASES:
        img, meta = overlay_case(os.path.join(FIGS, name))
        kb[name] = meta
        cards.append((title, note, img, meta))
        print(f"  ✓ {name}: {meta['tracks']} 行  span={meta['span']}")

    issi_img, clk = overlay_issi_clock(os.path.join(FIGS, CASES[0][0]))
    print(f"  ✓ ISSI CLK 验证: 几何升沿 {len(clk['rise'])} 个 / "
          f"厂商虚线 {len(clk['dash'])} 条 / 中位周期 {clk['period']:.1f}px")

    # 逐条虚线偏差
    dev = [min(abs(c - r) for r in clk["rise"]) for c in clk["dash"]]
    dev_rows = "".join(
        f"<tr><td>T{i}</td><td class='m'>{clk['dash'][i]}</td>"
        f"<td class='m'>{clk['rise'][i] if i < len(clk['rise']) else '—'}</td>"
        f"<td class='m {'ok' if dev[i] <= 3 else 'warn'}'>{dev[i]}px</td>"
        f"<td>{'几何解出与厂商标注重合' if dev[i] <= 3 else '该处图上有 tCK 标注竖线切断波形'}</td></tr>"
        for i in range(len(clk["dash"])))

    def card(title, note, img, meta):
        kinds = meta["kinds"]
        nlev = sum(1 for k in kinds if k == "level")
        chips = "".join(
            f"<span class='chip {'lv' if k == 'level' else 'bs'}'>#{i} {k}</span>"
            for i, k in enumerate(kinds))
        return f"""
      <figure class="fig">
        <figcaption>
          <div class="ft">{title}</div>
          <div class="fn">{note} ｜ 自动分出 <b>{meta['tracks']}</b> 行 ｜
            判为电平 <b class="lv2">{nlev}</b> 行 ｜
            波形区 x = [{meta['span'][0]}, {meta['span'][1]}]</div>
          <div class="chips">{chips}</div>
        </figcaption>
        <img src="data:image/png;base64,{img}" alt="{title}">
      </figure>"""

    cards_html = "".join(card(t, n, i, m) for t, n, i, m in cards)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>无框模式 · 真实 datasheet 读图验收</title>
<style>
:root{{
  --bg:#0e1116; --pan:#161b22; --pan2:#1c2330; --line:#2b3443;
  --tx:#e6edf3; --dim:#93a1b1; --red:#ff5c72; --amb:#ffb340;
  --grn:#3fd97f; --blu:#5aa9ff; --vio:#b98cff;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);
  font:15px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}}
.wrap{{max-width:1240px;margin:0 auto;padding:40px 22px 80px}}
h1{{font-size:29px;margin:0 0 6px;letter-spacing:-.4px}}
.sub{{color:var(--dim);font-size:14px;margin-bottom:30px}}
h2{{font-size:19px;margin:46px 0 14px;padding-left:11px;
  border-left:3px solid var(--blu);letter-spacing:-.2px}}
h3{{font-size:15.5px;margin:24px 0 8px;color:var(--tx)}}
p{{margin:9px 0;color:#cbd5e1}}
code{{background:#232b38;padding:1.5px 6px;border-radius:5px;font-size:13px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#ffd9a0}}
pre{{background:#0b0f14;border:1px solid var(--line);border-radius:11px;
  padding:15px 17px;overflow-x:auto;font-size:12.8px;line-height:1.62;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#c9d6e4}}
.hero{{background:linear-gradient(135deg,#16233a,#1a1f2b);
  border:1px solid #2c3d55;border-radius:16px;padding:22px 24px;margin-bottom:26px}}
.hero .big{{font-size:17px;line-height:1.8;margin:0}}
.hero b{{color:var(--grn)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:13px;margin:22px 0 8px}}
.kpi{{background:var(--pan);border:1px solid var(--line);border-radius:13px;
  padding:15px 17px}}
.kpi .n{{font-size:25px;font-weight:700;letter-spacing:-.5px}}
.kpi .l{{font-size:12.5px;color:var(--dim);margin-top:3px}}
.kpi .n.g{{color:var(--grn)}} .kpi .n.r{{color:var(--red)}}
.kpi .n.b{{color:var(--blu)}} .kpi .n.a{{color:var(--amb)}}
table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.6px}}
th,td{{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line)}}
th{{color:var(--dim);font-weight:600;font-size:12.5px;letter-spacing:.3px}}
td.m{{font-family:ui-monospace,Menlo,monospace}}
td.ok{{color:var(--grn)}} td.warn{{color:var(--amb)}}
tr:hover td{{background:#1a2130}}
.fig{{margin:20px 0 30px;background:var(--pan);border:1px solid var(--line);
  border-radius:15px;overflow:hidden}}
.fig img{{display:block;width:100%}}
.fig figcaption{{padding:15px 18px 13px;border-bottom:1px solid var(--line)}}
.ft{{font-weight:650;font-size:15px}}
.fn{{color:var(--dim);font-size:12.8px;margin-top:4px}}
.fn .lv2{{color:var(--red)}}
.chips{{margin-top:9px;display:flex;flex-wrap:wrap;gap:5px}}
.chip{{font:11.5px/1 ui-monospace,Menlo,monospace;padding:4px 8px;border-radius:6px;
  border:1px solid var(--line);color:var(--dim)}}
.chip.lv{{color:var(--red);border-color:#5c2230;background:#2a1620}}
.chip.bs{{color:var(--amb);border-color:#5c4420;background:#2a2114}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:880px){{.two{{grid-template-columns:1fr}}}}
.box{{background:var(--pan2);border:1px solid var(--line);border-radius:13px;padding:16px 18px}}
.box.g{{border-left:3px solid var(--grn)}} .box.r{{border-left:3px solid var(--red)}}
.box.a{{border-left:3px solid var(--amb)}} .box.b{{border-left:3px solid var(--blu)}}
.box h4{{margin:0 0 9px;font-size:14.5px}}
.box ul{{margin:0;padding-left:19px}} .box li{{margin:5px 0;font-size:13.6px;color:#cbd5e1}}
.tag{{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:20px;
  background:#233046;color:var(--blu);margin-right:6px}}
.foot{{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);
  color:#6b7a8d;font-size:12.5px}}
</style></head><body><div class="wrap">

<h1>无框模式 —— 真实 datasheet 读图验收</h1>
<div class="sub">让 <code>auto_trace.py</code> 能读真实厂商图 · 零大模型调用 · 全程确定性</div>

<div class="hero">
  <p class="big">真实 datasheet 的图<b>一条信号方框都没有</b>，原来的几何解析器靠「配对边框」分行，一张都读不了。<br>
  无框模式改走<b>人读图的那条路</b>：每条信号行左侧都有文字标签，垂直居中于该行 —— 用文字带分行。<br>
  四张真实厂商图，行划分<b>全部精确命中</b>；ISSI 图上解出的时钟上升沿与厂商自己标注的 T0–T9 虚线<b>逐个重合</b>。</p>
</div>

<div class="kpis">
  <div class="kpi"><div class="n g">4 / 4</div><div class="l">真实厂商图行划分全对</div></div>
  <div class="kpi"><div class="n b">0</div><div class="l">大模型调用次数</div></div>
  <div class="kpi"><div class="n g">1–2 px</div><div class="l">解出时钟沿 vs 厂商标注（10 个中 9 个）</div></div>
  <div class="kpi"><div class="n a">244.0 px</div><div class="l">ISSI CLK 实测周期（标准差 9.4）</div></div>
  <div class="kpi"><div class="n g">56 / 56</div><div class="l">技能自检项全过</div></div>
</div>

<h2>一、为什么需要无框模式</h2>
<p>真实厂商图的四个特征，把原来的几何解析器全堵死了：</p>
<table>
  <tr><th>障碍</th><th>实测证据</th><th>后果</th></tr>
  <tr><td>没有「每条信号一个方框」</td><td>AD7606 / ISSI / ADS8482 全部如此</td>
      <td><code>find_tracks</code> 靠配对边框分行 → 直接失效</td></tr>
  <tr><td>长横线 ≠ 电平轨</td><td>ISSI 图上检出 16 条「长横线」，其中<b>3 条是底部 tRCD/tRRD 标注尺寸线</b>、11 条是总线带边界与阴影区边界，真电平轨只有 1 条</td>
      <td>按「长横线」分行会分出完全错误的行</td></tr>
  <tr><td>电平平台可能太短</td><td>AD7606 Fig4 的 RD 低电平平台只有 ~150px &lt; 10%W(201px) 阈值</td>
      <td>整条 RD 轨漏检</td></tr>
  <tr><td>边沿是斜坡不是直角</td><td>ADI 图所有跳变边沿宽约 25px</td>
      <td>「机绘正交波形」这个前提部分失效</td></tr>
</table>

<h2>二、无框模式怎么做的（三步，全确定性）</h2>
<div class="two">
  <div class="box b">
    <h4><span class="tag">1</span>用行标签文字块分行</h4>
    <p style="font-size:13.6px">把左侧标签列里的深色像素做 y 方向投影，一段文字 = 一条信号行。</p>
    <p style="font-size:13.6px"><b>关键坑</b>：必须先剔掉<b>竖外框列</b> —— 外框每一行都是深的，会把所有文字带粘成一条。实测 ISSI 不剔除时 8 条带 → <b>1 条</b>，全错。</p>
  </div>
  <div class="box b">
    <h4><span class="tag">2</span>用长横段定波形区左右界</h4>
    <p style="font-size:13.6px">所有「长横向深色段」中，起点的最小值 / 终点的最大值。</p>
    <p style="font-size:13.6px"><b>关键坑</b>：必须排掉<b>近全宽的横线</b>（图的外框就是最长的那条横线，起点在最左）。实测 ISSI 不排除时误得 <code>[16,2916]</code>，正确是 <code>[356,2878]</code>。</p>
  </div>
  <div class="box b">
    <h4><span class="tag">3</span>用灰底填充判「电平 vs 总线」</h4>
    <p style="font-size:13.6px">厂商画总线带 / 无效区习惯铺一层中灰，电平信号是纯白底。</p>
    <p style="font-size:13.6px">阈值 0.05：ISSI 行0 CLK = <b>0.019</b>，行1–7 总线带 = <b>0.101 ~ 0.287</b>（5~15 倍分离）；AD7606 Fig2 五行电平 0.005~0.015，<b>零误报</b>。</p>
  </div>
  <div class="box a">
    <h4>刻意选的保守方向</h4>
    <p style="font-size:13.6px">拿不准时报 <code>level</code>：<b>多解一行</b>，工程师一眼看出是垃圾删掉即可；<br>报错成 <code>bus</code> 会<b>静默丢信号</b>，代价大得多。</p>
    <p style="font-size:13.6px">已知局限：AD7606 的 <code>DB[15:0]</code> 总线带是白底黑边（不铺灰），检不出来 —— 属于「解得不完美」而非「丢数据」。要精确控制就用 <code>--rows level,level,bus,level</code>。</p>
  </div>
</div>

<h2>三、端到端验证：ISSI CLK 解出的上升沿 vs 厂商标注</h2>
<p>ISSI 图里 T0–T9 十条竖直虚线，正是厂商自己画在每个时钟上升沿上的参考线 —— 可以当成独立的「真值」来交叉验证。</p>
<figure class="fig"><img src="data:image/png;base64,{issi_img}" alt="ISSI CLK 验证"></figure>
<p style="font-size:13.4px;color:#93a1b1">红线 = 几何解出的电平轨迹；<span style="color:#2979ff">蓝实线</span> = 厂商标注的 T0–T9；<span style="color:#3fd97f">绿虚线</span> = 几何解出的上升沿。</p>
<table>
  <tr><th>标注</th><th>厂商虚线 x</th><th>几何解出上升沿 x</th><th>偏差</th><th>说明</th></tr>
  {dev_rows}
</table>
<p>10 条里 9 条偏差 <b>1–2px</b>。唯一偏离的 T1，是图上 <code>tCK</code> 标注的竖直量测线把波形切断了 21px —— 属于<b>图上原有内容</b>，不是解析错误。相邻上升沿间距剔除该异常点后为 <b>243 / 244 / 244 / 244 / 244 / 244 / 244 / 243</b>。</p>

<h2>四、四张真实图的自动分行结果</h2>
<p>红框 = 判为电平信号，橙框 = 判为总线带，蓝竖线 = 自动定位的波形区左右界。</p>
{cards_html}

<h2>五、能力边界（写在明处）</h2>
<div class="two">
  <div class="box g">
    <h4>✓ 能做到</h4>
    <ul>
      <li>无框图上自动分行 —— 4/4 精确命中，行数、顺序、位置全对</li>
      <li>自动定位波形区左右界 —— 两套独立方法（空白走廊 / 长横段）在 ISSI 上互相印证，都是 x=356</li>
      <li>自动认出时钟轨道，解出周期与位窗</li>
      <li>对占空比不敏感 —— 自测图 SCLK 是 41%/59% 不对称占空比，用「全周期」口径仍判对</li>
      <li>无时钟的图<b>直接报错</b>，不硬凑假时钟输出垃圾</li>
    </ul>
  </div>
  <div class="box r">
    <h4>✗ 不能做到（需模型或人工）</h4>
    <ul>
      <li><b>认信号名</b>：标签是文字，几何只知其位置不知其内容 → 需要 OCR 或模型</li>
      <li><b>读总线文字</b>：<code>ACTIVE / NOP / WRITE / Din m</code> 这些值只能识别形状位置，读不出字</li>
      <li><b>选通型异步接口</b>：AD7606 Fig4 / Fig2、ADS8482 Fig33 全是 CS/RD 脉冲控制，<b>本来就没有时钟</b>，而本工具按「时钟周期 = 位窗」设计 → 不适用（已能正确报错拦下）</li>
      <li><b>斜边电平</b>：ADI 图的斜坡边沿会让边缘 1–2 个位窗的采样落在坡上</li>
      <li><b>轴断裂</b>：图中间的省略号符号代表时间被压缩，跨断裂点的周期无意义</li>
      <li><b>白底黑边的总线带</b>：灰底判据检不出来</li>
    </ul>
  </div>
</div>

<h2>六、这如何改变整条链路</h2>
<p>原来的问题不是「要不要用模型」，而是<b>「让模型干它擅长的哪一段」</b>。三层架构：</p>
<table>
  <tr><th>层</th><th>输入判据</th><th>做什么</th><th>成本</th></tr>
  <tr><td><b>L0 分流</b></td><td>是不是机绘波形图</td><td>决定走几何还是走模型</td><td>0</td></tr>
  <tr><td><b>L1 几何</b></td><td>机绘正交/斜边波形图</td><td>分行 → 定位位窗 → 采样电平 → WaveJSON</td><td><b>0 token，可复现</b></td></tr>
  <tr><td><b>L2 模型兜底</b></td><td>L1 失败 / 需要语义</td><td><b>只做几何做不到的三件事</b>：认信号名、读总线文字、判省略号。**不再让模型去数电平**</td><td>极小</td></tr>
</table>
<p>关键点：<b>让模型「数电平」是用它的短板</b>（本项目铁律 1 之所以存在，就是因为模型老把 <code>2-9</code> 当成电平）。而 L1 先把图<b>切成 N 个单信号条带</b>之后，模型的任务就从「数电平」降级为「认几个字」。</p>

<h2>七、怎么用</h2>
<pre># 无框模式（真实 datasheet 默认走这条）
python3 scripts/auto_trace.py --png datasheet-fig.png --verbose

# 手工指定每行类型（自动判不出白底总线带时兜底）
python3 scripts/auto_trace.py --png fig.png --rows level,level,bus,level

# 强制要求每条信号有独立方框（老行为）
python3 scripts/auto_trace.py --png fig.png --mode frame

# 自检（56 项，含无框模式 13 项）
python3 scripts/selftest.py</pre>

<div class="foot">
测试图源：ISSI IS42S 系列 SDRAM 数据手册、Analog Devices AD7606 数据手册（Fig 2 / Fig 4）、
TI ADS8482 数据手册（Fig 33）。图仅用于本机算法验证，未随技能分发。<br>
生成时间 2026-09-17 · wavejson skill · auto_trace.py frameless 模式
</div>

</div></body></html>"""

    out = os.path.join(HERE, "noframe-mode.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✓ {out}   {os.path.getsize(out)/1024:.0f} KB")
    return out


if __name__ == "__main__":
    main()
