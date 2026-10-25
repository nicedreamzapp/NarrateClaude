# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Report them privately through GitHub: go to the **Security** tab of this repo and click **Report a vulnerability** ([direct link](https://github.com/nicedreamzapp/NarrateClaude/security/advisories/new)). Only the maintainer sees the report.

Helpful details: what you found, how to reproduce it, which version or commit, your Mac and macOS version, and what `~/.local/bin/speak` runs.

I aim to reply within 3 days and to ship a fix or a clear plan within 30 days, depending on severity. You will be credited in the advisory unless you ask not to be.

## Supported versions

Fixes go into the latest release on `main`. Please update before reporting if you are on an older version.

## What matters most here

The parts where a mistake could hurt someone:

- `dictation/bin/inject`, which types whatever the mic hears into a Terminal window running Claude Code, through AppleScript
- the microphone listener in `dictation/src/Listen.swift` and the launcher gate in `dictation/bin/dictation` that stops a stray call from turning the mic on
- the filters in `dictation/filter/` that decide which speech gets through, including the local LLM judge in `relevance.py` that starts a server on port 8190
- `dictation/bin/speak-on-stop`, a Claude Code Stop hook that passes reply text to the `speak` script
- voiceprint enrollment in `dictation/filter/enroll.py`, which stores a speaker embedding on disk
