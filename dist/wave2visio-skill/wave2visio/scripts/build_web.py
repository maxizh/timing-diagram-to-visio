#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_web.py — 从单一真相源构建网页产物。

为什么要这个脚本：
  以前「AI 识别规则」和「渲染器」各写两份 —— 网页里内联一份、references 里一份。
  结果修一个 bug 要改五个文件，而且两边会悄悄漂移（2026-09-14 的 `2-9` 数据块
  bug 就是这种结构埋出来的）。

单一真相源：
  scripts/renderer.js          直角方波渲染器（JS）
  references/vision-prompt.md  AI Vision 识别 prompt 正文

生成物（不要手改，改源再跑本脚本）：
  assets/paste-to-visio.html   主工具：图片→AI→WaveJSON→SVG→Visio
  assets/viewer.html           通用预览器（样例 SPI 0x5A/0xC3）
  assets/spi-mode0-0xa5.html   开箱即用示例（SPI 0xA5）

用法：
  python3 scripts/build_web.py            # 构建
  python3 scripts/build_web.py --check    # 只校验产物是否与源一致（CI 用）
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_RENDERER = os.path.join(BASE, 'scripts', 'renderer.js')
SRC_PROMPT = os.path.join(BASE, 'references', 'vision-prompt.md')
TPL_DIR = os.path.join(BASE, 'templates')
OUT_DIR = os.path.join(BASE, 'assets')

PLACEHOLDER_DOC = '<!-- 本文件由 scripts/build_web.py 生成，请勿手改 -->\n'


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def load_prompt():
    """从 vision-prompt.md 取正文（第一个 --- 分隔线之后的部分）。"""
    md = read(SRC_PROMPT)
    parts = md.split('\n---\n', 1)
    if len(parts) != 2:
        raise SystemExit(f'✗ {SRC_PROMPT} 缺少 "---" 分隔线，无法定位正文')
    return parts[1].strip()


def js_string(s):
    """生成合法的 JS 字符串字面量（含 U+2028/2029 转义）。"""
    out = json.dumps(s, ensure_ascii=False)
    return out.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def js_json(obj):
    """生成合法的 JS 对象字面量（JSON 本身即合法 JS 字面量，仅需转义行分隔符）。"""
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    return s.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


# ---------------------------------------------------------------
# 样例数据（原先散在各 HTML 里，现在集中一处）
# ---------------------------------------------------------------
SPI_5A = {
    "head": {"text": "SPI Mode 0 · MOSI=0x5A · MISO=0xC3 · CPOL=0 CPHA=0"},
    "signal": [
        {"name": "CS_n", "wave": "11000000000000000011"},
        {"name": "SCLK", "wave": "00010101010101010100"},
        {"name": "MOSI", "wave": "00001100111100110000"},
        {"name": "MISO", "wave": "00111100000000111100"},
    ],
    "config": {"hscale": 1},
    "foot": {"text": "MOSI: 0101_1010 = 0x5A · MISO: 1100_0011 = 0xC3 · MSB First"},
}

SPI_A5 = {
    "head": {"text": "SPI Mode 0 · 传输 0xA5 (1010_0101) · CPOL=0 CPHA=0"},
    "signal": [
        {"name": "CS_n", "wave": "11000000000000000011"},
        {"name": "SCLK", "wave": "00010101010101010100"},
        {"name": "MOSI", "wave": "00110011000011001100"},
        {"name": "MISO", "wave": "00110011000011001100"},
    ],
    "config": {"hscale": 1},
    "foot": {"text": "0xA5 = 1010_0101 · MSB First · MOSI/MISO 均为 0xA5（回环）"},
}

COMMENT_5A = """/* SPI Mode 0 · MOSI=0x5A · MISO=0xC3
   数据线一律用 0/1 表达真实高低电平 —— 2-9 会渲染成数据块，不是电平！
   1 个 bit = 2 个字符，首尾各留 2 字符空闲 → 全部 20 字符对齐 */"""

COMMENT_A5 = """/* SPI Mode 0 · 传输 0xA5 (1010_0101)
   数据线一律用 0/1 表达真实高低电平 —— 2-9 会渲染成数据块，不是电平！
   1 个 bit = 2 个字符，首尾各留 2 字符空闲 → 全部 20 字符对齐 */"""

VIEWER_JOBS = [
    dict(
        out='viewer.html',
        title='WaveJSON Viewer — 时序图预览器',
        h1='WaveJSON Viewer',
        sub='粘贴 WaveJSON → 直角方波渲染 → 导出 SVG（可直接进 Visio）',
        sample=SPI_5A,
        comment=COMMENT_5A,
    ),
    dict(
        out='spi-mode0-0xa5.html',
        title='SPI Mode 0 · 0xA5 — WaveJSON 时序图',
        h1='SPI Mode 0 · 传输 0xA5',
        sub='SPI Mode 0 全双工 · 0xA5 = 1010_0101 · 直角方波 · 可导出 SVG 进 Visio',
        sample=SPI_A5,
        comment=COMMENT_A5,
    ),
]


def build():
    """返回 {产物路径: 内容}。"""
    renderer = read(SRC_RENDERER).rstrip() + '\n'
    prompt = load_prompt()
    out = {}

    # 1) 主工具
    tpl = read(os.path.join(TPL_DIR, 'paste-to-visio.html'))
    for ph in ('@@RENDERER_JS@@', '@@VISION_PROMPT_JS@@'):
        if ph not in tpl:
            raise SystemExit(f'✗ templates/paste-to-visio.html 缺少占位符 {ph}')
    body = tpl.replace('@@RENDERER_JS@@', renderer)
    body = body.replace('@@VISION_PROMPT_JS@@', js_string(prompt))
    out['paste-to-visio.html'] = PLACEHOLDER_DOC + body

    # 2) viewer 系列
    vtpl = read(os.path.join(TPL_DIR, 'viewer.html'))
    for job in VIEWER_JOBS:
        page = vtpl
        page = page.replace('@@RENDERER_JS@@', renderer)
        page = page.replace('@@SAMPLE_JSON@@', js_json(job['sample']))
        page = page.replace('@@SAMPLE_COMMENT@@', job['comment'])
        page = page.replace('@@TITLE@@', job['title'])
        page = page.replace('@@H1@@', job['h1'])
        page = page.replace('@@SUB@@', job['sub'])
        left = [p for p in ('@@RENDERER_JS@@', '@@SAMPLE_JSON@@', '@@SAMPLE_COMMENT@@',
                            '@@TITLE@@', '@@H1@@', '@@SUB@@') if p in page]
        if left:
            raise SystemExit(f'✗ {job["out"]} 仍有未替换占位符: {left}')
        out[job['out']] = PLACEHOLDER_DOC + page

    return out


def main():
    ap = argparse.ArgumentParser(description='从单一真相源构建网页产物')
    ap.add_argument('--check', action='store_true', help='只校验产物是否与源一致，不写入')
    a = ap.parse_args()

    artifacts = build()
    stale, written = [], []
    for name, content in artifacts.items():
        path = os.path.join(OUT_DIR, name)
        old = read(path) if os.path.exists(path) else None
        if old == content:
            continue
        stale.append(name)
        if not a.check:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            written.append(f'{name} ({len(content)/1024:.1f} KB)')

    if a.check:
        if stale:
            print('✗ 产物与源不一致，请运行 python3 scripts/build_web.py：')
            for n in stale:
                print('   -', n)
            sys.exit(1)
        print(f'✓ 全部 {len(artifacts)} 个产物与源一致')
        return

    if written:
        print('✓ 构建完成：')
        for w in written:
            print('   ', w)
    else:
        print('✓ 已是最新，无需重新生成')
    print(f'  源: scripts/renderer.js + references/vision-prompt.md')
    print(f'  产物目录: assets/')


if __name__ == '__main__':
    main()
