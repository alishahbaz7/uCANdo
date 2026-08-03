"""Import a **CanPlus / telematics "vehicle library" config** (`*.Config.XML`,
root ``<CanData>``) into the converter's canonical model.

See `docs/CANPLUS_CONFIG_DECODE.md` for the full reverse-engineering write-up.
Short version of what is *decodable* from the file (verified byte-exact):

- Each ``<VarDesc RawDataStr="…">`` is a fixed **22-byte little-endian record**:
  ``b2-3``=VarID, ``b8-9``=multiplier, ``b10-11``=divider, ``b12-13``=offset,
  ``b17-19``=**source-frame signature** (signals sharing a CAN frame share it).
- The per-signal **name / units / function / scaling** come from the matching
  ``<Variable>`` attributes (and cross-check the binary exactly).

What is **not** in the file (encrypted): the literal **arbitration ID** and the
**bit position** of each signal. So this importer emits the signal dictionary +
scaling, **grouped by the verified frame-signature cluster**, with:

- real CAN id + real bit layout for the **two field-validated** signals
  (Odometer ``0x540``, Range/DTE ``0x2A2``), and
- **placeholder** ids/positions for the rest (clearly flagged) — to be resolved
  from a capture. Placeholders are laid out non-overlapping so DBC export stays
  valid; only the *position* is provisional, never the name/scale/units.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# VarID → field-validated real layout (CAN id + canonical big-endian start/len).
# Canonical start_bit is MSB-first sequential (the convert.py convention);
# Odometer DBC 7|24@0 → 0, Range/DTE DBC 55|16@0 → 48.
_VALIDATED = {
    0x8000: {"frame": 0x540, "start": 0, "length": 24, "dlc": 3, "tag": "Odometer"},
    0x803C: {"frame": 0x2A2, "start": 48, "length": 16, "dlc": 8, "tag": "Range/DTE"},
}


def _u16(b, i):
    return b[i] | (b[i + 1] << 8)


def _s16(b, i):
    v = _u16(b, i)
    return v - 0x10000 if v >= 0x8000 else v


def _sanitize(name: str, used: set) -> str:
    """A DBC-safe signal/message identifier, de-duplicated within its scope."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "").strip()).strip("_") or "SIG"
    if s[0].isdigit():
        s = "_" + s
    base, n = s, 2
    while s in used:
        s = f"{base}_{n}"; n += 1
    used.add(s)
    return s


def _num(x):
    f = float(x)
    return int(f) if f == int(f) else round(f, 6)


def parse_to_model(text: str):
    """Parse CanPlus XML → ``({"messages": [...]}, warnings)`` (convert.py shape)."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    warnings = []

    # vehicle / library meta (informational)
    veh = root.find(".//VehicleLibraryInfo/Vehicle")
    if veh is not None:
        warnings.append(
            "Vehicle library: {} {} {} (engine type {}).".format(
                veh.get("Brand", "?"), veh.get("ModelName", "?"),
                veh.get("ProductionYear", "?"), veh.get("EngineType", "?")))

    # collect one signal per <VarDesc> (carries both the 22-byte record + attrs)
    descs = root.findall(".//Variable_Descriptors/VarDesc")
    raw_sigs = []          # (cluster, varid, fields)
    for d in descs:
        hexstr = (d.get("RawDataStr") or "").replace("-", "").strip()
        try:
            b = bytes.fromhex(hexstr)
        except ValueError:
            b = b""
        if len(b) < 22:
            warnings.append(f"Skipped '{d.get('Name','?')}': short/invalid descriptor.")
            continue
        var = d.find("Variable")
        attrs = var.attrib if var is not None else {}
        varid = _u16(b, 2)
        mult = _u16(b, 8) or int(attrs.get("FW_Multiplier", 1) or 1)
        div = _u16(b, 10) or int(attrs.get("FW_Divider", 1) or 1)
        offset = _s16(b, 12)
        cluster = f"{b[17]:02X}{b[18]:02X}{b[19]:02X}"
        raw_sigs.append({
            "cluster": cluster, "varid": varid,
            "name": d.get("Name") or attrs.get("Title") or f"VAR_{varid:04X}",
            "scale": _num(mult / div) if div else _num(mult),
            "offset": _num(offset),
            "unit": (attrs.get("FW_Units") or "").strip(),
            "function": attrs.get("Var_Function", "NotAssigned"),
        })

    if not raw_sigs:
        raise ValueError("No <VarDesc> records found — not a CanPlus vehicle library?")

    # group by frame-signature cluster → one message per cluster
    groups = {}
    for s in raw_sigs:
        groups.setdefault(s["cluster"], []).append(s)

    messages = []
    for cluster, members in groups.items():
        members.sort(key=lambda s: s["varid"])
        validated = next((m for m in members if m["varid"] in _VALIDATED), None)
        if validated:
            v = _VALIDATED[validated["varid"]]
            frame_id, is_ext, dlc = v["frame"], False, v["dlc"]
            mname = f"FRAME_{frame_id:03X}"
        else:
            frame_id = int(cluster, 16)              # derived from the file's frame signature
            is_ext = frame_id > 0x7FF
            dlc = 0
            mname = f"FRAME_{cluster}"

        sig_names, signals, cursor = set(), [], 0
        for m in members:
            vmeta = _VALIDATED.get(m["varid"])
            is_state = (m["scale"] == 1 and m["offset"] == 0
                        and m["unit"] in ("", "state"))
            if vmeta:                                # real, field-validated layout
                start, length, order = vmeta["start"], vmeta["length"], "big_endian"
                note = f"✅ validated ({vmeta['tag']}) — real CAN id & bit layout"
            else:                                    # provisional placeholder layout
                length = 1 if is_state else 16
                start, order = cursor, "little_endian"
                cursor += length
                note = "⚠ placeholder bit layout — resolve from a capture"
            signals.append({
                "name": _sanitize(m["name"], sig_names),
                "start_bit": start, "length": length, "byte_order": order,
                "is_signed": False, "scale": m["scale"], "offset": m["offset"],
                "min": None, "max": None, "unit": m["unit"], "value_table": None,
                "comment": f"VarID 0x{m['varid']:04X} · {m['function']} · cluster {cluster} · {note}",
                "ev_data": 0,
            })
        if not dlc:
            dlc = min(64, max(1, -(-cursor // 8)))
        messages.append({"name": mname, "frame_id": frame_id,
                         "is_extended": is_ext, "dlc": dlc, "signals": signals})

    n_val = sum(1 for c in groups if any(m["varid"] in _VALIDATED for m in groups[c]))
    warnings.append(
        f"Extracted {len(raw_sigs)} signals in {len(messages)} frame-clusters. "
        f"CAN ids & bit positions are PLACEHOLDERS except {n_val} field-validated "
        "(Odometer 0x540, Range/DTE 0x2A2) — resolve the rest from a capture "
        "(see docs/CANPLUS_CONFIG_DECODE.md).")
    return {"messages": messages}, warnings
