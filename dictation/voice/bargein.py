#!/usr/bin/env python3
"""bargein.py: talk over the voice ("Talking Stick") without it hearing itself.

Off by default. Turn it on with NARRATE_BARGE_IN=2 (or `stt.py --barge-in`).

While the computer is speaking, the listener normally ignores the mic. With
barge-in on it keeps listening instead:

  1. The exact audio being played (the WAV afplay is playing) is the echo
     reference. WebRTC's AEC3 echo canceller (from the `livekit` wheel, which
     bundles webrtc's audio processing module) subtracts it from the mic, so
     what is left is the room plus whoever is talking over it.
  2. A level/duration gate on that cleaned audio (the same idea as the
     iPhone app's LiveBargeIn: an adaptive estimate of the leftover echo,
     a fixed floor above silence, and several loud frames close together)
     decides the person is really talking, not a click or an echo spike.
  3. On a hit the voice is stopped, the last ~1.5 s of cleaned audio is handed
     to the normal endpointer (so the first words survive) and the rest of
     the sentence is transcribed like any other. The session then sends
     Escape + the text, as it already does for a new request.

Fail safe: if the echo canceller can't load, or the computer is talking but
we can't tell what it is playing (no afplay WAV to read), the listener keeps
the old behavior and stays deaf while it talks. It never feeds uncancelled
playback to speech-to-text.

Env (all optional):
  NARRATE_BARGE_IN          2 = on (1, the default, only stops the voice on a new request)
  NARRATE_BARGE_FLOOR_DB    cleaned level that can count as talking (default -38 dBFS)
  NARRATE_BARGE_MARGIN_DB   how far above the leftover echo it must be (default 10 dB)
  NARRATE_BARGE_FRAMES      loud 30 ms frames needed within the last 10 (default 4)
  NARRATE_BARGE_HOLDOFF_MS  ignore the first part of each reply while AEC adapts (default 300)
  NARRATE_BARGE_DEBUG       1 = also log levels every ~0.5 s while speaking
Barge-ins are logged to dictation/state/bargein.log (not the terminal, which claude owns).
"""

import collections
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

RATE = 16000
FRAME = 480          # 30 ms, same as stt.py
SUB = 160            # AEC3 works on 10 ms blocks
PREROLL_SEC = 1.5


def _env(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def log(msg: str) -> None:
    try:
        common.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(common.STATE_DIR / "bargein.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def enabled() -> bool:
    return os.environ.get("NARRATE_BARGE_IN", "1").strip() == "2"


def _db(x) -> float:
    return 20.0 * math.log10(x + 1e-9)


def _rms(frame) -> float:
    if not len(frame):
        return 0.0
    return math.sqrt(sum(float(v) * float(v) for v in frame) / len(frame))


# --- echo canceller -------------------------------------------------------------

class EchoCanceller:
    """WebRTC AEC3 on 16 kHz mono float frames (any multiple of 10 ms)."""

    def __init__(self):
        import numpy as np
        from livekit import rtc
        self._np = np
        self._rtc = rtc
        self.apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=False,
                                             high_pass_filter=True, auto_gain_control=False)

    @staticmethod
    def available() -> bool:
        try:
            import numpy  # noqa: F401
            from livekit import rtc
            rtc.AudioProcessingModule(echo_cancellation=True)
            return True
        except Exception:
            return False

    def _frame(self, samples):
        np = self._np
        pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype(np.int16)
        return self._rtc.AudioFrame(pcm.tobytes(), RATE, 1, len(pcm))

    def process(self, mic, ref):
        """mic, ref: equal-length float sequences. Returns the cleaned mic as a list of floats."""
        np = self._np
        out = np.empty(len(mic), dtype=np.float32)
        for i in range(0, len(mic) - SUB + 1, SUB):
            self.apm.process_reverse_stream(self._frame(ref[i:i + SUB]))
            f = self._frame(mic[i:i + SUB])
            self.apm.process_stream(f)
            out[i:i + SUB] = np.frombuffer(bytes(f.data), dtype=np.int16) / 32768.0
        return out


# --- the decision ----------------------------------------------------------------

class Detector:
    """LiveBargeIn, ported: is someone talking over the leftover echo?"""

    def __init__(self, floor_db=None, margin_db=None, needed=None, window=10, holdoff_ms=None):
        self.floor_db = _env("NARRATE_BARGE_FLOOR_DB", -38) if floor_db is None else floor_db
        self.margin_db = _env("NARRATE_BARGE_MARGIN_DB", 10) if margin_db is None else margin_db
        self.needed = int(_env("NARRATE_BARGE_FRAMES", 4) if needed is None else needed)
        self.window = window
        hold = _env("NARRATE_BARGE_HOLDOFF_MS", 300) if holdoff_ms is None else holdoff_ms
        self.holdoff = int(hold / 1000 * RATE / FRAME)
        self.reset()

    def reset(self):
        self.echo_db = -60.0
        self.recent = collections.deque(maxlen=self.window)
        self.frames = 0

    def threshold_db(self) -> float:
        return max(self.floor_db, self.echo_db + self.margin_db)

    def feed(self, level_db: float) -> bool:
        self.frames += 1
        loud = level_db > self.threshold_db()
        if not loud or self.frames <= self.holdoff:
            # Track the leftover echo: rise quickly, fall slowly.
            a = 0.3 if level_db > self.echo_db else 0.05
            self.echo_db = self.echo_db * (1 - a) + level_db * a
        if self.frames <= self.holdoff:
            return False
        self.recent.append(loud)
        return sum(self.recent) >= self.needed


class BargeIn:
    """Echo canceller + detector + a pre-roll of cleaned audio. Pure: no mic, no players."""

    def __init__(self, canceller=None, detector=None):
        self.aec = canceller or EchoCanceller()
        self.det = detector or Detector()
        self.preroll = collections.deque(maxlen=int(PREROLL_SEC * RATE / FRAME))
        self.last_level = -90.0

    def start_reply(self):
        """A new reply started playing."""
        self.det.reset()
        self.preroll.clear()

    def feed(self, mic, ref):
        """One 30 ms mic frame + the matching playback frame -> (cleaned frame, fired)."""
        clean = self.aec.process(mic, ref)
        self.preroll.append(clean)
        self.last_level = _db(_rms(clean))
        return clean, self.det.feed(self.last_level)

    def take_preroll(self):
        frames = list(self.preroll)
        self.preroll.clear()
        return frames


def ref_frame(samples, i, n):
    """samples[i:i+n] as floats, zero-padded where it runs off either end."""
    out = [0.0] * n
    lo, hi = max(0, i), min(len(samples), i + n)
    for j in range(lo, hi):
        out[j - i] = samples[j]
    return out


# --- what is playing right now ---------------------------------------------------

class Reference:
    """Finds the WAV the speaker is playing (afplay's file) and when it started."""

    def __init__(self, read_wav, poll_sec=0.05):
        self.read_wav = read_wav
        self.poll_sec = poll_sec
        self.lock = threading.Lock()
        self.current = None      # (key, samples, t0 wall clock)
        self.unknown = False     # something plays that we can't read
        self._cache = {}
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    @staticmethod
    def _afplay():
        """[(pid, wav_path or None)] for running afplay processes."""
        try:
            pids = subprocess.run(["pgrep", "-x", "afplay"], capture_output=True,
                                  text=True, timeout=2).stdout.split()
            if not pids:
                return []
            out = subprocess.run(["ps", "-o", "pid=,args=", "-p", ",".join(pids)], capture_output=True,
                                 text=True, timeout=2).stdout
        except Exception:
            return []
        found = []
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            args = parts[1].split()[1:]
            # -r / -q change the timing: we can't line that up, so treat it as unknown.
            if any(a in ("-r", "--rate", "-q", "--rQuality") for a in args):
                found.append((int(parts[0]), None))
                continue
            path = args[-1] if args else ""
            found.append((int(parts[0]), path if path.lower().endswith((".wav", ".wave")) else None))
        return found

    def _loop(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_sec)

    def poll_once(self):
        seen = time.time()
        players = self._afplay()
        with self.lock:
            if not players:
                self.current, self.unknown = None, False
            elif len(players) > 1 or players[0][1] is None:
                self.current, self.unknown = None, True
            else:
                pid, path = players[0]
                key = (pid, path)
                if not self.current or self.current[0] != key:
                    samples = self._load(path)
                    # Lead the real start a little: the reference must come
                    # before the echo, never after it.
                    self.current = (key, samples, seen - self.poll_sec) if samples is not None else None
                    self.unknown = samples is None

    def _load(self, path):
        if path in self._cache:
            return self._cache[path]
        try:
            samples = self.read_wav(path)
        except Exception:
            samples = None
        self._cache = {path: samples}
        return samples

    def snapshot(self):
        with self.lock:
            return self.current, self.unknown


def stop_playback():
    """Stop the voice now, including a speak script that would play its next chunk."""
    if common.IS_MACOS:
        try:
            out = subprocess.run(["ps", "-axo", "pid=,ppid=,comm="], capture_output=True,
                                 text=True, timeout=2).stdout
            procs = {}
            for line in out.splitlines():
                p = line.split(None, 2)
                if len(p) == 3:
                    procs[int(p[0])] = (int(p[1]), os.path.basename(p[2]))
            for pid, (ppid, comm) in procs.items():
                if comm == "afplay" and ppid in procs:
                    args = subprocess.run(["ps", "-o", "args=", "-p", str(ppid)], capture_output=True,
                                          text=True, timeout=2).stdout
                    if "speak" in args:
                        os.kill(ppid, signal.SIGTERM)
        except Exception:
            pass
    common.stop_speaking()
