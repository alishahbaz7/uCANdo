"""Import a **Vehicle Spy 3** (Intrepid neoVI) CAN bus trace CSV.

Vehicle Spy exports: a metadata header, a ``Network Description`` table
(network name -> hardware/protocol/baud), **three alternate column-header
rows** — one each for a CAN-style, LIN-style and J1939-style view of the same
columns — then data rows. A capture that stays on CAN networks (``HS CAN``,
``MS CAN``, ...) uses the CAN header consistently: ``Arb ID`` (hex, no
``0x``), ``Remote``/``Xtd`` flags (``F``/``T``), and up to 8 ``B1..B8`` hex
byte columns (blank past the frame's DLC — this is how short/non-8-byte
frames are represented, not a fixed-width field).

This module parses those CAN rows into the same **frames-by-id** shape
``reverse.load_log_frames()`` already produces from ``.asc``/``.blf``/``.trc``
via ``python-can`` — so a Vehicle Spy capture plugs into RE analysis,
CANMatch, and OBD-correlate with no changes to those engines.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict

_SIGNATURE = "vehicle spy"

#: Vehicle Spy interleaves **bus-event** rows with real frames — adapter status
#: reports such as ``CAN Rx/Tx REGS - TEC: 0 - REC: 1``, which carry ``Er=T``,
#: ``Description=CAN Bus Event`` and put that free text in the *Arb ID* column.
#: They are numbered like data rows, so the only robust discriminator is that a
#: real arbitration ID is pure hex. Rows failing this are skipped.
_HEX_ID = re.compile(r"[0-9A-Fa-f]{1,8}")


def is_vspy_csv(text: str) -> bool:
    """Sniff the first line for the Vehicle Spy export banner."""
    head = text.lstrip("﻿").splitlines()
    return bool(head) and head[0].strip().lower().startswith(_SIGNATURE)


def network_table(text: str) -> dict[str, dict]:
    """``{network_name: {"protocol": str, "baud": int|None}}`` from the file.

    Header is ``Network Description,Hardware,Network,Protocol,Baud Rate`` —
    the row's own name repeats in the "Network" column, protocol is index 3
    and **baud rate index 4**. This is where a Vehicle Spy capture records the
    bitrate it was taken at, so a replay can restore it without the operator
    having to remember (`neoVI` and other rows may leave baud blank).

    Note it is Vehicle Spy's *static* network config — every network it knows
    about, not only the ones that appear in the traffic. Callers should read
    baud for the networks they actually saw frames on.
    """
    return _network_table(text.lstrip("﻿").splitlines())


def _network_table(lines: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    start = next((i for i, ln in enumerate(lines) if ln.startswith("Network Description,")), None)
    if start is None:
        return out
    for ln in lines[start + 1:]:
        if not ln.strip() or ln.startswith("Line,"):
            break
        cols = ln.split(",")
        if len(cols) >= 5:                      # name, hardware, network, protocol, baud
            baud = cols[4].strip()
            out[cols[0].strip()] = {
                "protocol": cols[3].strip(),
                "baud": int(baud) if baud.isdigit() else None,
            }
    return out


def _network_protocols(lines: list[str]) -> dict[str, str]:
    """``{network_name: protocol}`` — the protocol column only."""
    return {k: v["protocol"] for k, v in _network_table(lines).items()}


def parse_frames(text: str) -> list[dict]:
    """Parse Vehicle Spy CSV text into a list of frame dicts, capture order.

    Each frame: ``{timestamp, network, id, id_hex, is_extended, is_remote,
    is_tx, data}``.
    """
    return list(iter_frames(text))


def iter_frames(text: str):
    """Streaming :func:`parse_frames` — yields one frame dict at a time.

    A 100k-row capture is ~6 MB of CSV; TX replay stores frames in packed
    arrays (:mod:`ucando.logstore`) rather than a list of dicts, so it wants
    them one at a time instead of materialising the whole list first.
    """
    if not is_vspy_csv(text):
        raise ValueError("not a Vehicle Spy 3 Bus Traffic File")
    lines = text.lstrip("﻿").splitlines()
    protocols = _network_protocols(lines)

    hdr_idx = next((i for i, ln in enumerate(lines)
                     if ln.startswith("Line,Abs Time") and "Arb ID" in ln), None)
    if hdr_idx is None:
        raise ValueError("Vehicle Spy CAN header row (Arb ID/Remote/Xtd) not found")
    header = lines[hdr_idx].split(",")

    for row in csv.reader(lines[hdr_idx + 1:]):
        if not row or not row[0].strip().isdigit():
            continue                            # blank line / trailer, not a data row
        d = dict(zip(header, row))
        net = (d.get("Network") or "").strip()
        if protocols.get(net, "CAN") != "CAN":
            continue                            # LIN/J1708/etc. share these columns differently
        id_hex = (d.get("Arb ID") or "").strip()
        if not id_hex or not _HEX_ID.fullmatch(id_hex):
            continue                            # bus-event row, not a frame (see below)
        byte_cols = [d.get(f"B{i}", "") for i in range(1, 9)]
        data = bytes.fromhex("".join(b for b in byte_cols if b.strip() != ""))
        yield {
            "timestamp": float(d["Abs Time(Sec)"]),
            "network": net,
            "id": int(id_hex, 16),
            "id_hex": id_hex.upper(),
            "is_extended": (d.get("Xtd") or "").strip().upper() == "T",
            "is_remote": (d.get("Remote") or "").strip().upper() == "T",
            # Frames the capturing tool transmitted itself. Replaying them back
            # is usually wrong (they are the tester's own traffic, not the
            # vehicle's), so TX replay can filter on this.
            "is_tx": (d.get("Tx") or "").strip().upper() == "T",
            "data": data,
        }


def to_frames_by_id(frames: list[dict], max_frames_per_id: int = 20000) -> dict:
    """``parse_frames()`` output -> ``{(id, ext): {timestamps, payloads}}``.

    Matches ``reverse.load_log_frames()`` exactly, so RE engines stay unaware
    of where the log came from.
    """
    out: dict[tuple[int, bool], dict] = defaultdict(lambda: {"timestamps": [], "payloads": []})
    for fr in frames:
        bucket = out[(fr["id"], fr["is_extended"])]
        if len(bucket["payloads"]) < max_frames_per_id:
            bucket["payloads"].append(fr["data"])
            bucket["timestamps"].append(fr["timestamp"])
    return dict(out)
