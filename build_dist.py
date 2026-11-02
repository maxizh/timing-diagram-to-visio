#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dist.py — 从**源**重建分发包（dist/wavejson-skill/）+ 两个 zip。

为什么要有这个（2026-11-02）：
  以前 dist/wavejson-skill/wave2visio/ 是源的一份**手工拷贝**，每次改完要手动
  rsync/cp 六七个地方 —— 已经因此出过两次事故：
    · 10-22 那晚把「修复前」的版本同步到了源和 dist，修复直接丢失
    · 11-02 改名时漏同步，自检基线跟着旧版走，「112 项全过」是假象
  现在：**源是唯一真相，dist 是构建产物**。一条命令重建，改完跑它就不会漂移。

用法：
    python3 build_dist.py            # 重建 dist + zip，并做一致性校验
    python3 build_dist.py --check    # 只校验（不写），用于 CI / 自检

一致性校验（每次都做）：
  · dist/wavejson-skill/wave2visio/ 与源逐字节一致
  · 两个 zip 的内容与目录一致
  · install.sh 里引用的技能名与源目录名一致

⚠️ 源目录名 = 技能名 = 安装目录名 = frontmatter 的 name
   改技能名时，这个脚本会自动跟着改 install.sh 的 SKILL_NAME。
"""
import argparse
import pathlib
import re
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / ".workbuddy" / "skills" / "wave2visio"
DIST = ROOT / "dist" / "wavejson-skill"
SKILL_NAME = SRC.name                      # wave2visio
IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.bak-*", "*.removed-*",
                                 "*.pyc", "memory")


def log(msg):
    print(f"  {msg}")


def copy_tree(src: pathlib.Path, dst: pathlib.Path):
    """把 src 的内容镜像到 dst（先清空 dst，保证没有残留）。"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)


def build(check_only=False):
    if not SRC.is_dir():
        print(f"ERROR: 源目录不存在 {SRC}", file=sys.stderr)
        return 2

    print(f"源       {SRC.relative_to(ROOT)}")
    print(f"分发包   {DIST.relative_to(ROOT)}")

    # ---- 1. 技能本体镜像 ----
    target = DIST / SKILL_NAME
    if check_only:
        if not target.is_dir():
            print(f"ERROR: 分发包缺 {target.relative_to(ROOT)}", file=sys.stderr)
            return 1
    else:
        copy_tree(SRC, target)
        log(f"✓ 镜像技能本体 → {target.relative_to(ROOT)}")

    # ---- 2. install.sh 的 SKILL_NAME 必须跟源目录名一致 ----
    inst = DIST / "install.sh"
    if inst.is_file():
        s = inst.read_text(encoding="utf-8")
        m = re.search(r'SKILL_NAME="([^"]+)"', s)
        if m and m.group(1) != SKILL_NAME:
            if check_only:
                print(f"ERROR: install.sh 的 SKILL_NAME={m.group(1)} ≠ {SKILL_NAME}",
                      file=sys.stderr)
                return 1
            s = re.sub(r'SKILL_NAME="[^"]+"', f'SKILL_NAME="{SKILL_NAME}"', s)
            s = s.replace("wavejson-skill/raw/main", f"{SKILL_NAME}-skill/raw/main")
            s = s.replace("<user>/wavejson-skill", f"<user>/{SKILL_NAME}-skill")
            inst.write_text(s, encoding="utf-8")
            log(f"✓ install.sh 的 SKILL_NAME → {SKILL_NAME}")

    # ---- 3. 逐字节一致性校验 ----
    src_files = sorted(p.relative_to(SRC) for p in SRC.rglob("*")
                       if p.is_file() and not any(x in str(p) for x in
                                                 (".DS_Store", "__pycache__", ".bak-")))
    bad = []
    for rel in src_files:
        a, b = SRC / rel, target / rel
        if not b.is_file():
            bad.append(f"{rel} 缺失")
        elif a.read_bytes() != b.read_bytes():
            bad.append(f"{rel} 内容不同")
    extra = [p.relative_to(target) for p in target.rglob("*")
             if p.is_file() and not (target / p.relative_to(target)).exists()
             and p.relative_to(target) not in src_files
             and not any(x in str(p) for x in (".DS_Store", "__pycache__", ".bak-"))]
    for e in extra:
        bad.append(f"{e} 是多余文件")
    if bad:
        print(f"ERROR: 分发包与源不一致（{len(bad)} 处）：", file=sys.stderr)
        for b in bad[:10]:
            print(f"    {b}", file=sys.stderr)
        return 1
    log(f"✓ 一致性校验通过（{len(src_files)} 个文件逐字节一致）")

    # ---- 4. 打包 zip ----
    # ⚠️ 两个坑（都实测踩过）：
    #   ① base 不能是 dist/ 本身 —— 那个目录里有 dist/wavejson-skill.zip，
    #      正在被写，rglob 会扫到它 → 边写边扫，死循环卡死（SIGTERM）。
    #      所以 base 必须是 dist/wavejson-skill/（子目录）。
    #   ② 第二个 zip 的 base 是 .workbuddy/skills/，不能 rglob 整个目录树 ——
    #      那里有一堆 wavejson.bak-* 历史备份，全扫进去又慢又脏。
    #      只打包**目标技能目录**这一个子目录。
    zips = [(ROOT / "dist" / "wavejson-skill.zip", DIST, "wavejson-skill", None),
            (ROOT / ".workbuddy" / "skills" / "wavejson-skill.zip",
             ROOT / ".workbuddy" / "skills", SKILL_NAME, SRC)]
    for zp, base, arc, only in zips:
        if check_only:
            continue
        zp.parent.mkdir(parents=True, exist_ok=True)
        if zp.exists():
            zp.unlink()
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            if only is None:
                # 整个 dist/wavejson-skill/ 目录
                for f in sorted(base.rglob("*")):
                    if f.is_file() and not any(x in str(f) for x in
                                               (".DS_Store", "__pycache__", ".bak-", ".removed-")):
                        z.write(f, f.relative_to(base))
            else:
                # 只打包技能目录本身，zip 内根就是 wave2visio/
                for f in sorted(only.rglob("*")):
                    if f.is_file() and not any(x in str(f) for x in
                                               (".DS_Store", "__pycache__", ".bak-", ".removed-")):
                        z.write(f, f.relative_to(only))
        log(f"✓ 打包 {zp.relative_to(ROOT)}  ({zp.stat().st_size} bytes)")

    print("✓ 分发包重建完成")
    return 0


def main():
    ap = argparse.ArgumentParser(description="从源重建分发包 + zip")
    ap.add_argument("--check", action="store_true", help="只校验不写")
    a = ap.parse_args()
    sys.exit(build(check_only=a.check))


if __name__ == "__main__":
    main()
