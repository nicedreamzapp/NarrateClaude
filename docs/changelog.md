---
title: Changelog
description: NarrateClaude change history built from the git log, from the first public release in April 2026 to the latest README fixes.
---

# Changelog

There are no tagged releases. This list is built from the git history of `main`, newest first. Dates are commit dates.

## 2026-10-09

- README notes that the listener uses the `en-US` recognizer and where the relevance judge looks for MLX (`~/.local/mlx-server/bin/python`). ([#4](https://github.com/nicedreamzapp/NarrateClaude/pull/4))

## 2026-09-27

- README gets a plain one-paragraph summary, a "What I built" table, a Known limits section, and fixes for claims that disagreed with the code. ([#3](https://github.com/nicedreamzapp/NarrateClaude/pull/3))

## 2026-09-19

- Credits name Kyutai for Pocket TTS. README adds other voice tools worth knowing (whisper.cpp, RealtimeSTT, mlx-audio).

## 2026-09-07

- New: `dictation/bin/speak-on-stop`, a Claude Code Stop hook that reads the last reply aloud.
- New: `dictation/filter/relevance.py` (tune out / tune in, pet-talk regexes, local LLM judge), `filter.py` and `enroll.py` (voiceprint).
- `dispatch` runs the listener through the voiceprint and relevance filters, and forces `arch -arm64` for the voiceprint filter.
- `inject` drops noise markers and fragments under 3 words, kills TTS before typing, scopes Escape and Return to the bound window, and sends a bare newline when that window is not focused.
- Added the 2.0 research logs: `BARGE_IN_ATTEMPTS.md`, `EXPERIMENT_PLAN.md`, `RESEARCH_2026_05_21.md`.

## 2026-08-06

- Added `CREDITS.md`.

## 2026-04-30

- README section on Ohm, a separate browser-based version (not in this repo). Removed a public URL from it the same day.

## 2026-04-23

- README links the NiceDreamzApps Discord.

## 2026-04-20

- Listener detects silent recognizer wedges (audio arriving, no events for 20 s) and the preventive recycle drops from 600 s to 300 s.
- `inject` presses Return after typing so the line submits.
- GitHub Sponsors enabled.

## 2026-04-18

- README stars badge.

## 2026-04-11

- First public release: `Listen.swift`, `MicProbe.swift`, `dictation`, `dispatch`, `inject`, `narrative-claude.sh`, `CLAUDE.md`, MIT license.
- `dispatch` never pastes into a dead Terminal window (shutdown flag instead of signals).
- `narrative-claude.sh` made executable.
- README rewritten, plus the three-repo stack table.
