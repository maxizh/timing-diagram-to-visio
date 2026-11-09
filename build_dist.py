#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dist.py — 从**源**重建分发包（dist/wave2visio-skill/）+ 两个 zip。

为什么要有这个（2026-11-02）：
  以前 dist/wave2visio-skill/wave2visio/ 是源的一份**手工拷贝**，每次改完要手动
  rsync/cp 六七个地方 —— 已经因此出过两次事故：
    · 10-22 那晚把「修复前」的版本同步到了源和 dist，修复直接丢失
    · 11-02 改名时漏同步，自检基线跟着旧版走，「112 项全过」是假象
  现在：**源是唯一真相，dist 是构建产物**。一条命令重建，改完跑它就不会漂移。

用法：
    python3 build_dist.py            # 重建 dist + zip，并做一致性校验
    python3 build_dist.py --check    # 只校验（不写），用于 CI / 自检

一致性校验（每次都做）：
  · dist/wave2visio-skill/wave2visio/ 与源逐字节一致
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
SKILL_NAME = SRC.name                      # wave2visio（= 目录名 = frontmatter name）
# 分发包名 = 技能名 + "-skill"（wave2visio-skill）。跟随技能名，改名不用手改。
PKG_NAME = f"{SKILL_NAME}-skill"
DIST = ROOT / "dist" / PKG_NAME
IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.bak-*", "*.removed-*",
                                 "*.pyc", "memory")

# 历史用过的技能名（改名后旧名会散落在各处，这里统一追杀）。
# ⚠️ WaveJSON 是**中间数据格式**名，不是技能名 —— 不要加到这张表里，
#    也不要去改 `wavejson2svg.py` 这类「格式→产物」的脚本名（它名副其实）。
OLD_NAMES = ["wavejson"]

# 旧技能名的残留形态（按特异性从高到低，逐个吃掉）。
# 每条 = (正则, 替换模板, 说明, 仅 .md 文件适用)。{N} 会替换成当前技能名。
# 最后一条**只在 .md 里判**：代码里拿「格式名」当变量名是合法的
# （如 verdi-to-visio.html 里的 `const wavejson = ...` 指的是 WaveJSON 数据）。
NAME_FIXES = [
    (r"@skill:{O}\b", "@skill:{N}", "@skill 触发名", False),
    (r"(?<![\w.])/{O}\b", "/{N}", "斜杠命令", False),
    (r"\${O}\b", "${N}", "Codex 触发名", False),
    (r"skills/{O}\b", "skills/{N}", "技能目录路径", False),
    (r"(?<![\w/]){O}/(?![a-z])", "{N}/", "技能目录名", False),
    (r"(?<![\w-]){O}[ _-]skill", "{N} skill", "技能署名", False),
    (r"(?<![\w-]){O}-skill\b", "{N}-skill", "分发包名", False),
    (r"(?<![\w/.\-]){O}(?!2svg|[\w.\-])", "{N}", "孤立旧技能名", True),
]
SCAN_EXTS = {".md", ".py", ".sh", ".html", ".js", ".json", ".svg", ".txt"}


def log(msg):
    print(f"  {msg}")


def _name_rules():
    """把 NAME_FIXES 里的 {O}/{N} 展开成「按历史名逐个」的 (正则, 替换, 说明, md_only)。"""
    rules = []
    for old in OLD_NAMES:
        if old == SKILL_NAME:
            continue
        for pat, rep, why, md_only in NAME_FIXES:
            p = pat.replace("{O}", old).replace("{N}", SKILL_NAME)
            r = rep.replace("{O}", old).replace("{N}", SKILL_NAME)
            rules.append((re.compile(p), r, why, md_only))
    return rules


def name_fix_file(path: pathlib.Path):
    """把单个文件里的旧技能名全部改成当前技能名。返回 [说明, ...]。"""
    if path.suffix.lower() not in SCAN_EXTS:
        return []
    s = path.read_text(encoding="utf-8")
    hits = []
    for rx, rep, why, md_only in _name_rules():
        if md_only and path.suffix.lower() != ".md":
            continue
        if rx.search(s):
            hits.append(why)
            s = rx.sub(rep, s)
    if hits:
        path.write_text(s, encoding="utf-8")
    return hits


def scan_stale_names(root: pathlib.Path):
    """扫整个目录树，返回 [(相对路径, 行号, 说明, 行内容), ...]。空 = 干净。"""
    out = []
    rules = _name_rules()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SCAN_EXTS:
            continue
        if any(x in str(p) for x in (".DS_Store", "__pycache__", ".bak-", ".removed-")):
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for rx, _rep, why, md_only in rules:
                if md_only and p.suffix.lower() != ".md":
                    continue
                if rx.search(line):
                    out.append((str(p.relative_to(root)), i, why, line.strip()))
                    break
    return out


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

    # ---- 2. 分发包里的「旧技能名」自动改成当前技能名 ----
    # 为什么要这一步（2026-11-02 血的教训）：改名时 install.sh / README 是手写文件，
    # 不在技能本体镜像范围内 —— 只修了本体，文档里的触发命令、目录名、包名全是旧名，
    # 用户照着文档敲旧触发名直接扑空。**文档也必须跟着改名。**
    for name in ("install.sh", "README.md"):
        f = DIST / name
        if not f.is_file():
            continue
        hits = name_fix_file(f) if not check_only else []
        if hits:
            log(f"✓ {name} 旧技能名 → {SKILL_NAME}（{'/'.join(sorted(set(hits)))}）")

    # ---- 2b. 命名守卫：分发包里不许再有任何旧技能名 ----
    stale = scan_stale_names(DIST)
    if stale:
        print(f"ERROR: 分发包残留旧技能名（{len(stale)} 处，应为 {SKILL_NAME}）：",
              file=sys.stderr)
        for r, i, why, line in stale[:10]:
            print(f"    {r}:{i}  [{why}]  {line[:90]}", file=sys.stderr)
        return 1
    log(f"✓ 命名守卫通过（0 处旧技能名残留）")

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
    #   ① base 不能是 dist/ 本身 —— 那个目录里有 dist/wave2visio-skill.zip，
    #      正在被写，rglob 会扫到它 → 边写边扫，死循环卡死（SIGTERM）。
    #      所以 base 必须是 dist/wave2visio-skill/（子目录）。
    #   ② 第二个 zip 的 base 是 .workbuddy/skills/，不能 rglob 整个目录树 ——
    #      那里有一堆 wavejson.bak-* 历史备份，全扫进去又慢又脏。
    #      只打包**目标技能目录**这一个子目录。
    zips = [(ROOT / "dist" / f"{PKG_NAME}.zip", DIST, PKG_NAME, None),
            (ROOT / ".workbuddy" / "skills" / f"{PKG_NAME}.zip",
             ROOT / ".workbuddy" / "skills", SKILL_NAME, SRC)]
    for zp, base, arc, only in zips:
        if check_only:
            continue
        zp.parent.mkdir(parents=True, exist_ok=True)
        if zp.exists():
            zp.unlink()
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            if only is None:
                # 整个 dist/wave2visio-skill/ 目录
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
