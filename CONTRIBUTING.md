# Contributing

Thanks for taking a look. Voice loops behave differently on every Mac, mic and room, so a bug report
from your setup is useful even if you never send code.

## Reporting a problem

Open an [issue](https://github.com/nicedreamzapp/NarrateClaude/issues/new/choose). The things that
make it quick to fix:

- your Mac (chip) and macOS version
- the mic you use (built-in, headset, USB) and what `~/.local/bin/speak` runs (`say`, Pocket TTS,
  Piper or something else)
- whether you started it with `narrative-claude.sh` or `dictation start`
- what `dictation tail` showed: what it heard, and what got typed into Terminal
- whether the relevance judge was running (the MLX server on port 8190)

## Running it locally

```bash
git clone https://github.com/nicedreamzapp/NarrateClaude.git ~/NarrateClaude
cd ~/NarrateClaude
chmod +x dictation/bin/* narrative-claude.sh

# Start `claude` in Apple Terminal first, then:
./dictation/bin/dictation setup

# Or the one-click way
bash ~/NarrateClaude/narrative-claude.sh
```

The launcher expects the repo at `~/NarrateClaude`. Set up `~/.local/bin/speak` as the README
describes.

## Tests

The suite in `tests/` runs anywhere, Linux included. It needs no GPU, model weights, network or
macOS APIs. CI runs it on every push and pull request, and also compiles the Swift listener on macOS.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

If you change `dictation/src/Listen.swift` or `MicProbe.swift`, check they still build with
`swiftc -O` on a Mac, the same way the macOS job in `.github/workflows/ci.yml` does.

## Pull requests

Small and focused is easiest to review. Say which Mac and macOS version you tested on, and whether
you tried it live with a mic. Keep `relevance.py` working on Python 3.9, since that is the macOS
system Python. For big changes, open an issue first so we can talk it through.

Please follow the [code of conduct](CODE_OF_CONDUCT.md).
