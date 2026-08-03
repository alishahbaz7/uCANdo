"""State-change sniffer & capture diff (Pillar B).

Two related reverse-engineering aids:

* :func:`diff_frames` / :func:`compare_logs` — compare a *baseline* set of frames
  against an *after* set and report, per arbitration ID, which bits were constant
  before but changed afterwards. This is how you find the bit behind a physical
  action ("which bit toggled when I pressed unlock?").
* :class:`StateSniffer` — the live, guided version: arm it to record a baseline
  window, perform the action, ``mark()`` to record the after window, then read
  the diff. It consumes frames through the standard bus-tap interface, so it
  needs no second receive thread.

Bit indexing matches the rest of the app (bit 0 = byte0/bit7, MSB-first), so the
contiguous changed-bit spans it emits feed straight into the DBC Builder via
``re_candidate_to_signal``.
"""

from __future__ import annotations

import threading

MAX_PER_ID = 5000   # cap per-ID buffering so a long arm window can't grow unbounded


def _bit(payload: bytes, i: int) -> int:
    byte = payload[i // 8] if (i // 8) < len(payload) else 0
    return (byte >> (7 - (i % 8))) & 1


def _const_map(payloads: list[bytes], nbits: int) -> tuple[dict[int, int], set[int]]:
    """Return ``({bit: steady_value} for constant bits, {varying bits})``."""
    if not payloads:
        return {}, set()
    first = [_bit(payloads[0], i) for i in range(nbits)]
    varying: set[int] = set()
    for p in payloads[1:]:
        for i in range(nbits):
            if _bit(p, i) != first[i]:
                varying.add(i)
    const = {i: first[i] for i in range(nbits) if i not in varying}
    return const, varying


def _group_bits(bits: list[int]) -> list[tuple[int, int]]:
    """Coalesce sorted bit indices into contiguous ``(start, length)`` spans."""
    spans: list[tuple[int, int]] = []
    bits = sorted(bits)
    i = 0
    while i < len(bits):
        j = i
        while j + 1 < len(bits) and bits[j + 1] == bits[j] + 1:
            j += 1
        spans.append((bits[i], bits[j] - bits[i] + 1))
        i = j + 1
    return spans


def _diff_one(base: list[bytes], after: list[bytes]) -> dict:
    nbits = max((len(p) for p in base + after), default=0) * 8
    base_const, _ = _const_map(base, nbits)
    after_const, after_var = _const_map(after, nbits)

    changed_bits = []
    for i, val in base_const.items():
        if i in after_var:                                   # became active
            changed_bits.append(i)
        elif i in after_const and after_const[i] != val:     # flipped to new steady value
            changed_bits.append(i)

    changed_byte_idx = sorted({b // 8 for b in changed_bits})
    changed_bytes = []
    for bi in changed_byte_idx:
        base_vals = sorted({p[bi] for p in base if bi < len(p)})
        after_vals = sorted({p[bi] for p in after if bi < len(p)})
        changed_bytes.append({
            "index": bi,
            "baseline": [f"{v:02X}" for v in base_vals],
            "after": [f"{v:02X}" for v in after_vals],
        })

    candidates = [{
        "start_bit": s, "length": ln, "name": f"event_{s}_{ln}",
        "byte_order": "big_endian", "kind": "event",
    } for s, ln in _group_bits(changed_bits)]

    return {
        "changed_bits": changed_bits,
        "changed_bytes": changed_bytes,
        "candidates": candidates,
        "baseline_frames": len(base),
        "after_frames": len(after),
    }


def diff_frames(baseline: dict, after: dict) -> dict:
    """Diff two frames-by-id maps; report new/removed IDs and per-ID bit changes."""
    base_keys = set(baseline)
    after_keys = set(after)

    def _hex(key):
        arb, ext = key
        return f"{arb:0{8 if ext else 3}X}"

    changed = []
    for key in sorted(base_keys & after_keys, key=lambda k: k[0]):
        arb, ext = key
        d = _diff_one(baseline[key]["payloads"], after[key]["payloads"])
        if d["changed_bits"]:
            d.update({"id": arb, "id_hex": _hex(key), "ext": ext})
            changed.append(d)

    return {
        "new_ids": [_hex(k) for k in sorted(after_keys - base_keys, key=lambda k: k[0])],
        "removed_ids": [_hex(k) for k in sorted(base_keys - after_keys, key=lambda k: k[0])],
        "changed": changed,
        "changed_id_count": len(changed),
    }


def compare_logs(path_a: str, path_b: str) -> dict:
    """Compare two recorded logs (a == baseline, b == after)."""
    from ..reverse import load_log_frames
    return diff_frames(load_log_frames(path_a), load_log_frames(path_b))


class StateSniffer:
    """Live guided sniffer: baseline window → action → after window → diff."""

    def __init__(self):
        self._lock = threading.Lock()
        self._phase = "idle"            # idle | baseline | after
        self._buf = {"baseline": {}, "after": {}}

    def _store(self, bucket: dict, msg) -> None:
        key = (msg.arbitration_id, bool(msg.is_extended_id))
        slot = bucket.get(key)
        if slot is None:
            slot = {"payloads": [], "timestamps": []}
            bucket[key] = slot
        if len(slot["payloads"]) < MAX_PER_ID:
            slot["payloads"].append(bytes(msg.data))
            slot["timestamps"].append(msg.timestamp)

    # ----- live tap --------------------------------------------------------
    def consume(self, msg) -> None:
        with self._lock:
            if self._phase in ("baseline", "after"):
                self._store(self._buf[self._phase], msg)

    # ----- control ---------------------------------------------------------
    def arm(self) -> dict:
        with self._lock:
            self._buf = {"baseline": {}, "after": {}}
            self._phase = "baseline"
        return self.status()

    def mark(self) -> dict:
        with self._lock:
            if self._phase == "baseline":
                self._phase = "after"
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._phase = "idle"
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {
                "phase": self._phase,
                "baseline_ids": len(self._buf["baseline"]),
                "baseline_frames": sum(len(s["payloads"]) for s in self._buf["baseline"].values()),
                "after_ids": len(self._buf["after"]),
                "after_frames": sum(len(s["payloads"]) for s in self._buf["after"].values()),
            }

    def result(self) -> dict:
        with self._lock:
            base = {k: dict(v) for k, v in self._buf["baseline"].items()}
            after = {k: dict(v) for k, v in self._buf["after"].items()}
        return {**diff_frames(base, after), "status": self.status()}
