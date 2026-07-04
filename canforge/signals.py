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
from collections import Counter, deque

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
        # Callables invoked with a copy of the latest values each frame, OUTSIDE
        # the lock (e.g. the rules engine). Like logger taps, kept cheap.
        self._value_subscribers: list = []

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
            # allow_truncated: some messages legitimately vary DLC frame-to-frame
            # (e.g. state-only sends fewer bytes) — decode what's present rather
            # than dropping the frame outright (matches framedecode.py's convention).
            decoded = self._db.decode_message(msg.arbitration_id, bytes(msg.data), allow_truncated=True)
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
            latest_copy = dict(self._latest) if self._value_subscribers else None
        # Notify subscribers (rules engine) outside the lock.
        if latest_copy is not None:
            for fn in self._value_subscribers:
                try:
                    fn(latest_copy)
                except Exception:
                    pass

    def decode_frames_offline(self, frames: list[dict]) -> dict:
        """Decode a whole log (chronologically ordered) against the loaded
        DBC, for a signal-vs-time plot from an uploaded file rather than the
        live bus. Mirrors :meth:`consume`'s decode/skip rules exactly, but is
        read-only w.r.t. ``self._db`` and never touches the live ring buffers
        (``_series``/``_latest``/``_t0``) — a connected live session, if any,
        is unaffected. Unbounded (no ``maxlen`` cap): the log is already a
        fixed, finite file, not an ever-growing live stream.

        ``frames``: ``[{"id", "data", "timestamp"}, ...]`` — see
        :func:`canforge.reverse.flatten_frames_by_id`.

        A DBC only ever covers *some* of a real bus's traffic, so most logs
        decode a minority of their frames — that is expected, not a bug.
        To make that legible instead of a mystery number, frames are split
        three ways: decoded, **unknown** (id has no message in this DBC —
        the normal case), and **errored** (id *is* defined but decode still
        raised — a real problem, e.g. a DBC/vehicle mismatch), each reported
        with counts so the caller can tell which case they're in.
        """
        with self._lock:
            db = self._db
        if db is None:
            return {"loaded": False, "series": {}}
        known_ids = {m.frame_id for m in db.messages}
        series: dict[str, list] = {}
        t0 = None
        frames_seen = frames_decoded = 0
        unknown_counts: Counter = Counter()
        error_counts: dict[int, dict] = {}
        for fr in frames:
            frames_seen += 1
            fid = fr["id"]
            if fid not in known_ids:
                unknown_counts[fid] += 1
                continue
            try:
                # allow_truncated: a message's real DLC can be shorter than its
                # widest signal on some frames (e.g. state-only sends) — decode
                # what's present rather than dropping the frame outright.
                decoded = db.decode_message(fid, bytes(fr["data"]), allow_truncated=True)
            except Exception as exc:
                err = error_counts.setdefault(fid, {"count": 0, "error": str(exc)})
                err["count"] += 1
                continue
            t = fr["timestamp"]
            if t0 is None:
                t0 = t
            rel = round(t - t0, 4)
            mname = db.get_message_by_frame_id(fid).name
            decoded_any = False
            for sig_name, value in decoded.items():
                if not isinstance(value, (int, float)):
                    try:
                        value = float(value)
                    except Exception:
                        continue
                series.setdefault(f"{mname}.{sig_name}", []).append((rel, float(value)))
                decoded_any = True
            frames_decoded += decoded_any
        return {
            "loaded": True, "frames_seen": frames_seen, "frames_decoded": frames_decoded,
            "series": series,
            "unknown_ids": [{"id_hex": f"{i:X}", "count": c}
                            for i, c in sorted(unknown_counts.items(), key=lambda kv: -kv[1])],
            "decode_errors": [{"id_hex": f"{i:X}", "count": v["count"], "error": v["error"]}
                              for i, v in sorted(error_counts.items(), key=lambda kv: -kv[1]["count"])],
        }

    def add_value_subscriber(self, fn) -> None:
        if fn not in self._value_subscribers:
            self._value_subscribers.append(fn)

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
