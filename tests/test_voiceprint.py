"""Tests for the voiceprint stage: dictation/filter/filter.py and enroll.py.

Resemblyzer (and the torch model behind it) is replaced by a fake encoder
whose embeddings the test picks, so cosine scores are exact and no weights
are downloaded. Each script is copied into a temp dictation/ tree because
both resolve their state dir relative to their own file.
"""

import io

import numpy as np
import pytest

from conftest import load_module, make_dictation_tree


def unit(*xs):
    v = np.array(xs, dtype=float)
    return v / np.linalg.norm(v)


# --- filter.py ----------------------------------------------------------------


@pytest.fixture
def filt(tmp_path, monkeypatch, fake_resemblyzer):
    root = make_dictation_tree(tmp_path, "filter/filter.py")
    monkeypatch.delenv("MATCH_THRESHOLD", raising=False)
    mod = load_module(root / "filter" / "filter.py", "voice_filter_under_test")
    mod.state = root / "state"
    mod.encoder = fake_resemblyzer
    return mod


def enroll_vector(filt, vec):
    np.save(filt.state / "voiceprint.npy", vec)


def make_wav(tmp_path, name, encoder, embedding):
    p = tmp_path / name
    p.write_bytes(b"RIFF")
    encoder.embeddings[str(p)] = embedding
    return p


def run_filter(filt, monkeypatch, capsys, lines):
    monkeypatch.setattr(filt.sys, "stdin", io.StringIO("".join(l + "\n" for l in lines)))
    rc = filt.main()
    captured = capsys.readouterr()
    return rc, captured.out.splitlines(), captured.err


def test_default_threshold(filt):
    assert filt.THRESHOLD == 0.48


def test_threshold_env_override(tmp_path, monkeypatch, fake_resemblyzer):
    root = make_dictation_tree(tmp_path, "filter/filter.py")
    monkeypatch.setenv("MATCH_THRESHOLD", "0.9")
    mod = load_module(root / "filter" / "filter.py", "voice_filter_env")
    assert mod.THRESHOLD == 0.9


def test_missing_voiceprint_exits_1(filt, monkeypatch, capsys):
    rc, out, err = run_filter(filt, monkeypatch, capsys, ["hello there friend"])
    assert rc == 1
    assert out == []
    assert "voiceprint missing" in err and "enroll.py" in err


def test_scores_and_routes_each_line(filt, monkeypatch, capsys, tmp_path):
    me = unit(1, 0, 0)
    enroll_vector(filt, me)
    enc = filt.encoder
    match = make_wav(tmp_path, "match.wav", enc, unit(1, 0.2, 0))        # ~0.98
    stranger = make_wav(tmp_path, "stranger.wav", enc, unit(0, 1, 0))     # 0.0
    short = make_wav(tmp_path, "short.wav", enc, unit(0, 1, 0))

    rc, out, err = run_filter(filt, monkeypatch, capsys, [
        f"open the deploy logs\t{match}",
        f"what's for dinner tonight\t{stranger}",
        f"ok thanks\t{short}",
        "no audio was attached here",
        "",
    ])
    assert rc == 0
    assert out == [
        "open the deploy logs",
        "ok thanks",
        "no audio was attached here",
    ]
    assert "ready (threshold=0.48)" in err

    # Every wav is deleted once scored or bypassed.
    for wav in (match, stranger, short):
        assert not wav.exists()

    decisions = (filt.state / "filter.log").read_text().splitlines()
    assert decisions[0].startswith("PASS\t0.98") and decisions[0].endswith("open the deploy logs")
    assert decisions[1] == "DROP\t0.000\twhat's for dinner tonight"
    assert decisions[2] == "PASS_SHORT\tok thanks"
    assert decisions[3] == "PASS_NO_AUDIO\tno audio was attached here"
    assert (filt.state / "dropped.log").read_text() == "0.000\twhat's for dinner tonight\n"


def test_score_exactly_at_threshold_passes(filt, monkeypatch, capsys, tmp_path):
    enroll_vector(filt, unit(1, 0))
    t = filt.THRESHOLD
    edge = make_wav(tmp_path, "edge.wav", filt.encoder, np.array([t, np.sqrt(1 - t * t)]))
    _, out, _ = run_filter(filt, monkeypatch, capsys, [f"right on the line here\t{edge}"])
    assert out == ["right on the line here"]


def test_scoring_error_fails_open(filt, monkeypatch, capsys, tmp_path):
    enroll_vector(filt, unit(1, 0, 0))
    missing = tmp_path / "gone.wav"
    rc, out, _ = run_filter(filt, monkeypatch, capsys, [f"this audio vanished somehow\t{missing}"])
    assert rc == 0
    assert out == ["this audio vanished somehow"]
    log = (filt.state / "filter.log").read_text()
    assert log.startswith("ERR\t")


# --- enroll.py ----------------------------------------------------------------


@pytest.fixture
def enroll(tmp_path, monkeypatch, fake_resemblyzer):
    root = make_dictation_tree(tmp_path, "filter/enroll.py")
    mod = load_module(root / "filter" / "enroll.py", "enroll_under_test")
    mod.state = root / "state"
    mod.encoder = fake_resemblyzer
    return mod


def test_enroll_usage(enroll, monkeypatch, capsys):
    monkeypatch.setattr(enroll.sys, "argv", ["enroll.py"])
    assert enroll.main() == 2
    assert "usage:" in capsys.readouterr().err


def test_enroll_missing_sample(enroll, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(enroll.sys, "argv", ["enroll.py", str(tmp_path / "nope.wav")])
    assert enroll.main() == 1
    assert "sample not found" in capsys.readouterr().err
    assert not (enroll.state / "voiceprint.npy").exists()


def test_enroll_averages_and_normalizes(enroll, monkeypatch, tmp_path):
    a = make_wav(tmp_path, "a.wav", enroll.encoder, unit(1, 0, 0))
    b = make_wav(tmp_path, "b.wav", enroll.encoder, unit(0, 1, 0))
    monkeypatch.setattr(enroll.sys, "argv", ["enroll.py", str(a), str(b)])
    assert enroll.main() == 0
    vp = np.load(enroll.state / "voiceprint.npy")
    np.testing.assert_allclose(vp, unit(1, 1, 0))
    assert np.linalg.norm(vp) == pytest.approx(1.0)


def test_enroll_creates_state_dir(enroll, monkeypatch, tmp_path):
    enroll.state.rmdir()
    a = make_wav(tmp_path, "a.wav", enroll.encoder, unit(3, 4))
    monkeypatch.setattr(enroll.sys, "argv", ["enroll.py", str(a)])
    assert enroll.main() == 0
    np.testing.assert_allclose(np.load(enroll.state / "voiceprint.npy"), [0.6, 0.8])
