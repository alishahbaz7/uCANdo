"""DBC Builder — edit a message/signal database and export to ``.dbc``.

The working model is plain JSON-able dicts (so the web UI can read/write it
directly); cantools is only used at the boundary to import an existing ``.dbc``
and to serialize the model back out to valid DBC text.

Signal ``start_bit`` is stored in cantools' own convention: for little-endian
(Intel) it's the LSB position ``byte*8 + bit``; for big-endian (Motorola) it's
the Vector sawtooth position of the signal's most significant bit. The
:func:`re_candidate_to_signal` helper converts the Reverse-Engineering module's
sequential MSB-first bit index into that big-endian start bit, so RE candidates
import cleanly.
"""

from __future__ import annotations

import cantools
from cantools.database.can import Database, Message, Signal
from cantools.database.conversion import BaseConversion


def re_candidate_to_signal(start_bit_seq: int, length: int, name: str) -> dict:
    """Convert an RE candidate (sequential MSB-first bit index) to a signal dict.

    RE bit index 0 = byte0/bit7. cantools big-endian start = byte*8 + (7 - bit).
    """
    byte = start_bit_seq // 8
    bit_in_byte = start_bit_seq % 8
    dbc_start = byte * 8 + (7 - bit_in_byte)
    return {
        "name": name,
        "start_bit": dbc_start,
        "length": length,
        "byte_order": "big_endian",
        "is_signed": False,
        "scale": 1.0,
        "offset": 0.0,
        "minimum": None,
        "maximum": None,
        "unit": "",
        "comment": "",
    }


def _default_signal(name: str) -> dict:
    return {
        "name": name, "start_bit": 0, "length": 8, "byte_order": "little_endian",
        "is_signed": False, "scale": 1.0, "offset": 0.0,
        "minimum": None, "maximum": None, "unit": "", "comment": "",
    }


class DbcModel:
    def __init__(self):
        # frame_id (int) -> message dict
        self.messages: dict[int, dict] = {}

    # ----- editing ---------------------------------------------------------
    def add_message(self, frame_id: int, name: str, length: int = 8,
                    is_extended: bool = False) -> dict:
        msg = {
            "frame_id": int(frame_id),
            "name": name or f"MSG_{frame_id:X}",
            "length": int(length),
            "is_extended": bool(is_extended),
            "comment": "",
            "signals": [],
        }
        self.messages[int(frame_id)] = msg
        return msg

    def remove_message(self, frame_id: int) -> None:
        self.messages.pop(int(frame_id), None)

    def add_signal(self, frame_id: int, signal: dict | None = None) -> dict:
        msg = self.messages[int(frame_id)]
        sig = {**_default_signal(f"sig_{len(msg['signals'])}"), **(signal or {})}
        msg["signals"].append(sig)
        return sig

    def update_signal(self, frame_id: int, index: int, patch: dict) -> dict:
        sig = self.messages[int(frame_id)]["signals"][index]
        sig.update(patch)
        return sig

    def remove_signal(self, frame_id: int, index: int) -> None:
        self.messages[int(frame_id)]["signals"].pop(index)

    def seed_from_re(self, re_id: dict) -> dict:
        """Create a message + signals from one Reverse-Engineering ID result."""
        msg = self.add_message(re_id["id"], re_id.get("id_hex", f"MSG_{re_id['id']:X}"),
                               length=re_id.get("length", 8), is_extended=re_id.get("ext", False))
        msg["name"] = f"MSG_{re_id['id_hex']}"
        for cand in re_id.get("candidates", []):
            sig = re_candidate_to_signal(cand["start_bit"], cand["length"], cand["name"])
            # Carry through any recovered metadata (e.g. LibreCAN scale/offset/unit,
            # detected byte order) so correlation/promote results aren't flattened.
            for k in ("scale", "offset", "unit", "byte_order", "is_signed", "comment"):
                if cand.get(k) is not None:
                    sig[k] = cand[k]
            msg["signals"].append(sig)
        return msg

    # ----- (de)serialization ----------------------------------------------
    def to_json(self) -> dict:
        return {"messages": sorted(self.messages.values(), key=lambda m: m["frame_id"])}

    def load_json(self, data: dict) -> None:
        self.messages = {int(m["frame_id"]): m for m in data.get("messages", [])}

    def _to_cantools_db(self) -> Database:
        db = Database()
        for msg in self.messages.values():
            signals = []
            for s in msg["signals"]:
                conversion = BaseConversion.factory(
                    scale=float(s.get("scale", 1) or 1),
                    offset=float(s.get("offset", 0) or 0),
                    is_float=bool(s.get("is_float", False)),
                )
                signals.append(Signal(
                    name=s["name"],
                    start=int(s["start_bit"]),
                    length=int(s["length"]),
                    byte_order=s.get("byte_order", "little_endian"),
                    is_signed=bool(s.get("is_signed", False)),
                    conversion=conversion,
                    minimum=s.get("minimum"),
                    maximum=s.get("maximum"),
                    unit=s.get("unit") or None,
                    comment=s.get("comment") or None,
                ))
            db.messages.append(Message(
                frame_id=int(msg["frame_id"]),
                name=msg["name"],
                length=int(msg["length"]),
                signals=signals,
                comment=msg.get("comment") or None,
                is_extended_frame=bool(msg.get("is_extended", False)),
            ))
        db.refresh()
        return db

    def to_dbc_string(self) -> str:
        return self._to_cantools_db().as_dbc_string()

    def import_dbc_string(self, text: str) -> None:
        db = cantools.database.load_string(text, database_format="dbc")
        self.messages = {}
        for m in db.messages:
            self.messages[m.frame_id] = {
                "frame_id": m.frame_id,
                "name": m.name,
                "length": m.length,
                "is_extended": bool(m.is_extended_frame),
                "comment": m.comment or "",
                "signals": [{
                    "name": s.name, "start_bit": s.start, "length": s.length,
                    "byte_order": s.byte_order, "is_signed": s.is_signed,
                    "scale": s.scale, "offset": s.offset,
                    "minimum": s.minimum, "maximum": s.maximum,
                    "unit": s.unit or "", "comment": s.comment or "",
                } for s in m.signals],
            }
