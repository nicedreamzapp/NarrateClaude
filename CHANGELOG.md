# Changelog

## 2.0.0 (2026-11-06)

The big one: you can talk over the voice to stop it. Everything else since 1.0.0 is below it.

### Talk over it (barge-in, macOS)

- New "Talking Stick" mode, opt-in with `NARRATE_BARGE_IN=2`. The mic stays open while the voice plays. WebRTC AEC3 from the `livekit` wheel cancels the WAV that `afplay` is playing, and a gate that learns each room stops the voice when you start talking and types what you said. Code in `dictation/voice/bargein.py`, extra package in `dictation/voice/requirements-bargein.txt`. ([#14](https://github.com/nicedreamzapp/NarrateClaude/pull/14))
- Measured on an M5 MacBook Pro with its built-in speakers and mic: 0 false triggers on echo alone; 9 of 10 live double-talk trials stopped the voice 0.16 to 0.39 s after I started talking; replaying the room recordings, 11 of 12 hits with a median of 0.14 s, the same with the mic 20 dB quieter.
- Limits: macOS only, and only voices that play a WAV through `afplay` (Piper, Kokoro), not Chatterbox. With the flag off the listener is the same as before. Full notes in Attempt 8 of `BARGE_IN_ATTEMPTS.md`.

### Listening and speaking

- whisper.cpp is the default speech to text on macOS, Linux and Windows: a local whisper-server with an f16 model picked by memory (`large-v3-turbo`, `small.en`, `base.en`) and Silero VAD. Apple's recognizer stays as `narrate-claude --apple`.
- Piper is the default voice when you have no `~/.local/bin/speak`.
- `narrate-claude --here` runs `claude` in a pty the loop owns (ConPTY on Windows), so any terminal works. This is how Linux and Windows run.
- Parakeet TDT v2 live transcript, a smoother Chatterbox voice (streamed, model kept loaded, no gap after the first word), podcast SSML and a compact `{.4}` / `{fast:...}` shorthand, and short replies like "yes" now go through. Thanks to [@hershykoh](https://github.com/hershykoh). ([#13](https://github.com/nicedreamzapp/NarrateClaude/pull/13))

### Install, tests, docs

- `install.sh` / `uninstall.sh`, and `install.ps1` / `uninstall.ps1` for Windows. whisper.cpp v1.9.5 is built from source and every model download is pinned and checked by sha256.
- A pytest suite, and CI that runs the whole voice loop end to end on Linux, macOS and Windows.
- A MkDocs documentation site, community files (contributing guide, code of conduct, security policy, issue templates) and an OpenSSF Scorecard workflow.
- The launcher finds the repo from its own location, so the folder can live anywhere.

## 1.0.0 (2026-08-06)

First tagged release: the hands-free on-device voice loop for macOS (Apple's speech engine, Terminal.app typing, the relevance and voiceprint filters, and the Stop hook that reads replies aloud).
