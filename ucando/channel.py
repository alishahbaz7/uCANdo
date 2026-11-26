"""Which copy this is — the packaged release or a run from source — and what follows from it.

The user runs the packaged release daily and a source copy while developing, **at the same
time** (user skill ``utility-ui`` §11). Everything the two could fight over is keyed on the
channel: the default port here, the data folder (``server.py``: the exe keeps its data beside
itself, the source copy the repo's ``data/``), the "Dev" mark in the banner and the tab title,
and usage reporting (release only). Browsers scope page storage by port, so the two copies keep
their own theme and sidebar choices too.

Imports nothing heavy: ``main.py`` reads it before the server is loaded.
"""

from __future__ import annotations

import os
import sys

#: "release" for the packaged exe, "dev" for a run from source.
CHANNEL = "release" if getattr(sys, "frozen", False) else "dev"


def app_home() -> str:
    """Where writable state lives: for a release, beside the launcher (``<install>/data``, shared
    by every version the updater installs) or beside a hand-unzipped exe;
    the repo root from source. ``UCANDO_HOME`` relocates it — tests point it at a temp dir so a
    run never writes into the real database. ``CANFORGE_HOME`` is the pre-v1.4.1 name, still
    honoured. The one rule: server.py and main.py both read it."""
    if getattr(sys, "frozen", False):
        # a launcher install (v1.6.0 on) keeps data/ beside the launcher, shared by every version;
        # an older copy unzipped by hand keeps it beside the program
        from .install import launcher_root
        home = launcher_root() or os.path.dirname(sys.executable)
    else:
        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.environ.get("UCANDO_HOME") or os.environ.get("CANFORGE_HOME") or home


def data_dir() -> str:
    return os.path.join(app_home(), "data")

#: The release keeps 8765 — the address its README has always given. A source run sits 100
#: above, so starting one never collides with the copy someone is working in.
DEFAULT_PORT = {"release": 8765, "dev": 8865}
