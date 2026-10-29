"""Tests for the open-source voice loop in dictation/voice/.

No whisper.cpp, no models, no mic, no speakers: whisper-server is replaced
by a tiny fake HTTP server, Piper by a fake module, and `claude` by a stub
script running in the loop's real pty. Modules are imported from a temp
copy of the dictation tree so nothing writes into the repo's state/.
"""

import json
import math
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import types
import wave
from array import array
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from conftest import IS_MACOS, REPO, load_module, make_dictation_tree

VOICE_FILES = ["voice/common.py", "voice/stt.py", "voice/speak.py", "voice/session.py",
               "voice/models.txt", "voice/requirements.txt", "filter/relevance.py"]


@pytest.fixture
def tree(tmp_path):
    return make_dictation_tree(tmp_path, *VOICE_FILES)


@pytest.fixture
def voice(tree, monkeypatch):
    """Import common/stt/speak/session from the temp tree."""
    monkeypatch.syspath_prepend(str(tree / "voice"))
    for name in ("common", "stt", "speak", "session"):
        sys.modules.pop(name, None)
    mods = types.SimpleNamespace()
    for name in ("common", "stt", "speak", "session"):
        mod = load_module(tree / "voice" / f"{name}.py", name)
        sys.modules[name] = mod
        setattr(mods, name, mod)
    yield mods
    for name in ("common", "stt", "speak", "session"):
        sys.modules.pop(name, None)


# --- common ------------------------------------------------------------------


@pytest.mark.parametrize("text,out", [
    ("(keyboard clicking)", None),
    ("[BLANK_AUDIO]", None),
    ("", None),
    ("   ", None),
    ("okay", None),
    ("yes please", None),
    ("Why?", "Why?"),
    ("open the deploy logs", "open the deploy logs"),
    ("  run the tests again  ", "run the tests again"),
])
def test_gate(voice, text, out):
    assert voice.common.gate(text) == out


def test_gate_force(voice):
    assert voice.common.gate("ok", force=True) == "ok"
    assert voice.common.gate("", force=True) is None


@pytest.mark.parametrize("ram,name", [(128, "large-v3-turbo"), (8, "large-v3-turbo"),
                                      (7.9, "small.en"), (4, "small.en"), (2, "base.en"), (0, "base.en")])
def test_model_for_ram(voice, ram, name):
    assert voice.common.model_for_ram(ram) == name


def test_models_are_full_precision_and_pinned(tree):
    """Every whisper model is an f16 file (no q4/q5/q8) pinned to a commit with a sha256."""
    from conftest import DICTATION
    rows = [l.split() for l in (DICTATION / "voice" / "models.txt").read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    names = {r[0] for r in rows}
    for needed in ("large-v3-turbo", "small.en", "base.en", "silero-vad", "piper-voice", "piper-voice-config"):
        assert needed in names
    for name, sha, rel, url in rows:
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
        assert "/resolve/main/" not in url and "/resolve/" in url
        assert not any(q in rel for q in ("q4", "q5", "q8")), rel
        assert url.endswith(rel.split("/")[-1])


def test_pick_model_env_and_fallback(voice, tmp_path, monkeypatch):
    c = voice.common
    monkeypatch.setenv("NARRATE_DATA", str(tmp_path / "data"))
    models = tmp_path / "data" / "models"
    models.mkdir(parents=True)
    monkeypatch.setattr(c, "total_ram_gib", lambda: 64)
    monkeypatch.delenv("NARRATE_WHISPER_MODEL", raising=False)
    # Nothing downloaded: the one that fits.
    assert c.pick_model().name == "ggml-large-v3-turbo.bin"
    # Only a smaller one downloaded: use it rather than fail.
    (models / "ggml-base.en.bin").write_bytes(b"x")
    assert c.pick_model().name == "ggml-base.en.bin"
    (models / "ggml-large-v3-turbo.bin").write_bytes(b"x")
    assert c.pick_model().name == "ggml-large-v3-turbo.bin"
    monkeypatch.setenv("NARRATE_WHISPER_MODEL", "small.en")
    assert c.pick_model() == models / "ggml-small.en.bin"
    monkeypatch.setenv("NARRATE_WHISPER_MODEL", str(tmp_path / "mine.bin"))
    assert c.pick_model() == tmp_path / "mine.bin"


def test_total_ram_is_positive(voice):
    assert voice.common.total_ram_gib() > 0.5


def test_speaking_pid_file(voice):
    c = voice.common
    assert not c.pid_alive(c.speaking_pid())
    c.STATE_DIR.mkdir(parents=True, exist_ok=True)
    c.SPEAKING_FILE.write_text(str(os.getpid()))
    assert c.pid_alive(c.speaking_pid())
    c.SPEAKING_FILE.write_text("999999999")
    assert not c.pid_alive(c.speaking_pid())


def test_player_running_uses_env_list(voice, monkeypatch):
    monkeypatch.setenv("NARRATE_MUTE_PROCS", "")
    assert voice.common.player_running() is False


# --- stt: VAD and audio --------------------------------------------------------


def tone(sec, amp=0.3, hz=220, rate=16000):
    return array("f", (amp * math.sin(2 * math.pi * hz * i / rate) for i in range(int(sec * rate))))


def silence(sec, rate=16000, level=0.0):
    import random
    rnd = random.Random(1)
    return array("f", (level * (rnd.random() * 2 - 1) for _ in range(int(sec * rate))))


def feed(ep, samples, frame=480):
    for i in range(0, len(samples) - frame + 1, frame):
        ep.feed(samples[i:i + frame])


def test_endpointer_splits_on_silence(voice):
    got = []
    ep = voice.stt.Endpointer(got.append, silence_sec=0.6, min_speech_sec=0.2)
    audio = silence(0.5, level=0.002) + tone(1.0) + silence(1.0, level=0.002) + tone(0.8) + silence(1.0, level=0.002)
    feed(ep, audio)
    assert len(got) == 2
    for utt, sec in zip(got, (1.0, 0.8)):
        dur = len(utt) / 16000
        assert sec <= dur <= sec + 0.9, dur  # pre-roll + short tail, no long silence


def test_endpointer_ignores_noise_and_clicks(voice):
    got = []
    ep = voice.stt.Endpointer(got.append, silence_sec=0.5, min_speech_sec=0.3)
    feed(ep, silence(3.0, level=0.003))         # room noise
    feed(ep, tone(0.1) + silence(1.0, level=0.003))  # a click: too short
    assert got == []


def test_endpointer_adapts_to_a_noisy_room(voice):
    """A fan that switches on is speech for a moment, then becomes the floor.
    (A tone that never stops is treated the same way: it is the room.)"""
    got = []
    ep = voice.stt.Endpointer(got.append, silence_sec=0.5, min_speech_sec=0.2)
    feed(ep, silence(1.0, level=0.002))
    feed(ep, silence(8.0, level=0.03))  # loud fan, well above min_level
    noise_rms = 0.03 / math.sqrt(3)
    assert ep.threshold() > noise_rms
    assert len(got) <= 1  # at most one noise burst, which whisper's VAD drops
    got.clear()
    feed(ep, silence(2.0, level=0.03))
    assert got == []
    feed(ep, tone(1.0, amp=0.5) + silence(1.0, level=0.03))
    assert len(got) == 1


def test_endpointer_caps_long_utterances(voice):
    got = []
    ep = voice.stt.Endpointer(got.append, silence_sec=0.5, max_sec=1.0, min_speech_sec=0.2)
    feed(ep, silence(1.0, level=0.002) + tone(2.5))
    assert len(got) in (2, 3)
    assert all(len(u) <= 16000 + 480 for u in got)


def test_wav_roundtrip_and_resample(voice, tmp_path):
    stt = voice.stt
    src = tone(0.5, amp=0.5)
    data = stt.to_wav_bytes(src)
    p = tmp_path / "a.wav"
    p.write_bytes(data)
    back = stt.read_wav(p)
    assert len(back) == len(src)
    assert max(abs(a - b) for a, b in zip(back, src)) < 1e-3
    # 22.05 kHz stereo (Piper's rate) comes back as 16 kHz mono.
    p2 = tmp_path / "b.wav"
    with wave.open(str(p2), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x10" * 2 * 22050)
    out = stt.read_wav(p2)
    assert abs(len(out) - 16000) <= 1
    assert abs(out[100] - 0x1000 / 32768) < 1e-4


@pytest.mark.parametrize("raw,clean", [
    (" Thank you. ", ""), ("you", ""), ("[BLANK_AUDIO]", ""),
    ("  open   the logs ", "open the logs"),
])
def test_clean_text(voice, raw, clean):
    assert voice.stt.clean_text(raw) == clean


def test_server_command_flags(voice, tmp_path):
    s = voice.stt.WhisperServer(model=tmp_path / "m.bin", binary=tmp_path / "ws",
                                vad=tmp_path / "vad.bin", lang="en", port=12345)
    cmd = s.command()
    assert cmd[:3] == [str(tmp_path / "ws"), "-m", str(tmp_path / "m.bin")]
    assert ["--host", "127.0.0.1"] == cmd[3:5]
    assert "--vad" in cmd and cmd[cmd.index("-vm") + 1] == str(tmp_path / "vad.bin")
    s2 = voice.stt.WhisperServer(model=tmp_path / "m.bin", binary=tmp_path / "ws", vad=False, port=1)
    assert "--vad" not in s2.command()


def test_server_start_reports_missing_pieces(voice, tmp_path):
    s = voice.stt.WhisperServer(model=tmp_path / "m.bin", binary=tmp_path / "nope", vad=False)
    with pytest.raises(FileNotFoundError, match="whisper-server not found"):
        s.start()


class FakeWhisper(BaseHTTPRequestHandler):
    """Answers /inference like whisper-server; the text is the WAV's length."""

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        assert self.path == "/inference"
        assert b'name="response_format"' in body and b"RIFF" in body
        start = body.index(b"RIFF")
        import io
        with wave.open(io.BytesIO(body[start:]), "rb") as w:
            secs = w.getnframes() / w.getframerate()
        text = f" heard {secs:.2f} seconds of speech "
        out = json.dumps({"text": text}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_whisper():
    httpd = HTTPServer(("127.0.0.1", 0), FakeWhisper)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def test_listener_file_path_end_to_end(voice, fake_whisper, tmp_path):
    """WAV -> Endpointer -> HTTP multipart -> text, with the fake server."""
    stt = voice.stt
    p = tmp_path / "talk.wav"
    p.write_bytes(stt.to_wav_bytes(silence(0.5) + tone(2.0) + silence(1.5) + tone(1.0) + silence(0.3)))
    server = stt.WhisperServer(port=fake_whisper)
    server.start = lambda: server
    server.stop = lambda: None
    got = []
    lst = stt.Listener(lambda t, w: got.append((t, w)), server=server, emit_wav=True)
    lst.start()
    lst.run_file(p)
    lst.drain()
    secs = [float(t.split()[1]) for t, _ in got]
    assert len(secs) == 2 and 2.0 <= secs[0] <= 2.8 and 1.0 <= secs[1] <= 1.8, secs
    for _, w in got:
        assert Path(w).exists() and Path(w).read_bytes()[:4] == b"RIFF"


# --- speak -------------------------------------------------------------------------


@pytest.fixture
def fake_piper(monkeypatch):
    mod = types.ModuleType("piper")

    class PiperVoice:
        loaded = []

        @classmethod
        def load(cls, path):
            cls.loaded.append(path)
            return cls()

        def synthesize_wav(self, text, wf):
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * 2205 * max(1, len(text.split())))

    mod.PiperVoice = PiperVoice
    monkeypatch.setitem(sys.modules, "piper", mod)
    return PiperVoice


def test_speak_out_writes_wav(voice, fake_piper, tmp_path):
    onnx = tmp_path / "v.onnx"
    onnx.write_bytes(b"x")
    out = tmp_path / "o.wav"
    assert voice.speak.main(["--out", str(out), "--voice", str(onnx), "hello", "there", "world"]) == 0
    with wave.open(str(out)) as w:
        assert w.getframerate() == 22050 and w.getnframes() == 3 * 2205
    assert fake_piper.loaded == [str(onnx)]
    assert not voice.common.SPEAKING_FILE.exists()


def test_speak_plays_and_holds_speaking_flag(voice, fake_piper, tmp_path, monkeypatch):
    onnx = tmp_path / "v.onnx"
    onnx.write_bytes(b"x")
    seen = {}

    def fake_play(path):
        seen["flag"] = voice.common.speaking_pid()
        seen["wav"] = Path(path).read_bytes()[:4]
    monkeypatch.setattr(voice.speak, "play", fake_play)
    assert voice.speak.main(["--voice", str(onnx), "say this out loud"]) == 0
    assert seen == {"flag": os.getpid(), "wav": b"RIFF"}
    assert not voice.common.SPEAKING_FILE.exists()


def test_speak_without_piper_uses_fallback(voice, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "piper", None)  # import fails
    calls = []
    monkeypatch.setattr(voice.speak, "fallback_synthesize", lambda t, o: calls.append(t) or False)
    assert voice.speak.main(["--out", str(tmp_path / "x.wav"), "no voice here"]) == 1
    assert calls == ["no voice here"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX players")
def test_player_command(voice):
    cmd = voice.speak.player_command("/tmp/x.wav")
    if IS_MACOS:
        assert cmd == ["afplay", "/tmp/x.wav"]
    else:
        assert cmd is None or cmd[-1] == "/tmp/x.wav"


# --- session -----------------------------------------------------------------------


def test_typist_sends_text_then_enter_separately(voice):
    writes = []
    t = voice.session.Typist(writes.append, barge_in=False)
    t.send("ok")  # gated: too short
    t.send("open the deploy logs\nplease")
    deadline = time.time() + 5
    while len(writes) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert writes == [b"open the deploy logs please", b"\r"]


def test_typist_barge_in_sends_escape_first(voice, monkeypatch):
    stopped = []
    monkeypatch.setattr(voice.common, "stop_speaking", lambda: stopped.append(1))
    writes = []
    t = voice.session.Typist(writes.append, barge_in=True)
    t.send("stop what you are doing")
    deadline = time.time() + 5
    while len(writes) < 3 and time.time() < deadline:
        time.sleep(0.05)
    assert writes == [b"\x1b", b"stop what you are doing", b"\r"] and stopped == [1]


def test_inject_server_needs_the_token(voice):
    sent = []

    class FakeTypist:
        def send(self, text, force=False):
            sent.append((text, force))
    srv = voice.session.InjectServer(FakeTypist())

    def talk(msg):
        with socket.create_connection(("127.0.0.1", srv.port), timeout=5) as c:
            c.sendall((json.dumps(msg) + "\n").encode())
            return c.recv(64).decode().strip()
    assert talk({"token": "wrong", "text": "nope nope nope"}) == "denied"
    assert talk({"token": srv.token, "text": "hello from a tool", "force": True}) == "ok"
    assert sent == [("hello from a tool", True)]


def test_send_without_session(voice):
    assert voice.session.send("anything at all") == 1


STUB = textwrap.dedent("""
    import os, sys
    out = sys.argv[1]
    print("stub ready", flush=True)
    for line in sys.stdin:
        line = line.replace("\\x1b", "").strip()
        if line:
            with open(out, "a") as f:
                f.write(line + "\\n")
        if line == "goodbye stub process now":
            sys.exit(3)
""")


@pytest.mark.skipif(os.name == "nt", reason="POSIX pty; Windows is covered by the CI e2e job")
def test_session_pty_with_stub(tree, tmp_path):
    """The real session.py runs a stub in its pty; --send types into it; the
    stub's exit code comes back and session.json is cleaned up."""
    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    got = tmp_path / "got.txt"
    env = dict(os.environ, NARRATE_BARGE_IN="0", NARRATE_RELEVANCE="0")
    proc = subprocess.Popen([sys.executable, str(tree / "voice" / "session.py"), "--no-listen", "--",
                             sys.executable, str(stub), str(got)], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    state = tree / "state" / "session.json"
    deadline = time.time() + 20
    while not state.exists() and time.time() < deadline:
        time.sleep(0.1)
    st = json.loads(state.read_text())
    assert st["mode"] == "pty" and st["pid"] == proc.pid
    if os.name != "nt":
        assert (state.stat().st_mode & 0o777) == 0o600

    def send(text):
        return subprocess.run([sys.executable, str(tree / "voice" / "session.py"), "--send", text],
                              env=env, capture_output=True, text=True, timeout=20)
    assert send("hi").returncode == 0          # accepted, then dropped by the gate
    assert send("open the deploy logs").returncode == 0
    time.sleep(1.0)  # let the typist finish before the keyboard types
    # Keyboard input still passes through to the program.
    proc.stdin.write(b"typed by hand on the keyboard\n")
    proc.stdin.flush()
    time.sleep(0.5)
    assert send("goodbye stub process now").returncode == 0
    out, _ = proc.communicate(timeout=20)
    assert proc.returncode == 3, out
    lines = got.read_text().splitlines()
    assert lines == ["open the deploy logs", "typed by hand on the keyboard", "goodbye stub process now"]
    assert b"stub ready" in out
    assert not state.exists()


def test_session_missing_command(tree):
    r = subprocess.run([sys.executable, str(tree / "voice" / "session.py"), "--no-listen", "--",
                        "definitely-not-a-real-command-xyz"], capture_output=True, text=True, timeout=20)
    assert r.returncode != 0 and "not found" in r.stderr


def test_relevance_coprocess_filters_lines(voice, tmp_path, monkeypatch):
    """Relevance runs relevance.py as a co-process: pet talk is dropped.
    HOME is an empty dir so relevance.py can't find (and start) a judge."""
    kept = []
    monkeypatch.setenv("HOME", str(tmp_path))
    rel = voice.session.Relevance(kept.append)
    try:
        rel.feed("open the deploy logs")
        rel.feed("good boy")
        rel.feed("claude rerun the failing step")
        deadline = time.time() + 15
        while len(kept) < 2 and time.time() < deadline:
            time.sleep(0.1)
        time.sleep(0.3)
    finally:
        rel.close()
    assert kept == ["open the deploy logs", "claude rerun the failing step"]
