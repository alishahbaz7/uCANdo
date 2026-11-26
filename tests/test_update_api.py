"""The update routes the page drives, and what an update's restart says it will stop.

A run from source (every test) never checks: the channel is GitHub and a test must not reach it.
The updater's own cases — real sockets, a dropped connection, the install beside — are in
test_update.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ucando import install, server


def test_a_source_run_does_not_check_and_says_why():
    with TestClient(server.app) as c:
        s = c.get("/api/update").json()
        assert s["stage"] == "disabled" and "source" in s["disabled_reason"]
        assert s["current"] == server.__version__ and s["can_install_here"] is False
        assert c.post("/api/update/check").json()["stage"] == "disabled"
        assert c.post("/api/update/install").json()["available"] is False


def test_the_channel_is_the_public_releases_repo():
    from ucando.update import config
    # the source repo is private: copies could never read its releases (the user, 2026-11-26)
    assert config.REPO == "alishahbaz7/uCANdo-releases"
    assert config.MANIFEST_URL.endswith("/uCANdo-releases/releases/latest/download/latest.json")
    assert config.asset_url("1.6.0").endswith("/download/v1.6.0/uCANdo-v1.6.0.zip")


def test_the_offer_names_what_the_restart_stops(monkeypatch):
    monkeypatch.setattr(server.replayer, "status", lambda: {"state": "playing"})
    monkeypatch.setattr(server.restbus, "status", lambda: {"running": True})
    monkeypatch.setattr(server.bus, "iface", object())          # connected
    said = server._update_interrupts()
    assert "TX replay is playing: it stops" in said
    assert "The restbus simulation stops" in said
    assert any("bus disconnects" in s for s in said)


def test_nothing_running_means_nothing_to_warn_about(monkeypatch):
    monkeypatch.setattr(server.replayer, "status", lambda: {"state": "idle"})
    monkeypatch.setattr(server.restbus, "status", lambda: {"running": False})
    monkeypatch.setattr(server.bus, "iface", None)
    assert server._update_interrupts() == []


def test_a_launcher_install_keeps_data_beside_the_launcher(tmp_path):
    exe = tmp_path / "versions" / "uCANdo-v1.6.0" / "uCANdo-v1.6.0.exe"
    assert install.launcher_root(str(exe)) == str(tmp_path)
    # a pre-1.6 copy unzipped by hand is not a launcher install: its data stays beside its exe
    assert install.launcher_root(str(tmp_path / "uCANdo" / "uCANdo.exe")) is None
    # a folder whose name and program disagree is not one either
    assert install.launcher_root(str(tmp_path / "versions" / "uCANdo-v1.6.0" / "other.exe")) is None
