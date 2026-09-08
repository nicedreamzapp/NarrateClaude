# Barge-in & Echo-Cancellation Attempts

Running log of everything we've tried to let Matt interrupt the assistant mid-TTS without false-triggering off speaker bleed. **Read this before starting any new attempt** so we don't repeat a dead end.

The hard constraint: this Mac is a desk setup with speakers, not headphones. Solution must work without headphones.

---

## Attempt 1 — Apple `setVoiceProcessingEnabled(true)` (tried twice)

**What:** Enable AVAudioEngine's built-in voice-processing audio unit, which on paper provides real acoustic echo cancellation, automatic gain control, and noise suppression.

**Result:** Failed both times. On this Mac it either:
- ducks system output volume to a near-mute level (TTS becomes inaudible), or
- hangs AVAudioEngine at startup (no audio at all)

**Don't retry** unless you've reproduced a fix from Apple themselves. Code comment lives in `dictation/src/Listen.swift` near the `installTap` call.

---

## Attempt 2 — Amplitude-based barge-in

**What:** While `afplay` (TTS) is running, count consecutive mic buffers whose max-abs sample exceeds `bargeInAudioThreshold`. If the streak passes `bargeInSustainedBuffers` (~92ms), kill `afplay`.

**Result:** False-triggered constantly off speaker bleed back into the mic. Threshold could not be tuned high enough to reject playback without also rejecting Matt.

**State:** Code is still in the listener but **disabled** — `bargeInAudioThreshold = Float.infinity` (`Listen.swift:90`). Keep it disabled.

---

## Attempt 3 — Pause-during-TTS (current production behavior)

**What:** While `afplay` is running, the listener simply skips feeding mic buffers to SFSpeech (`Listen.swift:583`). The active recognition task stays alive — just doesn't get fed.

**Result:** Reliable in the sense that nothing crashes and there are no false transcripts of TTS playback. But it has a serious UX bug: **any speech Matt utters while the assistant is narrating is silently dropped.** Never reaches SFSpeech.

This is what's in production today (2026-05-20). It's the baseline we're trying to beat.

---

## Attempt 4 — WebRTC AEC3 + Silero VAD (researched, rejected 2026-05-20)

**What was considered:** Wrap WebRTC's AEC3 as a Swift module, feed it the mic + the reference TTS signal, run the cleaned mic stream through Silero VAD to detect speech-onset.

**Why rejected:** Research turned up that there's no maintained Swift wrapper for `libwebrtc-audio-processing`, no Homebrew formula, and the integration cost is ~150-250 lines of C++ glue plus a CMake/SPM dance — *just to reach feature parity with what Apple's VPIO already does for free using the HAL-level reference signal*. Apple VPIO sidesteps the reference-signal time-alignment problem entirely because it taps the output mix at the hardware abstraction layer. AEC3 only wins if we *can't* use Apple VPIO; we can.

**The lesson:** the WebRTC AEC3 path is cargo-culted from how Pipecat / LiveKit / WebRTC apps handle browsers. On a native Mac with full control of the audio engine, Apple VPIO is the correct primitive.

---

## Attempt 5 — Apple VPIO (correctly configured this time) + FluidAudio Silero VAD + Personal VAD (in progress, started 2026-05-20)

**What:** Same Apple `setVoiceProcessingEnabled(true)` audio unit that failed in Attempt 1, **but configured the way it's actually meant to be used.** Specifically:
- Route Piper TTS through an `AVAudioPlayerNode` attached to the **same `AVAudioEngine`** that owns the mic input — so VPIO can see the playback signal at the HAL and cancel it. (Prior attempts left TTS on `afplay`, out-of-band.)
- Enable VPIO **before** `engine.start()`, with a consistent 48 kHz mono format on input and output.
- Add [FluidAudio](https://github.com/FluidInference/FluidAudio) as a Swift Package — pre-converted Silero VAD on CoreML pinned to the Apple Neural Engine, ~40-80 ms speech-onset detection, MIT licensed.
- Drop the `speakIsPlaying` skip from `handleBuffer` — feed the cleaned mic stream to SFSpeech continuously. The VAD on the cleaned stream is the barge-in trigger.
- (Phase 3) Add a personal VAD head conditioned on the existing Resemblyzer voiceprint at `dictation/state/voiceprint.npy`, HyWA-style — so only Matt's voice ever fires the barge-in, even when TTS bleed is loud.

**Why this is genuinely different from Attempts 1–3:**
- Attempt 1 enabled VPIO but kept `afplay` for TTS, so VPIO had no reference signal — it ducked everything trying to cancel an audio stream it couldn't see.
- Attempt 2 used amplitude thresholds (no AEC) — false-triggered on speaker bleed.
- Attempt 3 (current production) sidesteps the problem by muting the mic during TTS — but drops the user's speech entirely when they talk during the assistant's reply.
- Attempt 5 cancels the speaker bleed *properly* at the HAL using Apple's own AEC, then uses a learned VAD (not amplitude) on the cleaned signal.

**Implementation notes:**
- New code lives in `dictation-v2/` (Swift Package), to keep the v1 listener running.
- `dictation-v2/Sources/TalkingStick/main.swift` is the new listener.
- v1 (`dictation/bin/listen`) is untouched until v2 is benchmarked.

**Status:** Phase 1 confirmed working on macOS 26.4.1 / M5 Max (2026-05-21).

**Key discovery during integration:**

The high-level `setVoiceProcessingEnabled(true)` path works, but **the player node must connect directly to `engine.outputNode`, NOT through `engine.mainMixerNode`.** Routing through the mixer triggers `kAudioUnitErr_FailedInitialization (-10875)` on macOS 26.4 because the mixer's default format (44.1 kHz stereo) doesn't match VPIO's output node (48 kHz stereo), and the format negotiation breaks AUInitialize.

The fix lives in `dictation-v2/Sources/TalkingStick/Audio/AudioEngine.swift`:

```swift
let outFormat = engine.outputNode.inputFormat(forBus: 0)
engine.connect(player, to: engine.outputNode, format: outFormat)
```

This was almost certainly the failure mode of the prior Attempts 1 — VPIO was being enabled, but the engine was implicitly trying to route through the mixer at the wrong format and failing silently / wedging.

Format introspection on M5 Max / macOS 26.4 confirms this:
- `inputNode.outputFormat(0)`  → 9 ch, 48 kHz, Float32  ← VPIO input
- `outputNode.inputFormat(0)`  → 2 ch, 48 kHz, Float32  ← VPIO output (player goes here)
- `mainMixerNode.outputFormat` → 2 ch, **44.1 kHz**, Float32  ← the format mismatch trap

**Verified working (smoke test passes 2026-05-21):**
- TalkingStickEngine starts + stops cleanly with VPIO enabled and player attached
- FluidAudio Silero VAD CoreML model loads in 40 ms after first download, pins to ANE
- SFSpeech bridge constructs without throwing (once auth is granted)

**Still open:**
- Personal VAD training data — we need labeled (matt_speaks / matt_silent / tts_bleed / room_noise) segments to train the HyWA head.
- Smart Turn v3 CoreML conversion — Pipecat ships a PyTorch model; need to verify the ONNX → CoreML path on M5.
- End-to-end barge-in benchmark: play known TTS, speak known phrase over it, verify SFSpeech transcribes the phrase cleanly without TTS bleed contamination.

### Attempt 5 — end-to-end live test 2026-05-21 (first real session)

First time the full v2 stack was driven by an actual session (not the smoke test). New failure mode that the Phase-1 smoke test didn't expose: **the engine runs but no transcripts come out.**

**Setup:**
- Hardware: M5 Max, 128 GB, macOS 26.4.1 (Build 25E253)
- Input device: MacBook Pro Microphone (verified default via SwitchAudioSource)
- Output: built-in MacBook Pro speakers
- `talkingstick` (debug build) launched via `narrative-claude-v2.sh` at 23:08

**Observed behavior:**
- Process alive, CPU steady at ~10.9% (so the audio thread *is* doing work)
- Mic permission granted for the binary (TCC `auth_value=2`)
- stderr shows `talkingstick: listening (VPIO + FluidAudio Silero + WhisperKit + Smart Turn v3)` cleanly
- Smart Turn fires `EOT fired — finalizing utterance` constantly (~once every few seconds, even without speech)
- **Zero transcripts ever flow out of WhisperKit** — `dispatch-v2`'s stdout log accumulates nothing past the boot banner, `dictation.log.inject` stays empty
- Smoking-gun symptom: Matt has to double-tap Control to invoke Apple Dictation as a manual fallback every time he wants to talk

**Diagnostics performed:**
- `ffmpeg -f avfoundation -i ":1"` (MacBook Pro Microphone) → mean -50.8 dB, max -36.7 dB — **the mic hardware itself is fine.**
- `ffmpeg -f avfoundation -i ":0"` returns -91 dB silence, but `:0` is BlackHole 2ch (a virtual loopback), not the default mic — red herring.
- WhisperBridge filters `[BLANK_AUDIO]`, `(silence)`, `"you"`, `"."`, `".."` as hallucinations (WhisperBridge.swift:503–512). On a stream that's near-silent due to over-aggressive VPIO suppression, every inference returns one of these, gets dropped, and the EOT path has nothing to finalize.
- One `SWIFT TASK CONTINUATION MISUSE: main() leaked its continuation without resuming it` at boot — turns out this is intentional (`App.swift:214`, park-main-forever pattern) and not the cause.

**Likely root cause:** VPIO on macOS 26.4 is suppressing the mic stream so hard that WhisperKit only ever sees silence-or-near-silence. Apple Dictation works because it doesn't go through `AVAudioEngine` + VPIO at all — it captures via the SFSpeech daemon's own audio path.

This contradicts the smoke-test verdict ("Phase 1 confirmed working") because the smoke test only validated engine start/stop and component init, never an end-to-end *transcript while the mic is hot*.

**This is exactly the failure mode Hard Rule #2 was written to prevent.** Attempt 1 failed with VPIO. Hard Rule said "No more `setVoiceProcessingEnabled(true)` unless someone confirms it's been fixed in macOS." Attempt 5 turned VPIO back on with the format fix from the key discovery above. That format fix was real and necessary, but **it did not make VPIO usable on macOS 26.4 for actual STT throughput** — it just made the engine stop throwing `-10875` on init.

**Open questions to resolve before pushing on this further:**
- Is the VPIO output actually full-scale silence, or is it just heavily ducked? (Need a one-off binary that taps `inputNode`, writes a 10 s WAV to disk, and measures peak/RMS — same kind of tap WhisperBridge is using, but to a file we can `ffplay` ourselves.)
- Does VPIO recover if we *toggle* `setVoiceProcessingEnabled(false)` then `true` after the engine is running? (The AudioEngine.swift comment says toggling-on-running historically wedged, but it doesn't say anything about toggling-off-then-on as a kick.)
- Does it work with VPIO disabled and barge-in given up on? — this would make v2 equivalent to v1 minus the personal VAD work, which is still a real win because v1 crashes every 20 s. Worth a build flag.

**Volume side-quest from the same session** (not strictly an Attempt-5 issue, but caught and fixed in the same triage):
- Raw Piper LibriTTS R medium plays at ~-14.6 LUFS — significantly quieter than the old Pocket TTS / Chatterbox path, which was Matt's previous reference.
- Old `~/.local/bin/speak` piped Piper directly to `afplay` with no gain stage.
- Patched `~/.local/bin/speak` to run an ffmpeg filter (`volume=2.0,equalizer=f=4000:t=q:w=1:g=3`) and play with `afplay -v 1.3`. Output is ~-10 LUFS. Backup at `~/.local/bin/speak.piper-raw-backup`.
- Also bumped macOS output volume from 47 → 80 in the same session; Matt later dialed it back manually. The script's gain stack is what should stay.

**Hard rule reinforced:** smoke tests on the audio engine prove nothing about transcription throughput. Any future "VPIO is fixed" claim must come with a recorded WAV of the live tap, peak/RMS measured, and at least one real transcript that survived the WhisperBridge hallucination filter.

---

## Attempt 6 — Bring-our-own AEC: SpeexDSP echo canceller (in progress, started 2026-06-02)

**The pivot:** Attempt 5 proved Apple VPIO is unusable on macOS 26.4 — it ducks the mic to near-silence so WhisperKit only ever sees silence. Hard Rule #2 says don't turn VPIO back on until Apple fixes it. So Attempt 6 stops relying on Apple's canceller entirely and brings our own. This is the path Attempt 4 *researched and rejected* in favor of VPIO — now that VPIO is disproven on this OS, it's the live card.

**Why SpeexDSP instead of WebRTC AEC3:** WebRTC (Attempt 4's plan) is the heavyweight option — no Homebrew formula, no Swift wrapper, ~200 lines of C++ glue, a CMake/SPM dance. SpeexDSP is `brew install speexdsp`, a clean C API (`speex_echo_cancellation` / `speex_echo_capture` + `speex_echo_playback`), MIT-style license, and a residual-echo + denoise preprocessor that wires straight into the echo state. Far less integration cost for the same job. If Speex's linear filter proves too weak for real room acoustics we still have WebRTC AEC3 as Attempt 7.

**The structural advantage we exploit (same as the whole v2 thesis):** we know the EXACT signal we sent to the speaker — the Piper TTS WAV, byte for byte. That's the far-end reference. Speex's adaptive filter learns the speaker→mic room response and subtracts our own voice out of the mic, leaving only what Matt actually said.

**What was built:**
- `Sources/CSpeexDSP/` — C bridge target (`ts_aec.{h,c}`) over `libspeexdsp`. Links the brew `opt` symlink so it survives version bumps. Wires the preprocessor's `SET_ECHO_STATE` for residual suppression (`-40 dB` idle, `-15 dB` active) + denoise.
- `Sources/TalkingStick/Audio/SpeexEchoCanceller.swift` — Swift wrapper. Runs at 16 kHz mono (ideal for STT). Downmixes + resamples arbitrary input via `AVAudioConverter`, converts to int16, frames into 320-sample (20 ms) chunks, filter length 4096 (~256 ms tail). `pushReference()` for far-end, `process() -> cleaned buffer` for near-end.
- `AudioEngine.swift` — `TS_AEC=speex` forces VPIO **off** and adds `installReferenceTap()` on the player node to capture the exact TTS being played.
- `App.swift` — when AEC is active, the raw mic buffer is run through the canceller and the *cleaned* buffer is what STT/VAD/Smart-Turn see; player-node tap feeds the reference.
- `Sources/AecTest/` — offline proof harness (`swift run aectest`).

**Offline result (2026-06-02) — the canceller demonstrably works:**
```
Test 1 (echo only):   mic RMS=0.10354  cleaned RMS=0.00435  ERLE=27.6 dB  ✅
Test 2 (double-talk): echo-only tail reduction=28.6 dB; near-end speech 0.177→0.183 (preserved)
```
~28 dB of a known echo removed while near-end speech survives intact. This is the opposite of VPIO's failure mode (which killed *everything*). It's synthetic echo (delay 50 ms + gain 0.6), so real-room performance — multiple reflections, longer tails, speaker nonlinearity — will be lower and needs live measurement.

**Live wiring:** `narrative-claude-v2.sh` now launches dispatch-v2 with `TS_AEC=speex` (was `TS_DISABLE_VPIO=1`). TTS already routes through the player node via `speak-v2` → `state/tts.fifo` → `PLAY <wav>`, so the reference tap sees it with no other change. Fall back to `TS_DISABLE_VPIO=1` if the live AEC misbehaves.

**Still open:**
- Live end-to-end test with Matt talking over real TTS through the desk speakers (the thing only Matt at the machine can validate). Measure real-room ERLE + whether barge-in "stop" transcribes cleanly.
- Delay tuning: if speaker→mic latency exceeds the 256 ms filter tail, bump `filterLength`. May need to compensate for Core Audio output latency between the player tap and the mic tap.
- Double-talk robustness at real volumes — Speex can attenuate near-end during loud echo; watch for Matt's voice getting clipped when TTS is loud.
- Build warning: two `#SendableClosureCaptures` warnings in `SpeexEchoCanceller.to16kMonoInt16` (benign — convert closure is synchronous — but worth a clean-up).

---

### Attempt 6 — first live session fixes (2026-06-02)

First real driven session of the Speex AEC exposed three problems, all now fixed:

**Problem 1 — reference/capture desync (the xrun spam).** The C bridge used
Speex's *split* `speex_echo_playback` / `speex_echo_capture` API, with the player
tap feeding playback and the mic tap feeding capture on two independent Core
Audio callbacks. Speex's internal playback queue requires the two to be called
in lockstep; they never are (mic runs continuously, TTS plays only sometimes),
so every frame logged `No playback frame available` / `Had to discard a playback
frame` / `Auto-filling the buffer` and cancellation was garbage.

*Fix:* added `ts_aec_cancel()` wrapping the **combined** `speex_echo_cancellation`
(mic + paired reference in one call — no internal queue). `SpeexEchoCanceller`
now buffers the reference in a shallow ring (`maxRefBacklog = filterLength`, drops
oldest on overrun) and `process()` pulls one reference frame per mic frame,
zero-filling when nothing is playing. Result: **zero xrun lines**, offline ERLE
held/improved (29.5 dB). Files: `Sources/CSpeexDSP/ts_aec.{c,h}`,
`Sources/TalkingStick/Audio/SpeexEchoCanceller.swift`.

**Problem 2 — assistant cutting itself off (self-barge-in).** Personal VAD is
untrained, so barge-in ran on speaker-agnostic Silero, which fired on the
assistant's own cold-filter leakage / residual echo. Added a double-talk guard
to the `vad.onSpeechStart` handler in `App.swift`:
- **Convergence hold-off** (`TS_BARGE_HOLDOFF_MS`, default 700) — ignore barge-in
  for the first 700 ms of each utterance while the adaptive filter is cold.
- **Energy floor** (`TS_BARGE_RMS_FLOOR`, default 0.07) — only barge-in if the
  cleaned-mic RMS clears the floor; quiet residual echo can't trip it, Matt
  talking into the mic does. RMS is computed per-buffer in the input tap.
`TTSPlayer` now tracks `startedAt` / exposes `msSincePlaybackStart` for the
hold-off. Verified: quiet narration produces 0 false cutoffs (cold-start blip is
logged as "barge-in suppressed: within convergence window").

**Problem 3 — the assistant's own voice transcribed into Matt's input.** Two
causes: (a) STT ran on the cleaned mic even during TTS, so residual echo got
transcribed; (b) **`~/.local/bin/speak` used the v1 afplay path, which bypasses
the player node entirely — so it was never cancelled and got fully transcribed.**
*Fixes:* (a) the input tap no longer feeds STT/SmartTurn while `tts.isPlaying`
(barge-in still fires off the VAD; when Matt talks over, barge-in stops TTS and
STT resumes next buffer); (b) `~/.local/bin/speak` now auto-routes to `speak-v2`
→ `tts.fifo` whenever the v2 listener is live, falling back to afplay when it's
down. Verified: a full narration added **0 lines** to the transcript log.

**Still open:** real-room ERLE under load; whether 0.07 is the right floor (tune
live); personal-VAD voiceprint training is still the proper long-term fix to make
barge-in bulletproof regardless of room noise.

## Attempt 7 — WebRTC AEC3 + personal-VAD identity gate (WORKING, 2026-06-02)

**This is the one that worked end-to-end.** Built live with Matt driving, two
parallel build agents (WebRTC lib build + bridge code) plus integration.

**The pivot:** Attempt 6's Speex linear filter got ~29 dB ERLE — not enough.
Real-room residual echo off the open desk speakers peaked at ~0.067 cleaned RMS,
which *overlaps* Matt's normal speaking voice (~0.057–0.064). A pure energy gate
physically cannot separate them at that overlap, which is why every floor value
either let the assistant cut itself off (floor ≤ 0.06) or ignored Matt (floor ≥
0.075). Two changes broke the deadlock:

**1. WebRTC AEC3 (stronger canceller).** Built the PulseAudio standalone
`webrtc-audio-processing` fork **v2.1** for arm64 macOS into
`dictation-v2/vendor/webrtc-prefix/` (combined self-contained static archive
`libwebrtc-apm-combined.a` — APM + AEC3 + bundled abseil 20240722; the system
abseil was too new and removed `absl::Nullable`). New SwiftPM target `CWebRTCAEC`
(C++ `extern "C"` shim over `webrtc::AudioProcessing`, 10 ms / 160-sample
reframing rings), Swift wrapper `WebRTCEchoCanceller.swift` mirroring the Speex
one, selected with `TS_AEC=webrtc`. Shared `EchoCanceller` protocol in
`Sources/TalkingStick/Audio/EchoCanceller.swift` lets the listener + AecTest hold
either backend. **Offline ERLE: 58 dB (vs Speex 29.5 dB)** — residual echo 27×
quieter. Real-room residual dropped from ~0.19 (Speex) to ~0.06.

**2. Personal VAD finally LOADS + gates by identity.** The trained model
(`training/personal_vad/personal_vad.mlpackage`, built 2026-05-21 from the
enrolled voiceprint `dictation/state/voiceprint.npy`) existed all along but was
**never loading** — `PersonalVAD.swift` called `MLModel(contentsOf:)` directly on
the raw `.mlpackage`, which only loads compiled `.mlmodelc`. Error was swallowed
by `try?` so it silently fell back to speaker-agnostic Silero forever. **Fix:**
compile the package first via `MLModel.compileModel(at:)` when the path ends in
`.mlpackage`, then load the result. Once loaded, it gates barge-in by speaker
identity (class 1 = Matt → fire; class 2 = TTS bleed / others → ignore) AND now
also gates the during-TTS STT feed (new `VADWatcher.isTargetSpeaker(_:)`), so the
assistant's echo never self-transcribes even at a low floor.

**Result (verified live):** With `TS_AEC=webrtc TS_BARGE_RMS_FLOOR=0.03
TS_BARGE_HOLDOFF_MS=400`, Matt interrupted at **normal volume (RMS 0.057)** — the
log shows `barge-in: real speech over TTS (RMS 0.0571), killing TTS` — with zero
self-cutoffs and zero echo leaking into the transcript. The floor is now just a
noise gate; *identity*, not loudness, makes the decision. Baked into
`narrative-claude-v2.sh`. **If the personal VAD ever fails to load, 0.03 is far
too low (echo will self-trigger/self-transcribe) — fall back to floor ~0.4.**

**UPDATE same session — personal VAD too flaky live; reverted to energy gate.**
After the clean 0.057 fire, continued live use exposed that the personal-VAD
model misfires BOTH ways: false-positives (self-cutoff on the assistant's own
residual echo at floor 0.03, and echo leaking back into the transcript) and
false-negatives (blocking Matt mid-interrupt). Root cause: it's trained on a
mel-feature **stand-in**, not the real Silero/FluidAudio per-frame embeddings the
runtime feeds it (see `personal_vad_meta.json` "feature_source"). So the single
clean fire was partly luck. **Shipped stable config instead:** WebRTC AEC3 +
plain Silero energy gate, `PERSONAL_VAD_MODEL=/nonexistent` (disables the model),
`TS_BARGE_RMS_FLOOR=0.12` (above the ~0.067 residual so the assistant never
self-cuts; Matt interrupts at a normal/firm voice, his real interrupts measured
0.17–0.21), `TS_BARGE_HOLDOFF_MS=500`. Predictable and self-cut-free.

**The real next step** for flawless whisper-volume interruption: retrain the
personal-VAD head on FluidAudio's actual per-frame features (not the log-Mel
stand-in), re-export with `convert_to_coreml.py`, then re-enable (drop the
PERSONAL_VAD_MODEL override + set floor 0.03). The loading path + identity gate +
STT gate are all wired and working — only the model's accuracy is the gap.
Secondary: tune the WebRTC residual suppressor if loud TTS passages ever leak.

## Hard rules going forward

1. **No more amplitude-only barge-in.** It's been disproven twice (different threshold tunings).
2. **No more `setVoiceProcessingEnabled(true)` unless someone confirms it's been fixed in macOS.**
3. **Headphones are not an acceptable answer.** The solution must work with the open-air desktop speaker setup.
4. **Every new attempt gets a new section here, even if it works.** Future-you needs to see what's been tried.

## Session 2026-06-10 — fast barge-in + "bud out" relevance judge

Three fixes in one live session (first session driven on Fable 5):

**1. Barge-in latency.** The content-gated kill waited for a FINALIZED
transcript (~2.5 s stability window) before stopping TTS — felt broken. Now
`speech.onPartial` kills TTS on the first partial hypothesis with >=2 words
(`TalkingStickApp/App.swift`). Echo safety unchanged: partials during TTS only
exist if the feed gate (holdoff + floor + personal VAD) admitted the buffers.
Verified live: kill fired on partial "What are" while Matt was mid-sentence.

**2. Inject submit-without-focus.** `dictation/bin/inject` only pressed the
guaranteed Return when the bound Terminal window was frontmost. Now, when NOT
focused, it sends a bare newline via `do script ""` (writes to the bound tty
regardless of focus; harmless if already submitted).

**3. Cross-talk / "bud out" filter.** Matt runs multiple agent sessions in the
same room; this session was acting on speech meant for other agents.
`dictation/filter/relevance.py` rewritten into three layers:
  - "claude tune out / tune in" hard mute (stateful, survives respawns)
  - tight pet-talk regexes (old phone/gossip regexes REMOVED — they ate
    Matt's direct answers, e.g. "Yeah I was talking to another agent")
  - LLM judge: local Llama-3.2-3B (MLX server, port 8190, auto-started,
    ~100 ms) sees a rolling 6-line buffer of accepted lines, the previous
    line's verdict + age (conversational stickiness), and the assistant's
    last spoken TTS (written by speak-v2 to state/last_tts.txt). Fail-open
    on any error; <2 context lines = pass (cold start); any line containing
    "claude" = unconditional pass (name override).
Known limits: bare answers to the assistant's own question right after
other-agent talk can still false-drop, and topic-less fragments can leak
through — the 12B local judge was tried and is too slow (>2.5 s/call);
session-level judgment stays the backstop. dispatch-v2 respawn loop also has
a latent wedge: killing talkingstick leaves the FIFO cat-subshell blocking
the pipeline, so the respawn never fires — restart dispatch-v2 wholesale.
