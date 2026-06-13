"""CAN Logger — live capture, per-ID statistics and recording/export.

A :class:`CanLogger` owns one background receive thread bound to a
:class:`~canforge.hal.CANInterface`. Every received frame fans out to:

* a rolling **recent-frames** buffer for the live feed,
* an aggregated **per-ID** table (count, period estimate, last payload),
* global **stats** (total, frames/s, rough bus load), and
* any **active recording** writer (.asc / .blf / .csv).

Recording streams straight to a python-can writer, so logs of any length are
captured without holding every frame in memory.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Optional

import can

from .hal import CANInterface

RECENT_MAXLEN = 250
FPS_WINDOW_S = 2.0

# python-can writer per export format.
_WRITERS = {
    "asc": (can.ASCWriter, ".asc"),
    "blf": (can.BLFWriter, ".blf"),
    "csv": (can.CSVWriter, ".csv"),
}


def _frame_dict(msg: can.Message) -> dict:
    return {
        "ts": round(msg.timestamp, 6),
        "id": msg.arbitration_id,
        "id_hex": f"{msg.arbitration_id:0{8 if msg.is_extended_id else 3}X}",
        "ext": bool(msg.is_extended_id),
        "rtr": bool(msg.is_remote_frame),
        "fd": bool(getattr(msg, "is_fd", False)),
        "dlc": msg.dlc,
        "channel": str(msg.channel) if msg.channel is not None else "",
        "data": msg.data.hex(" ").upper(),
    }


class CanLogger:
    def __init__(self, iface: CANInterface, taps: Optional[list] = None):
        self._iface = iface
        self._lock = threading.Lock()
        # Frame taps: callables invoked with every received can.Message, OUTSIDE
        # the stats lock. Used by the Signal Viewer / Protocol Decoder to observe
        # live traffic without spawning a second receive thread.
        self._taps: list = list(taps) if taps else []
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self.total = 0
        self.start_ts: Optional[float] = None
        self.last_ts: Optional[float] = None
        self._recent: deque[dict] = deque(maxlen=RECENT_MAXLEN)
        self._fps_window: deque[float] = deque()
        # key -> aggregated stat. key is (arbitration_id, is_extended).
        self._ids: dict[tuple[int, bool], dict] = {}

        # Recording state.
        self._writer = None
        self._record_path: Optional[str] = None
        self._record_count = 0
        self._record_start: Optional[float] = None

    # ----- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.start_ts = time.time()
        self._thread = threading.Thread(target=self._run, name="can-logger", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        self.stop_recording()

    # ----- receive loop ----------------------------------------------------
    def _run(self) -> None:
        while self._running:
            try:
                msg = self._iface.recv(timeout=0.2)
            except Exception:
                # A read error usually means the bus went away; back off briefly.
                time.sleep(0.1)
                continue
            if msg is None:
                continue
            self._ingest(msg)

    def _ingest(self, msg: can.Message) -> None:
        now = msg.timestamp or time.time()
        with self._lock:
            self.total += 1
            self.last_ts = now
            self._recent.append(_frame_dict(msg))

            self._fps_window.append(now)
            cutoff = now - FPS_WINDOW_S
            while self._fps_window and self._fps_window[0] < cutoff:
                self._fps_window.popleft()

            key = (msg.arbitration_id, bool(msg.is_extended_id))
            stat = self._ids.get(key)
            if stat is None:
                stat = {
                    "id": msg.arbitration_id,
                    "id_hex": f"{msg.arbitration_id:0{8 if msg.is_extended_id else 3}X}",
                    "ext": bool(msg.is_extended_id),
                    "count": 0,
                    "dlc": msg.dlc,
                    "data": "",
                    "first_ts": now,
                    "last_ts": now,
                    "period_ms": 0.0,
                }
                self._ids[key] = stat
            # Exponential moving average of inter-frame period.
            dt_ms = (now - stat["last_ts"]) * 1000.0
            if stat["count"] >= 1 and dt_ms > 0:
                stat["period_ms"] = (
                    dt_ms if stat["period_ms"] == 0 else 0.8 * stat["period_ms"] + 0.2 * dt_ms
                )
            stat["count"] += 1
            stat["dlc"] = msg.dlc
            stat["data"] = msg.data.hex(" ").upper()
            stat["last_ts"] = now

            if self._writer is not None:
                try:
                    self._writer.on_message_received(msg)
                    self._record_count += 1
                except Exception:
                    pass

        # Taps run outside the lock so a slow consumer (e.g. DBC decode) never
        # stalls the receive loop or blocks UI snapshots.
        for tap in self._taps:
            try:
                tap(msg)
            except Exception:
                pass

    def add_tap(self, fn) -> None:
        if fn not in self._taps:
            self._taps.append(fn)

    def remove_tap(self, fn) -> None:
        if fn in self._taps:
            self._taps.remove(fn)

    # ----- recording -------------------------------------------------------
    def start_recording(self, fmt: str, path: str) -> dict:
        fmt = fmt.lower()
        if fmt not in _WRITERS:
            raise ValueError(f"Unknown format {fmt!r}. Use one of {sorted(_WRITERS)}")
        with self._lock:
            if self._writer is not None:
                raise RuntimeError("Already recording")
            writer_cls, ext = _WRITERS[fmt]
            if not path.lower().endswith(ext):
                path += ext
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._writer = writer_cls(path)
            self._record_path = path
            self._record_count = 0
            self._record_start = time.time()
        return {"recording": True, "path": path, "format": fmt}

    def stop_recording(self) -> dict:
        with self._lock:
            if self._writer is None:
                return {"recording": False}
            writer = self._writer
            path = self._record_path
            count = self._record_count
            self._writer = None
            self._record_path = None
        try:
            writer.stop()
        except Exception:
            pass
        return {"recording": False, "path": path, "frames": count}

    # ----- snapshot for the UI --------------------------------------------
    def snapshot(self, recent_limit: int = 60) -> dict:
        with self._lock:
            elapsed = (self.last_ts - self.start_ts) if (self.start_ts and self.last_ts) else 0.0
            fps = len(self._fps_window) / FPS_WINDOW_S if self._fps_window else 0.0
            ids = sorted(self._ids.values(), key=lambda s: s["id"])
            recent = list(self._recent)[-recent_limit:][::-1]  # newest first
            return {
                "running": self._running,
                "total": self.total,
                "unique_ids": len(self._ids),
                "fps": round(fps, 1),
                "bus_load_pct": self._bus_load(fps),
                "elapsed_s": round(elapsed, 2),
                "recording": self._writer is not None,
                "record_path": self._record_path,
                "record_frames": self._record_count,
                "ids": ids,
                "recent": recent,
            }

    def _bus_load(self, fps: float) -> float:
        """Rough bus-load estimate assuming ~110 bits/standard frame @ bitrate."""
        bitrate = 0
        cfg = getattr(self._iface, "config", {}) or {}
        bitrate = cfg.get("bitrate") or 500_000
        if not bitrate:
            return 0.0
        avg_bits_per_frame = 110  # arbitration + control + 8 data bytes + stuffing margin
        return round(min(100.0, (fps * avg_bits_per_frame) / bitrate * 100.0), 1)

    def clear(self) -> None:
        with self._lock:
            self.total = 0
            self._recent.clear()
            self._fps_window.clear()
            self._ids.clear()
            self.start_ts = time.time()
            self.last_ts = None
