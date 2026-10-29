#!/usr/bin/env bash
# NarrateClaude installer (macOS and Linux; Windows uses install.ps1).
#
#   curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --skip-model     (no model downloads)
#   bash ~/NarrateClaude/install.sh [--skip-model]          (from a checkout)
#
# Clones the repo (or uses the checkout this script sits in) and sets up the
# local, open-source voice loop under NARRATE_DATA:
#   - a Python venv with the mic library and Piper TTS (voice/requirements.txt)
#   - whisper.cpp, built from source at a pinned release (Metal on Apple Silicon)
#   - the f16 whisper model that fits this machine's memory, Silero VAD and a
#     Piper voice, all pinned by URL + sha256 (voice/models.txt)
# Creates ~/.local/bin/speak (the Piper voice) only if you have no speak yet,
# links `narrate-claude` into ~/.local/bin and, on macOS, compiles the optional
# Apple-speech listener. It never edits ~/.claude/settings.json and never
# starts the microphone.
#
# Environment (all optional):
#   NARRATE_REPO          git URL or local path to clone (default GitHub)
#   NARRATE_DIR           where to clone (default ~/NarrateClaude)
#   NARRATE_DATA          whisper.cpp, models, venv (default ~/.local/share/narrateclaude)
#   NARRATE_WHISPER_MODEL large-v3-turbo | small.en | base.en | tiny.en (default: by RAM)
#   NARRATE_SKIP_MODEL    1 = same as --skip-model
#   NARRATE_SKIP_BUILD    1 = build nothing (no whisper.cpp, no Swift listener)
#   NARRATE_PYTHON        Python 3.9+ for the venv (default: newest python3 found)
#   NARRATE_CMAKE_FLAGS   extra cmake flags for whisper.cpp (e.g. -DGGML_VULKAN=1)
#   KIT_BIN_DIR           where narrate-claude is linked (default ~/.local/bin)

set -euo pipefail

SPEAK_MARKER="# speak wrapper installed by NarrateClaude install.sh"
WHISPER_TAG="v1.9.5"
WHISPER_COMMIT="d1be6fde11ac6e0407606b4e42fe72d34add8037"
WHISPER_URL="https://github.com/ggml-org/whisper.cpp"

main() {
  local skip_model="${NARRATE_SKIP_MODEL:-0}" arg
  for arg in "$@"; do
    case "$arg" in
      --skip-model) skip_model=1 ;;
      *) die "usage: install.sh [--skip-model]" ;;
    esac
  done
  local repo="${NARRATE_REPO:-https://github.com/nicedreamzapp/NarrateClaude}"
  local dir="${NARRATE_DIR:-$HOME/NarrateClaude}"
  local bindir="${KIT_BIN_DIR:-$HOME/.local/bin}"
  local speak="$HOME/.local/bin/speak"
  local data="${NARRATE_DATA:-$HOME/.local/share/narrateclaude}"
  local os
  os="$(uname -s)"
  case "$os" in
    Darwin|Linux) ;;
    *) die "this installer is for macOS and Linux; on Windows run install.ps1" ;;
  esac
  command -v git >/dev/null || die "git is required"
  command -v curl >/dev/null || die "curl is required"

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

  # 2. The voice loop: venv, whisper.cpp, models.
  mkdir -p "$data/models"
  data="$(cd "$data" && pwd -P)"
  setup_venv "$src" "$data"
  if [ "${NARRATE_SKIP_BUILD:-0}" = 1 ]; then
    say "NARRATE_SKIP_BUILD=1: not building whisper.cpp"
  else
    build_whisper "$data" "$os"
  fi
  if [ "$skip_model" = 1 ]; then
    say "--skip-model: not downloading models (re-run without it to fetch them)"
  else
    local model="${NARRATE_WHISPER_MODEL:-}"
    if [ -z "$model" ]; then
      model="$("$data/venv/bin/python" -c 'import sys; sys.path.insert(0, sys.argv[1]); import common; print(common.model_for_ram(common.total_ram_gib()))' "$src/dictation/voice")"
    fi
    say "speech model: $model (full precision f16)"
    fetch_model "$src" "$data" "$model"
    fetch_model "$src" "$data" silero-vad
    fetch_model "$src" "$data" piper-voice-config
    fetch_model "$src" "$data" piper-voice
  fi

  # 3. The voice: only if there is no speak already. An older wrapper from
  #    this installer (it carries the marker line) is upgraded to Piper.
  if [ -e "$speak" ] && ! grep -qF "$SPEAK_MARKER" "$speak" 2>/dev/null; then
    say "keeping your existing $speak"
  elif [ ! -e "$speak" ] && command -v speak >/dev/null 2>&1; then
    say "keeping your existing speak ($(command -v speak))"
    say "note: CLAUDE.md and speak-on-stop call $speak; link it there if needed"
  else
    mkdir -p "$(dirname "$speak")"
    cat > "$speak" <<EOF
#!/bin/bash
$SPEAK_MARKER
# The local Piper voice. Replace this file with your own TTS any time.
export NARRATE_DATA="$data"
exec "$src/dictation/bin/narrate-speak" "\$@"
EOF
    chmod +x "$speak"
    say "created $speak (Piper voice, local; replace it with any TTS you like)"
  fi

  # 4. The launcher on PATH.
  mkdir -p "$bindir"
  local link="$bindir/narrate-claude"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    mv "$link" "$link.pre-kit"
    say "moved existing $link to $link.pre-kit"
  fi
  ln -sfn "$src/narrative-claude.sh" "$link"

  # 5. macOS only: the optional Apple-speech listener (narrate-claude --apple).
  #    Compiled directly; `dictation setup` would also need a Terminal window.
  local swift_src="$src/dictation/src/Listen.swift" listen="$src/dictation/bin/listen"
  if [ "$os" != Darwin ] || [ "${NARRATE_SKIP_BUILD:-0}" = 1 ]; then
    :
  elif [ ! -x /usr/bin/swiftc ]; then
    say "note: no swiftc, skipping the optional Apple-speech listener"
  elif [ -x "$listen" ] && [ "$listen" -nt "$swift_src" ]; then
    say "Apple-speech listener already compiled"
  else
    say "compiling the optional Apple-speech listener..."
    /usr/bin/swiftc -O "$swift_src" -o "$listen" || say "warning: swiftc failed; whisper.cpp still works"
    [ -f "$listen" ] && chmod +x "$listen"
  fi

  cat <<EOF

NarrateClaude installed in $src (voice loop in $data)
  Start it:  narrate-claude          macOS: opens Apple Terminal running claude, then listens
             narrate-claude --here   any terminal, macOS or Linux: claude runs inside the loop

Speech to text is whisper.cpp running on this machine; nothing leaves it.
The first run asks for Microphone access for your terminal app; approve it.
On macOS, Terminal may also ask to control System Events (it presses Return).

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

# --- voice loop pieces -------------------------------------------------------

pick_python() {
  local c v
  for c in "${NARRATE_PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
    if [ -z "$c" ] || ! command -v "$c" >/dev/null 2>&1; then continue; fi
    v="$("$c" -c 'import sys; print(int(sys.version_info >= (3, 9)))' 2>/dev/null)" || continue
    if [ "$v" = 1 ]; then command -v "$c"; return 0; fi
  done
  return 1
}

setup_venv() {
  local src="$1" data="$2" py req="$1/dictation/voice/requirements.txt" stamp="$2/venv/.requirements"
  if [ -x "$data/venv/bin/python" ] && [ -f "$stamp" ] && cmp -s "$req" "$stamp"; then
    say "voice packages already installed"
    return 0
  fi
  py="$(pick_python)" || die "Python 3.9+ is required (python3)"
  say "installing voice packages (Piper, mic) into $data/venv ..."
  [ -x "$data/venv/bin/python" ] || "$py" -m venv "$data/venv" ||
    die "could not create a venv with $py (Debian/Ubuntu: sudo apt install python3-venv)"
  "$data/venv/bin/python" -m pip install -q --disable-pip-version-check -r "$req" || die "pip install failed"
  cp "$req" "$stamp"
  if [ "$(uname -s)" = Linux ] && ! "$data/venv/bin/python" -c 'import sounddevice' >/dev/null 2>&1; then
    say "note: the mic needs PortAudio: sudo apt install libportaudio2 (or your distro's portaudio)"
  fi
}

build_whisper() {
  local data="$1" os="$2" dir="$1/whisper.cpp" cmake jobs flags=() extra=()
  local bin="$dir/build/bin/whisper-server" stamp="$dir/build/.narrate-commit"
  if [ -x "$bin" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$WHISPER_COMMIT" ]; then
    say "whisper.cpp $WHISPER_TAG already built"
    return 0
  fi
  if [ ! -d "$dir/.git" ]; then
    rm -rf "$dir"
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$WHISPER_TAG" "$WHISPER_URL" "$dir" ||
      die "could not clone whisper.cpp"
  elif [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" != "$WHISPER_COMMIT" ]; then
    { git -C "$dir" fetch -q --depth 1 origin tag "$WHISPER_TAG" &&
      git -C "$dir" -c advice.detachedHead=false checkout -q "$WHISPER_TAG"; } || die "could not update whisper.cpp"
  fi
  [ "$(git -C "$dir" rev-parse HEAD)" = "$WHISPER_COMMIT" ] || die "whisper.cpp $WHISPER_TAG is not the pinned commit"
  cmake="$(command -v cmake || true)"
  if [ -z "$cmake" ]; then
    say "no cmake on PATH, installing one into the venv"
    "$data/venv/bin/python" -m pip install -q --disable-pip-version-check cmake || die "could not install cmake"
    cmake="$data/venv/bin/cmake"
  fi
  command -v c++ >/dev/null 2>&1 || command -v g++ >/dev/null 2>&1 || command -v clang++ >/dev/null 2>&1 ||
    die "a C++ compiler is required (macOS: xcode-select --install; Linux: build-essential)"
  flags=(-DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF
         -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_SDL2=OFF -DWHISPER_CURL=OFF)
  if [ "$os" = Linux ] && command -v nvcc >/dev/null 2>&1; then
    flags+=(-DGGML_CUDA=1)
    say "CUDA found, building whisper.cpp with GPU support"
  fi
  if [ -n "${NARRATE_CMAKE_FLAGS:-}" ]; then
    read -r -a extra <<< "$NARRATE_CMAKE_FLAGS"
    flags+=("${extra[@]}")
  fi
  jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
  local gpu=""
  [ "$os" = Darwin ] && [ "$(uname -m)" = arm64 ] && gpu=" with Metal"
  say "building whisper.cpp $WHISPER_TAG$gpu (a few minutes)..."
  "$cmake" -S "$dir" -B "$dir/build" "${flags[@]}" >"$dir/build.log" 2>&1 ||
    die "cmake configure failed, see $dir/build.log"
  "$cmake" --build "$dir/build" --config Release -j "$jobs" --target whisper-server >>"$dir/build.log" 2>&1 ||
    die "whisper.cpp build failed, see $dir/build.log"
  [ -x "$bin" ] || die "build finished but $bin is missing"
  echo "$WHISPER_COMMIT" > "$stamp"
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

fetch_model() {
  local src="$1" data="$2" want="$3" name sum rel url dest
  while read -r name sum rel url; do
    case "$name" in ''|'#'*) continue ;; esac
    [ "$name" = "$want" ] || continue
    dest="$data/models/$rel"
    if [ -f "$dest" ] && [ "$(sha256 "$dest")" = "$sum" ]; then
      say "have $rel"
      return 0
    fi
    mkdir -p "$(dirname "$dest")"
    say "downloading $rel ..."
    curl -fL --retry 3 -sS -o "$dest.part" "$url" || { rm -f "$dest.part"; die "download failed: $url"; }
    [ "$(sha256 "$dest.part")" = "$sum" ] || { rm -f "$dest.part"; die "checksum mismatch for $rel"; }
    mv "$dest.part" "$dest"
    return 0
  done < "$src/dictation/voice/models.txt"
  die "unknown model '$want' (see dictation/voice/models.txt)"
}

say() { printf 'NarrateClaude: %s\n' "$*"; }
die() { printf 'NarrateClaude: ERROR: %s\n' "$*" >&2; exit 1; }
is_checkout() {
  [ -f "$1/narrative-claude.sh" ] && [ -f "$1/dictation/bin/dictation" ] &&
    git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

main "$@"
