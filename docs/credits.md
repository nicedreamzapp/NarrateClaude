---
title: Credits and upstream projects
description: The upstream projects NarrateClaude is built on, including Apple's Speech framework, Anthropic's Claude Code, MLX, mlx-lm, Llama 3.2, Resemblyzer and Kyutai's Pocket TTS.
---

# Credits

NarrateClaude's own code is the listener, the shell scripts and the filters listed on the [home page](index.md). Everything below is someone else's work.

## Used by the code in this repo

| Project | Used for | By |
|---|---|---|
| [Speech framework](https://developer.apple.com/documentation/speech) (`SFSpeechRecognizer`) and AVFoundation | Speech recognition and mic capture in `Listen.swift` | Apple |
| Terminal.app AppleScript, `osascript`, `afplay`, `say` | Window binding, typing, audio playback | Apple |
| [Claude Code](https://github.com/anthropics/claude-code) | The assistant the voice loop drives, the `CLAUDE.md` project instructions, Stop hooks | Anthropic |
| [MLX](https://github.com/ml-explore/mlx) | Runs the relevance judge model on Apple Silicon | Apple's ml-explore team |
| [mlx-lm](https://github.com/ml-explore/mlx-lm) | `mlx_lm server`, the local OpenAI-style endpoint the judge calls | Apple's ml-explore team |
| [Llama 3.2 3B Instruct](https://huggingface.co/mlx-community/Llama-3.2-3B-Instruct-4bit) (4-bit MLX conversion) | Default relevance judge model | Meta, converted by mlx-community |
| [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) and NumPy | Voiceprint enrollment and matching | Resemble AI, NumPy developers |

## Used alongside it

| Project | Role | By |
|---|---|---|
| [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) | The author's cloned voice behind `~/.local/bin/speak` | Kyutai |
| [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) | Runs Claude Code against a local model. Sibling project. | nicedreamzapp |

## Named in the 2.0 research logs

Not used by the published code: WebRTC audio processing (AEC3, via the PulseAudio `webrtc-audio-processing` fork), SpeexDSP, [FluidAudio](https://github.com/FluidInference/FluidAudio), Silero VAD, Smart Turn v3 from Pipecat, and WhisperKit.

## This site

Built with [MkDocs](https://www.mkdocs.org/) and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/).

If your work is listed here and you want the wording changed, or something is missing, [open an issue](https://github.com/nicedreamzapp/NarrateClaude/issues).
