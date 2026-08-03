"""Reverse-engineering analysis (pure-stdlib)."""

from ucando.reverse import analyze_id, _classify_byte, _entropy
from collections import Counter


def test_classify_constant():
    assert _classify_byte([7, 7, 7, 7]) == "constant"


def test_classify_counter():
    assert _classify_byte(list(range(0, 50))) == "counter"


def test_classify_continuous():
    vals = [(i * 37 + 11) % 256 for i in range(200)]
    assert _classify_byte(vals) == "continuous"


def test_entropy_zero_for_constant():
    assert _entropy(Counter([5, 5, 5]), 3) == 0.0


def test_analyze_constant_payload_has_no_candidates():
    payloads = [bytes([0xA5, 0x00])] * 20
    info = analyze_id(payloads)
    assert info["frames"] == 20
    assert info["candidates"] == []
    assert all(b["kind"] == "constant" for b in info["bytes"])


def test_analyze_counter_byte_detected_and_candidate_found():
    payloads = [bytes([i & 0xFF, 0x00]) for i in range(60)]
    info = analyze_id(payloads)
    assert info["bytes"][0]["kind"] == "counter"
    # The toggling counter byte must surface at least one candidate signal.
    assert len(info["candidates"]) >= 1
    cand = info["candidates"][0]
    assert cand["byte_order"] == "big_endian"
    assert cand["length"] >= 1
