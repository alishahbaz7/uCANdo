"""Persistence layer and config."""

from ucando.config import DEFAULTS, Config
from ucando.storage import Storage, adopt_legacy_db


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


# ----- pre-rename database adoption (CANForge → uCANdo, v1.4.1) -------------

def test_adopt_legacy_db_carries_data_over_including_the_wal(tmp_path):
    """A canforge.db beside the new path is adopted, uncheckpointed writes too."""
    legacy = tmp_path / "canforge.db"
    old = Storage(str(legacy))
    old.insert("vehicles", name="Aura", oem="Hyundai", model="Aura", year=2023)
    old.set_setting("default_channel", "ucando")
    # `old` is deliberately left open: those commits are still sitting in the
    # -wal file, which is precisely what a plain file copy would have dropped.

    new = tmp_path / "ucando.db"
    assert adopt_legacy_db(str(new)) == str(legacy)

    adopted = Storage(str(new))
    assert [r["name"] for r in adopted.list("vehicles")] == ["Aura"]
    assert adopted.get_setting("default_channel") == "ucando"
    assert legacy.exists()                      # original kept as a backup
    old.close()
    adopted.close()


def test_adopt_legacy_db_never_clobbers_an_existing_db(tmp_path):
    legacy = Storage(str(tmp_path / "canforge.db"))
    legacy.insert("vehicles", name="stale")
    current = Storage(str(tmp_path / "ucando.db"))
    current.insert("vehicles", name="current")

    assert adopt_legacy_db(str(tmp_path / "ucando.db")) is None
    assert [r["name"] for r in current.list("vehicles")] == ["current"]
    legacy.close()
    current.close()


def test_adopt_legacy_db_is_a_noop_without_a_legacy_file(tmp_path):
    new = tmp_path / "ucando.db"
    assert adopt_legacy_db(str(new)) is None
    assert not new.exists()                     # no empty file left behind
    assert adopt_legacy_db(":memory:") is None
