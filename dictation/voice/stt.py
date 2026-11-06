#!/usr/bin/env python3
"""stt.py: local speech to text with Parakeet (when installed) or whisper.cpp.

Listens on the microphone, cuts the audio into utterances with a simple
voice activity detector (an adaptive energy gate that decides when you
stopped talking), and sends each utterance to a whisper-server that this
process starts and keeps loaded. whisper.cpp's own Silero VAD runs inside
the server too, so stretches with no speech never turn into text.

Prints one transcript per line on stdout (the same contract as the Swift
listener), status on stderr. Pauses while the computer is talking (see
common.is_speaking) so the assistant never hears itself.

  stt.py                      listen on the default microphone
  stt.py --file a.wav ...     run WAV files through the same VAD + whisper
                              path instead of the mic (tests, no mic needed)

Env:
  LISTEN_SILENCE_SEC   silence that ends an utterance (default 1.0)
  LISTEN_MAX_UTTER_SEC hard cap on one utterance (default 60)
  LISTEN_MIN_SPEECH_SEC shorter bursts are ignored (default 0.2)
  LISTEN_EMIT_WAV      1 = print "text<TAB>wav_path" (for the voiceprint filter)
  NARRATE_BARGE_IN     2 = keep listening while the computer talks, cancel its
                       own voice and stop it when you talk over it (bargein.py;
                       same as --barge-in). Anything else: deaf while it talks.
  NARRATE_WHISPER_LANG spoken language (default en; "auto" to detect)
  NARRATE_WHISPER_THREADS  CPU threads for whisper (default: half the cores, 4-8)
"""

import collections
import io
import json
import math
import os
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

RATE = 16000
FRAME = 480  # 30 ms


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --- voice activity detection ------------------------------------------------


def rms(frame) -> float:
    if not frame:
        return 0.0
    return math.sqrt(sum(x * x for x in frame) / len(frame))


class Endpointer:
    """Splits a stream of 30 ms float frames into utterances.

    Speech starts when the frame energy stays above the threshold for a few
    frames, and ends after LISTEN_SILENCE_SEC below it. The threshold is a
    few times the room's noise floor (the quietest frame of the last 5 s),
    so a fan or a hum doesn't count as talking.
    Each finished utterance is passed to on_utterance as an array('f').
    """

    def __init__(self, on_utterance, silence_sec=None, max_sec=None, min_speech_sec=None,
                 start_frames=3, preroll_sec=0.5, min_level=None, ratio=3.0, floor_sec=5.0):
        self.on_utterance = on_utterance
        self.silence_frames = int((silence_sec or _env_float("LISTEN_SILENCE_SEC", 1.0)) * RATE / FRAME)
        self.max_frames = int((max_sec or _env_float("LISTEN_MAX_UTTER_SEC", 60.0)) * RATE / FRAME)
        self.min_speech_frames = int((min_speech_sec or _env_float("LISTEN_MIN_SPEECH_SEC", 0.2)) * RATE / FRAME)
        self.start_frames = start_frames
        self.preroll = int(preroll_sec * RATE / FRAME)
        # Absolute floor under the room-relative gate. 0.006 (-44 dBFS) was above most of
        # a quiet USB mic's speech (the mini's fifine: noise -70, speech peaks -39 dBFS),
        # so only leaning in close got heard. LISTEN_MIN_LEVEL overrides.
        self.min_level = _env_float("LISTEN_MIN_LEVEL", 0.0015) if min_level is None else min_level
        self.ratio = ratio
        self.floor = 0.0
        self.levels = collections.deque(maxlen=int(floor_sec * RATE / FRAME))
        self.reset()

    def reset(self):
        self.ring = []
        self.frames = []
        self.in_speech = False
        self.loud_run = 0
        self.quiet_run = 0
        self.speech_frames = 0

    def threshold(self) -> float:
        return max(self.min_level, self.floor * self.ratio)

    def feed(self, frame):
        level = rms(frame)
        loud = level > self.threshold()
        # Noise floor = the quietest frame of the last few seconds. Speech
        # always has gaps between words, so this is the room, not the voice;
        # a fan that switches on becomes the new floor once it fills the window.
        self.levels.append(level)
        self.floor = min(self.levels)
        if not self.in_speech:
            self.ring.append(frame)
            if len(self.ring) > self.preroll + self.start_frames:
                self.ring.pop(0)
            self.loud_run = self.loud_run + 1 if loud else 0
            if self.loud_run >= self.start_frames:
                self.in_speech = True
                self.frames = list(self.ring)
                self.speech_frames = self.loud_run
                self.quiet_run = 0
            return
        self.frames.append(frame)
        if loud:
            self.speech_frames += 1
            self.quiet_run = 0
        else:
            self.quiet_run += 1
        if self.quiet_run >= self.silence_frames or len(self.frames) >= self.max_frames:
            self.flush()

    def flush(self):
        if self.in_speech and self.speech_frames >= self.min_speech_frames:
            # Drop most of the trailing silence; keep a short tail.
            keep = len(self.frames) - max(0, self.quiet_run - 8)
            audio = array("f")
            for f in self.frames[:keep]:
                audio.extend(f)
            self.reset()
            self.on_utterance(audio)
        else:
            self.reset()


# --- audio helpers -------------------------------------------------------------


def to_wav_bytes(samples) -> bytes:
    pcm = array("h", (max(-32768, min(32767, int(x * 32767))) for x in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def resample(samples, src_rate, dst_rate=RATE):
    if src_rate == dst_rate:
        return samples
    n = int(len(samples) * dst_rate / src_rate)
    out = array("f", bytes(4 * n))
    step = src_rate / dst_rate
    last = len(samples) - 1
    for i in range(n):
        pos = i * step
        j = int(pos)
        frac = pos - j
        a = samples[j]
        b = samples[j + 1] if j < last else a
        out[i] = a + (b - a) * frac
    return out


def read_wav(path) -> array:
    """Any PCM WAV -> mono float samples at 16 kHz."""
    with wave.open(str(path), "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        ints = array("h", raw)
        if sys.byteorder == "big":
            ints.byteswap()
        scale = 32768.0
    elif width == 4:
        ints = array("i", raw)
        if sys.byteorder == "big":
            ints.byteswap()
        scale = 2147483648.0
    elif width == 1:
        ints = array("h", (b - 128 for b in raw))
        scale = 128.0
    else:
        raise ValueError(f"unsupported sample width {width}")
    mono = array("f", bytes(4 * (len(ints) // ch)))
    for i in range(len(mono)):
        mono[i] = sum(ints[i * ch + c] for c in range(ch)) / (ch * scale)
    return resample(mono, rate)


# --- whisper-server -------------------------------------------------------------


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def default_threads() -> int:
    env = os.environ.get("NARRATE_WHISPER_THREADS")
    if env and env.isdigit():
        return int(env)
    return max(4, min(8, (os.cpu_count() or 8) // 2))


class WhisperServer:
    """A whisper-server child process with the model kept in memory."""

    PID_FILE = common.STATE_DIR / "whisper-server.pid"

    def __init__(self, model=None, binary=None, vad=None, lang=None, port=None):
        self.model = Path(model) if model else common.pick_model()
        self.binary = Path(binary) if binary else common.whisper_server_bin()
        self.vad = vad if vad is not None else common.vad_model()
        self.lang = lang or os.environ.get("NARRATE_WHISPER_LANG", "en")
        self.port = port or free_port()
        self.proc = None

    def command(self):
        cmd = [str(self.binary), "-m", str(self.model), "--host", "127.0.0.1",
               "--port", str(self.port), "-l", self.lang, "-t", str(default_threads()), "-nt"]
        if self.vad:
            cmd += ["--vad", "-vm", str(self.vad)]
        return cmd

    def start(self, timeout=180):
        if not self.binary.exists():
            raise FileNotFoundError(f"whisper-server not found at {self.binary} (run install.sh)")
        if not self.model.exists():
            raise FileNotFoundError(f"whisper model not found at {self.model} (run install.sh)")
        self._kill_stale()
        kw = {}
        if common.IS_WINDOWS:
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        elif sys.platform.startswith("linux"):
            kw["preexec_fn"] = _die_with_parent
        log_path = common.STATE_DIR / "whisper-server.log"
        common.STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(self.command(), stdout=open(log_path, "ab"),
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        self.PID_FILE.write_text(str(self.proc.pid))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"whisper-server exited ({self.proc.returncode}); see {log_path}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return self
            except OSError:
                time.sleep(0.2)
        self.stop()
        raise TimeoutError("whisper-server did not come up")

    def _kill_stale(self):
        try:
            pid = int(self.PID_FILE.read_text().strip())
        except Exception:
            return
        if common.pid_alive(pid) and _looks_like_whisper(pid):
            try:
                if common.IS_WINDOWS:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            if self.proc and self.PID_FILE.read_text().strip() == str(self.proc.pid):
                self.PID_FILE.unlink()
        except Exception:
            pass

    def transcribe(self, wav_bytes: bytes, timeout=120) -> str:
        import urllib.request
        boundary = uuid.uuid4().hex
        # verbose_json carries whisper's per-segment no-speech probability (phantom filter).
        fields = {"response_format": "verbose_json", "temperature": "0.0", "no_timestamps": "true"}
        body = io.BytesIO()
        for k, v in fields.items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"u.wav\"\r\n"
                   "Content-Type: audio/wav\r\n\r\n".encode())
        body.write(wav_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/inference", data=body.getvalue(),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        probs = [s.get("no_speech_prob") for s in data.get("segments") or []
                 if isinstance(s, dict) and s.get("no_speech_prob") is not None]
        self.last_no_speech = min(probs) if probs else None
        return clean_text(data.get("text", ""))


class ParakeetServer:
    """NVIDIA Parakeet TDT 0.6B v3 (ONNX, int8) in-process via onnx-asr: ~7x faster than whisper here.

    Used instead of whisper when the model folder exists (NARRATE_PARAKEET_MODEL, default
    $NARRATE_DATA/models/parakeet-tdt-0.6b-v3-int8: encoder/decoder .onnx, nemo128.onnx, vocab.txt and
    a config.json with "features_size": 128) and onnx-asr is installed. NARRATE_STT=whisper turns it off.
    """

    def __init__(self, model=None):
        self.model = Path(model) if model else common.parakeet_model()
        self.asr = None

    @classmethod
    def available(cls):
        if os.environ.get("NARRATE_STT", "").lower() == "whisper" or not common.parakeet_model().is_dir():
            return False
        try:
            import onnx_asr  # noqa: F401
            return True
        except ImportError:
            return False

    def start(self):
        import onnx_asr
        # CPU beats CoreML here (most of the graph falls back to CPU anyway, in many small partitions)
        name = "nemo-" + self.model.name.removesuffix("-int8")  # nemo-parakeet-tdt-0.6b-v2 / -v3
        if "parakeet-tdt" not in name:  # a custom NARRATE_PARAKEET_MODEL folder name
            name = "nemo-parakeet-tdt-0.6b-v3"
        self.asr = onnx_asr.load_model(name, str(self.model), quantization="int8",
                                       providers=["CPUExecutionProvider"])
        return self

    def stop(self):
        self.asr = None

    def transcribe(self, wav_bytes: bytes, timeout=None) -> str:
        import numpy as np
        with wave.open(io.BytesIO(wav_bytes)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return clean_text(self.asr.recognize(audio, sample_rate=RATE))


def make_server(model=None):
    return ParakeetServer() if model is None and ParakeetServer.available() else WhisperServer(model=model)


def _die_with_parent():
    # Linux sends this signal when the *thread* that started the server
    # exits, so start it from a thread that lives as long as the listener.
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:
        pass


def _looks_like_whisper(pid: int) -> bool:
    if common.IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return "whisper-server" in out
    out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    return "whisper-server" in out


# Whisper fills silence or noise with these; they are never a real request.
HALLUCINATIONS = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.",
                  "thanks for watching.", ".", "bye.", "[blank_audio]", "(silence)"}


# What whisper says when it hears a breath, a click or the room. Only dropped when the
# audio backs that up (see is_phantom): a real, clearly spoken "okay" still goes through.
FILLERS = {"okay", "ok", "okay okay", "thank you", "thanks", "you", "bye", "bye bye",
           "hmm", "mm", "mhm", "um", "uh", "oh", "so", "the end", "i'm sorry"}
NO_SPEECH_DROP = 0.8       # whisper is this sure nothing was said...
NO_SPEECH_MAX_LOUD_SEC = 0.4  # ...and the audio agrees: drop whatever it wrote. (A real
                              # "Stop, tell me about mountains" came back at 0.6+ in the room.)
NO_SPEECH_FILLER = 0.2     # ...or a lone filler with even this much doubt
FILLER_MIN_LOUD_SEC = 0.25  # a lone filler needs this much clearly-voiced audio behind it


def loud_seconds(audio) -> float:
    """Seconds of the utterance well above its own quietest part (the room)."""
    levels = [rms(audio[i:i + FRAME]) for i in range(0, len(audio) - FRAME + 1, FRAME)]
    if not levels:
        return 0.0
    quiet = sorted(levels)[len(levels) // 5]
    gate = max(0.002, 4 * quiet)
    return sum(1 for v in levels if v > gate) * FRAME / RATE


def is_phantom(text: str, audio, no_speech=None) -> bool:
    """A transcript nobody said: whisper's no-speech call, or a lone filler on a blip."""
    if no_speech is not None and no_speech >= NO_SPEECH_DROP and loud_seconds(audio) < NO_SPEECH_MAX_LOUD_SEC:
        return True
    words = text.lower().strip().strip(".!?,").strip()
    if words not in FILLERS:
        return False
    if no_speech is not None and no_speech >= NO_SPEECH_FILLER:
        return True
    return loud_seconds(audio) < FILLER_MIN_LOUD_SEC


def clean_text(text: str) -> str:
    text = " ".join((text or "").split())
    return "" if text.lower() in HALLUCINATIONS else text


LIVE_FILE = common.STATE_DIR / "live.json"
LIVE_EVERY_SEC = 0.4

# --- the listener ------------------------------------------------------------------


class Listener:
    """Mic (or WAV files) -> Endpointer -> whisper-server -> on_text(text, wav_path)."""

    def __init__(self, on_text, server=None, emit_wav=False):
        self.on_text = on_text
        self.server = server or make_server()
        self.emit_wav = emit_wav
        self.jobs = queue.Queue()
        self.stopping = threading.Event()
        self.endpointer = Endpointer(self.jobs.put)
        self.speaking = False
        self._muted_until = 0.0
        self.barge_in = None  # set by run_mic when barge-in is on and AEC loads
        self._worker = threading.Thread(target=self._transcribe_loop, daemon=True)
        # Live transcript for the Claude Code band (only Parakeet is fast enough to re-run mid-utterance).
        self.live = isinstance(self.server, ParakeetServer)

    def start(self):
        self.server.start()
        self._worker.start()
        return self

    def stop(self):
        self.stopping.set()
        self.jobs.put(None)
        self.server.stop()
        if getattr(self, "_ref", None):
            self._ref.stop()

    def _live(self, state, text):
        if self.live:
            try:
                LIVE_FILE.write_text(json.dumps({"state": state, "text": text, "t": time.time()}), encoding="utf-8")
            except OSError:
                pass

    def _transcribe_loop(self):
        while True:
            try:
                audio = self.jobs.get(timeout=LIVE_EVERY_SEC if self.live else None)
            except queue.Empty:
                # Mid-utterance: re-transcribe what's been said so far and show it.
                frames = list(self.endpointer.frames) if self.endpointer.in_speech else []
                if frames:
                    so_far = array("f")
                    for f in frames:
                        so_far.extend(f)
                    try:
                        self._live("live", self.server.transcribe(to_wav_bytes(so_far)))
                    except Exception:
                        pass
                continue
            if audio is None:
                return
            wav = to_wav_bytes(audio)
            try:
                text = self.server.transcribe(wav)
            except Exception as e:
                common.log(f"stt: transcription failed: {e}")
                self._live("done", "")
                continue
            if text and is_phantom(text, audio, getattr(self.server, "last_no_speech", None)):
                try:
                    with open(common.STATE_DIR / "dropped.log", "a", encoding="utf-8") as f:
                        f.write(f"stt\tphantom\t{text}\n")
                except OSError:
                    pass
                text = ""
            self._live("done", text)
            if not text:
                continue
            path = ""
            if self.emit_wav:
                fd, path = tempfile.mkstemp(prefix="utt-", suffix=".wav", dir=str(common.STATE_DIR))
                with os.fdopen(fd, "wb") as f:
                    f.write(wav)
            try:
                self.on_text(text, path)
            except Exception as e:
                common.log(f"stt: handler failed: {e}")

    def run_file(self, path):
        audio = read_wav(path)
        for i in range(0, len(audio) - FRAME + 1, FRAME):
            self.endpointer.feed(audio[i:i + FRAME])
        # A file ends like a speaker going quiet.
        for _ in range(self.endpointer.silence_frames + 1):
            self.endpointer.feed(array("f", bytes(4 * FRAME)))

    def drain(self):
        self.jobs.put(None)
        self._worker.join()

    # Microphone ---------------------------------------------------------------

    def _speaking_poller(self):
        while not self.stopping.is_set():
            now_speaking = common.is_speaking()
            if now_speaking:
                self._muted_until = time.monotonic() + 0.4  # room echo tail
            self.speaking = now_speaking
            time.sleep(0.15)

    def _barge_setup(self, want):
        if not want:
            return None
        import bargein
        if not bargein.EchoCanceller.available():
            common.log("stt: barge-in needs the echo canceller (pip install livekit numpy); "
                       "staying deaf while the computer talks")
            return None
        common.log("stt: barge-in on (WebRTC AEC3 + level gate); talk over the voice to stop it")
        ref = bargein.Reference(active=lambda: not self.stopping.is_set()).start()
        return bargein.BargeIn(), ref

    def run_mic(self, barge_in=None):
        import sounddevice as sd  # only needed for the live mic
        import bargein

        threading.Thread(target=self._speaking_poller, daemon=True).start()
        barge = self._barge_setup(bargein.enabled() if barge_in is None else barge_in)
        if barge:
            self.barge_in, self._ref = barge
        frames = queue.Queue()
        rate = RATE
        try:
            sd.check_input_settings(samplerate=RATE, channels=1, dtype="float32")
        except Exception:
            rate = int(sd.query_devices(kind="input")["default_samplerate"])

        def callback(indata, n, t, status):
            frames.put((time.time(), array("f", bytes(indata))))

        blocksize = int(FRAME * rate / RATE)
        common.log(f"stt: listening (model {self.server.model.name}, {rate} Hz)")
        with sd.RawInputStream(samplerate=rate, channels=1, dtype="float32",
                            blocksize=blocksize, callback=callback):
            while not self.stopping.is_set():
                try:
                    stamp, block = frames.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.feed_block(resample(block, rate) if rate != RATE else block, stamp, time.monotonic())

    def feed_block(self, block, stamp, now):
        """One 16 kHz mic block captured at wall-clock `stamp`; `now` is time.monotonic()."""
        if not hasattr(self, "_pending"):
            self._pending = array("f")
            self._received = 0       # 16 kHz samples in; `_received` lines up with `stamp`
            self._done = 0           # samples handed on
            self._reply, self._anchor, self._barged_until, self._last_dbg = None, 0, 0.0, 0.0
            self._barge_cap, self._killed = 0.0, None
        self._received += len(block)
        if not self.barge_in:
            if self.speaking or now < self._muted_until:
                self.endpointer.reset()
                self._pending = array("f")
                return
            self._pending.extend(block)
            while len(self._pending) >= FRAME:
                self.endpointer.feed(self._pending[:FRAME])
                del self._pending[:FRAME]
            return

        import bargein
        self._pending.extend(block)
        while len(self._pending) >= FRAME:
            frame = self._pending[:FRAME]
            del self._pending[:FRAME]
            start = self._done
            self._done += FRAME
            if now < self._barged_until:
                cur, unknown = self._ref.snapshot()
                if unknown or (cur is not None and cur[0] != self._killed):
                    # Something new started playing: close the window. Its voice must
                    # never reach the transcriber uncancelled: drop the frames since it
                    # started, send what the person said before that, and let the
                    # speaking path below take over (with the new reference, or deaf).
                    self._barged_until = 0.0
                    ep = self.endpointer
                    if ep.in_speech:
                        since = stamp - cur[2] if cur is not None else 0.3
                        drop = min(len(ep.frames), int(since * RATE / FRAME) + 2)
                        del ep.frames[len(ep.frames) - drop:]
                        ep.quiet_run = max(0, ep.quiet_run - drop)
                        ep.flush()
                    ep.reset()
                else:
                    # Just interrupted: the voice is stopped. Keep the canceller running on
                    # the room's echo tail (reference now silent) and transcribe.
                    clean, _ = self.barge_in.feed(frame, bargein.ref_frame((), 0, FRAME))
                    self.endpointer.feed(array("f", clean))
                    if self.endpointer.in_speech:
                        self._barged_until = min(now + 1.0, self._barge_cap)
                    continue
            if not (self.speaking or now < self._muted_until):
                self._reply = None
                self.barge_in.idle(frame)
                self.endpointer.feed(frame)
                continue
            cur, _unknown = self._ref.snapshot()
            if cur is None:
                # Talking, but we can't see what it plays: stay deaf (fail safe).
                self.endpointer.reset()
                continue
            key, samples, t0 = cur
            if key != self._reply:
                self._reply = key
                # Where playback t0 falls in our count of mic samples.
                self._anchor = self._received - int((stamp - t0) * RATE)
                self.barge_in.start_reply()
                self.endpointer.reset()
            ref = bargein.ref_frame(samples, start - self._anchor, FRAME)
            _, fired = self.barge_in.feed(frame, ref)
            if os.environ.get("NARRATE_BARGE_DEBUG") == "1" and now - self._last_dbg > 0.5:
                self._last_dbg = now
                det = self.barge_in.det
                bargein.log(f"level {self.barge_in.last_level:.1f} dB, needs > {det.threshold_db():.1f} "
                            f"(noise {det.noise_db}, leak {det.leak_db}, coupling {det.coupling_db})")
            if fired:
                bargein.log(f"barge-in ({self.barge_in.last_level:.1f} dB over "
                            f"{self.barge_in.det.echo_db:.1f} dB echo), stopping the voice")
                bargein.stop_playback()
                self.endpointer.reset()
                for f in self.barge_in.take_preroll():
                    self.endpointer.feed(array("f", f))
                self._barged_until = now + 1.5
                # Hard cap: the window never outlives one long sentence.
                self._barge_cap = now + 15.0
                self._killed = key
                self._reply = None


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", nargs="*", help="transcribe WAV files through the VAD instead of the mic")
    ap.add_argument("--model", help="ggml model path (default: picked for this machine)")
    ap.add_argument("--barge-in", action="store_true",
                    help="keep listening while the computer talks and stop it when you talk over it")
    ap.add_argument("--check", action="store_true",
                    help="exit 0 if whisper-server and a model are installed, print what will load")
    args = ap.parse_args(argv)

    if args.check:
        if args.model is None and ParakeetServer.available():
            print(f"parakeet {ParakeetServer().model.name}")
            return 0
        server = WhisperServer(model=args.model)
        missing = [str(p) for p in (server.binary, server.model) if not p.exists()]
        if missing:
            common.log("stt: missing " + ", ".join(missing))
            return 1
        print(f"whisper.cpp {server.model.name}" + (" + silero vad" if server.vad else ""))
        return 0

    emit_wav = os.environ.get("LISTEN_EMIT_WAV") == "1"

    def out(text, wav):
        sys.stdout.write(f"{text}\t{wav}\n" if wav else text + "\n")
        sys.stdout.flush()

    listener = Listener(out, server=make_server(args.model), emit_wav=emit_wav)
    try:
        listener.start()
    except Exception as e:
        common.log(f"stt: {e}")
        return 4
    try:
        if args.file is not None:
            for f in args.file:
                listener.run_file(f)
            listener.drain()
        else:
            signal.signal(signal.SIGTERM, lambda *a: listener.stopping.set())
            listener.run_mic(barge_in=True if args.barge_in else None)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
