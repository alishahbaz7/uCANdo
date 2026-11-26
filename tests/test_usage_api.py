"""Usage reporting (user skill app-control) as uCANdo wires it.

The suite runs with UCANDO_USAGE=off (conftest), so the app's own reporter is off;
the first-start behaviour is checked on a reporter of its own, with a transport
that records instead of sending — nothing here can reach the real server.
"""
import tempfile

from fastapi.testclient import TestClient

from ucando import usage as usage_mod
from ucando.server import BUILD, app
from ucando.usage_client import UsageReporter

client = TestClient(app)


def test_reporting_is_off_under_test_and_says_why():
    s = client.get("/api/usage").json()
    assert s["enabled"] is False
    assert s["needs_name"] is False            # an off copy never asks for a name
    assert s["disabled_reason"]                 # …and the Settings card says why, in words
    assert s["build"] == BUILD


def test_a_source_run_does_not_report_unless_switched_on(monkeypatch):
    monkeypatch.setattr(usage_mod, "SWITCHED_OFF", False)
    monkeypatch.setattr(usage_mod, "FORCED_ON", False)
    with tempfile.TemporaryDirectory() as d:
        assert usage_mod.create(d, "dev").enabled is False       # the user's choice: release only
        assert usage_mod.create(d, "release").enabled is True
        monkeypatch.setattr(usage_mod, "FORCED_ON", True)
        assert usage_mod.create(d, "dev").enabled is True        # UCANDO_USAGE=on, to check the flow


def test_the_first_start_asks_the_name_then_greets():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        r = UsageReporter(app="uCANdo", version="0", data_dir=d, enabled=True, build="dev",
                          url="http://127.0.0.1:9/never", transport=lambda *a, **k: sent.append(a) or {"ok": True},
                          facts={"platform": "windows"})
        r.start(background=False, at_exit=False)
        assert r.needs_name                      # first start: ask once
        r.set_name("Asha", send_now=False)
        assert not r.needs_name and r.name == "Asha"
        st = usage_mod.status(r, "dev")
        assert st["name"] == "Asha" and st["disabled_reason"] is None
        r.stop()


def test_name_route_refuses_empty_and_overlong():
    assert client.post("/api/usage/name", json={"name": "   "}).status_code == 400
    assert client.post("/api/usage/name", json={"name": "x" * 81}).status_code == 400


def test_view_route_counts_known_views_only():
    # the page may only name a NAV id — free text never reaches the report
    assert client.post("/api/usage/view", json={"view": "signals"}).json() == {"ok": True}
    assert client.post("/api/usage/view", json={"view": "<script>"}).json() == {"ok": True}
    assert "signals" in usage_mod.VIEWS and "<script>" not in usage_mod.VIEWS


def test_counts_are_camel_case_numbers_only():
    usage_mod.count("busConnects")
    m = usage_mod._metrics()
    assert all(isinstance(v, int) for v in m.values())
    assert all(k[:1].islower() and "_" not in k for k in m)


def test_send_now_answers_at_once_when_off():
    r = client.post("/api/usage/send").json()
    assert r["sending"] is False and r["enabled"] is False
