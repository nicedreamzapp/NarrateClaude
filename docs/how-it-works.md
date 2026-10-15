---
title: How it works, architecture of the voice loop
description: How NarrateClaude turns speech into Claude Code input. The Swift SFSpeechRecognizer listener, stability-based endpointing, wedge watchdogs, the dispatch respawn loop, filters, and AppleScript injection into Terminal.
---

# How it works

NarrateClaude is a Unix pipeline supervised by a bash loop. One process listens, two filters decide what to keep, and one script types each surviving line into Terminal.

```mermaid
flowchart LR
    mic([Microphone]) --> listen[listen<br/>Swift, SFSpeechRecognizer]
    listen -->|one line per sentence| filter[filter.py<br/>voiceprint, or cat]
    filter --> rel[relevance.py<br/>was that for me?]
    rel --> loop{{dispatch<br/>read loop}}
    loop -->|log| log[(dictation.log)]
    loop --> inject[inject<br/>AppleScript]
    inject --> term[Terminal window<br/>running claude]
    term --> claude[Claude Code]
    claude -->|CLAUDE.md: narrate| speak[~/.local/bin/speak]
    speak --> afplay[afplay]
    afplay -. pgrep every 0.15 s pauses .-> listen
    watchdog[window watchdog<br/>every 3 s] -. window gone .-> loop
```

## The pieces

### 1. Launcher (`narrative-claude.sh`)

Stops any old listener, opens a Terminal window running `claude` in `~/NarrateClaude`, finds that window's ID by matching the new tab's tty, writes `state/target.json`, waits 6 seconds, and runs `dictation start` with the launcher gate variable set. If it cannot get a window ID it shows a macOS dialog and exits.

### 2. Control script (`dictation`)

Handles `setup`, `start`, `stop`, `status`, `toggle`, `tail` and `uninstall`. On `start` it checks the launcher gate, kills any existing `dispatch` or `listen` processes with `pkill -9` (so orphaned respawn loops cannot pile up), and starts `dispatch` in the background with `nohup`.

### 3. Supervisor (`dispatch`)

- Starts a **window watchdog** in the background. Every 3 seconds it reads `window_id` from `target.json` and asks Terminal whether that window still exists. If not, it touches `state/.shutdown` and kills the listener. A flag file is used instead of a signal because bash defers signals while blocked on a pipeline read.
- Runs a **respawn loop**: `listen | filter | relevance | while read line; do log; inject; done`. When the listener exits for any reason, the loop logs the lifetime and starts it again: after 1 second normally, after 5 seconds if it died in under 3 seconds (usually a permission problem).
- Picks the filters each round. The voiceprint stage is `filter.py` under `arch -arm64` only if its venv and `voiceprint.npy` exist, else `cat`. The relevance stage is `relevance.py` under `/usr/bin/python3` if the file exists, else `cat`.

### 4. Listener (`Listen.swift`)

One `SFSpeechAudioBufferRecognitionRequest` at a time, fed from an `AVAudioEngine` input tap, with partial results on.

**Endpointing by text, not volume.** Each partial result that differs from the last one resets a timer. When the text has not changed for `LISTEN_STABILITY_SEC` (2.5 s), the listener calls `endAudio()`. The final result is printed to stdout, or the last partial if the final is empty, and a new task starts. Background noise that never turns into words does not keep an utterance open.

**Pause while speaking.** A background thread runs `pgrep -x afplay` every 0.15 s. While `afplay` exists, incoming buffers are dropped and any in-progress task is cancelled. When it ends, the next buffer starts a new task. This is half-duplex: you cannot interrupt a reply by talking.

**Watchdog thread** (every 5 s):

- **Backlog wedge.** A counter is bumped on the audio thread before dispatching each buffer and another when the buffer is handled. If the difference passes 200, a call into Apple's speech daemon is likely stuck, so it exits 99.
- **Silent wedge.** If real audio (peak at or above 0.01) arrived within 5 s but there were no recognition events for 20 s, it exits 99.
- **Preventive recycle.** After 300 s it exits 0.

`dispatch` restarts it in each case.

**Errors.** Code 216 (cancelled) is ignored. 203 and 1110 ("no speech") restart the task at once. Other errors restart it after 0.5 s.

### 5. Voiceprint filter (`filter.py`)

Built to compare each utterance's [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) embedding to an enrolled voiceprint and drop other voices. It needs a WAV path per line. The v1 listener does not write audio, so every line passes as `PASS_NO_AUDIO`. Lines of 2 words or fewer always pass. Scoring errors pass (fail open).

### 6. Relevance filter (`relevance.py`) { #relevance-filter }

Decides whether a line was meant for this session. In order:

1. Empty lines are dropped. Lines starting with `[INTERRUPTED]` always pass (a marker from the unpublished v2 pipeline).
2. **Tune out / tune in.** Matching lines toggle a stored mute and are not passed on. While muted, everything is dropped.
3. Any line containing the word "claude" passes.
4. Lines about the assistant itself pass: being cut off, interrupted, not heard, the microphone, the listener, and similar phrases.
5. Lines of 18 words or more pass.
6. A short list of regexes drops pet talk ("good boy", "no no down") and "I'll call you back".
7. If fewer than 2 lines have been accepted so far, the line passes (cold start).
8. Otherwise a local LLM judge gets a few-shot prompt with the last 6 accepted lines, the previous line's verdict if under 45 s old, and returns PASS or DROP. Any error (server down, timeout over 2.5 s) passes the line and tries to start the judge server once.

The judge server is `mlx_lm server` from [mlx-lm](https://github.com/ml-explore/mlx-lm), started with `~/.local/mlx-server/bin/python` on `127.0.0.1:8190`, running `mlx-community/Llama-3.2-3B-Instruct-4bit` by default. If that Python does not exist, steps 1 to 7 still run and step 8 always fails open.

### 7. Injector (`inject`)

1. Drops `(...)` or `[...]` noise markers and lines under 3 words that do not end in `?` (unless `INJECT_FORCE=1`).
2. Kills anything speaking: `afplay`, `say`, Piper, `mlx_audio` TTS and `speak-stop-ui`.
3. Looks up the bound window by ID. If it is gone, prints `missing` and exits 2. It never falls back to another window.
4. If that window is focused, presses Escape, types with `do script`, then presses Return through System Events.
5. If it is not focused, types with `do script` and sends an extra empty `do script` as a newline. No keystrokes go to whatever app is in front.

`do script` writes to the tab's tty, so this works with the window in the background and does not touch the clipboard.

### 8. Narration (`CLAUDE.md` and `speak-on-stop`)

The voice side is plain Claude Code behavior. `CLAUDE.md` in the repo root tells Claude to speak every step with `~/.local/bin/speak`. The launcher starts `claude` in that folder so the file is loaded as project instructions. `speak-on-stop` is an optional Stop hook that reads the final reply instead.

## The 2.0 research

The repo also contains research logs for a full-duplex "Talking Stick" version that can be interrupted mid-reply: [`EXPERIMENT_PLAN.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/EXPERIMENT_PLAN.md), [`BARGE_IN_ATTEMPTS.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/BARGE_IN_ATTEMPTS.md) and [`RESEARCH_2026_05_21.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/RESEARCH_2026_05_21.md). Per the log, Apple's voice processing I/O did not hold up (attempts 1 and 5), and the setup that worked live was WebRTC AEC3 with an energy gate (attempt 7). That code lives in a local `dictation-v2/` folder that is git-ignored and not published.
