#!/usr/bin/env python3
"""session.py: run `claude` in a terminal this loop owns, and talk to it.

  session.py [--no-listen] [-- command args...]   (command defaults to claude)
  session.py --send "text"                         type text into a running session

The command runs inside a pseudo-terminal (pty on macOS/Linux, ConPTY via
pywinpty on Windows). Your keyboard and screen pass straight through, so it
works in any terminal app. Every utterance the listener hears goes through
the same filters as before (relevance.py, the noise gate), then gets typed
into the pty followed by Enter. No GUI scripting, no focus tricks.

When the command exits, the microphone and whisper-server go with it.

Env:
  NARRATE_BARGE_IN   1 (default) = a new request stops the voice and sends
                     Escape first, so Claude stops what it was doing
  NARRATE_RELEVANCE  1 (default) = run filter/relevance.py on each utterance
"""

import json
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ESC, ENTER = b"\x1b", b"\r"


def _log_line(text: str) -> None:
    try:
        common.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(common.STATE_DIR / "dictation.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
    except OSError:
        pass


class Typist:
    """Types queued lines into the pty, one at a time."""

    def __init__(self, write, barge_in=None):
        self.write = write
        self.barge_in = os.environ.get("NARRATE_BARGE_IN", "1") == "1" if barge_in is None else barge_in
        self.q = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, text: str, force=False):
        text = common.gate(text, force=force)
        if text:
            self.q.put(text)

    def _run(self):
        while True:
            text = self.q.get()
            _log_line(text)
            if self.barge_in:
                common.stop_speaking()
                self.write(ESC)
                time.sleep(0.12)
            # Text and Enter go in separate writes: sent together, the TUI
            # can read the burst as a paste and keep the Enter as a newline.
            self.write(text.replace("\r", " ").replace("\n", " ").encode("utf-8"))
            time.sleep(0.15)
            self.write(ENTER)
            time.sleep(0.1)


class InjectServer:
    """127.0.0.1 socket so other tools (and --send) can type into the session."""

    def __init__(self, typist):
        self.typist = typist
        self.token = secrets.token_hex(16)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(5)
                    data = b""
                    while not data.endswith(b"\n") and len(data) < 65536:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("token") != self.token:
                        conn.sendall(b"denied\n")
                        continue
                    self.typist.send(str(msg.get("text", "")), force=bool(msg.get("force")))
                    conn.sendall(b"ok\n")
                except Exception:
                    pass


def send(text: str, force=False) -> int:
    try:
        st = json.loads(common.SESSION_FILE.read_text())
    except Exception:
        common.log("session: no running session")
        return 1
    try:
        with socket.create_connection(("127.0.0.1", st["port"]), timeout=5) as c:
            c.sendall((json.dumps({"token": st["token"], "text": text, "force": force}) + "\n").encode())
            reply = c.recv(64).decode().strip()
    except OSError as e:
        common.log(f"session: {e}")
        return 1
    return 0 if reply == "ok" else 1


class Relevance:
    """filter/relevance.py as a co-process: lines in, kept lines out."""

    def __init__(self, on_line):
        script = common.DICT_DIR / "filter" / "relevance.py"
        self.proc = None
        if script.exists() and os.environ.get("NARRATE_RELEVANCE", "1") == "1":
            self.proc = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         text=True, bufsize=1)
            threading.Thread(target=self._read, args=(on_line,), daemon=True).start()
        self.on_line = on_line

    def _read(self, on_line):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if line:
                on_line(line)

    def feed(self, text, _wav=""):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(text.replace("\n", " ") + "\n")
                self.proc.stdin.flush()
                return
            except OSError:
                pass
        self.on_line(text)

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def start_listener(typist):
    """Start mic -> whisper -> relevance -> typist in background threads."""
    import stt
    rel = Relevance(typist.send)
    listener = stt.Listener(rel.feed)

    # Test hook: feed WAV files instead of the microphone (no mic, no audio).
    wavs = [w for w in os.environ.get("NARRATE_TEST_WAVS", "").split(os.pathsep) if w]

    def run():
        try:
            listener.start()
            if wavs:
                for w in wavs:
                    listener.run_file(w)
                return
            listener.run_mic()
        except Exception as e:
            common.log(f"\r\nnarrate: voice off ({e})\r")
    threading.Thread(target=run, daemon=True).start()
    return listener, rel


def resolve_command(cmd):
    exe = shutil.which(cmd[0])
    if not exe:
        raise FileNotFoundError(f"{cmd[0]} not found on PATH")
    if common.IS_WINDOWS and exe.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe] + cmd[1:]
    return [exe] + cmd[1:]


def write_state(server):
    common.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = common.SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mode": "pty", "pid": os.getpid(), "port": server.port,
                               "token": server.token}))
    if not common.IS_WINDOWS:
        os.chmod(tmp, 0o600)
    os.replace(tmp, common.SESSION_FILE)


def clear_state():
    try:
        if json.loads(common.SESSION_FILE.read_text()).get("pid") == os.getpid():
            common.SESSION_FILE.unlink()
    except Exception:
        pass


# --- POSIX ---------------------------------------------------------------------------


def run_posix(cmd, listen: bool) -> int:
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios
    import tty

    stdin_fd, stdout_fd = sys.stdin.fileno(), sys.stdout.fileno()
    interactive = os.isatty(stdin_fd)
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.execv(cmd[0], cmd)
        finally:
            os._exit(127)

    def resize(*_):
        if not os.isatty(stdout_fd):
            return
        try:
            size = fcntl.ioctl(stdout_fd, termios.TIOCGWINSZ, b"\0" * 8)
            fcntl.ioctl(master, termios.TIOCSWINSZ, size)
        except OSError:
            pass
    resize()
    signal.signal(signal.SIGWINCH, resize)

    lock = threading.Lock()

    def write(data: bytes):
        with lock:
            try:
                os.write(master, data)
            except OSError:
                pass

    typist = Typist(write)
    server = InjectServer(typist)
    write_state(server)
    listener = rel = None
    if listen:
        listener, rel = start_listener(typist)

    old = termios.tcgetattr(stdin_fd) if interactive else None
    if interactive:
        tty.setraw(stdin_fd)
    status = 0
    try:
        fds = [master, stdin_fd]
        while True:
            try:
                r, _, _ = select.select(fds, [], [], 0.5)
            except InterruptedError:
                continue
            if master in r:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                if not data:
                    break
                os.write(stdout_fd, data)
            if stdin_fd in r:
                data = os.read(stdin_fd, 65536)
                if not data:
                    fds.remove(stdin_fd)
                else:
                    write(data)
        _, st = os.waitpid(pid, 0)
        status = os.waitstatus_to_exitcode(st) if hasattr(os, "waitstatus_to_exitcode") else (st >> 8)
    finally:
        if old is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old)
        if listener:
            listener.stop()
        if rel:
            rel.close()
        clear_state()
    return status


# --- Windows -------------------------------------------------------------------------


def run_windows(cmd, listen: bool) -> int:
    import ctypes
    from winpty import PtyProcess  # pywinpty

    cols, rows = shutil.get_terminal_size((120, 30))
    proc = PtyProcess.spawn(cmd, dimensions=(rows, cols))
    lock = threading.Lock()

    def write(data: bytes):
        with lock:
            try:
                proc.write(data.decode("utf-8", "replace"))
            except Exception:
                pass

    typist = Typist(write)
    server = InjectServer(typist)
    write_state(server)
    listener = rel = None
    if listen:
        listener, rel = start_listener(typist)

    k32 = ctypes.windll.kernel32
    h_in, h_out = k32.GetStdHandle(-10), k32.GetStdHandle(-11)
    old_in, old_out = ctypes.c_uint(), ctypes.c_uint()
    console = bool(k32.GetConsoleMode(h_in, ctypes.byref(old_in)))
    if console:
        # Raw VT input: keys arrive as the same escape sequences a Unix tty sends.
        ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
        k32.SetConsoleMode(h_in, ENABLE_VIRTUAL_TERMINAL_INPUT)
    if k32.GetConsoleMode(h_out, ctypes.byref(old_out)):
        k32.SetConsoleMode(h_out, old_out.value | 0x0004 | 0x0001)  # VT processing
    out = sys.stdout

    def pump_out():
        while True:
            try:
                data = proc.read(65536)
            except EOFError:
                return
            except Exception:
                if not proc.isalive():
                    return
                continue
            if data:
                out.write(data)
                out.flush()

    def pump_in():
        if console:
            buf = ctypes.create_unicode_buffer(4096)
            n = ctypes.c_uint()
            while proc.isalive():
                if not k32.ReadConsoleW(h_in, buf, 4096, ctypes.byref(n), None):
                    return
                if n.value:
                    write(buf[:n.value].encode("utf-8"))
        else:
            for line in sys.stdin.buffer:
                write(line)

    t_out = threading.Thread(target=pump_out, daemon=True)
    t_out.start()
    threading.Thread(target=pump_in, daemon=True).start()
    try:
        while proc.isalive():
            time.sleep(0.2)
        t_out.join(timeout=2)
    finally:
        if console:
            k32.SetConsoleMode(h_in, old_in.value)
        if listener:
            listener.stop()
        if rel:
            rel.close()
        clear_state()
    return proc.exitstatus or 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--send"]:
        force = "--force" in argv
        text = " ".join(a for a in argv[1:] if a != "--force")
        return send(text, force=force)
    listen = True
    if "--no-listen" in argv:
        argv.remove("--no-listen")
        listen = False
    if argv[:1] == ["--"]:
        argv = argv[1:]
    cmd = resolve_command(argv or ["claude"])
    return run_windows(cmd, listen) if common.IS_WINDOWS else run_posix(cmd, listen)


if __name__ == "__main__":
    sys.exit(main())
