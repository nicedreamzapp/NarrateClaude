---
title: Hands-free voice control for Claude Code on macOS
description: NarrateClaude lets you talk to Claude Code on a Mac. Apple's on-device speech recognizer types what you say into Terminal, and replies are spoken back through any voice you choose.
---

# NarrateClaude

**Talk to Claude Code on your Mac and hear it answer.** NarrateClaude is a small set of scripts and one Swift program that turn the `claude` command in Apple Terminal into a voice loop:

1. A listener transcribes your speech continuously with Apple's Speech framework (`SFSpeechRecognizer`), on-device when your Mac supports it.
2. When the words stop changing for 2.5 seconds, the sentence is typed into the Terminal window running `claude` and submitted.
3. Claude Code speaks while it works, through whatever program you put at `~/.local/bin/speak`. That can be macOS `say` or a cloned copy of your own voice.
4. The mic pauses while `afplay` is playing, so the assistant does not hear itself.

Everything in this repo is the v1 voice loop. It runs on Apple Silicon Macs, in Apple's Terminal.app, in English (`en-US`).

[Install](install.md){ .md-button .md-button--primary }
[Quickstart](quickstart.md){ .md-button }

## Who it is for

- People who use [Claude Code](https://github.com/anthropics/claude-code) and want to work away from the keyboard for stretches.
- People who want a voice loop where speech recognition stays on the Mac. Pair it with [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) to run the model locally too. Without a local model, `claude` still talks to Anthropic's servers.
- Tinkerers who want a working example of continuous `SFSpeechRecognizer` dictation with wedge detection and auto-respawn.

## What is in the repo

| Part | File |
|---|---|
| Continuous listener (Swift) | [`dictation/src/Listen.swift`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/src/Listen.swift) |
| Supervisor: respawn loop, window watchdog, pipeline | [`dictation/bin/dispatch`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/dispatch) |
| Injector: types each sentence into the bound Terminal window | [`dictation/bin/inject`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/inject) |
| Control CLI: `setup`, `start`, `stop`, `status`, `toggle`, `tail`, `uninstall` | [`dictation/bin/dictation`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/dictation) |
| One-click launcher | [`narrative-claude.sh`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/narrative-claude.sh) |
| "Was that for me?" relevance filter | [`dictation/filter/relevance.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/filter/relevance.py) |
| Voiceprint filter and enrollment (inactive with the v1 listener) | [`dictation/filter/filter.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/filter/filter.py), [`enroll.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/filter/enroll.py) |
| Claude Code Stop hook that reads the last reply aloud | [`dictation/bin/speak-on-stop`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/speak-on-stop) |
| Mic diagnostic | [`dictation/src/MicProbe.swift`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/src/MicProbe.swift) |
| The always-narrate instructions Claude Code reads | [`CLAUDE.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/CLAUDE.md) |

## Screenshots and demo

There is no screenshot, GIF or demo video in the repo yet. The best record of how it behaves is the engineering log [`BARGE_IN_ATTEMPTS.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/BARGE_IN_ATTEMPTS.md), which covers seven echo-cancellation attempts for the unpublished 2.0 work, with what failed and the measured results (for example 58 dB offline echo reduction for WebRTC AEC3 against 29.5 dB for SpeexDSP).

## Known limits

- Apple Terminal only. iTerm2, Ghostty and Warp are not supported yet ([issue #2](https://github.com/nicedreamzapp/NarrateClaude/issues/2)).
- No barge-in. Anything you say while a reply is playing through `afplay` is dropped.
- Lines under 3 words are dropped unless they end in `?`.
- English only (`en-US` recognizer).
- The repo must be cloned to `~/NarrateClaude`, because the launcher uses that path.

Details are on the [Troubleshooting](troubleshooting.md) and [FAQ](faq.md) pages.

## Built on

Apple's Speech framework, [Claude Code](https://github.com/anthropics/claude-code) by Anthropic, [MLX](https://github.com/ml-explore/mlx) and [mlx-lm](https://github.com/ml-explore/mlx-lm) for the optional relevance judge, Meta's Llama 3.2 3B as that judge's model, [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) for voiceprints, and [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai for the author's cloned voice. See [Credits](credits.md).
