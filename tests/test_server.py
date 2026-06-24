"""End-to-end API smoke tests via FastAPI TestClient (no hardware)."""

import uuid

import can
from fastapi.testclient import TestClient

from canforge.server import app
from tests.conftest import wait_until

client = TestClient(app)


def test_info_and_plugins():
    info = client.get("/api/info").json()
    assert info["app"] == "uCANdo"
    assert "plugins_loaded" in info

    plugins = client.get("/api/plugins").json()
    assert {"re_engine", "decoder", "exporter", "oem_pack"} <= set(plugins)


def test_devices_lists_virtual():
    devs = client.get("/api/devices").json()["devices"]
    assert any(d["hw"] == "virtual" for d in devs)


def test_drivers_status():
    backends = client.get("/api/drivers/status").json()["backends"]
    by_hw = {b["hw"]: b for b in backends}
    assert by_hw["virtual"]["ready"] is True
    # neovi (if its driver/lib isn't ready) should expose an installer remedy.
    nv = by_hw["neovi"]
    if not nv["ready"]:
        assert nv["remedy"]["type"] in ("installer", "pip")


def test_config_get_and_set():
    assert "default_bitrate" in client.get("/api/config").json()
    r = client.post("/api/config", json={"key": "ui_theme", "value": "light"}).json()
    assert r["ok"] and r["config"]["ui_theme"] == "light"


def test_re_engines_listed():
    engines = client.get("/api/re/engines").json()["engines"]
    names = {e["name"] for e in engines}
    assert {"read", "basic"} <= names


def test_re_promote_seeds_dbc():
    id_result = {
        "id": 0x123, "id_hex": "123", "ext": False, "length": 8,
        "candidates": [
            {"start_bit": 0, "length": 8, "name": "keep", "confidence": 0.9},
            {"start_bit": 8, "length": 8, "name": "drop", "confidence": 0.1},
        ],
    }
    r = client.post("/api/re/promote",
                    json={"id_result": id_result, "min_confidence": 0.5}).json()
    assert r["ok"] is True
    msg = next(m for m in r["messages"] if m["frame_id"] == 0x123)
    names = {s["name"] for s in msg["signals"]}
    assert "keep" in names and "drop" not in names


def test_connect_status_disconnect_virtual():
    chan = f"srv-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/connect", json={"hw": "virtual", "channel": chan,
                                          "simulate": True}).json()
    assert r["ok"] is True
    try:
        status = client.get("/api/status").json()
        assert status["connected"] is True
        assert status["connection"]["channel"] == chan
    finally:
        d = client.post("/api/disconnect").json()
        assert d["connected"] is False


def test_oem_profiles_seeded_and_identify_live():
    data = client.get("/api/oem/profiles").json()
    assert "Tata" in data["targets"]
    assert any(p["name"] == "Sim Vehicle" for p in data["profiles"])

    chan = f"oem-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/connect", json={"hw": "virtual", "channel": chan,
                                             "simulate": True}).json()["ok"]
    try:
        assert wait_until(lambda: client.get("/api/oem/identify").json().get("observed_ids", 0) >= 2,
                          timeout=4.0)
        ident = client.get("/api/oem/identify").json()
        assert any(m["name"] == "Sim Vehicle" for m in ident["matches"])
        pid = next(m["profile_id"] for m in ident["matches"] if m["name"] == "Sim Vehicle")
        assert client.post(f"/api/oem/apply?pid={pid}").json()["ok"]
    finally:
        client.post("/api/disconnect")


def test_signals_computed_and_alarms():
    assert client.post("/api/signals/computed",
                       json={"defs": [{"name": "Dbl", "expr": "sig('M.A') * 2"}]}).json()["ok"]
    r = client.post("/api/signals/alarms",
                    json={"defs": [{"name": "Hot", "key": "M.Temp", "max": 90}]}).json()
    assert r["ok"]
    d = client.get("/api/signals/derived").json()
    assert any(c["name"] == "Dbl" for c in d["computed"])
    assert any(a["name"] == "Hot" for a in d["alarms"])


def test_oem_auto_apply_on_sim():
    chan = f"auto-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/connect", json={"hw": "virtual", "channel": chan,
                                             "simulate": True}).json()["ok"]
    try:
        assert wait_until(lambda: client.get("/api/oem/identify").json().get("observed_ids", 0) >= 2,
                          timeout=4.0)
        r = client.post("/api/oem/auto-apply").json()
        assert r.get("ok") and r["applied"]["name"] == "Sim Vehicle"
        assert r["loaded"] is True            # DBC now loaded in the Signal Viewer
    finally:
        client.post("/api/disconnect")


def test_autore_analyze_confirm_save(tmp_path):
    import math, struct
    p = str(tmp_path / "auto.asc")
    w = can.ASCWriter(p)
    for i in range(300):
        rpm = int(2000 + 1500 * math.sin(i / 30.0))
        w.on_message_received(can.Message(arbitration_id=0x100, data=struct.pack("<H", rpm) + b"\0\0\0\0\0\0",
                                          is_extended_id=False, timestamp=i * 0.05))
        r = rpm * 4
        w.on_message_received(can.Message(arbitration_id=0x7E8,
                                          data=bytes([0x04, 0x41, 0x0C, (r >> 8) & 0xFF, r & 0xFF, 0, 0, 0]),
                                          is_extended_id=False, timestamp=i * 0.05 + 0.01))
    w.stop()

    rep = client.post("/api/autore/analyze-log", json={"path": p, "known_values": {}}).json()
    assert rep["ok"] is True
    a = rep["report"]["A"]
    # RPM lands in the high tier (label "Engine RPM" from correlation or
    # "EngineRPM" if a saved profile also matched via DB-match — either is fine).
    assert any("RPM" in (s["label"] or "") for s in a)

    assert {"petrol", "ev"} <= set(client.get("/api/autore/protocols").json()["protocols"])

    # Save tier A as a profile.
    sv = client.post("/api/autore/save-profile",
                     json={"oem": "Test", "name": "AutoReProf", "tiers": ["A"]}).json()
    assert sv["ok"] is True and sv["profile"]["oem"] == "Test"


def test_decode_dbc_frames_endpoint():
    from canforge.dbc_builder import DbcModel
    m = DbcModel()
    m.add_message(0x94, "M94", length=8)
    m.add_signal(0x94, {"name": "Speed", "start_bit": 3, "length": 12,
                        "byte_order": "big_endian", "scale": 10, "offset": 0})
    dbc_text = m.to_dbc_string()

    imp = client.post("/api/decode/dbc-import",
                      files={"file": ("t.dbc", dbc_text, "text/plain")}).json()
    assert imp["ok"] and any(msg["id_hex"] == "94" for msg in imp["messages"])

    dec = client.post("/api/decode/frames",
                      json={"frames": [{"id": "94", "data": "0006320040001C00"}]}).json()
    assert dec["ok"]
    sig = next(s for s in dec["frames"][0]["signals"] if s["name"] == "Speed")
    assert float(sig["physical"]) == 60.0 and len(sig["cells"]) == 12


def test_oem_from_builder_and_delete():
    client.post("/api/dbc/set", json={"messages": [
        {"frame_id": 0x321, "name": "M", "length": 8, "is_extended": False,
         "signals": [{"name": "s", "start_bit": 0, "length": 8, "byte_order": "little_endian"}]}]})
    r = client.post("/api/oem/from-builder", json={"oem": "Test", "name": "Prof321"}).json()
    assert r["ok"] and r["profile"]["oem"] == "Test"
    assert client.post(f"/api/oem/profile/delete?pid={r['id']}").json()["ok"]


def test_sniffer_live_through_bus():
    chan = f"sniff-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/connect", json={"hw": "virtual", "channel": chan,
                                             "simulate": False}).json()["ok"]
    sender = can.Bus(interface="virtual", channel=chan, bitrate=500_000)
    try:
        assert client.post("/api/re/sniff/arm").json()["phase"] == "baseline"
        for _ in range(8):
            sender.send(can.Message(arbitration_id=0x301, data=b"\x00\xAA", is_extended_id=False))
        assert wait_until(lambda: client.get("/api/re/sniff/status").json()["baseline_frames"] >= 8)
        client.post("/api/re/sniff/mark")
        for v in (0x00, 0x01, 0x00, 0x01, 0x00, 0x01):
            sender.send(can.Message(arbitration_id=0x301, data=bytes([v, 0xAA]), is_extended_id=False))
        assert wait_until(lambda: client.get("/api/re/sniff/status").json()["after_frames"] >= 6)
        res = client.get("/api/re/sniff/result").json()["result"]
        assert any(c["id_hex"] == "301" for c in res["changed"])
    finally:
        client.post("/api/re/sniff/stop")
        sender.shutdown()
        client.post("/api/disconnect")
