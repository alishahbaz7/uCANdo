"""TX Scheduler — transmit predefined frames cyclically or on demand.

Holds a table of TX entries (arbitration ID + payload + cycle time + mode) and
runs a single background scheduler thread that re-sends each enabled cyclic
entry when its period elapses. One-shot entries are fired once via
:meth:`send_once`. All transmission goes through a ``send`` callable
(``BusManager.send``) so the scheduler stays adapter agnostic.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import can


def _parse_data(data) -> bytes:
    """Accept hex string ('11 22 AA') or list[int]."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        cleaned = data.replace(",", " ").split()
        return bytes(int(b, 16) for b in cleaned)
    return bytes(int(b) & 0xFF for b in (data or []))


class TxScheduler:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: list[dict] = []   # each: id, ext, data(bytes), cycle_ms, enabled, mode, _next, _count
        self._next_id = 1
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._send: Optional[Callable] = None

    # ----- table management ------------------------------------------------
    def add(self, arb_id: int, data, cycle_ms: int = 100, mode: str = "cyclic",
            is_extended: bool = False, name: str = "") -> dict:
        with self._lock:
            entry = {
                "uid": self._next_id,
                "name": name or f"TX_{arb_id:X}",
                "id": int(arb_id),
                "ext": bool(is_extended),
                "data": _parse_data(data),
                "cycle_ms": int(cycle_ms),
                "mode": mode,            # cyclic | once
                "enabled": mode == "cyclic",
                "_next": 0.0,
                "count": 0,
            }
            self._next_id += 1
            self._entries.append(entry)
            return self._public(entry)

    def update(self, uid: int, patch: dict) -> dict:
        with self._lock:
            entry = self._find(uid)
            if "data" in patch:
                patch = {**patch, "data": _parse_data(patch["data"])}
            entry.update({k: v for k, v in patch.items() if k in
                          ("name", "id", "ext", "data", "cycle_ms", "mode", "enabled")})
            return self._public(entry)

    def remove(self, uid: int) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if e["uid"] != uid]

    def _find(self, uid: int) -> dict:
        for e in self._entries:
            if e["uid"] == uid:
                return e
        raise KeyError(uid)

    # ----- run -------------------------------------------------------------
    def start(self, send: Callable[[can.Message], None]) -> None:
        with self._lock:
            if self._running:
                return
            self._send = send
            self._running = True
            now = time.time()
            for e in self._entries:
                e["_next"] = now
        self._thread = threading.Thread(target=self._run, name="tx-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def send_once(self, uid: int, send: Callable[[can.Message], None]) -> dict:
        with self._lock:
            entry = self._find(uid)
            msg = self._to_msg(entry)
            entry["count"] += 1
        send(msg)
        return {"sent": True}

    def _run(self) -> None:
        while self._running:
            now = time.time()
            due = []
            with self._lock:
                for e in self._entries:
                    if e["enabled"] and e["mode"] == "cyclic" and now >= e["_next"]:
                        due.append(self._to_msg(e))
                        e["_next"] = now + e["cycle_ms"] / 1000.0
                        e["count"] += 1
            for msg in due:
                try:
                    if self._send:
                        self._send(msg)
                except Exception:
                    pass
            time.sleep(0.002)  # 2 ms scheduler tick

    # ----- helpers ---------------------------------------------------------
    @staticmethod
    def _to_msg(e: dict) -> can.Message:
        return can.Message(arbitration_id=e["id"], data=e["data"],
                           is_extended_id=e["ext"])

    @staticmethod
    def _public(e: dict) -> dict:
        return {
            "uid": e["uid"], "name": e["name"], "id": e["id"],
            "id_hex": f"{e['id']:0{8 if e['ext'] else 3}X}", "ext": e["ext"],
            "data": e["data"].hex(" ").upper(), "dlc": len(e["data"]),
            "cycle_ms": e["cycle_ms"], "mode": e["mode"],
            "enabled": e["enabled"], "count": e["count"],
        }

    def table(self) -> dict:
        with self._lock:
            return {"running": self._running,
                    "entries": [self._public(e) for e in self._entries]}
