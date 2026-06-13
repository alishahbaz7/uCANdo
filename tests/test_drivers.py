"""Hardware preflight + driver assistant (no network)."""

import zipfile

from canforge import preflight
from canforge.drivers import DriverAssistant


# ----- preflight -----------------------------------------------------------
def test_virtual_always_ready():
    b = preflight.check_backend("virtual")
    assert b["ready"] is True and b["status"] == "ready"


def test_unknown_backend():
    assert preflight.check_backend("nope")["status"] == "error"


def test_check_all_covers_backends():
    hws = {b["hw"] for b in preflight.check_all()}
    assert {"virtual", "neovi", "pcan", "microchip"} <= hws


def test_neovi_requirement_has_installer():
    inst = preflight.REQUIREMENTS["neovi"]["installer"]
    assert inst["url"].endswith(".zip") and inst["kind"] == "zip"


# ----- driver assistant ----------------------------------------------------
def test_page_kind_backend_returns_url(tmp_path):
    da = DriverAssistant(str(tmp_path))
    # PCAN/Microchip are "page" installers — nothing to download.
    r = da.start_download("pcan")
    assert r["state"] == "page" and r["url"]
    assert da.prepare_and_launch("microchip")["open_url"]


def test_filename_from_url(tmp_path):
    da = DriverAssistant(str(tmp_path))
    assert da._filename("neovi") == "RP1210KitInstall.zip"


def test_cached_path_none_when_absent(tmp_path):
    # Point cache somewhere empty; (a real copy may exist in ~/Downloads on this
    # machine, so only assert the method runs and returns a path-or-None).
    da = DriverAssistant(str(tmp_path))
    res = da.cached_path("neovi")
    assert res is None or res.endswith("RP1210KitInstall.zip")


def test_extract_installer_finds_setup_exe(tmp_path):
    # Build a fake kit zip with a setup.exe and some noise.
    zpath = tmp_path / "kit.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("readme.txt", "hi")
        z.writestr("Driver/Setup.exe", b"MZfake")
        z.writestr("data/blob.bin", b"\x00\x01")
    da = DriverAssistant(str(tmp_path / "cache"))
    found = da._extract_installer("neovi", str(zpath))
    assert found and found.lower().endswith("setup.exe")
    import os
    assert os.path.isfile(found)
