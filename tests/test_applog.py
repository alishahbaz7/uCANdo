"""Error/crash logging — verify failures land in the log file for diagnosis."""

import logging
import os
import threading
import uuid

import can

# Importing the server triggers applog.setup_logging() (data/ucando.log).
import ucando.server  # noqa: F401
from ucando import applog
from ucando.logger import CanLogger


def _read_log() -> str:
    path = applog.log_path()
    assert path and os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_log_file_created_and_path_exposed():
    assert applog.log_path() and os.path.exists(applog.log_path())


def test_error_message_written_to_file():
    marker = f"stability-err-{uuid.uuid4().hex}"
    logging.getLogger("ucando.test").error(marker)
    assert marker in _read_log()


def test_exception_traceback_is_logged():
    marker = f"trace-{uuid.uuid4().hex}"
    try:
        raise ValueError(marker)
    except ValueError:
        logging.getLogger("ucando.test").exception("boom")
    text = _read_log()
    assert marker in text and "Traceback" in text and "ValueError" in text


def test_crash_hooks_are_installed():
    import sys
    assert sys.excepthook is not sys.__excepthook__          # our main-thread hook
    assert callable(threading.excepthook)


def test_worker_thread_crash_is_logged():
    # A real worker-thread exception must be captured via threading.excepthook.
    marker = f"threadcrash-{uuid.uuid4().hex}"

    def _boom():
        raise RuntimeError(marker)

    t = threading.Thread(target=_boom, name="boom-thread")
    t.start()
    t.join()
    assert marker in _read_log()


def test_frame_tap_error_is_logged_once():
    # A tap that raises must be logged (not silently swallowed) without crashing capture.
    class _FakeIface:
        config = {"bitrate": 500_000}
        def recv(self, timeout=0.0): return None
        def close(self): pass

    lg = CanLogger(_FakeIface())
    tag = f"taperr-{uuid.uuid4().hex}"

    def bad_tap(msg):
        raise RuntimeError(tag)

    lg.add_tap(bad_tap)
    msg = can.Message(arbitration_id=0x123, data=b"\x01\x02", is_extended_id=False)
    lg._ingest(msg)            # first failure -> logged
    lg._ingest(msg)            # subsequent failures suppressed (no flood)
    text = _read_log()
    assert "frame tap" in text and "bad_tap" in text
    # capture itself kept working despite the failing tap
    assert lg.snapshot()["total"] == 2


def test_setup_logging_is_idempotent():
    before = applog.log_path()
    applog.setup_logging("some/other/never-used.log")        # no-op once configured
    assert applog.log_path() == before
