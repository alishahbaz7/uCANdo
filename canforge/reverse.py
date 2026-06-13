"""Reverse Engineering — find signals inside an unknown CAN log.

Given a recorded log, this groups frames by arbitration ID and, for each ID,
measures how every bit and byte behaves over time:

* **bit activity** — how often each of the 64 payload bits toggles,
* **byte entropy** — Shannon entropy (0..8 bits) of each byte's value
  distribution, a quick "is this constant / counter / noisy" indicator,
* **byte classification** — constant, counter (monotonic step), multi-state
  (few distinct values), or continuous (many values),
* **candidate signals** — contiguous runs of active bits coalesced into
  suggested signals, which the DBC Builder can import directly.

Pure-stdlib analysis (``math`` only); the only external read is
``can.LogReader`` for parsing the log.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

import can


def _entropy(counter: Counter, total: int) -> float:
    if total <= 1:
        return 0.0
    h = 0.0
    for c in counter.values():
        p = c / total
        h -= p * math.log2(p)
    return h


def _classify_byte(values: list[int]) -> str:
    distinct = len(set(values))
    if distinct == 1:
        return "constant"
    # Monotonic-ish wrapping counter: most consecutive deltas equal a small step.
    deltas = [(values[i] - values[i - 1]) % 256 for i in range(1, len(values))]
    if deltas:
        common_delta, freq = Counter(deltas).most_common(1)[0]
        if 1 <= common_delta <= 4 and freq / len(deltas) > 0.8:
            return "counter"
    if distinct <= 8:
        return "multi-state"
    return "continuous"


def analyze_id(payloads: list[bytes]) -> dict:
    """Per-ID bit/byte analysis from the raw payload sequence."""
    n = len(payloads)
    max_len = max((len(p) for p in payloads), default=0)

    # Bit toggle counts across consecutive frames.
    bit_toggles = [0] * (max_len * 8)
    prev_bits = None
    for p in payloads:
        bits = []
        for bi in range(max_len):
            byte = p[bi] if bi < len(p) else 0
            for k in range(8):  # bit 0 = MSB of the byte (DBC big-endian convention)
                bits.append((byte >> (7 - k)) & 1)
        if prev_bits is not None:
            for i in range(len(bits)):
                if bits[i] != prev_bits[i]:
                    bit_toggles[i] += 1
        prev_bits = bits

    bytes_info = []
    for bi in range(max_len):
        col = [p[bi] for p in payloads if bi < len(p)]
        counter = Counter(col)
        bytes_info.append({
            "index": bi,
            "entropy": round(_entropy(counter, len(col)), 3),
            "distinct": len(counter),
            "min": min(col) if col else 0,
            "max": max(col) if col else 0,
            "kind": _classify_byte(col) if col else "constant",
        })

    # Coalesce active bits into candidate signals.
    active = [t > 0 for t in bit_toggles]
    candidates = []
    i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j < len(active) and active[j]:
                j += 1
            length = j - i
            candidates.append({
                "start_bit": i,
                "length": length,
                "name": f"sig_{i}_{length}",
                "byte_order": "big_endian",
                "toggle_rate": round(sum(bit_toggles[i:j]) / (length * max(1, n - 1)), 3),
            })
            i = j
        else:
            i += 1

    return {
        "frames": n,
        "length": max_len,
        "bit_toggles": bit_toggles,
        "bytes": bytes_info,
        "candidates": candidates,
    }


def analyze_log(path: str, max_frames_per_id: int = 20000) -> dict:
    """Group a log by arbitration ID and analyze each."""
    by_id: dict[tuple[int, bool], list[bytes]] = defaultdict(list)
    timestamps: dict[tuple[int, bool], list[float]] = defaultdict(list)

    with can.LogReader(path) as reader:
        for msg in reader:
            key = (msg.arbitration_id, bool(msg.is_extended_id))
            if len(by_id[key]) < max_frames_per_id:
                by_id[key].append(bytes(msg.data))
                timestamps[key].append(msg.timestamp)

    results = []
    for (arb_id, ext), payloads in by_id.items():
        ts = timestamps[(arb_id, ext)]
        period_ms = 0.0
        if len(ts) > 1:
            period_ms = (ts[-1] - ts[0]) / (len(ts) - 1) * 1000.0
        info = analyze_id(payloads)
        info.update({
            "id": arb_id,
            "id_hex": f"{arb_id:0{8 if ext else 3}X}",
            "ext": ext,
            "period_ms": round(period_ms, 2),
        })
        results.append(info)

    results.sort(key=lambda r: r["id"])
    return {
        "path": path,
        "id_count": len(results),
        "total_frames": sum(r["frames"] for r in results),
        "ids": results,
    }
