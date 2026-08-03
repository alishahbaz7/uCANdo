"""OEM CAN Database — CRUD, fingerprint, CANMatch auto-identify, seeding."""

from ucando.dbc_builder import DbcModel
from ucando.oem_db import (
    OemDatabase, fingerprint_frames, fingerprint_from_id_stats,
)


def _frames(ids):
    return {(i, False): {"payloads": [bytes(8)], "timestamps": [0.0, 0.01]} for i in ids}


def test_fingerprint_id_set():
    sig = fingerprint_frames(_frames([0x100, 0x200]))
    assert set(sig["id_set"]) == {"100", "200"}


def test_fingerprint_from_id_stats():
    sig = fingerprint_from_id_stats([{"id": 0x100, "ext": False, "dlc": 8, "period_ms": 10}])
    assert sig["id_set"] == ["100"]


def test_crud(storage):
    db = OemDatabase(storage)
    pid = db.add_profile("Tata", "Nexon 2024", model="Nexon", status="draft")
    assert db.get_profile(pid)["oem"] == "Tata"
    db.update_profile(pid, {"status": "reviewed"})
    assert db.get_profile(pid)["status"] == "reviewed"
    db.delete_profile(pid)
    assert db.get_profile(pid) is None


def test_import_dbc_builds_signature(storage):
    db = OemDatabase(storage)
    m = DbcModel()
    m.add_message(0x3B4, "VEHICLE", length=8)
    m.add_signal(0x3B4, {"name": "Speed", "start_bit": 0, "length": 8, "byte_order": "little_endian"})
    pid = db.import_dbc("Mahindra", "XUV700", m.to_dbc_string())
    prof = db.get_profile(pid)
    assert "3B4" in prof["signature"]["id_set"]


def test_seed_builtins_idempotent(storage):
    db = OemDatabase(storage)
    assert db.seed_builtins() == 1           # sim demo only — no empty placeholders
    assert db.seed_builtins() == 0           # second run adds nothing
    profiles = db.list_profiles()
    assert {p["name"] for p in profiles} == {"Sim Vehicle"}
    assert all(p["id_count"] for p in profiles)


def _two_signal_dbc() -> str:
    m = DbcModel()
    m.add_message(0x120, "ODO", length=5)
    m.add_signal(0x120, {"name": "Odometer", "start_bit": 7, "length": 32,
                         "byte_order": "big_endian", "scale": 0.1, "unit": "km"})
    m.add_message(0x2A2, "RANGE", length=8)
    m.add_signal(0x2A2, {"name": "Dte", "start_bit": 0, "length": 16,
                         "byte_order": "little_endian"})
    return m.to_dbc_string()


def test_list_profiles_counts_messages_signals_and_year(storage):
    db = OemDatabase(storage)
    # A capture-derived signature deliberately carries more IDs than the DBC
    # decodes — the list must report both, not conflate them.
    sig = {"ids": [{"id": i, "ext": False, "dlc": 8, "period_ms": 10.0}
                   for i in (0x120, 0x2A2, 0x333)],
           "id_set": ["120", "2A2", "333"]}
    pid = db.add_profile("MG", "Windsor EV 2026", model="Windsor",
                         dbc=_two_signal_dbc(), signature=sig,
                         year_min=2026, year_max=2026)
    row = next(p for p in db.list_profiles() if p["id"] == pid)
    assert (row["id_count"], row["msg_count"], row["signal_count"]) == (3, 2, 2)
    assert row["year"] == "2026"
    assert "dbc" not in row                       # list payload stays light

    ranged = db.add_profile("Tata", "Nexon", dbc=_two_signal_dbc(),
                            year_min=2020, year_max=2023)
    named = db.add_profile("Hyundai", "Aura 2023 (HSCAN1)", dbc=_two_signal_dbc())
    by_id = {p["id"]: p for p in db.list_profiles()}
    assert by_id[ranged]["year"] == "2020–2023"
    assert by_id[named]["year"] == "2023"          # fallback: read from the name


def test_profile_signals_expands_the_dbc(storage):
    db = OemDatabase(storage)
    pid = db.add_profile("MG", "Windsor EV 2026", model="Windsor", dbc=_two_signal_dbc())
    d = db.profile_signals(pid)
    assert (d["msg_count"], d["signal_count"]) == (2, 2)
    assert [m["id_hex"] for m in d["messages"]] == ["120", "2A2"]   # sorted by frame id
    odo = d["messages"][0]["signals"][0]
    assert (odo["name"], odo["length"], odo["scale"], odo["unit"]) == ("Odometer", 32, 0.1, "km")

    assert db.profile_signals(999999) is None                      # no such profile
    bad = db.add_profile("MG", "Corrupt", dbc="not a dbc at all")
    assert db.profile_signals(bad)["error"] and db.profile_signals(bad)["messages"] == []


def test_prune_blank_drops_empty_and_repairs_stale_signature(storage):
    db = OemDatabase(storage)
    db.seed_builtins()
    empty = db.add_profile("Tata", "Tata (no data yet)")            # no DBC at all
    header_only = db.add_profile("MG", "Half-saved", dbc=DbcModel().to_dbc_string())

    m = DbcModel()
    m.add_message(0x3B4, "VEHICLE", length=8)
    stale = db.add_profile("Mahindra", "XUV700", dbc=m.to_dbc_string(),
                           signature={"ids": [], "id_set": []})     # signature never built

    assert db.prune_blank() == 2
    assert db.prune_blank() == 0                                    # idempotent
    names = {p["name"] for p in db.list_profiles()}
    assert names == {"Sim Vehicle", "XUV700"}
    assert db.get_profile(empty) is None and db.get_profile(header_only) is None
    assert db.get_profile(stale)["signature"]["id_set"] == ["3B4"]  # repaired, not deleted


def test_identify_matches_sim_profile(storage):
    db = OemDatabase(storage)
    db.seed_builtins()
    matches = db.identify(_frames([0x100, 0x200]))
    assert matches
    assert matches[0]["name"] == "Sim Vehicle"
    assert matches[0]["score"] >= 0.9


def test_identify_no_match_below_threshold(storage):
    db = OemDatabase(storage)
    db.seed_builtins()
    # Totally different IDs → no confident match.
    assert db.identify(_frames([0x555, 0x666, 0x777]), min_score=0.5) == []
