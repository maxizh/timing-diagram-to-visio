#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 技能商店发布前一键预检（纯标准库，零依赖）。

用法：python3 dist/workbuddy-store/prepublish_check.py
退出码 0 = 可以上传；1 = 有问题（逐条列出，精确到文件与行号）。

检查五件事：
  1. 平台必填 frontmatter（复用 build_dist.check_store_frontmatter）
  2. 商店 zip 结构（复用 build_dist.verify_store_zip）
  3. 头像规格 512x512 PNG / ≤500KB（直接读 PNG IHDR，不需要 Pillow）
  4. 公开前敏感信息：本机绝对路径 / 个人信息 / 凭证 / 邮箱 / 手机号
  5. 用户可见部分按语言分区、不中英混排（check_language_split）

⚠️ 扫描对象是**商店 zip 内的全部文件 + 发布辅助脚本**，不含本校验器自身 ——
   校验器源码里有检测用的模式字面量，扫它必然自命中，那是逻辑错误不是豁免。
"""
import importlib.util
import pathlib
import re
import struct
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location("bd", ROOT / "build_dist.py")
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)

TEXT_EXT = {".md", ".py", ".sh", ".html", ".js", ".json",
            ".svg", ".txt", ".yaml", ".yml", ".css"}
AUX = [HERE / "make_avatar.py"]

PATS = [
    ("本机绝对路径", r"/Users/[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+|C:\\Users\\"),
    # 只判「非通用措辞」这类模式，不把任何具体个人标识写进公开的校验器源码。
    # 不判「粘给 X」：技能里「把图粘给宿主 AI」是中性技术措辞，判了会误报。
    ("非通用措辞", r"[\u4e00-\u9fa5]{0,6}(专用|专属|私人定制)"),
    ("密钥/凭证",
     r"(?i)sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{10,}"
     r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
     r"|(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[\"'][^\"']{8,}"),
    ("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("邮箱地址", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
]
# 二进制（PNG 等）只查这些足够长、不会随机命中的标记
BIN_MARKERS = [b"/Users/", b"/home/", b"C:\\Users\\",
               b"@qq.com", b"@outlook.com", b"PRIVATE KEY"]


def check_avatar():
    p = HERE / "wave2visio-avatar.png"
    if not p.is_file():
        # 用文件名而非 relative_to：HERE 可被替换（如 CI 临时目录），别在报错分支里再抛异常
        return [f"头像不存在: {p.name}"]
    b = p.read_bytes()
    errs = []
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        errs.append("头像不是 PNG")
    elif struct.unpack(">II", b[16:24]) != (512, 512):
        errs.append(f"头像尺寸 {struct.unpack('>II', b[16:24])} != 512x512")
    if p.stat().st_size > 500 * 1024:
        errs.append(f"头像 {p.stat().st_size} bytes > 500KB")
    return errs


def check_language_split():
    """用户可见部分必须按语言分区，不许中英混排（Max 2026-11-15 定的规范）。

    只管「给用户看的内容」：frontmatter 的中/英展示字段 + 正文「# 使用说明」下的
    中文区 / 英文区。底下「# 技能实现说明」是给宿主智能体与开发者看的，不受此约束。
    """
    s = (bd.SRC / "SKILL.md").read_text(encoding="utf-8")
    lines = s.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return ["SKILL.md frontmatter 缺结束 ---"]
    fm = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    errs = []

    # 十六进制数值（A5 / 0xA5）是数值符号，不算语言混排
    def latin_words(t):
        return re.findall(r"[A-Za-z]+", re.sub(r"(?:0x)?[0-9A-Fa-f]+", " ", t))

    def has_han(t):
        return bool(re.search(r"[\u4e00-\u9fa5]", t))

    # 1) 中文展示字段：零拉丁字母
    zh_vals = []
    for m in re.finditer(r"^(display_name|description_zh):\s*(.*)$", fm, re.M):
        zh_vals.append((m.group(1), m.group(2)))
    m = re.search(r"^examples_zh:\n((?:  - .*\n)+)", fm, re.M)
    if m:
        for i, l in enumerate(m.group(1).strip().splitlines(), 1):
            zh_vals.append((f"examples_zh[{i}]", l.strip()))
    for k, v in zh_vals:
        w = latin_words(v)
        if w:
            errs.append(f"中文展示字段 {k} 混入拉丁字母: {w[:6]}")

    # 2) 英文展示字段：零中文字符
    for k in ("display_name_en", "description", "description_en"):
        mm = re.search(rf"^{k}:\s*(.*)$", fm, re.M)
        if mm and has_han(mm.group(1)):
            errs.append(f"英文展示字段 {k} 混入中文")
    m = re.search(r"^examples_en:\n((?:  - .*\n)+)", fm, re.M)
    if m and has_han(m.group(1)):
        errs.append("英文展示字段 examples_en 混入中文")

    # 3) 正文两个语言区各自纯净
    if "## 中文" not in body or "## English" not in body:
        errs.append("正文缺「## 中文」或「## English」语言分区")
    else:
        zh_sec = body.split("## 中文", 1)[1].split("## English", 1)[0]
        en_sec = body.split("## English", 1)[1].split("\n---", 1)[0]
        w = latin_words(zh_sec)
        if w:
            errs.append(f"正文中文区混入拉丁字母: {w[:6]}")
        if has_han(en_sec):
            errs.append("正文英文区混入中文")

    # 4) frontmatter 中文块整体排在英文块之前（不许中英字段一行一交替）
    m = re.search(r"^examples_zh:\n((?:  - .*\n)+)", fm, re.M)
    if m and "display_name_en:" in fm and m.end() > fm.find("display_name_en:"):
        errs.append("frontmatter 中英文字段交替，未按语言分块")
    return errs


def scan_secrets():
    if not bd.STORE_ZIP.is_file():
        return [], 0
    blobs = []
    with zipfile.ZipFile(bd.STORE_ZIP) as z:
        for n in sorted(z.namelist()):
            blobs.append((n, z.read(n)))
    for p in AUX:
        if p.is_file():
            blobs.append((str(p.relative_to(ROOT)), p.read_bytes()))
    hits = []
    for name, raw in blobs:
        ext = pathlib.Path(name).suffix.lower()
        if ext in TEXT_EXT:
            s = raw.decode("utf-8", "ignore")
            for label, pat in PATS:
                for m in re.finditer(pat, s):
                    hits.append((label, name, s[:m.start()].count("\n") + 1,
                                 m.group()[:70]))
        else:
            for marker in BIN_MARKERS:
                if marker in raw:
                    hits.append(("二进制内嵌敏感串", name, 0, marker.decode()))
    return hits, len(blobs)


def main():
    errs = []
    print("=== WorkBuddy 技能商店发布前预检 ===")
    print(f"  商店包 {bd.STORE_ZIP.relative_to(ROOT)}")

    e = bd.check_store_frontmatter(bd.SRC / "SKILL.md")
    print(f"  [1] 平台必填 frontmatter : {'PASS' if not e else 'FAIL'}  {e}")
    errs += [f"frontmatter: {x}" for x in e]

    if not bd.STORE_ZIP.is_file():
        e = [f"商店包不存在 {bd.STORE_ZIP.relative_to(ROOT)}，请先跑 build_dist.py"]
    else:
        e = bd.verify_store_zip(bd.STORE_ZIP)
    print(f"  [2] 商店 zip 结构        : {'PASS' if not e else 'FAIL'}  {e}")
    errs += [f"zip 结构: {x}" for x in e]

    e = check_avatar()
    print(f"  [3] 头像规格             : {'PASS' if not e else 'FAIL'}  {e}")
    errs += [f"头像: {x}" for x in e]

    hits, nfiles = scan_secrets()
    print(f"  [4] 敏感信息（{nfiles} 个文件）: {'PASS' if not hits else 'FAIL'}  命中 {len(hits)}")
    for h in hits[:15]:
        print(f"      {h}")
    errs += [f"敏感信息 {label} @ {name}:{line}  {val}"
             for label, name, line, val in hits]

    e = check_language_split()
    print(f"  [5] 用户可见部分语言分区: {'PASS' if not e else 'FAIL'}  {e}")
    errs += [f"语言分区: {x}" for x in e]

    if bd.STORE_ZIP.is_file():
        size = bd.STORE_ZIP.stat().st_size
        print(f"  商店包体积: {size} bytes ({size / 1024:.0f} KB) / 上限 3MB")

    print()
    if errs:
        print(f"✗ 预检未通过（{len(errs)} 项），不要上传：")
        for x in errs:
            print(f"    - {x}")
        return 1
    print("✓ 预检全绿，可上传到开放平台")
    return 0


if __name__ == "__main__":
    sys.exit(main())
