#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 pdf-trace-demo.html —— 「PDF 直读」路线的对照验收页（单文件，全 base64 内嵌）。

做两件事：
  1. 真实厂商 PDF（ISSI SDR p54）：把**原图裁出来**，和 pdf_trace.py 生成的 SVG 并排 ——
     这是「一模一样」这条红线的目视凭据；
  2. 合成 PDF（selftest 自己造的那张）：同一套并排，演示链路可复现、且无版权顾虑。

输出落在 skill 库**之外**（test-cases/），因为要内嵌厂商图 —— 与 noframe-mode.html 同规矩。

用法：python3 build_pdf_demo.py
"""
import base64
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPTS = os.path.join(ROOT, ".workbuddy", "skills", "wave2visio", "scripts")
sys.path.insert(0, SCRIPTS)

import pymupdf                                            # noqa: E402
import pdf_trace as pt                                    # noqa: E402
import wavejson2svg                                       # noqa: E402


def _b64_png(raw_bytes):
    return "data:image/png;base64," + base64.b64encode(raw_bytes).decode()


def page_crop(pdf, page_no, y0, y1, dpi=200):
    """把某页的 [y0,y1] 横条渲染成 PNG（含左侧行标签与整幅波形）。"""
    doc = pymupdf.open(pdf)
    page = doc[page_no - 1]
    clip = pymupdf.Rect(0, max(0.0, y0), page.rect.width, min(page.rect.height, y1))
    pm = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, clip=clip)
    return _b64_png(pm.tobytes("png"))


def svg_of(pdf, page_no, dpi=300):
    """跑整条链：PDF 认字 ⊕ PNG 数电平 → WaveJSON → SVG。"""
    res, meta = pt.analyse(pdf, page_no)
    png, scale = pt.render_page(pdf, page_no, dpi=dpi)
    pt.fuse_levels(res, png, scale)
    wj = pt.to_wavejson(res)
    return res, wj, wavejson2svg.render(wj)


def svg_img(svg_text, scale=1.0):
    b = base64.b64encode(svg_text.encode("utf-8")).decode()
    return f'<img class="svg" src="data:image/svg+xml;base64,{b}" style="zoom:{scale}">'


def rows_table(res):
    out = ['<table><thead><tr><th>行</th><th>类型</th><th>值（按槽位）</th>'
           '<th>几何解出的电平</th></tr></thead><tbody>']
    for r in res["rows"]:
        kind = "总线带" if r["kind"] == pt.KIND_BUS else "电平"
        if r["kind"] == pt.KIND_BUS:
            vals = " · ".join(f'<b>{k}</b>={v}' for k, v in
                              sorted(r["slots"].items(), key=lambda t: int(t[0])))
        else:
            vals = "—"
        wave = r.get("wave") or "—"
        out.append(f'<tr><td class="nm">{r["name"]}</td><td>{kind}</td>'
                   f'<td class="vals">{vals}</td><td class="wv">{wave}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def case(title, src, pdf, page_no, note, svg_zoom=1.0):
    """一个对照块：原图裁片 ‖ 本工具输出。

    裁片的 y 范围直接取 pdf_trace 自己解出的 `figure_y`（= 各行标签带的上下界），
    再加点余量，避免手填一个会随图变化的魔数。
    """
    res, wj, svg = svg_of(pdf, page_no)
    gy0 = res["figure_y"][0] - 30
    gy1 = res["figure_y"][1] + 50
    return f"""
<section>
  <h2>{title}</h2>
  <p class="note">{note}</p>
  <div class="pair">
    <figure><figcaption>① 原图（来自 {src}，直接裁自 PDF 矢量页）</figcaption>
      {page_crop(pdf, page_no, gy0, gy1)}</figure>
    <figure><figcaption>② 本工具输出（<code>pdf_trace.py</code> → WaveJSON → SVG，零大模型）</figcaption>
      {svg_img(svg, svg_zoom)}</figure>
  </div>
  <details open><summary>解出来的行与值（文本层直读，逐字）</summary>
    {rows_table(res)}
    <p class="kv">位网格：{json.dumps(res["grid"], ensure_ascii=False)}</p>
  </details>
</section>"""


def main():
    issi = os.path.abspath(os.path.join(HERE, "dl", "issi_sdr.pdf"))

    # 合成 PDF 现场造一张（无版权顾虑，链路可复现）
    import tempfile
    import selftest as st
    tmp = tempfile.mkdtemp(prefix="pdf_demo_")
    synth = os.path.join(tmp, "synth_timing.pdf")
    st._make_synth_timing_pdf(synth)

    blocks = []
    if os.path.exists(issi):
        blocks.append(case(
            "真实厂商 PDF：ISSI IS42S16400J SDRAM 交替 bank 写时序（p54）",
            "ISSI IS42S16400J datasheet（不入库）", issi, 54,
            "这是原厂图里信号最密的一页：8 行信号 / 5 行并行总线 / 10 个时钟周期 / 灰底 DON'T CARE。"
            "信号名与总线值由 PDF 文本层直读，电平高低由像素几何解出。", svg_zoom=0.86))
    else:
        blocks.append("<section><h2>真实厂商 PDF</h2>"
                      "<p class='note'>跳过：本机没有 dl/issi_sdr.pdf</p></section>")

    blocks.append(case(
        "合成 PDF：教科书式 3 行时序图（自检第 [10] 组用的那张，现场生成）",
        "selftest._make_synth_timing_pdf()", synth, 1,
        "这张图不进仓库、每次自检现场生成 —— 所以整条链路可以**无版权地**长期回归。"
        "CLK 每槽前半低后半高、CMD 是三个总线方框、DATA 是「低电平线 + 首槽灰底 DON'T CARE」。",
        svg_zoom=1.0))

    html = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>pdf_trace.py 对照验收 · wave2visio skill</title>
<style>
  :root {{ --bg:#0f1115; --fg:#e6e8ee; --dim:#9aa3b2; --line:#2a2f3a; --acc:#7cc4ff; --ok:#5fd39a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 28px 64px; background:var(--bg); color:var(--fg);
         font:15px/1.7 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif; }}
  h1 {{ font-size:24px; margin:0 0 6px; }}
  h2 {{ font-size:17px; margin:0 0 6px; color:#fff; }}
  .lead {{ color:var(--dim); margin:0 0 28px; max-width:1000px; }}
  .lead b {{ color:var(--fg); }}
  section {{ border-top:1px solid var(--line); padding:22px 0 30px; }}
  .note {{ color:var(--dim); margin:0 0 16px; max-width:1000px; }}
  .pair {{ display:grid; grid-template-columns:1fr; gap:18px; }}
  figure {{ margin:0; background:#fff; border:1px solid var(--line); border-radius:10px;
            padding:10px; overflow:auto; }}
  figcaption {{ color:#5a6273; font-size:12.5px; margin:2px 0 10px; }}
  figure img, figure object {{ display:block; width:100%; height:auto; }}
  figcaption code {{ background:#eef1f6; padding:1px 5px; border-radius:4px; }}
  table {{ border-collapse:collapse; width:100%; margin:10px 0 6px; font-size:13.5px; }}
  th, td {{ border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }}
  th {{ background:#171b23; color:#fff; font-weight:600; }}
  td.nm {{ color:var(--acc); white-space:nowrap; }}
  td.wv {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.4px; }}
  td.vals {{ color:#cdd3de; }}
  details summary {{ cursor:pointer; color:var(--acc); font-weight:600; margin-top:8px; }}
  .kv {{ color:var(--dim); font-size:13px; font-family:ui-monospace,Menlo,monospace; }}
  .ok {{ color:var(--ok); font-weight:600; }}
  footer {{ color:var(--dim); font-size:12.5px; margin-top:26px; }}
</style>
<h1>pdf_trace.py 对照验收 —— 「有 PDF 就别读 PNG」</h1>
<p class="lead">
  左＝厂商原图（直接裁自 PDF 矢量页），右＝本工具输出。
  信号名 / 总线值 / 位网格来自 <b>PDF 文本层</b>（厂商原始数据，逐字精确）；
  电平高低来自 <b>PNG 像素几何</b>。全程 <b>零大模型、零 OCR、零 API Key</b>。
</p>
{''.join(blocks)}
<footer>wave2visio skill · scripts/pdf_trace.py · 本页为单文件自包含（图片全部 base64 内嵌），可直接转发<br>
厂商图源不入技能库（本页在 test-cases/ 下，不进分发 zip）</footer>
</html>"""

    out = os.path.join(HERE, "pdf-trace-demo.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ {out}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
