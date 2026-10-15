"""Tests for dictation/filter/relevance.py, the "was that for me?" filter.

The local MLX judge server is never started: urlopen is replaced with a
fake, and the auto-start path is pointed at a python that does not exist.
"""

import io
import json
import os
import time

import pytest

from conftest import DICTATION, load_module

RELEVANCE = DICTATION / "filter" / "relevance.py"


@pytest.fixture
def rel(tmp_path, monkeypatch):
    """A fresh copy of the module per test, with all state redirected."""
    mod = load_module(RELEVANCE, "relevance_under_test")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(mod, "STATE_DIR", state)
    monkeypatch.setattr(mod, "DROP_LOG", state / "dropped.log")
    monkeypatch.setattr(mod, "DEC_LOG", state / "relevance.log")
    monkeypatch.setattr(mod, "STATE_FILE", state / "relevance_state.json")
    monkeypatch.setattr(mod, "LAST_TTS_FILE", tmp_path / "last_tts.txt")
    monkeypatch.setattr(mod, "JUDGE_PYTHON", tmp_path / "no-such-python")
    # Port 8190 is never open in tests; don't even try to connect.
    monkeypatch.setattr(mod, "port_open", lambda port: False)
    return mod


class FakeJudge:
    """Records requests to the judge and answers with a canned reply."""

    def __init__(self, reply="PASS", exc=None):
        self.reply = reply
        self.exc = exc
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        if self.exc is not None:
            raise self.exc
        body = json.dumps({"choices": [{"message": {"content": self.reply}}]})
        return io.BytesIO(body.encode())

    def last_messages(self):
        req, _ = self.requests[-1]
        return json.loads(req.data)["messages"]


@pytest.fixture
def judge(rel, monkeypatch):
    fake = FakeJudge()
    monkeypatch.setattr(rel.urllib.request, "urlopen", fake)
    return fake


def warm_state(**extra):
    """State with enough context lines that the LLM judge is consulted."""
    state = {"tuned_out": False, "recent": ["fix the deploy script", "rerun it"]}
    state.update(extra)
    return state


# --- decide(): ordering of the layers -------------------------------------


def test_empty_and_whitespace_dropped(rel):
    assert rel.decide("", {}) == (False, "empty")
    assert rel.decide("   \t ", {}) == (False, "empty")


def test_pipeline_marker_always_passes_even_when_tuned_out(rel):
    state = {"tuned_out": True}
    assert rel.decide("[INTERRUPTED] stop talking", state) == (True, "marker")


@pytest.mark.parametrize("phrase", [
    "claude tune out",
    "Claude, tune out",
    "ok tune-out for a bit",
    "TUNEOUT",
])
def test_tune_out_sets_gate_and_is_not_injected(rel, phrase):
    state = {"tuned_out": False}
    assert rel.decide(phrase, state) == (False, "tune_out")
    assert state["tuned_out"] is True


@pytest.mark.parametrize("phrase", ["claude tune in", "Claude. Tune in", "tune-in"])
def test_tune_in_clears_gate_and_is_not_injected(rel, phrase):
    state = {"tuned_out": True}
    assert rel.decide(phrase, state) == (False, "tune_in")
    assert state["tuned_out"] is False


def test_tuned_out_gate_drops_everything_including_named_assistant(rel, judge):
    state = {"tuned_out": True, "recent": []}
    assert rel.decide("claude open my email", state) == (False, "tuned_out_gate")
    long = " ".join(["word"] * 30)
    assert rel.decide(long, state) == (False, "tuned_out_gate")
    assert judge.requests == []


def test_tune_words_inside_other_words_do_not_toggle(rel):
    # \b anchors: "fortune in" must not count as "tune in".
    state = {"tuned_out": True}
    assert rel.decide("that was a fortune in cash", state) == (False, "tuned_out_gate")
    assert state["tuned_out"] is True


def test_naming_claude_is_an_absolute_pass(rel, judge):
    state = warm_state()
    assert rel.decide("Claude, look at my email", state) == (True, "named_assistant")
    assert judge.requests == []


def test_named_assistant_beats_pet_talk_regex(rel):
    assert rel.decide("claude, good boy", warm_state()) == (True, "named_assistant")


@pytest.mark.parametrize("text", [
    "you're still cutting me off",
    "you keep interrupting",
    "are you not listening",
    "I can't hear you",
    "you don't hear me at all",
    "is the microphone working",
])
def test_feedback_about_the_assistant_hard_passes(rel, judge, text):
    assert rel.decide(text, warm_state()) == (True, "assistant_feedback")
    assert judge.requests == []


def test_long_utterance_passes_without_judge(rel, judge):
    text = " ".join(["plan"] * 18)
    assert rel.decide(text, warm_state()) == (True, "long_utterance_pass")
    assert judge.requests == []


def test_seventeen_words_is_not_long(rel, judge):
    judge.reply = "DROP"
    text = " ".join(["plan"] * 17)
    assert rel.decide(text, warm_state()) == (False, "llm")


@pytest.mark.parametrize("text", [
    "good boy",
    "who's a good girl",
    "no no no",
    "no no down",
    "I'll call you back",
    "ill call you back",
])
def test_pet_and_phone_talk_dropped_by_regex(rel, judge, text):
    keep, reason = rel.decide(text, warm_state())
    assert keep is False
    assert reason.startswith("matched:")
    assert judge.requests == []


def test_single_no_is_not_pet_talk(rel, judge):
    # "no" on its own is a valid answer to the assistant; it must reach the judge.
    keep, reason = rel.decide("no", warm_state())
    assert (keep, reason) == (True, "llm")


@pytest.mark.parametrize("recent", [[], ["only one line"]])
def test_cold_start_passes_without_judge(rel, judge, recent):
    state = {"tuned_out": False, "recent": list(recent)}
    assert rel.decide("make the logo bigger", state) == (True, "cold_start_pass")
    assert judge.requests == []
    assert state["last"]["verdict"] == "PASS"
    assert state["last"]["text"] == "make the logo bigger"


def test_missing_recent_key_counts_as_cold_start(rel, judge):
    assert rel.decide("hello there", {}) == (True, "cold_start_pass")


# --- decide() + llm_judge ---------------------------------------------------


def test_judge_pass(rel, judge):
    state = warm_state()
    assert rel.decide("did you fix the timeout", state) == (True, "llm")
    assert state["last"]["verdict"] == "PASS"


def test_judge_drop_is_recorded_as_last_verdict(rel, judge):
    judge.reply = " drop\n"
    state = warm_state()
    assert rel.decide("grab the door", state) == (False, "llm")
    assert state["last"]["verdict"] == "DROP"
    assert state["last"]["text"] == "grab the door"


def test_judge_failure_fails_open(rel, monkeypatch):
    fake = FakeJudge(exc=TimeoutError("judge slow"))
    monkeypatch.setattr(rel.urllib.request, "urlopen", fake)
    state = warm_state()
    keep, reason = rel.decide("did you fix the timeout", state)
    assert keep is True
    assert reason == "llm_error:TimeoutError_fail_open"
    assert state["last"]["verdict"] == "PASS"


def test_judge_malformed_json_fails_open(rel, monkeypatch):
    monkeypatch.setattr(rel.urllib.request, "urlopen",
                        lambda req, timeout=None: io.BytesIO(b"not json"))
    keep, reason = rel.decide("did you fix the timeout", warm_state())
    assert keep is True
    assert reason.endswith("_fail_open")


def test_judge_failure_tries_autostart_once(rel, monkeypatch, tmp_path):
    fake = FakeJudge(exc=ConnectionRefusedError())
    monkeypatch.setattr(rel.urllib.request, "urlopen", fake)
    fake_python = tmp_path / "python"
    fake_python.write_text("")
    monkeypatch.setattr(rel, "JUDGE_PYTHON", fake_python)
    spawned = []
    monkeypatch.setattr(rel.subprocess, "Popen",
                        lambda *a, **kw: spawned.append(a[0]))
    rel.decide("first ambiguous line", warm_state())
    rel.decide("second ambiguous line", warm_state())
    assert len(spawned) == 1
    cmd = spawned[0]
    assert cmd[:4] == [str(fake_python), "-m", "mlx_lm", "server"]
    assert "--port" in cmd and str(rel.JUDGE_PORT) in cmd
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"


def test_autostart_skipped_when_port_already_open(rel, monkeypatch, tmp_path):
    fake_python = tmp_path / "python"
    fake_python.write_text("")
    monkeypatch.setattr(rel, "JUDGE_PYTHON", fake_python)
    monkeypatch.setattr(rel, "port_open", lambda port: True)
    spawned = []
    monkeypatch.setattr(rel.subprocess, "Popen", lambda *a, **kw: spawned.append(a))
    rel.ensure_judge_server()
    assert spawned == []


def test_autostart_skipped_when_mlx_python_missing(rel, monkeypatch):
    spawned = []
    monkeypatch.setattr(rel.subprocess, "Popen", lambda *a, **kw: spawned.append(a))
    rel.ensure_judge_server()
    assert spawned == []


def test_judge_request_shape(rel, judge):
    rel.llm_judge("new words", ["line a", "line b"], None)
    req, timeout = judge.requests[-1]
    assert req.full_url == rel.JUDGE_URL
    assert timeout == rel.JUDGE_TIMEOUT_S
    body = json.loads(req.data)
    assert body["temperature"] == 0
    assert body["max_tokens"] == 4
    msgs = body["messages"]
    assert msgs[0] == {"role": "system", "content": rel.JUDGE_SYSTEM}
    # system + (user, assistant) per few-shot example + the real question
    assert len(msgs) == 1 + 2 * len(rel.JUDGE_FEWSHOT) + 1
    final = msgs[-1]["content"]
    assert "- line a\n- line b" in final
    assert "New line: new words" in final
    assert final.endswith("PASS or DROP?")


def test_judge_prompt_without_context(rel, judge):
    rel.llm_judge("hello", [], None)
    assert "(no lines yet" in judge.last_messages()[-1]["content"]


def test_judge_prompt_includes_recent_previous_verdict(rel, judge):
    last = {"text": "what do labels cost", "verdict": "DROP", "ts": time.time() - 10}
    rel.llm_judge("no your estimate was wrong", ["a", "b"], last)
    final = judge.last_messages()[-1]["content"]
    assert "judged: for a DIFFERENT conversation): what do labels cost" in final


def test_judge_prompt_marks_previous_pass_as_this_session(rel, judge):
    last = {"text": "rerun it", "verdict": "PASS", "ts": time.time() - 3}
    rel.llm_judge("and the logs", ["a", "b"], last)
    assert "judged: for THIS session): rerun it" in judge.last_messages()[-1]["content"]


def test_judge_prompt_ignores_previous_verdict_older_than_45s(rel, judge):
    last = {"text": "what do labels cost", "verdict": "DROP", "ts": time.time() - 46}
    rel.llm_judge("no your estimate was wrong", ["a", "b"], last)
    assert "Previous line" not in judge.last_messages()[-1]["content"]


def test_judge_prompt_includes_fresh_tts_and_truncates(rel, judge):
    rel.LAST_TTS_FILE.write_text("  " + "x" * 400 + "  ")
    rel.llm_judge("yes", ["a", "b"], None)
    final = judge.last_messages()[-1]["content"]
    assert "THIS assistant said aloud" in final
    assert "x" * 300 in final and "x" * 301 not in final


def test_judge_prompt_ignores_stale_tts(rel, judge):
    rel.LAST_TTS_FILE.write_text("old words")
    old = time.time() - 181
    os.utime(rel.LAST_TTS_FILE, (old, old))
    rel.llm_judge("yes", ["a", "b"], None)
    assert "said aloud" not in judge.last_messages()[-1]["content"]


# --- state persistence ------------------------------------------------------


def test_load_state_defaults_when_missing(rel):
    assert rel.load_state() == {"tuned_out": False, "recent": []}


def test_load_state_defaults_when_corrupt(rel):
    rel.STATE_FILE.write_text("{not json")
    assert rel.load_state() == {"tuned_out": False, "recent": []}


def test_state_round_trip(rel):
    state = {"tuned_out": True, "recent": ["a", "b"]}
    rel.save_state(state)
    assert rel.load_state() == state


def test_save_state_swallows_write_errors(rel, tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "STATE_FILE", tmp_path / "missing-dir" / "s.json")
    rel.save_state({"tuned_out": False})  # must not raise


# --- main(): the stdin -> stdout filter ------------------------------------


def run_main(rel, monkeypatch, capsys, lines):
    monkeypatch.setattr(rel.sys, "stdin", io.StringIO("".join(l + "\n" for l in lines)))
    assert rel.main() == 0
    return capsys.readouterr().out.splitlines()


def test_main_end_to_end(rel, judge, monkeypatch, capsys):
    judge.reply = "DROP"
    out = run_main(rel, monkeypatch, capsys, [
        "open the deploy script",          # cold start pass
        "",                                # blank, skipped
        "[INTERRUPTED]",                   # marker, passes, not in context
        "show me the error",               # cold start pass (1 line of context)
        "grab the door",                   # judge says DROP
        "claude tune out",                 # gate on, not forwarded
        "claude are you there",            # gated
        "claude tune in",                  # gate off, not forwarded
        "good boy",                        # regex drop
        "claude what failed",              # named pass
    ])
    assert out == [
        "open the deploy script",
        "[INTERRUPTED]",
        "show me the error",
        "claude what failed",
    ]
    state = json.loads(rel.STATE_FILE.read_text())
    assert state["tuned_out"] is False
    assert state["recent"] == ["open the deploy script", "show me the error",
                               "claude what failed"]

    decisions = rel.DEC_LOG.read_text().splitlines()
    assert len(decisions) == 9
    assert decisions[0] == "PASS\tcold_start_pass\topen the deploy script"
    assert decisions[1] == "PASS\tmarker\t[INTERRUPTED]"
    assert "DROP\tllm\tgrab the door" in decisions
    assert "DROP\ttuned_out_gate\tclaude are you there" in decisions

    drops = rel.DROP_LOG.read_text().splitlines()
    assert drops[0] == "rel\tllm\tgrab the door"
    assert all(d.startswith("rel\t") for d in drops)
    assert len(drops) == 5


def test_main_caps_context_window(rel, judge, monkeypatch, capsys):
    lines = [f"claude step {i}" for i in range(10)]
    run_main(rel, monkeypatch, capsys, lines)
    state = json.loads(rel.STATE_FILE.read_text())
    assert state["recent"] == lines[-rel.CONTEXT_LINES:]


def test_main_resumes_tuned_out_state_after_restart(rel, judge, monkeypatch, capsys):
    rel.save_state({"tuned_out": True, "recent": []})
    out = run_main(rel, monkeypatch, capsys, ["claude are you there"])
    assert out == []
