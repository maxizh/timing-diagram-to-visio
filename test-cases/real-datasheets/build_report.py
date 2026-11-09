#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 datasheet 候选选型报告（单文件，图片全 base64 内嵌）。"""
import base64, os, re, json
import pymupdf

FIGS = [
 dict(f="ad7606-fig2-convst-after.png", part="AD7606 / AD7606-6 / AD7606-4", mfr="Analog Devices",
      pdf="dl/ad7606.pdf", pg=9, title="Figure 2 · CONVST Timing — Reading After a Conversion",
      rows="CONVST A/B · BUSY · CS̅ · RESET", nrow=4, bus=0,
      why="最接近我们现有测试图的复杂度。控制线为主，无数据总线。适合当「真实但不难」的基线。",
      risk="低"),
 dict(f="ad7606-fig4-parallel-cs-rd.png", part="AD7606 / AD7606-6 / AD7606-4", mfr="Analog Devices",
      pdf="dl/ad7606.pdf", pg=9, title="Figure 4 · Parallel Mode, Separate CS̅ and RD̅ Pulses",
      rows="CS̅ · RD̅ · DATA DB[15:0] · FRSTDATA", nrow=4, bus=1,
      why="含 16 位并行总线，数据相位用 V1…V8 标注。总线过渡是斜边梯形 —— 正是悬而未决的「总线怎么画」问题。",
      risk="中（斜边梯形画法）"),
 dict(f="ads8482-fig33-auto-read.png", part="ADS8482", mfr="Texas Instruments",
      pdf="dl/ads8482.pdf", pg=17, title="Figure 33 · Conversion & Acquisition Cycles, CS̅/RD̅ tied to BDGND — Auto Read",
      rows="CONVST · BUSY · CS̅=0 · CONVERT† · SAMPLING† · BYTE · BUS 18/16 · RD̅=0 · DB[17:12] · DB[11:10] · DB[9:0]",
      nrow=11, bus=3,
      why="行数最多（11 条），3 条数据总线分时复用，还有斜线阴影区表示状态不确定。",
      risk="高（弧线箭头 + 阴影块，渲染器目前不支持）"),
 dict(f="issi-sdr-alternating-bank-write.png", part="IS42S16400J / IS45S16400J", mfr="Integrated Silicon Solution (ISSI)",
      pdf="dl/issi_sdr.pdf", pg=54, title="ALTERNATING BANK WRITE ACCESS",
      rows="CLK · CKE · COMMAND · DQM/DQML,DQMH · A0-A9,A11 · A10 · BA0,BA1 · DQ",
      nrow=8, bus=4,
      why="本批最佳靶子：8 条信号、4 条并行总线、T0–T9 十个时钟周期、两个 bank 交错。横平竖直、带虚线格、带 DON'T CARE 图例 —— 结构上完全是我们渲染器能吃的形态。",
      risk="低-中"),
 dict(f="issi-sdr-write-page-burst.png", part="IS42S16400J / IS45S16400J", mfr="Integrated Silicon Solution (ISSI)",
      pdf="dl/issi_sdr.pdf", pg=55, title="WRITE — FULL PAGE BURST",
      rows="CLK · CKE · COMMAND · DQM/DQML,DQMH · A0-A9,A11 · A10 · BA0,BA1 · DQ",
      nrow=8, bus=4,
      why="与上一张同结构但更规整（单 bank 连续突发），适合做「同一模板的简单变体」回归。",
      risk="低-中"),
 dict(f="issi-sdr-p48.png", part="IS42S16400J / IS45S16400J", mfr="Integrated Silicon Solution (ISSI)",
      pdf="dl/issi_sdr.pdf", pg=48, title="WRITE — WITHOUT AUTO PRECHARGE",
      rows="CLK · CKE · COMMAND · DQM/DQML,DQMH · A0-A9,A11 · A10 · BA0,BA1 · DQ",
      nrow=8, bus=4,
      why="三张 SDRAM 里最短的一段，适合先拿它试水。",
      risk="低-中"),
]

def metrics_of(pdf, pg):
    """客观指标：矢量线段数 + 可提取的时序参数标注（去重）。
    注意 AD7606 那页的标注是矢量轮廓，没有文本层 —— 提取数为 0 是真实现象，不是 bug。"""
    p = pymupdf.open(pdf)[pg-1]
    segs = sum(len([i for i in d.get("items", []) if i[0] == "l"]) for d in p.get_drawings())
    ws = p.get_text("words")
    stop = {"to","the","than","then","tied","two","time","times","total","typ","typical"}
    toks = sorted({w[4] for w in ws
                   if re.fullmatch(r"t[A-Za-z0-9()]{0,8}", w[4]) and w[4].lower() not in stop})
    return segs, toks

def b64(p):
    return base64.b64encode(open(p,"rb").read()).decode()

cards = []
for i, f in enumerate(FIGS, 1):
    segs, ps = metrics_of(f["pdf"], f["pg"])
    f["segs"] = segs
    cards.append(f"""
<div class=card>
  <div class=hd>
    <div class=rank>{'首选' if f['f'].startswith('issi-sdr-alternating') else ('压力测试' if f['f'].startswith('ads8482') else f'候选 {i}')}</div>
    <div><div class=ttl>{f['title']}</div>
      <div class=meta>{f['mfr']} · {f['part']} · PDF 第 {f['pg']} 页 ·
        信号行 <b>{f['nrow']}</b> · 并行总线 <b>{f['bus']}</b> · 矢量线段 <b>{f['segs']}</b> ·
        可提取时序参数 <b>{len(ps)}</b> 个</div></div>
  </div>
  <div class=rows><b>信号：</b>{f['rows']}</div>
  <div class=params>{' '.join(f'<span class=tag>{p}</span>' for p in ps[:26]) or '<span class=nolabel>该图标注是矢量轮廓（无文本层）—— 任何基于文字提取的方法在这里都会失效，只能靠像素/几何</span>'}</div>
  <img src="data:image/png;base64,{b64('figs/'+f['f'])}">
  <div class=foot><div class=why><b>价值：</b>{f['why']}</div>
  <div class=rk><b>实现风险：</b>{f['risk']}</div>
  <div class=fname>figs/{f['f']}</div></div>
</div>""")

html = f"""<!doctype html><html lang=zh><meta charset=utf-8>
<title>真实 datasheet 时序图候选</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#fff;color:#1a1a1a;
 font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;padding:40px 28px 70px}}
h1{{font-size:25px;margin:0 0 6px;letter-spacing:-.3px}}
.sub{{color:#666;font-size:13px;margin-bottom:26px}}
h2{{font-size:17px;margin:40px 0 14px;padding-left:10px;border-left:3px solid #111}}
.lead{{background:#fafafa;border:1px solid #e5e5e5;border-radius:10px;padding:16px 18px;font-size:14px}}
.lead b{{color:#1a5fb4}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}}
th,td{{border:1px solid #e5e5e5;padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#fafafa;font-size:12px;color:#666;font-weight:600}}
.card{{border:1px solid #e5e5e5;border-radius:12px;padding:16px 18px;margin:18px 0}}
.hd{{display:flex;gap:12px;align-items:flex-start;margin-bottom:10px}}
.rank{{flex:0 0 auto;background:#111;color:#fff;border-radius:6px;padding:3px 9px;font-size:12px;margin-top:2px}}
.ttl{{font-size:15px;font-weight:600}}
.meta{{font-size:12.5px;color:#666;margin-top:2px}}
.rows{{font-size:13px;margin:6px 0}}
.params{{margin:8px 0 12px}}
.tag{{display:inline-block;background:#eef4fb;color:#1a5fb4;border-radius:4px;
 padding:1px 6px;font-size:11.5px;margin:0 4px 4px 0;font-family:ui-monospace,Menlo,monospace}}
img{{width:100%;height:auto;display:block;border:1px solid #eee;border-radius:6px}}
.foot{{display:flex;gap:20px;margin-top:10px;font-size:13px;flex-wrap:wrap}}
.why{{flex:1 1 420px}} .rk{{flex:0 0 170px;color:#c0392b}}
.fname{{flex:1 1 100%;color:#999;font-size:11.5px;font-family:ui-monospace,Menlo,monospace}}
.warn{{border-left:3px solid #c0392b;background:#fff6f5;border-radius:0 8px 8px 0;padding:12px 16px;margin:16px 0;font-size:13.5px}}
.nolabel{{color:#999;font-size:12.5px}}
code{{background:#f5f5f5;border:1px solid #e5e5e5;border-radius:4px;padding:1px 5px;font-size:12.5px}}
</style>
<div class=wrap>
<h1>真实 datasheet 时序图候选</h1>
<div class=sub>2026-09-17 · 从 4 个真实厂商 datasheet 里筛出 6 张 · 全部原图未加工，仅按图框/图注精确裁切</div>

<div class=lead>
我们从「信号复杂度」出发筛了三档：<b>控制线为主</b>（AD7606）、<b>带并行总线</b>（AD7606 Fig 4 / ISSI SDRAM）、
<b>总线分时复用 + 多状态</b>（ADS8482）。<b>首选 ISSI IS42S16400J 的「ALTERNATING BANK WRITE ACCESS」</b>：
8 条信号、4 条并行总线、10 个时钟周期、两个 bank 交错，而且是横平竖直的机绘形态，正好是我们要验的那一类。
</div>

<h2>一、来源与检索路径</h2>
<table>
<tr><th style="width:24%">厂商</th><th style="width:30%">器件</th><th>说明</th></tr>
<tr><td>Analog Devices</td><td>AD7606 / AD7606-6 / AD7606-4</td><td>8 通道 16 位同步采样 ADC。第 9 页整页 4 张时序图。</td></tr>
<tr><td>Texas Instruments</td><td>ADS8482</td><td>18 位 1MSPS 并行输出 ADC。Figure 33 是本批最复杂的一张。</td></tr>
<tr><td>ISSI</td><td>IS42S16400J / IS45S16400J</td><td>256Mb SDR SDRAM。第 47–55 页是完整的时序波形章节。</td></tr>
<tr><td>TI（备用）</td><td>ADS1256 / ADS131M08 / SN74V293</td><td>已下载，本轮未出图（时序图偏简单或不在候选页）。</td></tr>
</table>
<div class=sub style="margin-top:-4px">检索方式：先按 <code>横竖线密度 + 时序关键词命中数</code> 自动给 PDF 每一页打分排序，
再人工确认。脚本见 <code>crop_figs.py</code>，切图边界取「图框矩形」或「相邻图注」，不靠手工量。</div>

<h2>二、候选清单</h2>
{''.join(cards)}

<h2>三、这三类对我们的意义</h2>
<table>
<tr><th style="width:22%">能验什么</th><th>对应图</th></tr>
<tr><td><b>真实厂商排版</b></td><td>全部 6 张。都是真实交付物，不是我画的。字体、线宽、标注风格全是工业界的。</td></tr>
<tr><td><b>并行总线怎么画</b></td><td>ISSI SDRAM 的 DQ / ADDR / BA / COMMAND 四条总线；AD7606 Fig 4 的 DB[15:0]。
这一条一直悬着 —— 我们渲染器只有直角方波，没做总线的斜边梯形。</td></tr>
<tr><td><b>无框图的解析</b></td><td>全部 6 张都<b>没有</b>每条信号的独立方框。我们现在的 <code>auto_trace.py</code> 只认有框的，
所以这批图正好是「无框模式」的需求样本。</td></tr>
<tr><td><b>多总线 + 多状态</b></td><td>ADS8482 Figure 33：11 行、3 条数据总线分时复用、斜线阴影表示不确定区。当前渲染器的天花板。</td></tr>
</table>

<div class=warn>
<b>版权提醒：</b>这些图是 ADI / TI / ISSI 的 datasheet 原图，著作权归各厂商。用于内部工程测试没问题，
但<b>不要打进 skill 的 zip 分发</b>。所以它们放在 <code>test-cases/</code> 下，不在 <code>.workbuddy/skills/wave2visio/assets/</code> 里。
</div>

<h2>四、文件清单</h2>
<table>
<tr><th style="width:44%">文件</th><th>内容</th></tr>
<tr><td><code>figs/*.png</code></td><td>6 张裁好的时序图（400 DPI，白边已自动裁掉）</td></tr>
<tr><td><code>dl/*.pdf</code></td><td>原始 datasheet（ad7606 / ads8482 / issi_sdr / ads1256 / ads131m08）</td></tr>
<tr><td><code>crop_figs.py</code></td><td>切图脚本（图框法 + 图注夹法）</td></tr>
<tr><td><code>scout/*.png</code></td><td>选型阶段的缩略拼版，留档</td></tr>
</table>

</div></html>"""
open("real-datasheet-candidates.html","w",encoding="utf-8").write(html)
print("✓ real-datasheet-candidates.html", len(html), "字节")
