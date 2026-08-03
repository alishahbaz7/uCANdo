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

from . import canplus, jsondecode

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


def _sort_model(model):
    """Order messages by CAN ID and, within each, signals by start bit (ascending).

    Applied on **parse** (so the workbench preview reads top-to-bottom) and on
    **serialize** (so the downloaded file keeps the same clean, structured order).
    ``start_bit`` is the canonical per-signal position, so ascending order lists
    signals in payload order for both Motorola and Intel layouts. In place; idempotent.
    """
    for m in model.get("messages", []):
        m["signals"].sort(key=lambda s: (int(s.get("start_bit", 0)), str(s.get("name", ""))))
    model["messages"].sort(key=lambda m: (int(m.get("frame_id", 0)), str(m.get("name", ""))))
    return model


# --------------------------------------------------------------------------- #
# bit-position conversion (only at the DBC boundary)
# --------------------------------------------------------------------------- #
def _be_seq_cantools(pos: int) -> int:
    """Map between the JSON big-endian ``startingBit`` (MSB-first sequential) and
    the cantools/DBC Motorola start bit. Self-inverse: ``byte*8 + (7 - bit)``.

    Validated against the Ziptron DBC: JSON 24 ↔ DBC 31, 48 ↔ 55, 42 ↔ 45, …
    """
    return (pos // 8) * 8 + (7 - pos % 8)


def _to_cantools_start(start_bit: int, big_endian: bool) -> int:
    return _be_seq_cantools(start_bit) if big_endian else start_bit


def _from_cantools_start(start: int, big_endian: bool) -> int:
    return _be_seq_cantools(start) if big_endian else start


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
            be = s.byte_order == "big_endian"
            value_table = {int(k): str(v) for k, v in s.choices.items()} if s.choices else None
            sigs.append({
                "name": s.name, "start_bit": _from_cantools_start(s.start, be),
                "length": s.length, "byte_order": s.byte_order,
                "is_signed": bool(s.is_signed),
                "scale": _num(s.scale), "offset": _num(s.offset),
                "min": None if s.minimum is None else _num(s.minimum),
                "max": None if s.maximum is None else _num(s.maximum),
                "unit": s.unit or "", "value_table": value_table,
                # A DBC has no evData field. These databases are EV vehicle packs
                # and the cloud consumes them with the flag set, so default it on
                # rather than emitting 0 for every signal (which is what silently
                # zeroed a whole signature before).
                "comment": s.comment or "", "ev_data": 1,
            })
        messages.append({
            "name": m.name, "frame_id": m.frame_id,
            "is_extended": bool(m.is_extended_frame), "dlc": m.length, "signals": sigs,
        })
    # CAN IDs in a DBC are written decimal (`BO_ 288`) but *read* as hex by everyone
    # working on the bus, and the cloud signature keys are hex. Record that so the
    # JSON export does not silently renumber 0x120 into "288" - see model_to_json.
    return {"messages": messages, "id_base": 16}, warnings


def model_to_dbc(model):
    try:
        content = _model_to_dbc(model)
        # A DBC has no field for evData, so it is dropped here and comes back as 0
        # on the next JSON/CSV export. Every other lossy field is reported, so this
        # one must be too: it was silently zeroing a flag set on *every* signal of
        # a real cloud signature. CSV carries evData, so it is the lossless hop.
        warnings = []
        if any(s.get("ev_data") for m in model["messages"] for s in m["signals"]):
            warnings.append("DBC has no field for: evData - dropped (a round trip "
                            "through DBC returns evData=0; convert via CSV to keep it).")
        return content, warnings
    except Exception as exc:
        # A DBC cannot hold overlapping signals, but a source JSON/CSV can carry
        # them (an off-by-one startingBit is the usual cause). cantools reports
        # only the two names - add the CAN ID and bit spans so the fix is obvious.
        raise ValueError(f"{exc}{_overlap_detail(model)}") from None


def _overlap_detail(model) -> str:
    """``" - 0x287 PackCurrent bits 1-16 overlaps PackVoltage3 bits 16-31"`` (or "").

    Compared as occupied ``(byte, bit)`` cells, not as ``start_bit`` ranges: the
    canonical start bit means MSB-first-sequential for big-endian signals and
    LSB-first-sequential for little-endian ones, so only the cell sets of a
    mixed-endian message are directly comparable.
    """
    found = []
    for m in model["messages"]:
        owner: dict[tuple[int, int], dict] = {}
        for s in m["signals"]:
            be = s["byte_order"] == "big_endian"
            for cell in jsondecode.signal_cells(s["start_bit"], s["length"], be):
                prev = owner.setdefault(tuple(cell), s)
                if prev is not s:
                    found.append(
                        f"0x{m['frame_id']:X} {prev['name']} bits "
                        f"{prev['start_bit']}-{prev['start_bit'] + prev['length'] - 1}"
                        f" overlaps {s['name']} bits "
                        f"{s['start_bit']}-{s['start_bit'] + s['length'] - 1}")
                    break
    return (" - " + "; ".join(found)) if found else ""


def _model_to_dbc(model) -> str:
    db = Database()
    for m in model["messages"]:
        ct_sigs = []
        for s in m["signals"]:
            be = s["byte_order"] == "big_endian"
            conv = BaseConversion.factory(
                scale=float(s.get("scale", 1) or 1),
                offset=float(s.get("offset", 0) or 0), is_float=False)
            sig = Signal(
                name=s["name"], start=_to_cantools_start(s["start_bit"], be),
                length=s["length"], byte_order=s["byte_order"],
                is_signed=bool(s.get("is_signed")), conversion=conv,
                minimum=s.get("min"), maximum=s.get("max"),
                unit=(s.get("unit") or None), comment=(s.get("comment") or None))
            if s.get("value_table"):
                try:
                    sig.choices = {int(k): str(v) for k, v in s["value_table"].items()}
                except Exception:
                    pass
            ct_sigs.append(sig)
        db.messages.append(Message(
            frame_id=m["frame_id"], name=m["name"], length=m["dlc"],
            signals=ct_sigs, is_extended_frame=bool(m.get("is_extended"))))
    return db.as_dbc_string()


# --------------------------------------------------------------------------- #
# JSON  ⇄  model
# --------------------------------------------------------------------------- #
def json_to_model(text: str):
    data = json.loads(text)
    # Keys are decimal in some exports, hex in others — decide once per file
    # (see jsondecode.detect_id_base); a per-key guess cannot tell them apart.
    base = jsondecode.detect_id_base(data.keys())
    messages, warnings = [], []
    if base == 16:
        warnings.append("CAN ID keys read as hexadecimal (e.g. "
                        f"{next(iter(data), '')!s} = "
                        f"{jsondecode.parse_frame_id(next(iter(data), '0'), 16)} decimal). "
                        "JSON export writes decimal keys.")
    for id_str, sig_list in data.items():
        frame_id = jsondecode.parse_frame_id(id_str, base)
        sigs, max_end = [], 0
        for s in jsondecode.signal_list(id_str, sig_list):
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
            "name": jsondecode.message_name(frame_id, base), "frame_id": frame_id,
            "is_extended": frame_id > 0x7FF,
            "dlc": min(64, max(8, -(-max_end // 8))), "signals": sigs,
        })
    # Round-trip the key base the file was written in, so JSON -> JSON keeps it.
    return {"messages": messages, "id_base": base}, warnings


def json_id_key(frame_id: int, base: int) -> str:
    """CAN id as a JSON object key: ``"00000120"`` for hex, ``"288"`` for decimal.

    Hex is zero-padded to 8 digits — the 32-bit id field, and the form the cloud
    signatures use. Decoders detect the base per file (``detect_id_base``), so
    either key style reads back to the same id.
    """
    return f"{frame_id:08X}" if base == 16 else str(frame_id)


def _qualifiers(model) -> dict:
    """``{frame_id: qualifier}`` used to disambiguate a repeated signal name.

    Prefers the **message name** over the CAN id, because it says *why* the two
    signals differ: ``PackVoltage_HvPower`` vs ``PackVoltage_HvBattery2`` beats
    ``PackVoltage_287`` vs ``PackVoltage_29A`` for anyone reading a dashboard. A
    DBC already guarantees signal names are unique *within* a message, so the
    message name is guaranteed to disambiguate.

    A leading **bus tag** is stripped as noise: ``HSC_HvPower`` → ``HvPower``. A
    vehicle has only a handful of buses, so *few distinct first segments across many
    messages* is the tell (``mg_commute_ev_2026`` is 54 × ``HSC_`` + 1 × ``MSC_`` —
    requiring *every* name to share one prefix would have missed it). The strip is
    kept only if the shortened names stay unique, so it can never make a qualifier
    ambiguous. Falls back to the compact hex id for messages with no real name — a
    JSON source auto-names them ``MSG_<id>``, which would qualify nothing.
    """
    names = {m["frame_id"]: (m.get("name") or "") for m in model["messages"]}
    real = {fid: n for fid, n in names.items() if n and not n.startswith("MSG_")}
    use = real
    heads = {n.split("_", 1)[0] for n in real.values()}
    if len(real) > len(heads) <= 3 and all("_" in n for n in real.values()):
        short = {fid: n.split("_", 1)[1] for fid, n in real.items()}
        if all(short.values()) and len(set(short.values())) == len(short):
            use = short                      # unambiguous after the strip
    return {fid: use.get(fid) or f"{fid:X}" for fid in names}


def _dedupe_signal_names(model) -> tuple[dict, list]:
    """``{(frame_id, name): unique_name}`` for names that repeat across messages.

    JSON consumers key on ``fieldName``, so two signals sharing a name collide even
    though the DBC scopes names per message. A repeated name becomes
    ``<name>_<qualifier>`` (see :func:`_qualifiers`); names that appear once are
    left untouched. Signal name stays first so the family still sorts together.
    """
    seen = {}
    for m in model["messages"]:
        for s in m["signals"]:
            seen.setdefault(s["name"], []).append(m["frame_id"])
    qual = _qualifiers(model)
    renames, notes = {}, []
    for name, ids in seen.items():
        if len(ids) < 2:
            continue
        for fid in ids:
            renames[(fid, name)] = f"{name}_{qual[fid]}"
        notes.append(f"{name} x{len(ids)} -> " +
                     ", ".join(f"{name}_{qual[i]}" for i in ids))
    return renames, notes


def model_to_json(model):
    out, dropped, dlc_lost = {}, set(), []
    # Key base follows the source (hex for DBC/CSV, as-read for JSON) so a 0x120
    # message is not renumbered into "288" on the way out.
    base = model.get("id_base", 10)
    renames, rename_notes = _dedupe_signal_names(model)
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
                "fieldName": renames.get((m["frame_id"], s["name"]), s["name"]),
                "reverse": 0 if s["byte_order"] == "big_endian" else 1,
                "startingBit": s["start_bit"], "size": s["length"],
                "evData": int(s.get("ev_data") or 0),
                "multiplier": _num(s.get("scale", 1)), "offset": _num(s.get("offset", 0)),
                "signed": int(bool(s.get("is_signed"))),
            })
        out[json_id_key(m["frame_id"], base)] = arr
        # JSON carries no DLC; a reader must synthesise it as max(8, ceil(max_end/8)).
        # Name the messages where that guess will *not* reproduce the real DLC, so a
        # short-DLC frame (MG Commute 0x120 is 5 bytes, 0x348 is 6) is not silently
        # widened to 8 without anyone noticing.
        end = max((s["start_bit"] + s["length"] for s in m["signals"]), default=0)
        if m.get("dlc") and m["dlc"] != min(64, max(8, -(-end // 8))):
            dlc_lost.append(f"0x{m['frame_id']:X} (DLC {m['dlc']})")
    warnings = []
    if dropped:
        warnings.append("JSON has no field for: " + ", ".join(sorted(dropped)) + " - dropped.")
    if dlc_lost:
        shown = ", ".join(dlc_lost[:8]) + (f", +{len(dlc_lost) - 8} more" if len(dlc_lost) > 8 else "")
        warnings.append("JSON has no DLC field - these messages will read back as 8 "
                        "bytes: " + shown + ".")
    if rename_notes:
        warnings.append("Duplicate signal names qualified by their message (JSON keys "
                        "on fieldName): " + "; ".join(rename_notes) + ".")
    return json.dumps(out, indent=2), warnings


# --------------------------------------------------------------------------- #
# CSV  ⇄  model
# --------------------------------------------------------------------------- #
def model_to_csv(model):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    for m in model["messages"]:
        for s in m["signals"]:
            w.writerow([
                m["name"], f"0x{m['frame_id']:X}", m["frame_id"],
                int(bool(m.get("is_extended"))), m["dlc"],
                s["name"], s["start_bit"], s["length"],
                "Motorola" if s["byte_order"] == "big_endian" else "Intel",
                int(bool(s.get("is_signed"))), _num(s.get("scale", 1)), _num(s.get("offset", 0)),
                _blank(s.get("min")), _blank(s.get("max")), s.get("unit") or "",
                _fmt_value_table(s.get("value_table")),
                s.get("comment") or "", int(s.get("ev_data") or 0),
            ])
    return buf.getvalue(), []


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
    # Deliberately no id_base: a CSV carries *both* a hex and a decimal id column,
    # so it cannot say which base the data came from. Claiming hex here would flip
    # a decimal-keyed JSON to hex on a JSON -> CSV -> JSON round trip.
    return {"messages": [by_id[i] for i in order]}, warnings


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
# CanPlus XML is import-only (no serializer) — it has no place to round-trip to.
_PARSERS = {"dbc": dbc_to_model, "json": json_to_model, "csv": csv_to_model,
            "canplus": canplus.parse_to_model}
_SERIALIZERS = {"dbc": model_to_dbc, "json": model_to_json, "csv": model_to_csv}


def detect_format(filename: str, text: str) -> str:
    fn = (filename or "").lower()
    for ext in ("dbc", "json", "csv"):
        if fn.endswith("." + ext):
            return ext
    if "<CanData" in text[:5000]:        # CanPlus / telematics vehicle library
        return "canplus"
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
    """Parse a file into the canonical model."""
    if from_fmt is None:
        from_fmt = detect_format(filename, text)
    if from_fmt not in _PARSERS:
        raise ValueError(f"unknown source format: {from_fmt}")
    model, warnings = _PARSERS[from_fmt](text)
    _sort_model(model)
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
    _sort_model(model)
    content, warnings = _SERIALIZERS[to_fmt](model)
    return {"content": content, "warnings": warnings}


def convert(text: str, to_fmt: str, from_fmt: str | None = None, filename: str = ""):
    """One-shot parse + serialize. Returns ``{content, warnings, summary, from}``."""
    p = parse(text, from_fmt=from_fmt, filename=filename)
    s = serialize(p["model"], to_fmt)
    p["summary"]["to"] = to_fmt
    return {"content": s["content"], "warnings": p["warnings"] + s["warnings"],
            "summary": p["summary"], "from": p["from"]}
