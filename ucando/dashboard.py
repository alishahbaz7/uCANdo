"""Dashboard — live decoded values for standard protocols.

Unlike the Signal Viewer (which needs a user-supplied DBC), the Dashboard
decodes *standardised* parameters that need no DBC: OBD-II Mode 01 PIDs and
common J1939 SPNs. It taps the live bus, keeps the latest numeric value for
each known parameter, and groups them by standard for a gauge-style page.

Tables here cover the everyday subset (engine speed, vehicle speed,
temperatures, throttle, fuel, load). Add rows to ``OBD_PIDS`` / ``J1939_PGNS``
to extend coverage — the consume/snapshot machinery needs no changes.
"""

from __future__ import annotations

import threading
import time

# OBD-II response IDs (functional + physical ECU responses).
OBD_RESPONSE_IDS = range(0x7E8, 0x7F0)

# pid -> (name, unit, decoder(payload_bytes_after_pid) -> float | None)
OBD_PIDS = {
    0x04: ("Engine load", "%",   lambda d: d[0] * 100 / 255 if d else None),
    0x05: ("Coolant temp", "°C", lambda d: d[0] - 40 if d else None),
    0x0A: ("Fuel pressure", "kPa", lambda d: d[0] * 3 if d else None),
    0x0B: ("Intake MAP", "kPa",  lambda d: d[0] if d else None),
    0x0C: ("Engine RPM", "rpm",  lambda d: ((d[0] << 8) + d[1]) / 4 if len(d) >= 2 else None),
    0x0D: ("Vehicle speed", "km/h", lambda d: d[0] if d else None),
    0x0F: ("Intake air temp", "°C", lambda d: d[0] - 40 if d else None),
    0x10: ("MAF rate", "g/s",    lambda d: ((d[0] << 8) + d[1]) / 100 if len(d) >= 2 else None),
    0x11: ("Throttle pos", "%",  lambda d: d[0] * 100 / 255 if d else None),
    0x2F: ("Fuel level", "%",    lambda d: d[0] * 100 / 255 if d else None),
    0x42: ("Ctrl module V", "V", lambda d: ((d[0] << 8) + d[1]) / 1000 if len(d) >= 2 else None),
    0x46: ("Ambient temp", "°C", lambda d: d[0] - 40 if d else None),
}

# pgn -> (group_label, [ {name, unit, start, length, scale, offset, spn} ... ])
# start = 0-based byte index into the 8-byte payload; multi-byte values are
# little-endian (J1939 convention).
J1939_PGNS = {
    0xF004: ("EEC1", [
        {"name": "Engine speed", "unit": "rpm", "start": 3, "length": 2, "scale": 0.125, "offset": 0, "spn": 190},
        {"name": "Actual torque", "unit": "%", "start": 2, "length": 1, "scale": 1, "offset": -125, "spn": 513},
    ]),
    0xFEF1: ("CCVS", [
        {"name": "Wheel speed", "unit": "km/h", "start": 1, "length": 2, "scale": 1 / 256, "offset": 0, "spn": 84},
    ]),
    0xFEEE: ("ET1", [
        {"name": "Coolant temp", "unit": "°C", "start": 0, "length": 1, "scale": 1, "offset": -40, "spn": 110},
        {"name": "Fuel temp", "unit": "°C", "start": 1, "length": 1, "scale": 1, "offset": -40, "spn": 174},
    ]),
    0xFEF2: ("LFE1", [
        {"name": "Fuel rate", "unit": "L/h", "start": 0, "length": 2, "scale": 0.05, "offset": 0, "spn": 183},
    ]),
    0xF003: ("EEC2", [
        {"name": "Accel pedal", "unit": "%", "start": 1, "length": 1, "scale": 0.4, "offset": 0, "spn": 91},
    ]),
    0xFEF6: ("IC1", [
        {"name": "Boost pressure", "unit": "kPa", "start": 1, "length": 1, "scale": 2, "offset": 0, "spn": 102},
    ]),
}


def _pgn_from_id(arb_id: int) -> int:
    data_page = (arb_id >> 24) & 0x1
    pf = (arb_id >> 16) & 0xFF
    ps = (arb_id >> 8) & 0xFF
    if pf < 240:
        return (data_page << 16) | (pf << 8)
    return (data_page << 16) | (pf << 8) | ps


class Dashboard:
    def __init__(self):
        self._lock = threading.Lock()
        # group -> { name -> {value, unit, source, ts, spn?/pid?} }
        self._values: dict[str, dict] = {}

    def _put(self, group: str, name: str, value, unit: str, **extra) -> None:
        if value is None:
            return
        with self._lock:
            self._values.setdefault(group, {})[name] = {
                "name": name, "value": round(float(value), 3), "unit": unit,
                "ts": round(time.time(), 3), **extra,
            }

    # ----- live tap --------------------------------------------------------
    def consume(self, msg) -> None:
        data = bytes(msg.data)
        if not data:
            return
        if msg.is_extended_id:
            self._consume_j1939(msg.arbitration_id, data)
        elif msg.arbitration_id in OBD_RESPONSE_IDS:
            self._consume_obd(data)

    def _consume_obd(self, data: bytes) -> None:
        # ISO-TP single frame: high nibble 0, low nibble = length.
        if (data[0] >> 4) != 0:
            return
        length = data[0] & 0x0F
        payload = data[1:1 + length]
        if len(payload) < 2 or payload[0] != 0x41:   # Mode 01 positive response
            return
        pid = payload[1]
        entry = OBD_PIDS.get(pid)
        if not entry:
            return
        name, unit, fn = entry
        self._put("OBD-II", name, fn(payload[2:]), unit, pid=f"0x{pid:02X}")

    def _consume_j1939(self, arb_id: int, data: bytes) -> None:
        pgn = _pgn_from_id(arb_id)
        spec = J1939_PGNS.get(pgn & 0x3FFFF) or J1939_PGNS.get(pgn & 0xFFFF)
        if not spec:
            return
        group, fields = spec
        for f in fields:
            seg = data[f["start"]:f["start"] + f["length"]]
            if len(seg) < f["length"]:
                continue
            raw = int.from_bytes(seg, "little")
            # 0xFF.. = "not available" per J1939.
            if raw == (1 << (8 * f["length"])) - 1:
                continue
            self._put(f"J1939 · {group}", f["name"], raw * f["scale"] + f["offset"],
                      f["unit"], spn=f["spn"])

    # ----- read API --------------------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            groups = []
            for group in sorted(self._values):
                items = sorted(self._values[group].values(), key=lambda v: v["name"])
                for it in items:
                    it["stale"] = (now - it["ts"]) > 3.0
                groups.append({"group": group, "items": items})
            return {"groups": groups}

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
