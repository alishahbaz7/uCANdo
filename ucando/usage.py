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
from collections.abc import Callable

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


#: Windows console events after which the process is ended without uvicorn's shutdown:
#: CTRL_CLOSE_EVENT (the console window's X), CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT.
#: Ctrl+C (0) and Ctrl+Break (1) are left to uvicorn, which shuts down cleanly on them.
CONSOLE_CLOSE_EVENTS = frozenset({2, 5, 6})
_console_handler = None  # the registered callback; it must stay referenced or ctypes frees it


def on_console_event(kind: int, reporter: UsageReporter | None) -> bool:
    """The console is closing: end the session and send it (3 s at most) before Windows ends the
    process. Returns False so the default handling — ending the process — carries on."""
    if kind in CONSOLE_CLOSE_EVENTS and reporter is not None:
        try:
            reporter.stop()
        except Exception:
            pass  # silent by design: reporting must never hold up closing
    return False


def end_session_on_console_close(get_reporter: Callable[[], UsageReporter | None]) -> bool:
    """Closing uCANdo's console window, the documented way to stop it, gives the process about
    5 s and never reaches uvicorn's shutdown: an open app window's WebSocket alone holds that up.
    So the lifespan's ``usage.stop()`` never ran, and every session reached the server as *not
    closed normally*, its last minutes only at the next start (found on the v1.6.0 release build,
    2026-11-26). This registers a console handler that ends the session directly.
    ``get_reporter()`` returns the reporter, or None while the server is not loaded.
    Returns whether a handler was registered (Windows only)."""
    global _console_handler
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    def _handle(kind: int) -> bool:
        try:
            reporter = get_reporter()
        except Exception:
            reporter = None
        return on_console_event(kind, reporter)

    _console_handler = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(_handle)
    return bool(ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler, True))


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
