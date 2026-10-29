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


def synthesize(text: str, out_path: str, voice_path=None) -> None:
    """Text -> WAV with Piper. Raises if Piper or the voice is missing."""
    from piper import PiperVoice  # installed into the venv by install.sh

    voice_path = Path(voice_path) if voice_path else common.piper_voice()
    if not voice_path.exists():
        raise FileNotFoundError(f"Piper voice not found: {voice_path}")
    voice = PiperVoice.load(str(voice_path))
    with wave.open(out_path, "wb") as wf:
        voice.synthesize_wav(text, wf)


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
        if not common.IS_WINDOWS:
            signal.signal(signal.SIGTERM, _on_term)
        common.STATE_DIR.mkdir(parents=True, exist_ok=True)
        common.SPEAKING_FILE.write_text(str(os.getpid()))
        try:
            play(target)
        finally:
            try:
                if common.speaking_pid() == os.getpid():
                    common.SPEAKING_FILE.unlink()
            except OSError:
                pass
        return 0
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
