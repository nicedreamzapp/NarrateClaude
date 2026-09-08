#!/usr/bin/env python3
# enroll.py — turn Matt's reference voice sample into a single 256-dim
# embedding that the filter compares each utterance against.
#
# Run once after install (or after refreshing the reference clip):
#     .venv/bin/python enroll.py /path/to/clean_voice_sample.wav
#
# Writes ../state/voiceprint.npy. The filter mmaps that file at startup.

import sys
from pathlib import Path

import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: enroll.py <voice-sample.wav> [more-samples.wav ...]", file=sys.stderr)
        return 2

    sample_paths = [Path(p).expanduser().resolve() for p in sys.argv[1:]]
    for p in sample_paths:
        if not p.exists():
            print(f"enroll: sample not found: {p}", file=sys.stderr)
            return 1

    state_dir = Path(__file__).resolve().parent.parent / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / "voiceprint.npy"

    encoder = VoiceEncoder(verbose=False)
    embeddings = []
    for p in sample_paths:
        print(f"enroll: loading {p}", file=sys.stderr)
        wav = preprocess_wav(p)
        print(
            f"enroll: encoding {len(wav) / 16000:.1f}s of audio",
            file=sys.stderr,
        )
        embeddings.append(encoder.embed_utterance(wav))

    # Multi-sample averaging tightens the embedding against per-clip
    # microphone / room / mood variance. Matches Resemblyzer's
    # embed_speaker pattern.
    stacked = np.stack(embeddings, axis=0)
    mean = stacked.mean(axis=0)
    voiceprint = mean / np.linalg.norm(mean)
    np.save(out_path, voiceprint)
    print(
        f"enroll: wrote {out_path} (dim={voiceprint.shape[0]}, samples={len(sample_paths)})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
