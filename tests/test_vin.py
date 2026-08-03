"""VIN parsing + VIN-pattern vehicle identification — see ucando/vin.py."""

import json

import pytest

from ucando import vin
from ucando.oem_db import OemDatabase

# The real MG Windsor Pro VIN observed on the 2026-08-01 capture vehicle.
PRO_VIN = "MZ72D5FEF8H030876"

MINI_DBC = """VERSION ""

NS_ :

BS_:

BU_:

BO_ 288 HSC_Odometer: 5 Vector__XXX
 SG_ Odometer : 7|32@0+ (0.015625,0) [0|67108864] "km" Vector__XXX
"""


# ----- parsing --------------------------------------------------------------

def test_format_validation_rejects_iso_excluded_letters():
    assert vin.is_valid_format(PRO_VIN)
    assert not vin.is_valid_format("MZ72D5FEF8H03087")        # 16 chars
    assert not vin.is_valid_format("MZ72D5FEF8H0308761")      # 18 chars
    assert not vin.is_valid_format("IZ72D5FEF8H030876")       # I is not allowed
    assert not vin.is_valid_format("OZ72D5FEF8H030876")       # O is not allowed
    assert not vin.is_valid_format("QZ72D5FEF8H030876")       # Q is not allowed
    assert not vin.is_valid_format("")


def test_normalise_strips_separators_and_case():
    assert vin.normalise(" mz7-2d5 fef8h030876 ") == PRO_VIN
    assert vin.is_valid_format(" mz7-2d5 fef8h030876 ")


def test_split_sections():
    p = vin.split(PRO_VIN)
    assert p["wmi"] == "MZ7"
    assert p["vds"] == "2D5FEF"
    assert p["vis"] == "8H030876"
    assert p["serial"] == "030876"
    assert vin.split("nonsense") == {}


def test_year_code_is_reported_raw_not_interpreted():
    """MG India does not follow ISO 3779 position 10: this confirmed-2026 car
    carries '8', which ISO would read as 2008. We must never infer a year."""
    p = vin.split(PRO_VIN)
    assert p["year_code"] == "8"
    assert "year" not in p


# ----- pattern matching -----------------------------------------------------

@pytest.mark.parametrize("pattern,expected", [
    ("MZ72D5FEF*", True),
    ("MZ7*", True),
    ("MZ72D5FEF8H030876", True),          # fully literal
    ("MZ7?D5FEF*", True),                 # ? matches one char
    ("MZ8*", False),
    ("*030876", True),                    # suffix
    ("MZ7", False),                       # must describe the WHOLE vin
    ("", False),
])
def test_pattern_matching(pattern, expected):
    assert vin.matches(PRO_VIN, pattern) is expected


def test_best_pattern_match_prefers_the_most_specific():
    assert vin.best_pattern_match(PRO_VIN, ["MZ7*", "MZ72D5FEF*"]) == "MZ72D5FEF*"
    assert vin.best_pattern_match(PRO_VIN, ["MZ8*"]) is None
    assert vin.best_pattern_match(PRO_VIN, []) is None


# ----- identification against the pack library ------------------------------

def _pack(root, oem, model, variant, patterns=None):
    d = root / oem / model / variant
    d.mkdir(parents=True)
    (d / f"{oem.lower()}_{model.lower()}_{variant.lower()}.dbc").write_text(
        MINI_DBC, encoding="utf-8")
    if patterns is not None:
        (d / "vehicle.json").write_text(json.dumps({"vin_patterns": patterns}),
                                        encoding="utf-8")
    return d


def test_identify_from_vin_ranks_by_specificity(storage, tmp_path):
    _pack(tmp_path, "MG", "Windsor Pro", "EV_2026", ["MZ72D5FEF*"])
    _pack(tmp_path, "MG", "Generic", "EV_2026", ["MZ7*"])
    db = OemDatabase(storage)
    db.seed_builtins(packs_dir=tmp_path)
    m = db.identify_from_vin(PRO_VIN, tmp_path)
    assert [x["name"] for x in m] == ["Windsor Pro EV 2026", "Generic EV 2026"]
    assert m[0]["matched_pattern"] == "MZ72D5FEF*"
    assert m[0]["id"] is not None and m[0]["decodable"]      # joinable to a profile


def test_identify_from_vin_ignores_packs_without_patterns(storage, tmp_path):
    _pack(tmp_path, "MG", "Comet", "EV_2024")                # no vehicle.json
    db = OemDatabase(storage)
    db.seed_builtins(packs_dir=tmp_path)
    assert db.identify_from_vin(PRO_VIN, tmp_path) == []


def test_identify_from_vin_refuses_a_malformed_vin(storage, tmp_path):
    _pack(tmp_path, "MG", "Windsor Pro", "EV_2026", ["MZ7*"])
    db = OemDatabase(storage)
    db.seed_builtins(packs_dir=tmp_path)
    assert db.identify_from_vin("NOT-A-VIN", tmp_path) == []


def test_endpoint_identifies_the_real_windsor_pro():
    """End-to-end against the shipped oem_packs library."""
    from fastapi.testclient import TestClient
    from ucando.server import app
    c = TestClient(app)
    r = c.post(f"/api/oem/identify-vin?vin={PRO_VIN}").json()
    assert r["ok"] and r["vin"] == PRO_VIN
    assert r["parts"]["wmi"] == "MZ7"
    assert any(m["name"].startswith("Windsor Pro") for m in r["matches"])

    bad = c.post("/api/oem/identify-vin?vin=TOOSHORT").json()
    assert not bad["ok"]
