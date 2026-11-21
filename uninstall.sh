#!/usr/bin/env bash
set -euo pipefail

OPENCODE_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
for dst in "$OPENCODE_CFG/skills/subagent-bench" "$OPENCODE_CFG/commands/modelcompare.md"; do
  if [ -L "$dst" ]; then
    rm "$dst"
    echo "Removed symlink $dst"
  elif [ -e "$dst" ]; then
    echo "Skipped $dst (not a symlink; remove manually if desired)"
  fi
done
