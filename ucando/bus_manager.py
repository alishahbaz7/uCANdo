"""Application-wide bus state.

A single :class:`BusManager` instance holds the currently open interface, the
:class:`~ucando.logger.CanLogger` bound to it, and (for the virtual bus) the
synthetic traffic feeder. The FastAPI layer holds exactly one of these and
serializes connect/disconnect through its lock.
"""

from __future__ import annotations

import threading
from typing import Optional

from .hal import CANInterface, create_interface
from .logger import CanLogger
from .sim import SyntheticTraffic


class BusManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.iface: Optional[CANInterface] = None
        self.logger: Optional[CanLogger] = None
        self.sim: Optional[SyntheticTraffic] = None
        self.conn: Optional[dict] = None
        # Persistent frame taps re-applied to each new logger on connect, so
        # subsystems (Signal Viewer, Protocol Decoder) survive reconnects.
        self._taps: list = []

    def add_tap(self, fn) -> None:
        if fn not in self._taps:
            self._taps.append(fn)
        if self.logger:
            self.logger.add_tap(fn)

    def remove_tap(self, fn) -> None:
        if fn in self._taps:
            self._taps.remove(fn)
        if self.logger:
            self.logger.remove_tap(fn)

    def send(self, msg) -> None:
        """Transmit a frame on the live bus (used by Replay / TX Scheduler)."""
        if self.iface is None:
            raise RuntimeError("Not connected")
        self.iface.send(msg)

    @property
    def connected(self) -> bool:
        return self.iface is not None

    def connect(self, hw: str, channel: str, bitrate: int = 500_000,
                fd: bool = False, simulate: bool = True,
                echo_tx: bool = False) -> dict:
        """Open a bus.

        *echo_tx* asks the driver to loop our own transmitted frames back into
        the receive path (``receive_own_messages``). That turns "what we sent"
        from a self-reported claim into something the logger actually observed —
        the basis of the TX-vs-cloud byte comparison. It is off by default
        because on a normal capture it would double-count our own traffic in the
        logger's statistics.
        """
        with self._lock:
            if self.iface is not None:
                self._teardown()

            # For the virtual bus, optionally start a synthetic feeder so the
            # logger has traffic to capture during development.
            if hw == "virtual" and simulate:
                self.sim = SyntheticTraffic(channel=str(channel), bitrate=bitrate)
                self.sim.start()

            extra = {"receive_own_messages": True} if echo_tx else {}
            self.iface = create_interface(hw, channel, bitrate=bitrate, fd=fd, **extra)
            self.logger = CanLogger(self.iface, taps=self._taps)
            self.logger.start()
            self.conn = {
                "hw": hw, "channel": str(channel), "bitrate": bitrate,
                "fd": fd, "simulated": bool(self.sim and self.sim.running),
                "echo_tx": bool(echo_tx),
            }
            return dict(self.conn)

    def disconnect(self) -> dict:
        with self._lock:
            self._teardown()
            return {"connected": False}

    def _teardown(self) -> None:
        if self.logger:
            self.logger.stop()
            self.logger = None
        if self.iface:
            self.iface.close()
            self.iface = None
        if self.sim:
            self.sim.stop()
            self.sim = None
        self.conn = None

    def status(self) -> dict:
        base = {"connected": self.connected, "connection": self.conn}
        if self.logger:
            base["logger"] = self.logger.snapshot()
        return base
