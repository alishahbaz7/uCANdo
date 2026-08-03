"""DTC monitor — Diagnostic Trouble Codes across standards.

Passively decodes trouble codes seen on the bus and keeps the current set,
grouped by source:

* **OBD-II** Mode 03 (stored) / 07 (pending) / 0A (permanent) responses —
  2-byte codes decoded to the familiar ``P/C/B/U`` form.
* **UDS** service 0x19 ReadDTCInformation responses — 3-byte DTC + status byte
  (status bits expanded to names).
* **J1939** DM1 (active, PGN 0xFECA) / DM2 (previously active, PGN 0xFECB) —
  each 4-byte DTC split into SPN / FMI / occurrence count, with FMI text.

OBD-II/UDS codes normally arrive only in response to a request, so the server
exposes a "scan" that transmits the standard requests; J1939 DM1 is broadcast
periodically and shows up passively. Multi-frame (ISO-TP) DTC lists beyond a
single frame are not yet reassembled here — see the note in ``_consume_obd``.
"""

from __future__ import annotations

import threading
import time

OBD_RESPONSE_IDS = range(0x7E8, 0x7F0)
OBD_MODE_SID = {0x43: "Mode 03 · stored", 0x47: "Mode 07 · pending", 0x4A: "Mode 0A · permanent"}
_OBD_LETTERS = ["P", "C", "B", "U"]

# A small description table — extend freely; unknown codes still show raw.
DTC_DESCRIPTIONS = {
    "P0133": "O2 Sensor Circuit Slow Response (Bank 1 Sensor 1)",
    "P0171": "System Too Lean (Bank 1)",
    "P0300": "Random / Multiple Cylinder Misfire Detected",
    "P0420": "Catalyst System Efficiency Below Threshold (Bank 1)",
    "U0100": "Lost Communication With ECM/PCM",
}

# Standard J1939 Failure Mode Identifiers.
J1939_FMI = {
    0: "Data above normal (most severe)", 1: "Data below normal (most severe)",
    2: "Data erratic / intermittent", 3: "Voltage above normal / shorted high",
    4: "Voltage below normal / shorted low", 5: "Current below normal / open circuit",
    6: "Current above normal / grounded", 7: "Mechanical system not responding",
    8: "Abnormal frequency / pulse width", 9: "Abnormal update rate",
    10: "Abnormal rate of change", 11: "Root cause not known", 12: "Bad intelligent device",
    13: "Out of calibration", 14: "Special instructions", 15: "Data above normal (least severe)",
    16: "Data above normal (moderate)", 17: "Data below normal (least severe)",
    18: "Data below normal (moderate)", 19: "Received network data in error",
    31: "Condition exists",
}
J1939_SPN_NAMES = {
    84: "Wheel-based vehicle speed", 91: "Accelerator pedal position", 100: "Engine oil pressure",
    102: "Boost pressure", 110: "Engine coolant temperature", 175: "Engine oil temperature",
    190: "Engine speed", 247: "Engine total hours", 639: "J1939 network",
}

# ISO 14229 DTC status mask bits (bit 0 → bit 7).
UDS_STATUS_BITS = [
    "testFailed", "testFailedThisCycle", "pending", "confirmed",
    "testNotCompletedSinceClear", "testFailedSinceClear",
    "testNotCompletedThisCycle", "warningIndicator",
]


def _pgn_from_id(arb_id: int) -> int:
    data_page = (arb_id >> 24) & 0x1
    pf = (arb_id >> 16) & 0xFF
    ps = (arb_id >> 8) & 0xFF
    return (data_page << 16) | (pf << 8) | (ps if pf >= 240 else 0)


def decode_obd_dtc(b1: int, b2: int) -> str:
    letter = _OBD_LETTERS[(b1 >> 6) & 0x3]
    return f"{letter}{(b1 >> 4) & 0x3}{b1 & 0xF:X}{b2:02X}"


class DtcMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        # group -> { code -> record }
        self._dtcs: dict[str, dict] = {}
        # ISO-TP reassembly buffers, keyed by responder arbitration ID, so DTC
        # lists spanning multiple frames are recombined before decoding.
        self._isotp: dict[int, dict] = {}

    def _put(self, group: str, code: str, rec: dict) -> None:
        with self._lock:
            g = self._dtcs.setdefault(group, {})
            existing = g.get(code)
            rec["code"] = code
            rec["ts"] = round(time.time(), 3)
            rec["seen"] = (existing["seen"] + 1) if existing else 1
            g[code] = rec

    # ----- live tap --------------------------------------------------------
    def consume(self, msg) -> None:
        data = bytes(msg.data)
        if not data:
            return
        if msg.is_extended_id:
            self._consume_j1939(msg.arbitration_id, data)
        elif msg.arbitration_id in OBD_RESPONSE_IDS:
            self._consume_obd(msg.arbitration_id, data)

    def _consume_obd(self, arb_id: int, data: bytes) -> None:
        """Feed an OBD/UDS responder frame through ISO-TP, decode when complete."""
        pci = data[0] >> 4
        if pci == 0x0:                       # Single frame
            length = data[0] & 0x0F
            self._isotp.pop(arb_id, None)    # abandon any stale partial
            self._decode_dtc_service(data[1:1 + length])
        elif pci == 0x1 and len(data) >= 2:  # First frame
            total = ((data[0] & 0x0F) << 8) | data[1]
            self._isotp[arb_id] = {"data": bytearray(data[2:8]), "remaining": total - 6}
        elif pci == 0x2:                     # Consecutive frame
            st = self._isotp.get(arb_id)
            if not st:
                return
            take = min(7, st["remaining"])
            st["data"].extend(data[1:1 + take])
            st["remaining"] -= take
            if st["remaining"] <= 0:
                self._decode_dtc_service(bytes(self._isotp.pop(arb_id)["data"]))

    def _decode_dtc_service(self, payload: bytes) -> None:
        """Decode a fully-reassembled OBD Mode 03/07/0A or UDS 0x59 response."""
        if not payload:
            return
        sid = payload[0]
        if sid in OBD_MODE_SID:
            body = payload[1:]
            if len(body) % 2 == 1:      # optional leading DTC-count byte
                body = body[1:]
            for i in range(0, len(body) - 1, 2):
                b1, b2 = body[i], body[i + 1]
                if b1 == 0 and b2 == 0:
                    continue
                code = decode_obd_dtc(b1, b2)
                self._put(f"OBD-II · {OBD_MODE_SID[sid]}", code,
                          {"desc": DTC_DESCRIPTIONS.get(code, ""), "status": "", "source": "OBD-II"})
        elif sid == 0x59:               # UDS ReadDTCInformation response
            self._consume_uds_19(payload)

    def _consume_uds_19(self, payload: bytes) -> None:
        # 0x59 <subfunc> <statusAvailabilityMask> then records of DTC(3) + status(1).
        # Records start after SID(1) + subfunction(1) + availability mask(1).
        body = payload[3:] if len(payload) >= 3 else b""
        for i in range(0, len(body) - 3, 4):
            b1, b2, b3, st = body[i], body[i + 1], body[i + 2], body[i + 3]
            if b1 == 0 and b2 == 0 and b3 == 0:
                continue
            code = decode_obd_dtc(b1, b2) + f"-{b3:02X}"
            flags = [name for bit, name in enumerate(UDS_STATUS_BITS) if st & (1 << bit)]
            self._put("UDS · ReadDTCInformation", code,
                      {"desc": DTC_DESCRIPTIONS.get(code[:5], ""), "status": ", ".join(flags) or f"0x{st:02X}",
                       "source": "UDS"})

    def _consume_j1939(self, arb_id: int, data: bytes) -> None:
        pgn = _pgn_from_id(arb_id)
        if pgn == 0xFECA:
            group = "J1939 · DM1 active"
        elif pgn == 0xFECB:
            group = "J1939 · DM2 previously active"
        else:
            return
        # bytes 0-1 = lamp status; DTCs are 4 bytes each from byte 2.
        i = 2
        while i + 4 <= len(data):
            c = data[i:i + 4]
            spn = c[0] | (c[1] << 8) | ((c[2] >> 5) << 16)
            fmi = c[2] & 0x1F
            oc = c[3] & 0x7F
            i += 4
            if spn in (0, 0x7FFFF) and fmi == 0:   # padding / no-DTC
                continue
            code = f"SPN {spn} / FMI {fmi}"
            self._put(group, code, {
                "desc": J1939_SPN_NAMES.get(spn, ""), "status": J1939_FMI.get(fmi, ""),
                "spn": spn, "fmi": fmi, "oc": oc, "source": "J1939",
            })

    # ----- read API --------------------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            groups = []
            total = 0
            for group in sorted(self._dtcs):
                items = sorted(self._dtcs[group].values(), key=lambda r: r["code"])
                for it in items:
                    it["stale"] = (now - it["ts"]) > 5.0
                total += len(items)
                groups.append({"group": group, "items": items})
            return {"count": total, "groups": groups}

    def clear(self) -> None:
        with self._lock:
            self._dtcs.clear()
