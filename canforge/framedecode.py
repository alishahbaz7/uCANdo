"""DBC frame decoder with byte/bit mapping (BusMaster-style view).

Decodes raw CAN frames against a loaded cantools database and returns, per
frame: the data bytes, each signal's **raw + physical value + unit**, and the
exact **(byte, bit) cells** each signal occupies — so the UI can render the 8×8
bit grid and highlight a signal's bits like BusMaster's "Configure Transmission
Messages" dialog.

The bit cells are computed robustly via cantools' own packer (encode the signal
as all-ones with every other signal at zero, then read back which bits are set),
so it's correct for both Intel (LE) and Motorola (BE) layouts without hand-rolling
the sawtooth bit math.
"""

from __future__ import annotations


def _normalize(data_hex: str, dlc: int) -> bytes:
    """Hex string → exactly ``dlc`` bytes (tolerant of lost leading zeros/spaces)."""
    h = data_hex.strip().replace(" ", "").replace("0x", "")
    if len(h) % 2:
        h = "0" + h
    if len(h) < dlc * 2:
        h = h.zfill(dlc * 2)           # restore dropped leading zeros
    return bytes.fromhex(h)[:dlc]


def signal_cells(message, sig) -> list[list[int]]:
    """Return ``[[byte, bit0..7], ...]`` cells this signal occupies (bit 0 = LSB)."""
    try:
        vals = {s.name: s.offset for s in message.signals}     # every signal at raw 0
        vals[sig.name] = ((1 << sig.length) - 1) * sig.scale + sig.offset  # this one all-ones
        # padding=False so only this signal's bits are set (no unused-bit fill).
        enc = message.encode(vals, strict=False, padding=False)
    except Exception:
        return []
    cells = []
    for bi, byte in enumerate(enc):
        for bit in range(8):
            if byte & (1 << bit):
                cells.append([bi, bit])
    return cells


def decode_frame(db, frame_id: int, data_hex: str) -> dict:
    """Decode one frame; returns message info, bytes, and per-signal detail+cells."""
    m = db.get_message_by_frame_id(frame_id)
    b = _normalize(data_hex, m.length)
    phys = db.decode_message(frame_id, b, decode_choices=True, allow_truncated=True)
    raw = db.decode_message(frame_id, b, decode_choices=False, scaling=False, allow_truncated=True)

    signals = []
    for s in m.signals:
        if s.name not in phys:
            continue
        signals.append({
            "name": s.name,
            "raw": raw.get(s.name),
            "physical": str(phys[s.name]),       # str so enum/choice labels survive
            "unit": s.unit or "",
            "start_bit": s.start, "length": s.length, "byte_order": s.byte_order,
            "cells": signal_cells(m, s),
        })
    return {
        "id": frame_id, "id_hex": f"{frame_id:X}", "name": m.name, "length": m.length,
        "bytes": [b[i] if i < len(b) else 0 for i in range(m.length)],
        "signals": signals,
    }


def decode_frames(db, frames: list[dict]) -> list[dict]:
    """Decode a list of ``{"id": <hex or int>, "data": <hex>}`` frames."""
    out = []
    for fr in frames:
        rid = fr.get("id")
        fid = int(str(rid), 16) if not isinstance(rid, int) else rid
        try:
            out.append(decode_frame(db, fid, str(fr.get("data", ""))))
        except Exception as exc:
            out.append({"id_hex": f"{fid:X}", "error": str(exc)})
    return out
