#!/usr/bin/env python3
"""relevance.py — second-stage filter that runs AFTER the voiceprint filter.

Even when an utterance passes voiceprint (so we're confident it's Matt
speaking), we still want to drop it if it clearly wasn't aimed at THIS
assistant session — e.g. Matt is talking to another agent session in the
same room, his dog, his daughter, or someone on the phone. Those
utterances are his real voice, so voiceprint correctly passes them; this
filter is the "was that for me?" check on top.

Three layers, cheapest first:

  1. Wake-phrase gate ("claude tune out" / "claude tune in") — a hard,
     stateful mute. While tuned out, EVERYTHING is dropped until the
     tune-in phrase. State survives respawns via relevance_state.json.
  2. Regex drops — obvious pet-talk / phone-call patterns (kept from v1).
  3. LLM judge — a local Llama-3.2-3B (MLX, port 8190) sees this
     session's recent accepted lines plus the new line and answers
     PASS/DROP. ~100 ms. Few-shot prompt, biased toward PASS: a wrongly
     dropped command hurts more than a wrongly passed one. On ANY judge
     failure (server down, timeout) the line passes — fail open.

The judge server is auto-started if port 8190 is closed (model:
mlx-community/Llama-3.2-3B-Instruct-4bit, already in the HF cache).

Stdin: one utterance per line. Stdout: utterances that pass. Decisions
logged to ../state/relevance.log; drops also to ../state/dropped.log.
"""

import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
DROP_LOG = STATE_DIR / "dropped.log"
DEC_LOG = STATE_DIR / "relevance.log"
STATE_FILE = STATE_DIR / "relevance_state.json"
# What this session's assistant last said aloud (written by speak-v2).
LAST_TTS_FILE = STATE_DIR.parent.parent / "dictation-v2" / "state" / "last_tts.txt"

import os
JUDGE_URL = "http://127.0.0.1:8190/v1/chat/completions"
JUDGE_PORT = 8190
JUDGE_MODEL = os.environ.get("RELEVANCE_MODEL", "mlx-community/Llama-3.2-3B-Instruct-4bit")
JUDGE_PYTHON = Path.home() / ".local/mlx-server/bin/python"
JUDGE_TIMEOUT_S = 2.5
CONTEXT_LINES = 6  # rolling window of accepted lines shown to the judge

# Lines the pipeline itself generates — never judge these, always pass.
PASS_PREFIXES = ("[INTERRUPTED]",)

# Wake-phrase gate. "claude" optional so SFSpeech mishearing the name
# doesn't strand Matt in the wrong state.
TUNE_OUT_RE = re.compile(r"\b(claude[,. ]*)?tune[ -]?out\b", re.IGNORECASE)
TUNE_IN_RE = re.compile(r"\b(claude[,. ]*)?tune[ -]?in\b", re.IGNORECASE)

# Patterns that signal Matt is clearly talking to a human or an animal,
# not the assistant. Each is matched case-insensitively against the whole
# utterance. Keep this list tight — false drops hurt more than misses.
HUMAN_OR_ANIMAL_PATTERNS = [
    # Pet talk — unambiguous; everything subtler is the LLM judge's call now.
    # (The old phone-call/gossip regexes are gone: the "yeah/yes I was..."
    # pattern ate Matt's direct answers to the assistant's own questions.)
    r"\bgood (boy|girl|dog)\b",
    r"\bno (no )+(no\b|down\b|off\b)",
    r"\bi'?ll call you back\b",
]

_compiled = [re.compile(p, re.IGNORECASE) for p in HUMAN_OR_ANIMAL_PATTERNS]

JUDGE_SYSTEM = """You are a microphone router for a hands-free voice assistant called Claude.
The user (Matt) sits at a desk with an always-on mic. He often has OTHER conversations
in the same room: other assistant sessions working on different projects, family,
phone calls. Every spoken line reaches you; you decide if it was meant for THIS session.

You are given THIS session's recent conversation lines, then a new line.

Rules:
- PASS if the new line plausibly continues THIS session's conversation, gives
  feedback about the assistant's behavior (its voice, speed, hearing, interruptions),
  or is a direct command or question that fits this session's work.
- PASS if the new line reads as an ANSWER to what THIS assistant just said aloud
  (when that is shown) — even a bare yes/no/"not you".
- PASS greetings, "stop", "wait", "never mind", and meta-comments about the assistant.
- DROP only when the line clearly belongs to a DIFFERENT topic than this session's
  recent lines — a different project, prices/orders for physical goods, other people.
- Conversations are sticky: if Matt's PREVIOUS line just seconds ago was for a
  different conversation, an ambiguous follow-up (one that mentions no topic from
  THIS session) most likely continues that other conversation — DROP it. The
  word "you" or "your" alone does not mean THIS assistant; he says "you" to the
  other sessions too.
- When uncertain and the previous line was for THIS session (or there is no
  previous line), PASS. A wrongly dropped command is worse than a wrongly passed one.

Answer with exactly one word: PASS or DROP."""

JUDGE_FEWSHOT = [
    ("THIS session recent lines:\n- the deploy script keeps failing on the second step\n- ok rerun it and show me the error\n\nNew line: did you fix the timeout yet",
     "PASS"),
    ("THIS session recent lines:\n- the deploy script keeps failing on the second step\n- ok rerun it and show me the error\n\nNew line: honey can you grab the door",
     "DROP"),
    ("THIS session recent lines:\n- lets work on the website header\n\nNew line: make the logo bigger",
     "PASS"),
    ("THIS session recent lines:\n- lets work on the website header\n- make the logo bigger\n\nPrevious line (4s ago, judged: for a DIFFERENT conversation): what do the shipping labels cost\n\nNew line: no your second estimate was wrong",
     "DROP"),
]


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"tuned_out": False, "recent": []}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


_autostart_attempted = False


def ensure_judge_server() -> None:
    """Spawn the MLX judge server if nothing is listening. Once per run."""
    global _autostart_attempted
    if _autostart_attempted or port_open(JUDGE_PORT):
        return
    _autostart_attempted = True
    if not JUDGE_PYTHON.exists():
        return
    try:
        log = open("/tmp/relevance-judge.log", "a")
        subprocess.Popen(
            [str(JUDGE_PYTHON), "-m", "mlx_lm", "server",
             "--model", JUDGE_MODEL, "--port", str(JUDGE_PORT),
             "--host", "127.0.0.1"],
            stdout=log, stderr=log, start_new_session=True,
        )
    except Exception:
        pass


def llm_judge(text: str, recent: list, last) -> tuple:
    """Return (verdict, reason). verdict in {PASS, DROP, ERROR}."""
    ctx = "\n".join(f"- {l}" for l in recent) if recent else "(no lines yet — new session)"
    # Conversational stickiness: tell the judge what Matt's previous line was
    # judged as, and how long ago — an ambiguous follow-up seconds after an
    # other-conversation line is most likely more of that conversation.
    prev = ""
    if last and last.get("text"):
        age = int(time.time() - last.get("ts", 0))
        # 45s, not 120: a stale DROP verdict biasing the judge for two full
        # minutes is how one wrong drop cascaded into eating whole runs of
        # Matt's speech (2026-06-11).
        if age <= 45:
            who = "for THIS session" if last.get("verdict") == "PASS" else "for a DIFFERENT conversation"
            prev = f"\n\nPrevious line ({age}s ago, judged: {who}): {last['text']}"
    # What THIS assistant most recently said aloud — lets the judge recognize
    # Matt's line as a direct answer to it.
    try:
        tts_age = time.time() - LAST_TTS_FILE.stat().st_mtime
        if tts_age <= 180:
            said = LAST_TTS_FILE.read_text().strip()[:300]
            if said:
                prev += f"\n\nTHIS assistant said aloud {int(tts_age)}s ago: {said}"
    except OSError:
        pass
    msgs = [{"role": "system", "content": JUDGE_SYSTEM}]
    for q, a in JUDGE_FEWSHOT:
        msgs.append({"role": "user", "content": q + "\n\nPASS or DROP?"})
        msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content":
                 f"THIS session recent lines:\n{ctx}{prev}\n\nNew line: {text}\n\nPASS or DROP?"})
    body = json.dumps({"model": JUDGE_MODEL, "messages": msgs,
                       "max_tokens": 4, "temperature": 0}).encode()
    req = urllib.request.Request(JUDGE_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=JUDGE_TIMEOUT_S) as r:
            out = json.load(r)["choices"][0]["message"]["content"].strip().upper()
        return ("PASS" if "PASS" in out else "DROP"), "llm"
    except Exception as e:
        ensure_judge_server()
        return "ERROR", f"llm_error:{type(e).__name__}"


def decide(text: str, state: dict) -> tuple[bool, str]:
    """Return (keep, reason). Mutates state (tune gate, recent buffer)."""
    text = text.strip()
    if not text:
        return False, "empty"

    # Pipeline-internal markers always pass, never enter the context buffer.
    if text.startswith(PASS_PREFIXES):
        return True, "marker"

    # Layer 1 — wake-phrase gate. The toggle lines themselves are not
    # injected (they're commands to the filter, not messages to Claude).
    if TUNE_OUT_RE.search(text):
        state["tuned_out"] = True
        return False, "tune_out"
    if TUNE_IN_RE.search(text):
        state["tuned_out"] = False
        return False, "tune_in"
    if state.get("tuned_out"):
        return False, "tuned_out_gate"

    # Saying the assistant's name is an absolute override — Matt can pull
    # this session into ANY topic at any time ("claude, look at my email"),
    # so topic drift is never outlawed, only unaddressed cross-talk.
    if re.search(r"\bclaude\b", text, re.IGNORECASE):
        return True, "named_assistant"

    # Feedback about the assistant's own behavior is ALWAYS for this session.
    # The system prompt tells the judge this, but the 3B model misjudges it
    # in practice (2026-06-11: it ate "You're still cutting me off ... which
    # is bothering me"). Hard-pass it so Matt can never be silenced while
    # complaining that he's being silenced.
    if re.search(
        r"\b(cut(ting|s)? (your\s?self|me) off|interrupt(ing|ed|s)?|"
        r"not (listening|hearing)|can'?t hear|(don'?t|not) hear(ing)? me|"
        r"hear everything|getting through|tune[ -]?(in|out)|microphone|"
        r"listener|control control)\b",
        text, re.IGNORECASE,
    ):
        return True, "assistant_feedback"

    # Long monologues are Matt dictating plans/instructions — the single
    # most expensive thing to lose. The judge's false-drop rate on these
    # outweighs the cross-talk risk (2026-06-11: it ate a 30-word models
    # question and a multi-step email-board plan), so length is a pass.
    if len(text.split()) >= 18:
        return True, "long_utterance_pass"

    # Layer 2 — cheap regex drops.
    for pat in _compiled:
        m = pat.search(text)
        if m:
            return False, f"matched:{m.re.pattern[:40]}"

    # Layer 3 — LLM judge with rolling session context. Fail open.
    # With little/no context the judge has nothing to anchor "THIS session"
    # to and over-drops legitimate first lines — let those through; the
    # judge earns trust as the buffer fills.
    recent = state.get("recent", [])
    if len(recent) < 2:
        state["last"] = {"text": text, "verdict": "PASS", "ts": time.time()}
        return True, "cold_start_pass"
    verdict, reason = llm_judge(text, recent, state.get("last"))
    effective = "DROP" if verdict == "DROP" else "PASS"
    state["last"] = {"text": text, "verdict": effective, "ts": time.time()}
    if verdict == "DROP":
        return False, reason
    return True, reason if verdict == "PASS" else f"{reason}_fail_open"


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    drop_log = open(DROP_LOG, "a", buffering=1)
    dec_log = open(DEC_LOG, "a", buffering=1)
    state = load_state()
    ensure_judge_server()
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line:
            continue
        keep, reason = decide(line, state)
        if keep:
            if reason != "marker":
                recent = state.setdefault("recent", [])
                recent.append(line)
                del recent[:-CONTEXT_LINES]
            dec_log.write(f"PASS\t{reason}\t{line}\n")
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        else:
            dec_log.write(f"DROP\t{reason}\t{line}\n")
            drop_log.write(f"rel\t{reason}\t{line}\n")
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
