"""End-to-end API smoke tests via FastAPI TestClient (no hardware)."""

import uuid

from fastapi.testclient import TestClient

from canforge.server import app

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
