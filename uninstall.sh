#!/usr/bin/env bash
# NarrateClaude uninstaller (macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash -s -- --purge
#   bash ~/NarrateClaude/uninstall.sh [--purge]
#
# Stops the listener (`dictation stop`), removes the narrate-claude link (only
# if it points into the checkout), the ~/.local/bin/speak wrapper (only if the
# installer wrote it) and the compiled listener. --purge also deletes the clone
# in NARRATE_DIR, including dictation/state. Never touches ~/.claude.
# Same environment variables as install.sh.

set -euo pipefail

SPEAK_MARKER="# speak wrapper installed by NarrateClaude install.sh"

main() {
  local purge=0 arg
  for arg in "$@"; do
    case "$arg" in
      --purge) purge=1 ;;
      *) echo "usage: uninstall.sh [--purge]" >&2; return 1 ;;
    esac
  done

  local dir="${NARRATE_DIR:-$HOME/NarrateClaude}"
  local bindir="${KIT_BIN_DIR:-$HOME/.local/bin}"
  local speak="$HOME/.local/bin/speak"
  local link="$bindir/narrate-claude"

  # Checkouts the install may have used: this script's own, the one the
  # launcher link points at, and NARRATE_DIR.
  local srcs=() self="${BASH_SOURCE[0]:-}" d target=""
  if [ -n "$self" ] && [ -f "$self" ]; then
    self="$(cd "$(dirname "$self")" && pwd -P)"
    [ -f "$self/narrative-claude.sh" ] && srcs+=("$self")
  fi
  if [ -L "$link" ]; then
    target="$(readlink "$link")"
    case "$target" in */narrative-claude.sh) srcs+=("$(dirname "$target")") ;; esac
  fi
  [ -d "$dir" ] && srcs+=("$(cd "$dir" && pwd -P)")
  srcs+=("$dir")

  # 1. Stop the listener and drop the compiled binary.
  for d in ${srcs[@]+"${srcs[@]}"}; do
    if [ -x "$d/dictation/bin/dictation" ]; then
      "$d/dictation/bin/dictation" stop >/dev/null 2>&1 || true
    fi
    if [ -f "$d/dictation/bin/listen" ]; then
      rm -f "$d/dictation/bin/listen"
      say "removed $d/dictation/bin/listen"
    fi
  done

  # 2. The launcher link, only if it points into one of our checkouts.
  if [ -n "$target" ]; then
    for d in ${srcs[@]+"${srcs[@]}"}; do
      if [ "$target" = "$d/narrative-claude.sh" ]; then
        rm -f "$link"
        say "removed $link"
        break
      fi
    done
  fi

  # 3. speak, only if the installer wrote it.
  if [ -f "$speak" ] && grep -qF "$SPEAK_MARKER" "$speak"; then
    rm -f "$speak"
    say "removed $speak"
  fi

  # 4. --purge: the clone (state included).
  if [ "$purge" = 1 ]; then
    if [ -f "$dir/narrative-claude.sh" ] && [ -d "$dir/dictation" ]; then
      rm -rf "$dir"
      say "removed $dir"
    fi
    if [ -n "$self" ] && [ -f "$self/narrative-claude.sh" ]; then
      say "left the checkout you ran this from: $self"
    fi
  fi
  say "uninstalled"
}

say() { printf 'NarrateClaude: %s\n' "$*"; }

main "$@"
