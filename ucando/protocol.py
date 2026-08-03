"""Protocol Decoder — interpret frames as OBD-II, UDS (ISO-TP) or J1939.

A single :func:`decode_frame` classifies one frame and returns a human-readable
interpretation. :class:`ProtocolDecoder` adds stateful ISO-TP reassembly so
multi-frame UDS/OBD responses (First + Consecutive frames) are recombined into
the full service payload before decoding.

The tables here cover the commonly-needed subset for day-to-day work, not the
entire standards; unknown codes are reported with their raw value rather than
dropped.
"""

from __future__ import annotations

# ---- OBD-II -----------------------------------------------------------------
OBD_REQUEST_ID = 0x7DF
OBD_RESPONSE_IDS = range(0x7E8, 0x7F0)

OBD_MODES = {
    0x01: "Show current data", 0x02: "Show freeze frame", 0x03: "Show DTCs",
    0x04: "Clear DTCs", 0x06: "Test results", 0x07: "Pending DTCs",
    0x09: "Vehicle info",
}

# PID -> (name, decoder(data_bytes) -> str). data_bytes excludes mode+pid.
def _obd_temp(d):     return f"{d[0] - 40} °C" if d else "?"
def _obd_rpm(d):      return f"{((d[0] << 8) + d[1]) / 4:.0f} rpm" if len(d) >= 2 else "?"
def _obd_speed(d):    return f"{d[0]} km/h" if d else "?"
def _obd_pct(d):      return f"{d[0] * 100 / 255:.1f} %" if d else "?"
def _obd_load(d):     return f"{d[0] * 100 / 255:.1f} %" if d else "?"

OBD_PIDS = {
    0x04: ("Engine load", _obd_load),
    0x05: ("Coolant temp", _obd_temp),
    0x0C: ("Engine RPM", _obd_rpm),
    0x0D: ("Vehicle speed", _obd_speed),
    0x0F: ("Intake air temp", _obd_temp),
    0x11: ("Throttle position", _obd_pct),
    0x2F: ("Fuel level", _obd_pct),
}

# ---- UDS --------------------------------------------------------------------
UDS_SERVICES = {
    0x10: "DiagnosticSessionControl", 0x11: "ECUReset", 0x14: "ClearDTC",
    0x19: "ReadDTCInformation", 0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress", 0x27: "SecurityAccess",
    0x2E: "WriteDataByIdentifier", 0x31: "RoutineControl",
    0x34: "RequestDownload", 0x36: "TransferData", 0x37: "RequestTransferExit",
    0x3E: "TesterPresent", 0x85: "ControlDTCSetting",
}
UDS_NRC = {
    0x10: "general reject", 0x11: "service not supported", 0x12: "sub-function not supported",
    0x13: "incorrect length", 0x22: "conditions not correct", 0x31: "request out of range",
    0x33: "security access denied", 0x35: "invalid key", 0x78: "response pending",
}

# ---- J1939 ------------------------------------------------------------------
J1939_PGN_NAMES = {
    0xF004: "EEC1 (Electronic Engine Controller 1)",
    0xFEF1: "Cruise Control / Vehicle Speed",
    0xFEEE: "Engine Temperature 1",
    0xFEF6: "Intake/Exhaust Conditions",
    0xF003: "EEC2",
    0xFEE9: "Fuel Consumption",
}


def decode_j1939_id(arb_id: int) -> dict:
    """Decompose a 29-bit J1939 identifier into priority/PGN/source address."""
    # 29-bit layout: PRIO(3) EDP(1) DP(1) PF(8) PS(8) SA(8)
    priority = (arb_id >> 26) & 0x7
    data_page = (arb_id >> 24) & 0x1
    pdu_format = (arb_id >> 16) & 0xFF
    pdu_specific = (arb_id >> 8) & 0xFF
    source = arb_id & 0xFF
    if pdu_format < 240:               # PDU1 — destination-specific, PS not part of PGN
        pgn = (data_page << 16) | (pdu_format << 8)
        destination = pdu_specific
    else:                              # PDU2 — broadcast, PS is the group extension
        pgn = (data_page << 16) | (pdu_format << 8) | pdu_specific
        destination = None
    return {
        "priority": priority, "pgn": pgn,
        "pgn_hex": f"{pgn:04X}", "pgn_name": J1939_PGN_NAMES.get(pgn & 0xFFFF, ""),
        "source": source, "destination": destination,
    }


def _decode_obd(data: bytes, is_response: bool) -> dict | None:
    if len(data) < 2:
        return None
    # ISO-TP single frame: first nibble 0 = SF, low nibble = length.
    length = data[0] & 0x0F
    payload = data[1:1 + length]
    if not payload:
        return None
    mode = payload[0]
    if is_response:
        mode -= 0x40
    # Not a recognised OBD mode (e.g. a UDS 0x7F negative response that happens
    # to share the 0x7E8 ID) — let the caller fall through to the UDS decoder.
    if mode not in OBD_MODES:
        return None
    info = {"protocol": "OBD-II", "mode": f"0x{mode:02X}",
            "mode_name": OBD_MODES.get(mode, "?")}
    if mode in (0x01, 0x02) and len(payload) >= 2:
        pid = payload[1]
        name, decoder = OBD_PIDS.get(pid, (f"PID 0x{pid:02X}", None))
        info["pid"] = f"0x{pid:02X}"
        info["pid_name"] = name
        if is_response and decoder:
            info["value"] = decoder(payload[2:])
    return info


def _decode_uds(payload: bytes) -> dict | None:
    if not payload:
        return None
    sid = payload[0]
    if sid == 0x7F and len(payload) >= 3:   # negative response
        return {"protocol": "UDS", "type": "negative",
                "service": UDS_SERVICES.get(payload[1], f"0x{payload[1]:02X}"),
                "nrc": f"0x{payload[2]:02X}",
                "nrc_name": UDS_NRC.get(payload[2], "?")}
    is_resp = sid >= 0x40 and (sid - 0x40) in UDS_SERVICES
    base = sid - 0x40 if is_resp else sid
    if base not in UDS_SERVICES:
        return None
    info = {"protocol": "UDS", "type": "response" if is_resp else "request",
            "service": UDS_SERVICES[base], "sid": f"0x{base:02X}"}
    if base == 0x22 and len(payload) >= 3:  # ReadDataByIdentifier
        did = (payload[1] << 8) | payload[2]
        info["did"] = f"0x{did:04X}"
        if is_resp:
            info["data"] = payload[3:].hex(" ").upper()
    return info


class ProtocolDecoder:
    """Stateful decoder with ISO-TP reassembly per source ID."""

    def __init__(self):
        # arb_id -> {"data": bytearray, "remaining": int}
        self._isotp: dict[int, dict] = {}

    def decode(self, arb_id: int, data: bytes, is_extended: bool = False) -> dict:
        data = bytes(data)
        # J1939 lives on 29-bit IDs.
        if is_extended:
            j = decode_j1939_id(arb_id)
            j["protocol"] = "J1939"
            j["data"] = data.hex(" ").upper()
            return j

        is_obd_resp = arb_id in OBD_RESPONSE_IDS
        is_obd_req = arb_id == OBD_REQUEST_ID

        # ISO-TP framing (UDS / multi-frame OBD).
        if data:
            pci = data[0] >> 4
            if pci == 0x1:   # First frame
                total = ((data[0] & 0x0F) << 8) | data[1]
                self._isotp[arb_id] = {"data": bytearray(data[2:]), "remaining": total - 6}
                return {"protocol": "ISO-TP", "type": "first", "total_len": total,
                        "data": data.hex(" ").upper()}
            if pci == 0x2:   # Consecutive frame
                st = self._isotp.get(arb_id)
                if st:
                    take = min(7, st["remaining"])
                    st["data"].extend(data[1:1 + take])
                    st["remaining"] -= take
                    if st["remaining"] <= 0:
                        full = bytes(self._isotp.pop(arb_id)["data"])
                        decoded = _decode_uds(full) or {"protocol": "ISO-TP", "type": "reassembled"}
                        decoded["data"] = full.hex(" ").upper()
                        return decoded
                return {"protocol": "ISO-TP", "type": "consecutive",
                        "data": data.hex(" ").upper()}

        # Single-frame OBD takes priority on its known IDs.
        if is_obd_req or is_obd_resp:
            obd = _decode_obd(data, is_obd_resp)
            if obd:
                return obd

        # Single-frame UDS (strip the SF length byte).
        if data and (data[0] >> 4) == 0x0:
            length = data[0] & 0x0F
            uds = _decode_uds(data[1:1 + length])
            if uds:
                return uds

        return {"protocol": "raw", "data": data.hex(" ").upper()}
