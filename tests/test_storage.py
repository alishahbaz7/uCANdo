"""Persistence layer and config."""

from ucando.config import DEFAULTS, Config


def test_schema_tables_exist(storage):
    rows = storage.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    assert {"settings", "oem_profiles", "vehicles", "captures", "jobs"} <= names


def test_insert_get_list_delete(storage):
    rid = storage.insert("vehicles", name="Nexon", oem="Tata", model="Nexon", year=2024)
    row = storage.get("vehicles", rid)
    assert row["name"] == "Nexon"
    assert row["created_at"] > 0          # auto-stamped
    assert len(storage.list("vehicles")) == 1
    storage.delete("vehicles", rid)
    assert storage.get("vehicles", rid) is None


def test_settings_roundtrip(storage):
    storage.set_setting("foo", {"a": 1})
    assert storage.get_setting("foo") == {"a": 1}
    storage.set_setting("foo", 42)        # upsert
    assert storage.get_setting("foo") == 42
    assert storage.get_setting("missing", "fallback") == "fallback"


def test_oem_profile_persists(storage):
    pid = storage.insert("oem_profiles", oem="Mahindra", model="XUV700",
                         name="XUV700 base", dbc="", signature="{}")
    assert storage.get("oem_profiles", pid)["oem"] == "Mahindra"


def test_config_defaults_and_override(storage):
    cfg = Config(storage)
    assert cfg.get("default_bitrate") == DEFAULTS["default_bitrate"]
    cfg.set("default_bitrate", 250_000)
    assert cfg.get("default_bitrate") == 250_000
    assert cfg.all()["default_bitrate"] == 250_000


def test_profiles(storage):
    cfg = Config(storage)
    cfg.save_profile("bench-1", {"hw": "pcan", "channel": "PCAN_USBBUS1"})
    assert cfg.load_profile("bench-1")["hw"] == "pcan"
    assert "bench-1" in cfg.list_profiles()
