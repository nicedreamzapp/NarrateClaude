---
title: FAQ, NarrateClaude voice control for Claude Code
description: Answers about NarrateClaude. Does it work offline, which Macs and terminals, other languages, interrupting replies, using your own cloned voice, using it with tools other than Claude Code, and cost.
---

# FAQ

## Is it fully offline?

Speech recognition runs on the Mac when the recognizer reports on-device support. The listener asks for on-device mode only in that case. What Claude Code talks to is up to you. Plain `claude` uses Anthropic's servers. To keep the model local too, run Claude Code against a local model with [claude-code-local](https://github.com/nicedreamzapp/claude-code-local). The optional relevance judge runs locally on `127.0.0.1`.

## Which Macs does it run on?

Macs with Apple Silicon. The dispatcher forces `arch -arm64` for the voiceprint filter, and the README lists M1 through M5. The listener itself uses only Apple frameworks (Speech, AVFoundation). **TODO-VERIFY:** minimum macOS version. The `.app` recipe sets `LSMinimumSystemVersion` to 12.0, but the scripts were not tested against it.

## Does it work in iTerm2, Ghostty or Warp?

Not yet. Binding, typing and the window watchdog all use Terminal.app AppleScript. Help is wanted in [issue #2](https://github.com/nicedreamzapp/NarrateClaude/issues/2).

## Does it work in other languages?

No. The recognizer is created with `en-US`. Changing the locale in `Listen.swift` and recompiling is the place to start. The relevance filter's prompts and regexes are also English.

## Can I interrupt it while it is talking?

No. In v1 the mic is paused while `afplay` plays. Starting to speak right after a reply ends works, and a new injected line kills any speech still playing. The interruptible 2.0 work is described in the research logs but not published.

## Why does "yes" not go through?

The injector drops lines under 3 words unless they end in a question mark. Apple's recognizer adds punctuation, so "why?" can pass. Set `INJECT_FORCE=1` to turn the gate off.

## Do I need a cloned voice?

No. A 4-line `say` plus `afplay` script works. See [Install](install.md#2-create-the-speak-command). Any offline TTS works if it plays through `afplay`. The author uses Pocket TTS by Kyutai.

## Can it drive something other than Claude Code?

The listener and injector do not care what runs in the window. `dictation setup` and the launcher both look for or start `claude`, though. To target another program you would write `dictation/state/target.json` yourself (`{ "app": "Terminal", "window_id": N }`). **TODO-VERIFY:** this is what the code allows, not a tested setup.

## How do I mute it without stopping it?

Say "Claude tune out". Say "Claude tune in" to resume. Or run `dictation stop`.

## Why must it live in `~/NarrateClaude`?

`narrative-claude.sh` has `$HOME/NarrateClaude` hard-coded, and it starts `claude` there so `CLAUDE.md` is loaded. The scripts under `dictation/bin` find their own folder, so they work from anywhere.

## What happens if I close the Terminal window?

The window watchdog checks every 3 seconds. When the bound window is gone it stops the listener, and `inject` refuses to type into any other window in the meantime.

## Does it record my voice?

The v1 listener does not write audio to disk. Transcribed lines are written to `dictation/state/dictation.log`, and the filters log decisions next to it. Delete that folder to clear them.

## What does it cost?

The code is MIT licensed. Apple's recognizer comes with macOS. Claude Code usage costs whatever your Claude plan or API usage costs, unless you run a local model.

## Is there a demo video?

Not in the repo yet.
