"""Shared pytest fixtures and the virtual-bus integration harness.

No hardware is needed: every integration test runs against python-can's
in-process ``virtual`` bus on a per-test unique channel, so tests don't see
each other's traffic.
"""

from __future__ import annotations

import time
import uuid

import can
import pytest

from canforge.storage import Storage


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
