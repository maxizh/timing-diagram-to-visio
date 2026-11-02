#!/usr/bin/env bash
#
# skill_dir.sh — 打印本技能在当前机器上的实际安装目录。
#
# 为什么需要它：同一个技能包可装到三个宿主（~/.workbuddy / ~/.claude / ~/.codex），
# 而 SKILL.md 里的命令示例只能给一个默认路径。硬编码路径会让「装到 A、用B」
# 的用户复制命令后跑到空目录去。这里按实际存在的安装位置判定，避免文档骗人。
#
# 用法：
#   eval "SKILL=$(bash "$(dirname "$0")/skill_dir.sh")"   # 源码内取路径
#   bash skill_dir.sh                # 直接打印
#
# 退出码：0 = 找到；1 = 三处都没找到（打印排查提示）
set -euo pipefail

NAME="${1:-wave2visio}"
CANDIDATES=(
  "$HOME/.workbuddy/skills/$NAME"
  "$HOME/.claude/skills/$NAME"
  "$HOME/.codex/skills/$NAME"
)

for d in "${CANDIDATES[@]}"; do
  if [[ -f "$d/SKILL.md" ]]; then
    printf '%s\n' "$d"
    exit 0
  fi
done

echo "ERROR: 未找到技能 '$NAME' 的安装目录，查过这三处：" >&2
printf '  - %s\n' "${CANDIDATES[@]}" >&2
echo "装一下：bash install.sh  或参照 README 手动复制 wavejson/ 目录。" >&2
exit 1