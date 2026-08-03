"""DBC Builder — RE candidate conversion and DBC round-trip via cantools."""

from ucando.dbc_builder import DbcModel, re_candidate_to_signal


def test_re_candidate_bit_conversion():
    # RE seq bit 0 = byte0/bit7 -> cantools big-endian start = 7.
    sig = re_candidate_to_signal(0, 16, "rpm")
    assert sig["start_bit"] == 7
    assert sig["length"] == 16
    assert sig["byte_order"] == "big_endian"


def test_build_export_import_roundtrip():
    m = DbcModel()
    m.add_message(0x100, "ENGINE", length=8)
    m.add_signal(0x100, {"name": "Speed", "start_bit": 0, "length": 8,
                         "byte_order": "little_endian", "scale": 0.5, "offset": -10})
    text = m.to_dbc_string()
    assert "ENGINE" in text and "Speed" in text

    m2 = DbcModel()
    m2.import_dbc_string(text)
    msgs = m2.to_json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["frame_id"] == 0x100
    assert msgs[0]["name"] == "ENGINE"
    sig = msgs[0]["signals"][0]
    assert sig["name"] == "Speed"
    assert sig["scale"] == 0.5


def test_seed_from_re():
    m = DbcModel()
    re_id = {"id": 0x200, "id_hex": "200", "ext": False, "length": 8,
             "candidates": [{"start_bit": 8, "length": 8, "name": "ctr"}]}
    msg = m.seed_from_re(re_id)
    assert msg["frame_id"] == 0x200
    assert msg["signals"][0]["name"] == "ctr"
