---
title: Troubleshooting NarrateClaude
description: Fixes for common NarrateClaude problems. Speech recognition not authorized, setup cannot find the claude window, start refused, listener restarting, words not typed, short commands ignored, and mic silence.
---

# Troubleshooting

Each section starts with the exact message the code prints, where there is one.

First, look at the logs:

```bash
cd ~/NarrateClaude/dictation/state
tail -n 50 dictation.log            # accepted lines, respawns, watchdog
tail -n 50 dictation.log.stderr     # listener and filter errors
tail -n 20 dictation.log.inject     # inject results: ok / missing
tail -n 20 relevance.log            # PASS or DROP with the reason
```

## `Speech recognition not authorized (status=N)`

From `Listen.swift`, exit code 2. Turn on **Speech Recognition** and **Microphone** for Terminal in **System Settings > Privacy & Security**, then restart the listener. Status values come from Apple's `SFSpeechRecognizerAuthorizationStatus`.

## `Could not create SFSpeechRecognizer for en-US` or `SFSpeechRecognizer is not currently available`

Exit code 3. The en-US recognizer could not be created or is not available right now. Check that Dictation and Siri language data for English (US) is installed. **TODO-VERIFY:** which macOS settings make the recognizer unavailable.

## `Failed to start audio engine: ...`

Exit code 4. Another app may hold the input device, or no input device exists. Run the mic probe below.

## `setup: couldn't find a Terminal window running 'claude'.`

`dictation setup` looks in Apple Terminal for a tab whose processes include `claude`. Start `claude` in Terminal.app first. iTerm2, Ghostty and Warp are not supported ([issue #2](https://github.com/nicedreamzapp/NarrateClaude/issues/2)).

If several windows run `claude`, the first one found is bound. Use `narrative-claude.sh`, which binds the window it opens itself, or close the extra windows.

## `dictation start: refused — the listener may only be started by ...`

Exit code 3. `start` needs `NARRATE_DICTATION_LAUNCHER` set to `NarrativeClaude.app` or `Narrative Gemma.command`:

```bash
NARRATE_DICTATION_LAUNCHER="NarrativeClaude.app" ~/NarrateClaude/dictation/bin/dictation start
```

`toggle` turns on through `start`, so it needs the same variable.

## `start: listener not compiled. Run: dictation setup` or `start: no bound window`

Run `dictation setup` with `claude` open in Terminal. It writes `state/target.json` and compiles `bin/listen`.

## `NarrativeClaude: failed to open Terminal window.`

A dialog from `narrative-claude.sh`. It could not get a window ID back from Terminal. Check that the app running the script is allowed to control Terminal in **System Settings > Privacy & Security > Automation**.

## Listener keeps exiting and restarting

`dictation.log` shows `dispatch: listener exited after Ns, respawning`. Some restarts are normal: the listener recycles itself every 300 seconds (`LISTEN_MAX_SESSION_SEC`) and exits after a wedge.

| In `dictation.log.stderr` | Meaning |
|---|---|
| `WATCHDOG: max session age 300s reached` | Normal preventive recycle. |
| `WATCHDOG: listener queue wedged (...)` | Apple's speech daemon stalled. Restarted automatically. |
| `WATCHDOG: silent wedge — ...` | Audio arrived but no recognition events for 20 s. Restarted automatically. |
| `Speech recognition not authorized` | Permission problem, see above. |

If the lifetime is under 3 seconds every time, the dispatcher backs off 5 seconds between tries. That almost always means permissions or a missing mic.

## I talk and nothing is typed

Work down the pipeline:

1. **Was it heard?** If the line is not in `dictation.log`, look at `dictation.log.stderr`. Set `LISTEN_DEBUG=1` to see partials.
2. **Was it dropped by the relevance filter?** Check `relevance.log`. A `DROP tuned_out_gate` reason means you said "tune out" at some point, maybe by accident. Say "Claude tune in", or stop the listener and delete `state/relevance_state.json`. The mute is saved and survives restarts and reboots.
3. **Was it too short?** Lines under 3 words that do not end in `?` are dropped silently by `inject` after they are logged. Say a longer sentence.
4. **Was the window found?** `missing` in `dictation.log.inject` means the bound window is gone. Run `setup` again or relaunch.
5. **Is a reply still playing?** The mic is off while `afplay` runs.

## Words show up but are not submitted

`inject` types with `do script` and then presses Return through System Events only when the bound window is in front. When it is in the background it sends a second empty line. If text still sits at the prompt, bring the window to the front once, and check Terminal is allowed to control System Events in **Privacy & Security > Automation** and **Accessibility**. **TODO-VERIFY:** which of these permissions is required.

## The assistant hears itself

The listener only pauses while a process named exactly `afplay` exists. If your `speak` script plays audio another way (for example plain `say`), the mic stays open and transcribes the reply. Render to a file and play it with `afplay`, as in [Install](install.md#2-create-the-speak-command).

## Other audio on my Mac stops when I talk

Expected. Each injected line runs `pkill -f afplay` and `pkill -x say` system-wide, to cut off the assistant.

## Check the mic at all

```bash
cd ~/NarrateClaude/dictation/src
swiftc -O MicProbe.swift -o /tmp/micprobe
/tmp/micprobe
```

Talk for 6 seconds. It prints one of three verdicts:

| Verdict | Meaning |
|---|---|
| `mic delivered SILENCE — TCC is blocking input` | Peak RMS under 0.0001. Grant Microphone access. |
| `mic alive but voice didn't cross 0.012 ...` | Mic works but is quiet. Speak up or move closer. |
| `mic alive and crossing threshold — should be working` | The mic is fine. Look elsewhere. |

## Relevance judge never runs

Look at `/tmp/relevance-judge.log`. The judge only auto-starts when `~/.local/mlx-server/bin/python` exists and has `mlx_lm`, and the model must be downloadable or already cached. Without it every line that reaches the judge passes with reason `llm_error:..._fail_open`. That is safe, just less selective.

## Voiceprint filter passes everything

Expected with this repo. The v1 listener emits text without audio, so `filter.py` logs `PASS_NO_AUDIO` for every line. See [Configuration](configuration.md#voiceprint-filter-filterpy).

## `speak-on-stop` is silent

It exits quietly on any problem. Check that `SPEAK` and `FLAG` at the top of the file point to real paths on your Mac (the repo has the author's paths), and that the `FLAG` file exists.

## macOS 26 and the 2.0 listener

[Issue #1](https://github.com/nicedreamzapp/NarrateClaude/issues/1) (closed) reported no transcripts from the unpublished v2 listener with voice processing on macOS 26.4. It does not affect the v1 listener in this repo, which does not enable voice processing.

## Still stuck

Open an issue at [github.com/nicedreamzapp/NarrateClaude/issues](https://github.com/nicedreamzapp/NarrateClaude/issues) with `dictation.log` and `dictation.log.stderr` attached.
