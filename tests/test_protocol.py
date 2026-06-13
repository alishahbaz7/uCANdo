"""Protocol decoding: OBD-II, UDS, J1939 and ISO-TP reassembly."""

from canforge.protocol import ProtocolDecoder, decode_j1939_id


def test_obd_rpm_response():
    d = ProtocolDecoder()
    # 0x7E8, SF len 4: 0x41 (mode 01 resp) PID 0x0C, raw 0x0FA0 -> 1000 rpm.
    res = d.decode(0x7E8, bytes([0x04, 0x41, 0x0C, 0x0F, 0xA0, 0, 0, 0]))
    assert res["protocol"] == "OBD-II"
    assert "1000" in res["value"]


def test_j1939_id_decode():
    arb = (3 << 26) | (0xF0 << 16) | (0x04 << 8) | 0x00
    j = decode_j1939_id(arb)
    assert j["pgn"] == 0xF004
    assert j["priority"] == 3
    assert j["source"] == 0x00


def test_uds_read_data_by_identifier_request():
    d = ProtocolDecoder()
    res = d.decode(0x700, bytes([0x03, 0x22, 0xF1, 0x90, 0, 0, 0, 0]))
    assert res["protocol"] == "UDS"
    assert res["service"] == "ReadDataByIdentifier"
    assert res["did"] == "0xF190"


def test_isotp_multiframe_reassembly():
    d = ProtocolDecoder()
    # First frame: total len 14, carries 6 payload bytes (UDS 0x62 RDBI resp).
    ff = d.decode(0x7E8, bytes([0x10, 14, 0x62, 0xF1, 0x90, 0x01, 0x02, 0x03]))
    assert ff["type"] == "first"
    # Consecutive frames complete the 14-byte payload.
    d.decode(0x7E8, bytes([0x21, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A]))
    res = d.decode(0x7E8, bytes([0x22, 0x0B, 0, 0, 0, 0, 0, 0]))
    assert res["protocol"] == "UDS"
    assert res["service"] == "ReadDataByIdentifier"
