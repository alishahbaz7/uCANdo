"""oem_packs/ library auto-loading + EV charge math channels.

Covers the two things that let a known vehicle decode with zero RE:
seeding profiles straight from the pack folder tree, and deriving charge state
from pack V/I without any vehicle-specific reverse engineering.
"""

import json

import pytest

from ucando.derived import (ComputedSignals, detect_ev_keys, ev_charge_channels)
from ucando.oem_db import OemDatabase, iter_packs

MINI_DBC = """VERSION ""

NS_ :

BS_:

BU_:

BO_ 647 HSC_HvPower: 8 Vector__XXX
 SG_ PackCurrent : 7|16@0+ (0.1,-1000) [-1000|5535] "A" Vector__XXX
 SG_ PackVoltage : 23|16@0+ (0.1,0) [0|1000] "V" Vector__XXX

BO_ 874 HSC_BatterySoc: 8 Vector__XXX
 SG_ StateOfCharge : 15|8@0+ (0.5,0) [0|127.5] "%" Vector__XXX
"""


def _pack(root, oem, model, variant, *, signature=None):
    d = root / oem / model / variant
    d.mkdir(parents=True)
    (d / f"{oem.lower()}_{model.lower()}_{variant.lower()}.dbc").write_text(
        MINI_DBC, encoding="utf-8")
    if signature is not None:
        (d / "signature.json").write_text(json.dumps(signature), encoding="utf-8")
    return d


# ----- pack discovery -------------------------------------------------------

def test_iter_packs_parses_make_model_fuel_year(tmp_path):
    _pack(tmp_path, "MG", "Windsor", "EV_2026")
    _pack(tmp_path, "Hyundai", "Aura", "Petrol_2023")
    packs = {p["name"]: p for p in iter_packs(tmp_path)}
    assert set(packs) == {"Windsor EV 2026", "Aura Petrol 2023"}
    w = packs["Windsor EV 2026"]
    assert (w["oem"], w["model"], w["fuel"], w["year"]) == ("MG", "Windsor", "EV", 2026)
    assert "HSC_HvPower" in w["dbc"]


def test_iter_packs_prefers_capture_derived_signature(tmp_path):
    sig = {"ids": [{"id": 1, "ext": False, "dlc": 8, "period_ms": 10.0}], "id_set": ["1"]}
    _pack(tmp_path, "MG", "Windsor", "EV_2026", signature=sig)
    assert iter_packs(tmp_path)[0]["signature"] == sig


def test_two_taps_of_one_vehicle_do_not_collide(tmp_path):
    """An OBD-2 tap and a powertrain-local tap see different bus segments, so
    the same vehicle can legitimately need two DBCs in one folder."""
    d = tmp_path / "MG" / "ZS" / "EV_2022"
    d.mkdir(parents=True)
    (d / "mg_zs_ev_2022_obd.dbc").write_text(MINI_DBC, encoding="utf-8")
    (d / "mg_zs_ev_2022_aps.dbc").write_text(MINI_DBC, encoding="utf-8")
    packs = {p["name"]: p for p in iter_packs(tmp_path)}
    assert set(packs) == {"ZS EV 2022 (obd)", "ZS EV 2022 (aps)"}
    assert packs["ZS EV 2022 (aps)"]["bus"] == "aps"
    assert packs["ZS EV 2022 (obd)"]["year"] == 2022


def test_per_dbc_signature_beats_folder_signature(tmp_path):
    d = tmp_path / "MG" / "ZS" / "EV_2022"
    d.mkdir(parents=True)
    (d / "mg_zs_ev_2022_obd.dbc").write_text(MINI_DBC, encoding="utf-8")
    (d / "mg_zs_ev_2022_aps.dbc").write_text(MINI_DBC, encoding="utf-8")
    (d / "signature.json").write_text(json.dumps({"ids": [], "id_set": ["FOLDER"]}),
                                      encoding="utf-8")
    (d / "mg_zs_ev_2022_aps.signature.json").write_text(
        json.dumps({"ids": [], "id_set": ["APS"]}), encoding="utf-8")
    packs = {p["name"]: p for p in iter_packs(tmp_path)}
    assert packs["ZS EV 2022 (aps)"]["signature"]["id_set"] == ["APS"]
    assert packs["ZS EV 2022 (obd)"]["signature"]["id_set"] == ["FOLDER"]


def test_single_dbc_has_no_bus_suffix_in_name(tmp_path):
    _pack(tmp_path, "MG", "Windsor", "EV_2026")
    p = iter_packs(tmp_path)[0]
    assert p["name"] == "Windsor EV 2026" and p["bus"] == "CAN"


def test_year_may_be_omitted_when_unknown(tmp_path):
    """Better a pack with no year than a fabricated one."""
    _pack(tmp_path, "MG", "ZS", "EV")
    p = iter_packs(tmp_path)[0]
    assert p["name"] == "ZS EV" and p["year"] is None and p["fuel"] == "EV"


def test_iter_packs_tolerates_missing_dir_and_bad_signature(tmp_path):
    assert iter_packs(tmp_path / "nope") == []
    d = _pack(tmp_path, "MG", "ZS", "EV_2022")
    (d / "signature.json").write_text("{not json", encoding="utf-8")
    # bad sibling JSON must not lose the pack — it falls back to a DBC signature
    assert iter_packs(tmp_path)[0]["signature"] is None


# ----- seeding --------------------------------------------------------------

def test_seed_without_packs_dir_is_unchanged(storage):
    """The default must stay pure so the library has no repo-layout dependency."""
    assert OemDatabase(storage).seed_builtins() == 1


def test_seed_loads_packs_and_is_idempotent(storage, tmp_path):
    _pack(tmp_path, "MG", "Windsor", "EV_2026")
    db = OemDatabase(storage)
    assert db.seed_builtins(packs_dir=tmp_path) == 2
    assert db.seed_builtins(packs_dir=tmp_path) == 0
    prof = next(p for p in db.list_profiles() if p["name"] == "Windsor EV 2026")
    assert (prof["oem"], prof["status"], prof["year_min"]) == ("MG", "shipped", 2026)


def test_renaming_a_pack_folder_does_not_leave_an_orphan(storage, tmp_path):
    """The folder tree is the source of truth. Renaming EV -> EV_2026 must not
    leave the old profile behind, or the DB lists one vehicle twice."""
    import shutil
    _pack(tmp_path, "MG", "ZS", "EV")
    db = OemDatabase(storage)
    db.seed_builtins(packs_dir=tmp_path)
    assert {p["name"] for p in db.list_profiles()} >= {"ZS EV"}

    shutil.move(str(tmp_path / "MG" / "ZS" / "EV"), str(tmp_path / "MG" / "ZS" / "EV_2026"))
    db.seed_builtins(packs_dir=tmp_path)
    names = {p["name"] for p in db.list_profiles()}
    assert "ZS EV 2026" in names
    assert "ZS EV" not in names                       # the orphan is gone


def test_pruning_never_touches_hand_made_profiles(storage, tmp_path):
    """Only rows the seeder created are eligible — user work is sacred."""
    db = OemDatabase(storage)
    db.add_profile("Acme", "My Own RE", dbc=MINI_DBC, status="draft")
    _pack(tmp_path, "MG", "Windsor", "EV_2026")
    db.seed_builtins(packs_dir=tmp_path)
    db.seed_builtins(packs_dir=tmp_path / "empty")     # no packs at all
    assert "My Own RE" in {p["name"] for p in db.list_profiles()}


def test_seeded_pack_identifies_from_its_capture_signature(storage, tmp_path):
    """A capture-derived signature is what makes live auto-identify work."""
    ids = [{"id": i, "ext": False, "dlc": 8, "period_ms": 10.0} for i in (0x120, 0x155, 0x287)]
    sig = {"ids": ids, "id_set": [f"{r['id']:X}" for r in ids]}
    _pack(tmp_path, "MG", "Windsor", "EV_2026", signature=sig)
    db = OemDatabase(storage)
    db.seed_builtins(packs_dir=tmp_path)
    m = db.identify_from_signature(sig)
    assert m and m[0]["name"] == "Windsor EV 2026" and m[0]["score"] >= 0.9


# ----- EV charge channels ---------------------------------------------------

def test_detect_ev_keys_matches_on_signal_name():
    keys = ["HSC_HvPower.PackVoltage", "HSC_HvPower.PackCurrent",
            "HSC_BatterySoc.StateOfCharge", "X.Irrelevant"]
    assert detect_ev_keys(keys) == {"volts": "HSC_HvPower.PackVoltage",
                                    "amps": "HSC_HvPower.PackCurrent",
                                    "soc": "HSC_BatterySoc.StateOfCharge"}
    assert detect_ev_keys(["A.Nope"]) == {}


def _evaluate(defs, values):
    c = ComputedSignals()
    c.set(defs)
    return c.evaluate(values)


def test_ev_charge_channels_reproduce_the_measured_windsor_session():
    """-7.0 A at 380.7 V is the real slow-AC session — 2.66 kW, class 1."""
    defs = ev_charge_channels("P.PackVoltage", "P.PackCurrent", "B.StateOfCharge", 38.0)
    out = _evaluate(defs, {"P.PackVoltage": 380.7, "P.PackCurrent": -7.0,
                           "B.StateOfCharge": 83.0})
    assert out["ChargePower_kW"] == pytest.approx(2.665, abs=0.01)
    assert out["IsCharging"] == 1.0
    assert out["ChargerClass"] == 1.0                       # slow AC
    assert out["TimeToFull_min"] == pytest.approx(145.4, abs=1.0)


@pytest.mark.parametrize("amps,kw,cls", [
    (-7.0, 2.7, 1.0),          # slow AC
    (-25.0, 9.5, 2.0),         # fast AC
    (-130.0, 49.5, 3.0),       # DC fast
])
def test_charger_class_bands(amps, kw, cls):
    defs = ev_charge_channels("P.PackVoltage", "P.PackCurrent")
    out = _evaluate(defs, {"P.PackVoltage": 380.7, "P.PackCurrent": amps})
    assert out["ChargePower_kW"] == pytest.approx(kw, abs=0.1)
    assert out["ChargerClass"] == cls


def test_discharging_is_not_charging():
    defs = ev_charge_channels("P.PackVoltage", "P.PackCurrent", "B.StateOfCharge", 38.0)
    out = _evaluate(defs, {"P.PackVoltage": 377.8, "P.PackCurrent": 67.1,
                           "B.StateOfCharge": 83.0})
    assert out["ChargePower_kW"] < 0                        # drawing, not charging
    assert out["IsCharging"] == 0.0
    assert out["ChargerClass"] == 0.0
    assert out["TimeToFull_min"] == 0.0                     # guarded, no divide blow-up


def test_time_to_full_omitted_without_capacity():
    """Capacity is not on the bus; a countdown from a guess is worse than none."""
    names = {d["name"] for d in ev_charge_channels("P.V", "P.I", "B.Soc")}
    assert "TimeToFull_min" not in names
    assert {"ChargePower_kW", "IsCharging", "ChargerClass"} <= names


def test_positive_charge_convention_supported():
    defs = ev_charge_channels("P.V", "P.I", charge_is_negative=False)
    out = _evaluate(defs, {"P.V": 380.0, "P.I": 7.0})
    assert out["ChargePower_kW"] == pytest.approx(2.66, abs=0.01)
    assert out["IsCharging"] == 1.0
