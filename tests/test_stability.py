"""Stability / robustness suite.

Beyond the happy-path tests, this probes edge cases, malformed input, error
paths, round-trips and connect/disconnect lifecycle — the things that decide
whether the utility degrades gracefully (HTTP 400 + {ok:false}) or crashes (500).
"""

import json
import uuid

import can
import pytest
from fastapi.testclient import TestClient

from canforge import convert as cv
from canforge import jsondecode as jd
from canforge.dbc_builder import DbcModel
from canforge.framedecode import decode_frame, decode_frames
from canforge.server import app
from tests.conftest import wait_until

client = TestClient(app)


# --------------------------------------------------------------------------- #
# A. jsondecode — edge cases
# --------------------------------------------------------------------------- #
def _sig(**kw):
    base = {"reverse": 0, "startingBit": 0, "size": 8, "multiplier": 1,
            "offset": 0, "signed": 0, "evData": 0}
    base.update(kw)
    base.setdefault("fieldName", "S")
    return base


def test_json_signed_twos_complement():
    m = jd.load_signature(json.dumps({"100": [_sig(size=8, signed=1, reverse=1)]}))
    f = jd.decode_frame(m, 0x64, "FF00000000000000")     # byte0 = 0xFF
    assert f["signals"][0]["raw"] == -1                  # 0xFF as signed8 = -1


def test_json_little_endian_multibyte():
    m = jd.load_signature(json.dumps({"100": [_sig(size=16, reverse=1)]}))
    f = jd.decode_frame(m, 0x64, "3412000000000000")     # LE: byte0 LSB
    assert f["signals"][0]["raw"] == 0x1234              # 4660


def test_json_scale_offset_applied():
    m = jd.load_signature(json.dumps({"100": [_sig(size=8, multiplier=0.5, offset=10, reverse=1)]}))
    f = jd.decode_frame(m, 100, "0400000000000000")      # byte0 = 0x04 (id 100 = decimal)
    assert f["signals"][0]["raw"] == 4
    assert f["signals"][0]["physical"] == "12.0"         # 4*0.5 + 10


def test_json_short_payload_padded_no_crash():
    # a short payload is right-padded (byte 0 stays byte 0) — must not crash
    m = jd.load_signature(json.dumps({"100": [_sig(size=8, reverse=1)]}))
    assert "error" not in jd.decode_frame(m, 100, "04")


def test_json_oversized_payload_truncated():
    m = jd.load_signature(json.dumps({"100": [_sig(size=8, reverse=1)]}))
    # message length is 8; a 10-byte payload must be truncated, not crash
    f = jd.decode_frame(m, 100, "11" * 10)
    assert "error" not in f and f["signals"][0]["raw"] == 0x11


def test_json_malformed_text_raises_cleanly():
    with pytest.raises(Exception):
        jd.load_signature("{ not valid json")


def test_json_many_signals_no_crash():
    sigs = [_sig(fieldName=f"b{i}", startingBit=i, size=1, reverse=1) for i in range(64)]
    m = jd.load_signature(json.dumps({"200": sigs}))
    f = jd.decode_frame(m, 200, "FF" * 8)                # id 200 = decimal key
    assert len(f["signals"]) == 64 and all(s["raw"] == 1 for s in f["signals"])


# --------------------------------------------------------------------------- #
# B. convert — robustness across all six directions + bad input
# --------------------------------------------------------------------------- #
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


def test_convert_all_six_directions_nonempty():
    json_text = cv.convert(DBC, "json", filename="x.dbc")["content"]
    csv_text = cv.convert(DBC, "csv", filename="x.dbc")["content"]
    pairs = [
        (DBC, "json", "x.dbc"), (DBC, "csv", "x.dbc"),
        (json_text, "dbc", "x.json"), (json_text, "csv", "x.json"),
        (csv_text, "dbc", "x.csv"), (csv_text, "json", "x.csv"),
    ]
    for text, to, name in pairs:
        out = cv.convert(text, to, filename=name)["content"]
        assert out and out.strip(), f"{name} -> {to} produced empty output"


def test_convert_empty_model_serializes():
    empty = {"messages": []}
    assert cv.serialize(empty, "json")["content"].strip() == "{}"
    assert cv.serialize(empty, "csv")["content"].startswith("message_name,")
    assert "VERSION" in cv.serialize(empty, "dbc")["content"]    # valid empty DBC


def test_convert_csv_missing_column_raises():
    with pytest.raises(ValueError):
        cv.csv_to_model("foo,bar\n1,2\n")


def test_convert_csv_bad_row_skipped_with_warning():
    csv_text = (
        "message_name,CAN ID (Dec),is_extended,dlc,signal_name,start_bit,length,byte_order,signed,scale,offset,min,max,unit,value_table,comment,ev_data\n"
        "M,not_a_number,0,8,a,0,8,Intel,0,1,0,,,,,,0\n"     # bad id -> skipped
        "M,100,0,8,b,0,8,Intel,0,1,0,,,,,,0\n"              # good
    )
    model, warnings = cv.csv_to_model(csv_text)
    assert len(model["messages"]) == 1 and model["messages"][0]["frame_id"] == 100
    assert any("bad CAN ID" in w for w in warnings)


def test_convert_detect_format_unknown_raises():
    with pytest.raises(ValueError):
        cv.detect_format("", "this is neither json nor dbc nor csv")


def test_convert_byte_order_aliases():
    for raw, expect in [("Motorola", "big_endian"), ("Intel", "little_endian"),
                        ("big_endian", "big_endian"), ("0", "big_endian"),
                        ("1", "little_endian"), ("LE", "little_endian")]:
        assert cv._parse_byte_order(raw) == expect


def test_convert_value_table_parse_ignores_junk():
    assert cv._parse_value_table("0:P;junk;2:N;:bad;x:y") == {0: "P", 2: "N"}
    assert cv._parse_value_table("") is None


def test_convert_json_csv_json_roundtrip_preserves_layout():
    sig = {"909": [
        {"fieldName": "soc", "reverse": 0, "startingBit": 24, "size": 16, "multiplier": 0.1, "offset": 0, "signed": 0},
        {"fieldName": "Batt_Current", "reverse": 0, "startingBit": 56, "size": 16, "multiplier": 0.05, "offset": 1000, "signed": 0},
    ]}
    csv_text = cv.convert(json.dumps(sig), "csv", filename="s.json")["content"]
    back = json.loads(cv.convert(csv_text, "json", filename="s.csv")["content"])
    got = {s["fieldName"]: (s["startingBit"], s["size"], s["multiplier"]) for s in back["909"]}
    assert got["soc"] == (24, 16, 0.1)
    assert got["Batt_Current"] == (56, 16, 0.05)


# --------------------------------------------------------------------------- #
# C. framedecode — malformed payloads degrade gracefully
# --------------------------------------------------------------------------- #
def _ct_db():
    import cantools
    m = DbcModel()
    m.add_message(0x94, "M94", length=8)
    m.add_signal(0x94, {"name": "Speed", "start_bit": 3, "length": 12,
                        "byte_order": "big_endian", "scale": 10, "offset": 0})
    return cantools.database.load_string(m.to_dbc_string(), database_format="dbc")


def test_framedecode_non_hex_is_caught():
    res = decode_frames(_ct_db(), [{"id": "94", "data": "zzzznothex"}])
    assert "error" in res[0]                              # caught, not raised


def test_framedecode_unknown_id_graceful_via_decode_frames():
    # decode_frames (plural) is the API entry point — it wraps per-frame errors
    res = decode_frames(_ct_db(), [{"id": "7FF", "data": "00"}])
    assert "error" in res[0]


def test_framedecode_oversized_truncated():
    f = decode_frame(_ct_db(), 0x94, "FF" * 16)           # oversized -> truncated to DLC
    assert "error" not in f and len(f["bytes"]) == 8


# --------------------------------------------------------------------------- #
# D. API — no 500s on a broad GET sweep, and graceful error paths
# --------------------------------------------------------------------------- #
GET_ENDPOINTS = [
    "/", "/index.html", "/api/info", "/api/plugins", "/api/config", "/api/devices",
    "/api/drivers/status", "/api/status", "/api/logs", "/api/re/engines",
    "/api/oem/profiles", "/api/jobs", "/api/rules", "/api/tx", "/api/restbus/status",
    "/api/signals", "/api/signals/derived", "/api/dashboard", "/api/dtc",
    "/api/decode/live", "/api/autore/protocols", "/api/autore/report",
]


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_get_endpoints_never_500(path):
    assert client.get(path).status_code < 500


def test_convert_endpoint_bad_target_is_graceful():
    r = client.post("/api/convert?to=xml",
                    files={"file": ("x.json", b"{}", "application/json")})
    assert r.status_code < 500 and r.json()["ok"] is False


def test_convert_parse_malformed_json_graceful():
    r = client.post("/api/convert/parse",
                    files={"file": ("bad.json", b"{ broken", "application/json")})
    assert r.status_code < 500 and r.json()["ok"] is False


def test_convert_export_garbage_model_graceful():
    r = client.post("/api/convert/export", json={"model": {"messages": "garbage"}, "to": "json"})
    assert r.status_code < 500          # caught, not a crash


def test_decode_json_import_malformed_graceful():
    r = client.post("/api/decode/json-import",
                    files={"file": ("bad.json", b"not json", "application/json")})
    assert r.status_code < 500 and r.json()["ok"] is False


def test_manual_protocol_decode_bad_hex_graceful():
    r = client.post("/api/decode/frame", json={"id": 0x100, "data": "zzz", "is_extended": False})
    assert r.status_code < 500          # must not crash on non-hex


def test_decode_frames_unknown_id_after_import():
    m = DbcModel()
    m.add_message(0x94, "M94", length=8)
    m.add_signal(0x94, {"name": "Speed", "start_bit": 0, "length": 8, "byte_order": "little_endian"})
    client.post("/api/decode/dbc-import", files={"file": ("t.dbc", m.to_dbc_string(), "text/plain")})
    dec = client.post("/api/decode/frames", json={"frames": [{"id": "7FF", "data": "00"}]}).json()
    assert dec["ok"] and "error" in dec["frames"][0]     # per-frame error, request still ok


# --------------------------------------------------------------------------- #
# E. connect / disconnect lifecycle stability
# --------------------------------------------------------------------------- #
def test_disconnect_when_not_connected_is_graceful():
    r = client.post("/api/disconnect").json()
    assert r.get("connected") is False


def test_connect_disconnect_cycles_no_leak():
    import uuid
    for _ in range(3):
        chan = f"cyc-{uuid.uuid4().hex[:6]}"
        assert client.post("/api/connect", json={"hw": "virtual", "channel": chan,
                                                 "simulate": True}).json()["ok"]
        assert wait_until(lambda: client.get("/api/status").json()["connected"], timeout=3)
        assert client.post("/api/disconnect").json()["connected"] is False


def test_connect_while_connected_is_graceful():
    chan = f"dup-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/connect", json={"hw": "virtual", "channel": chan, "simulate": False}).json()["ok"]
    try:
        # a second connect must not 500 (either rejects or reconnects)
        r = client.post("/api/connect", json={"hw": "virtual", "channel": chan, "simulate": False})
        assert r.status_code < 500
    finally:
        client.post("/api/disconnect")


# --------------------------------------------------------------------------- #
# F. deeper edge cases — CSV quoting, large DBs, unicode, boundaries, signed-BE
# --------------------------------------------------------------------------- #
def _model_one_signal(comment="", unit="", value_table=None):
    return {"messages": [{"name": "M", "frame_id": 100, "is_extended": False, "dlc": 8,
        "signals": [{"name": "s", "start_bit": 0, "length": 8, "byte_order": "little_endian",
                     "is_signed": False, "scale": 1, "offset": 0, "min": None, "max": None,
                     "unit": unit, "value_table": value_table, "comment": comment, "ev_data": 0}]}]}


def test_csv_comment_with_comma_roundtrips():
    csv_text = cv.serialize(_model_one_signal(comment="hello, world; ok"), "csv")["content"]
    back, _ = cv.csv_to_model(csv_text)
    assert back["messages"][0]["signals"][0]["comment"] == "hello, world; ok"


def test_csv_unicode_roundtrips():
    csv_text = cv.serialize(_model_one_signal(comment="température ±2°C", unit="°C"), "csv")["content"]
    s = cv.csv_to_model(csv_text)[0]["messages"][0]["signals"][0]
    assert s["comment"] == "température ±2°C" and s["unit"] == "°C"


def test_csv_tolerates_missing_and_extra_columns():
    csv_text = "CAN ID (Dec),signal_name,start_bit,length,extra\n100,s,0,8,whatever\n"
    sig = cv.csv_to_model(csv_text)[0]["messages"][0]["signals"][0]
    assert sig["name"] == "s" and sig["byte_order"] == "little_endian"   # defaults applied


def test_convert_large_db_all_directions():
    big = {"messages": [{"name": f"M{i}", "frame_id": 256 + i, "is_extended": False, "dlc": 8,
        "signals": [{"name": f"s{i}", "start_bit": 0, "length": 8, "byte_order": "little_endian",
                     "is_signed": False, "scale": 1, "offset": 0, "min": None, "max": None,
                     "unit": "", "value_table": None, "comment": "", "ev_data": 0}]} for i in range(60)]}
    for fmt in ("dbc", "json", "csv"):
        assert cv.serialize(big, fmt)["content"].strip()
    rt = cv.parse(cv.serialize(big, "dbc")["content"], from_fmt="dbc")["model"]
    assert len(rt["messages"]) == 60


def test_json_evdata_passthrough():
    sig = {"100": [{"fieldName": "x", "reverse": 0, "startingBit": 0, "size": 8,
                    "multiplier": 1, "offset": 0, "signed": 0, "evData": 1}]}
    back = json.loads(cv.convert(json.dumps(sig), "json", filename="s.json")["content"])
    assert back["100"][0]["evData"] == 1


def test_json_signed_big_endian():
    m = jd.load_signature(json.dumps({"100": [_sig(size=16, signed=1, reverse=0)]}))
    f = jd.decode_frame(m, 100, "FFFF000000000000")      # 0xFFFF as signed16 = -1
    assert f["signals"][0]["raw"] == -1


def test_json_boundary_last_bit():
    m = jd.load_signature(json.dumps({"100": [_sig(size=1, startingBit=63, reverse=1)]}))
    f = jd.decode_frame(m, 100, "00000000000000FF")      # byte7 bit7 set -> 1
    assert f["signals"][0]["raw"] == 1
