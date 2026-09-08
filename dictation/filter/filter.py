#!/usr/bin/env python3
# filter.py — sit between the swift listener and the inject step. Each
# line on stdin is `<text>\t<wav_path>` (the listener now mirrors per-task
# audio to a wav so we can score it). We compute a Resemblyzer embedding,
# compare against the enrolled voiceprint, and only forward Matt's
# utterances. Anything else gets logged to ../state/dropped.log with a
# reason, then the wav is deleted.
#
# Forwarded lines on stdout are bare text (the original listener contract)
# so dispatch + inject keep working without changes.
#
# Tunables (env):
#   MATCH_THRESHOLD   cosine similarity floor for an utterance to count as
#                     Matt. Default 0.72; tighten if false-positives slip
#                     through (the cloned voice or a cousin's voice
#                     scoring high), loosen if your own utterances drop.

import os
import sys
from pathlib import Path

import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav


THRESHOLD = float(os.environ.get("MATCH_THRESHOLD", "0.48"))


def _log(handle, msg: str) -> None:
    handle.write(msg + "\n")
    handle.flush()


def main() -> int:
    state_dir = Path(__file__).resolve().parent.parent / "state"
    voiceprint_path = state_dir / "voiceprint.npy"
    drop_log_path = state_dir / "dropped.log"
    decision_log_path = state_dir / "filter.log"

    if not voiceprint_path.exists():
        sys.stderr.write(
            f"filter: voiceprint missing at {voiceprint_path} — run enroll.py first\n"
        )
        return 1

    enrolled = np.load(voiceprint_path)
    encoder = VoiceEncoder(verbose=False)
    sys.stderr.write(f"filter: ready (threshold={THRESHOLD})\n")
    sys.stderr.flush()

    drop_log = open(drop_log_path, "a", buffering=1)
    decision_log = open(decision_log_path, "a", buffering=1)

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line:
            continue
        if "\t" in line:
            text, wav_path = line.split("\t", 1)
        else:
            # Listener emitted text only (older build, or saveTaskAudio
            # failed). Without audio we cannot voice-match — pass through
            # so we don't strand the user, but log for visibility.
            _log(decision_log, f"PASS_NO_AUDIO\t{line}")
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            continue

        # Short-utterance bypass — single/double words ("OK", "Yes", "Hello",
        # "Why aren't you answering me") don't carry enough audio for a
        # reliable voiceprint match; the embedding scores low even when it
        # really is Matt. Just pass them through. Downstream relevance filter
        # still gets a shot.
        word_count = len(text.strip().split())
        if word_count <= 2:
            _log(decision_log, f"PASS_SHORT\t{text}")
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
            try: os.remove(wav_path)
            except OSError: pass
            continue

        score = None
        try:
            wav = preprocess_wav(Path(wav_path))
            embedding = encoder.embed_utterance(wav)
            score = float(np.dot(enrolled, embedding))
        except Exception as exc:
            _log(decision_log, f"ERR\t{exc}\t{wav_path}\t{text}")
            # On scoring error, fail open — pass the text through so a
            # transient file/io issue doesn't strand a real utterance.
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        else:
            if score >= THRESHOLD:
                _log(decision_log, f"PASS\t{score:.3f}\t{text}")
                sys.stdout.write(text + "\n")
                sys.stdout.flush()
            else:
                _log(drop_log, f"{score:.3f}\t{text}")
                _log(decision_log, f"DROP\t{score:.3f}\t{text}")
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
