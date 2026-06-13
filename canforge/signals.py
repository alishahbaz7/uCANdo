"""Signal Viewer — decode live frames against a DBC and buffer time series.

A loaded cantools database is used to decode every incoming frame (delivered
via a :class:`~canforge.logger.CanLogger` tap). Decoded scalar signals are
appended to bounded per-signal ring buffers; the UI polls :meth:`series` to
draw strip charts.

The decoder is deliberately defensive: unknown IDs, short payloads, and
multiplexed/choice (non-numeric) signals are skipped rather than raised, so a
partial or mismatched DBC never stalls the live view.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import cantools

from .derived import AlarmMonitor, ComputedSignals

COMPUTED_PREFIX = "COMPUTED"


class SignalViewer:
    def __init__(self, maxlen: int = 600):
        self._lock = threading.Lock()
        self._db = None
        self._dbc_name: str | None = None
        self._maxlen = maxlen
        # "MSG.SIGNAL" -> deque[(t, value)]
        self._series: dict[str, deque] = {}
        self._t0: float | None = None
        self._frames_decoded = 0
        self._frames_seen = 0
        # Latest value per signal key — feeds computed signals + alarms.
        self._latest: dict[str, float] = {}
        self.computed = ComputedSignals()
        self.alarms = AlarmMonitor()

    # ----- DBC management --------------------------------------------------
    def load_dbc_string(self, text: str, name: str = "inline.dbc") -> dict:
        db = cantools.database.load_string(text, database_format="dbc")
        with self._lock:
            self._db = db
            self._dbc_name = name
            self._series.clear()
            self._t0 = None
            self._frames_decoded = 0
            self._frames_seen = 0
        return self.info()

    def load_dbc_file(self, path: str) -> dict:
        db = cantools.database.load_file(path)
        with self._lock:
            self._db = db
            self._dbc_name = path
            self._series.clear()
            self._t0 = None
        return self.info()

    def info(self) -> dict:
        with self._lock:
            if not self._db:
                return {"loaded": False, "signals": []}
            sigs = []
            for m in self._db.messages:
                for s in m.signals:
                    sigs.append({"key": f"{m.name}.{s.name}", "message": m.name,
                                 "signal": s.name, "unit": s.unit or ""})
            return {"loaded": True, "dbc": self._dbc_name,
                    "messages": len(self._db.messages), "signals": sigs}

    # ----- live tap (called per frame by the logger) -----------------------
    def consume(self, msg) -> None:
        if self._db is None:
            return
        with self._lock:
            self._frames_seen += 1
        try:
            decoded = self._db.decode_message(msg.arbitration_id, bytes(msg.data))
        except Exception:
            return
        t = msg.timestamp or time.time()
        try:
            message = self._db.get_message_by_frame_id(msg.arbitration_id)
            mname = message.name
        except Exception:
            mname = f"0x{msg.arbitration_id:X}"
        with self._lock:
            if self._t0 is None:
                self._t0 = t
            rel = round(t - self._t0, 4)
            for sig_name, value in decoded.items():
                # Skip choice/enumeration (NamedSignalValue) — not chartable.
                if not isinstance(value, (int, float)):
                    try:
                        value = float(value)
                    except Exception:
                        continue
                key = f"{mname}.{sig_name}"
                self._append(key, rel, float(value))
                self._latest[key] = float(value)
            # Derived: computed signals (math channels), then alarms.
            for cname, cval in self.computed.evaluate(self._latest).items():
                ckey = f"{COMPUTED_PREFIX}.{cname}"
                self._append(ckey, rel, cval)
                self._latest[ckey] = cval
            self.alarms.evaluate(self._latest)
            self._frames_decoded += 1

    def _append(self, key: str, t: float, value: float) -> None:
        buf = self._series.get(key)
        if buf is None:
            buf = deque(maxlen=self._maxlen)
            self._series[key] = buf
        buf.append((t, value))

    # ----- read API --------------------------------------------------------
    def series(self, keys: list[str] | None = None) -> dict:
        with self._lock:
            out = {}
            wanted = keys or list(self._series.keys())
            for k in wanted:
                buf = self._series.get(k)
                if buf:
                    out[k] = list(buf)
            return {
                "loaded": self._db is not None,
                "frames_seen": self._frames_seen,
                "frames_decoded": self._frames_decoded,
                "series": out,
            }

    # ----- computed signals & alarms --------------------------------------
    def set_computed(self, defs: list[dict]) -> dict:
        self.computed.set(defs)
        return {"computed": self.computed.defs()}

    def set_alarms(self, defs: list[dict]) -> dict:
        self.alarms.set(defs)
        return self.alarms.snapshot()

    def derived(self) -> dict:
        """Computed-signal defs + current alarm states (UI polls this)."""
        with self._lock:
            return {"computed": self.computed.defs(), **self.alarms.snapshot()}

    def clear(self) -> None:
        with self._lock:
            self._series.clear()
            self._latest.clear()
            self._t0 = None
            self.alarms.clear()
