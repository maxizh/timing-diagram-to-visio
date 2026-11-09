#!/usr/bin/env bash
#
# wave2visio skill installer — Agent Skills open standard
# Works with: WorkBuddy / Claude Code / Codex CLI
#
# Local (from this repo / extracted zip):
#   bash install.sh                    # install to all three agents
#   bash install.sh claude             # install to Claude Code only
#   bash install.sh workbuddy codex    # pick targets
#   bash install.sh --uninstall        # remove from all agents
#   bash install.sh --uninstall claude # remove from Claude Code only
#
# Remote one-liner (after you host this repo, e.g. on GitHub):
#   curl -fsSL https://example.com/wave2visio-skill/raw/main/install.sh | \
#       bash -s -- --repo https://github.com/<user>/wave2visio-skill
#
set -euo pipefail

SKILL_NAME="wave2visio"
VERSION="$(sed -n 's/^version: *//p' "$(dirname "$0")/wave2visio/SKILL.md" 2>/dev/null || true)"
VERSION="${VERSION:-unknown}"

# --- targets ---------------------------------------------------------------
# name|install-path|trigger-hint
ALL_TARGETS=(
  "workbuddy|$HOME/.workbuddy/skills|WorkBuddy: natural language, or @skill:wave2visio"
  "claude|$HOME/.claude/skills|Claude Code: auto-match, or /wave2visio (restart not needed)"
  "codex|$HOME/.codex/skills|Codex CLI: auto-match, or \$wave2visio (restart Codex if not shown)"
)

usage() {
  cat <<EOF
wave2visio skill installer (v${VERSION})

Usage:
  bash install.sh [target ...]        install (default: all targets)
  bash install.sh --uninstall [t ...] uninstall
  bash install.sh --list              list targets and paths
  bash install.sh --repo URL [...]    remote mode: clone repo first (for curl | bash)

Targets: workbuddy claude codex all
EOF
}

resolve_targets() {
  local args=("$@") out=()
  if [[ ${#args[@]} -eq 0 || ( ${#args[@]} -eq 1 && -z "${args[0]}" ) ]]; then
    echo "workbuddy claude codex"
    return
  fi
  for a in "${args[@]}"; do
    case "$a" in
      all) echo "workbuddy claude codex"; return ;;
      workbuddy|claude|codex) out+=("$a") ;;
      *) echo "ERROR: unknown target '$a' (use: workbuddy claude codex all)" >&2; exit 2 ;;
    esac
  done
  echo "${out[*]}"
}

target_row() {   # echo the matching "name|path|hint" row
  local t="$1" row
  for row in "${ALL_TARGETS[@]}"; do
    if [[ "$row" == "$t|"* ]]; then
      echo "$row"
      return 0
    fi
  done
  echo "ERROR: no such target '$t'" >&2
  exit 2
}

target_path() {
  local rest
  rest="$(target_row "$1")"
  rest="${rest#*|}"
  echo "${rest%%|*}"
}

target_hint() {
  local rest
  rest="$(target_row "$1")"
  echo "${rest##*|}"
}

# --- locate the skill directory ---------------------------------------------
find_skill_dir() {
  # 1) next to this script (local checkout / extracted zip)
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/${SKILL_NAME}"
  [[ -f "$d/SKILL.md" ]] && { echo "$d"; return 0; }
  # 2) cwd
  d="$(pwd)/${SKILL_NAME}"
  [[ -f "$d/SKILL.md" ]] && { echo "$d"; return 0; }
  return 1
}

# --- main -------------------------------------------------------------------
ACTION="install"
REPO=""
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall) ACTION="uninstall"; shift ;;
    --list)      ACTION="list"; shift ;;
    --repo)      REPO="$2"; shift 2 ;;
    --repo=*)    REPO="${1#*=}"; shift ;;
    -h|--help)   usage; exit 0 ;;
    *)           ARGS+=("$1"); shift ;;
  esac
done

if [[ "$ACTION" == "list" ]]; then
  for row in "${ALL_TARGETS[@]}"; do
    t="${row%%|*}"; rest="${row#*|}"; p="${rest%%|*}"; h="${rest##*|}"
    printf '%-10s %s\n  └─ %s\n' "$t" "$p/$SKILL_NAME" "$h"
  done
  exit 0
fi

if [[ ${#ARGS[@]} -eq 0 ]]; then
  TARGETS="$(resolve_targets)"
else
  TARGETS="$(resolve_targets "${ARGS[@]}")"
fi

# uninstall ------------------------------------------------------------------
if [[ "$ACTION" == "uninstall" ]]; then
  for t in $TARGETS; do
    d="$(target_path "$t")/$SKILL_NAME"
    if [[ -d "$d" ]]; then
      mv "$d" "${d}.removed-$(date +%Y%m%d%H%M%S)"
      echo "✓ uninstalled: $d (old copy kept as ${d}.removed-<ts>, delete it yourself when sure)"
    else
      echo "- not installed: $d"
    fi
  done
  exit 0
fi

# install --------------------------------------------------------------------
SKILL_DIR=""
if ! SKILL_DIR="$(find_skill_dir)"; then
  if [[ -n "$REPO" ]]; then
    TMP="$(mktemp -d)"
    echo "→ cloning $REPO ..."
    if command -v git >/dev/null 2>&1; then
      git clone --depth 1 "$REPO" "$TMP/repo" >/dev/null
    else
      curl -fsSL "$REPO/archive/refs/heads/main.zip" -o "$TMP/repo.zip"
      unzip -q "$TMP/repo.zip" -d "$TMP"
      mv "$TMP"/*-main "$TMP/repo"
    fi
    SKILL_DIR="$TMP/repo/${SKILL_NAME}"
    [[ -f "$SKILL_DIR/SKILL.md" ]] || { echo "ERROR: $SKILL_NAME/SKILL.md not found in $REPO" >&2; exit 1; }
  else
    echo "ERROR: cannot locate ${SKILL_NAME}/SKILL.md next to this script." >&2
    echo "  Run from the repo root, or pass --repo <git-url> (for curl | bash usage)." >&2
    exit 1
  fi
fi

STAMP="$(date +%Y%m%d%H%M%S)"
for t in $TARGETS; do
  dest_root="$(target_path "$t")"
  dest="$dest_root/$SKILL_NAME"
  mkdir -p "$dest_root"
  if [[ -d "$dest" ]]; then
    mv "$dest" "${dest}.bak-${STAMP}"
    echo "· backup: ${dest}.bak-${STAMP}"
  fi
  cp -R "$SKILL_DIR" "$dest"
  echo "✓ installed: $t → $dest"
  echo "    trigger: $(target_hint "$t")"
done

echo
echo "Self-test (offline, no API key needed):"
echo "  cd $(target_path "$(for t in $TARGETS; do echo $t; break; done)")/$SKILL_NAME && python3 scripts/selftest.py"
