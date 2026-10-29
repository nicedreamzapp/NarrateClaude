---
title: Hands-free voice control for Claude Code
description: NarrateClaude lets you talk to Claude Code on macOS, Linux and Windows. whisper.cpp transcribes what you say on your own machine and types it into claude, and replies are spoken back with the local Piper voice or any voice you choose.
---

# NarrateClaude

**Talk to Claude Code and hear it answer.** NarrateClaude turns the `claude` command into a voice loop, on macOS, Linux and Windows, with nothing but open-source parts running on your machine:

1. A listener records the mic and cuts it into sentences with a voice activity detector, then transcribes each one with [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (a full-precision f16 model, Metal on Apple Silicon).
2. Each sentence is typed into `claude`, which runs inside the loop's own pseudo-terminal, so any terminal app works. On macOS the original Apple Terminal mode is still the default.
3. Claude Code speaks while it works, through `~/.local/bin/speak`: the local [Piper](https://github.com/OHF-Voice/piper1-gpl) voice out of the box, or a cloned copy of your own voice.
4. The mic pauses while the voice plays, so the assistant does not hear itself.

Apple's speech engine is still there as `narrate-claude --apple`.

[Install](install.md){ .md-button .md-button--primary }
[Quickstart](quickstart.md){ .md-button }

## Who it is for

- People who use [Claude Code](https://github.com/anthropics/claude-code) and want to work away from the keyboard for stretches.
- People who want a voice loop where speech recognition stays on the Mac. Pair it with [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) to run the model locally too. Without a local model, `claude` still talks to Anthropic's servers.
- Tinkerers who want a working example of continuous `SFSpeechRecognizer` dictation with wedge detection and auto-respawn.

## What is in the repo

| Part | File |
|---|---|
| Listener: VAD + whisper.cpp | [`dictation/voice/stt.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/voice/stt.py) |
| Session: `claude` in the loop's own pty | [`dictation/voice/session.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/voice/session.py) |
| Default voice (Piper) | [`dictation/voice/speak.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/voice/speak.py) |
| Optional Apple-speech listener (Swift) | [`dictation/src/Listen.swift`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/src/Listen.swift) |
| Supervisor: respawn loop, window watchdog, pipeline | [`dictation/bin/dispatch`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/dispatch) |
| Injector: types each sentence into the bound Terminal window | [`dictation/bin/inject`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/inject) |
| Control CLI: `setup`, `start`, `stop`, `status`, `toggle`, `tail`, `uninstall` | [`dictation/bin/dictation`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/dictation) |
| One-click launcher | [`narrative-claude.sh`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/narrative-claude.sh) |
| "Was that for me?" relevance filter | [`dictation/filter/relevance.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/filter/relevance.py) |
| Voiceprint filter and enrollment (Terminal.app mode) | [`dictation/filter/filter.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/filter/filter.py), [`enroll.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/filter/enroll.py) |
| Claude Code Stop hook that reads the last reply aloud | [`dictation/bin/speak-on-stop`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/bin/speak-on-stop) |
| Mic diagnostic | [`dictation/src/MicProbe.swift`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/src/MicProbe.swift) |
| The always-narrate instructions Claude Code reads | [`CLAUDE.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/CLAUDE.md) |

## Screenshots and demo

There is no screenshot, GIF or demo video in the repo yet. The best record of how it behaves is the engineering log [`BARGE_IN_ATTEMPTS.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/BARGE_IN_ATTEMPTS.md), which covers seven echo-cancellation attempts for the unpublished 2.0 work, with what failed and the measured results (for example 58 dB offline echo reduction for WebRTC AEC3 against 29.5 dB for SpeexDSP).

## Known limits

- The default macOS mode is Apple Terminal only; `narrate-claude --here` works in any terminal ([issue #2](https://github.com/nicedreamzapp/NarrateClaude/issues/2)).
- No barge-in by voice. Anything you say while a reply is playing is dropped.
- Lines under 3 words are dropped unless they end in `?`.
- English by default (`NARRATE_WHISPER_LANG` changes it with the multilingual model).

Details are on the [Troubleshooting](troubleshooting.md) and [FAQ](faq.md) pages.

## Built on

[whisper.cpp](https://github.com/ggml-org/whisper.cpp), [Silero VAD](https://github.com/snakers4/silero-vad), [Piper](https://github.com/OHF-Voice/piper1-gpl), Apple's Speech framework (for `--apple`), [Claude Code](https://github.com/anthropics/claude-code) by Anthropic, [MLX](https://github.com/ml-explore/mlx) and [mlx-lm](https://github.com/ml-explore/mlx-lm) for the optional relevance judge, Meta's Llama 3.2 3B as that judge's model, [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) for voiceprints, and [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai for the author's cloned voice. See [Credits](credits.md).
