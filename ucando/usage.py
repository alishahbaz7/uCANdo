"""Usage reporting for uCANdo (user skill ``app-control``) — who uses this copy, which version, how.

One reporter for the app, sending to the shared usage server every one of this user's apps reports
to, as app "uCANdo". **Release builds only** (the user's choice, 2026-11-24): the packaged exe
reports, a run from source does not — so a development session never adds a row to the user list.
``UCANDO_USAGE=off`` switches a release copy off; ``UCANDO_USAGE=on`` switches a source run on
(with ``UCANDO_USAGE_URL`` pointing it at a test server — never the real one without saying so).
The test suite sets ``UCANDO_USAGE=off`` in conftest, so no test can reach the server.

Reports wait in ``data/usage.json`` until the server has them, so starts made offline still count;
nothing here may slow or stop uCANdo (the client sends on its own thread, gives up after 30 s,
backs off while offline and catches everything).

What is reported: the name the person gave once, this computer (Windows login, computer name,
Windows version, time zone), the app version and build, how long uCANdo ran, the views opened,
errors, and the counts below. **Never reported:** CAN frames, IDs, payloads, signal values, DBCs,
log files or their names, VINs, adapter serials — anything a capture contains.
"""

from __future__ import annotations

import os
import threading
from collections import Counter

from . import __app_name__, __version__
from .usage_client import URL, UsageReporter

_ENV = os.environ.get("UCANDO_USAGE", "").strip().lower()
SWITCHED_OFF = _ENV in ("0", "off", "false", "no")
FORCED_ON = _ENV in ("1", "on", "true", "yes")
TEST_URL = os.environ.get("UCANDO_USAGE_URL") or None

#: The views a view-open may name — the ``NAV`` ids in web/app.js. Anything else is not counted,
#: so a page can never put free text into the report.
VIEWS = frozenset({
    "dashboard", "logger", "replay", "re", "autore", "framedec", "convert", "dbc", "oem",
    "signals", "scheduler", "automation", "dtc", "decoder",
})

# uCANdo's own counters — camelCase, counts only, read into the session's metrics on each tick.
_counts: Counter = Counter()
_lock = threading.Lock()


def count(name: str, n: int = 1) -> None:
    """Something uCANdo did, counted: busConnects, recordings, replaysStarted, …"""
    with _lock:
        _counts[name] += n


def _metrics() -> dict:
    with _lock:
        return dict(_counts)


def create(data_dir: str, build: str) -> UsageReporter:
    """The app's one reporter. ``build`` is "release" for the packaged exe, "dev" from source."""
    enabled = (build == "release" or FORCED_ON) and not SWITCHED_OFF
    reporter = UsageReporter(app=__app_name__, version=__version__, data_dir=data_dir,
                             enabled=enabled, build=build, url=TEST_URL or URL)
    reporter.metrics = _metrics
    return reporter


def disabled_reason(reporter: UsageReporter, build: str) -> str | None:
    """Why reporting is off on this copy, in words; None when it is on."""
    if reporter.enabled:
        return None
    if SWITCHED_OFF:
        return "Usage reporting is switched off on this computer."
    if build != "release":
        return "A run from source does not report — only the packaged uCANdo does."
    return "Usage reporting is off on this copy."


def status(reporter: UsageReporter, build: str) -> dict:
    """For Settings → Usage reporting, the first-start name prompt and the greeting."""
    s = reporter.status()
    s["needs_name"] = reporter.needs_name
    s["disabled_reason"] = disabled_reason(reporter, build)
    s["build"] = build
    return s
