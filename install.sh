#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCODE_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
SKILL_SRC="$REPO_DIR/skills/subagent-bench"
SKILL_DST="$OPENCODE_CFG/skills/subagent-bench"
CMD_SRC="$REPO_DIR/commands/modelcompare.md"
CMD_DST="$OPENCODE_CFG/commands/modelcompare.md"

mkdir -p "$OPENCODE_CFG/skills" "$OPENCODE_CFG/commands"

link_item() {
  local src="$1"
  local dst="$2"
  if [ -L "$dst" ]; then
    rm "$dst"
  elif [ -e "$dst" ]; then
    local backup="${dst}.bak.$(date +%Y%m%d%H%M%S)"
    mv "$dst" "$backup"
    echo "Backed up existing $dst -> $backup"
  fi
  ln -s "$src" "$dst"
  echo "Linked $dst -> $src"
}

link_item "$SKILL_SRC" "$SKILL_DST"
link_item "$CMD_SRC" "$CMD_DST"

echo ""
echo "Installed subagent-bench skill and /modelcompare command."
echo "OpenCode V2 discovers changes automatically (run /reload in an open TUI if needed)."
