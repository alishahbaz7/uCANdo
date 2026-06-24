"""Application logging — rotating file + console, plus crash hooks.

`setup_logging()` wires a **rotating log file** (default ``data/ucando.log``) so any
error, warning or crash is captured for later corrective action — including:

* uncaught exceptions in the **main thread** (``sys.excepthook``),
* uncaught exceptions in **worker threads** (``threading.excepthook``),
* unhandled errors in API routes (the FastAPI handler in ``server.py``),
* otherwise-swallowed errors in the capture loop / frame taps.

Modules just use ``logging.getLogger("canforge.<area>")``; the file handler is
attached to the root logger so every logger flows into the same file.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading

LOGGER_NAME = "canforge"
_configured = False
_log_path: str | None = None


def setup_logging(log_path: str, level: int = logging.INFO) -> logging.Logger:
    """Attach a rotating file handler (1 MB × 5) + console; install crash hooks.

    Idempotent — safe to call more than once (only the first call configures).
    """
    global _configured, _log_path
    log = logging.getLogger(LOGGER_NAME)
    if _configured:
        return log
    _log_path = log_path
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    # Root at WARNING keeps noisy third-party libs (httpx/uvicorn access, can, …)
    # to problems-only; our own canforge.* logger runs at INFO for key activity.
    root.setLevel(logging.WARNING)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass                                   # never let logging setup break startup
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    log.setLevel(level)                        # canforge.* = INFO (activity + all errors)
    _install_crash_hooks()
    _configured = True
    log.info("uCANdo logging started -> %s", log_path)
    return log


def log_path() -> str | None:
    return _log_path


def _install_crash_hooks() -> None:
    crash = logging.getLogger(LOGGER_NAME + ".crash")

    def _excepthook(exc_type, exc, tb):
        crash.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    def _thread_excepthook(args):
        crash.critical("Uncaught exception in thread %s",
                       getattr(args.thread, "name", "?"),
                       exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    try:
        threading.excepthook = _thread_excepthook      # Python 3.8+
    except Exception:
        pass
