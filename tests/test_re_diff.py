"""State-change sniffer and capture diff."""

import can

from canforge.re_engines.diff import StateSniffer, diff_frames, _group_bits


def _frames(payloads):
    return {"payloads": [bytes(p) for p in payloads], "timestamps": list(range(len(payloads)))}


def test_group_bits_contiguous():
    assert _group_bits([3, 4, 5, 10]) == [(3, 3), (10, 1)]


def test_diff_detects_newly_active_bit():
    key = (0x300, False)
    # Baseline: byte0 constant 0x00. After: byte0 bit toggles to 0x01 sometimes.
    base = {key: _frames([[0x00, 0xAA]] * 10)}
    after = {key: _frames([[0x00, 0xAA], [0x01, 0xAA], [0x00, 0xAA], [0x01, 0xAA]])}
    d = diff_frames(base, after)
    assert d["changed_id_count"] == 1
    ch = d["changed"][0]
    # byte0 bit7 (sequential index 7) is the changed LSB.
    assert 7 in ch["changed_bits"]
    assert ch["candidates"][0]["kind"] == "event"


def test_diff_reports_new_and_removed_ids():
    base = {(0x10, False): _frames([[0]] * 3)}
    after = {(0x20, False): _frames([[0]] * 3)}
    d = diff_frames(base, after)
    assert d["new_ids"] == ["020"]
    assert d["removed_ids"] == ["010"]


def test_state_sniffer_lifecycle():
    s = StateSniffer()
    assert s.status()["phase"] == "idle"
    s.arm()
    assert s.status()["phase"] == "baseline"
    for _ in range(5):
        s.consume(can.Message(arbitration_id=0x301, data=b"\x00\xAA", is_extended_id=False))
    s.mark()
    assert s.status()["phase"] == "after"
    for v in (0x00, 0x01, 0x00, 0x01):
        s.consume(can.Message(arbitration_id=0x301, data=bytes([v, 0xAA]), is_extended_id=False))
    res = s.result()
    assert res["changed_id_count"] == 1
    assert res["changed"][0]["id_hex"] == "301"
    s.stop()
    assert s.status()["phase"] == "idle"
