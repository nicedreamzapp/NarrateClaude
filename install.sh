#!/usr/bin/env bash
# NarrateClaude installer (macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.sh | bash
#   bash ~/NarrateClaude/install.sh        (from a checkout)
#
# Clones the repo (or uses the checkout this script sits in), makes the scripts
# executable, creates ~/.local/bin/speak (a say -> afplay wrapper) only if you
# have no speak yet, links `narrate-claude` (the one-click launcher) into
# ~/.local/bin and compiles the Swift listener. It never edits
# ~/.claude/settings.json and never starts the microphone.
#
# Environment (all optional):
#   NARRATE_REPO        git URL or local path to clone (default GitHub)
#   NARRATE_DIR         where to clone (default ~/NarrateClaude)
#   KIT_BIN_DIR         where narrate-claude is linked (default ~/.local/bin)
#   NARRATE_SKIP_BUILD  1 = do not compile the listener

set -euo pipefail

SPEAK_MARKER="# speak wrapper installed by NarrateClaude install.sh"

main() {
  local repo="${NARRATE_REPO:-https://github.com/nicedreamzapp/NarrateClaude}"
  local dir="${NARRATE_DIR:-$HOME/NarrateClaude}"
  local bindir="${KIT_BIN_DIR:-$HOME/.local/bin}"
  local speak="$HOME/.local/bin/speak"

  [ "$(uname -s)" = "Darwin" ] || die "NarrateClaude needs macOS (Apple Terminal, Speech framework)"
  command -v git >/dev/null || die "git is required"

  # 1. Checkout: the one this script lives in, else clone / update NARRATE_DIR.
  local self="${BASH_SOURCE[0]:-}" src=""
  if [ -n "$self" ] && [ -f "$self" ]; then
    self="$(cd "$(dirname "$self")" && pwd -P)"
    is_checkout "$self" && src="$self"
  fi
  if [ -z "$src" ]; then
    if is_checkout "$dir"; then
      if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
        say "local edits in $dir, skipping update"
      else
        git -C "$dir" pull --ff-only -q || say "warning: could not update $dir, using it as is"
      fi
    elif [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
      die "$dir exists and is not a NarrateClaude checkout; set NARRATE_DIR"
    else
      mkdir -p "$(dirname "$dir")"
      git clone -q "$repo" "$dir" || die "git clone $repo failed"
    fi
    src="$(cd "$dir" && pwd -P)"
  fi
  chmod +x "$src"/dictation/bin/* "$src/narrative-claude.sh"

  # 2. The voice: only if there is no speak already.
  if [ -e "$speak" ]; then
    say "keeping your existing $speak"
  elif command -v speak >/dev/null 2>&1; then
    say "keeping your existing speak ($(command -v speak))"
    say "note: CLAUDE.md and speak-on-stop call $speak; link it there if needed"
  else
    mkdir -p "$(dirname "$speak")"
    cat > "$speak" <<EOF
#!/bin/bash
$SPEAK_MARKER
# Render to a file and play it with afplay: the listener only mutes the
# mic while afplay is running, so plain \`say\` would hear itself.
f="\${TMPDIR:-/tmp}/speak.\$\$.aiff"
say -o "\$f" "\$@" && afplay "\$f"
rm -f "\$f"
EOF
    chmod +x "$speak"
    say "created $speak (macOS voice; replace it with any TTS that plays through afplay)"
  fi

  # 3. The launcher on PATH.
  mkdir -p "$bindir"
  local link="$bindir/narrate-claude"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    mv "$link" "$link.pre-kit"
    say "moved existing $link to $link.pre-kit"
  fi
  ln -sfn "$src/narrative-claude.sh" "$link"

  # 4. Compile the listener directly (`dictation setup` would also need a
  #    Terminal window already running claude; the launcher binds its own).
  local swift_src="$src/dictation/src/Listen.swift" listen="$src/dictation/bin/listen"
  if [ "${NARRATE_SKIP_BUILD:-0}" = 1 ]; then
    say "NARRATE_SKIP_BUILD=1: not compiling the listener"
  elif [ ! -x /usr/bin/swiftc ]; then
    say "warning: /usr/bin/swiftc not found; run xcode-select --install, then re-run this installer"
  elif [ -x "$listen" ] && [ "$listen" -nt "$swift_src" ]; then
    say "listener already compiled"
  else
    say "compiling the listener..."
    /usr/bin/swiftc -O "$swift_src" -o "$listen" || die "swiftc failed"
    chmod +x "$listen"
  fi

  cat <<EOF

NarrateClaude installed in $src
  Start it:  narrate-claude   (opens Apple Terminal running claude, then listens)

Permissions: the first run asks for Microphone and Speech Recognition for
Terminal; approve both (System Settings > Privacy & Security). Terminal may
also ask to control System Events, which the injector uses to press Return.

Optional, read every reply aloud: add this Stop hook to ~/.claude/settings.json
yourself, then turn it on with  touch ~/.claude/narration.on  (rm to turn off).
CLAUDE.md already narrates inside the launcher's session, so use one or the other.

  {
    "hooks": {
      "Stop": [
        { "hooks": [ { "type": "command", "command": "$src/dictation/bin/speak-on-stop" } ] }
      ]
    }
  }

EOF
  case ":$PATH:" in
    *":$bindir:"*) ;;
    *) say "add $bindir to your PATH to use narrate-claude" ;;
  esac
  say "done"
  say "uninstall: curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash"
}

say() { printf 'NarrateClaude: %s\n' "$*"; }
die() { printf 'NarrateClaude: ERROR: %s\n' "$*" >&2; exit 1; }
is_checkout() {
  [ -f "$1/narrative-claude.sh" ] && [ -f "$1/dictation/bin/dictation" ] &&
    git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

main "$@"
