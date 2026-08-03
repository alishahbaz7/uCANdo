"""DTC monitor — single-frame and the new ISO-TP multi-frame reassembly."""

import can

from ucando.dtc import DtcMonitor, decode_obd_dtc


def _all_codes(snap):
    return {it["code"] for g in snap["groups"] for it in g["items"]}


def test_decode_obd_dtc_letters():
    assert decode_obd_dtc(0x01, 0x33) == "P0133"
    assert decode_obd_dtc(0x04, 0x20) == "P0420"


def test_single_frame_mode03():
    m = DtcMonitor()
    # SF: count=2, P0133 + P0420 (as the simulator emits).
    m.consume(can.Message(arbitration_id=0x7E8, is_extended_id=False,
                          data=bytes([0x06, 0x43, 0x02, 0x01, 0x33, 0x04, 0x20, 0x00])))
    snap = m.snapshot()
    assert snap["count"] == 2
    assert {"P0133", "P0420"} <= _all_codes(snap)


def test_multiframe_isotp_mode03_reassembly():
    m = DtcMonitor()
    rid = 0x7E8
    # 14-byte Mode 03 response: SID, count=6, then six 2-byte DTCs.
    m.consume(can.Message(arbitration_id=rid, is_extended_id=False,
                          data=bytes([0x10, 0x0E, 0x43, 0x06, 0x01, 0x33, 0x01, 0x71])))
    m.consume(can.Message(arbitration_id=rid, is_extended_id=False,
                          data=bytes([0x21, 0x03, 0x00, 0x04, 0x20, 0x01, 0x01, 0x01])))
    m.consume(can.Message(arbitration_id=rid, is_extended_id=False,
                          data=bytes([0x22, 0x02, 0, 0, 0, 0, 0, 0])))
    snap = m.snapshot()
    assert snap["count"] == 6
    assert {"P0133", "P0171", "P0300", "P0420", "P0101", "P0102"} <= _all_codes(snap)


def test_j1939_dm1_passive():
    m = DtcMonitor()
    arb = (3 << 26) | (0xFE << 16) | (0xCA << 8) | 0x00   # DM1, PGN 0xFECA
    m.consume(can.Message(arbitration_id=arb, is_extended_id=True,
                          data=bytes([0x00, 0xFF, 0x64, 0x00, 0x01, 0x01, 0xFF, 0xFF])))
    snap = m.snapshot()
    codes = _all_codes(snap)
    assert any("SPN 100" in c for c in codes)
