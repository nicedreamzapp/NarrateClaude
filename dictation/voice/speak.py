#!/usr/bin/env python3
"""speak.py: the default open-source voice (Piper TTS, fully local).

  speak.py "text to say"            synthesize and play it
  speak.py --out reply.wav "text"   write a WAV file, play nothing

Your own ~/.local/bin/speak always wins; this is what the installer points
speak at when you don't have one. While it plays, state/speaking.pid holds
its pid so the listener stays deaf to it, and a new voice request (barge-in)
can stop it.

Players: afplay on macOS, the first of pw-play / paplay / aplay / ffplay on
Linux, the built-in winsound on Windows. If Piper isn't installed, macOS
falls back to `say` and Linux to espeak-ng.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

_player = None


# Chatterbox tags ([laugh], [chuckle], [sigh], ...): other voices would read them out.
TAG_RE = re.compile(r"\[[a-z ]+\]\s*", re.I)


def synthesize(text: str, out_path: str, voice_path=None) -> None:
    """Text -> WAV with Piper. Raises if Piper or the voice is missing."""
    from piper import PiperVoice  # installed into the venv by install.sh

    voice_path = Path(voice_path) if voice_path else common.piper_voice()
    if not voice_path.exists():
        raise FileNotFoundError(f"Piper voice not found: {voice_path}")
    voice = PiperVoice.load(str(voice_path))
    with wave.open(out_path, "wb") as wf:
        voice.synthesize_wav(text, wf)


CHATTERBOX_PY = Path("~/.local/share/explain-as-podcast/venv/bin/python").expanduser()
CHATTERBOX_VOICE = os.environ.get("NARRATE_CHATTERBOX_VOICE", "~/.local/share/explain-as-podcast/voices/s1.wav")


def chatterbox_connect():
    """A socket to chatterbox_server.py with the request not yet sent; starts the server on first use
    (loading the model takes ~20 s once)."""
    import socket
    import time
    sock_path = str(common.STATE_DIR / "chatterbox.sock")

    def connect():
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(sock_path)
            return s
        except OSError:
            s.close()
            raise

    try:
        return connect()
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    if not CHATTERBOX_PY.exists():
        raise FileNotFoundError(f"Chatterbox venv not found: {CHATTERBOX_PY}")
    common.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(common.STATE_DIR / "chatterbox.log", "ab") as logf:
        subprocess.Popen([str(CHATTERBOX_PY), str(Path(__file__).with_name("chatterbox_server.py")),
                          sock_path, CHATTERBOX_VOICE], stdout=logf, stderr=logf,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(240):  # up to 2 minutes for the first model load
        time.sleep(0.5)
        try:
            return connect()
        except (FileNotFoundError, ConnectionRefusedError):
            continue
    raise RuntimeError("chatterbox server didn't start; see state/chatterbox.log")


def chatterbox_play(sock, text: str) -> None:
    """Play the line through ffplay while the server is still generating it.

    ffplay is fed 0.2 s blocks in real time, and silence whenever the next piece isn't ready yet:
    on macOS ffplay goes quiet for good if its input stalls (same trick as explain-as-podcast).
    """
    import queue
    import threading
    import time
    global _player
    sr, block = 24000, 24000 // 5 * 4  # float32 mono: 0.2 s = 19200 bytes
    env = dict(os.environ, SDL_AUDIO_DRIVER="coreaudio", SDL_AUDIODRIVER="coreaudio") if common.IS_MACOS else None
    sock.sendall((" ".join(text.split()) + "\n").encode())
    q = queue.Queue()

    def read():
        try:
            while data := sock.recv(65536):
                q.put(data)
        except OSError:  # socket closed under us by a barge-in
            pass
        finally:
            q.put(None)

    threading.Thread(target=read, daemon=True).start()
    _player = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-f", "f32le",
                                "-ar", str(sr), "-ch_layout", "mono", "-i", "-"],
                               stdin=subprocess.PIPE, env=env)
    # The first streamed piece (~0.56 s of audio) lands at ~0.5 s, but the second takes ~1.1 s more,
    # so playing at once speaks a word, stalls, then resumes. Wait for ~1 s of audio (or the end) first.
    preroll = int(float(os.environ.get("NARRATE_CB_PREROLL", "1.0")) * sr) * 4
    buf, done, sent, t0, started = b"", False, 0.0, time.monotonic(), False
    try:
        while not done or buf:
            while not done:
                try:
                    data = q.get_nowait()
                except queue.Empty:
                    break
                if data is None:
                    done = True
                else:
                    buf += data
            started = started or done or len(buf) >= preroll
            if started and (len(buf) >= block or (done and buf)):
                cut = min(len(buf), block) // 4 * 4
                data, buf = buf[:cut], buf[cut:]
                if not data:  # a stray partial sample at the very end
                    break
            else:
                data = bytes(block)  # nothing ready yet: keep ffplay fed with silence
            _player.stdin.write(data)
            sent += len(data) / 4 / sr
            ahead = sent - (time.monotonic() - t0)
            if ahead > 0.5:
                time.sleep(ahead - 0.5)
        _player.stdin.close()
        _player.wait()
    except BrokenPipeError:
        pass
    finally:
        _player = None


def fallback_synthesize(text: str, out_path: str) -> bool:
    """Built-in system voices, used only when Piper isn't installed."""
    if common.IS_MACOS and shutil.which("say"):
        aiff = out_path + ".aiff"
        ok = subprocess.run(["say", "-o", aiff, text]).returncode == 0
        if ok:
            os.replace(aiff, out_path)
        return ok
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return subprocess.run([exe, "-w", out_path, text]).returncode == 0
    return False


def player_command(path: str):
    if common.IS_MACOS:
        return ["afplay", path]
    for cmd in (["pw-play", path], ["paplay", path], ["aplay", "-q", path],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def play(path: str) -> None:
    global _player
    if common.IS_WINDOWS:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
        return
    cmd = player_command(path)
    if not cmd:
        raise RuntimeError("no audio player found (install pipewire, pulseaudio-utils or alsa-utils)")
    _player = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _player.wait()
    _player = None


def _on_term(*_):
    if _player and _player.poll() is None:
        _player.terminate()
    sys.exit(0)


def speaking(play_fn) -> int:
    """Run play_fn with state/speaking.pid set, so the listener stays deaf and barge-in can stop us."""
    if not common.IS_WINDOWS:
        signal.signal(signal.SIGTERM, _on_term)
    common.STATE_DIR.mkdir(parents=True, exist_ok=True)
    common.SPEAKING_FILE.write_text(str(os.getpid()))
    try:
        play_fn()
    finally:
        try:
            if common.speaking_pid() == os.getpid():
                common.SPEAKING_FILE.unlink()
        except OSError:
            pass
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Say text with the local Piper voice.")
    ap.add_argument("--out", help="write the WAV here instead of playing it")
    ap.add_argument("--voice", help="Piper .onnx voice (default: the installed one)")
    ap.add_argument("text", nargs="*")
    args = ap.parse_args(argv)
    text = " ".join(args.text).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    if not text:
        return 0

    if os.environ.get("NARRATE_TTS") == "chatterbox" and not (args.out or args.voice) and shutil.which("ffplay"):
        try:
            sock = chatterbox_connect()
        except Exception as e:
            common.log(f"speak: {e}; using Piper")
        else:
            with sock:
                return speaking(lambda: chatterbox_play(sock, text))

    text = re.sub(r"<[^>]+>", " ", TAG_RE.sub("", text)).strip()  # Piper / say: drop Chatterbox tags and SSML
    target = args.out
    tmp = None
    if not target:
        fd, tmp = tempfile.mkstemp(prefix="speak-", suffix=".wav")
        os.close(fd)
        target = tmp
    try:
        try:
            synthesize(text, target, args.voice)
        except (ImportError, FileNotFoundError) as e:
            if not fallback_synthesize(text, target):
                common.log(f"speak: {e}; no fallback voice either")
                return 1
        if args.out:
            return 0
        return speaking(lambda: play(target))
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
