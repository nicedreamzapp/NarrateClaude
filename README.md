<p align="center">
  <h1 align="center">🎤 NarrateClaude — Hands-Free, On-Device, In Your Own Voice</h1>
  <p align="center">
    <strong>Speak to Claude Code. Hear it narrate back in your own cloned voice.<br>Both sides of the voice loop run 100% on your Mac. Nothing leaves the box.</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/🎙️_STT-Apple_SFSpeechRecognizer-blue?style=for-the-badge" alt="Apple STT">
    <img src="https://img.shields.io/badge/🔊_TTS-Your_Cloned_Voice-orange?style=for-the-badge" alt="Cloned TTS">
    <img src="https://img.shields.io/badge/🔒_Privacy-100%25_Local-success?style=for-the-badge" alt="100% Local">
    <img src="https://img.shields.io/badge/🍎_Platform-macOS_arm64-lightgrey?style=for-the-badge" alt="macOS">
    <a href="LICENSE"><img src="https://img.shields.io/badge/📜_License-MIT-yellow?style=for-the-badge" alt="MIT"></a>
  </p>
</p>

---

## 🤔 What Is This?

A continuous on-device dictation pipeline for macOS that pipes your voice into a target Terminal window and listens for the reply to be spoken back through `afplay`. It was built to give [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) a fully hands-free voice loop — speak a question, hear Gemma narrate the plan, hear it confirm the result, keep talking — but the listening side is general-purpose and could drive **any** CLI, not just Claude Code.

Most "voice AI" demos online use cloud STT (Whisper API, Deepgram) and cloud TTS (ElevenLabs cloud, OpenAI). This doesn't. Apple's `SFSpeechRecognizer` — the on-device engine that powers macOS Dictation — is a first-class macOS API, and this project wraps it in a continuous-listen Swift daemon with production hardening (wedge detection, preventive process recycling, feedback-loop prevention) so you can actually hold long conversations with it without the listener falling over.

**No network calls in the voice path. On a plane, in a Faraday cage, on a disconnected-by-policy client machine — it still works.**

---

## 🔁 The Voice Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR MACBOOK (M-series)                     │
│                                                                 │
│    🎙️  Your voice                                               │
│         │                                                       │
│         ▼                                                       │
│    🎧 listen  (Swift binary, built from src/Listen.swift)       │
│       • Apple SFSpeechRecognizer — on-device engine             │
│       • Continuous listening, stability-based end-of-utterance  │
│       • Auto-pauses during afplay playback (no feedback loops)  │
│       • Wedge-detection watchdog + 10-min preventive recycle    │
│         │                                                       │
│         ▼                                                       │
│    📬 dispatch  (bash watchdog + respawn supervisor)            │
│         │                                                       │
│         ▼                                                       │
│    ⌨️  inject  (AppleScript → target Terminal window by id)     │
│         │                                                       │
│         ▼                                                       │
│    🤖 claude  (narration persona loaded from CLAUDE.md)         │
│         │                                                       │
│         ▼                                                       │
│    ⚡ whatever CLI you've bound it to                           │
│       (claude-code-local → local MLX + Gemma 4 31B by default)  │
│         │                                                       │
│         ▼                                                       │
│    🔊 ~/.local/bin/speak  "naturally phrased reply"             │
│       • Your TTS of choice (cloned voice, Piper, macOS say)     │
│         │                                                       │
│         ▼                                                       │
│    🎵 afplay  (listen pauses itself during this)                │
│         │                                                       │
│         ▼                                                       │
│    👂 You hear it                                               │
│         │                                                       │
│         └──────────────► and you keep talking                   │
│                                                                 │
│           🔒 Your voice never leaves this box. Ever.            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Install

### Prerequisites
- **macOS 12+** on Apple Silicon
- **Xcode command-line tools** (for `swiftc`): `xcode-select --install`
- **Microphone + Speech Recognition permission for Terminal** (you'll be prompted the first time you run `listen` — approve both)
- A target CLI you want to control by voice. If you're here for Claude Code, install [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) too.
- A TTS CLI at `~/.local/bin/speak` that takes a string and plays audio. Simplest stub:
  ```bash
  mkdir -p ~/.local/bin
  cat > ~/.local/bin/speak <<'SPEAK'
  #!/bin/bash
  say "$@"
  SPEAK
  chmod +x ~/.local/bin/speak
  ```
  (Replaces `say` with Piper, a cloned-voice model, ElevenLabs-local, or whatever you prefer.)

### Clone and build
```bash
git clone https://github.com/nicedreamzapp/NarrateClaude.git ~/NarrateClaude
cd ~/NarrateClaude

# Make everything executable
chmod +x dictation/bin/dictation dictation/bin/dispatch dictation/bin/inject narrative-claude.sh

# Compile the Swift listener. The `dictation setup` subcommand handles this
# AND binds to whichever Terminal window is currently running `claude`.
# Run it from INSIDE the Terminal window you want the listener to talk to:
./dictation/bin/dictation setup
```

`setup` does two things: compiles `src/Listen.swift` into `bin/listen` using `swiftc -O`, and captures the Terminal window ID of the currently running `claude` session so the injector knows where to paste.

---

## 🚀 Run

### Option A — one-shot launcher (recommended)

```bash
bash ~/NarrateClaude/narrative-claude.sh
```

This opens a new Terminal window running `claude`, captures its window ID, waits for the banner, then starts the listener. When you close the Terminal window, the dispatch watchdog notices within ~5 seconds and shuts the listener down automatically.

### Option B — manual control

```bash
~/NarrateClaude/dictation/bin/dictation setup    # bind to the current claude session
~/NarrateClaude/dictation/bin/dictation start    # start the listener
~/NarrateClaude/dictation/bin/dictation tail     # watch transcripts
~/NarrateClaude/dictation/bin/dictation stop     # stop the listener
~/NarrateClaude/dictation/bin/dictation toggle   # flip on / off
```

> 🔒 **Start is gated.** `dictation start` refuses to run unless it's called with `NARRATE_DICTATION_LAUNCHER` set to an authorized launcher name (`NarrativeClaude.app` or `Narrative Gemma.command` by default). This stops random processes or typos from spinning up the mic unintentionally. Edit the gate in `dictation/bin/dictation` if you want a different authorized launcher name.

### Option C — wrap it in a `.app` bundle

If you want a Dock-friendly double-clickable icon:

```bash
mkdir -p ~/Desktop/NarrativeClaude.app/Contents/MacOS
ln -sf ~/NarrateClaude/narrative-claude.sh \
  ~/Desktop/NarrativeClaude.app/Contents/MacOS/NarrativeClaude
cat > ~/Desktop/NarrativeClaude.app/Contents/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>          <string>com.you.narrativeclaude</string>
    <key>CFBundleName</key>                <string>Narrative Claude</string>
    <key>CFBundleDisplayName</key>         <string>Narrative Claude</string>
    <key>CFBundleExecutable</key>          <string>NarrativeClaude</string>
    <key>CFBundleVersion</key>             <string>1.0</string>
    <key>CFBundleShortVersionString</key>  <string>1.0</string>
    <key>CFBundlePackageType</key>         <string>APPL</string>
    <key>NSHighResolutionCapable</key>     <true/>
    <key>LSMinimumSystemVersion</key>      <string>12.0</string>
</dict>
</plist>
PLIST
```

Drop a `.icns` at `Contents/Resources/AppIcon.icns` and add `CFBundleIconFile = AppIcon` to the plist if you want a custom icon.

---

## 🎭 The Narration Persona

`CLAUDE.md` at the repo root is the persona file designed to be injected as a Claude Code system prompt (via `--append-system-prompt-file` or equivalent). It enforces **speak-every-turn**: the model narrates every tool call, every reasoning step, every result out loud through `~/.local/bin/speak` before writing the text reply. You're never staring at a silent terminal wondering if it's thinking.

The [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) project includes a `Narrative Gemma.command` launcher that boots a local Gemma 4 31B MLX model and injects this persona automatically. If you're running a different model or a different CLI, point your own system-prompt mechanism at this file.

---

## 🏗️ Architecture Notes

### Why stability-based utterance detection

The naive approach is to detect end-of-utterance via RMS silence: "if the mic energy stays below a threshold for N seconds, the user is done talking." That breaks the moment you have a fan, HVAC, music, or any consistent background noise above the threshold. `Listen.swift` instead watches the **partial transcription result** — if `SFSpeechRecognizer` has been returning the same text for 2.5 seconds (configurable via `LISTEN_STABILITY_SEC`), it calls `endAudio()` to force the recognizer to finalize the current utterance. Stability detection works regardless of background noise level.

### Why the feedback-loop pause

`~/.local/bin/speak` plays its output through `afplay`, which means the model's own spoken reply hits the speakers, bounces around the room, and gets picked up by the mic as "input" — a feedback loop where the model ends up transcribing itself. The listener watches for a running `afplay` process and pauses speech recognition while one exists, resuming the moment playback stops.

### Why the wedge-detection watchdog

`SFSpeechRecognizer` talks to `speechd` (Apple's speech daemon) via XPC. Under certain conditions the sync XPC call into `speechd` can hang — the daemon accepts audio buffers but never returns a transcription callback. The listener watches the audio-buffer queue depth; if it grows above `LISTEN_WEDGE_BACKLOG` (default 200 buffers, ~4-5 seconds) with no progress, the process exits with code 99. The `dispatch` supervisor sees the exit and restarts a fresh listener — loop recovered.

### Why the 10-minute preventive recycle

Even without wedging, long-running `SFSpeechRecognizer` sessions sometimes degrade (occasional dropped utterances, slower finalization). `LISTEN_MAX_SESSION_SEC` (default 600) forces a clean exit every 10 minutes regardless of health, and `dispatch` respawns a fresh listener. The transition is seamless because each `listen` process exits cleanly and the watchdog window on the bound target is continuous across respawns.

### Environment variable overrides

All tunables in `Listen.swift` are env-overridable:

| Env var | Default | Purpose |
|---|---:|---|
| `LISTEN_STABILITY_SEC` | 2.5 | How long partial text must be unchanged before finalizing an utterance |
| `LISTEN_MAX_UTTER_SEC` | 60.0 | Hard cap on a single utterance length |
| `LISTEN_MAX_SESSION_SEC` | 600.0 | Preventive process recycle interval (seconds) |
| `LISTEN_WEDGE_BACKLOG` | 200 | Audio buffer backlog that triggers a wedge exit |
| `LISTEN_DEBUG` | `0` | Set to `1` for verbose diagnostic logging to stderr |

---

## 🧪 Diagnostics

If something's not working:

```bash
# Mic probe — confirms audio is reaching the process at all
cd dictation/src
swiftc -O MicProbe.swift -o /tmp/micprobe
/tmp/micprobe
# Say "HELLO HELLO HELLO" loudly. You should see non-zero RMS readings.
```

```bash
# Tail the live dictation log
~/NarrateClaude/dictation/bin/dictation tail
```

```bash
# Check process state + bound window
~/NarrateClaude/dictation/bin/dictation status
```

Common failure modes:
- **"Speech recognition not authorized"** — open System Settings → Privacy & Security → Speech Recognition and enable Terminal (and/or whichever app is running `listen`). Also Privacy & Security → Microphone. Both are required.
- **"couldn't find a Terminal window running 'claude'"** on `dictation setup` — make sure you're running Claude Code in Apple's Terminal.app (not iTerm, not Warp — the injector uses Terminal-specific AppleScript). Then re-run `dictation setup` from inside that window.
- **Listener exits immediately and respawns in a loop** — check `dictation/state/dictation.log.stderr` for the actual error. Most common cause is missing Microphone or Speech Recognition permission for the parent process.

---

## 🤝 Contributing

Ideas and PRs welcome, especially around:

- **Alternative TTS backends** — recipes for Piper, MLX-TTS, local ElevenLabs, Kyutai Moshi, or any other offline synthesizer that slots cleanly into `~/.local/bin/speak`
- **Non-Terminal targets** — right now `inject` writes into Apple Terminal specifically. iTerm2, Ghostty, Alacritty, or a generic "active text field" injector would open up a lot more use cases
- **Continuous-listen improvements** — different stability heuristics, interruption detection (listen again as soon as the TTS stops, even mid-sentence), confidence-score gating
- **Porting `listen.swift` to other STT engines** while keeping the rest of the pipeline unchanged (Whisper.cpp locally, MLX-Whisper, etc.)

Open an issue or a PR. Real bug reports with `dictation/state/dictation.log` attached are especially useful.

---

## 🔗 Related

- [**claude-code-local**](https://github.com/nicedreamzapp/claude-code-local) — the local-AI stack this voice pipeline was originally built for. Runs Claude Code against a local MLX server (Gemma / Llama / Qwen) with zero cloud calls. Its `Narrative Gemma.command` launcher boots the model side of the voice loop.
- [**browser-agent**](https://github.com/nicedreamzapp/browser-agent) — a separate sibling project that drives a real Brave browser via Chrome DevTools Protocol using the same local MLX server.

---

## 🙏 Credits

- 🍎 **Apple** — `SFSpeechRecognizer` is a surprisingly good on-device speech recognizer that's been shipping with macOS for years and is underused in local-first AI projects
- 🎤 **Pocket TTS** — the cloned-voice synthesizer on the output side (any compatible TTS works)
- 🧠 **Claude Code + claude-code-local** — the model this voice loop was built to talk to

---

<p align="center">
  <strong>📜 MIT License</strong> — Use it however you want.<br><br>
  ⭐ <strong>Star this repo if it helped you talk to your Mac instead of typing at it.</strong> ⭐
</p>
