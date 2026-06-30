"""Decode raw CAN frames against a lightweight **Signature JSON** (cloud format).

The Signature JSON is a limited DBC alternative used for cloud visualization::

    {"900": [{"fieldName","reverse","startingBit","size",
              "multiplier","offset","signed","evData"}, ...], ...}

Bit/byte convention — **validated against the Ziptron DBC** (see
``docs/JSON_SIGNATURE_DECODE.md``):

* keys are CAN IDs in **decimal**;
* for **big-endian** (``reverse == 0``) ``startingBit`` is **MSB-first
  sequential**: bit 0 = byte0's MSB, bit 7 = byte0's LSB, bit 8 = byte1's MSB,
  … and the value is read MSB-first. This equals the DBC/cantools Motorola
  layout: cantools start = ``(startingBit//8)*8 + (7 - startingBit%8)``;
* for **little-endian** (``reverse == 1``) ``startingBit`` is LSB-first
  sequential (bit 0 = byte0's LSB) and the value is read LSB-first;
* a signal occupies ``size`` consecutive bits from ``startingBit``;
* ``signed == 1`` → two's complement over ``size`` bits;
* physical = ``raw * multiplier + offset``.

Ground truth (Ziptron DBC, message 0x244/580, frame ``5251 0047 C000 BA56``):
``DTeInfo=287`` (start 24, size 10) and ``HVBattSoCPercen=93`` (start 48, size 7)
— both reproduced exactly. byte-aligned ``canOdometer=75971`` also holds.

Self-contained (no cantools): the JSON carries no enums / min-max / units, so a
direct bit extractor reproduces the cloud/DBC values exactly. The output dict
shape matches :func:`canforge.framedecode.decode_frames`, so the Frame Decoder
UI renders the same byte view / signal table / bit grid.
"""

from __future__ import annotations
import json

from .framedecode import _fmt_physical


def load_signature(text: str) -> dict:
    """Parse Signature JSON text into an internal ``{frame_id: message}`` map."""
    data = json.loads(text)
    messages: dict[int, dict] = {}
    for id_str, sig_list in data.items():
        frame_id = int(id_str)
        sigs = []
        max_end = 0
        for s in sig_list:
            start = int(s["startingBit"])
            size = int(s["size"])
            max_end = max(max_end, start + size)
            sigs.append({
                "name": str(s["fieldName"]),
                "start": start,
                "size": size,
                # reverse: 0 = big-endian (Motorola), 1 = little-endian (Intel)
                "big_endian": int(s.get("reverse", 0)) == 0,
                "signed": bool(int(s.get("signed", 0))),
                "multiplier": float(s.get("multiplier", 1) or 1),
                "offset": float(s.get("offset", 0)),
            })
        # No DLC in the JSON: size the frame to hold every signal, at least 8
        # bytes, capped at the CAN-FD max of 64. (A few EV battery/range
        # signals legitimately extend past byte 7 → frame grows beyond 8.)
        length = min(64, max(8, -(-max_end // 8)))
        # Name from the decimal ID (the JSON's native base) for consistency.
        messages[frame_id] = {"name": f"MSG_{frame_id}", "length": length, "signals": sigs}
    return messages


def signature_messages(messages: dict) -> list:
    """Catalogue rows for the UI (mirrors the DBC import response shape).

    ``id`` is the native **decimal** CAN ID (the JSON's own representation);
    ``id_hex`` is kept for internal frame routing only.
    """
    return [{
        "id": fid,
        "id_hex": f"{fid:X}",
        "name": m["name"],
        "length": m["length"],
        "signals": [s["name"] for s in m["signals"]],
    } for fid, m in messages.items()]


def _bit(data: bytes, byte: int, bitpos: int) -> int:
    return (data[byte] >> bitpos) & 1 if byte < len(data) else 0


def _extract_raw(data: bytes, start: int, size: int, big_endian: bool) -> int:
    """Extract an unsigned integer from the signal's bit span.

    big-endian: ``startingBit`` is **MSB-first sequential** (bit 0 = byte0's MSB);
    the value is read MSB-first (validated against the Ziptron DBC).
    little-endian: ``startingBit`` is LSB-first sequential (bit 0 = byte0's LSB).
    """
    raw = 0
    if big_endian:
        for i in range(size):
            n = start + i                       # MSB-first sequential position
            raw = (raw << 1) | _bit(data, n // 8, 7 - (n % 8))
        return raw
    for i in range(size):
        n = start + i
        raw |= _bit(data, n // 8, n % 8) << i
    return raw


def _cells(start: int, size: int, big_endian: bool) -> list:
    """``[[byte, bitpos], …]`` occupied by the field (bitpos 0 = byte's LSB)."""
    if big_endian:                              # MSB-first seq: position n -> bit 7-(n%8)
        return [[(start + i) // 8, 7 - ((start + i) % 8)] for i in range(size)]
    return [[(start + i) // 8, (start + i) % 8] for i in range(size)]


def _msb_lsb_cells(start: int, size: int, big_endian: bool):
    """Return ``(msb_cell, lsb_cell)`` — [byte, bitpos] of the value's MSB & LSB."""
    end = start + size - 1
    if big_endian:                              # MSB is the first bit, LSB the last
        return [start // 8, 7 - (start % 8)], [end // 8, 7 - (end % 8)]
    return [end // 8, end % 8], [start // 8, start % 8]   # LE: LSB at start


def decode_frame(messages: dict, frame_id: int, data_hex: str) -> dict:
    m = messages.get(frame_id)
    if m is None:
        return {"id": frame_id, "id_hex": f"{frame_id:X}", "error": "id not in signature"}
    length = m["length"]
    h = data_hex.strip().replace(" ", "").replace("0x", "")
    if len(h) % 2:
        h = "0" + h
    if len(h) < length * 2:
        h = h.zfill(length * 2)            # restore dropped leading zeros
    data = bytes.fromhex(h)[:length]
    if len(data) < length:                # pad so signal byte indexing is safe
        data = data + bytes(length - len(data))

    signals = []
    for s in m["signals"]:
        raw = _extract_raw(data, s["start"], s["size"], s["big_endian"])
        if s["signed"] and raw >= (1 << (s["size"] - 1)):
            raw -= (1 << s["size"])       # two's complement
        phys = raw * s["multiplier"] + s["offset"]
        msb, lsb = _msb_lsb_cells(s["start"], s["size"], s["big_endian"])
        signals.append({
            "name": s["name"],
            "raw": raw,
            "physical": _fmt_physical(phys, s["multiplier"]),
            "choice": None,               # JSON has no VAL_ table
            "unit": "",
            "min": None, "max": None, "out_of_range": False,
            "start_bit": s["start"], "length": s["size"],
            "byte_order": "big_endian" if s["big_endian"] else "little_endian",
            "cells": _cells(s["start"], s["size"], s["big_endian"]),
            "msb_cell": msb, "lsb_cell": lsb,
        })
    return {
        "id": frame_id, "id_hex": f"{frame_id:X}", "name": m["name"], "length": length,
        "bytes": [data[i] for i in range(length)],
        "signals": signals,
    }


def decode_frames(messages: dict, frames: list) -> list:
    """Decode a list of ``{"id": <hex or int>, "data": <hex>}`` frames."""
    out = []
    for fr in frames:
        rid = fr.get("id")
        fid = int(str(rid), 16) if not isinstance(rid, int) else rid
        try:
            out.append(decode_frame(messages, fid, str(fr.get("data", ""))))
        except Exception as exc:
            out.append({"id_hex": f"{fid:X}", "error": str(exc)})
    return out
