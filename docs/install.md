---
title: Install NarrateClaude on macOS, Linux and Windows
description: Requirements and install for NarrateClaude, the hands-free voice loop for Claude Code. Covers the one-line installers, whisper.cpp, the f16 models, the Piper voice, permissions and the manual Apple-speech setup.
---

# Install

## Requirements

| Need | Why |
|---|---|
| macOS, Linux, or Windows 10/11 | Terminal.app mode is macOS only; the pty session (`narrate-claude --here`) runs everywhere. |
| A C++ compiler on macOS/Linux (`xcode-select --install`, `build-essential`) | `install.sh` builds whisper.cpp from source. cmake is installed into the venv if it's missing. Windows uses the official binaries. |
| Python 3.9+ (3.10+ on Windows) | The listener, session and Piper voice run in a venv the installer creates. |
| PortAudio on Linux (`libportaudio2`) | The mic library (python-sounddevice). The macOS and Windows wheels bundle it. |
| [Claude Code](https://github.com/anthropics/claude-code), so `claude` is on your PATH | The session runs `claude` itself. |
| A microphone | Built-in is fine. |

Optional:

- [claude-code-local](https://github.com/nicedreamzapp/claude-code-local), so `claude` talks to a model on your machine instead of Anthropic's servers.
- A Python at `~/.local/mlx-server/bin/python` with `mlx_lm` installed, for the relevance judge. See [Configuration](configuration.md#relevance-filter).

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.sh | bash        # macOS, Linux
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.sh | bash -s -- --skip-model
```

```powershell
irm https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.ps1 | iex              # Windows
```

It clones to `~/NarrateClaude` (`NARRATE_DIR`; `NARRATE_REPO` picks the source) and puts the voice loop in `~/.local/share/narrateclaude` (`%LOCALAPPDATA%\narrateclaude` on Windows; `NARRATE_DATA`):

- whisper.cpp v1.9.5: built from the pinned tag with cmake (Metal on Apple Silicon, CUDA when `nvcc` is on PATH, extra flags in `NARRATE_CMAKE_FLAGS`), or the official Windows zip checked by sha256
- a venv with [`dictation/voice/requirements.txt`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/voice/requirements.txt): python-sounddevice, Piper, and pywinpty on Windows
- from [`dictation/voice/models.txt`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/voice/models.txt), each pinned to a commit and checked by sha256: the f16 whisper model for your memory (`large-v3-turbo` at 8 GB or more, `small.en` at 4 to 8 GB, `base.en` below; `NARRATE_WHISPER_MODEL` overrides), Silero VAD v6.2.0 and the Piper voice `en_US-lessac-high`. `--skip-model` (`NARRATE_SKIP_MODEL=1`) downloads none of them.

Then it creates `~/.local/bin/speak` with the Piper voice only if you have no `speak` (marked so uninstall can tell it apart; an older `say` wrapper from this installer is upgraded), links `narrative-claude.sh` as `narrate-claude` in `~/.local/bin` (`KIT_BIN_DIR`; `narrate-claude.cmd` on Windows), and on macOS compiles the optional Apple-speech listener (`NARRATE_SKIP_BUILD=1` builds nothing). It prints the Stop-hook snippet but never edits `~/.claude/settings.json`. Running it again rebuilds and downloads nothing that is already there.

Uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash
# also delete the models and the clone, including dictation/state:
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash -s -- --purge
```

```powershell
irm https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.ps1 | iex   # $env:NARRATE_PURGE = "1" first to purge
```

It runs `dictation stop`, removes the `narrate-claude` link, the installer's `speak`, the compiled listener, whisper.cpp and the venv. Models stay unless you purge.

The steps below are the manual install of the original macOS Terminal.app setup with Apple's speech engine (`narrate-claude --apple`). The repo can live anywhere: `narrative-claude.sh` finds its own folder, following symlinks, and falls back to `$NARRATE_DIR`, then `~/NarrateClaude`, when it was copied out of the repo.

## 1. Clone

```bash
git clone https://github.com/nicedreamzapp/NarrateClaude.git ~/NarrateClaude
cd ~/NarrateClaude
chmod +x dictation/bin/* narrative-claude.sh
```

## 2. Create the speak command

The listener mutes the mic while `afplay` runs, so render speech to a file and play it with `afplay`. Plain `say` would be heard by the mic.

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/speak <<'EOF'
#!/bin/bash
f="${TMPDIR:-/tmp}/speak.$$.aiff"
say -o "$f" "$@" && afplay "$f"
rm -f "$f"
EOF
chmod +x ~/.local/bin/speak
~/.local/bin/speak "testing one two three"
```

To use a cloned voice, replace the script with anything that takes text as its arguments and plays the result through `afplay`. The author uses [Pocket TTS](https://github.com/kyutai-labs/pocket-tts). The repo does not include a Pocket TTS wrapper.

## 3. Compile the listener and bind a window

Open Apple Terminal, start `claude`, then from a second tab or window run:

```bash
~/NarrateClaude/dictation/bin/dictation setup
```

`setup` does three things:

1. Finds the first Terminal window with a tab running `claude` and writes its ID to `dictation/state/target.json`.
2. Compiles `dictation/src/Listen.swift` to `dictation/bin/listen` with `swiftc -O`.
3. Marks `inject`, `listen` and `dictation` executable.

If more than one window runs `claude`, the first match wins. The [one-click launcher](quickstart.md) avoids this by binding to the window it opens itself.

## 4. Grant permissions

The first time the listener runs, macOS asks for **Microphone** and **Speech Recognition** access for Terminal. Approve both. If you missed the prompt, turn them on in **System Settings > Privacy & Security**.

The injector presses Escape and Return through System Events when the bound window is focused, so macOS may also ask to let Terminal control System Events. **TODO-VERIFY:** which exact Automation and Accessibility prompts appear on a clean install.

## 5. Optional: wrap the launcher in an .app

The script header and README describe a minimal bundle so you can start it from the Dock:

```bash
APP=~/Desktop/NarrativeClaude.app
mkdir -p "$APP/Contents/MacOS"
ln -sf ~/NarrateClaude/narrative-claude.sh "$APP/Contents/MacOS/NarrativeClaude"
```

Then add an `Info.plist` with `CFBundleExecutable` set to `NarrativeClaude`. The full plist is in the [README](https://github.com/nicedreamzapp/NarrateClaude#optional-wrap-it-in-a-app-bundle).

## Uninstall (manual install)

```bash
~/NarrateClaude/dictation/bin/dictation uninstall
```

This stops the listener and removes the PID file, `target.json`, and the `dictation.log`, `.stderr` and `.inject` logs. It keeps the compiled binary and does not remove other files in `dictation/state/` (relevance state, `dropped.log`, `relevance.log`, `filter.log`, `voiceprint.npy`). Delete the folder to remove everything.
