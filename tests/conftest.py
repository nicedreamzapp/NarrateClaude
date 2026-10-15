"""Shared helpers for the NarrateClaude test suite.

Everything here runs on a plain Linux box: no microphone, no GPU, no model
download, no network, no Terminal.app. The scripts under test resolve their
state directory relative to their own file, so tests that exercise a whole
script copy it into a temp tree first and never touch the repo's real
dictation/state/.
"""

import importlib.machinery
import importlib.util
import shutil
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DICTATION = REPO / "dictation"

IS_MACOS = sys.platform == "darwin"


def load_module(path: Path, name: str):
    """Import a Python file by path, including ones with no .py suffix."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def make_dictation_tree(tmp_path: Path, *relpaths: str) -> Path:
    """Copy the given files (relative to dictation/) into tmp_path/dictation.

    Returns the new dictation/ dir. Executable bits are preserved so bash
    scripts can be run directly.
    """
    root = tmp_path / "dictation"
    for rel in relpaths:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DICTATION / rel, dst)
    (root / "state").mkdir(parents=True, exist_ok=True)
    return root


class FakeVoiceEncoder:
    """Stand-in for resemblyzer.VoiceEncoder.

    embed_utterance returns whatever vector the test queued for that wav
    path, so tests choose the similarity score without any model weights.
    """

    embeddings: dict = {}

    def __init__(self, verbose=True):
        self.verbose = verbose

    def embed_utterance(self, wav):
        return FakeVoiceEncoder.embeddings[str(wav)]


def fake_preprocess_wav(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    # The fake encoder keys on the path, so just hand the path through.
    return str(path)


@pytest.fixture
def fake_resemblyzer(monkeypatch):
    """Install a fake `resemblyzer` module so filter.py / enroll.py import
    without torch or the pretrained voice encoder weights."""
    mod = types.ModuleType("resemblyzer")
    mod.VoiceEncoder = FakeVoiceEncoder
    mod.preprocess_wav = fake_preprocess_wav
    monkeypatch.setitem(sys.modules, "resemblyzer", mod)
    FakeVoiceEncoder.embeddings = {}
    return FakeVoiceEncoder
