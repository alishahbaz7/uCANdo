"""Signature-JSON frame decoder — convention locked by the Ziptron DBC.

Ground truth: cantools decoding the real Ziptron DBC (msg 0x244/580) for frame
``52 51 00 47 C0 00 BA 56`` gives DTeInfo=287 and HVBattSoCPercen=93. The JSON
must reproduce those exactly. The convention is **MSB-first sequential** for
big-endian (bit 0 = byte0's MSB); byte-aligned signals read the same either way.
"""

import json

from ucando import jsondecode as jd

# Ziptron message 905 (== DBC 0x244 signals), the authoritative reference.
ZIPTRON_905 = [
    {"fieldName": "distanceToEmpty", "reverse": 0, "startingBit": 24, "size": 10, "multiplier": 1.0, "offset": 0},
    {"fieldName": "stateOfCharge", "reverse": 0, "startingBit": 48, "size": 7, "multiplier": 1.0, "offset": 0},
    {"fieldName": "batteryHighTemp", "reverse": 0, "startingBit": 42, "size": 2, "multiplier": 1.0, "offset": 0},
    {"fieldName": "hvCriticalAlert", "reverse": 0, "startingBit": 19, "size": 2, "multiplier": 1.0, "offset": 0},
]

SIGNATURE = {
    "900": [
        {"fieldName": "flag8", "reverse": 0, "startingBit": 8, "size": 1, "multiplier": 1, "offset": 0, "signed": 0},
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


def test_matches_ziptron_dbc_ground_truth():
    # The whole reason for the MSB-first convention: match the real DBC exactly.
    m = jd.load_signature(json.dumps({"905": ZIPTRON_905}))
    vals = {s["name"]: s["raw"] for s in jd.decode_frame(m, 905, "5251004 7C000BA56".replace(" ", ""))["signals"]}
    assert vals["distanceToEmpty"] == 287     # cantools DBC DTeInfo (24|10@0)
    assert vals["stateOfCharge"] == 93         # cantools DBC HVBattSoCPercen (55|7@0)
    assert vals["batteryHighTemp"] == 0
    assert vals["hvCriticalAlert"] == 0


def test_single_bit_msb_first():
    # startingBit 8 = byte1's MSB (bit 7) under the MSB-first convention
    m = _msgs()
    assert jd.decode_frame(m, 900, "0080000000000000")["signals"][0]["raw"] == 1   # byte1=0x80 → bit7=1
    assert jd.decode_frame(m, 900, "0005000000000000")["signals"][0]["raw"] == 0   # byte1=0x05 → bit7=0


def test_multibyte_big_endian_odometer():
    # bytes 0,1,2 = 01 28 C3 assembled big-endian = 0x0128C3 = 75971 (byte-aligned)
    odo = jd.decode_frame(_msgs(), 912, "0128C30000000000")["signals"][0]
    assert odo["raw"] == 75971 and odo["physical"] == "75971" and odo["byte_order"] == "big_endian"


def test_scale_and_offset_applied():
    # soc ×0.1, byte-aligned bytes 3-4 big-endian; byte4 = 0x64 (=100) → 10.0
    soc = next(s for s in jd.decode_frame(_msgs(), 909, "000000006400000000")["signals"] if s["name"] == "soc")
    assert soc["raw"] == 100 and soc["physical"] == "10.0"


def test_frame_grows_past_8_bytes_when_needed():
    m = _msgs()
    assert m[909]["length"] == 9 and m[900]["length"] == 8


def test_cells_cover_the_bit_span():
    cells = jd.decode_frame(_msgs(), 912, "0128C30000000000")["signals"][0]["cells"]
    assert sorted(cells) == sorted([b, bit] for b in (0, 1, 2) for bit in range(8))


def test_msb_lsb_cells_big_endian():
    odo = jd.decode_frame(_msgs(), 912, "0128C30000000000")["signals"][0]
    assert odo["msb_cell"] == [0, 7] and odo["lsb_cell"] == [2, 0]


def test_msb_lsb_single_bit():
    sb = jd.decode_frame(_msgs(), 900, "0000000000000000")["signals"][0]  # startingBit 8 → byte1 MSB
    assert sb["msb_cell"] == sb["lsb_cell"] == [1, 7]


def test_unknown_id_returns_error():
    assert "error" in jd.decode_frame(_msgs(), 0x7FF, "00")


def test_decode_frames_multi_payload_ordered():
    # Trace view contract: a list of payloads on one ID decodes in order, each
    # frame carrying its own signals (raw/physical) so the matrix can diff rows.
    m = jd.load_signature(json.dumps({"905": ZIPTRON_905}))
    idhex = f"{905:X}"
    payloads = ["525100FFC000BE56", "525100498000BE56", "52510047C000BA56"]
    out = jd.decode_frames(m, [{"id": idhex, "data": p} for p in payloads])
    assert [f["id"] for f in out] == [905, 905, 905]
    dte = [next(s["raw"] for s in f["signals"] if s["name"] == "distanceToEmpty") for f in out]
    assert dte == [1023, 294, 287]      # varies across the sequence (change-highlight)


def test_hex_keyed_signature_loads_and_decodes():
    # Frame Decoder path on a hex-keyed export (Signature_mgevcommute.json).
    m = jd.load_signature(json.dumps({"00000155": [
        {"fieldName": "AccelPedalPos", "reverse": 0, "startingBit": 16, "size": 8,
         "multiplier": 1, "offset": 0, "signed": 0}]}))
    assert list(m.keys()) == [0x155]
    assert m[0x155]["name"] == "MSG_155"
    out = jd.decode_frame(m, 0x155, "0011223344556677")
    assert out["signals"][0]["raw"] == 0x22           # byte 2
    assert jd.signature_messages(m)[0]["id_hex"] == "155"


def test_short_dlc_frame_pads_right_not_left():
    """Real MG Commute 0x120 is DLC 5; left-padding used to shift it to 0.00.

    Ground truth: `00 02 FE A2 00` -> Odometer 0x0002FEA2 = 196258 counts at
    1/64 km = 3066.53 km, against a dash photo reading 3066 (see
    docs/MG_COMMUTE_DECODE.md). Left-padding to the synthesised 8-byte length
    would move the accumulator into bytes 3-6 and read 0.
    """
    m = jd.load_signature(json.dumps({"00000120": [
        {"fieldName": "Odometer", "reverse": 0, "startingBit": 0, "size": 32,
         "multiplier": 0.015625, "offset": 0, "signed": 0}]}))
    assert m[0x120]["length"] == 8            # synthesised, not a real DLC
    out = jd.decode_frame(m, 0x120, "0002FEA200")
    assert out["signals"][0]["physical"] == "3066.53"
    # the trailing pad bytes are zeros, and byte 0 stayed byte 0
    assert out["bytes"] == [0x00, 0x02, 0xFE, 0xA2, 0x00, 0, 0, 0]


def test_short_payload_keeps_byte0_at_byte0():
    m = jd.load_signature(json.dumps({"100": [
        {"fieldName": "b0", "reverse": 0, "startingBit": 0, "size": 8,
         "multiplier": 1, "offset": 0, "signed": 0}]}))
    # "04" means byte 0 = 0x04, not byte 7 = 0x04
    assert jd.decode_frame(m, 100, "04")["signals"][0]["raw"] == 0x04
