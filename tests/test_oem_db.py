"""OEM CAN Database — CRUD, fingerprint, CANMatch auto-identify, seeding."""

from canforge.dbc_builder import DbcModel
from canforge.oem_db import (
    OemDatabase, TARGET_OEMS, fingerprint_frames, fingerprint_from_id_stats,
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
    n1 = db.seed_builtins()
    assert n1 == 1 + len(TARGET_OEMS)        # sim demo + placeholders
    assert db.seed_builtins() == 0           # second run adds nothing
    names = {p["name"] for p in db.list_profiles()}
    assert "Sim Vehicle" in names


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
