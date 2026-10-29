"""Tests for dictation/bin/speak-on-stop, the Claude Code Stop hook.

The real `speak` binary is never run: SPEAK points at a temp path and
subprocess.Popen is replaced with a recorder.
"""

import io
import json

import pytest

from conftest import DICTATION, load_module

HOOK = DICTATION / "bin" / "speak-on-stop"


@pytest.fixture
def hook(tmp_path, monkeypatch):
    mod = load_module(HOOK, "speak_on_stop_under_test")
    flag = tmp_path / "narration.on"
    flag.write_text("")
    speak = tmp_path / "speak"
    speak.write_text("#!/bin/sh\n")
    monkeypatch.setattr(mod, "FLAG", str(flag))
    monkeypatch.setattr(mod, "SPEAK", str(speak))
    spoken = []
    monkeypatch.setattr(mod.subprocess, "Popen",
                        lambda cmd, **kw: spoken.append(cmd))
    mod.spoken = spoken
    return mod


def write_transcript(path, events):
    path.write_text("\n".join(
        e if isinstance(e, str) else json.dumps(e) for e in events) + "\n")
    return str(path)


def assistant(*blocks, wrapped=True):
    content = [b if isinstance(b, dict) else {"type": "text", "text": b} for b in blocks]
    if wrapped:
        return {"type": "assistant", "message": {"role": "assistant", "content": content}}
    return {"role": "assistant", "content": content}


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


# --- _extract_assistant_text -----------------------------------------------


def test_extract_missing_file(hook, tmp_path):
    assert hook._extract_assistant_text(str(tmp_path / "nope.jsonl")) == ""


def test_extract_latest_assistant_text(hook, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        user("hi"),
        assistant("first reply"),
        user("again"),
        assistant("second reply"),
    ])
    assert hook._extract_assistant_text(t) == "second reply"


def test_extract_joins_text_blocks_and_skips_tool_use(hook, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        assistant("Part one.",
                  {"type": "tool_use", "name": "Bash", "input": {}},
                  "Part two."),
    ])
    assert hook._extract_assistant_text(t) == "Part one.\nPart two."


def test_extract_skips_pure_tool_call_entries(hook, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        assistant("Here is the answer."),
        assistant({"type": "tool_use", "name": "Read", "input": {}}),
    ])
    assert hook._extract_assistant_text(t) == "Here is the answer."


def test_extract_tolerates_blank_and_corrupt_lines(hook, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        assistant("good line"),
        "",
        "{truncated json",
    ])
    assert hook._extract_assistant_text(t) == "good line"


def test_extract_unwrapped_shape_and_string_content(hook, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        assistant("list form", wrapped=False),
        {"role": "assistant", "content": "  plain string form  "},
    ])
    assert hook._extract_assistant_text(t) == "plain string form"


def test_extract_none_found(hook, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [user("only user")])
    assert hook._extract_assistant_text(t) == ""


# --- _scrub_for_tts ---------------------------------------------------------


@pytest.mark.parametrize("raw, spoken", [
    ("Run this:\n```bash\nls -la\n```\nthen check.",
     "Run this: [code block on screen] then check."),
    ("Use `git status` now", "Use git status now"),
    ("This is **important** and *subtle*", "This is important and subtle"),
    ("- one\n* two\n+ three", "one two three"),
    ("## Heading\nBody", "Heading Body"),
    ("See https://example.com/a?b=c for more", "See link for more"),
    ("Edited /Users/someone/project/file.py today", "Edited a file today"),
    ("either/or stays", "either/or stays"),
    ("  lots   of\n\n whitespace ", "lots of whitespace"),
])
def test_scrub(hook, raw, spoken):
    assert hook._scrub_for_tts(raw) == spoken


# --- main() -----------------------------------------------------------------


def run_hook(hook, monkeypatch, payload):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(stdin))
    return hook.main()


def test_main_speaks_scrubbed_reply(hook, monkeypatch, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [assistant("Done. **All** tests pass.")])
    assert run_hook(hook, monkeypatch, {"transcript_path": t}) == 0
    assert hook.spoken == [[hook.SPEAK, "Done. All tests pass."]]


def test_main_accepts_camelcase_key(hook, monkeypatch, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [assistant("ok then")])
    run_hook(hook, monkeypatch, {"transcriptPath": t})
    assert hook.spoken == [[hook.SPEAK, "ok then"]]


def test_main_silent_when_flag_off(hook, monkeypatch, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [assistant("hello")])
    monkeypatch.setattr(hook, "FLAG", str(tmp_path / "absent"))
    assert run_hook(hook, monkeypatch, {"transcript_path": t}) == 0
    assert hook.spoken == []


def test_main_silent_when_speak_missing(hook, monkeypatch, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [assistant("hello")])
    monkeypatch.setattr(hook, "SPEAK", str(tmp_path / "no-speak"))
    monkeypatch.setattr(hook, "BUILTIN_DATA", str(tmp_path / "no-data"))
    assert run_hook(hook, monkeypatch, {"transcript_path": t}) == 0
    assert hook.spoken == []


def test_main_falls_back_to_the_builtin_voice(hook, monkeypatch, tmp_path):
    """No speak of your own, but the Piper voice is installed: use it."""
    t = write_transcript(tmp_path / "t.jsonl", [assistant("hello there")])
    monkeypatch.setattr(hook, "SPEAK", str(tmp_path / "no-speak"))
    (tmp_path / "data" / "venv").mkdir(parents=True)
    monkeypatch.setattr(hook, "BUILTIN_DATA", str(tmp_path / "data"))
    assert run_hook(hook, monkeypatch, {"transcript_path": t}) == 0
    assert hook.spoken == [[hook.BUILTIN_SPEAK, "hello there"]]


@pytest.mark.parametrize("payload", ["not json", {}, {"transcript_path": ""}])
def test_main_silent_on_bad_payload(hook, monkeypatch, payload):
    assert run_hook(hook, monkeypatch, payload) == 0
    assert hook.spoken == []


def test_main_silent_when_reply_scrubs_to_nothing(hook, monkeypatch, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [assistant("## ")])
    assert run_hook(hook, monkeypatch, {"transcript_path": t}) == 0
    assert hook.spoken == []


def test_main_truncates_long_replies_on_a_word_boundary(hook, monkeypatch, tmp_path):
    words = " ".join(f"word{i}" for i in range(400))
    t = write_transcript(tmp_path / "t.jsonl", [assistant(words)])
    run_hook(hook, monkeypatch, {"transcript_path": t})
    (cmd,) = hook.spoken
    text = cmd[1]
    assert text.endswith("… and there's more on screen.")
    body = text[: -len("… and there's more on screen.")]
    assert len(body) <= hook.MAX_LEN
    assert words.startswith(body + " ")


def test_main_survives_popen_failure(hook, monkeypatch, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [assistant("hello")])

    def boom(*a, **kw):
        raise OSError("exec format error")

    monkeypatch.setattr(hook.subprocess, "Popen", boom)
    assert run_hook(hook, monkeypatch, {"transcript_path": t}) == 0
