# NarrateClaude 2.0 — The "Talking Stick" Barge-In Experiment

**Status:** Active research build, started 2026-05-20.
**Hardware:** Apple M5 Max, 128 GB unified memory, macOS 26 (Darwin 25.4).
**Goal:** Build a personalized full-duplex voice assistant that you can interrupt mid-TTS more reliably than OpenAI Realtime, Gemini Live, or any other publicly available voice agent.

---

## The thesis

Big AI companies optimize barge-in for **everyone on Earth**. We're optimizing it for **one person**. That asymmetry is the entire research opportunity.

Specifically, we have two structural advantages no public voice agent has:

1. **We know the exact TTS signal we just played.** Piper LibriTTS generates the WAV before it hits the speaker — we have the reference signal byte-for-byte, not an estimate.
2. **We have the user's voiceprint pre-enrolled.** A Resemblyzer embedding for Matt's voice already lives at `dictation/state/voiceprint.npy`. Any VAD or speaker-separation model can be conditioned on it.

Combine the two and you can build a personal VAD that fires *only* when this specific human speaks, ignoring the assistant's own playback even when it bleeds through the mic. The big players can't ship this because they don't know in advance who's going to use their product.

---

## The stack we're building

```
┌────────────────────────────────────────────────────────────────────┐
│  Microphone (continuous)                                           │
│        │                                                           │
│        ▼                                                           │
│  AVAudioEngine + kAudioUnitSubType_VoiceProcessingIO  ─── Apple    │
│        │   (hardware-aligned AEC, NS, AGC)                         │
│        ▼                                                           │
│  Cleaned mic stream  ────────────────┐                             │
│        │                             │                             │
│        ▼                             ▼                             │
│  Silero VAD (FluidAudio,             Personal VAD head             │
│   ~40-80 ms, speaker-agnostic)       (HyWA-style, conditioned on   │
│                                        the user's Resemblyzer      │
│                                        embedding)                  │
│                                      │                             │
│                                      ▼                             │
│                              "is THIS human speaking, right now?"  │
│                                      │                             │
│                       ┌──────────────┴──────────────┐              │
│                       ▼                             ▼              │
│              kill TTS player node          Smart Turn v3 (CoreML)  │
│              (barge-in trigger)            "did THIS human finish  │
│                                              their sentence?"      │
│                                              │                     │
│                                              ▼                     │
│                                       Finalize utterance,          │
│                                       hand to Claude               │
└────────────────────────────────────────────────────────────────────┘

           TTS path (routed THROUGH the same AVAudioEngine so VPIO can cancel it):

   Claude reply text  ──►  Piper LibriTTS  ──►  AVAudioPlayerNode
                                                    │
                                                    ▼
                                          Output mix ──► Speakers
                                                    │
                                                    └─► (reference signal
                                                         seen by VPIO at HAL)
```

Critically: **Piper's output no longer goes through `afplay`.** It's scheduled directly on an `AVAudioPlayerNode` attached to the same `AVAudioEngine` that owns the input node. That's the configuration that makes `setVoiceProcessingEnabled(true)` work — Apple's HAL needs to see the playback signal to cancel it.

This is *why the previous VPIO attempts failed.* They turned on VPIO but kept playing TTS via `afplay`, which is out-of-band from AVAudioEngine. VPIO had no idea what to cancel and either ducked everything or wedged the engine. Routing TTS through the same engine is the unlock.

---

## Phases

### Phase 1 — Apple VPIO baseline (this build)

Replace `afplay`-based TTS with an `AVAudioPlayerNode` on the same engine that owns the mic, and turn on `setVoiceProcessingEnabled(true)`. Drop the `speakIsPlaying` skip in `handleBuffer` — feed the cleaned mic stream to SFSpeech continuously.

**Success metric:** the user can say "stop" mid-TTS and the listener transcribes it cleanly without false-positives from the assistant's own voice bleeding through.

### Phase 2 — FluidAudio Silero VAD

Add [FluidAudio](https://github.com/FluidInference/FluidAudio) as a Swift Package dependency. Install a second tap on the cleaned input node. When `voiceProbability > 0.5` for ≥ 2 consecutive frames, fire `bargein()` which kills the active TTS player node and immediately stops feeding the prior assistant turn through Piper.

**Success metric:** barge-in latency from "user starts speaking" to "TTS audibly stops" is under 100 ms.

### Phase 3 — Personal VAD head (HyWA-style)

Train a small hypernetwork that takes Matt's enrolled Resemblyzer embedding and generates a personalized weight set for a tiny VAD classifier. Replace the speaker-agnostic Silero output with this personal score. Anything that's not Matt's voice — TTS bleed, the dog, the kid, a phone call across the room — never fires the barge-in.

This is the publishable contribution. Reference: [HyWA, arXiv 2510.12947](https://arxiv.org/abs/2510.12947).

**Success metric:** zero false-fires on a 30-minute test recording containing the assistant's TTS at full volume, ambient room noise, and a TV playing a podcast — while still correctly firing on the enrolled user.

### Phase 4 — Smart Turn v3 (CoreML)

Port [pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn) to CoreML and wire it as the end-of-turn predictor. Replaces the 2.5-second stability heuristic in `Listen.swift` with a learned classifier that knows the difference between "I'm pausing mid-thought" and "I'm done, your turn."

**Success metric:** median end-of-turn detection latency drops from ~2500 ms (current stability window) to under 400 ms, with no premature finalizations on natural speech pauses.

### Phase 5 — Moonshot: Joint full-duplex fine-tune (research-grade)

Fine-tune Moshi on a corpus of `(matt_voice_clip, piper_tts_clip)` pairs using MLX. End-to-end joint audio model that swallows the AEC/VAD/EOT pipeline entirely. This is where the 128 GB Apple Silicon edge becomes load-bearing — most individual researchers can't afford to fine-tune a 7B+ audio model on personal data. We can.

**Concrete path (validated by research 2026-05-21):**
- Moshi-MLX weights already exist: `kyutai/moshiko-mlx-bf16` on HuggingFace (~14 GB)
- Reference fine-tune scripts: `kyutai-labs/moshi-finetune` (CUDA, port loop to MLX)
- Alternative MLX-LoRA tooling: `ARahim3/mlx-tune` already supports TTS/STT LoRA on Apple Silicon
- Realistic budget: 4-8 hours of fine-tuning on M5 GPU per training run
- Use the synthetic data harness output (the user's voice + Piper clone pairs) as training corpus

**Success metric:** beats the Phase 1–4 pipeline on the same benchmark. If it doesn't, Phase 1–4 is the shipping version.

---

## The publishable contribution

**Working title:** "Zero-shot personal full-duplex via TTS-clone self-supervision: training a barge-in-aware speech agent on synthetic (user, user-cloned-TTS) pairs."

**Venue target:** ICASSP 2026 Urgent Speech Enhancement Challenge (submission window open as of 2026-05).

**The novelty stack nobody else has assembled:**

1. The user's enrolled Resemblyzer embedding conditions a HyWA-style Personal VAD head (architectural reuse of existing 2025 work).
2. The user's Piper voice clone generates **infinite labeled barge-in scenarios** — the assistant's own voice IS the user's voice, which is the worst-case AEC adversary, and we can synthesize unlimited training data of that adversary against itself.
3. End-to-end joint AEC + PVAD + EOT model fine-tuned on this self-supervised single-user corpus, on consumer hardware.

**The ICASSP/Interspeech 2026 hook:** prior PVAD papers (HyWA included) all assume a generic multi-speaker training corpus with one held-out target. We flip the assumption: train *only* on the target speaker plus their TTS clone, and demonstrate it beats multi-speaker pretraining for that user.

**Why nobody else has done this:**
- Big labs don't have a single user's voiceprint + TTS clone enrolled in advance.
- Individual researchers don't have 128 GB of unified memory to fine-tune 7B audio models on personal data.
- We have both, on one machine, today.

**Prior art to map for the publication:**
- [Textual Echo Cancellation (Google, 2020)](https://arxiv.org/abs/2008.06006) — uses TTS text/audio as AEC conditioning
- [US Patent 20250201259 (June 2025)](https://patents.justia.com/patent/20250201259) — "AEC with TTS Data Loopback" — industrial recognition of the TTS-reference-signal advantage
- [RIR as Prompt for AEC (arXiv 2505.19480)](https://arxiv.org/pdf/2505.19480) — room-impulse-response conditioning we can borrow

---

## Hardware-specific notes — what the M5 Max uniquely unlocks

The M5 Max has per-core **Neural Accelerators** on every GPU core (≈4× M4 compute on AI matmul), 614 GB/s memory bandwidth at 40-core GPU config, and 18 TOPS Int8 on a 16-core ANE. The right placement of each phase is:

| Component | Where it runs | Why |
|---|---|---|
| Silero VAD | ANE | Tiny, Int8-friendly, ~40-80ms onset — already there via FluidAudio |
| Smart Turn v3 | ANE | Tiny (8M params, ~8MB int8) — perfect for ANE |
| Personal VAD (HyWA) | ANE | Small head, must run real-time per frame |
| WhisperKit STT | ANE | Already pinned, ~5ms decode on M3, faster on M5 |
| Moshi LoRA fine-tune | GPU (MLX) | Bandwidth-bound, 7B doesn't fit ANE — the new neural accelerators are the unlock |
| Moshi inference | GPU (MLX) | Real-time at ~200ms latency per Kyutai's benchmarks |

**Don't try to ANE-pin Moshi.** It won't fit and you'd give up the M5's new GPU neural accelerators. The ANE is for the tiny detectors; the GPU is for the big generative model.

---

## What we are not doing

- **Headphone-based AEC.** Headphones aren't an acceptable answer; the assistant has to work with open desk speakers. This is the hard problem on purpose.
- **WebRTC AEC3 standalone.** Researched and rejected — no Homebrew formula, no maintained Swift wrapper, ~250 lines of C++ glue, and Apple VPIO already does the same job using the HAL-level reference signal Apple gives us for free. (See `BARGE_IN_ATTEMPTS.md`.)
- **Amplitude-based barge-in.** Tried, failed twice. Don't return.
- **`setVoiceProcessingEnabled(true)` with `afplay`-routed TTS.** Tried, failed twice. The new approach routes TTS through the same engine; that's the difference.

---

## Repo layout for v2

```
NarrateClaude/
├── EXPERIMENT_PLAN.md        ← this file
├── BARGE_IN_ATTEMPTS.md      ← log of every attempt, what worked, what didn't
├── dictation/                ← v1 (current production) — UNCHANGED until v2 ships
│   ├── bin/                  ← still runs, you still have dictation
│   ├── filter/
│   ├── src/Listen.swift      ← the current listener
│   └── state/
└── dictation-v2/             ← new (Talking Stick)
    ├── Package.swift         ← Swift Package Manager, pulls FluidAudio
    ├── Sources/
    │   └── TalkingStick/
    │       └── main.swift    ← Listen v2: AVAudioEngine + VPIO + VAD pipeline
    ├── Tests/
    └── README.md
```

When v2 is proven on a benchmark we trust, we cut over by replacing `dictation/bin/listen` with the v2 binary. Until then, the v1 listener is untouched and Matt's dictation keeps working.

---

## Demo readiness

If you're walking someone through this in the next few weeks, the talking points are:

1. **The framing.** Big AI companies optimize for everyone; you're optimizing for one. That asymmetry is the entire opportunity.
2. **The hardware.** 128 GB unified memory on Apple Silicon is more than most AI dev boxes. The ANE makes Silero VAD and Smart Turn run in single-digit milliseconds. Fine-tuning a 7B audio model on personal voice data is feasible on this machine in a way it isn't on a typical workstation.
3. **The receipt.** `BARGE_IN_ATTEMPTS.md` shows every dead end with reasons. This isn't a first attempt — it's the fourth, informed by the failure modes of the prior three.
4. **The publishable contribution.** Phase 3 (Personal VAD conditioned on a pre-enrolled voiceprint, trained on the user's TTS reference signal) is genuinely new ground. Nobody ships this because nobody else has the user pre-enrolled.
5. **The shipping version.** Even if Phase 5 (the joint full-duplex moonshot) flops, Phases 1–4 produce a voice agent that beats the public state of the art on the specific problem of barge-in for a known user. That's the floor.
