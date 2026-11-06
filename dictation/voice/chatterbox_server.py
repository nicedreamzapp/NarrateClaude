#!/usr/bin/env python3
"""chatterbox_server.py: keeps Chatterbox Turbo loaded so `speak` doesn't reload it every line.

Runs in the explain-as-podcast venv (chatterbox-mlx). speak.py starts it on first use when
NARRATE_TTS=chatterbox. Protocol on the unix socket: the client sends one line of text; the server
streams back raw float32 mono PCM at 24 kHz as it is generated, then closes. If the client hangs up
(barge-in), generation stops. Text can carry Chatterbox tags like [laugh], [chuckle], [sigh].

A line with SSML tags in it is a podcast script, in explain-as-podcast's SSML (its scripts/ssml.py does
the parsing): <break time="500ms"/>, <prosody rate pitch volume>, <voice name="s2"> (a file in its
voices/ folder, or a path to a .wav), sampling attributes like temperature / seed, <sub>, <say-as>,
<audio src>, <p>. Plain text streams as before; a <prosody> span is generated whole and then
time-stretched / pitch-shifted, so it starts later.

Env (read at server start; restart the server to change them):
  NARRATE_CB_QUANT_BITS   8 = 8-bit weights (~15% faster per explain-as-podcast; listen first)
  NARRATE_CB_NANO         1 = the smaller nano model (~2x faster, starts in ~0.25 s)
  NARRATE_CB_FIRST_CHUNK  speech tokens in the first streamed piece (default 15; lower = sooner)
  NARRATE_CB_CHUNK        speech tokens in the second piece; later ones double (default 24; the
                          library's 50 left a ~0.6 s gap after a short first piece)
  NARRATE_CB_WATERMARK    0 = skip the Perth watermark (default on)
  NARRATE_CB_IDLE         seconds without a request before the server exits and frees the model
                          (default 1800); the next speak starts it again
  NARRATE_CB_TEMPERATURE  delivery variety (default 0.8)
  NARRATE_CB_SEED         fixed seed so a line always sounds the same (default: random)
"""
import os
import re
import socketserver
import sys
from pathlib import Path

import glob
import librosa
import numpy as np
import torch
from chatterbox.tts_turbo_mlx import ChatterboxTurboMLX

from common import expand, has_shorthand  # the {.4} / {fast:..} shorthand (this script's folder)

SOCK = sys.argv[1]
VOICE = os.path.expanduser(sys.argv[2])
VOICE_DIR = Path(VOICE).parent

# The podcast plugin's SSML parser (stdlib only). Newest installed copy; without it, "<" lines are spoken as text.
_ssml = sorted(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/explain-as-podcast/*/scripts/ssml.py")),
               key=os.path.getmtime)
if _ssml:
    sys.path.insert(0, os.path.dirname(_ssml[-1]))
    import ssml
else:
    ssml = None

OPTS = {"first_chunk_tokens": int(os.environ.get("NARRATE_CB_FIRST_CHUNK", "15")),
        "chunk_tokens": int(os.environ.get("NARRATE_CB_CHUNK", "24")),
        "watermark": os.environ.get("NARRATE_CB_WATERMARK", "1") != "0",
        "temperature": float(os.environ.get("NARRATE_CB_TEMPERATURE", "0.8"))}
if os.environ.get("NARRATE_CB_SEED"):
    OPTS["seed"] = int(os.environ["NARRATE_CB_SEED"])

# The 19 paralinguistic tags in Chatterbox Turbo's tokenizer (as explain-as-podcast's ssml.py);
# any other [tag], like a typo'd [laughs], would be read aloud, so it is dropped.
TAGS = {"laugh", "chuckle", "sigh", "gasp", "groan", "clear throat", "cough", "sniff", "shush", "crying",
        "happy", "surprised", "sarcastic", "angry", "fear", "whispering", "dramatic", "narration", "advertisement"}


def clean_tags(text: str) -> str:
    def fix(m):
        tag = m.group(1).strip().lower()
        return f"[{tag}]" if tag in TAGS else ""
    return " ".join(re.sub(r"\[([^\]]*)\]", fix, text).split())


_voices = {}


def load_voice(wav: str):
    """-> the voice's conditioning, cached for the server's life (see _embed)."""
    if wav not in _voices:
        _embed(wav)
        _voices[wav] = (model._t3_cond_emb, model._ref_dict)  # same internals render.py swaps
    model._t3_cond_emb, model._ref_dict = _voices[wav]


def _embed(wav: str) -> None:
    """Embed the voice clip once into <name>.conds.pt in the voices folder (explain-as-podcast's cache, same
    layout, so the two share it); re-embedded when the .wav is newer."""
    cache = VOICE_DIR / f"{Path(wav).stem}.conds.pt"  # where render.py keeps its caches
    if cache.exists() and cache.stat().st_mtime >= Path(wav).stat().st_mtime:
        model.set_conditionals_from_dict(torch.load(cache))
        return
    saved = {}

    def capture(speaker_emb, prompt_tokens, ref_dict, _orig=model._set_conditionals):
        saved.update(t3={"speaker_emb": torch.from_numpy(np.asarray(speaker_emb)),
                         "cond_prompt_speech_tokens": None if prompt_tokens is None
                         else torch.from_numpy(np.asarray(prompt_tokens))},
                     gen=ref_dict)
        _orig(speaker_emb, prompt_tokens, ref_dict)
    model._set_conditionals = capture
    try:
        model.prepare_conditionals(wav, norm_loudness=False)
    finally:
        del model._set_conditionals
    try:
        torch.save(saved, cache)
    except OSError:
        pass  # read-only voice dir: just embed again next start


model = ChatterboxTurboMLX.from_pretrained(
    nano=os.environ.get("NARRATE_CB_NANO") == "1",
    quantize_bits=int(os.environ.get("NARRATE_CB_QUANT_BITS") or 0) or None)
assert model.sr == 24000, model.sr  # speak.py plays at 24 kHz
load_voice(VOICE)
model.generate("Okay.")  # warm-up: the first generation is several seconds slower


ALIASES = {"andrew": "s1", "speaker1": "s1", "brian": "s2", "speaker2": "s2"}  # as render.py


def voice_wav(name: str) -> str:
    """As render.py's voice_file: saved hosts beside the narrator voice, then the plugin's bundled
    library, then a .wav path."""
    name = ALIASES.get(name, name)
    dirs = [VOICE_DIR] + ([Path(_ssml[-1]).parent.parent / "voices"] if _ssml else [])
    for path in [d / f"{name}.wav" for d in dirs] + [Path(name).expanduser()]:
        if path.suffix == ".wav" and path.exists():
            return str(path)
    raise FileNotFoundError(f"no voice named {name!r}")


def apply_prosody(wav, prosody):
    """As render.py: the engine has no rate/pitch/volume, so they are applied to the generated audio."""
    if prosody.get("rate", 1.0) != 1.0:
        wav = librosa.effects.time_stretch(wav, rate=prosody["rate"])
    if prosody.get("pitch", 0.0):
        wav = librosa.effects.pitch_shift(wav, sr=model.sr, n_steps=prosody["pitch"])
    if prosody.get("volume", 0.0):
        wav = wav * 10 ** (prosody["volume"] / 20)
    return np.clip(wav, -1.0, 1.0)


def items(line: str):
    if ssml and has_shorthand(line):
        line = expand(line)
    if ssml and re.search(r"<\w[^>]*>", line):  # any SSML tag, even mid-line after a [tag]
        try:
            return ssml.parse(line if line.startswith("<speak") else f"<speak>{line}</speak>", VOICE_DIR)
        except Exception as e:  # bad markup: say the words rather than nothing
            print(f"ssml: {e}; speaking it as text", flush=True)
            line = re.sub(r"<[^>]+>", " ", line)
    return [("speech", VOICE, clean_tags(line), {}, {})]


def render(line: str):
    """Yield float32 pieces for one line: plain text streams; script items play in order."""
    try:
        for item in items(line):
            if item[0] == "break":
                yield np.zeros(int(model.sr * item[1]), dtype=np.float32)
            elif item[0] == "audio":
                if Path(item[1]).exists():
                    yield librosa.load(item[1], sr=model.sr, mono=True)[0]
            else:
                _, voice, text, sampling, prosody = item
                try:
                    load_voice(voice_wav(voice))
                except Exception as e:  # unknown voice name: keep the default one
                    print(f"voice {voice}: {e}", flush=True)
                    load_voice(VOICE)
                opts = {**OPTS, **sampling}
                if prosody:
                    yield apply_prosody(model.generate(text, **{k: v for k, v in opts.items()
                                                                if k not in ("first_chunk_tokens", "chunk_tokens")}), prosody)
                else:
                    gen = model.generate_stream(text, **opts)
                    try:
                        yield from gen
                    finally:
                        gen.close()
    finally:
        load_voice(VOICE)  # back to the narrator, even after a barge-in


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        gen = render(" ".join(self.rfile.readline().decode().split()))
        try:
            for piece in gen:
                self.wfile.write(np.asarray(piece, dtype=np.float32).tobytes())
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client was stopped: drop the rest of the line
        finally:
            gen.close()


Path(SOCK).unlink(missing_ok=True)  # a stale socket; speak.py's lock means no other server owns it
with socketserver.UnixStreamServer(SOCK, Handler) as srv:
    srv.timeout, srv.idle = float(os.environ.get("NARRATE_CB_IDLE", "1800")), False
    srv.handle_timeout = lambda: setattr(srv, "idle", True)
    print("ready", flush=True)
    while not srv.idle:
        srv.handle_request()
    Path(SOCK).unlink(missing_ok=True)  # idle: free the model; the next speak starts a new server
    print("idle, exiting", flush=True)
