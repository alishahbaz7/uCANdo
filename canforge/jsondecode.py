"""Decode raw CAN frames against a lightweight **Signature JSON** (cloud format).

The Signature JSON is a limited DBC alternative used for cloud visualization::

    {"900": [{"fieldName","reverse","startingBit","size",
              "multiplier","offset","signed","evData"}, ...], ...}

Bit/byte convention — **validated against the Ziptron DBC** (see
``docs/JSON_SIGNATURE_DECODE.md``):

* keys are CAN IDs in **decimal** *or* **hex** — two exporters exist in the wild
  and the base is auto-detected per file by :func:`detect_id_base`;
* for **big-endian** (``reverse == 0``) ``startingBit`` is **MSB-first
  sequential**: bit 0 = byte0's MSB, bit 7 = byte0's LSB, bit 8 = byte1's MSB,
  … and the value is read MSB-first. This equals the DBC/cantools Motorola
  layout: cantools start = ``(startingBit//8)*8 + (7 - startingBit%8)``;
* for **little-endian** (``reverse == 1``) ``startingBit`` is LSB-first
  sequential (bit 0 = byte0's LSB) and the value is read LSB-first;
* a signal occupies ``size`` consecutive bits from ``startingBit``;
* ``signed == 1`` → two's complement over ``size`` bits;
* physical = ``raw * multiplier + offset``;
* the JSON carries **no DLC**, so the frame length is synthesised as
  ``max(8, ceil(max_end/8))``. A payload shorter than that is padded on the
  **right** — see :func:`decode_frame`.

Ground truth (Ziptron DBC, message 0x244/580, frame ``5251 0047 C000 BA56``):
``DTeInfo=287`` (start 24, size 10) and ``HVBattSoCPercen=93`` (start 48, size 7)
— both reproduced exactly. byte-aligned ``canOdometer=75971`` also holds. Second
vehicle (MG Commute EV 2026, ``oem_packs/MG/Commute/EV_2026``): the DLC-5 frame
``0x120`` = ``00 02 FE A2 00`` gives ``Odometer = 3066.53 km`` against a dash
reading of 3066 — the case that pinned the padding direction.

Self-contained (no cantools): the JSON carries no enums / min-max / units, so a
direct bit extractor reproduces the cloud/DBC values exactly. The output dict
shape matches :func:`canforge.framedecode.decode_frames`, so the Frame Decoder
UI renders the same byte view / signal table / bit grid.
"""

from __future__ import annotations
import json

from .framedecode import _fmt_physical


def detect_id_base(keys) -> int:
    """Return ``16`` if this signature's CAN-ID keys are hex, else ``10``.

    Two exporters are in the field and a *per-key* guess cannot separate them —
    ``"120"`` is legal in both bases. So the base is decided **once for the whole
    file**, from whichever keys are unambiguous:

    * a ``0x`` prefix or any hex letter (``"408b"``, ``"18FEEA27"``) → hex;
    * a zero-padded key (``"000000E1"``) → hex: the 8-digit padded form is the
      32-bit hex ID field, and no decimal exporter pads.

    Nothing unambiguous → decimal (the original Ziptron-validated convention).
    One hex key therefore makes the file hex, which is what rescues mixed-width
    files like ``408b``/``4091``/``15`` — all three are hex there.
    """
    for k in keys:
        s = str(k).strip()
        if s[:2].lower() == "0x":
            return 16
        if any(c in "abcdefABCDEF" for c in s):
            return 16
        if len(s) > 1 and s[0] == "0":
            return 16
    return 10


def parse_frame_id(key, base: int) -> int:
    """CAN-ID key → int in ``base``, with an error that names the offender."""
    s = str(key).strip()
    try:
        return int(s[2:] if s[:2].lower() == "0x" else s, base)
    except ValueError:
        raise ValueError(
            f"CAN ID key {key!r} is not a valid "
            f"{'hex' if base == 16 else 'decimal'} number") from None


_REQUIRED_SIGNAL_KEYS = ("fieldName", "startingBit", "size")


def signal_list(key, value) -> list:
    """Validate one ``{id: [...]}`` entry and return its list of signal dicts.

    Other telematics JSON families share the ``{id: ...}`` outer shape but carry
    **no bit layout** — e.g. a name/scaling map (``{"title", "multiplier",
    "divider", "offSet"}``), where CAN id and layout live elsewhere. Such a file
    cannot be decoded at all, so name the missing fields here instead of dying on
    a ``TypeError`` deep in the bit maths. A lone signal object is accepted as a
    one-element list.
    """
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(
            f"CAN ID {key!r}: expected a list of signals, got {type(value).__name__}")
    for s in value:
        if not isinstance(s, dict):
            raise ValueError(
                f"CAN ID {key!r}: expected signal objects, got {type(s).__name__}")
        missing = [k for k in _REQUIRED_SIGNAL_KEYS if k not in s]
        if missing:
            raise ValueError(
                f"CAN ID {key!r}: signal is missing {', '.join(missing)} — this file "
                "carries no bit layout, so it is not a Signature JSON and cannot be decoded")
    return value


def message_name(frame_id: int, base: int) -> str:
    """``MSG_<id>`` in the file's own base — ``MSG_18FEEA27`` beats ``MSG_419360295``."""
    return f"MSG_{frame_id:X}" if base == 16 else f"MSG_{frame_id}"


def load_signature(text: str) -> dict:
    """Parse Signature JSON text into an internal ``{frame_id: message}`` map."""
    data = json.loads(text)
    base = detect_id_base(data.keys())
    messages: dict[int, dict] = {}
    for id_str, sig_list in data.items():
        frame_id = parse_frame_id(id_str, base)
        sigs = []
        max_end = 0
        for s in signal_list(id_str, sig_list):
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
        # Name from the ID in the file's own base, so it reads back recognisably.
        messages[frame_id] = {"name": message_name(frame_id, base),
                              "length": length, "signals": sigs}
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


def signal_cells(start: int, size: int, big_endian: bool) -> list:
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
    data = bytes.fromhex(h)[:length]
    if len(data) < length:
        # Pad on the **right**: a payload shorter than ``length`` is a short-DLC
        # frame missing its trailing bytes, and CAN payload bytes are positional,
        # not one big integer — byte 0 must stay byte 0. Left-padding silently
        # shifted real data (MG Commute 0x120, DLC 5: odometer read 0.00 instead
        # of the dash-confirmed 3066.53 km). ``length`` is only a guess here
        # anyway — the JSON carries no DLC, so it is synthesised as max(8, …).
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
            "cells": signal_cells(s["start"], s["size"], s["big_endian"]),
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
