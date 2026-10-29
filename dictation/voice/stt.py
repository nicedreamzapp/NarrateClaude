#!/usr/bin/env python3
"""stt.py: local speech to text with whisper.cpp.

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
  LISTEN_MIN_SPEECH_SEC shorter bursts are ignored (default 0.35)
  LISTEN_EMIT_WAV      1 = print "text<TAB>wav_path" (for the voiceprint filter)
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
                 start_frames=3, preroll_sec=0.5, min_level=0.006, ratio=3.0, floor_sec=5.0):
        self.on_utterance = on_utterance
        self.silence_frames = int((silence_sec or _env_float("LISTEN_SILENCE_SEC", 1.0)) * RATE / FRAME)
        self.max_frames = int((max_sec or _env_float("LISTEN_MAX_UTTER_SEC", 60.0)) * RATE / FRAME)
        self.min_speech_frames = int((min_speech_sec or _env_float("LISTEN_MIN_SPEECH_SEC", 0.35)) * RATE / FRAME)
        self.start_frames = start_frames
        self.preroll = int(preroll_sec * RATE / FRAME)
        self.min_level = min_level
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
        fields = {"response_format": "json", "temperature": "0.0", "no_timestamps": "true"}
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
        return clean_text(data.get("text", ""))


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


def clean_text(text: str) -> str:
    text = " ".join((text or "").split())
    return "" if text.lower() in HALLUCINATIONS else text


# --- the listener ------------------------------------------------------------------


class Listener:
    """Mic (or WAV files) -> Endpointer -> whisper-server -> on_text(text, wav_path)."""

    def __init__(self, on_text, server=None, emit_wav=False):
        self.on_text = on_text
        self.server = server or WhisperServer()
        self.emit_wav = emit_wav
        self.jobs = queue.Queue()
        self.stopping = threading.Event()
        self.endpointer = Endpointer(self.jobs.put)
        self.speaking = False
        self._muted_until = 0.0
        self._worker = threading.Thread(target=self._transcribe_loop, daemon=True)

    def start(self):
        self.server.start()
        self._worker.start()
        return self

    def stop(self):
        self.stopping.set()
        self.jobs.put(None)
        self.server.stop()

    def _transcribe_loop(self):
        while True:
            audio = self.jobs.get()
            if audio is None:
                return
            wav = to_wav_bytes(audio)
            try:
                text = self.server.transcribe(wav)
            except Exception as e:
                common.log(f"stt: transcription failed: {e}")
                continue
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

    def run_mic(self):
        import sounddevice as sd  # only needed for the live mic

        threading.Thread(target=self._speaking_poller, daemon=True).start()
        frames = queue.Queue()
        rate = RATE
        try:
            sd.check_input_settings(samplerate=RATE, channels=1, dtype="float32")
        except Exception:
            rate = int(sd.query_devices(kind="input")["default_samplerate"])

        def callback(indata, n, t, status):
            frames.put(array("f", bytes(indata)))

        blocksize = int(FRAME * rate / RATE)
        common.log(f"stt: listening (model {self.server.model.name}, {rate} Hz)")
        with sd.RawInputStream(samplerate=rate, channels=1, dtype="float32",
                            blocksize=blocksize, callback=callback):
            pending = array("f")
            while not self.stopping.is_set():
                try:
                    block = frames.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self.speaking or time.monotonic() < self._muted_until:
                    self.endpointer.reset()
                    pending = array("f")
                    continue
                pending.extend(resample(block, rate) if rate != RATE else block)
                while len(pending) >= FRAME:
                    self.endpointer.feed(pending[:FRAME])
                    del pending[:FRAME]


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", nargs="*", help="transcribe WAV files through the VAD instead of the mic")
    ap.add_argument("--model", help="ggml model path (default: picked for this machine)")
    ap.add_argument("--check", action="store_true",
                    help="exit 0 if whisper-server and a model are installed, print what will load")
    args = ap.parse_args(argv)

    if args.check:
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

    listener = Listener(out, server=WhisperServer(model=args.model), emit_wav=emit_wav)
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
            listener.run_mic()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
