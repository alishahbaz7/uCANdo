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
import math


def _fmt_physical(val: float, scale) -> str:
    """Format a physical value using the signal's scale to determine decimal places (max 2)."""
    try:
        s = abs(float(scale)) if scale else 1.0
        if s == 0 or s >= 1:
            decimals = 0
        else:
            decimals = min(2, -int(math.floor(math.log10(s))))
    except (ValueError, TypeError, OverflowError):
        decimals = 2
    return f"{float(val):.{decimals}f}"


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
    # decode_choices=False so phys is always numeric (we handle labels separately)
    phys = db.decode_message(frame_id, b, decode_choices=False, allow_truncated=True)
    raw  = db.decode_message(frame_id, b, decode_choices=False, scaling=False, allow_truncated=True)

    signals = []
    for s in m.signals:
        if s.name not in phys:
            continue
        pv = phys[s.name]           # numeric physical value
        rv = raw.get(s.name)        # raw integer value

        # DBC value description (VAL_ table): e.g. {1: "P", 2: "R", 3: "N", 4: "D"}
        choice: str | None = None
        if s.choices and rv is not None:
            try:
                choice = s.choices.get(int(rv))
                if choice is not None:
                    choice = str(choice)
            except (ValueError, TypeError):
                pass

        # Format: scale-aware decimal places, capped at 2
        phys_str = _fmt_physical(pv, s.scale) if isinstance(pv, (int, float)) else str(pv)
        phys_f = float(pv) if isinstance(pv, (int, float)) else None

        out_of_range = (
            phys_f is not None
            and (
                (s.minimum is not None and phys_f < float(s.minimum))
                or (s.maximum is not None and phys_f > float(s.maximum))
            )
        )
        signals.append({
            "name": s.name,
            "raw": rv,
            "physical": phys_str,
            "choice": choice,           # DBC value description label, or null
            "unit": s.unit or "",
            "min": float(s.minimum) if s.minimum is not None else None,
            "max": float(s.maximum) if s.maximum is not None else None,
            "out_of_range": out_of_range,
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
