---
title: FAQ, NarrateClaude voice control for Claude Code
description: Answers about NarrateClaude. Does it work offline, which computers and terminals, other languages, interrupting replies, using your own cloned voice, using it with tools other than Claude Code, and cost.
---

# FAQ

## Is it fully offline?

Yes, apart from what Claude Code talks to. Speech recognition is whisper.cpp on your machine and the default voice is Piper, both local; after install nothing is downloaded. Plain `claude` uses Anthropic's servers. To keep the model local too, run Claude Code against a local model with [claude-code-local](https://github.com/nicedreamzapp/claude-code-local). The optional relevance judge runs locally on `127.0.0.1`.

## Which computers does it run on?

macOS (Apple Silicon gets Metal acceleration), Linux and Windows 10/11. The installer picks the f16 whisper model that fits your memory: `large-v3-turbo` at 8 GB or more, `small.en` at 4 to 8 GB, `base.en` below. The `--apple` Terminal mode needs macOS. **TODO-VERIFY:** minimum macOS version.

## Does it work in iTerm2, Ghostty or Warp?

Yes, with `narrate-claude --here`: `claude` runs inside the loop's own pty, so any terminal works. The default macOS mode still opens Apple Terminal and types through its AppleScript ([issue #2](https://github.com/nicedreamzapp/NarrateClaude/issues/2)).

## Does it work in other languages?

The default is English (`NARRATE_WHISPER_LANG=en`). `large-v3-turbo` is multilingual: set `NARRATE_WHISPER_LANG` to a language code or `auto`. The `.en` models are English only. The relevance filter's prompts and regexes are English, and `--apple` uses `en-US`.

## Can I interrupt it while it is talking?

Not by voice. The mic is paused while the voice plays. Starting to speak right after a reply ends works, and a new injected line kills any speech still playing. The interruptible 2.0 work is described in the research logs but not published.

## Why does "yes" not go through?

The injector drops lines under 3 words unless they end in a question mark. Whisper adds punctuation, so "why?" can pass. Set `INJECT_FORCE=1` to turn the gate off.

## Do I need a cloned voice?

No. The installer's `~/.local/bin/speak` uses the local Piper voice. Any offline TTS works in its place if it plays through a player the listener knows (`afplay`, `aplay`, `paplay`, `pw-play`, `ffplay`). The author uses Pocket TTS by Kyutai.

## Can it drive something other than Claude Code?

Yes: `dictation/voice/session.py -- your-program` runs any terminal program inside the loop. In Terminal.app mode, the listener and injector do not care what runs in the window. `dictation setup` and the launcher both look for or start `claude`, though. To target another program you would write `dictation/state/target.json` yourself (`{ "app": "Terminal", "window_id": N }`). **TODO-VERIFY:** this is what the code allows, not a tested setup.

## How do I mute it without stopping it?

Say "Claude tune out". Say "Claude tune in" to resume. Or run `dictation stop`.

## Does it have to live in `~/NarrateClaude`?

No. `narrative-claude.sh` finds its own folder (following symlinks, so an `.app` wrapper or the `narrate-claude` link works) and starts `claude` there so `CLAUDE.md` is loaded. If the script was copied out of the repo, it falls back to `$NARRATE_DIR`, then `~/NarrateClaude`. The scripts under `dictation/bin` find their own folder too.

## What happens if I close the Terminal window?

The window watchdog checks every 3 seconds. When the bound window is gone it stops the listener, and `inject` refuses to type into any other window in the meantime.

## Does it record my voice?

The v1 listener does not write audio to disk. Transcribed lines are written to `dictation/state/dictation.log`, and the filters log decisions next to it. Delete that folder to clear them.

## What does it cost?

The code is MIT licensed. whisper.cpp, Piper and Silero VAD are open source. Claude Code usage costs whatever your Claude plan or API usage costs, unless you run a local model.

## Is there a demo video?

Not in the repo yet.
