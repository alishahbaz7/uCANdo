"""DBC frame decoder + byte/bit mapping."""

import cantools

from ucando.dbc_builder import DbcModel
from ucando.framedecode import decode_frame, decode_frames, _normalize


def _db():
    m = DbcModel()
    m.add_message(0x94, "M94", length=8)
    m.add_signal(0x94, {"name": "Speed", "start_bit": 3, "length": 12,
                        "byte_order": "big_endian", "scale": 10, "offset": 0})
    m.add_message(0x540, "M540", length=3)
    m.add_signal(0x540, {"name": "Odometer", "start_bit": 7, "length": 24,
                         "byte_order": "big_endian", "scale": 1, "offset": 0})
    return cantools.database.load_string(m.to_dbc_string(), database_format="dbc")


def test_normalize_leading_zeros_and_dlc():
    assert _normalize("205000000000200", 4) == bytes.fromhex("02050000")  # lost lead zero + trim to DLC
    assert _normalize("0128C30000000000", 3) == bytes.fromhex("0128C3")
    assert _normalize("8", 1) == b"\x08"


def test_decode_values_and_cells():
    f = decode_frame(_db(), 0x94, "0006320040001C00")
    speed = next(s for s in f["signals"] if s["name"] == "Speed")
    assert speed["raw"] == 6 and float(speed["physical"]) == 60.0
    assert len(speed["cells"]) == 12                 # 12-bit signal -> 12 grid cells
    assert f["bytes"][1] == 0x06


def test_odometer_full_24bit():
    f = decode_frame(_db(), 0x540, "0128C30000000000")
    odo = f["signals"][0]
    assert odo["name"] == "Odometer" and odo["raw"] == 0x0128C3
    assert len(odo["cells"]) == 24


def test_decode_frames_hex_ids_and_errors():
    res = decode_frames(_db(), [{"id": "94", "data": "0006320040001C00"},
                                {"id": "999", "data": "00"}])   # 0x999 not in DBC
    assert res[0]["name"] == "M94"
    assert "error" in res[1]


def test_short_payload_pads_right():
    """A short-DLC payload keeps byte 0 at byte 0 (was left-padded, shifting it)."""
    from ucando.framedecode import _normalize
    assert _normalize("0002FEA200", 8) == bytes([0x00, 0x02, 0xFE, 0xA2, 0, 0, 0, 0])
    assert _normalize("94", 8)[0] == 0x94
    assert _normalize("FF" * 16, 8) == b"\xff" * 8        # oversized still truncates
