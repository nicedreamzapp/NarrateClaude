---
title: Barge-in (talk over it)
description: NarrateClaude 2.0 lets you talk over the voice on macOS to stop it. How to turn it on, how it works, what was measured and the current limits.
---

# Barge-in: talk over it to stop it

New in 2.0, on macOS. With barge-in on, the mic stays open while the voice is talking. Start talking and the voice stops, and what you said goes to Claude as your next line, the same as any other sentence.

## Turn it on

It is off by default. Add the echo canceller to the installer's venv once (a prebuilt wheel, nothing to compile), then start with `NARRATE_BARGE_IN=2`:

```bash
~/.local/share/narrateclaude/venv/bin/pip install -r ~/NarrateClaude/dictation/voice/requirements-bargein.txt
NARRATE_BARGE_IN=2 narrate-claude
```

If you installed somewhere else, the venv is under `NARRATE_DATA` and the checkout under `NARRATE_DIR` (see [Install](install.md)).

With the flag off the listener is exactly the 1.x behavior. If the echo canceller can't load, or what is playing isn't a WAV it can read, it falls back to that behavior and stays deaf while the voice talks. It never sends uncancelled playback to speech to text.

## How it works

The code is [`dictation/voice/bargein.py`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/dictation/voice/bargein.py).

1. **Reference.** The listener reads which WAV `afplay` is playing and lines it up against the mic samples.
2. **Echo cancelling.** WebRTC's AEC3, from the `livekit` wheel, subtracts that WAV from the mic. A fresh canceller starts for every reply, because the speaker to mic delay changes from reply to reply.
3. **Gate.** The cleaned audio has to clear the learned room noise, the playback level plus the learned speaker leak, and the leftover echo, on 4 of the last 10 frames of 30 ms, after a 300 ms hold-off at the start of each reply. It only fires while the canceller is removing at least 10 dB.
4. **On a hit.** It stops `afplay` and the `speak` script that owns it, hands the last 1.5 s of cleaned audio to the endpointer so your first words survive, and transcribes the rest. The session sends Escape and your sentence.

## What was measured

On an M5 MacBook Pro with the built-in speakers and mic, in an empty office:

| Test | Result |
|---|---|
| Echo alone (20 s of silence and 3 full replies, about 50 s) | 0 false barge-ins |
| Live double-talk, a cloned voice talking over the reply | 9 of 10 fired; the voice stopped 0.16 to 0.39 s after the speech started (one at 1.09 s) |
| Replaying those room recordings as one session | 11 of 12 hits, median 0.14 s, 0 false |
| Same replay with the mic 20 dB quieter | 11 of 12 hits, 0 false |

No assistant words showed up in any transcript. The full log is Attempt 8 in [`BARGE_IN_ATTEMPTS.md`](https://github.com/nicedreamzapp/NarrateClaude/blob/main/BARGE_IN_ATTEMPTS.md), and the test write-up is in [PR #14](https://github.com/nicedreamzapp/NarrateClaude/pull/14).

## Limits

- macOS only.
- Only voices that play a WAV through `afplay` (the built-in Piper voice, Kokoro). Chatterbox streams through ffplay and stays half-duplex for now.
- Talking over the first ~0.3 s of a reply can pick up the voice's opening words.
- Talking right as a new reply starts can send an empty clip to whisper.
- Speech still going when the 15 s barge-in window ends is dropped.
- A loud fan or HVAC hum can raise the trigger level too high.

## Tuning

| Variable | Default | Effect |
|---|---:|---|
| `NARRATE_BARGE_IN` | `1` | `1`: a new sentence stops the voice and sends Escape. `2`: barge-in, as above. |
| `NARRATE_BARGE_FLOOR_DB` | `-65` | Absolute minimum level (dBFS) that can count as talking. The real gate is learned from the room. |
| `NARRATE_BARGE_MARGIN_DB` | `10` | How far above the leftover echo it must be. |
| `NARRATE_BARGE_FRAMES` | `4` | Loud 30 ms frames needed within the last 10. |
| `NARRATE_BARGE_HOLDOFF_MS` | `300` | Ignore the start of each reply while the canceller adapts. |
| `NARRATE_BARGE_DEBUG` | unset | `1` logs levels every ~0.5 s while the voice is talking. |

Every barge-in is logged to `dictation/state/bargein.log`. If it never fires, turn on `NARRATE_BARGE_DEBUG=1`, talk over a reply, and compare your level with the "needs >" number in that log.
