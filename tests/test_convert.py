"""Format converter — DBC ⇄ JSON ⇄ CSV, all six directions + round-trips."""

import json

import pytest

from canforge import convert as cv

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
    # CAN IDs are decimal keys
    assert set(d.keys()) == {"256", "912"}
    odo = d["912"][0]
    assert odo["fieldName"] == "canOdometer"
    assert odo["reverse"] == 0 and odo["startingBit"] == 0 and odo["size"] == 24
    rpm = [s for s in d["256"] if s["fieldName"] == "Rpm"][0]
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
    assert back["912"][0] == {"fieldName": "canOdometer", "reverse": 0, "startingBit": 0,
                              "size": 24, "evData": 0, "multiplier": 1, "offset": 0, "signed": 0}
    assert back["900"][0]["startingBit"] == 8 and back["900"][0]["reverse"] == 0


def test_sub_byte_big_endian_is_flagged_not_silent():
    # Batt_Voltage: big-endian, 11 bits, not byte-aligned → ambiguous in DBC
    sig = {"909": [{"fieldName": "Batt_Voltage", "reverse": 0, "startingBit": 40,
                    "size": 11, "multiplier": 0.25, "offset": 0, "signed": 0}]}
    r = cv.convert(json.dumps(sig), "dbc", filename="s.json")
    assert any("big-endian" in w for w in r["warnings"])


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
def test_parse_tags_doubt_per_signal():
    p = cv.parse(DBC, filename="x.dbc")
    sigs = {s["name"]: s for m in p["model"]["messages"] for s in m["signals"]}
    # byte-aligned BE + LE signals carry no doubt
    assert sigs["canOdometer"]["doubt"] is None
    assert sigs["Rpm"]["doubt"] is None


def test_doubt_flagged_and_commented_for_sub_byte_be():
    sig = {"909": [{"fieldName": "Batt_Voltage", "reverse": 0, "startingBit": 40,
                    "size": 11, "multiplier": 0.25, "offset": 0, "signed": 0}]}
    p = cv.parse(json.dumps(sig), filename="s.json")
    assert p["model"]["messages"][0]["signals"][0]["doubt"]      # tagged on parse
    # exported DBC carries a CM_ comment for it
    out = cv.serialize(p["model"], "dbc")["content"]
    assert any(l.startswith("CM_ SG_ 909 Batt_Voltage") and "uCANdo" in l for l in out.splitlines())


def test_serialize_subset_only():
    p = cv.parse(DBC, filename="x.dbc")
    # keep only canOdometer
    p["model"]["messages"] = [
        {**m, "signals": [s for s in m["signals"] if s["name"] == "canOdometer"]}
        for m in p["model"]["messages"] if any(s["name"] == "canOdometer" for s in m["signals"])
    ]
    out = cv.serialize(p["model"], "json")["content"]
    d = json.loads(out)
    assert list(d.keys()) == ["912"] and d["912"][0]["fieldName"] == "canOdometer"


def test_value_table_survives_dbc_to_csv_to_dbc():
    csv_text = cv.serialize(cv.parse(DBC, filename="x.dbc")["model"], "csv")["content"]
    assert "0:P;1:R;2:N;3:D" in csv_text
    dbc_again = cv.serialize(cv.parse(csv_text, filename="x.csv")["model"], "dbc")["content"]
    assert 'VAL_ 256 Gear 0 "P" 1 "R" 2 "N" 3 "D"' in dbc_again


def test_endpoints_parse_and_export():
    from fastapi.testclient import TestClient
    from canforge.server import app
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
