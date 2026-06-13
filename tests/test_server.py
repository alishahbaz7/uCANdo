"""End-to-end API smoke tests via FastAPI TestClient (no hardware)."""

import uuid

import can
from fastapi.testclient import TestClient

from canforge.server import app
from tests.conftest import wait_until

client = TestClient(app)


def test_info_and_plugins():
    info = client.get("/api/info").json()
    assert info["app"] == "CANForge"
    assert "plugins_loaded" in info

    plugins = client.get("/api/plugins").json()
    assert {"re_engine", "decoder", "exporter", "oem_pack"} <= set(plugins)


def test_devices_lists_virtual():
    devs = client.get("/api/devices").json()["devices"]
    assert any(d["hw"] == "virtual" for d in devs)


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
