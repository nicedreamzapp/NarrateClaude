---
title: Install NarrateClaude on macOS
description: Requirements and step-by-step install for NarrateClaude, the hands-free voice loop for Claude Code. Covers Xcode command-line tools, compiling the Swift listener, permissions and the speak command.
---

# Install

## Requirements

These come from what the scripts actually call.

| Need | Why |
|---|---|
| A Mac with Apple Silicon | The dispatcher runs the optional voiceprint filter with `/usr/bin/arch -arm64`. The README targets M1 and later. |
| Xcode command-line tools (`xcode-select --install`) | `dictation setup` compiles the listener with `/usr/bin/swiftc`. The scripts also call `/usr/bin/python3`. |
| Apple's Terminal.app | Window binding and typing use Terminal's AppleScript dictionary. Other terminals do not work yet. |
| [Claude Code](https://github.com/anthropics/claude-code), so `claude` runs in Terminal | `dictation setup` looks for a Terminal tab whose processes include `claude`. |
| A microphone | Built-in is fine. |
| English speech | The recognizer is created with `Locale(identifier: "en-US")`. |
| A program at `~/.local/bin/speak` that plays audio with `afplay` | The listener pauses only while a process named `afplay` exists. |

Optional:

- [claude-code-local](https://github.com/nicedreamzapp/claude-code-local), so `claude` talks to a model on your Mac instead of Anthropic's servers.
- A Python at `~/.local/mlx-server/bin/python` with `mlx_lm` installed, for the relevance judge. See [Configuration](configuration.md#relevance-filter).

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.sh | bash
```

It clones to `~/NarrateClaude` (`NARRATE_DIR`; `NARRATE_REPO` picks the source), runs `chmod +x`, creates the starter `~/.local/bin/speak` from step 2 only if you have no `speak` (marked so uninstall can tell it apart), links `narrative-claude.sh` as `narrate-claude` in `~/.local/bin` (`KIT_BIN_DIR`), and compiles the listener with the same `swiftc -O` command `dictation setup` uses (`NARRATE_SKIP_BUILD=1` skips it). Window binding is left to the launcher, so no `claude` window is needed. It prints the Stop-hook snippet but never edits `~/.claude/settings.json`. Then grant the permissions in step 4.

Uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash
# also delete the clone, including dictation/state:
curl -fsSL https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.sh | bash -s -- --purge
```

It runs `dictation stop` and removes the `narrate-claude` link, the installer's `speak` and the compiled listener.

The steps below are the manual install. The repo can live anywhere: `narrative-claude.sh` finds its own folder, following symlinks, and falls back to `$NARRATE_DIR`, then `~/NarrateClaude`, when it was copied out of the repo.

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
