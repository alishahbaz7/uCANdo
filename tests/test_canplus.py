"""CanPlus vehicle-library XML import → canonical model (see canforge/canplus.py)."""

import json

from canforge import canplus, convert as cv

# 5 real VarDesc records from the MG ZS EV library: speed, odometer, range/DTE,
# and two doors that share a frame-signature cluster (B5FF08).
XML = '''<?xml version="1.0" encoding="us-ascii"?>
<CanData><PL_Signature>554161D9</PL_Signature>
<Variable_Descriptors>
 <VarDesc Name="Vehicle Speed" RawDataStr="00-DC-05-80-13-7B-A3-00-03-00-C8-00-00-00-27-10-0D-40-81-03-8E-31"><Variable Title="Vehicle Speed" VarID="8005" Var_Function="NotAssigned" FW_Multiplier="3" FW_Divider="200" FW_Offset="0" FW_Units="km/h"/></VarDesc>
 <VarDesc Name="Total Vehicle Distance" RawDataStr="00-AC-00-80-13-AB-03-05-E8-03-01-00-00-00-27-10-0D-B9-F3-08-8E-31"><Variable Title="Total Vehicle Distance" VarID="8000" Var_Function="Odometer" FW_Multiplier="1000" FW_Divider="1" FW_Offset="0" FW_Units="m"/></VarDesc>
 <VarDesc Name="Range Vehicle in KM" RawDataStr="00-0C-3C-80-13-AB-A3-00-01-00-01-00-00-00-27-10-0D-FD-B1-06-8E-31"><Variable Title="Range" VarID="803C" Var_Function="NotAssigned" FW_Multiplier="1" FW_Divider="1" FW_Offset="0" FW_Units="km"/></VarDesc>
 <VarDesc Name="Door Driver" RawDataStr="00-DA-0D-80-13-B9-EF-00-01-00-01-00-00-00-27-10-0D-B5-FF-08-8E-31"><Variable Title="Door Driver" VarID="800D" Var_Function="NotAssigned" FW_Multiplier="1" FW_Divider="1" FW_Offset="0" FW_Units="state"/></VarDesc>
 <VarDesc Name="Door Lock" RawDataStr="00-02-11-80-13-E1-EF-00-01-00-01-00-00-00-27-10-0D-B5-FF-08-8E-31"><Variable Title="Door Lock" VarID="8011" Var_Function="NotAssigned" FW_Multiplier="1" FW_Divider="1" FW_Offset="0" FW_Units="state"/></VarDesc>
</Variable_Descriptors>
<Config><VehicleLibraryInfo><Vehicle Brand="MG" ModelName="ZS EV" ProductionYear="2020" EngineType="4"/></VehicleLibraryInfo></Config></CanData>'''


def _byname(model):
    return {s["name"]: (m, s) for m in model["messages"] for s in m["signals"]}


def test_detect_and_parse_counts():
    assert cv.detect_format("MG.Config.XML", XML) == "canplus"
    model, warns = canplus.parse_to_model(XML)
    sigs = [s for m in model["messages"] for s in m["signals"]]
    assert len(sigs) == 5
    assert any("MG ZS EV" in w for w in warns)
    assert any("PLACEHOLDER" in w for w in warns)


def test_scaling_decoded_from_binary():
    sigs = _byname(canplus.parse_to_model(XML)[0])
    # multiplier/divider come straight from the 22-byte record
    assert sigs["Vehicle_Speed"][1]["scale"] == 0.015        # 3/200
    assert sigs["Total_Vehicle_Distance"][1]["scale"] == 1000
    assert sigs["Range_Vehicle_in_KM"][1]["unit"] == "km"


def test_validated_signals_get_real_layout():
    by = _byname(canplus.parse_to_model(XML)[0])
    odo_m, odo_s = by["Total_Vehicle_Distance"]
    assert odo_m["frame_id"] == 0x540 and odo_m["is_extended"] is False
    assert odo_s["start_bit"] == 0 and odo_s["length"] == 24 and odo_s["byte_order"] == "big_endian"
    dte_m, dte_s = by["Range_Vehicle_in_KM"]
    assert dte_m["frame_id"] == 0x2A2 and dte_s["start_bit"] == 48 and dte_s["length"] == 16
    assert "validated" in odo_s["comment"]


def test_unvalidated_signals_cluster_and_placeholder():
    model = canplus.parse_to_model(XML)[0]
    by = _byname(model)
    # the two doors share the B5FF08 cluster → same frame, non-overlapping placeholders
    dm, ds = by["Door_Driver"]; lm, ls = by["Door_Lock"]
    assert dm is lm and dm.get("is_extended") is True
    assert {ds["start_bit"], ls["start_bit"]} == {0, 1}
    assert "placeholder" in ds["comment"] and ds["byte_order"] == "little_endian"


def test_canplus_exports_through_converter():
    # validated start bits convert back to the DBC Motorola positions exactly
    dbc = cv.convert(XML, "dbc", filename="MG.xml")["content"]
    assert "BO_ 1344 FRAME_540" in dbc and "Total_Vehicle_Distance : 7|24@0+" in dbc
    assert "BO_ 674 FRAME_2A2" in dbc and "Range_Vehicle_in_KM : 55|16@0+" in dbc
    # JSON export keys the (decimal) frame ids
    d = json.loads(cv.convert(XML, "json", filename="MG.xml")["content"])
    assert "1344" in d and "674" in d


def test_parse_endpoint_accepts_canplus():
    from fastapi.testclient import TestClient
    from canforge.server import app
    c = TestClient(app)
    r = c.post("/api/convert/parse",
               files={"file": ("MG.Config.XML", XML.encode(), "text/xml")}).json()
    assert r["ok"] and r["source_fmt"] == "canplus"
    assert any("PLACEHOLDER" in w for w in r["warnings"])
