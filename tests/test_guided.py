"""Guided (Mode 2) protocols + runner."""

from canforge.guided import GuidedRunner, list_protocols, load_protocol


def _frames(arb, payloads):
    return {(arb, False): {"payloads": [bytes(p) for p in payloads],
                           "timestamps": list(range(len(payloads)))}}


def test_protocols_load():
    assert {"petrol", "diesel", "ev"} <= set(list_protocols())
    p = load_protocol("petrol")
    assert p["fuel"] == "petrol" and len(p["steps"]) > 5
    kinds = {s["kind"] for s in p["steps"]}
    assert {"baseline", "ramp", "stimulus", "known_value"} <= kinds


def test_apply_stimulus_labels_changed_bit():
    r = GuidedRunner(load_protocol("petrol"))
    base = _frames(0x300, [[0x00, 0xAA]] * 8)              # byte0 steady
    after = _frames(0x300, [[0x00, 0xAA], [0x01, 0xAA]] * 4)  # byte0 bit toggles
    r.apply_stimulus({"label": "AC Status", "kind": "stimulus"}, base, after)
    rep = r.report()
    assert "AC Status" in [s["label"] for s in rep["A"] + rep["B"]]
    # one bit changed -> single_bit -> high confidence
    assert any(s["label"] == "AC Status" for s in rep["A"])


def test_apply_known_value():
    r = GuidedRunner(load_protocol("petrol"))
    raw = 193353
    payload = bytes([raw & 0xFF, (raw >> 8) & 0xFF, (raw >> 16) & 0xFF, 0])
    best = r.apply_known({"label": "Odometer", "kind": "known_value"}, _frames(0x5B0, [payload] * 10), 19335)
    assert best and best["id"] == 0x5B0 and best["scale"] == 0.1
    assert any(s["label"] == "Odometer" for s in r.report()["A"])


def test_unknown_fuel_raises():
    import pytest
    with pytest.raises(ValueError):
        load_protocol("nuclear")
