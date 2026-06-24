"""Convert a CAN signal database among **DBC**, **Signature-JSON** and **CSV**
in any direction (see ``docs/CONVERTER_PLAN.md``).

A single **canonical model** sits in the middle; each format parses *into* it and
serializes *out of* it, so all six directions reuse the same two halves::

    DBC ─┐        ┌─ DBC
    JSON ┼─model──┼─ JSON
    CSV ─┘        └─ CSV

Canonical model (one dict)::

    {"messages": [
        {"name", "frame_id"(int, decimal), "is_extended"(bool), "dlc"(int),
         "signals": [
            {"name", "start_bit", "length", "byte_order"("big_endian"/"little_endian"),
             "is_signed", "scale", "offset", "min", "max", "unit",
             "value_table"({int:str}|None), "comment", "ev_data"(0/1)} ]} ]}

``start_bit`` is **Intel / LSB-first sequential** (bit 0 = byte0 LSB) - the same
convention as the JSON and CSV, validated last session. Only the **DBC** boundary
converts to/from cantools' own bit numbering; JSON and CSV use it directly.

Lossy directions are reported, never silent: →JSON drops message names, DLC,
min/max, units, value tables and comments (the format has nowhere to put them).
"""

from __future__ import annotations

import csv
import io
import json

import cantools
from cantools.database.can import Database, Message, Signal
from cantools.database.conversion import BaseConversion

from . import framedecode

CSV_HEADER = [
    "message_name", "CAN ID (HEX)", "CAN ID (Dec)", "is_extended", "dlc",
    "signal_name", "start_bit", "length", "byte_order", "signed", "scale",
    "offset", "min", "max", "unit", "value_table", "comment", "ev_data",
]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _num(x):
    """Trim ``1.0`` → ``1`` for clean CSV/JSON output, keep ``0.1`` as-is."""
    f = float(x)
    return int(f) if f == int(f) else f


def _blank(x):
    return "" if x is None else _num(x) if isinstance(x, (int, float)) else x


def _parse_byte_order(raw) -> str:
    """Accept Motorola/Intel, big_endian/little_endian, or reverse 0/1."""
    s = str(raw).strip().lower()
    if s in ("motorola", "big_endian", "big-endian", "be", "0"):
        return "big_endian"
    if s in ("intel", "little_endian", "little-endian", "le", "1"):
        return "little_endian"
    return "little_endian"


def _parse_value_table(raw):
    """``"0:P;1:R;2:N"`` → ``{0:'P', 1:'R', 2:'N'}`` (or None)."""
    if not raw or not str(raw).strip():
        return None
    out = {}
    for pair in str(raw).split(";"):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        k, v = pair.split(":", 1)
        try:
            out[int(k.strip())] = v.strip()
        except ValueError:
            continue
    return out or None


def _fmt_value_table(vt) -> str:
    return ";".join(f"{k}:{v}" for k, v in (vt or {}).items())


# --------------------------------------------------------------------------- #
# bit-position conversion (only needed at the DBC boundary)
# --------------------------------------------------------------------------- #
def _intelseq_to_cantools_start(start_bit: int, length: int, big_endian: bool) -> int:
    """Canonical Intel/LSB-seq start → cantools ``Signal.start``."""
    if not big_endian:
        return start_bit                       # Intel: LSB position is identical
    # Motorola: cantools start = the field's MSB position. For a field occupying
    # Intel-seq [start_bit, end], the MSB is the highest bit of the lowest byte.
    end = start_bit + length - 1
    first_byte = start_bit // 8
    return min(end, first_byte * 8 + 7)


def _cantools_cells_to_intelseq(cells, length: int):
    """cantools cell occupancy → ``(start_bit, contiguous?)`` in Intel-seq."""
    idxs = sorted(b * 8 + bit for b, bit in cells)
    if not idxs:
        return 0, False
    start = idxs[0]
    contiguous = idxs == list(range(start, start + length))
    return start, contiguous


def _be_doubt(start_bit: int, length: int, byte_order: str):
    """A note if this signal can't be represented exactly in DBC, else None.

    Only **big-endian** signals that cross a byte boundary while *not* being
    whole-byte-aligned are ambiguous (the cloud's Intel-seq span and DBC's
    Motorola sawtooth disagree). Single-byte or byte-aligned BE round-trips fine.
    """
    if byte_order != "big_endian":
        return None
    first = start_bit // 8
    last = (start_bit + length - 1) // 8
    if last > first and not (start_bit % 8 == 0 and length % 8 == 0):
        return f"sub-byte big-endian (size {length}) - verify bit layout in a DBC tool"
    return None


def inject_doubts(model) -> int:
    """Tag each signal with a ``doubt`` note (or None). Returns the count."""
    n = 0
    for m in model["messages"]:
        for s in m["signals"]:
            s["doubt"] = _be_doubt(s["start_bit"], s["length"], s["byte_order"])
            if s["doubt"]:
                n += 1
    return n


def _merge_comment(user_comment, note) -> str:
    parts = [p for p in [(user_comment or "").strip(),
                         ("uCANdo: " + note) if note else ""] if p]
    return " | ".join(parts)


# --------------------------------------------------------------------------- #
# DBC  ⇄  model
# --------------------------------------------------------------------------- #
def dbc_to_model(text: str):
    db = cantools.database.load_string(text, database_format="dbc")
    warnings, messages = [], []
    for m in db.messages:
        sigs = []
        for s in m.signals:
            if s.multiplexer_ids:                      # multiplexed payload signal
                warnings.append(f"{m.name}.{s.name}: multiplexed signal skipped (v1)")
                continue
            cells = framedecode.signal_cells(m, s)
            start_bit, contiguous = _cantools_cells_to_intelseq(cells, s.length)
            if not contiguous:
                warnings.append(
                    f"{m.name}.{s.name}: non-contiguous layout (sub-byte big-endian) - "
                    "start bit in JSON/CSV is approximate")
            value_table = None
            if s.choices:
                value_table = {int(k): str(v) for k, v in s.choices.items()}
            sigs.append({
                "name": s.name, "start_bit": start_bit, "length": s.length,
                "byte_order": s.byte_order,
                "is_signed": bool(s.is_signed),
                "scale": _num(s.scale), "offset": _num(s.offset),
                "min": None if s.minimum is None else _num(s.minimum),
                "max": None if s.maximum is None else _num(s.maximum),
                "unit": s.unit or "", "value_table": value_table,
                "comment": s.comment or "", "ev_data": 0,
            })
        messages.append({
            "name": m.name, "frame_id": m.frame_id,
            "is_extended": bool(m.is_extended_frame), "dlc": m.length, "signals": sigs,
        })
    return {"messages": messages}, warnings


def model_to_dbc(model):
    warnings = []
    db = Database()
    for m in model["messages"]:
        ct_sigs = []
        for s in m["signals"]:
            be = s["byte_order"] == "big_endian"
            note = _be_doubt(s["start_bit"], s["length"], s["byte_order"])
            if note:
                warnings.append(f"{m['name']}.{s['name']}: {note}")
            conv = BaseConversion.factory(
                scale=float(s.get("scale", 1) or 1),
                offset=float(s.get("offset", 0) or 0), is_float=False)
            sig = Signal(
                name=s["name"],
                start=_intelseq_to_cantools_start(s["start_bit"], s["length"], be),
                length=s["length"], byte_order=s["byte_order"],
                is_signed=bool(s.get("is_signed")), conversion=conv,
                minimum=s.get("min"), maximum=s.get("max"),
                unit=(s.get("unit") or None),
                comment=(_merge_comment(s.get("comment"), note) or None))   # #6: annotate doubts
            if s.get("value_table"):
                try:
                    sig.choices = {int(k): str(v) for k, v in s["value_table"].items()}
                except Exception:
                    pass
            ct_sigs.append(sig)
        db.messages.append(Message(
            frame_id=m["frame_id"], name=m["name"], length=m["dlc"],
            signals=ct_sigs, is_extended_frame=bool(m.get("is_extended"))))
    return db.as_dbc_string(), warnings


# --------------------------------------------------------------------------- #
# JSON  ⇄  model
# --------------------------------------------------------------------------- #
def json_to_model(text: str):
    data = json.loads(text)
    messages = []
    for id_str, sig_list in data.items():
        frame_id = int(id_str)
        sigs, max_end = [], 0
        for s in sig_list:
            start = int(s["startingBit"])
            size = int(s["size"])
            max_end = max(max_end, start + size)
            sigs.append({
                "name": str(s["fieldName"]), "start_bit": start, "length": size,
                "byte_order": "big_endian" if int(s.get("reverse", 0)) == 0 else "little_endian",
                "is_signed": bool(int(s.get("signed", 0))),
                "scale": _num(s.get("multiplier", 1) or 1), "offset": _num(s.get("offset", 0)),
                "min": None, "max": None, "unit": "", "value_table": None,
                "comment": "", "ev_data": int(s.get("evData", 0)),
            })
        messages.append({
            "name": f"MSG_{frame_id}", "frame_id": frame_id,
            "is_extended": frame_id > 0x7FF,
            "dlc": min(64, max(8, -(-max_end // 8))), "signals": sigs,
        })
    return {"messages": messages}, []


def model_to_json(model):
    out, dropped = {}, set()
    for m in model["messages"]:
        if not m["name"].startswith("MSG_"):
            dropped.add("message names")
        arr = []
        for s in m["signals"]:
            if s.get("unit"):
                dropped.add("units")
            if s.get("min") is not None or s.get("max") is not None:
                dropped.add("min/max")
            if s.get("value_table"):
                dropped.add("value tables")
            if s.get("comment"):
                dropped.add("comments")
            arr.append({
                "fieldName": s["name"],
                "reverse": 0 if s["byte_order"] == "big_endian" else 1,
                "startingBit": s["start_bit"], "size": s["length"],
                "evData": int(s.get("ev_data") or 0),
                "multiplier": _num(s.get("scale", 1)), "offset": _num(s.get("offset", 0)),
                "signed": int(bool(s.get("is_signed"))),
            })
        out[str(m["frame_id"])] = arr
    warnings = []
    if dropped:
        warnings.append("JSON has no field for: " + ", ".join(sorted(dropped)) + " - dropped.")
    return json.dumps(out, indent=2), warnings


# --------------------------------------------------------------------------- #
# CSV  ⇄  model
# --------------------------------------------------------------------------- #
def model_to_csv(model):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    warnings = []
    for m in model["messages"]:
        for s in m["signals"]:
            note = _be_doubt(s["start_bit"], s["length"], s["byte_order"])
            if note:
                warnings.append(f"{m['name']}.{s['name']}: {note}")
            w.writerow([
                m["name"], f"0x{m['frame_id']:X}", m["frame_id"],
                int(bool(m.get("is_extended"))), m["dlc"],
                s["name"], s["start_bit"], s["length"],
                "Motorola" if s["byte_order"] == "big_endian" else "Intel",
                int(bool(s.get("is_signed"))), _num(s.get("scale", 1)), _num(s.get("offset", 0)),
                _blank(s.get("min")), _blank(s.get("max")), s.get("unit") or "",
                _fmt_value_table(s.get("value_table")),
                _merge_comment(s.get("comment"), note), int(s.get("ev_data") or 0),
            ])
    return buf.getvalue(), warnings


def csv_to_model(text: str):
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []

    def _find(*names):
        return next((n for n in names if n in fields), None)

    # CAN ID can come from a decimal column, a hex column, or the legacy can_id.
    id_dec = _find("CAN ID (Dec)", "can_id_dec", "can_id")
    id_hex = _find("CAN ID (HEX)", "can_id_hex")
    if not (id_dec or id_hex):
        raise ValueError("CSV missing a CAN ID column (need 'CAN ID (Dec)' or 'CAN ID (HEX)')")
    missing = [c for c in ("signal_name", "start_bit", "length") if c not in fields]
    if missing:
        raise ValueError("CSV missing required column(s): " + ", ".join(missing))

    by_id, order = {}, []
    warnings = []
    for i, row in enumerate(reader, start=2):
        dec_v = (row.get(id_dec) or "").strip() if id_dec else ""
        hex_v = (row.get(id_hex) or "").strip() if id_hex else ""
        if not dec_v and not hex_v:
            continue
        try:                                   # prefer decimal; fall back to hex
            if dec_v:
                frame_id = int(dec_v, 16) if dec_v.lower().startswith("0x") else int(dec_v)
            else:
                frame_id = int(hex_v, 16)
        except ValueError:
            warnings.append(f"row {i}: bad CAN ID '{dec_v or hex_v}' - skipped")
            continue
        if frame_id not in by_id:
            by_id[frame_id] = {
                "name": (row.get("message_name") or f"MSG_{frame_id}").strip(),
                "frame_id": frame_id,
                "is_extended": str(row.get("is_extended", "")).strip() in ("1", "true", "True"),
                "dlc": int(row["dlc"]) if (row.get("dlc") or "").strip() else 8,
                "signals": [],
            }
            order.append(frame_id)
        num = lambda k, d=None: (float(row[k]) if (row.get(k) or "").strip() not in ("", None) else d)
        by_id[frame_id]["signals"].append({
            "name": (row.get("signal_name") or "").strip(),
            "start_bit": int(float(row["start_bit"])), "length": int(float(row["length"])),
            "byte_order": _parse_byte_order(row.get("byte_order", "Intel")),
            "is_signed": str(row.get("signed", "")).strip() in ("1", "true", "True"),
            "scale": _num(num("scale", 1)), "offset": _num(num("offset", 0)),
            "min": num("min"), "max": num("max"),
            "unit": (row.get("unit") or "").strip(),
            "value_table": _parse_value_table(row.get("value_table")),
            "comment": (row.get("comment") or "").strip(),
            "ev_data": int(float(row["ev_data"])) if (row.get("ev_data") or "").strip() else 0,
        })
    return {"messages": [by_id[i] for i in order]}, warnings


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
_PARSERS = {"dbc": dbc_to_model, "json": json_to_model, "csv": csv_to_model}
_SERIALIZERS = {"dbc": model_to_dbc, "json": model_to_json, "csv": model_to_csv}


def detect_format(filename: str, text: str) -> str:
    fn = (filename or "").lower()
    for ext in ("dbc", "json", "csv"):
        if fn.endswith("." + ext):
            return ext
    head = text.lstrip()
    if head.startswith("{"):
        return "json"
    if head.startswith("VERSION") or "\nBO_ " in text or text.startswith("BO_ "):
        return "dbc"
    first_line = text.split("\n", 1)[0]
    if "can_id" in first_line and "signal_name" in first_line:
        return "csv"
    raise ValueError("could not detect format - use a .dbc / .json / .csv file")


def parse(text: str, from_fmt: str | None = None, filename: str = ""):
    """Parse a file into the canonical model (with per-signal ``doubt`` tags)."""
    if from_fmt is None:
        from_fmt = detect_format(filename, text)
    if from_fmt not in _PARSERS:
        raise ValueError(f"unknown source format: {from_fmt}")
    model, warnings = _PARSERS[from_fmt](text)
    inject_doubts(model)
    summary = {
        "from": from_fmt,
        "messages": len(model["messages"]),
        "signals": sum(len(m["signals"]) for m in model["messages"]),
    }
    return {"model": model, "from": from_fmt, "warnings": warnings, "summary": summary}


def serialize(model, to_fmt: str):
    """Serialize a (possibly edited/filtered) canonical model to ``to_fmt``."""
    if to_fmt not in _SERIALIZERS:
        raise ValueError(f"unknown target format: {to_fmt}")
    content, warnings = _SERIALIZERS[to_fmt](model)
    return {"content": content, "warnings": warnings}


def convert(text: str, to_fmt: str, from_fmt: str | None = None, filename: str = ""):
    """One-shot parse + serialize. Returns ``{content, warnings, summary, from}``."""
    p = parse(text, from_fmt=from_fmt, filename=filename)
    s = serialize(p["model"], to_fmt)
    p["summary"]["to"] = to_fmt
    return {"content": s["content"], "warnings": p["warnings"] + s["warnings"],
            "summary": p["summary"], "from": p["from"]}
