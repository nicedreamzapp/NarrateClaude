#!/usr/bin/env python3
"""chatterbox_server.py: keeps Chatterbox Turbo loaded so `speak` doesn't reload it every line.

Runs in the explain-as-podcast venv (chatterbox-mlx). speak.py starts it on first use when
NARRATE_TTS=chatterbox. Protocol on the unix socket: the client sends one line of text; the server
streams back raw float32 mono PCM at 24 kHz as it is generated, then closes. If the client hangs up
(barge-in), generation stops. Text can carry Chatterbox tags like [laugh], [chuckle], [sigh].

Env (read at server start; restart the server to change them):
  NARRATE_CB_NANO         1 = the smaller nano model (~2x faster, starts in ~0.25 s)
  NARRATE_CB_FIRST_CHUNK  speech tokens in the first streamed piece (default 15; lower = sooner)
  NARRATE_CB_TEMPERATURE  delivery variety (default 0.8)
  NARRATE_CB_SEED         fixed seed so a line always sounds the same (default: random)
"""
import os
import socketserver
import sys
from pathlib import Path

import numpy as np
from chatterbox.tts_turbo_mlx import ChatterboxTurboMLX

SOCK = sys.argv[1]
VOICE = os.path.expanduser(sys.argv[2])

OPTS = {"first_chunk_tokens": int(os.environ.get("NARRATE_CB_FIRST_CHUNK", "15")),
        "temperature": float(os.environ.get("NARRATE_CB_TEMPERATURE", "0.8"))}
if os.environ.get("NARRATE_CB_SEED"):
    OPTS["seed"] = int(os.environ["NARRATE_CB_SEED"])

model = ChatterboxTurboMLX.from_pretrained(nano=os.environ.get("NARRATE_CB_NANO") == "1")
assert model.sr == 24000, model.sr  # speak.py plays at 24 kHz
model.prepare_conditionals(VOICE, norm_loudness=False)
model.generate("Okay.")  # warm-up: the first generation is several seconds slower


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        text = self.rfile.readline().decode().strip()
        gen = model.generate_stream(text, **OPTS)
        try:
            for piece in gen:
                self.wfile.write(np.asarray(piece, dtype=np.float32).tobytes())
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client was stopped: drop the rest of the line
        finally:
            gen.close()


Path(SOCK).unlink(missing_ok=True)
with socketserver.UnixStreamServer(SOCK, Handler) as srv:
    print("ready", flush=True)
    srv.serve_forever()
