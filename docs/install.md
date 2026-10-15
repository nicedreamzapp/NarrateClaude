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
| The repo at `~/NarrateClaude` | `narrative-claude.sh` hard-codes `$HOME/NarrateClaude`. |

Optional:

- [claude-code-local](https://github.com/nicedreamzapp/claude-code-local), so `claude` talks to a model on your Mac instead of Anthropic's servers.
- A Python at `~/.local/mlx-server/bin/python` with `mlx_lm` installed, for the relevance judge. See [Configuration](configuration.md#relevance-filter).

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

## Uninstall

```bash
~/NarrateClaude/dictation/bin/dictation uninstall
```

This stops the listener and removes the PID file, `target.json`, and the `dictation.log`, `.stderr` and `.inject` logs. It keeps the compiled binary and does not remove other files in `dictation/state/` (relevance state, `dropped.log`, `relevance.log`, `filter.log`, `voiceprint.npy`). Delete the folder to remove everything.
