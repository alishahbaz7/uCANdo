"""uCANdo's own window (Edge app mode), as Runway opens it."""
import json
import sqlite3
import tempfile
from pathlib import Path

from ucando import desktop


def test_app_window_is_edge_app_mode_in_its_own_quiet_profile():
    cmd = desktop.app_window_command("msedge.exe", "http://127.0.0.1:8865/", "D:/u/data/window", dark=True)
    assert cmd[0] == "msedge.exe" and "--app=http://127.0.0.1:8865/" in cmd
    assert "--user-data-dir=D:/u/data/window" in cmd
    # a fresh profile must not sign in or sync — Edge's sync dialog would cover the first window
    assert {"--no-first-run", "--no-default-browser-check", "--disable-sync"} <= set(cmd)
    assert "--force-dark-mode" in cmd


def test_light_theme_opens_a_light_window():
    assert "--force-dark-mode" not in desktop.app_window_command("e", "u", "p", dark=False)


def _db_with_theme(folder: Path, value):
    con = sqlite3.connect(folder / "ucando.db")
    con.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if value is not None:
        con.execute("INSERT INTO settings VALUES ('ui_theme', ?)", (json.dumps(value),))
    con.commit()
    con.close()


def test_saved_theme_decides_the_window_mode():
    with tempfile.TemporaryDirectory() as d:
        assert desktop.saved_theme_is_dark(d) is True            # no database yet: dark, the default
        _db_with_theme(Path(d), "light")
        assert desktop.saved_theme_is_dark(d) is False
    with tempfile.TemporaryDirectory() as d:
        _db_with_theme(Path(d), "dark")
        assert desktop.saved_theme_is_dark(d) is True
    with tempfile.TemporaryDirectory() as d:
        _db_with_theme(Path(d), None)                            # never saved: dark
        assert desktop.saved_theme_is_dark(d) is True


# ---- the taskbar: uCANdo's own button, with its own logo -------------------------------------
# Edge names an app window's taskbar identity after the host and the window profile's folder:
# uCANdo and Runway, both 127.0.0.1 from a folder called "window", were ONE app to Windows —
# one button, one icon (the user, 25-11-2026). Measured on real windows, those IDs were:
SHARED = "MSEdge.127.0.0.1_/.window.Default"
MEASURED_LONG = ("uCANdo-dev-window", "MSEdge.127.0.0.1_/.uCANdodevwow.Default")


def test_each_channel_has_a_profile_of_its_own_name(tmp_path):
    rel = desktop.window_profile(str(tmp_path), "release")
    dev = desktop.window_profile(str(tmp_path), "dev")
    assert Path(rel).name == "uCANdoWindow" and Path(dev).name == "uCANdoDevWin"
    # twelve letters, no punctuation: Edge keeps them whole in the ID
    for p in (rel, dev):
        assert Path(p).name.isalnum() and len(Path(p).name) <= 12
        assert desktop.edge_profile_id(p) == Path(p).name + ".Default"


def test_edge_profile_id_follows_edges_own_shortening():
    name, app_id = MEASURED_LONG
    assert app_id.endswith("." + desktop.edge_profile_id("D:/x/data/" + name))
    assert desktop.edge_profile_id("D:/x/data/window") == "window.Default"


def test_a_window_is_ours_only_by_our_profiles_identity(tmp_path):
    rel = desktop.window_profile(str(tmp_path), "release")
    assert desktop.owns_app_id("MSEdge.127.0.0.1_/.uCANdoWindow.Default", rel)
    assert not desktop.owns_app_id(SHARED, rel)                                   # the old shared one
    assert not desktop.owns_app_id("MSEdge.127.0.0.1_/.uCANdoDevWin.Default", rel)  # the dev copy's
    assert not desktop.owns_app_id("MSEdge.127.0.0.1_/.RunwayWindow.Default", rel)  # Runway's
    assert not desktop.owns_app_id(None, rel)


def test_the_old_profile_moves_so_the_page_keeps_its_settings(tmp_path):
    old = tmp_path / "window"
    (old / "Default").mkdir(parents=True)
    (old / "Default" / "marker").write_text("theme, views, pins", encoding="utf-8")
    new = desktop.window_profile(str(tmp_path), "release")
    assert desktop.adopt_old_profile(str(tmp_path), new) == new
    assert (Path(new) / "Default" / "marker").read_text(encoding="utf-8") == "theme, views, pins"
    assert not old.exists()
    # a second start: nothing to move
    assert desktop.adopt_old_profile(str(tmp_path), new) == new


def test_an_old_profile_still_in_use_is_used_once_more(tmp_path, monkeypatch):
    (tmp_path / "window").mkdir()
    new = desktop.window_profile(str(tmp_path), "release")

    def locked(*_a):
        raise PermissionError("Edge holds it")
    monkeypatch.setattr(desktop.os, "rename", locked)
    assert desktop.adopt_old_profile(str(tmp_path), new) == str(tmp_path / "window")


def test_a_pinned_button_starts_uCANdo_with_its_logo(tmp_path):
    rel = desktop.relaunch_details("release", frozen=True, executable="C:/Apps/uCANdo/uCANdo.exe")
    assert rel["command"].endswith('uCANdo.exe') and rel["icon"].endswith("uCANdo.exe,0")
    assert rel["name"] == "uCANdo"
    dev = desktop.relaunch_details("dev", frozen=False, executable="C:/py/python.exe")
    assert "python.exe" in dev["command"] and dev["command"].rstrip('"').endswith("main.py")
    assert dev["icon"].endswith("ucando.ico,0") and dev["name"] == "uCANdo (dev)"


def test_the_logo_ships_as_a_multi_size_icon():
    ico = Path(__file__).resolve().parent.parent / "packaging" / "ucando.ico"
    head = ico.read_bytes()[:6]
    assert head[:4] == b"\x00\x00\x01\x00"                     # an .ico
    assert int.from_bytes(head[4:6], "little") >= 5            # 16 … 256 px
    spec = (ico.parent / "uCANdo.spec").read_text(encoding="utf-8")
    assert "ucando.ico" in spec                                # the exe carries it
