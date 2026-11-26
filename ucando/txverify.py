"""Prove the bytes we transmitted are the bytes the TCU received.

"The TCU showed data" is a smoke test. This module makes it a measurement, by
keeping three artifacts apart:

* **A** — the log file: what the *vehicle* originally sent.
* **B** — what uCANdo actually put on the wire (:class:`TxRecorder`).
* **C** — what the device under test reported to the cloud (:func:`parse_cloud_log`).

The claim under test is **B == C**. Comparing A against C instead is the trap:
when they differ you cannot tell whether uCANdo altered something or the TCU
misparsed it, and you debug the wrong side. B is recorded separately so every
mismatch localises immediately.

B is deliberately recorded *after* signal patching (:mod:`ucando.txpatch`), since
that is what leaves the adapter. A verification run should normally have patching
off — :func:`compare` records whether it was on so a report can never
accidentally claim byte-fidelity against a log that was rewritten on the way out.

What we do NOT do: inject a sync/marker frame to align the two streams. That
would be a manipulation of the transmitted data, which is the one thing this
whole exercise exists to rule out. Alignment is by content instead.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
from collections import deque
from typing import Iterable, Optional

from .logstore import FrameStore

#: Frames kept for the live preview. Small on purpose — at 1 870 fps the UI can
#: only ever show a decimated view, so the ring is for "what just went out",
#: while the full-session record (opt-in) is what the byte diff runs on.
RING = 2000

#: How far ahead of the cursor an aligner will look for the next matching frame
#: before calling it a divergence. A TCU legitimately drops frames (it forwards
#: a subset), so the window must be generous; but unbounded search would make a
#: single corrupt frame look like total loss.
ALIGN_WINDOW = 2000


class TxRecorder:
    """Tap on the TX path: records exactly what was handed to the adapter.

    Installed on :class:`~ucando.replay.TxEngine`, which funnels every frame —
    playlist, patched, single-stepped — through one place.
    """

    def __init__(self, ring: int = RING, clock=time.perf_counter):
        # ``clock`` must be the clock the TX tap stamps frames with (TxEngine passes
        # time.perf_counter()), so an ID's age is "now minus when it last went out".
        self._clock = clock
        self._lock = threading.Lock()
        self._ring: deque = deque(maxlen=ring)
        self._ids: dict[tuple[int, bool], dict] = {}
        self._store: Optional[FrameStore] = None       # full session, opt-in
        self._recording = False
        self._count = 0
        self._t0: Optional[float] = None

    # ----- hot path -------------------------------------------------------
    def consume(self, timestamp: float, frame_id: int, extended: bool, data: bytes) -> None:
        with self._lock:
            if self._t0 is None:
                self._t0 = timestamp
            rel = timestamp - self._t0
            self._count += 1
            self._ring.append((rel, frame_id, extended, data))
            key = (frame_id, extended)
            entry = self._ids.get(key)
            if entry is None:
                self._ids[key] = {"id": frame_id, "extended": extended, "count": 1,
                                  "dlc": len(data), "data": data, "first_s": rel,
                                  "last_s": rel}
            else:
                entry["count"] += 1
                entry["dlc"] = len(data)
                entry["data"] = data
                entry["last_s"] = rel
            if self._recording and self._store is not None:
                self._store.append(rel, frame_id, data, network="tx", extended=extended)

    # ----- control --------------------------------------------------------
    def start_recording(self) -> dict:
        with self._lock:
            self._store = FrameStore("<tx-session>", "tx")
            self._recording = True
        return self.status()

    def stop_recording(self) -> dict:
        with self._lock:
            self._recording = False
        return self.status()

    def reset(self) -> None:
        with self._lock:
            self._ring.clear()
            self._ids.clear()
            self._store = None
            self._recording = False
            self._count = 0
            self._t0 = None

    def store(self) -> Optional[FrameStore]:
        with self._lock:
            return self._store

    # ----- reads ----------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {"frames": self._count, "unique_ids": len(self._ids),
                    "recording": self._recording,
                    "recorded": len(self._store) if self._store is not None else 0}

    def ids(self) -> list[dict]:
        """Latest payload per ID — the decimated view the UI can actually render.

        ``age_s`` is how long ago the ID last went out and ``period_ms`` its mean
        interval, so a view can say "stopped" by the ID's *own* rhythm (a 1 s
        message is not late after 300 ms) — and goes stale honestly when playback
        pauses or a scenario silences the bus, which is what the device sees too.
        """
        now = self._clock()
        with self._lock:
            t0 = self._t0 or 0.0
            rows = [{"id": e["id"], "id_hex": f"{e['id']:X}", "extended": e["extended"],
                     "count": e["count"], "dlc": e["dlc"],
                     "data": e["data"].hex().upper(), "last_s": round(e["last_s"], 3),
                     "age_s": round(max(0.0, now - (t0 + e["last_s"])), 3),
                     "period_ms": (round((e["last_s"] - e["first_s"]) / (e["count"] - 1) * 1000, 1)
                                   if e["count"] > 1 else None)}
                    for e in self._ids.values()]
        rows.sort(key=lambda r: r["id"])
        return rows

    def recent(self, limit: int = 200, frame_id: Optional[int] = None) -> list[dict]:
        with self._lock:
            items = list(self._ring)
        if frame_id is not None:
            items = [f for f in items if f[1] == frame_id]
        return [{"t": round(t, 4), "id": fid, "id_hex": f"{fid:X}", "extended": ext,
                 "dlc": len(data), "data": data.hex().upper()}
                for t, fid, ext, data in items[-limit:]]


# ---------------------------------------------------------------------------
# Cloud-side log import
# ---------------------------------------------------------------------------
_HEX = re.compile(r"^[0-9A-Fa-f]+$")
#: A raw-frame line in a plain text dump: an optional timestamp, an ID, then
#: payload bytes. Deliberately permissive — cloud exports vary per platform, and
#: this is easier to extend than to guess right first time.
_TEXT_LINE = re.compile(
    r"^\s*(?:(?P<t>\d+(?:\.\d+)?)\s+)?(?:0x)?(?P<id>[0-9A-Fa-f]{1,8})\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}[\s,:-]*){0,64})\s*$")

_ID_KEYS = ("id", "canid", "can_id", "arbitration_id", "arbid", "frameid", "frame_id", "pgn", "msgid")
_DATA_KEYS = ("data", "payload", "bytes", "hex", "raw", "databytes", "data_hex")
_TIME_KEYS = ("t", "time", "timestamp", "ts", "epoch", "recvtime", "received_at")


def _norm_hex(text: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", text or "").upper()


def _coerce_id(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except ValueError:
        pass
    return int(s, 16) if _HEX.fullmatch(s) else None


def _from_mapping(row: dict) -> Optional[dict]:
    """Pull (timestamp, id, data) out of one dict/CSV row, whatever it calls them."""
    low = {str(k).strip().lower().replace(" ", "").replace("-", "_"): v for k, v in row.items()}
    fid = next((_coerce_id(low[k]) for k in _ID_KEYS if k in low and low[k] not in (None, "")), None)
    raw = next((low[k] for k in _DATA_KEYS if k in low and low[k] not in (None, "")), None)
    if fid is None or raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        try:
            data = bytes(int(b) & 0xFF for b in raw)
        except (TypeError, ValueError):
            return None
    else:
        hexs = _norm_hex(str(raw))
        if len(hexs) % 2:
            return None
        data = bytes.fromhex(hexs)
    ts = next((low[k] for k in _TIME_KEYS if k in low and low[k] not in (None, "")), None)
    try:
        timestamp = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        timestamp = None
    return {"t": timestamp, "id": fid, "data": data}


def parse_cloud_log(text: str) -> dict:
    """Read a cloud-side raw-frame export into ``[{t, id, data}]``.

    Tries, in order: JSON (object or array, nested one level), JSON-lines, CSV
    with a header, then permissive plain text. Returns the frames plus the
    dialect used, so a wrong guess is visible in the report rather than silently
    producing an empty diff.
    """
    text = text.lstrip("﻿")
    if not text.strip():
        raise ValueError("cloud log is empty")

    # --- JSON / JSON-lines --------------------------------------------------
    stripped = text.lstrip()
    if stripped[:1] in "[{":
        try:
            data = json.loads(text)
            frames = _walk_json(data)
            if frames:
                return {"frames": frames, "dialect": "json"}
        except json.JSONDecodeError:
            pass
    if stripped[:1] == "{":
        frames = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                got = _from_mapping(json.loads(line))
            except json.JSONDecodeError:
                got = None
            if got:
                frames.append(got)
        if frames:
            return {"frames": frames, "dialect": "json-lines"}

    # --- CSV with a header --------------------------------------------------
    head = text.splitlines()[0]
    if "," in head or "\t" in head or ";" in head:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = None
        reader = csv.DictReader(io.StringIO(text), dialect=dialect) if dialect \
            else csv.DictReader(io.StringIO(text))
        frames = [f for f in (_from_mapping(r) for r in reader if r) if f]
        if frames:
            return {"frames": frames, "dialect": "csv"}

    # --- permissive plain text --------------------------------------------
    frames = []
    for line in text.splitlines():
        m = _TEXT_LINE.match(line)
        if not m:
            continue
        hexs = _norm_hex(m.group("data"))
        if not hexs or len(hexs) % 2:
            continue
        frames.append({"t": float(m.group("t")) if m.group("t") else None,
                       "id": int(m.group("id"), 16), "data": bytes.fromhex(hexs)})
    if frames:
        return {"frames": frames, "dialect": "text"}

    raise ValueError("could not find raw CAN frames — tried JSON, JSON-lines, CSV "
                     "and plain text. Needs an ID column and a payload column "
                     f"(ID: any of {', '.join(_ID_KEYS[:4])}…; "
                     f"payload: any of {', '.join(_DATA_KEYS[:4])}…)")


def _walk_json(data, depth: int = 0) -> list[dict]:
    """Find the frame list in a JSON document, one nesting level down."""
    if isinstance(data, list):
        out = [f for f in (_from_mapping(d) for d in data if isinstance(d, dict)) if f]
        if out:
            return out
        if depth < 2:
            for item in data:
                got = _walk_json(item, depth + 1)
                if got:
                    return got
        return []
    if isinstance(data, dict):
        one = _from_mapping(data)
        if one:
            return [one]
        if depth < 2:
            for value in data.values():
                got = _walk_json(value, depth + 1)
                if got:
                    return got
    return []


# ---------------------------------------------------------------------------
# B vs C
# ---------------------------------------------------------------------------
def compare(tx_store: Optional[FrameStore], cloud_frames: Iterable[dict],
            *, patched: Optional[list] = None, filtered: Optional[dict] = None,
            align_window: int = ALIGN_WINDOW) -> dict:
    """Byte-for-byte diff of what we transmitted against what the cloud reported.

    The headline number is **unknown payloads**: a payload the cloud reported for
    an ID that we never transmitted for that ID. That is the only outcome which
    means corruption (or another node talking) — everything else is loss, which a
    TCU does legitimately because it forwards a subset of the bus.

    Per ID we also walk the cloud sequence forward against ours, so the report
    can point at the *first* frame that diverged rather than only a rate.
    """
    if tx_store is None or not len(tx_store):
        raise ValueError("no transmitted frames recorded — start TX recording, "
                         "then replay, then compare")

    tx_by_id: dict[int, list[bytes]] = {}
    for i in range(len(tx_store)):
        tx_by_id.setdefault(int(tx_store.ids[i]), []).append(tx_store.payload(i))

    cloud_by_id: dict[int, list[bytes]] = {}
    cloud_total = 0
    for frame in cloud_frames:
        cloud_by_id.setdefault(int(frame["id"]), []).append(bytes(frame["data"]))
        cloud_total += 1

    per_id, unknown_total, matched_total = [], 0, 0
    for fid in sorted(set(tx_by_id) | set(cloud_by_id)):
        ours, theirs = tx_by_id.get(fid, []), cloud_by_id.get(fid, [])
        our_set = set(ours)
        # "Unknown payload" means the bytes differ for an ID we DID send — the
        # unambiguous fidelity failure. An ID we never sent at all is a
        # different finding (another node on the bus, or the TCU generating it)
        # and is reported as `ids_only_at_cloud`, not as corruption.
        unknown = [p for p in theirs if p not in our_set] if ours else []
        matched, first_bad = _align(ours, theirs, align_window)
        unknown_total += len(unknown)
        matched_total += matched
        row = {
            "id": fid, "id_hex": f"{fid:X}",
            "tx": len(ours), "cloud": len(theirs),
            "matched": matched,
            "unknown": len(unknown),
            "distinct_tx": len(our_set), "distinct_cloud": len(set(theirs)),
            "delivery_pct": round(100.0 * len(theirs) / len(ours), 1) if ours else None,
            "verdict": _verdict(ours, theirs, unknown),
        }
        if unknown:
            # The evidence a firmware bug report needs: the exact bytes the cloud
            # claimed, which never left this machine.
            row["unknown_samples"] = [p.hex().upper() for p in unknown[:5]]
        if first_bad is not None:
            row["first_divergence"] = first_bad
        per_id.append(row)

    ok = unknown_total == 0
    extra_ids = sorted(set(cloud_by_id) - set(tx_by_id))
    warnings = []
    if extra_ids:
        # Not counted as a fidelity failure — on a bench bus another ECU may be
        # talking — but never hidden either, since a TCU inventing frames would
        # look exactly like this.
        warnings.append(f"{len(extra_ids)} ID(s) reached the cloud that we never "
                        f"transmitted: " +
                        ", ".join(f"0x{i:X}" for i in extra_ids[:8]) +
                        (" …" if len(extra_ids) > 8 else "") +
                        " — another node on the bus, or generated by the device")
    if patched:
        warnings.append(f"signal patching was active ({', '.join(patched)}) — this "
                        f"compares against what left the adapter, not the log file")
    return {
        "ok": ok,
        "verdict": "byte-identical" if ok else "MISMATCH — see unknown payloads",
        "warnings": warnings,
        "tx_frames": len(tx_store), "cloud_frames": cloud_total,
        "tx_ids": len(tx_by_id), "cloud_ids": len(cloud_by_id),
        "matched_frames": matched_total,
        "unknown_payloads": unknown_total,
        "ids_only_at_cloud": extra_ids,
        "ids_never_arrived": sorted(fid for fid in tx_by_id if fid not in cloud_by_id),
        "per_id": per_id,
        # Stated, never implied: a byte-fidelity claim is void if we rewrote
        # signals on the way out, and "missing IDs" is meaningless if we filtered
        # them ourselves.
        "patched_signals": patched or [],
        "patching_active": bool(patched),
        "tx_filters": filtered or {},
    }


def _align(ours: list[bytes], theirs: list[bytes], window: int) -> tuple[int, Optional[dict]]:
    """Walk the cloud sequence forward through ours; report the first mismatch.

    A TCU forwards a subset, so gaps are normal: we skip ahead to the next match
    within *window*. Only a payload that appears nowhere ahead is a divergence.
    """
    cursor = matched = 0
    for pos, payload in enumerate(theirs):
        limit = min(len(ours), cursor + window)
        found = -1
        for j in range(cursor, limit):
            if ours[j] == payload:
                found = j
                break
        if found < 0:
            return matched, {"cloud_index": pos, "cloud_data": payload.hex().upper(),
                             "expected_near": [p.hex().upper()
                                               for p in ours[cursor:cursor + 3]]}
        matched += 1
        cursor = found + 1
    return matched, None


def _verdict(ours: list[bytes], theirs: list[bytes], unknown: list[bytes]) -> str:
    # Order matters: an ID we never transmitted must not read as "corrupt", or a
    # second ECU on the bench bus looks like a corruption bug.
    if not ours:
        return "unexpected id"           # arrived at the cloud but we never sent it
    if not theirs:
        return "not forwarded"           # TCU filters this ID, or never saw it
    if unknown:
        return "corrupt"                 # we sent this ID, but with different bytes
    if len(theirs) < len(ours):
        return "sampled"                 # subset, but every payload was ours
    return "complete"
