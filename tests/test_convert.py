"""Format converter — DBC ⇄ JSON ⇄ CSV, all six directions + round-trips."""

import json

import pytest

from ucando import convert as cv

# A small but representative database: little-endian + byte-aligned big-endian,
# scale/offset, a value table, min/max, units.
DBC = """\
VERSION ""

BU_:

BO_ 256 ENGINE: 8 Vector__XXX
 SG_ Rpm : 0|16@1+ (0.25,0) [0|16000] "rpm" Vector__XXX
 SG_ Gear : 24|3@1+ (1,0) [0|7] "" Vector__XXX

BO_ 912 ODO: 8 Vector__XXX
 SG_ canOdometer : 7|24@0+ (1,0) [0|16777215] "km" Vector__XXX

VAL_ 256 Gear 0 "P" 1 "R" 2 "N" 3 "D" ;
"""


def test_dbc_to_json_and_back_preserves_layout():
    r = cv.convert(DBC, "json", filename="x.dbc")
    assert r["summary"] == {"from": "dbc", "to": "json", "messages": 2, "signals": 3}
    d = json.loads(r["content"])
    # DBC-sourced: CAN IDs keep their hex reading, zero-padded to the 32-bit field
    assert set(d.keys()) == {"00000100", "00000390"}      # 0x100 = 256, 0x390 = 912
    odo = d["00000390"][0]
    assert odo["fieldName"] == "canOdometer"
    assert odo["reverse"] == 0 and odo["startingBit"] == 0 and odo["size"] == 24
    rpm = [s for s in d["00000100"] if s["fieldName"] == "Rpm"][0]
    assert rpm["reverse"] == 1 and rpm["startingBit"] == 0      # little-endian
    assert rpm["multiplier"] == 0.25
    # →JSON is lossy: units / min-max / value table dropped → reported
    assert any("dropped" in w for w in r["warnings"])


def test_dbc_to_csv_carries_full_metadata():
    r = cv.convert(DBC, "csv", filename="x.dbc")
    lines = r["content"].splitlines()
    assert lines[0].startswith("message_name,CAN ID (HEX),CAN ID (Dec),is_extended,dlc,signal_name,start_bit")
    gear = [ln for ln in lines if ln.startswith("ENGINE,") and "Gear" in ln][0]
    assert "0:P;1:R;2:N;3:D" in gear      # value table preserved
    odo = [ln for ln in lines if "canOdometer" in ln][0]
    assert ",Motorola," in odo            # big-endian -> Motorola
    assert ",km," in odo                  # unit preserved
    assert not r["warnings"]              # CSV is lossless from DBC


def test_csv_has_both_hex_and_dec_id_columns():
    lines = cv.convert(DBC, "csv", filename="x.dbc")["content"].splitlines()
    hdr = lines[0].split(",")
    assert hdr[1] == "CAN ID (HEX)" and hdr[2] == "CAN ID (Dec)"
    eng = [ln for ln in lines if ln.startswith("ENGINE,")][0].split(",")
    assert eng[1] == "0x100" and eng[2] == "256"        # 256 == 0x100
    model = cv.parse("\n".join(lines), filename="x.csv")["model"]
    assert {m["frame_id"] for m in model["messages"]} == {256, 912}


def test_csv_round_trip_through_dbc_is_stable():
    csv_text = cv.convert(DBC, "csv", filename="x.dbc")["content"]
    model_dbc = cv.convert(csv_text, "dbc", filename="x.csv")["content"]
    csv_again = cv.convert(model_dbc, "csv", filename="x.dbc")["content"]
    # CSV → DBC → CSV reproduces the same table
    assert csv_again.strip() == csv_text.strip()


def test_json_to_dbc_to_json_preserves_validated_signals():
    sig = {
        "900": [{"fieldName": "Seat_belt_passenger", "reverse": 0, "startingBit": 8,
                 "size": 1, "multiplier": 1, "offset": 0, "signed": 0, "evData": 0}],
        "912": [{"fieldName": "canOdometer", "reverse": 0, "startingBit": 0,
                 "size": 24, "multiplier": 1, "offset": 0, "signed": 0, "evData": 0}],
    }
    dbc = cv.convert(json.dumps(sig), "dbc", filename="s.json")["content"]
    back = json.loads(cv.convert(dbc, "json", filename="s.dbc")["content"])
    # A DBC hop cannot carry the source key base (or evData), so the output is
    # DBC-native: hex keys and evData=1. The ids themselves are unchanged.
    assert back["00000390"][0] == {"fieldName": "canOdometer", "reverse": 0, "startingBit": 0,
                                   "size": 24, "evData": 1, "multiplier": 1, "offset": 0, "signed": 0}
    assert back["00000384"][0]["startingBit"] == 8 and back["00000384"][0]["reverse"] == 0


def test_big_endian_startingbit_maps_to_dbc_motorola_exactly():
    # MSB-first startingBit -> cantools Motorola start, validated vs the Ziptron
    # DBC (JSON 24->DBC 31, 48->55), and it round-trips back unchanged.
    sig = {"905": [
        {"fieldName": "dte", "reverse": 0, "startingBit": 24, "size": 10, "multiplier": 1, "offset": 0},
        {"fieldName": "soc", "reverse": 0, "startingBit": 48, "size": 7, "multiplier": 1, "offset": 0},
    ]}
    dbc = cv.convert(json.dumps(sig), "dbc", filename="s.json")["content"]
    assert "dte : 31|10@0+" in dbc and "soc : 55|7@0+" in dbc
    back = json.loads(cv.convert(dbc, "json", filename="s.dbc")["content"])
    # DBC-sourced -> hex keys (905 = 0x389); the bit layout round-trips exactly
    assert {s["fieldName"]: s["startingBit"] for s in back["00000389"]} == {"dte": 24, "soc": 48}


def test_messages_and_signals_sorted_ascending():
    # Out-of-order input: messages 912 before 256, signals Gear(24) before Rpm(0).
    unsorted = (
        'VERSION ""\n\nBU_:\n\n'
        "BO_ 912 ODO: 8 Vector__XXX\n"
        ' SG_ canOdometer : 7|24@0+ (1,0) [0|16777215] "km" Vector__XXX\n'
        "BO_ 256 ENGINE: 8 Vector__XXX\n"
        ' SG_ Gear : 24|3@1+ (1,0) [0|7] "" Vector__XXX\n'
        ' SG_ Rpm : 0|16@1+ (0.25,0) [0|16000] "rpm" Vector__XXX\n'
    )
    model = cv.parse(unsorted, filename="x.dbc")["model"]
    # messages ascending by CAN ID
    assert [m["frame_id"] for m in model["messages"]] == [256, 912]
    # signals within 256 ascending by start bit (Rpm@0 before Gear@24)
    eng = next(m for m in model["messages"] if m["frame_id"] == 256)
    assert [s["name"] for s in eng["signals"]] == ["Rpm", "Gear"]
    # export keeps the same order: ENGINE block before ODO block
    csv_text = cv.serialize(model, "csv")["content"]
    rows = [ln for ln in csv_text.splitlines()[1:]]
    assert rows[0].startswith("ENGINE,") and "Rpm" in rows[0]
    assert rows[1].startswith("ENGINE,") and "Gear" in rows[1]
    assert rows[2].startswith("ODO,")


def test_byte_order_aliases_accepted_on_csv_import():
    csv_text = (
        "message_name,can_id,is_extended,dlc,signal_name,start_bit,length,byte_order,signed,scale,offset,min,max,unit,value_table,comment,ev_data\n"
        "M,100,0,8,a,0,8,big_endian,0,1,0,,,,,,0\n"
        "M,100,0,8,b,8,8,1,0,1,0,,,,,,0\n"            # reverse-flag 1 = little
        "M,100,0,8,c,16,8,Intel,0,1,0,,,,,,0\n"
    )
    model = cv.convert(csv_text, "json", filename="x.csv")
    d = json.loads(model["content"])
    rev = {s["fieldName"]: s["reverse"] for s in d["100"]}
    assert rev == {"a": 0, "b": 1, "c": 1}


def test_detect_format_and_unknown_raises():
    assert cv.detect_format("", "{ }") == "json"
    assert cv.detect_format("", 'VERSION ""\nBO_ 1 X: 8 Z') == "dbc"
    assert cv.detect_format("x.csv", "message_name,can_id,signal_name") == "csv"
    with pytest.raises(ValueError):
        cv.detect_format("", "hello world")


# ----- workbench: parse → edit/select → serialize --------------------------
def test_serialize_subset_only():
    p = cv.parse(DBC, filename="x.dbc")
    # keep only canOdometer
    p["model"]["messages"] = [
        {**m, "signals": [s for s in m["signals"] if s["name"] == "canOdometer"]}
        for m in p["model"]["messages"] if any(s["name"] == "canOdometer" for s in m["signals"])
    ]
    out = cv.serialize(p["model"], "json")["content"]
    d = json.loads(out)
    assert list(d.keys()) == ["00000390"]            # DBC-sourced -> hex key
    assert d["00000390"][0]["fieldName"] == "canOdometer"


def test_value_table_survives_dbc_to_csv_to_dbc():
    csv_text = cv.serialize(cv.parse(DBC, filename="x.dbc")["model"], "csv")["content"]
    assert "0:P;1:R;2:N;3:D" in csv_text
    dbc_again = cv.serialize(cv.parse(csv_text, filename="x.csv")["model"], "dbc")["content"]
    assert 'VAL_ 256 Gear 0 "P" 1 "R" 2 "N" 3 "D"' in dbc_again


def test_endpoints_parse_and_export():
    from fastapi.testclient import TestClient
    from ucando.server import app
    c = TestClient(app)
    pr = c.post("/api/convert/parse",
                files={"file": ("x.dbc", DBC.encode(), "text/plain")}).json()
    assert pr["ok"] and pr["source_fmt"] == "dbc" and pr["source_name"] == "x"
    model = pr["model"]
    ex = c.post("/api/convert/export", json={"model": model, "to": "json", "source_name": "x"}).json()
    assert ex["ok"]
    assert ex["filename"].startswith("Signature_x_") and ex["filename"].endswith(".json")
    # DBC/CSV filenames have no Signature_ prefix
    ex2 = c.post("/api/convert/export", json={"model": model, "to": "csv", "source_name": "x"}).json()
    assert ex2["filename"].startswith("x_") and ex2["filename"].endswith(".csv")


# ----- hex vs decimal CAN-ID keys (two exporters in the field) --------------
def test_hex_id_keys_are_detected_and_parsed():
    # Real shape of Signature_mgevcommute.json: 8-digit zero-padded hex keys.
    text = json.dumps({
        "000000E1": [{"fieldName": "DriverSeatBelt", "reverse": 0, "startingBit": 12,
                      "size": 1, "evData": 1, "multiplier": 1, "offset": 0, "signed": 0}],
        "0000012A": [{"fieldName": "DoorDriver", "reverse": 0, "startingBit": 8,
                      "size": 1, "evData": 1, "multiplier": 1, "offset": 0, "signed": 0}],
    })
    r = cv.parse(text, filename="Signature_x.json")
    assert [m["frame_id"] for m in r["model"]["messages"]] == [0xE1, 0x12A]
    # message names read back in the file's own base, not as opaque decimals
    assert [m["name"] for m in r["model"]["messages"]] == ["MSG_E1", "MSG_12A"]
    # the base is a real semantic choice, so it is reported, not silent
    assert any("hexadecimal" in w for w in r["warnings"])


def test_decimal_id_keys_still_decimal():
    # Ziptron convention: unpadded decimal keys stay decimal (900 != 0x900).
    text = json.dumps({"900": [{"fieldName": "a", "reverse": 0, "startingBit": 0,
                                "size": 8, "multiplier": 1, "offset": 0, "signed": 0}]})
    r = cv.parse(text, filename="x.json")
    assert [m["frame_id"] for m in r["model"]["messages"]] == [900]
    assert not any("hexadecimal" in w for w in r["warnings"])


def test_one_hex_key_makes_the_whole_file_hex():
    # Signature_tmlais038B.json shape: "408b" proves hex, so "15" is 0x15 too.
    from ucando import jsondecode as jd
    assert jd.detect_id_base(["408b", "4091", "15"]) == 16
    assert jd.detect_id_base(["900", "905", "912"]) == 10
    assert jd.detect_id_base(["18FEEA27"]) == 16
    assert jd.detect_id_base(["0x200"]) == 16
    assert jd.detect_id_base(["00000200"]) == 16        # zero-padded => hex
    assert jd.detect_id_base([]) == 10


def test_json_without_bit_layout_names_the_missing_fields():
    # A different telematics JSON family: {title, multiplier, divider, offSet}.
    text = json.dumps({"408b": {"title": "canOdometer", "multiplier": 1.0,
                                "divider": 1.0, "offSet": 0}})
    with pytest.raises(ValueError) as e:
        cv.parse(text, filename="x.json")
    msg = str(e.value)
    assert "startingBit" in msg and "not a Signature JSON" in msg


def test_overlapping_signals_report_can_id_and_bit_spans():
    # A DBC cannot hold overlaps; the error must locate them in the source.
    text = json.dumps({"00000287": [
        {"fieldName": "PackCurrent", "reverse": 0, "startingBit": 1, "size": 16,
         "multiplier": 0.1, "offset": 1000, "signed": 0},
        {"fieldName": "PackVoltage3", "reverse": 0, "startingBit": 16, "size": 16,
         "multiplier": 0.1, "offset": 0, "signed": 0},
    ]})
    model = cv.parse(text, filename="x.json")["model"]
    with pytest.raises(ValueError) as e:
        cv.serialize(model, "dbc")
    msg = str(e.value)
    assert "0x287" in msg and "PackCurrent bits 1-16" in msg and "PackVoltage3 bits 16-31" in msg
    # JSON and CSV have no such constraint - they still export
    assert cv.serialize(model, "json")["content"]
    assert cv.serialize(model, "csv")["content"]


# ----- DBC -> JSON export conventions (cloud signature) ---------------------
DUP_DBC = """\
VERSION ""

BU_:

BO_ 288 HSC_Odometer: 5 Vector__XXX
 SG_ Odometer : 7|32@0+ (0.015625,0) [0|67108864] "km" Vector__XXX
 SG_ Checksum : 39|8@0+ (1,0) [0|255] "" Vector__XXX

BO_ 647 HSC_Pack: 8 Vector__XXX
 SG_ PackVoltage : 7|16@0+ (0.1,0) [0|1000] "V" Vector__XXX
 SG_ Checksum : 63|8@0+ (1,0) [0|255] "" Vector__XXX

BO_ 666 HSC_Pack2: 8 Vector__XXX
 SG_ PackVoltage : 7|16@0+ (0.1,0) [0|1000] "V" Vector__XXX
"""


def test_dbc_to_json_keys_are_padded_hex():
    d = json.loads(cv.convert(DUP_DBC, "json", filename="x.dbc")["content"])
    # 288 = 0x120, 647 = 0x287, 666 = 0x29A — hex, zero-padded to the 32-bit field,
    # so a DBC read as 0x120 on the bus is not renumbered to "288" in the signature.
    assert set(d.keys()) == {"00000120", "00000287", "0000029A"}


def test_dbc_to_json_sets_ev_flag():
    d = json.loads(cv.convert(DUP_DBC, "json", filename="x.dbc")["content"])
    assert all(s["evData"] == 1 for sigs in d.values() for s in sigs)


def test_duplicate_signal_names_get_can_id_suffix():
    r = cv.convert(DUP_DBC, "json", filename="x.dbc")
    d = json.loads(r["content"])
    names = {k: [s["fieldName"] for s in v] for k, v in d.items()}
    # Qualified by *message name* (minus the shared HSC_ bus tag), not the CAN id:
    # "which frame did this come from" is the useful question, and a DBC already
    # guarantees signal names are unique within a message.
    assert names["00000120"] == ["Odometer", "Checksum_Odometer"]
    assert names["00000287"] == ["PackVoltage_Pack", "Checksum_Pack"]
    assert names["0000029A"] == ["PackVoltage_Pack2"]
    # Odometer appears once, so it keeps its bare name
    assert "Odometer" in names["00000120"]
    assert any("Duplicate signal names" in w for w in r["warnings"])


def test_qualifier_falls_back_to_hex_id_without_message_names():
    # A JSON source auto-names messages MSG_<id>, which qualifies nothing — the
    # hex CAN id must be used instead.
    sig = {
        "0000012A": [{"fieldName": "Dup", "reverse": 0, "startingBit": 0, "size": 8,
                      "multiplier": 1, "offset": 0, "signed": 0, "evData": 1}],
        "00000287": [{"fieldName": "Dup", "reverse": 0, "startingBit": 0, "size": 8,
                      "multiplier": 1, "offset": 0, "signed": 0, "evData": 1}],
    }
    d = json.loads(cv.convert(json.dumps(sig), "json", filename="s.json")["content"])
    got = sorted(s["fieldName"] for v in d.values() for s in v)
    assert got == ["Dup_12A", "Dup_287"]


def test_qualifier_strip_skipped_when_it_would_collide():
    # Stripping the first segment must not create an ambiguous qualifier.
    dbc = """\
VERSION ""

BU_:

BO_ 256 HSC_Pack: 8 Vector__XXX
 SG_ V : 7|8@0+ (1,0) [0|255] "" Vector__XXX

BO_ 512 MSC_Pack: 8 Vector__XXX
 SG_ V : 7|8@0+ (1,0) [0|255] "" Vector__XXX
"""
    d = json.loads(cv.convert(dbc, "json", filename="x.dbc")["content"])
    got = sorted(s["fieldName"] for v in d.values() for s in v)
    # both strip to "Pack", so the full names are kept
    assert got == ["V_HSC_Pack", "V_MSC_Pack"]


def test_json_decimal_keys_survive_a_csv_round_trip():
    # CSV cannot know the source base, so it must not flip decimal keys to hex.
    sig = {"905": [{"fieldName": "a", "reverse": 0, "startingBit": 0, "size": 8,
                    "multiplier": 1, "offset": 0, "signed": 0, "evData": 1}]}
    csv_text = cv.convert(json.dumps(sig), "csv", filename="s.json")["content"]
    back = json.loads(cv.convert(csv_text, "json", filename="s.csv")["content"])
    assert list(back.keys()) == ["905"]
    assert back["905"][0]["evData"] == 1        # CSV is the evData-preserving hop


def test_dlc_and_evdata_losses_are_reported():
    # Both were silent before: a 5-byte message reads back as 8, and evData is
    # zeroed by a DBC hop. Every other lossy field was already reported.
    w = cv.convert(DUP_DBC, "json", filename="x.dbc")["warnings"]
    assert any("no DLC field" in x and "0x120 (DLC 5)" in x for x in w)
    sig = {"905": [{"fieldName": "a", "reverse": 0, "startingBit": 0, "size": 8,
                    "multiplier": 1, "offset": 0, "signed": 0, "evData": 1}]}
    w2 = cv.convert(json.dumps(sig), "dbc", filename="s.json")["warnings"]
    assert any("evData" in x for x in w2)
