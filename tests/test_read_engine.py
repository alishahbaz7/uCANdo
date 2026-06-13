"""READ reverse-engineering engine: primitives, classification, dispatch."""

import struct

from canforge.re_engines.read import (
    ReadEngine, analyze_id_read, bit_flip_rates, classify_span,
    detect_multiplexor, extract_spans, value_be, value_le, _counter_step,
)


# ----- primitives ----------------------------------------------------------
def test_value_be_and_le():
    p = bytes([0x12, 0x34])
    assert value_be(p, 0, 16) == 0x1234
    assert value_le(p, 0, 16) == 0x3412


def test_bit_flip_rate_lsb_flips_every_frame():
    payloads = [bytes([i & 0xFF]) for i in range(64)]
    bfr = bit_flip_rates(payloads, 8)
    # bit 7 (sequential index 7) is the byte LSB → flips every frame ~1.0.
    assert bfr[7] > 0.95
    # bit 0 (MSB) flips rarely.
    assert bfr[0] < 0.2


def test_counter_step_detects_increment():
    assert _counter_step([10, 11, 12, 13, 14], 8) == 1
    assert _counter_step([5, 5, 5, 5], 8) is None


def test_extract_spans_splits_on_activity():
    # 8 bits active (~0.5), 8 bits dead.
    bfr = [0.5] * 8 + [0.0] * 8
    spans = extract_spans(bfr)
    assert (0, 8) in spans
    assert (8, 8) in spans


# ----- classification ------------------------------------------------------
def test_counter_byte_classified():
    payloads = [bytes([i & 0xFF, 0xA5]) for i in range(120)]
    r = analyze_id_read(payloads)
    counters = [c for c in r["candidates"] if c["kind"] == "counter"]
    assert counters and counters[0]["step"] == 1
    assert counters[0]["byte_order"] == "big_endian"


def test_constant_payload_no_candidates():
    payloads = [bytes([0xDE, 0xAD])] * 50
    r = analyze_id_read(payloads)
    assert r["candidates"] == []
    assert all(b["kind"] == "constant" for b in r["bytes"])


def test_crc_like_byte_high_bfr():
    # Pseudo-random full byte via an LCG (deterministic, no random module).
    vals, x = [], 0x1234
    for _ in range(200):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        vals.append(bytes([(x >> 16) & 0xFF]))
    span = classify_span(vals, 0, 8, bit_flip_rates(vals, 8))
    assert span["kind"] in ("crc", "physical")
    assert span["bfr"] > 0.35


def test_physical_endianness_by_smoothness():
    # A smooth ramp stored little-endian over 2 bytes should be read as LE
    # (BE interpretation would be jumpy).
    payloads = [struct.pack("<H", (v * 7) & 0xFFFF) for v in range(300)]
    span = classify_span(payloads, 0, 16, bit_flip_rates(payloads, 16))
    assert span["byte_order"] == "little_endian"


def test_detect_multiplexor():
    payloads = []
    for i in range(40):
        sel = i % 2
        if sel == 0:
            payloads.append(bytes([0, i & 0xFF, 0xAA]))   # byte1 varies
        else:
            payloads.append(bytes([1, 0x55, i & 0xFF]))   # byte2 varies
    mux = detect_multiplexor(payloads, 3)
    assert mux is not None
    assert mux["selector_byte"] == 0


# ----- engine + registry dispatch ------------------------------------------
def test_engine_output_shape():
    frames = {(0x100, False): {"timestamps": [0.0, 0.01, 0.02],
                               "payloads": [bytes([0]), bytes([1]), bytes([2])]}}
    out = ReadEngine().analyze(frames)
    assert out["engine"] == "read"
    assert out["ids"][0]["id_hex"] == "100"
    assert "candidates" in out["ids"][0]


def test_analyze_log_dispatches_via_registry(tmp_path):
    import can
    p = str(tmp_path / "cap.asc")
    w = can.ASCWriter(p)
    for i in range(60):
        m = can.Message(arbitration_id=0x200, data=bytes([i & 0xFF, 0xA5]),
                        is_extended_id=False, timestamp=i * 0.01)
        w.on_message_received(m)
    w.stop()

    from canforge.reverse import analyze_log
    res = analyze_log(p, engine="read")
    assert res["engine"] == "read"
    assert res["id_count"] == 1
    # The "basic" engine is also registered and selectable.
    res_basic = analyze_log(p, engine="basic")
    assert res_basic["engine"] == "basic"
