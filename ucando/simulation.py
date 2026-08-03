"""Restbus simulation — play the "rest of the bus" from a database.

When you bench-test a single ECU it expects to hear all the *other* ECUs. A
restbus simulation transmits every message in a DBC cyclically (at each
message's cycle time, or a default), so the ECU under test sees a plausible live
vehicle. This is one of CANoe's headline features.

:class:`RestbusSimulator` takes a cantools database (loaded from the DBC Builder
model or an OEM profile) and a ``send`` callable (``BusManager.send``) — like
Replay and the TX Scheduler it never opens its own bus, staying adapter
agnostic. It runs one daemon thread that re-sends each due message; payloads are
the DBC-encoded defaults (all signals 0 / their minimum), falling back to a
zero-filled frame of the message length if encoding fails.

Override values per message via :meth:`set_value` to drive a signal during a
test (e.g. hold EngineRPM at 2000).
"""

from __future__ import annotations

import threading
import time

import can

DEFAULT_CYCLE_MS = 100


def _cycle_ms(message) -> float:
    ct = getattr(message, "cycle_time", None)
    return float(ct) if ct else float(DEFAULT_CYCLE_MS)


def _default_payload(message) -> bytes:
    """DBC-encoded all-zero payload, or a zero frame if encoding fails."""
    try:
        values = {s.name: 0 for s in message.signals if not s.is_multiplexer}
        return bytes(message.encode(values, strict=False, padding=True))
    except Exception:
        return bytes(message.length)


class RestbusSimulator:
    def __init__(self, send):
        self._send = send
        self._lock = threading.Lock()
        self._msgs: list[dict] = []      # {id, ext, data(bytes), cycle_ms, _next, name}
        self._overrides: dict[int, bytes] = {}
        self._thread = None
        self._running = False
        self._sent = 0

    def load_db(self, db) -> dict:
        """Build the transmit plan from a cantools database."""
        with self._lock:
            self._msgs = []
            for m in db.messages:
                self._msgs.append({
                    "id": m.frame_id, "ext": bool(m.is_extended_frame),
                    "name": m.name, "cycle_ms": _cycle_ms(m),
                    "data": _default_payload(m), "_next": 0.0,
                })
        return self.status()

    def set_value(self, frame_id: int, data) -> None:
        """Override a message's transmitted payload (hex str or bytes)."""
        if isinstance(data, str):
            data = bytes(int(b, 16) for b in data.replace(",", " ").split())
        with self._lock:
            self._overrides[int(frame_id)] = bytes(data)

    # ----- lifecycle -------------------------------------------------------
    def start(self) -> dict:
        with self._lock:
            if self._running or not self._msgs:
                return self.status()
            self._running = True
            now = time.time()
            for m in self._msgs:
                m["_next"] = now
        self._thread = threading.Thread(target=self._run, name="restbus", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        return self.status()

    def _run(self) -> None:
        while self._running:
            now = time.time()
            due = []
            with self._lock:
                for m in self._msgs:
                    if now >= m["_next"]:
                        data = self._overrides.get(m["id"], m["data"])
                        due.append((m, data))
                        m["_next"] = now + m["cycle_ms"] / 1000.0
            for m, data in due:
                try:
                    self._send(can.Message(arbitration_id=m["id"], data=data,
                                           is_extended_id=m["ext"]))
                    self._sent += 1
                except Exception:
                    pass
            time.sleep(0.002)

    def status(self) -> dict:
        with self._lock:
            return {"running": self._running, "messages": len(self._msgs),
                    "sent": self._sent,
                    "msg_ids": [f"{m['id']:0{8 if m['ext'] else 3}X}" for m in self._msgs]}
