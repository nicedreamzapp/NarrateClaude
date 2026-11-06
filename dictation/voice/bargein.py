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
  NARRATE_BARGE_FLOOR_DB    absolute minimum level that can count as talking (default -65 dBFS;
                            the real gate is learned from the room, see Detector)
  NARRATE_BARGE_MARGIN_DB   how far above the leftover echo it must be (default 10 dB)
  NARRATE_BARGE_FRAMES      loud 30 ms frames needed within the last 10 (default 4)
  NARRATE_BARGE_HOLDOFF_MS  ignore the first part of each reply while AEC adapts (default 300)
  NARRATE_BARGE_DEBUG       1 = also log levels every ~0.5 s while speaking
Barge-ins are logged to dictation/state/bargein.log (not the terminal, which claude owns).
"""

import collections
import math
import os
import re
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
            now = time.time()
            f.write(time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now % 1 * 1000):03d} {now:.3f} " + msg + "\n")
    except OSError:
        pass


def enabled() -> bool:
    return os.environ.get("NARRATE_BARGE_IN", "1").strip() == "2"


def _db(x) -> float:
    return 20.0 * math.log10(x + 1e-9)


def _rms(frame) -> float:
    import numpy as np
    x = np.asarray(frame, dtype=np.float32)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def read_wav(path):
    """Any PCM WAV -> mono float32 numpy samples at 16 kHz (vectorized)."""
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width {width}")
    x = x[:len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    if rate != RATE and len(x):
        n = int(len(x) * RATE / rate)
        x = np.interp(np.arange(n) * (rate / RATE), np.arange(len(x)), x).astype(np.float32)
    return x


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
    """LiveBargeIn, ported and made room-adaptive: is someone talking over the leftover echo?

    A frame is loud when the echo-cancelled level beats all of:
      - the room's own noise + NOISE_MARGIN (learned, so a quiet USB mic works the same
        as a hot built-in one; a fixed -38 dBFS floor never fired on the mini's fifine),
      - the playback level just played + the learned echo leak + LEAK_MARGIN (what the
        canceller lets through on loud passages and speaker transients: in a real room
        that is bursts of the assistant's own consonants, 7-15 dB under the playback),
      - the smoothed leftover echo + MARGIN (the iPhone app's rule),
      - an absolute minimum, FLOOR.
    `needed` loud frames within the last `window` fire it.
    """

    NOISE_MARGIN = 12.0
    LEAK_MARGIN = 3.0
    # Until bursts teach it more: the canceller's worst leak sits ~10 dB under the raw
    # echo coupling (M5 desk speakers, measured 11/06). Relative, so mic gain cancels out.
    LEAK_UNDER_COUPLING = 10.0
    NOISE_START_MAX = -45.0
    LEAK_MAX_UNDER_COUPLING = 4.0
    MIN_ERLE = 10.0         # dB the canceller must be removing before a barge-in may fire
    COUPLING_FRAMES = 30    # coupling: measured over the first 30 frames of each reply that
                            # carry real playback (not frame numbers: replies start with silence)
    REF_ACTIVE_DB = -40.0   # a playback frame this loud counts as "carrying echo"
    NOISE_RISE_MAX = 0.05   # dB per frame: estimates may only creep up
    LEAK_RISE_MAX = 1.0

    def __init__(self, floor_db=None, margin_db=None, needed=None, window=10, holdoff_ms=None):
        self.floor_db = _env("NARRATE_BARGE_FLOOR_DB", -65) if floor_db is None else floor_db
        self.margin_db = _env("NARRATE_BARGE_MARGIN_DB", 10) if margin_db is None else margin_db
        self.needed = int(_env("NARRATE_BARGE_FRAMES", 4) if needed is None else needed)
        self.window = window
        hold = _env("NARRATE_BARGE_HOLDOFF_MS", 300) if holdoff_ms is None else holdoff_ms
        self.holdoff = int(hold / 1000 * RATE / FRAME)
        self.reset()

    def reset(self):
        """Forget everything (first reply of the session)."""
        self.echo_db = -90.0
        self.noise_db = None
        self.coupling_db = None   # raw mic level vs playback level (speaker->mic loudness)
        self.leak_db = None       # cancelled level vs playback level, worst case
        self.erle_db = None       # dB the canceller removes; carried across replies (see feed)
        self.new_reply()

    def new_reply(self):
        """A new reply: start the warm-up again but keep what was learned about the room,
        so someone already talking when it starts can't become the baseline."""
        self.recent = collections.deque(maxlen=self.window)
        self.refs = collections.deque(maxlen=20)   # ~0.6 s: covers the speaker->mic delay
        self.frames = 0
        self._coupling = []
        self._coupling_done = False
        if getattr(self, "leak_db", None) is not None and self.coupling_db is not None:
            # Let old bursts fade a little each reply, never under the prior.
            self.leak_db = max(self.coupling_db - self.LEAK_UNDER_COUPLING, self.leak_db - 2.0)

    def observe_quiet(self, level_db: float) -> None:
        """Room noise: follow quiet frames down fast, creep up slowly (a fan switching on).
        The listener also calls this between replies, so it is known before the first one."""
        if self.noise_db is None:
            if level_db < self.NOISE_START_MAX:   # never start from someone talking
                self.noise_db = level_db
        elif level_db < self.noise_db:
            self.noise_db += 0.3 * (level_db - self.noise_db)
        elif level_db < self.noise_db + self.NOISE_MARGIN:   # someone talking is not the room
            self.noise_db += min(self.NOISE_RISE_MAX, 0.002 * (level_db - self.noise_db))

    def threshold_db(self, ref_env=None) -> float:
        if ref_env is None:
            ref_env = max(self.refs) if self.refs else -120.0
        t = max(self.floor_db, self.echo_db + self.margin_db)
        if self.leak_db is not None:
            t = max(t, ref_env + self.leak_db + self.LEAK_MARGIN)
        if self.noise_db is not None:
            t = max(t, self.noise_db + self.NOISE_MARGIN)
        return t

    def feed(self, level_db: float, ref_db: float = -120.0, raw_db: "float | None" = None) -> bool:
        self.frames += 1
        warm = self.frames <= self.holdoff
        self.refs.append(ref_db)
        ref_env = max(self.refs)
        playing = ref_env > -60
        loud = level_db > self.threshold_db(ref_env)
        # Frames near someone talking (loud now or in the last 10) teach nothing.
        active = loud or any(self.recent)
        # Coupling: the first COUPLING_FRAMES frames of this reply that carry playback.
        if ref_db > self.REF_ACTIVE_DB and raw_db is not None and not active and not self._coupling_done:
            self._coupling.append(raw_db - ref_env)
            if len(self._coupling) in (8, self.COUPLING_FRAMES):
                self._learn_coupling(final=len(self._coupling) == self.COUPLING_FRAMES)
        if (not playing or warm) and not active:
            self.observe_quiet(level_db)
        if not active or warm:
            # Leftover echo: rise quickly, fall slowly.
            a = 0.3 if level_db > self.echo_db else 0.05
            self.echo_db = self.echo_db * (1 - a) + level_db * a
        if not active and not warm:
            # ERLE only where there IS echo to remove: the current playback frame is loud
            # and the mic is above the room. Gaps between sentences don't touch it, so the
            # last good value is held right where people tend to interrupt.
            if ref_db > self.REF_ACTIVE_DB and raw_db is not None and \
                    (self.noise_db is None or raw_db > self.noise_db + 6):
                e = raw_db - level_db
                self.erle_db = e if self.erle_db is None else self.erle_db + 0.05 * (e - self.erle_db)
            if playing and self.leak_db is not None and self.cancelling():
                # Echo leak relative to what was played: an upper envelope, rate-limited, bounded.
                rel = level_db - ref_env
                if rel > self.leak_db:
                    self.leak_db += min(self.LEAK_RISE_MAX, 0.3 * (rel - self.leak_db))
                self.leak_db = min(self.leak_db, self.coupling_db - self.LEAK_MAX_UNDER_COUPLING)
        if warm:
            # Warm-up hears everything, the person included: never let it push the
            # echo estimate above the room's noise + margin.
            cap = (self.noise_db + self.NOISE_MARGIN) if self.noise_db is not None else self.floor_db
            self.echo_db = min(self.echo_db, max(cap, self.floor_db))
            return False
        self.recent.append(loud)
        # Fail safe: if the canceller isn't taking the echo off, what is "loud" is
        # probably our own voice. Never fire then. (No estimate yet = first reply's
        # first moments: the leak and echo gates carry it.)
        return sum(self.recent) >= self.needed and self.cancelling()

    def cancelling(self) -> bool:
        return self.erle_db is None or self.erle_db >= self.MIN_ERLE

    def _learn_coupling(self, final):
        """Speaker->mic loudness for this reply: a high percentile of raw - played, smoothed
        across replies. Provisional after 8 frames, settled once per reply after 30."""
        c = sorted(self._coupling)[int(0.9 * (len(self._coupling) - 1))]
        if self.coupling_db is None:
            self.coupling_db = c
        elif final:
            self.coupling_db = 0.7 * self.coupling_db + 0.3 * c
        if final:
            self._coupling_done = True
        prior = self.coupling_db - self.LEAK_UNDER_COUPLING
        self.leak_db = prior if self.leak_db is None else max(prior, self.leak_db)


class BargeIn:
    """Echo canceller + detector + a pre-roll of cleaned audio. Pure: no mic, no players."""

    def __init__(self, canceller=None, detector=None):
        self._make_aec = None if canceller else EchoCanceller
        self.aec = canceller or EchoCanceller()
        self.det = detector or Detector()
        self.preroll = collections.deque(maxlen=int(PREROLL_SEC * RATE / FRAME))
        self.last_level = -90.0

    def start_reply(self):
        """A new reply started playing. A fresh canceller each time: the reference's start
        is only known to within a poll interval, so the speaker->mic delay differs per
        reply, and AEC3 carrying the last reply's delay diverged in the M5 room (11/06)."""
        self.aec = self._make_aec() if self._make_aec else self.aec
        self.det.new_reply()
        self.preroll.clear()

    def feed(self, mic, ref):
        """One 30 ms mic frame + the matching playback frame -> (cleaned frame, fired)."""
        clean = self.aec.process(mic, ref)
        self.preroll.append(clean)
        self.last_level = _db(_rms(clean))
        return clean, self.det.feed(self.last_level, _db(_rms(ref)) if len(ref) else -120.0, _db(_rms(mic)))

    def idle(self, frame):
        """A mic frame while nothing plays: keeps the room-noise estimate current
        (observe_quiet ignores frames well above the room, i.e. someone talking)."""
        self.det.observe_quiet(_db(_rms(frame)))

    def take_preroll(self):
        frames = list(self.preroll)
        self.preroll.clear()
        return frames


def ref_frame(samples, i, n):
    """samples[i:i+n] as float32, zero-padded where it runs off either end."""
    import numpy as np
    out = np.zeros(n, dtype=np.float32)
    lo, hi = max(0, i), min(len(samples), i + n)
    if hi > lo:
        out[lo - i:hi - i] = samples[lo:hi]
    return out


# --- what is playing right now ---------------------------------------------------

class Reference:
    """Finds the WAV the speaker is playing (afplay's file) and when it started."""

    IDLE_SEC = 0.15   # between polls while nothing plays (same pace as stt's speaking poller)

    def __init__(self, read_wav=None, poll_sec=0.05, active=None):
        self.read_wav = read_wav or globals()["read_wav"]
        self.poll_sec = poll_sec
        self.active = active or (lambda: True)   # e.g. the listener is running
        self._interval = poll_sec
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
        return [Reference.parse(line) for line in out.splitlines() if line.split(None, 1)[1:]]

    @staticmethod
    def parse(line):
        """'pid args' from ps -> (pid, wav path or None). Paths may contain spaces."""
        pid, args = line.split(None, 1)
        rest = args.split(None, 1)[1] if len(args.split(None, 1)) > 1 else ""
        # -r / -q change the timing: we can't line that up, so treat it as unknown.
        if re.search(r"(^|\s)(-r|--rate|-q|--rQuality)(\s|$)", rest):
            return int(pid), None
        m = re.search(r"(?:^|\s)(/.*?\.wave?)\s*$", rest, re.I)
        return int(pid), (m.group(1) if m else None)

    def _loop(self):
        while not self._stop.is_set():
            if not self.active():
                with self.lock:
                    self.current, self.unknown = None, False
                self._stop.wait(1.0)
                continue
            playing = self.poll_once()
            # Fast while something plays, slower when idle. A new player is seen
            # at most one interval late; poll_once leads t0 by that interval.
            self._interval = self.poll_sec if playing else self.IDLE_SEC
            self._stop.wait(self._interval)

    def poll_once(self):
        seen = time.time()
        lead = self._interval
        players = self._afplay()
        if not players:
            with self.lock:
                self.current, self.unknown = None, False
            return False
        if len(players) > 1 or players[0][1] is None:
            with self.lock:
                self.current, self.unknown = None, True
            return True
        pid, path = players[0]
        key = (pid, path)
        with self.lock:
            same = self.current is not None and self.current[0] == key
        if not same:
            samples = self._load(path)          # decode outside the lock
            with self.lock:
                # Lead the real start: the reference must come before the echo, never after.
                self.current = (key, samples, seen - lead) if samples is not None else None
                self.unknown = samples is None
        return True

    def _load(self, path):
        try:
            st = os.stat(path)
            ck = (path, st.st_mtime_ns, st.st_size)
        except OSError:
            return None
        if ck in self._cache:
            return self._cache[ck]
        try:
            samples = self.read_wav(path)
        except Exception:
            samples = None
        self._cache = {ck: samples}
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
