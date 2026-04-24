<p align="center">
  <h1 align="center">🎤 NarrateClaude</h1>
  <h3 align="center">Talk to your Mac. It talks back. In your own voice. Zero internet.</h3>
  <p align="center"><em>🪴 Step one of an ambient-computing journey. Work while playing. The keyboard is optional.</em></p>
  <p align="center">
    <a href="https://github.com/nicedreamzapp/NarrateClaude/stargazers"><img src="https://img.shields.io/github/stars/nicedreamzapp/NarrateClaude?style=for-the-badge&logo=github&color=f5c542&labelColor=1f2328" alt="GitHub stars"></a>
    <a href="https://github.com/sponsors/nicedreamzapp"><img src="https://img.shields.io/github/sponsors/nicedreamzapp?style=for-the-badge&logo=githubsponsors&color=ea4aaa&labelColor=1f2328&label=%E2%9D%A4%20Sponsor" alt="Sponsor"></a>
    <img src="https://img.shields.io/badge/🎙️_Speak-To_Your_Mac-orange?style=for-the-badge" alt="Speak">
    <img src="https://img.shields.io/badge/🔊_Listen-In_Your_Voice-blueviolet?style=for-the-badge" alt="Listen">
    <img src="https://img.shields.io/badge/🪴_Ambient-Computing-ff69b4?style=for-the-badge" alt="Ambient">
    <img src="https://img.shields.io/badge/🔒_Privacy-100%25_Local-success?style=for-the-badge" alt="Local">
    <img src="https://img.shields.io/badge/🍎_macOS-Apple_Silicon-lightgrey?style=for-the-badge" alt="macOS">
    <img src="https://img.shields.io/badge/✈️_Works-On_A_Plane-9cf?style=for-the-badge" alt="Offline">
    <a href="LICENSE"><img src="https://img.shields.io/badge/📜_MIT-Free_Forever-yellow?style=for-the-badge" alt="MIT"></a>
    <a href="https://discord.gg/ZdSqgAxUW"><img src="https://img.shields.io/discord/1497121921580404818?label=NiceDreamzApps&logo=discord&color=5865F2&style=for-the-badge" alt="Join the NiceDreamzApps Discord"></a>
  </p>
</p>

> ## 🧩 You're looking at the **EARS + MOUTH** of a three-repo local-first ambient-computing stack
>
> Pair it with its sibling repos for the full experience:
>
> | 🎤 **THIS REPO** | 🤖 **claude-code-local** | 🌐 **browser-agent** |
> |:---:|:---:|:---:|
> | **EARS + MOUTH** | **BRAIN** | **HANDS** |
> | Talk to your Mac, hear it reply in your own cloned voice — 100% on-device | Runs local AI (Gemma / Llama / Qwen) + Claude Code | Drives a real Brave browser via Chrome DevTools |
> | *You are here* 👈 | 🔗 [**github.com/nicedreamzapp/claude-code-local**](https://github.com/nicedreamzapp/claude-code-local) | 🔗 [**github.com/nicedreamzapp/browser-agent**](https://github.com/nicedreamzapp/browser-agent) |
>
> 👉 **[See how all three fit together below](#-the-complete-local-first-stack)**

---

## ✨ TL;DR

> 💬 **You:** *"Hey, read my project notes and tell me what's important."*
>
> 🔊 **Your Mac (in your own cloned voice):** *"Sure — opening the notes file now... Looks like the auth migration is the priority. You've got 12 TODOs across 4 files, and 3 of them are marked urgent. Want me to walk through the urgent ones?"*
>
> 💬 **You:** *"Yeah, start with the first one."*
>
> 🔊 **Your Mac:** *"Alright, pulling it up..."*

**That whole conversation happens without touching the internet.** 🔒 No cloud. No API bills. No one listening in. Works on a plane. Works in a vault. Works when your Wi-Fi dies.

Your voice goes into Apple's built-in speech engine (the same one that powers macOS Dictation, but running continuously). The text gets handed to a local AI model on your Mac. The model's reply comes out through a cloned copy of **your own voice**. And the mic is smart enough to not listen to itself talking — so there's no weird feedback loops.

It's Siri, if Siri was actually private, actually smart, and actually sounded like you.

---

## 🪴 Why I Built This — Ambient Computing Starts Here

> 💭 **I'm tired of being hunched over a screen with a mouse in my hand.**

Look at how we actually compute in 2026. We're glued to desks. 🪑 Backs curved into question marks. 🖱️ Wrists inflamed from clicking a tiny plastic puck thousands of times a day. 👀 Eyes locked 18 inches from a glowing rectangle for 8+ hours. We buy **$1,500 "ergonomic" chairs** to patch the damage the rest of the furniture is doing to us. We buy standing desks. We buy split keyboards. We buy wrist braces. Carpal tunnel and hunched shoulders are so normal we don't even flag them anymore.

### 🚨 Something is wrong with the shape of this.

I think this era is going to look weird in a few years — the same way pay phones and fax machines look weird now. **Screens-and-mice-as-the-only-interface is ending.** Not tomorrow, not for everyone, but soon. And I want to be one of the people building what comes next instead of waiting for someone else to ship it.

### 🪴 Ambient computing means: the computer is *around* you, not *in front of* you.

You don't sit down at a workstation and stop living. You **go about your life**, and when you need the computer, you just talk to it. 🗣️ It hears you wherever you are. 🔊 It answers in a voice that feels like yours — because it *is* yours, cloned from your actual speech. 🤖 It handles the task. And then it gets quiet again until you need it again.

### 🎨 You know what that unlocks? **Work while playing.**

- 🚶 Walk around the house while your Mac writes code for you
- 🍳 Debug a production issue while you're making dinner
- 🏞️ Take notes on a walk and have your voice clone read back the highlights when you get home
- 🧘 Do actual stretching in the middle of a work session without losing your flow
- 👶 Hold your kid and still ship the feature

**The keyboard and mouse stop being the interface.** 🎙️ Your voice becomes the interface. Your environment becomes the interface. The screen becomes **optional** — something you glance at when you want to see the details, not a pane of glass you're chained to for 8 hours a day.

> 💡 **I believe if you can work while playing, you should.** Work doesn't have to mean sitting still and suffering. It can mean *moving*, *living*, existing in the world while the machines do their part.

### 🌱 This is the first step

NarrateClaude 1.0 is just the first tooth on the gear. It gets Apple's on-device speech engine talking to a local LLM on your Mac in a loop that stays **100% private**. It proves a voice-first interface to a real coding environment isn't just possible — it's *usable*. (I'm using it right now, as I write this, without touching a keyboard for long stretches.)

But the north star is bigger than one mode on one Mac. It's a full ambient-computing stack where **screens are optional, typing is optional, sitting in one place is optional** — and the only thing that isn't optional is that **your data and your voice never leave your house**. 🔒

That's the bet. **Want to build it with me?** 🤝

---

## 🤔 Wait, What?

### 🎯 The simple version
Most "AI voice assistants" — even the ones you're thinking of right now — send your voice to a server, wait for that server to transcribe it, wait for another server to think about it, wait for a third server to turn the answer back into audio, and then play it. **Every step leaves your house.** Every step costs money. Every step stops working the second your Wi-Fi drops.

NarrateClaude doesn't do that. It uses a trick almost nobody is using publicly: **Apple has shipped a legit on-device speech engine with every Mac for years**, and it's just sitting there, free, fast, private. This project wraps it in a smart listener that runs continuously and ties it to a local AI brain and your own cloned voice. Push a button, start talking, and your Mac becomes a genuine conversation partner that never phones home.

### 🧱 What it connects to
By default, NarrateClaude is the *voice* half of a bigger setup: **[claude-code-local](https://github.com/nicedreamzapp/claude-code-local)** — which runs Claude Code (the AI coding tool) against a local AI model on your Mac. Together they mean you can *talk to Claude Code*, have it *narrate what it's doing* through your speakers, and never leak a single keystroke, file path, or voice sample to the cloud.

But the listening side is general-purpose — it'll drive **any** command-line tool that lives in a Terminal window. Want to talk to a local database? Your text editor? A custom shell script? Same pipeline works.

---

## 🎬 What It Feels Like

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   1. 🖱️  You double-click the app                            │
│      ↓                                                       │
│   2. 🪟  A Terminal window pops open with Claude Code        │
│      ↓                                                       │
│   3. 🎙️  The mic icon lights up (listening...)              │
│      ↓                                                       │
│   4. 💬  You speak naturally: "Check my email for urgent"   │
│      ↓                                                       │
│   5. ⏸️  You stop talking for ~2 seconds                    │
│      ↓                                                       │
│   6. ✨  Your words appear in the Terminal automatically    │
│      ↓                                                       │
│   7. 🧠  Claude reads them and starts working               │
│      ↓                                                       │
│   8. 🔊  Claude speaks the answer — in YOUR cloned voice    │
│      ↓                                                       │
│   9. 🎙️  Mic comes back on, ready for your next thing       │
│      ↓                                                       │
│   ♾️   Loop forever, hands never touch the keyboard          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

No hotword. No "Hey Claude." Just talk. When you're done talking, stop. When the answer comes, listen. When you want to say something else, start talking again. The mic is smart enough to pause itself while your Mac is speaking so it doesn't accidentally hear its own voice and start replying to itself.

---

## 🌈 Why This Is A Big Deal

| | 😴 **Cloud Voice AI** (Alexa, Siri, Google, ChatGPT Voice) | 🚀 **NarrateClaude** |
|---|---|---|
| 🎙️ **Your voice goes to…** | Their servers | Nowhere. Stays on your Mac. |
| 🧠 **AI thinking happens on…** | Their servers | Your Mac (local model) |
| 🔊 **The voice you hear is…** | Some stranger's synthesized voice | **Your own cloned voice** |
| ✈️ **Works on a plane?** | ❌ No Wi-Fi = no assistant | ✅ Yes, forever |
| 💰 **Monthly cost** | $$ API fees / subscriptions | **$0. Forever.** |
| 🔒 **Privacy** | Whatever their privacy policy says today | **Absolute** |
| 🎧 **Trained on your data?** | Maybe. Probably. Who knows. | **Never.** |
| 🛑 **Company can shut it off?** | Yes | No — it's just your Mac |

> 💡 **The crazy part:** Apple has been shipping the on-device speech engine that makes this possible with macOS for *years*. Almost nobody is wrapping it for continuous use with a local LLM. You're looking at one of the first projects that does. 🦄

---

## 🔁 How The Magic Works (The Pretty Diagram)

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR MACBOOK 💻                             │
│                                                                 │
│    🎙️  Your voice                                               │
│         │                                                       │
│         ▼                                                       │
│    🎧 listen  (listens continuously, on-device)                 │
│       • Apple's built-in speech engine                          │
│       • Waits for ~2 seconds of "done talking" before typing    │
│       • Pauses itself when your Mac is speaking (no feedback!)  │
│         │                                                       │
│         ▼                                                       │
│    ⌨️  Auto-types your words into a Terminal window             │
│         │                                                       │
│         ▼                                                       │
│    🤖 Claude Code (running locally, no cloud!)                  │
│         │                                                       │
│         ▼                                                       │
│    ⚡ Local AI brain on your chip (Gemma, Llama, etc.)          │
│         │                                                       │
│         ▼                                                       │
│    🔊 Speaks the reply  (in YOUR cloned voice)                  │
│         │                                                       │
│         ▼                                                       │
│    👂 You hear it                                               │
│         │                                                       │
│         └──────────────► and you keep talking                   │
│                                                                 │
│           🔒 NOTHING LEAVES THIS BOX. EVER. 🔒                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Setup (The 5-Minute Version)

### 📋 What you need first

- 🍎 **A Mac with Apple Silicon** (M1, M2, M3, M4, M5 — any of them)
- 🛠️ **Xcode command-line tools** — install with `xcode-select --install` if you haven't already (free, ~1 minute)
- 🎤 **A microphone** (built-in is fine)
- 🔊 **A TTS voice** — your cloned voice if you have one, or macOS's built-in `say` command as a free starter
- 🤖 **[claude-code-local](https://github.com/nicedreamzapp/claude-code-local)** — the local AI coding side of the setup. Optional but highly recommended.

### 🚀 Install in 3 commands

```bash
# 1. Clone this repo
git clone https://github.com/nicedreamzapp/NarrateClaude.git ~/NarrateClaude
cd ~/NarrateClaude

# 2. Make everything runnable
chmod +x dictation/bin/* narrative-claude.sh

# 3. Compile the listener and bind it to your current Terminal window
./dictation/bin/dictation setup
```

That's it. ✅

### 🔊 Set up your voice (pick one)

**Option A — Free starter (5 seconds)**

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/speak <<'EOF'
#!/bin/bash
say "$@"
EOF
chmod +x ~/.local/bin/speak
```

Done. Your Mac will now speak replies using macOS's built-in voice. Not your voice yet, but it works.

**Option B — Your own cloned voice (the real fun)**

Point `~/.local/bin/speak` at whatever TTS tool you want: Pocket TTS, Piper, local ElevenLabs, your own voice clone from any service that runs offline. Any script that takes a string and plays audio works — we're not picky.

### 🎤 Grant microphone permission

The first time you run the listener, macOS will ask for Microphone **and** Speech Recognition permission. **Approve both.** You'll only be asked once.

---

## 🏃 Run It

### 🖱️ The one-click way

```bash
bash ~/NarrateClaude/narrative-claude.sh
```

This opens a fresh Terminal window with Claude Code running, binds the mic to that window, and starts listening. When you close the Terminal window, the listener shuts down on its own — no cleanup needed.

Want a **Dock-friendly double-clickable icon**? See the [`.app` bundle recipe](#optional-wrap-it-in-a-app-bundle) below.

### 🔧 The manual way (for tinkerers)

```bash
# Bind to the current Claude Code Terminal window
~/NarrateClaude/dictation/bin/dictation setup

# Start listening
~/NarrateClaude/dictation/bin/dictation start

# See what it's hearing
~/NarrateClaude/dictation/bin/dictation tail

# Stop listening
~/NarrateClaude/dictation/bin/dictation stop

# Toggle on/off
~/NarrateClaude/dictation/bin/dictation toggle
```

### <a name="optional-wrap-it-in-a-app-bundle"></a>📦 Optional: wrap it in a `.app` bundle

If you want a Dock-friendly icon you can double-click from Finder:

```bash
APP=~/Desktop/NarrativeClaude.app
mkdir -p "$APP/Contents/MacOS"
ln -sf ~/NarrateClaude/narrative-claude.sh "$APP/Contents/MacOS/NarrativeClaude"
cat > "$APP/Contents/Info.plist" <<'PLIST'
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

🎨 Want a custom icon? Drop a `.icns` file at `$APP/Contents/Resources/AppIcon.icns` and add `<key>CFBundleIconFile</key><string>AppIcon</string>` to the plist.

---

## 🎭 The "Always Narrating" Brain

There's a small file at the root of this repo called `CLAUDE.md`. It tells your local AI: **"Every reply must be spoken out loud. Narrate what you're doing in real time. Don't just sit there silently."**

That's the rule that makes the whole thing feel *alive*. Without it, the AI would do its work silently and only speak at the end, which feels weird and slow. With it, the AI narrates every step — *"Okay, I'm opening the file now... found 12 TODOs... let me look at the urgent ones..."* — so you're never wondering if it's thinking or frozen.

If you're running [claude-code-local](https://github.com/nicedreamzapp/claude-code-local), the `Narrative Gemma.command` launcher injects this file automatically. If you're running a different setup, point your own system-prompt flag at `~/NarrateClaude/CLAUDE.md` and you're good.

---

## 🤓 For the Curious — Under the Hood

> Skip this section if you just want it to work. Keep reading if you like knowing *why*.

### 🎙️ The listener is smart about ending sentences

Most dictation software detects "done talking" by watching the **microphone volume** — if it's quiet for a bit, you must be done. **This breaks the moment you have a fan, HVAC, background music, or any consistent noise** above the silence threshold.

NarrateClaude instead watches the **transcribed text**. If Apple's speech engine has been returning the same words for 2.5 seconds, you're done — it commits the sentence and moves on. Works in noisy rooms, works with music playing, works on a plane with engines roaring.

### 🔁 The mic pauses itself so the AI doesn't talk to itself

When your Mac speaks the reply out loud, that sound comes out of your speakers, bounces around the room, and hits your microphone. Without special handling, the listener would hear *"Okay, I'm opening the file now..."*, transcribe it, and treat it as *your* next command — infinite feedback loop.

Fix: the listener watches for the TTS playback process (`afplay`) and **auto-pauses** speech recognition while it's running. The moment the audio stops, the mic comes back on. Clean handoff every time.

### 🛡️ It's production-hardened, not a demo

Running continuous speech recognition for hours is a different problem from running it for 30 seconds in a demo. Apple's speech engine can get stuck, leak memory, or degrade over time. NarrateClaude defends against all of that:

- 🚨 **Wedge detection** — if the listener's audio queue grows too big without progress, it assumes the speech engine is hung and exits. A supervisor restarts it fresh.
- 🔄 **Preventive recycling** — every 10 minutes the listener exits cleanly and respawns. Stops slow degradation before it starts.
- 🎯 **Strict window binding** — the dictation is tied to a specific Terminal window by window ID. If that window closes, the listener stops within ~5 seconds. No orphaned listeners.
- 🔐 **Launch gating** — the start command refuses to run unless called by an authorized launcher (protects against random processes or typos unexpectedly turning on your mic).

### ⚙️ Everything is tunable

Environment variables for when you want to fiddle:

| Knob | Default | What it does |
|---|---:|---|
| `LISTEN_STABILITY_SEC` | 2.5 | How long the text needs to stop changing before we finalize a sentence |
| `LISTEN_MAX_UTTER_SEC` | 60 | Hard cap on a single utterance (seconds) |
| `LISTEN_MAX_SESSION_SEC` | 600 | Force a clean respawn every N seconds (preventive) |
| `LISTEN_WEDGE_BACKLOG` | 200 | Audio buffers piled up = engine is wedged, bail |
| `LISTEN_DEBUG` | `0` | Set to `1` for noisy diagnostic logging |

---

## 🧪 Something Not Working?

### 🎤 "Speech recognition not authorized" or no mic input

Open **System Settings → Privacy & Security**:
- ✅ Enable **Microphone** for Terminal
- ✅ Enable **Speech Recognition** for Terminal

Both are required. Restart the listener after granting.

### 🪟 "Couldn't find a Terminal window running claude" during setup

Make sure Claude Code is running in **Apple's Terminal.app** (not iTerm2, not Warp, not Ghostty — those aren't supported yet because the injector uses Terminal-specific AppleScript). Then run `dictation setup` from *inside* that window.

### 🔁 Listener keeps exiting and restarting

Check the error log:

```bash
cat ~/NarrateClaude/dictation/state/dictation.log.stderr
```

Most common cause: Microphone or Speech Recognition permission was revoked or never granted.

### 🎤 Just want to check the mic is working at all

```bash
cd ~/NarrateClaude/dictation/src
swiftc -O MicProbe.swift -o /tmp/micprobe
/tmp/micprobe
# Say "HELLO HELLO HELLO" out loud. You should see non-zero numbers scroll by.
```

If the numbers stay at zero, macOS isn't letting the process access the mic — fix the permission first.

---

## 🤝 Contributing

PRs and issues super welcome, especially if you want to:

- 🎙️ **Port the injector to iTerm2, Ghostty, Alacritty, or any other terminal** — right now it's Apple Terminal only, which limits who can use it
- 🔊 **Add a TTS recipe** — Piper, local ElevenLabs, MLX-TTS, Kyutai Moshi, or any other offline voice synthesizer that slots into `~/.local/bin/speak`
- 🧠 **Use a different STT engine** — Whisper.cpp, MLX-Whisper, etc. The rest of the pipeline doesn't care what's on the listening end
- 🗣️ **Interruption detection** — let me cut off the TTS mid-sentence if I start talking again (barge-in)
- 🐛 **Just tell me what's broken** — open an issue with the contents of `dictation/state/dictation.log` attached

Small PRs welcome. Huge PRs welcome. Ideas-with-no-code welcome.

---

## 🧩 The Complete Local-First Stack

`NarrateClaude` is the **ears and mouth** — the listener, the injector, the cloned-voice pipeline. It's one of three sibling repos that together form a **local-first ambient computing stack** that never sends a keystroke, a voice clip, or a page load to the cloud. Each piece stands alone; together they're the full setup.

```
      🎤 NarrateClaude         🤖 claude-code-local          🌐 browser-agent
      ─────────────────        ────────────────────         ──────────────────
      EARS + MOUTH             BRAIN                        HANDS
      (this repo)              ────────────────────         ──────────────────
      ─────────────────        MLX + Gemma / Llama     →    Chrome DevTools
      Apple SFSpeech     →     Anthropic API server         iframes + Shadow DOM
      continuous listener      Tool-call parser (×3)        Brave browser control
      AppleScript inject       Code mode, prompt cache      Snapshot + click + type
      cloned-voice TTS         Narrative Gemma launcher     ──────────────────
      ─────────────────        ────────────────────         🔗 github.com/
      🔗 github.com/           🔗 github.com/                nicedreamzapp/
      nicedreamzapp/           nicedreamzapp/                browser-agent
      NarrateClaude            claude-code-local
      (this repo)
```

| What you want | Clone |
|---|---|
| 🎙️ Just the continuous on-device dictation pipeline (any CLI target) | Just this repo |
| 🎤 Talk to Claude Code and hear it narrate back in your own voice | This repo **+** [`claude-code-local`](https://github.com/nicedreamzapp/claude-code-local) |
| 🌐 Talk to a local AI that can drive Claude Code **and** a real browser | All three |
| 🪴 Full ambient-computing stack on one Mac, 100% on-device | All three |

### Why two repos instead of one bundle

**Focus.** The listening pipeline is a general-purpose macOS dictation tool — it'll drive any Terminal-based CLI, not just Claude Code. The brain side is a full local-AI server with its own architecture and roadmap. Smooshing them together would mean two teams of contributors stepping on each other and a vendored-copy drift problem. Separate repos = separate focus = clean contribution surface for each.

Think of it as hi-fi audio gear: the speakers and the amplifier are separate components, each great on its own, and together they make a system.

---

## 🔗 Sibling Projects (Quick Links)

- 🤖 [**claude-code-local**](https://github.com/nicedreamzapp/claude-code-local) — The local AI brain NarrateClaude was originally built to talk to. Run Claude Code against a local Gemma / Llama / Qwen model with zero cloud calls. Ships the `Narrative Gemma.command` launcher that loads the narration persona on the model side.
- 🌐 [**browser-agent**](https://github.com/nicedreamzapp/browser-agent) — Drives a real Brave browser via Chrome DevTools Protocol using the same local AI setup. Add it to the stack when you want the model to navigate the web for you.

---

## 🙏 Credits

- 🍎 **Apple** — `SFSpeechRecognizer` is a legitimately good on-device speech engine that's been sitting in macOS for years, mostly unused by the indie AI scene. Thanks for shipping it.
- 🎤 **Pocket TTS** — the cloned-voice synthesizer I use on the output side. Any compatible TTS works, but this is what I reach for.
- 🤖 **Anthropic + Claude Code** — the AI coding tool this voice loop was built to talk to
- 🎙️ **Every "voice AI" demo that's secretly a cloud pipeline** — thanks for leaving this gap unfilled, I guess

---

## 💬 Community

Builders running, contributing to, or hacking on `NarrateClaude`, `claude-code-local`, and `browser-agent` hang out in a small Discord. Quiet, builder-tone, no bots.

<p align="center">
  <a href="https://discord.gg/ZdSqgAxUW"><img src="https://img.shields.io/discord/1497121921580404818?label=Join%20NiceDreamzApps%20on%20Discord&logo=discord&color=5865F2&style=for-the-badge" alt="Join the NiceDreamzApps Discord"></a>
</p>

👉 **[discord.gg/ZdSqgAxUW](https://discord.gg/ZdSqgAxUW)**

---

<p align="center">
  <strong>📜 MIT License</strong> — Use it however you want. Fork it. Build on it. Ship it in your own product.<br><br>
  ⭐ <strong>If this helped you talk to your Mac instead of typing at it, leave a star.</strong> ⭐<br><br>
  <sub>Built with love on an M5 Max by <a href="https://github.com/nicedreamzapp">@nicedreamzapp</a></sub>
</p>
