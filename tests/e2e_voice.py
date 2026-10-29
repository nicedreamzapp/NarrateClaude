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
    print("e2e voice loop: OK")


if __name__ == "__main__":
    main()
