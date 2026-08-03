"""Shared pytest fixtures and the virtual-bus integration harness.

No hardware is needed: every integration test runs against python-can's
in-process ``virtual`` bus on a per-test unique channel, so tests don't see
each other's traffic.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid

# Redirect the server's writable home *before* anything imports ``canforge.server``
# (pytest loads conftest first), so a test run never touches data/canforge.db.
_TEST_HOME = tempfile.mkdtemp(prefix="canforge-tests-")
os.environ.setdefault("CANFORGE_HOME", _TEST_HOME)

import can
import pytest

from canforge.storage import Storage


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("CANFORGE_HOME") == _TEST_HOME:
        shutil.rmtree(_TEST_HOME, ignore_errors=True)


def wait_until(predicate, timeout: float = 3.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until true or timeout. Returns the final truthiness."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


@pytest.fixture
def vchannel() -> str:
    """A unique virtual-bus channel name per test."""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sender(vchannel):
    """A raw virtual bus on the test channel for injecting frames."""
    bus = can.Bus(interface="virtual", channel=vchannel, bitrate=500_000)
    yield bus
    bus.shutdown()


@pytest.fixture
def storage():
    """An in-memory Storage instance (no file on disk)."""
    s = Storage(path=":memory:")
    yield s
    s.close()
