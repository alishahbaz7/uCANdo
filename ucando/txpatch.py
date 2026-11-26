"""Patch signals into replayed frames — live overrides and loop-seam continuity.

Two things a recorded log cannot do on its own, both needed to test a telematics
unit on a bench:

**Live overrides.** "Show me what the TCU does at 8 % battery" should not mean
driving a car flat and re-capturing. Replay the real drive as background traffic
and force one signal to a value while it plays.

**Loop-seam continuity.** A recorded drive is finite; a soak test is not. Looping
a log naively snaps the odometer backwards (the MG Windsor capture ends at
3075 km and restarts at 3066), resets state of charge, and breaks rolling
counters mid-stream — so a receiver that sanity-checks any of those sees a
vehicle that teleported. :class:`FramePatcher` continues monotonic signals across
the seam, regenerates counters from a running total, and recomputes checksums.

Why raw bit patching, not cantools encode
-----------------------------------------
The obvious implementation is ``decode_message`` → change one key →
``encode_message``. It is wrong here on both counts: it **zeroes every bit the
DBC does not describe** (real payloads carry unmapped bits, and a partially
reverse-engineered DBC describes only some of them), and it costs a few hundred
microseconds when the budget is 535 µs *per frame*. So a patch writes only its
own signal's bits and leaves the captured payload byte-exact everywhere else.
The bit math is verified against cantools as the oracle in the tests.

Frames with nothing to patch cost one dict lookup and are returned untouched.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

#: Signals whose *name* suggests a true accumulator — something that should keep
#: climbing forever, not merely something that happened to rise during one
#: capture. Used only to rank :func:`analyze` candidates: a battery temperature
#: that drifted up over 41 s is monotonic in the data but must NOT accumulate
#: across a loop, and only the operator can make that call.
_ACCUMULATOR_HINTS = ("odo", "odometer", "distance", "mileage", "trip", "total",
                      "energy", "kwh", "charge_count", "runtime", "hours",
                      "uptime", "cycles", "consumed", "regen")

#: Checksum algorithms we can regenerate. A vehicle's real algorithm is usually
#: proprietary — guessing one silently would be worse than leaving the captured
#: byte alone, so ``none`` is the default and the others are opt-in.
CHECKSUMS = ("none", "sum8", "xor8")


# ---------------------------------------------------------------------------
# bit packing
# ---------------------------------------------------------------------------
def cantools_start_to_msb_seq(start: int) -> int:
    """Motorola start bit -> sequential MSB-first index (self-inverse).

    Same conversion `dbc_builder.re_candidate_to_signal` and `jsondecode` use:
    within a byte the DBC counts bit 7 as the MSB, while sequential numbering
    counts bit 0 = byte 0's MSB.
    """
    return (start // 8) * 8 + (7 - start % 8)


def pack_signal(data: bytearray, start: int, length: int, big_endian: bool,
                raw: int) -> None:
    """Write *raw* into *data* in place, touching only this signal's bits."""
    total = len(data) * 8
    mask = (1 << length) - 1
    raw &= mask
    if big_endian:
        # Sequential MSB-first: the signal's MSB sits at bit `seq` counting from
        # the payload's most significant bit.
        seq = cantools_start_to_msb_seq(start)
        shift = total - (seq + length)
        if shift < 0:
            raise ValueError("signal runs past the end of the payload")
        acc = int.from_bytes(data, "big")
        acc = (acc & ~(mask << shift)) | (raw << shift)
        data[:] = acc.to_bytes(len(data), "big")
    else:
        # Intel: `start` is the LSB position in LSB-first sequential numbering.
        if start + length > total:
            raise ValueError("signal runs past the end of the payload")
        acc = int.from_bytes(data, "little")
        acc = (acc & ~(mask << start)) | (raw << start)
        data[:] = acc.to_bytes(len(data), "little")


def unpack_signal(data: bytes, start: int, length: int, big_endian: bool,
                  signed: bool) -> int:
    """Read a signal's raw integer back out — the inverse of :func:`pack_signal`."""
    total = len(data) * 8
    mask = (1 << length) - 1
    if big_endian:
        seq = cantools_start_to_msb_seq(start)
        shift = total - (seq + length)
        raw = (int.from_bytes(data, "big") >> shift) & mask
    else:
        raw = (int.from_bytes(data, "little") >> start) & mask
    if signed and raw >= (1 << (length - 1)):
        raw -= 1 << length
    return raw


def _scale_offset(sig) -> tuple[float, float]:
    """cantools 41.x moved scale/offset onto a `conversion` object."""
    conv = getattr(sig, "conversion", None)
    scale = getattr(conv, "scale", None) if conv is not None else None
    offset = getattr(conv, "offset", None) if conv is not None else None
    if scale is None:
        scale = getattr(sig, "scale", 1) or 1
    if offset is None:
        offset = getattr(sig, "offset", 0) or 0
    return float(scale), float(offset)


class Field:
    """One signal's fixed bit layout + conversion, resolved once at setup."""

    __slots__ = ("message", "name", "start", "length", "big_endian", "signed",
                 "scale", "offset", "minimum", "maximum", "unit")

    def __init__(self, msg, sig):
        self.message = msg.name
        self.name = sig.name
        self.start = sig.start
        self.length = sig.length
        self.big_endian = sig.byte_order == "big_endian"
        self.signed = bool(sig.is_signed)
        self.scale, self.offset = _scale_offset(sig)
        self.minimum, self.maximum = sig.minimum, sig.maximum
        self.unit = sig.unit or ""

    def to_raw(self, physical: float) -> int:
        raw = int(round((float(physical) - self.offset) / self.scale))
        lim = 1 << self.length
        if self.signed:
            raw = max(-(lim >> 1), min((lim >> 1) - 1, raw))
        else:
            raw = max(0, min(lim - 1, raw))
        return raw

    def to_physical(self, raw: int) -> float:
        return raw * self.scale + self.offset

    def read(self, data: bytes) -> float:
        return self.to_physical(unpack_signal(data, self.start, self.length,
                                              self.big_endian, self.signed))

    def write(self, data: bytearray, physical: float) -> None:
        pack_signal(data, self.start, self.length, self.big_endian,
                    self.to_raw(physical))

    def info(self) -> dict:
        return {"message": self.message, "signal": self.name, "unit": self.unit,
                "length": self.length, "signed": self.signed,
                "byte_order": "big_endian" if self.big_endian else "little_endian",
                "minimum": self.minimum, "maximum": self.maximum,
                "scale": self.scale, "offset": self.offset}


# ---------------------------------------------------------------------------
# the patcher
# ---------------------------------------------------------------------------
class _Rule:
    """What to do to one signal of one message on every frame."""
    __slots__ = ("field", "kind", "value", "base", "pending_rebase", "last_out",
                 "count", "wrap")

    def __init__(self, field: Field, kind: str, value: Any = None):
        self.field = field
        self.kind = kind                 # set | monotonic | counter
        self.value = value
        self.base = 0.0                  # monotonic: added to the captured value
        self.pending_rebase = False
        self.last_out: Optional[float] = None
        self.count = 0                   # counter: frames of this message sent
        self.wrap = 1 << field.length


class FramePatcher:
    """Rewrites outgoing payloads. Installed on :class:`~ucando.replay.TxEngine`.

    Thread-safe: the UI mutates overrides from a request thread while the TX
    worker calls :meth:`patch` at line rate.
    """

    def __init__(self, db=None, name: str = ""):
        self._lock = threading.Lock()
        self.db = db
        self.name = name
        self._fields: dict[tuple[str, str], tuple[Any, Field]] = {}
        self._rules: dict[tuple[int, bool], list[_Rule]] = {}
        self._checksums: dict[tuple[int, bool], tuple[str, Field]] = {}
        self._patched = 0
        if db is not None:
            self._index(db)

    # ----- setup ----------------------------------------------------------
    def _index(self, db) -> None:
        for msg in db.messages:
            for sig in msg.signals:
                if sig.multiplexer_ids:
                    continue            # a multiplexed signal is only present in some frames
                try:
                    self._fields[(msg.name, sig.name)] = (msg, Field(msg, sig))
                except Exception:
                    continue

    def messages(self) -> list[dict]:
        """Message/signal tree for the override pickers."""
        out: dict[str, dict] = {}
        for (mname, sname), (msg, field) in self._fields.items():
            entry = out.setdefault(mname, {
                "message": mname, "id_hex": f"{msg.frame_id:X}",
                "extended": bool(msg.is_extended_frame), "signals": []})
            entry["signals"].append(field.info())
        for entry in out.values():
            entry["signals"].sort(key=lambda s: s["signal"])
        return sorted(out.values(), key=lambda m: m["message"])

    def _key(self, msg) -> tuple[int, bool]:
        return (msg.frame_id, bool(msg.is_extended_frame))

    def _add_rule(self, message: str, signal: str, kind: str, value=None) -> _Rule:
        found = self._fields.get((message, signal))
        if found is None:
            raise KeyError(f"{message}.{signal} is not in the loaded DBC")
        msg, field = found
        key = self._key(msg)
        rules = self._rules.setdefault(key, [])
        for existing in rules:
            if existing.field.name == signal:
                rules.remove(existing)
                break
        rule = _Rule(field, kind, value)
        if kind == "monotonic":
            rule.pending_rebase = False     # first pass plays as captured
        rules.append(rule)
        return rule

    # ----- public configuration -------------------------------------------
    def set_override(self, message: str, signal: str, value: float) -> dict:
        """Hold *signal* at *value* — takes effect on the next frame sent."""
        with self._lock:
            rule = self._add_rule(message, signal, "set", float(value))
            return {"message": message, "signal": signal, "kind": "set",
                    "value": rule.value, **rule.field.info()}

    def clear(self, message: str, signal: str) -> None:
        with self._lock:
            found = self._fields.get((message, signal))
            if not found:
                return
            key = self._key(found[0])
            self._rules[key] = [r for r in self._rules.get(key, [])
                                if r.field.name != signal]
            if not self._rules[key]:
                self._rules.pop(key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._rules.clear()
            self._checksums.clear()

    def set_monotonic(self, pairs: list[tuple[str, str]]) -> None:
        """Signals that must never step backwards across a loop seam."""
        with self._lock:
            for key, rules in list(self._rules.items()):
                self._rules[key] = [r for r in rules if r.kind != "monotonic"]
                if not self._rules[key]:
                    self._rules.pop(key)
            for message, signal in pairs:
                self._add_rule(message, signal, "monotonic")

    def set_counters(self, pairs: list[tuple[str, str]]) -> None:
        """Rolling counters to regenerate from a running total."""
        with self._lock:
            for key, rules in list(self._rules.items()):
                self._rules[key] = [r for r in rules if r.kind != "counter"]
                if not self._rules[key]:
                    self._rules.pop(key)
            for message, signal in pairs:
                self._add_rule(message, signal, "counter")

    def set_checksum(self, message: str, signal: str, algorithm: str) -> None:
        """Recompute *signal* after patching, using *algorithm*.

        Only whole-byte checksum fields are supported; a vehicle's real
        algorithm is usually proprietary, so this is opt-in and never guessed.
        """
        if algorithm not in CHECKSUMS:
            raise ValueError(f"unknown checksum algorithm {algorithm!r}")
        with self._lock:
            found = self._fields.get((message, signal))
            if found is None:
                raise KeyError(f"{message}.{signal} is not in the loaded DBC")
            msg, field = found
            if algorithm == "none":
                self._checksums.pop(self._key(msg), None)
                return
            # Byte-aligned means start-bit 7 of its byte for Motorola (the MSB)
            # and bit 0 for Intel (the LSB).
            aligned = field.start % 8 == (7 if field.big_endian else 0)
            if field.length != 8 or not aligned:
                raise ValueError(f"{message}.{signal} is not a whole byte — "
                                 f"only byte-aligned 8-bit checksums are supported")
            self._checksums[self._key(msg)] = (algorithm, field)

    def config(self) -> dict:
        with self._lock:
            rules = [{"message": r.field.message, "signal": r.field.name,
                      "kind": r.kind, "value": r.value, "unit": r.field.unit,
                      "last": None if r.last_out is None else round(r.last_out, 4)}
                     for rules in self._rules.values() for r in rules]
            checks = [{"message": f.message, "signal": f.name, "algorithm": algo}
                      for algo, f in self._checksums.values()]
        return {"dbc": self.name, "rules": sorted(rules, key=lambda r: (r["message"], r["signal"])),
                "checksums": checks, "patched": self._patched,
                "active": bool(rules or checks)}

    # ----- hot path -------------------------------------------------------
    def patch(self, frame_id: int, extended: bool, data: bytes) -> Optional[bytes]:
        """Return a rewritten payload, or ``None`` when nothing applies.

        One dict lookup for the overwhelming majority of frames.
        """
        key = (frame_id, extended)
        rules = self._rules.get(key)
        checksum = self._checksums.get(key)
        if not rules and not checksum:
            return None
        buf = bytearray(data)
        with self._lock:
            for rule in rules or ():
                field = rule.field
                if field.start // 8 >= len(buf):
                    continue                     # short-DLC frame: signal absent
                try:
                    if rule.kind == "set":
                        field.write(buf, rule.value)
                        rule.last_out = rule.value
                    elif rule.kind == "monotonic":
                        captured = field.read(buf)
                        if rule.pending_rebase:
                            rule.pending_rebase = False
                            # Only correct a *backward* step. A forward jump is
                            # not a monotonicity violation and is often real
                            # driving — a playlist of non-consecutive chunks
                            # legitimately skips kilometres, and flattening that
                            # would erase distance the vehicle actually covered.
                            if captured + rule.base < (rule.last_out or 0.0):
                                rule.base = rule.last_out - captured
                        out = captured + rule.base
                        field.write(buf, out)
                        rule.last_out = out
                    elif rule.kind == "counter":
                        out = rule.count % rule.wrap
                        rule.count += 1
                        field.write(buf, field.to_physical(out))
                        rule.last_out = out
                except (ValueError, OverflowError):
                    continue                     # never let a bad patch kill the replay
            if checksum:
                algo, field = checksum
                byte = field.start // 8
                if byte < len(buf):
                    others = [b for i, b in enumerate(buf) if i != byte]
                    buf[byte] = (sum(others) & 0xFF) if algo == "sum8" \
                        else _xor(others)
            self._patched += 1
        return bytes(buf)

    def on_rewind(self) -> None:
        """The timeline jumped back (loop or item repeat) — hold the seam.

        Monotonic signals re-anchor on their next frame; counters keep counting,
        which is exactly what makes them seamless.
        """
        with self._lock:
            for rules in self._rules.values():
                for rule in rules:
                    if rule.kind == "monotonic" and rule.last_out is not None:
                        rule.pending_rebase = True


def _xor(values) -> int:
    acc = 0
    for v in values:
        acc ^= v
    return acc


# ---------------------------------------------------------------------------
# candidate detection
# ---------------------------------------------------------------------------
def analyze(store, sel, db, max_frames_per_id: int = 4000) -> dict:
    """:func:`analyze_many` for a single (store, selection)."""
    return analyze_many([(store, sel)], db, max_frames_per_id)


def analyze_many(sources, db, max_frames_per_id: int = 4000) -> dict:
    """Find which DBC signals in a capture behave monotonically or as counters.

    Runs over the frames the plan will actually transmit, so it reports what is
    really in *these* logs rather than what the DBC hints at by name. Monotonic =
    never decreases and does increase (odometer, energy totals). Counter =
    small field that mostly steps by a constant and wraps.

    *sources* is a list of ``(store, indices)`` — plural because one chunk of a
    capture is not representative. In the real MG Windsor drive the odometer is
    **constant through the first 41 s file** (the car had not pulled away yet)
    and only varies in later chunks, so scanning the first file alone would
    report no odometer at all. Payloads are concatenated per CAN ID in playlist
    order, which is also chronological, so monotonicity is judged across the
    whole span rather than within one chunk.
    """
    by_id: dict[tuple[int, bool], list[bytes]] = {}
    for store, sel in sources:
        for i in sel:
            key = (int(store.ids[i]), bool(store.flags[i] & 0x01))
            bucket = by_id.setdefault(key, [])
            if len(bucket) < max_frames_per_id:
                bucket.append(store.payload(i))

    monotonic, counters = [], []
    for msg in db.messages:
        payloads = by_id.get((msg.frame_id, bool(msg.is_extended_frame)))
        if not payloads or len(payloads) < 8:
            continue
        for sig in msg.signals:
            if sig.multiplexer_ids:
                continue
            try:
                field = Field(msg, sig)
            except Exception:
                continue
            if (field.start // 8) >= min(len(p) for p in payloads):
                continue
            try:
                values = [field.read(p) for p in payloads]
            except (ValueError, OverflowError):
                continue
            if len(set(values)) < 2:
                continue                          # constant: nothing to continue
            deltas = [b - a for a, b in zip(values, values[1:])]
            entry = {"message": msg.name, "signal": sig.name, "unit": field.unit,
                     "length": field.length,
                     "first": round(values[0], 4), "last": round(values[-1], 4)}
            if all(d >= 0 for d in deltas):
                low = sig.name.lower()
                monotonic.append({**entry, "rise": round(values[-1] - values[0], 4),
                                  # A name hint only ranks the list; it never
                                  # selects anything. "Rose during this capture"
                                  # and "must accumulate forever" are different
                                  # claims, and only the operator knows which.
                                  "accumulator_hint": any(h in low for h in _ACCUMULATOR_HINTS)})
            elif field.length <= 8:
                # A rolling counter: steps up by a constant, with wraps as the
                # only negative deltas.
                ups = [d for d in deltas if d > 0]
                wraps = [d for d in deltas if d < 0]
                if ups and len(set(ups)) == 1 and wraps and \
                        len(wraps) <= len(deltas) // max(2, field.length):
                    counters.append({**entry, "step": ups[0], "wraps": len(wraps)})
    monotonic.sort(key=lambda e: (not e["accumulator_hint"], -abs(e["rise"])))
    counters.sort(key=lambda e: (e["message"], e["signal"]))
    return {"monotonic": monotonic, "counters": counters}
