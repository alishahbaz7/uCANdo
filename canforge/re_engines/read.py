"""READ — Bit-flip-rate reverse-engineering engine.

An implementation of the ideas in *READ: Reverse Engineering of Automotive
Dataframes* (Marchetti & Stabili, 2019), adapted to CANForge's data shapes.

The core signal is the **Bit-Flip Rate (BFR)**: for each payload bit, the
fraction of consecutive frame pairs in which the bit changed. Within a single
multi-bit value the least-significant bit flips most often and the rate falls
toward the most-significant bit; a *new* signal begins where the rate drops
back down (its MSB). That gives us signal boundaries far better than the naive
"contiguous toggling bits" heuristic in :mod:`canforge.reverse`.

Each extracted span is then classified and its endianness inferred:

* **constant** — never changes,
* **counter** — reconstructed value increments by a small fixed step (mod 2^n),
* **crc** — a near-full byte flipping at ~0.5 with high entropy and no structure,
* **multi-state** — only a handful of distinct values (likely an enum/flag),
* **physical** — a smoothly-varying analog quantity.

Bit indexing matches the rest of the app: **bit 0 = byte0/bit7 (MSB-first,
sequential)**, so contiguous bits form a big-endian integer naturally and
:func:`canforge.dbc_builder.re_candidate_to_signal` converts cleanly.

Pure stdlib (``math`` + ``collections``); no bus, no I/O — fully unit-testable.
"""

from __future__ import annotations

import math
from collections import Counter

EPS = 0.005          # BFR below this == bit considered constant
DROP = 0.12          # absolute BFR drop that marks a new-signal boundary
DROP_RATIO = 0.6     # ... and the drop must be at least this fraction


# ---------------------------------------------------------------------------
# Bit / value primitives
# ---------------------------------------------------------------------------
def _bit(payload: bytes, i: int) -> int:
    """Bit ``i`` in MSB-first sequential order (0 = byte0/bit7)."""
    byte = payload[i // 8] if (i // 8) < len(payload) else 0
    return (byte >> (7 - (i % 8))) & 1


def bit_flip_rates(payloads: list[bytes], nbits: int) -> list[float]:
    """Fraction of consecutive frame pairs in which each bit toggled."""
    if len(payloads) < 2:
        return [0.0] * nbits
    flips = [0] * nbits
    prev = [_bit(payloads[0], i) for i in range(nbits)]
    for p in payloads[1:]:
        for i in range(nbits):
            b = _bit(p, i)
            if b != prev[i]:
                flips[i] += 1
                prev[i] = b
    pairs = len(payloads) - 1
    return [f / pairs for f in flips]


def value_be(payload: bytes, start: int, length: int) -> int:
    """Big-endian integer from contiguous MSB-first bits."""
    v = 0
    for i in range(start, start + length):
        v = (v << 1) | _bit(payload, i)
    return v


def value_le(payload: bytes, start: int, length: int) -> int:
    """Little-endian integer over whole bytes (caller ensures byte alignment)."""
    nbytes = length // 8
    b0 = start // 8
    v = 0
    for k in range(nbytes):
        byte = payload[b0 + k] if (b0 + k) < len(payload) else 0
        v |= byte << (8 * k)
    return v


def _entropy(values) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    counter = Counter(values)
    h = 0.0
    for c in counter.values():
        p = c / n
        h -= p * math.log2(p)
    return h


# ---------------------------------------------------------------------------
# Boundary detection & classification
# ---------------------------------------------------------------------------
def extract_spans(bfr: list[float]) -> list[tuple[int, int]]:
    """Split the bit array into ``(start, length)`` spans at signal boundaries.

    A boundary falls between bit ``i-1`` and ``i`` when activity turns on/off, or
    when the BFR drops sharply (the LSB of one signal abutting the MSB of the
    next). Within a signal BFR is roughly non-decreasing toward the LSB, so only
    *drops* cut.
    """
    n = len(bfr)
    if n == 0:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    for i in range(1, n):
        prev_active = bfr[i - 1] > EPS
        cur_active = bfr[i] > EPS
        cut = False
        if cur_active != prev_active:
            cut = True
        elif cur_active and prev_active:
            drop = bfr[i - 1] - bfr[i]
            if drop > DROP and bfr[i] < bfr[i - 1] * DROP_RATIO:
                cut = True
        if cut:
            spans.append((start, i - start))
            start = i
    spans.append((start, n - start))
    return spans


def _counter_step(values: list[int], length: int):
    """If ``values`` look like a wrapping counter, return its step, else None."""
    if len(values) < 3:
        return None
    mod = 1 << length
    deltas = [(values[i] - values[i - 1]) % mod for i in range(1, len(values))]
    common, freq = Counter(deltas).most_common(1)[0]
    if 1 <= common <= 8 and freq / len(deltas) > 0.8:
        return common
    return None


def _smoothness(values: list[int], length: int) -> float:
    """Mean absolute wrap-aware delta, normalized to [0,1]. Lower = smoother."""
    mod = 1 << length
    if len(values) < 2 or mod <= 1:
        return 1.0
    total = 0.0
    for i in range(1, len(values)):
        d = (values[i] - values[i - 1]) % mod
        if d > mod // 2:
            d -= mod
        total += abs(d)
    return total / (len(values) - 1) / mod


def classify_span(payloads: list[bytes], start: int, length: int,
                  bfr: list[float]) -> dict:
    """Classify one span; infer endianness; return a candidate-signal dict."""
    span_bfr = bfr[start:start + length]
    mean_bfr = sum(span_bfr) / length if length else 0.0
    byte_aligned = (start % 8 == 0) and (length % 8 == 0) and length >= 8

    be_vals = [value_be(p, start, length) for p in payloads]
    order = "big_endian"
    values = be_vals
    kind = "physical"
    step = None
    confidence = 0.5

    if max(span_bfr, default=0.0) <= EPS:
        kind = "constant"
        confidence = 0.99
    else:
        # Counter? Try big-endian, then little-endian (byte-aligned only).
        step = _counter_step(be_vals, length)
        if step is None and byte_aligned:
            le_vals = [value_le(p, start, length) for p in payloads]
            le_step = _counter_step(le_vals, length)
            if le_step is not None:
                order, values, step = "little_endian", le_vals, le_step
        if step is not None:
            kind, confidence = "counter", 0.9
        else:
            # Endianness by smoothness for multi-byte spans.
            if byte_aligned:
                le_vals = [value_le(p, start, length) for p in payloads]
                if _smoothness(le_vals, length) < _smoothness(be_vals, length):
                    order, values = "little_endian", le_vals
            distinct = len(set(values))
            if length >= 7 and 0.35 <= mean_bfr <= 0.65 and distinct > len(values) * 0.5:
                kind, confidence = "crc", 0.7
            elif distinct <= 8:
                kind, confidence = "multi-state", 0.7
            else:
                kind, confidence = "physical", 0.6

    cand = {
        "start_bit": start,
        "length": length,
        "name": f"{kind}_{start}_{length}",
        "byte_order": order,
        "kind": kind,
        "bfr": round(mean_bfr, 3),
        "confidence": round(confidence, 2),
    }
    if step is not None:
        cand["step"] = step
    return cand


def detect_multiplexor(payloads: list[bytes], nbytes: int) -> dict | None:
    """Heuristic mux-selector detection.

    A multiplexor selector is a low-cardinality byte such that *which other
    bytes vary* depends on its value. We pick the byte with 2..16 distinct
    values that best partitions the rest of the payload into value-dependent
    active sets.
    """
    if len(payloads) < 8 or nbytes == 0:
        return None
    best = None
    for sel in range(nbytes):
        sel_vals = [p[sel] if sel < len(p) else 0 for p in payloads]
        distinct = sorted(set(sel_vals))
        if not (2 <= len(distinct) <= 16):
            continue
        # Active byte-set per selector value.
        active_by_val: dict[int, set] = {}
        groups: dict[int, list[bytes]] = {}
        for v, p in zip(sel_vals, payloads):
            groups.setdefault(v, []).append(p)
        for v, ps in groups.items():
            if len(ps) < 2:
                continue
            active = set()
            for bi in range(nbytes):
                if bi == sel:
                    continue
                col = [p[bi] if bi < len(p) else 0 for p in ps]
                if len(set(col)) > 1:
                    active.add(bi)
            active_by_val[v] = active
        if len(active_by_val) < 2:
            continue
        # Score: how differently each value lights up the payload.
        union = set().union(*active_by_val.values()) if active_by_val else set()
        inter = set.intersection(*active_by_val.values()) if active_by_val else set()
        divergence = len(union) - len(inter)
        if divergence >= 1 and (best is None or divergence > best["divergence"]):
            best = {"selector_byte": sel, "values": distinct,
                    "divergence": divergence,
                    "active_by_value": {str(v): sorted(a) for v, a in active_by_val.items()}}
    return best


def analyze_id_read(payloads: list[bytes]) -> dict:
    """Per-ID READ analysis. Output is a superset of ``reverse.analyze_id``."""
    n = len(payloads)
    max_len = max((len(p) for p in payloads), default=0)
    nbits = max_len * 8

    bfr = bit_flip_rates(payloads, nbits)

    # Per-byte info (keeps the keys web/app.js reads: index, kind, entropy).
    bytes_info = []
    for bi in range(max_len):
        col = [p[bi] for p in payloads if bi < len(p)]
        counter = Counter(col)
        byte_bfr = bfr[bi * 8:bi * 8 + 8]
        bytes_info.append({
            "index": bi,
            "entropy": round(_entropy(col), 3),
            "distinct": len(counter),
            "min": min(col) if col else 0,
            "max": max(col) if col else 0,
            "bfr": round(sum(byte_bfr) / 8, 3) if byte_bfr else 0.0,
            "kind": _byte_kind(col, byte_bfr),
        })

    candidates = []
    for start, length in extract_spans(bfr):
        if max(bfr[start:start + length], default=0.0) <= EPS:
            continue  # skip constant spans as signals (still shown via bytes_info)
        candidates.append(classify_span(payloads, start, length, bfr))

    result = {
        "frames": n,
        "length": max_len,
        "bit_toggles": [round(r, 3) for r in bfr],   # now BFR (0..1), not raw counts
        "bytes": bytes_info,
        "candidates": candidates,
    }
    mux = detect_multiplexor(payloads, max_len)
    if mux:
        result["multiplexor"] = mux
    return result


def _byte_kind(col: list[int], byte_bfr: list[float]) -> str:
    if not col:
        return "constant"
    if len(set(col)) == 1:
        return "constant"
    mean = sum(byte_bfr) / len(byte_bfr) if byte_bfr else 0.0
    step = _counter_step(col, 8)
    if step is not None:
        return "counter"
    if 0.35 <= mean <= 0.65 and len(set(col)) > len(col) * 0.5:
        return "crc"
    if len(set(col)) <= 8:
        return "multi-state"
    return "continuous"


class ReadEngine:
    """RE engine adapter registered into ``RE_ENGINES`` as ``read``."""

    name = "read"

    def analyze(self, frames_by_id: dict, **opts) -> dict:
        results = []
        for (arb_id, ext), data in frames_by_id.items():
            payloads = data["payloads"]
            ts = data.get("timestamps", [])
            info = analyze_id_read(payloads)
            period_ms = 0.0
            if len(ts) > 1:
                period_ms = (ts[-1] - ts[0]) / (len(ts) - 1) * 1000.0
            info.update({
                "id": arb_id,
                "id_hex": f"{arb_id:0{8 if ext else 3}X}",
                "ext": ext,
                "period_ms": round(period_ms, 2),
            })
            results.append(info)
        results.sort(key=lambda r: r["id"])
        return {
            "engine": "read",
            "id_count": len(results),
            "total_frames": sum(r["frames"] for r in results),
            "ids": results,
        }
