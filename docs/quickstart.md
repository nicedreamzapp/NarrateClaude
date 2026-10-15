---
title: Quickstart, talk to Claude Code in 2 minutes
description: Start NarrateClaude with one command, speak to Claude Code in Terminal, check what the listener heard, and stop it again. Includes the manual start, stop and tail commands.
---

# Quickstart

This assumes you finished [Install](install.md) and `dictation setup` compiled the listener.

## One command

```bash
bash ~/NarrateClaude/narrative-claude.sh
```

What happens, step by step (from `narrative-claude.sh`):

1. Any running listener is stopped so the new window owns the mic.
2. Terminal opens a new window running `cd ~/NarrateClaude && claude`, with `CLAUDE_SESSION_LABEL=NarrativeClaude` exported.
3. That window's ID is written to `dictation/state/target.json`.
4. The script waits 6 seconds for `claude` to draw its prompt.
5. The listener starts with `NARRATE_DICTATION_LAUNCHER=NarrativeClaude.app`.

Because `claude` starts inside `~/NarrateClaude`, Claude Code reads the repo's `CLAUDE.md`, which tells it to narrate everything through `~/.local/bin/speak`.

## Talk

Speak a full sentence. When the transcription stops changing for 2.5 seconds, the sentence is typed into the bound window and submitted.

Things to know on day one:

- **Use at least 3 words**, or end with a question. "Yes" and "do it" are dropped. "Why?" goes through.
- **Wait for the reply to finish.** The mic is paused while `afplay` plays.
- **Starting a new sentence cuts off speech.** Each injected line first kills `afplay`, `say` and a few TTS processes.
- **"Claude tune out"** mutes the relevance filter until you say **"Claude tune in"**. The word "Claude" is optional. The mute survives restarts.

## Watch what it heard

```bash
~/NarrateClaude/dictation/bin/dictation tail
```

Every accepted line is logged with a timestamp, along with dispatcher events such as listener respawns.

## Stop

Close the Terminal window. The window watchdog checks every 3 seconds and shuts the listener down when the window is gone. Or stop it directly:

```bash
~/NarrateClaude/dictation/bin/dictation stop
```

## Manual control

```bash
D=~/NarrateClaude/dictation/bin/dictation

$D setup     # bind to the Terminal window running claude, compile listener
NARRATE_DICTATION_LAUNCHER="NarrativeClaude.app" $D start
$D status    # ON/OFF, bound window, compiled or not
$D tail      # follow the log
$D stop
NARRATE_DICTATION_LAUNCHER="NarrativeClaude.app" $D toggle
```

`start` is refused unless `NARRATE_DICTATION_LAUNCHER` is `NarrativeClaude.app` or `Narrative Gemma.command`, so a stray call cannot turn on the mic. See [Configuration](configuration.md#launcher-gate).

!!! note
    `dictation start` prints "~1s of silence ends each utterance", but the listener's default is 2.5 seconds of unchanged text (`LISTEN_STABILITY_SEC`). The printed message is out of date.
