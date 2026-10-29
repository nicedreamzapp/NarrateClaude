#!/usr/bin/env python3
"""End-to-end check of an installed voice loop, with no mic and no speakers.

Run with the venv python after install.sh / install.ps1:

    <venv python> tests/e2e_voice.py

1. Piper writes a few spoken sentences to WAV files (nothing is played).
2. The whisper.cpp listener runs them through the same VAD + whisper path
   the microphone uses, and must hear the right words.
3. A session runs a stub in place of `claude` inside the loop's own pty,
   with the listener fed from the WAV files; the stub must receive each
   sentence as a submitted line. Plus one line typed in with --send.
4. The session itself runs inside a real terminal (a pty on macOS/Linux,
   a ConPTY console on Windows) and keys typed into that terminal must
   reach the stub, so the keyboard passthrough is tested too.

CI runs this on macOS, Linux and Windows. It never touches a real claude.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VOICE = REPO / "dictation" / "voice"
PY = sys.executable

SENTENCES = [
    "Open the deploy logs and tell me why the build failed.",
    "Please run the whole test suite again.",
]


def words(s):
    return re.sub(r"[^a-z ]", "", s.lower()).split()


def close_enough(heard, said):
    h, s = set(words(heard)), words(said)
    return sum(w in h for w in s) >= len(s) - 1


def run(args, **kw):
    print("+", " ".join(str(a) for a in args), flush=True)
    return subprocess.run(args, capture_output=True, text=True, timeout=600, **kw)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="narrate-e2e-"))
    wavs = []
    # 1. Piper -> WAV
    for i, s in enumerate(SENTENCES):
        out = tmp / f"s{i}.wav"
        r = run([PY, str(VOICE / "speak.py"), "--out", str(out), s])
        assert r.returncode == 0, r.stderr
        with wave.open(str(out)) as w:
            secs = w.getnframes() / w.getframerate()
        assert secs > 1.0, f"{out} is only {secs:.2f}s"
        print(f"  piper wrote {out.name}: {secs:.1f}s", flush=True)
        wavs.append(str(out))

    # 2. WAV -> VAD -> whisper.cpp
    r = run([PY, str(VOICE / "stt.py"), "--check"])
    assert r.returncode == 0, r.stderr
    print("  " + r.stdout.strip())
    t0 = time.monotonic()
    r = run([PY, str(VOICE / "stt.py"), "--file"] + wavs)
    assert r.returncode == 0, r.stderr
    heard = [l for l in r.stdout.splitlines() if l.strip()]
    print(f"  heard in {time.monotonic() - t0:.1f}s: {heard}", flush=True)
    assert len(heard) == len(SENTENCES), heard
    for h, s in zip(heard, SENTENCES):
        assert close_enough(h, s), (h, s)

    # 3. Session: listener -> pty -> stub claude
    got = tmp / "got.txt"
    stub = tmp / "fakeclaude.py"
    stub.write_text(textwrap.dedent(f"""
        import sys
        print("fake claude ready", flush=True)
        for line in sys.stdin:
            line = line.replace("\\x1b", "").strip()
            if not line:
                continue
            with open({str(got)!r}, "a", encoding="utf-8") as f:
                f.write(line + "\\n")
            if line == "please quit the session now":
                break
    """))
    env = dict(os.environ, NARRATE_TEST_WAVS=os.pathsep.join(wavs), NARRATE_RELEVANCE="0",
               NARRATE_BARGE_IN="0")
    session = subprocess.Popen([PY, str(VOICE / "session.py"), "--", PY, str(stub)], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    state = REPO / "dictation" / "state" / "session.json"
    deadline = time.monotonic() + 240
    lines = []
    while time.monotonic() < deadline:
        lines = got.read_text(encoding="utf-8").splitlines() if got.exists() else []
        if len(lines) >= len(SENTENCES):
            break
        assert session.poll() is None, session.stdout.read()
        time.sleep(0.5)
    print(f"  stub received: {lines}", flush=True)
    assert len(lines) == len(SENTENCES), lines
    for h, s in zip(lines, SENTENCES):
        assert close_enough(h, s), (h, s)
    assert json.loads(state.read_text())["mode"] == "pty"
    r = run([PY, str(VOICE / "session.py"), "--send", "please quit the session now"])
    assert r.returncode == 0, r.stderr
    session.wait(timeout=60)
    assert got.read_text(encoding="utf-8").splitlines()[-1] == "please quit the session now"
    assert not state.exists(), "session.json should be removed on exit"
    keyboard_through_a_real_terminal(tmp)
    print("e2e voice loop: OK")


def keyboard_through_a_real_terminal(tmp):
    got = tmp / "keys.txt"
    stub = tmp / "keystub.py"
    stub.write_text(textwrap.dedent(f"""
        import sys
        print("key stub ready", flush=True)
        for line in sys.stdin:
            line = line.strip()
            if line:
                with open({str(got)!r}, "a", encoding="utf-8") as f:
                    f.write(line + "\\n")
            if line == "bye":
                break
    """))
    cmd = [PY, str(VOICE / "session.py"), "--no-listen", "--", PY, str(stub)]
    env = dict(os.environ, NARRATE_BARGE_IN="0", NARRATE_RELEVANCE="0")
    if os.name == "nt":
        from winpty import PtyProcess
        term = PtyProcess.spawn(cmd, env=env, dimensions=(30, 100))
        write = term.write
        read = lambda: term.read(4096)
        alive = term.isalive
    else:
        import pty
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(cmd[0], cmd, env)
        write = lambda s: os.write(fd, s.encode())
        read = lambda: os.read(fd, 4096)

        def alive():
            return os.waitpid(pid, os.WNOHANG) == (0, 0)
    import threading
    screen = []

    def drain():
        while True:
            try:
                data = read()
            except Exception:
                return
            if not data:
                return
            screen.append(data if isinstance(data, str) else data.decode("utf-8", "replace"))
    threading.Thread(target=drain, daemon=True).start()

    def wait_for(pred, secs=30):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if pred():
                return True
            time.sleep(0.2)
        return False
    assert wait_for(lambda: "key stub ready" in "".join(screen)), "".join(screen)[-500:]
    for ch in "typed on the keyboard":
        write(ch)
        time.sleep(0.01)
    write("\r")
    assert wait_for(lambda: got.exists() and "typed on the keyboard" in got.read_text(encoding="utf-8")), \
        "".join(screen)[-500:]
    write("bye\r")
    assert wait_for(lambda: not alive()), "session did not exit"
    print(f"  keyboard passthrough: {got.read_text(encoding='utf-8').splitlines()}", flush=True)


if __name__ == "__main__":
    main()
