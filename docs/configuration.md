---
title: Configuration, every option, flag and environment variable
description: Reference for all NarrateClaude settings read from the source code. Listener tuning variables, the launcher gate, injector override, voiceprint threshold, relevance judge model, hard-coded paths and state files.
---

# Configuration

Everything on this page was read from the source. Defaults are the values in the code. Where a comment and the code disagree, the code wins and the mismatch is noted.

## Listener (`Listen.swift`)

Set these in the environment of the process that runs `dispatch` (it passes its environment down to `listen`).

| Variable | Default | What the code does |
|---|---:|---|
| `LISTEN_STABILITY_SEC` | `2.5` | Seconds the partial transcript must stay unchanged before the listener calls `endAudio()` and emits the sentence. |
| `LISTEN_MAX_UTTER_SEC` | `60` | Hard cap on one recognition task. After this many seconds the utterance is finalized even if text is still changing. |
| `LISTEN_MAX_SESSION_SEC` | `300` | Preventive recycle. The watchdog exits with code 0 after this many seconds and the dispatcher starts a fresh listener. |
| `LISTEN_WEDGE_BACKLOG` | `200` | If audio buffers received minus buffers processed exceeds this, the listener assumes the recognizer queue is stuck and exits with code 99. |
| `LISTEN_SILENT_WEDGE_SEC` | `20` | If real audio arrived in the last 5 seconds but no recognition events for this many seconds, exit 99. Skipped while `afplay` is playing. |
| `LISTEN_AUDIO_THRESHOLD` | `0.01` | Peak sample level (max absolute value in a buffer) that counts as real audio for the silent-wedge check. |
| `LISTEN_DEBUG` | unset | Set to `1` for verbose logs (partials, finals, pauses, errors, heartbeat every 80 buffers) on stderr, which goes to `dictation/state/dictation.log.stderr`. |

Fixed values in the same file, not configurable without editing:

| Constant | Value | Meaning |
|---|---:|---|
| Locale | `en-US` | Recognizer language. |
| `silentWedgeAudioRecencySec` | 5.0 s | How recent audio must be to count as "user is talking" for the silent-wedge check. |
| `pausePollInterval` | 0.15 s | How often the listener runs `pgrep -x afplay`. |
| `watchdogPollInterval` | 5.0 s | How often the watchdog checks backlog, silent wedge and session age. |
| Tap buffer size | 1024 frames | Audio tap on the input node. |

On-device recognition is requested (`requiresOnDeviceRecognition = true`) only when `supportsOnDeviceRecognition` is true. Otherwise Apple's recognizer may use its server. The task hint is `.dictation`.

### Example

```bash
LISTEN_STABILITY_SEC=1.8 LISTEN_DEBUG=1 \
NARRATE_DICTATION_LAUNCHER="NarrativeClaude.app" \
  ~/NarrateClaude/dictation/bin/dictation start
```

**TODO-VERIFY:** `dictation start` launches `dispatch` with `nohup`, which keeps the caller's environment, so the `LISTEN_*` variables above should reach the listener. This has not been tested on a Mac for this page.

## Launcher gate

| Variable | Accepted values | Effect |
|---|---|---|
| `NARRATE_DICTATION_LAUNCHER` | `NarrativeClaude.app` or `Narrative Gemma.command` | Required by `dictation start` (and by `toggle` when it turns on). Any other value prints `dictation start: refused` and exits with code 3. |

`narrative-claude.sh` sets it to `NarrativeClaude.app`. `Narrative Gemma.command` is a launcher in the sibling [claude-code-local](https://github.com/nicedreamzapp/claude-code-local) repo, not this one.

`narrative-claude.sh` also exports `CLAUDE_SESSION_LABEL=NarrativeClaude` in the new Terminal window. Nothing in this repo reads it. **TODO-VERIFY:** what consumes it (possibly claude-code-local or a status line).

## Injector (`inject`)

| Variable | Default | What the code does |
|---|---|---|
| `INJECT_FORCE` | `0` | Set to `1` to skip the noise gate: lines wrapped in `(...)` or `[...]` and lines under 3 words that do not end in `?` are normally dropped. |

The inject comment mentions a `dictation send` debug command. That subcommand does not exist in `dictation`. To type a line by hand, call inject directly:

```bash
INJECT_FORCE=1 ~/NarrateClaude/dictation/bin/inject "hello there"
```

Behavior that is not configurable:

- Before typing, it runs `pkill -f afplay`, `pkill -f speak-stop-ui`, `pkill -f "piper -m"`, `pkill -f mlx_audio.tts.generate` and `pkill -x say`. These match system-wide, so any other `afplay` on your Mac is stopped too.
- Text is written with Terminal's `do script ... in selected tab of` the bound window.
- If the bound window is the frontmost Terminal window, it presses Escape (key code 53) before typing and Return (key code 36) after.
- If it is not focused, it waits 0.25 s and sends an empty `do script ""` as a second newline instead.

## Voiceprint filter (`filter.py`)

| Variable | Default in code | What the code does |
|---|---:|---|
| `MATCH_THRESHOLD` | `0.48` | Cosine similarity floor between an utterance embedding and `state/voiceprint.npy`. |

The comment at the top of `filter.py` says the default is 0.72. The code uses 0.48.

The filter only runs when all three exist: `dictation/filter/.venv/bin/python`, `dictation/filter/filter.py` and `dictation/state/voiceprint.npy`. It expects lines shaped `text<TAB>wav_path`. The v1 listener emits text only, so every line is logged as `PASS_NO_AUDIO` and passed through. In practice the voiceprint filter does not filter with the code in this repo.

Create a voiceprint (needs `numpy` and `resemblyzer` in that venv):

```bash
cd ~/NarrateClaude/dictation/filter
python3 -m venv .venv && .venv/bin/pip install numpy resemblyzer
.venv/bin/python enroll.py /path/to/clean_sample.wav [more.wav ...]
```

`enroll.py` averages the Resemblyzer embeddings of all samples, normalizes the result, and writes `dictation/state/voiceprint.npy`.

## Relevance filter

`relevance.py` runs on every line with `/usr/bin/python3`. It has no third-party dependencies.

| Variable | Default | What the code does |
|---|---|---|
| `RELEVANCE_MODEL` | `mlx-community/Llama-3.2-3B-Instruct-4bit` | Model name sent to the judge server and passed to `mlx_lm server --model` when auto-starting it. |

Fixed values:

| Constant | Value |
|---|---|
| Judge URL | `http://127.0.0.1:8190/v1/chat/completions` |
| Judge Python | `~/.local/mlx-server/bin/python` (auto-start is skipped if missing) |
| Judge timeout | 2.5 s |
| Judge server log | `/tmp/relevance-judge.log` |
| Context lines kept | 6 |
| Long-utterance pass | 18 words or more |
| Previous-verdict window | 45 s |
| Last-TTS file | `../dictation-v2/state/last_tts.txt`, only used if newer than 180 s. `dictation-v2` is not published, so with this repo alone the file does not exist. |

Spoken controls:

| Say | Effect |
|---|---|
| "Claude tune out" (or "tune out") | Drop every line until tune in. Stored in `state/relevance_state.json`, so it survives restarts. |
| "Claude tune in" (or "tune in") | Stop dropping. |
| Anything containing "Claude" | Always passes. |

See [How it works](how-it-works.md#relevance-filter) for the full decision order.

## Stop hook (`speak-on-stop`)

A Claude Code Stop hook that reads the last assistant message aloud. Its settings are constants at the top of the file:

| Constant | Value in repo | Change it to |
|---|---|---|
| `SPEAK` | the author's `~/.local/bin/speak`, as an absolute path | Your own `~/.local/bin/speak` path, written out in full. |
| `FLAG` | the author's `~/.claude/narration.on`, as an absolute path | Any path. The hook only speaks while this file exists. |
| `MAX_LEN` | `1200` | Characters before the text is cut and "and there's more on screen." is appended. |

Before speaking, it replaces fenced code with "[code block on screen]", strips Markdown markers, replaces URLs with "link" and paths with "a file".

Register it in Claude Code's settings as a `Stop` hook command. **TODO-VERIFY:** the exact `settings.json` snippet against the current [Claude Code hooks docs](https://docs.anthropic.com/en/docs/claude-code/hooks). The repo does not include one. Note that `CLAUDE.md` already tells Claude to speak through `speak`, so running both may read replies twice.

The docstring mentions Kokoro-82M. The code just runs whatever `SPEAK` points to.

## Files and paths

| Path | Written by | Contents |
|---|---|---|
| `dictation/bin/listen` | `dictation setup` | Compiled listener (git-ignored). |
| `dictation/state/target.json` | `setup`, `narrative-claude.sh` | `{ "app": "Terminal", "window_id": N }`. Re-read on every inject and every watchdog tick, so you can re-bind without restarting. |
| `dictation/state/listener.pid` | `dictation start` | PID of `dispatch`. |
| `dictation/state/dictation.log` | `dispatch`, `dictation start` | Accepted lines and pipeline events. |
| `dictation/state/dictation.log.stderr` | `dispatch` | Listener and filter stderr. Cleared on each `start`. |
| `dictation/state/dictation.log.inject` | `dispatch` | Output of each inject call (`ok` or `missing`). |
| `dictation/state/.shutdown` | window watchdog | Tells the respawn loop to exit. |
| `dictation/state/relevance_state.json` | `relevance.py` | Tune-out flag, last 6 accepted lines, last verdict. |
| `dictation/state/relevance.log` | `relevance.py` | `PASS` or `DROP`, reason, line. |
| `dictation/state/dropped.log` | both filters | Dropped lines. |
| `dictation/state/filter.log` | `filter.py` | Voiceprint decisions. |
| `dictation/state/voiceprint.npy` | `enroll.py` | 256-dim voiceprint. |
| `~/.local/bin/speak` | you | The voice. Called by Claude through `CLAUDE.md` and by `speak-on-stop`. |

## Exit codes

`listen`:

| Code | Meaning |
|---:|---|
| 0 | Clean exit, including the preventive recycle |
| 2 | Speech recognition not authorized |
| 3 | Could not create `SFSpeechRecognizer`, or it is not available |
| 4 | Audio engine failed to start |
| 99 | Watchdog found a wedged recognizer (backlog or silent wedge) |

`dictation`: 1 for setup or start failures, 2 for an unknown subcommand, 3 when `start` is refused by the launcher gate. `inject`: 1 when not bound, 2 when the bound window no longer exists.
