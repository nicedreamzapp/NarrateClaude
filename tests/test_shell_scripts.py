"""Tests for the bash scripts in dictation/bin/.

These run the real scripts with bash, against a temp copy of the dictation/
tree. They only exercise paths that stop before any AppleScript, pkill of
audio players, or swiftc call, so they are safe on Linux CI and on a dev Mac.
The one full-pipeline test that would reach osascript is Linux-only.
"""

import json
import os
import shutil
import subprocess
import time

import pytest

from conftest import IS_MACOS, REPO, make_dictation_tree


def run(cmd, env=None, input=None, timeout=30):
    full_env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    full_env.update(env or {})
    return subprocess.run(cmd, env=full_env, input=input, capture_output=True,
                          text=True, timeout=timeout)


@pytest.mark.parametrize("script", [
    "dictation/bin/dictation",
    "dictation/bin/dispatch",
    "dictation/bin/inject",
    "narrative-claude.sh",
])
def test_bash_syntax(script):
    r = run(["bash", "-n", str(REPO / script)])
    assert r.returncode == 0, r.stderr


# --- inject: noise gate -----------------------------------------------------
#
# target.json is written WITHOUT a window_id. Any text that gets past the
# noise gate then fails with "missing window_id" (exit 1) before inject
# kills audio or calls osascript. Text the gate drops exits 0 silently.
# That makes "exit 1 + missing window_id" a safe signal for "would inject".


@pytest.fixture
def inject(tmp_path):
    root = make_dictation_tree(tmp_path, "bin/inject")
    (root / "state" / "target.json").write_text(json.dumps({"app": "Terminal"}))
    return root / "bin" / "inject"


def gate_dropped(r):
    return r.returncode == 0 and r.stdout == "" and r.stderr == ""


def gate_passed(r):
    return r.returncode == 1 and "missing window_id" in r.stderr


def test_inject_requires_binding(tmp_path):
    root = make_dictation_tree(tmp_path, "bin/inject")
    r = run(["bash", str(root / "bin" / "inject"), "hello there friend"])
    assert r.returncode == 1
    assert "not bound to a window" in r.stderr


@pytest.mark.parametrize("text", [
    "(keyboard clicking)",
    "(footsteps)",
    "[BLANK_AUDIO]",
    "",
    "okay",
    "yes please",
])
def test_inject_gate_drops_noise_and_fragments(inject, text):
    assert gate_dropped(run(["bash", str(inject), text]))


@pytest.mark.parametrize("text", [
    "why?",
    "open the file",
    "please run all the tests again",
])
def test_inject_gate_passes_questions_and_sentences(inject, text):
    assert gate_passed(run(["bash", str(inject), text]))


def test_inject_force_bypasses_gate(inject):
    r = run(["bash", str(inject), "okay"], env={"INJECT_FORCE": "1"})
    assert gate_passed(r)


def test_inject_reads_stdin_and_joins_args(inject):
    assert gate_passed(run(["bash", str(inject)], input="run the tests now\n"))
    assert gate_passed(run(["bash", str(inject), "run", "the", "tests"]))
    assert gate_dropped(run(["bash", str(inject)], input="okay\n"))


# --- dictation control CLI ----------------------------------------------------


@pytest.fixture
def dictation(tmp_path):
    root = make_dictation_tree(tmp_path, "bin/dictation")
    shutil.rmtree(root / "state")  # the script must create it itself
    return root


def dict_run(root, *args, env=None):
    return run(["bash", str(root / "bin" / "dictation"), *args], env=env)


def test_status_is_default_and_creates_state_dir(dictation):
    r = dict_run(dictation)
    assert r.returncode == 0
    assert (dictation / "state").is_dir()
    assert "Dictation: OFF" in r.stdout
    assert "Bound:     (none" in r.stdout
    assert "Listener:  not compiled" in r.stdout


def test_status_shows_binding_and_compiled_listener(dictation):
    (dictation / "state" / "target.json").parent.mkdir(exist_ok=True)
    (dictation / "state" / "target.json").write_text('{ "app": "Terminal", "window_id": 42 }\n')
    listen = dictation / "bin" / "listen"
    listen.write_text("#!/bin/sh\n")
    listen.chmod(0o755)
    r = dict_run(dictation, "status")
    assert '"window_id": 42' in r.stdout
    assert "Listener:  compiled" in r.stdout


def test_stale_pid_file_reads_as_off(dictation):
    (dictation / "state").mkdir()
    # A pid that cannot be alive.
    (dictation / "state" / "listener.pid").write_text("999999999\n")
    assert "Dictation: OFF" in dict_run(dictation, "status").stdout


def test_live_pid_reads_as_on(dictation):
    (dictation / "state").mkdir()
    (dictation / "state" / "listener.pid").write_text(f"{os.getpid()}\n")
    assert f"Dictation: ON (pid {os.getpid()})" in dict_run(dictation, "status").stdout


def test_unknown_subcommand(dictation):
    r = dict_run(dictation, "bogus")
    assert r.returncode == 2
    assert "usage: dictation" in r.stderr


@pytest.mark.parametrize("launcher", ["", "Terminal", "narrativeclaude.app"])
def test_start_refuses_unauthorized_launcher(dictation, launcher):
    env = {"NARRATE_DICTATION_LAUNCHER": launcher} if launcher else {}
    r = dict_run(dictation, "start", env=env)
    assert r.returncode == 3
    assert "refused" in r.stderr
    assert not (dictation / "state" / "listener.pid").exists()


@pytest.mark.parametrize("launcher", ["NarrativeClaude.app", "Narrative Gemma.command"])
def test_start_accepts_authorized_launcher_then_checks_listener(dictation, launcher):
    r = dict_run(dictation, "start", env={"NARRATE_DICTATION_LAUNCHER": launcher})
    assert r.returncode == 1
    assert "listener not compiled" in r.stderr
    log = (dictation / "state" / "dictation.log").read_text()
    assert f"authorized launcher = {launcher}" in log


def test_start_requires_binding(dictation):
    listen = dictation / "bin" / "listen"
    listen.write_text("#!/bin/sh\n")
    listen.chmod(0o755)
    r = dict_run(dictation, "start", env={"NARRATE_DICTATION_LAUNCHER": "NarrativeClaude.app"})
    assert r.returncode == 1
    assert "no bound window" in r.stderr


def test_stop_when_not_running_cleans_pid(dictation):
    (dictation / "state").mkdir()
    (dictation / "state" / "listener.pid").write_text("999999999\n")
    r = dict_run(dictation, "stop")
    assert r.returncode == 0
    assert "Not running." in r.stdout
    assert not (dictation / "state" / "listener.pid").exists()


def test_uninstall_removes_state_but_keeps_binary(dictation):
    state = dictation / "state"
    state.mkdir()
    files = ["target.json", "dictation.log", "dictation.log.stderr", "dictation.log.inject"]
    for name in files:
        (state / name).write_text("x")
    listen = dictation / "bin" / "listen"
    listen.write_text("#!/bin/sh\n")
    r = dict_run(dictation, "uninstall")
    assert r.returncode == 0
    for name in files:
        assert not (state / name).exists()
    assert listen.exists()


# --- dispatch -----------------------------------------------------------------


@pytest.fixture
def dispatch_tree(tmp_path):
    return make_dictation_tree(tmp_path, "bin/dispatch", "filter/relevance.py")


def test_dispatch_requires_listener(dispatch_tree):
    r = run(["bash", str(dispatch_tree / "bin" / "dispatch")])
    assert r.returncode == 1
    assert "listener not compiled" in r.stderr


def test_dispatch_requires_binding(dispatch_tree):
    listen = dispatch_tree / "bin" / "listen"
    listen.write_text("#!/bin/sh\n")
    listen.chmod(0o755)
    r = run(["bash", str(dispatch_tree / "bin" / "dispatch")])
    assert r.returncode == 1
    assert "no target window bound" in r.stderr


def write_exe(path, body):
    path.write_text(body)
    path.chmod(0o755)


@pytest.mark.skipif(IS_MACOS, reason=(
    "dispatch's window watchdog calls /usr/bin/osascript against the real "
    "Terminal.app; on Linux osascript is absent so the watchdog shuts the "
    "pipeline down, which is what this test relies on"))
@pytest.mark.skipif(not os.path.exists("/usr/bin/python3"),
                    reason="dispatch runs relevance.py with /usr/bin/python3")
def test_dispatch_pipeline_end_to_end(dispatch_tree, tmp_path):
    """Fake listener -> passthrough voice filter -> real relevance.py -> fake
    inject. No voiceprint is enrolled, so dispatch must fall back to `cat`
    for the voiceprint stage. The judge is never reached: the first two
    lines are cold-start passes and the rest are decided by rules."""
    root = dispatch_tree
    (root / "state" / "target.json").write_text('{ "app": "Terminal", "window_id": 7 }')
    injected = tmp_path / "injected.txt"
    write_exe(root / "bin" / "listen", "\n".join([
        "#!/bin/bash",
        "echo 'open the deploy logs'",
        "echo 'claude tune out'",
        "echo 'this one is muted'",
        "echo 'claude tune in'",
        "echo 'good boy'",
        "echo 'claude rerun the failing step'",
        "",
    ]))
    write_exe(root / "bin" / "inject",
              f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{injected}"\n')

    # HOME points at an empty dir so relevance.py cannot find (and auto-start)
    # a real MLX judge server.
    home = tmp_path / "home"
    home.mkdir()
    start = time.monotonic()
    r = run(["bash", str(root / "bin" / "dispatch")], env={"HOME": str(home)}, timeout=60)
    elapsed = time.monotonic() - start

    assert r.returncode == 0, r.stderr
    assert injected.read_text().splitlines() == [
        "open the deploy logs",
        "claude rerun the failing step",
    ]
    log = (root / "state" / "dictation.log").read_text()
    assert "dispatch: starting listener (attempt 1)" in log
    assert "watchdog: bound window 7 is gone, requesting shutdown" in log
    assert "shutdown requested by watchdog, exiting cleanly" in log
    assert not (root / "state" / ".shutdown").exists()
    assert elapsed < 30
