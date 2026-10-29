"""Shared paths and helpers for the open-source voice loop.

Everything runs locally: whisper.cpp for speech to text, Piper for the
default voice. Nothing here needs a network connection after install.

Paths (all overridable by env):
  NARRATE_DATA            where install.sh puts whisper.cpp, models and the venv
                          (~/.local/share/narrateclaude, %LOCALAPPDATA%\\narrateclaude)
  NARRATE_WHISPER_SERVER  path to the whisper-server binary
  NARRATE_WHISPER_MODEL   a model name (large-v3-turbo, small.en, base.en, ...)
                          or a path to a ggml .bin file
  NARRATE_VAD_MODEL       path to the Silero VAD ggml model ("" turns it off)
  NARRATE_PIPER_VOICE     a Piper voice name or a path to its .onnx file
"""

import os
import re
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

VOICE_DIR = Path(__file__).resolve().parent
DICT_DIR = VOICE_DIR.parent
STATE_DIR = DICT_DIR / "state"
SPEAKING_FILE = STATE_DIR / "speaking.pid"
SESSION_FILE = STATE_DIR / "session.json"

# Full-precision (f16) ggml models only, best first. The first one that fits
# the machine's memory is the default; see pick_model().
MODELS = [
    # name, minimum total RAM in GiB
    ("large-v3-turbo", 8),
    ("small.en", 4),
    ("base.en", 0),
]
VAD_MODEL_FILE = "ggml-silero-v6.2.0.bin"
DEFAULT_PIPER_VOICE = "en_US-lessac-high"


def data_dir() -> Path:
    env = os.environ.get("NARRATE_DATA")
    if env:
        return Path(env)
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "narrateclaude"
    return Path.home() / ".local" / "share" / "narrateclaude"


def models_dir() -> Path:
    return data_dir() / "models"


def total_ram_gib() -> float:
    """Total physical memory in GiB, or 0 if it can't be read."""
    try:
        if IS_MACOS:
            out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5).stdout
            return int(out.strip()) / 2**30
        if IS_WINDOWS:
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except Exception:
        return 0.0


def model_for_ram(ram_gib: float) -> str:
    for name, need in MODELS:
        if ram_gib >= need:
            return name
    return MODELS[-1][0]


def model_path(name: str) -> Path:
    return models_dir() / f"ggml-{name}.bin"


def pick_model() -> Path:
    """The model the listener loads.

    NARRATE_WHISPER_MODEL wins (a name or a path). Otherwise the best model
    that fits this machine's memory; if that one isn't downloaded, the best
    one that is.
    """
    env = os.environ.get("NARRATE_WHISPER_MODEL", "").strip()
    if env:
        p = Path(env).expanduser()
        return p if (p.suffix == ".bin" or p.exists()) else model_path(env)
    want = model_for_ram(total_ram_gib())
    if model_path(want).exists():
        return model_path(want)
    names = [n for n, _ in MODELS]
    for name in names[names.index(want):] + names[:names.index(want)]:
        if model_path(name).exists():
            return model_path(name)
    return model_path(want)


def vad_model() -> "Path | None":
    env = os.environ.get("NARRATE_VAD_MODEL")
    if env is not None:
        return Path(env).expanduser() if env.strip() else None
    p = models_dir() / VAD_MODEL_FILE
    return p if p.exists() else None


def whisper_server_bin() -> Path:
    env = os.environ.get("NARRATE_WHISPER_SERVER")
    if env:
        return Path(env).expanduser()
    exe = "whisper-server.exe" if IS_WINDOWS else "whisper-server"
    d = data_dir()
    for cand in (d / "whisper.cpp" / "build" / "bin" / exe,
                 d / "whisper" / exe,
                 d / "whisper" / "Release" / exe):
        if cand.exists():
            return cand
    return d / "whisper.cpp" / "build" / "bin" / exe


def piper_voice() -> Path:
    env = os.environ.get("NARRATE_PIPER_VOICE", "").strip() or DEFAULT_PIPER_VOICE
    p = Path(env).expanduser()
    if p.suffix == ".onnx":
        return p
    return models_dir() / "piper" / f"{env}.onnx"


# --- noise gate (same rules as bin/inject) ----------------------------------

_MARKER_RE = re.compile(r"^\s*[\(\[].*[\)\]]\s*$")


def gate(text: str, force: bool = False) -> "str | None":
    """Return the text to send, or None to drop it.

    Drops pure noise markers ("(keyboard clicking)", "[BLANK_AUDIO]") and
    fragments under three words, unless the fragment ends in "?".
    """
    text = (text or "").strip()
    if not text:
        return None
    if force:
        return text
    if _MARKER_RE.match(text):
        return None
    if len(text.split()) < 3 and not text.endswith("?"):
        return None
    return text


# --- "is the computer talking right now?" -----------------------------------

# Players a user's own speak script may use. While one of these runs, the
# listener stops listening so the assistant never hears itself.
PLAYERS_POSIX = ["afplay", "say", "aplay", "paplay", "pw-play", "pw-cat", "ffplay", "mpv", "play"]


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=5).stdout
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def speaking_pid() -> int:
    try:
        return int(SPEAKING_FILE.read_text().strip() or 0)
    except Exception:
        return 0


def player_running(names=None) -> bool:
    if IS_WINDOWS:
        return False
    env = os.environ.get("NARRATE_MUTE_PROCS")
    names = names or ([n for n in env.split(",") if n] if env is not None else PLAYERS_POSIX)
    for name in names:
        try:
            if subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=2).returncode == 0:
                return True
        except Exception:
            return False
    return False


def is_speaking() -> bool:
    return pid_alive(speaking_pid()) or player_running()


def stop_speaking() -> None:
    """Barge-in: silence the voice when a new request comes in."""
    pid = speaking_pid()
    if pid_alive(pid):
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=5)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    if IS_MACOS:
        # Legacy speak scripts play through afplay; the old injector did this too.
        for name in ("afplay", "say"):
            subprocess.run(["pkill", "-x", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)


def log(msg: str) -> None:
    sys.stderr.write(msg.rstrip("\n") + "\n")
    sys.stderr.flush()
