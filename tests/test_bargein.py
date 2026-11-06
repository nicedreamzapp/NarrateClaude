"""Barge-in (NARRATE_BARGE_IN=2), offline: no mic, no speakers, nothing played.

The computer's voice is a TTS clip; the "room" is that clip delayed and
attenuated with a few reflections and some noise (speaker -> mic echo); the
person is a second clip added at a known time. The detector must never fire
on echo alone, and must fire soon after the person starts talking.

Clips come from macOS `say -o` (written to files, never played). Elsewhere a
synthetic voice-like signal stands in. Needs the echo canceller wheel
(`pip install livekit numpy`); skipped without it.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("livekit.rtc")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dictation" / "voice"))
import bargein  # noqa: E402
import stt  # noqa: E402

RATE, FRAME = bargein.RATE, bargein.FRAME

REPLY = ("Okay, I looked through the listener and the session code. The microphone was muted the "
         "whole time the voice was playing, so anything you said got dropped. I changed it to keep "
         "listening, cancel my own voice out of the signal, and stop talking as soon as you start.")
USER = ["Wait, stop, hold on a second.", "Hey, actually, let me change that.",
        "No no, go back to the first one."]
TTS_VOICES = ["Samantha", "Fred", "Karen", "Daniel"]
USER_VOICES = ["Daniel", "Samantha", "Fred"]


def _say(tmp, voice, text, name):
    aiff, wav = tmp / f"{name}.aiff", tmp / f"{name}.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True, timeout=60)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)],
                   check=True, timeout=60)
    return np.asarray(stt.read_wav(wav), dtype=np.float32)


def _synthetic(seed, seconds):
    """Voiced syllables: a pitch-gliding pulse train through two formants, gated on and off."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    f0 = 110 + 60 * rng.random() + 25 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    src = sum(np.sin(k * phase) / k for k in range(1, 30))
    env = np.zeros(n)
    i = 0
    while i < n:
        syl = int(RATE * (0.12 + 0.15 * rng.random()))
        env[i:i + syl] = np.hanning(min(syl, n - i))
        i += syl + int(RATE * 0.04 * rng.random()) + (int(RATE * 0.3) if rng.random() < 0.15 else 0)
    form = np.sin(2 * np.pi * (500 + 300 * rng.random()) * t) * 0.5 + 1
    return (src * env * form).astype(np.float32)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bargein")
    if shutil.which("say") and shutil.which("afconvert"):
        tts = [_say(tmp, v, REPLY, f"tts{i}") for i, v in enumerate(TTS_VOICES)]
        users = [_say(tmp, v, u, f"user{i}") for i, (v, u) in enumerate(zip(USER_VOICES, USER))]
    else:
        tts = [_synthetic(i, 12) for i in range(4)]
        users = [_synthetic(100 + i, 2) for i in range(3)]
    norm = lambda x: x / (np.max(np.abs(x)) + 1e-9) * 0.5  # noqa: E731
    return [norm(x) for x in tts], [norm(x) for x in users]


def room(x, delay, gain, n, drive=0.0):
    """Speaker -> mic: direct path + reflections, optional speaker overdrive."""
    if drive:
        x = np.tanh(x * (1 + drive)) / np.tanh(1 + drive)
    y = np.zeros(n, dtype=np.float32)
    d = int(delay * RATE)
    for dd, gg in ((0, 1.0), (0.011, 0.35), (0.027, 0.2), (0.05, 0.1), (0.083, 0.05)):
        s = d + int(dd * RATE)
        m = min(len(x), n - s)
        if m > 0:
            y[s:s + m] += gain * gg * x[:m]
    return y


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def run(ref, mic):
    """Feed frames through BargeIn; return the time (s) of the first fire or None, and the pre-roll."""
    b = bargein.BargeIn()
    b.start_reply()
    for k in range(0, len(mic) - FRAME + 1, FRAME):
        r = bargein.ref_frame(ref, k, FRAME)
        _, fired = b.feed(mic[k:k + FRAME], r)
        if fired:
            return (k + FRAME) / RATE, b.take_preroll()
    return None, None


def onset(user):
    """First 30 ms frame of the user clip that is clearly speech."""
    peak = max(rms(user[k:k + FRAME]) for k in range(0, len(user) - FRAME, FRAME))
    for k in range(0, len(user) - FRAME, FRAME):
        if rms(user[k:k + FRAME]) > 0.1 * peak:
            return k / RATE
    return 0.0


# Echo paths: (reference lead + acoustic delay in s, echo gain at the mic, speaker overdrive)
ECHO_PATHS = [(0.03, 0.4, 0.0), (0.12, 0.6, 0.0), (0.25, 0.8, 0.0), (0.12, 0.6, 0.5)]


@pytest.mark.parametrize("path", ECHO_PATHS, ids=lambda p: f"delay{int(p[0]*1000)}ms-g{p[1]}-drive{p[2]}")
def test_no_false_barge_in_on_echo_alone(clips, path):
    tts, _ = clips
    delay, gain, drive = path
    noise = np.random.default_rng(1)
    for x in tts:
        n = len(x) + RATE
        mic = room(x, delay, gain, n, drive) + noise.normal(0, 0.002, n).astype(np.float32)
        fired_at, _ = run(np.concatenate([x, np.zeros(RATE, np.float32)]), mic)
        assert fired_at is None, f"fired at {fired_at:.2f}s on echo alone ({path})"


@pytest.mark.parametrize("level", [0.08, 0.04], ids=["normal-voice", "quiet-voice"])
@pytest.mark.parametrize("path", ECHO_PATHS[:3], ids=lambda p: f"delay{int(p[0]*1000)}ms-g{p[1]}")
def test_barge_in_fires_fast_on_the_person(clips, path, level):
    tts, users = clips
    delay, gain, drive = path
    latencies = []
    noise = np.random.default_rng(2)
    for i, x in enumerate(tts):
        u = users[i % len(users)]
        u = u / (rms(u) + 1e-9) * level  # speech RMS at the mic
        start = 2.5 + 1.3 * i            # mid-reply, different spots
        n = len(x) + RATE
        mic = room(x, delay, gain, n, drive) + noise.normal(0, 0.002, n).astype(np.float32)
        s = int(start * RATE)
        mic[s:s + len(u)] += u[:n - s]
        fired_at, preroll = run(np.concatenate([x, np.zeros(RATE, np.float32)]), mic)
        on = start + onset(u)
        assert fired_at is not None, f"never fired (clip {i}, {path}, level {level})"
        lat = fired_at - on
        assert -0.05 < lat < 1.0, f"latency {lat:.2f}s (clip {i})"
        # The first words are in the pre-roll handed to the transcriber.
        pre = np.concatenate(preroll)
        assert len(pre) / RATE >= lat + 0.05
        latencies.append(lat)
    print(f"\nbarge-in latency {path} level {level}: " + ", ".join(f"{v*1000:.0f}ms" for v in latencies))
    assert sorted(latencies)[len(latencies) // 2] < 0.35   # typical: a word or two in


def test_ref_frame_pads_both_ends():
    s = [1.0, 2.0, 3.0]
    assert bargein.ref_frame(s, -2, 4) == [0.0, 0.0, 1.0, 2.0]
    assert bargein.ref_frame(s, 2, 3) == [3.0, 0.0, 0.0]
    assert bargein.ref_frame(s, 5, 2) == [0.0, 0.0]


def test_detector_holds_off_then_needs_several_loud_frames():
    d = bargein.Detector(floor_db=-38, margin_db=10, needed=4, holdoff_ms=300)
    assert not any(d.feed(-10) for _ in range(d.holdoff))          # cold canceller: ignored
    d = bargein.Detector(floor_db=-38, margin_db=10, needed=4, holdoff_ms=0)
    assert not any(d.feed(-60) for _ in range(20))                 # quiet room
    assert not any(d.feed(-20) for _ in range(3))                  # a short click/burst
    d.reset()
    fired = [d.feed(-20) for _ in range(4)]
    assert fired[-1] and not any(fired[:-1])


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NARRATE_BARGE_IN", raising=False)
    assert not bargein.enabled()
    monkeypatch.setenv("NARRATE_BARGE_IN", "1")
    assert not bargein.enabled()
    monkeypatch.setenv("NARRATE_BARGE_IN", "2")
    assert bargein.enabled()


def test_falls_back_to_deaf_without_the_canceller(monkeypatch):
    monkeypatch.setattr(bargein.EchoCanceller, "available", staticmethod(lambda: False))
    listener = stt.Listener(lambda *a: None, server=object())
    assert listener._barge_setup(True) is None


def test_reference_reads_afplay_wav(monkeypatch, tmp_path):
    wav = tmp_path / "out_000.wav"
    wav.write_bytes(stt.to_wav_bytes([0.1] * 1600))
    ref = bargein.Reference(stt.read_wav)
    monkeypatch.setattr(bargein.Reference, "_afplay", staticmethod(lambda: [(42, str(wav))]))
    ref.poll_once()
    cur, unknown = ref.snapshot()
    assert cur and len(cur[1]) == 1600 and not unknown
    monkeypatch.setattr(bargein.Reference, "_afplay", staticmethod(lambda: [(43, None)]))
    ref.poll_once()
    assert ref.snapshot() == (None, True)   # can't read it -> listener stays deaf


class FakeRef:
    def __init__(self, samples):
        self.samples, self.on = samples, True

    def snapshot(self):
        return ((1, "reply.wav"), self.samples, 0.0) if self.on else None, False


def listen_through(tts, mic_fn, monkeypatch):
    """Drive Listener.feed_block in virtual time; returns (utterances, kill time or None)."""
    listener = stt.Listener(lambda *a: None, server=object())
    listener.barge_in = bargein.BargeIn()
    listener._ref = FakeRef(tts)
    killed = []

    def stop():
        killed.append(t)
        listener._ref.on = False
    monkeypatch.setattr(bargein, "stop_playback", stop)
    monkeypatch.setattr(bargein, "log", lambda msg: None)   # never write the real state dir
    n = len(tts) + 3 * RATE
    mic = mic_fn(n, lambda: killed[0] if killed else None)
    for k in range(0, n - FRAME + 1, FRAME):
        t = (k + FRAME) / RATE
        listener.speaking = listener._ref.on and t < len(tts) / RATE + 0.2
        listener.feed_block(mic(k), t, t)
    listener.endpointer.flush()
    utts = []
    while not listener.jobs.empty():
        utts.append(listener.jobs.get())
    return utts, (killed[0] if killed else None)


def _mic(tts, user=None, at=0.0, delay=0.12, gain=0.6):
    def make(n, kill_time):
        noise = np.random.default_rng(3).normal(0, 0.002, n).astype(np.float32)
        echo = room(tts, delay, gain, n)
        u = np.zeros(n, np.float32)
        if user is not None:
            s = int(at * RATE)
            u[s:s + len(user)] = user[:n - s]

        def frame(k):
            kt = kill_time()
            e = echo[k:k + FRAME].copy()
            if kt is not None:   # the voice stops at the kill (+ the acoustic delay)
                cut = int((kt + delay) * RATE) - k
                e[max(0, cut):] = 0
            return (e + u[k:k + FRAME] + noise[k:k + FRAME]).tolist()
        return frame
    return make


def test_listener_stays_quiet_on_its_own_voice(clips, monkeypatch):
    tts, _ = clips
    utts, killed = listen_through(tts[0], _mic(tts[0]), monkeypatch)
    assert killed is None and utts == []


def test_listener_stops_the_voice_and_keeps_the_first_words(clips, monkeypatch):
    tts, users = clips
    u = users[0] / (rms(users[0]) + 1e-9) * 0.08
    at = 3.0
    utts, killed = listen_through(tts[0], _mic(tts[0], u, at), monkeypatch)
    on = at + onset(u)
    assert killed is not None and killed - on < 0.6
    assert len(utts) == 1
    got = np.asarray(utts[0])
    # Everything the person said is in the utterance: from before onset to the end of the clip.
    assert len(got) / RATE >= (at + len(u) / RATE) - on
