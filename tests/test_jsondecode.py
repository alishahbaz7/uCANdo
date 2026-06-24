"""Signature-JSON frame decoder — convention locked by real vehicle frames.

These two frames came from the MG ZS EV and pin down the bit/byte convention
(see docs/JSON_SIGNATURE_DECODE.md):
  * id 900 / 0205000000000200 → Seat_belt_passenger = 1
  * id 912 / 0128C30000000000 → canOdometer = 75971
If either assertion ever fails, the decode convention has drifted.
"""

import json

from canforge import jsondecode as jd

SIGNATURE = {
    "900": [
        {"fieldName": "Seat_belt_passenger", "reverse": 0, "startingBit": 8, "size": 1, "multiplier": 1, "offset": 0, "signed": 0},
        {"fieldName": "Seat_belt_driver", "reverse": 0, "startingBit": 12, "size": 1, "multiplier": 1, "offset": 0, "signed": 0},
    ],
    "909": [
        {"fieldName": "soc", "reverse": 0, "startingBit": 24, "size": 16, "multiplier": 0.1, "offset": 0, "signed": 0},
        {"fieldName": "Batt_Current", "reverse": 0, "startingBit": 56, "size": 16, "multiplier": 0.05, "offset": 1000, "signed": 0},
    ],
    "912": [
        {"fieldName": "canOdometer", "reverse": 0, "startingBit": 0, "size": 24, "multiplier": 1, "offset": 0, "signed": 0},
    ],
}


def _msgs():
    return jd.load_signature(json.dumps(SIGNATURE))


def test_single_bit_lsb_first():
    # byte1 = 0x05 → LSB set; startingBit 8 = byte1's LSB → passenger = 1
    f = jd.decode_frame(_msgs(), 900, "0205000000000200")
    by_name = {s["name"]: s["raw"] for s in f["signals"]}
    assert by_name["Seat_belt_passenger"] == 1
    assert by_name["Seat_belt_driver"] == 0


def test_multibyte_big_endian_odometer():
    # bytes 0,1,2 = 01 28 C3 assembled big-endian = 0x0128C3 = 75971
    f = jd.decode_frame(_msgs(), 912, "0128C30000000000")
    odo = f["signals"][0]
    assert odo["raw"] == 75971
    assert odo["physical"] == "75971"
    assert odo["byte_order"] == "big_endian"


def test_scale_and_offset_applied():
    # msg 909 is 9 bytes (Batt_Current spills past byte 7); soc ×0.1 sits in
    # bytes 3-4 big-endian. byte4 = 0x64 (=100) → 100 * 0.1 = 10.0
    f = jd.decode_frame(_msgs(), 909, "000000006400000000")
    soc = next(s for s in f["signals"] if s["name"] == "soc")
    assert soc["raw"] == 100
    assert soc["physical"] == "10.0"


def test_frame_grows_past_8_bytes_when_needed():
    # Batt_Current (start 56, size 16) extends into a 9th byte → frame length 9
    m = _msgs()
    assert m[909]["length"] == 9
    assert m[900]["length"] == 8


def test_cells_cover_the_bit_span():
    f = jd.decode_frame(_msgs(), 912, "0128C30000000000")
    cells = f["signals"][0]["cells"]
    # 24-bit field at startingBit 0 → every bit of bytes 0,1,2
    assert sorted(cells) == sorted([b, bit] for b in (0, 1, 2) for bit in range(8))


def test_msb_lsb_cells_big_endian():
    f = jd.decode_frame(_msgs(), 912, "0128C30000000000")
    odo = f["signals"][0]
    # 24-bit big-endian at startingBit 0: MSB = byte0 bit7, LSB = byte2 bit0
    assert odo["msb_cell"] == [0, 7]
    assert odo["lsb_cell"] == [2, 0]


def test_msb_lsb_single_bit_collapses():
    f = jd.decode_frame(_msgs(), 900, "0205000000000200")
    sb = f["signals"][0]            # Seat_belt_passenger, 1 bit at startingBit 8
    assert sb["msb_cell"] == sb["lsb_cell"] == [1, 0]


def test_unknown_id_returns_error():
    f = jd.decode_frame(_msgs(), 0x7FF, "00")
    assert "error" in f
