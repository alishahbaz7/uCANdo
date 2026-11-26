"""TX signal patching — live overrides and loop-seam continuity.

The bit math is checked against **cantools as the oracle**: a patch must put the
value where cantools reads it, and must leave every other bit of the captured
payload byte-exact (which is precisely what a decode→edit→encode round-trip
would *not* do).
"""

import cantools
import pytest

from ucando import txpatch
from ucando.replay import TxEngine
from ucando.txpatch import FramePatcher

# Motorola (big_endian) and Intel (little_endian) signals, signed and unsigned,
# byte-aligned and straddling a byte boundary, plus a checksum byte.
DBC = """VERSION ""

BO_ 512 Batt: 8 Vector__XXX
 SG_ Soc : 7|8@0+ (0.5,0) [0|100] "%" Vector__XXX
 SG_ Volt : 15|16@0+ (0.1,0) [0|800] "V" Vector__XXX
 SG_ Temp : 31|8@0- (1,-40) [-168|87] "degC" Vector__XXX
 SG_ Counter : 35|4@0+ (1,0) [0|15] "" Vector__XXX
 SG_ Csum : 63|8@0+ (1,0) [0|255] "" Vector__XXX

BO_ 513 Dash: 8 Vector__XXX
 SG_ Odo : 0|24@1+ (0.1,0) [0|1000000] "km" Vector__XXX
 SG_ Dte : 24|12@1+ (1,0) [0|999] "km" Vector__XXX
 SG_ Bias : 40|10@1- (0.25,0) [-128|127] "" Vector__XXX
"""


@pytest.fixture
def db():
    return cantools.database.load_string(DBC, database_format="dbc")


@pytest.fixture
def patcher(db):
    return FramePatcher(db, "test.dbc")


def _field(db, message, signal):
    msg = db.get_message_by_name(message)
    sig = next(s for s in msg.signals if s.name == signal)
    return txpatch.Field(msg, sig)


# ----- bit packing, verified against cantools ------------------------------
@pytest.mark.parametrize("message,signal,value", [
    ("Batt", "Soc", 8.0),            # Motorola, byte-aligned, scaled
    ("Batt", "Soc", 100.0),
    ("Batt", "Volt", 396.5),         # Motorola, 16-bit across two bytes
    ("Batt", "Temp", -12.0),         # Motorola, signed, negative
    ("Batt", "Temp", 87.0),          # its true ceiling: raw 127 with offset -40
    ("Batt", "Counter", 13),         # Motorola, 4-bit nibble
    ("Dash", "Odo", 3075.4),         # Intel, 24-bit
    ("Dash", "Dte", 263),            # Intel, 12-bit straddling bytes
    ("Dash", "Bias", -31.5),         # Intel, signed, sub-byte scale
    ("Dash", "Bias", 31.25),
])
def test_pack_matches_cantools(db, message, signal, value):
    field = _field(db, message, signal)
    buf = bytearray(b"\x5A" * 8)                  # non-zero, so leftovers show
    field.write(buf, value)
    decoded = db.decode_message(db.get_message_by_name(message).frame_id, bytes(buf))
    assert float(decoded[signal]) == pytest.approx(value, abs=field.scale / 2 + 1e-9)
    # And our own reader agrees with cantools.
    assert field.read(bytes(buf)) == pytest.approx(float(decoded[signal]), abs=1e-9)


def test_patch_leaves_every_other_bit_untouched(db):
    """The reason we don't decode→encode: unmapped bits must survive."""
    msg = db.get_message_by_name("Batt")
    original = bytes.fromhex("00" * 8)
    buf = bytearray(bytes.fromhex("A5C3F0690F1234FF"))
    before = db.decode_message(msg.frame_id, bytes(buf))

    field = _field(db, "Batt", "Soc")
    field.write(buf, 12.0)

    after = db.decode_message(msg.frame_id, bytes(buf))
    assert float(after["Soc"]) == 12.0
    for name in ("Volt", "Temp", "Counter", "Csum"):
        assert after[name] == before[name], f"{name} was collateral damage"
    assert len(buf) == 8 and original != bytes(buf)


def test_pack_round_trips_every_representable_value(db):
    field = _field(db, "Batt", "Temp")            # signed 8-bit, scale 1, offset -40
    for raw in range(-128, 128):
        physical = raw - 40                       # the span the field can actually hold
        buf = bytearray(8)
        field.write(buf, physical)
        assert field.read(bytes(buf)) == physical


def test_value_the_field_cannot_hold_saturates_rather_than_wraps(db):
    """A signed 8-bit at offset -40 tops out at 87 even though the DBC may claim more.

    Wrapping would turn "battery at 119 °C" into a plausible-looking cold
    reading; saturating is at least visibly pinned at the limit.
    """
    field = _field(db, "Batt", "Temp")
    buf = bytearray(8)
    field.write(buf, 119.0)
    assert field.read(bytes(buf)) == 87.0
    field.write(buf, -500.0)
    assert field.read(bytes(buf)) == -168.0


def test_signal_past_the_end_of_a_short_payload_is_refused(db):
    field = _field(db, "Batt", "Csum")            # lives in byte 7
    with pytest.raises(ValueError):
        field.write(bytearray(4), 1)              # DLC-4 frame has no byte 7


def test_msb_seq_conversion_is_self_inverse():
    for start in range(64):
        assert txpatch.cantools_start_to_msb_seq(
            txpatch.cantools_start_to_msb_seq(start)) == start


# ----- overrides ----------------------------------------------------------
def test_override_rewrites_only_the_target_message(patcher, db):
    patcher.set_override("Batt", "Soc", 8.0)
    out = patcher.patch(512, False, bytes.fromhex("FF" * 8))
    assert out is not None
    assert float(db.decode_message(512, out)["Soc"]) == 8.0
    # A message with no rule is returned untouched (None == "send as captured").
    assert patcher.patch(513, False, bytes.fromhex("FF" * 8)) is None


def test_override_is_clamped_to_the_field_width(patcher, db):
    patcher.set_override("Batt", "Soc", 9999.0)          # 8-bit, scale 0.5
    out = patcher.patch(512, False, bytes(8))
    assert float(db.decode_message(512, out)["Soc"]) == 127.5   # saturated, not wrapped


def test_override_can_be_cleared(patcher):
    patcher.set_override("Batt", "Soc", 8.0)
    assert patcher.config()["active"] is True
    patcher.clear("Batt", "Soc")
    assert patcher.config()["active"] is False
    assert patcher.patch(512, False, bytes(8)) is None


def test_second_override_of_one_signal_replaces_the_first(patcher, db):
    patcher.set_override("Batt", "Soc", 8.0)
    patcher.set_override("Batt", "Soc", 42.0)
    out = patcher.patch(512, False, bytes(8))
    assert float(db.decode_message(512, out)["Soc"]) == 42.0
    assert len(patcher.config()["rules"]) == 1


def test_unknown_signal_is_rejected(patcher):
    with pytest.raises(KeyError):
        patcher.set_override("Batt", "NoSuchSignal", 1.0)


# ----- loop-seam continuity ----------------------------------------------
def _odo_frame(db, km):
    buf = bytearray(8)
    _field(db, "Dash", "Odo").write(buf, km)
    return bytes(buf)


def test_monotonic_signal_never_steps_backwards_across_a_seam(patcher, db):
    """The MG Windsor case: the log ends at 3075 km and restarts at 3066."""
    patcher.set_monotonic([("Dash", "Odo")])
    read = lambda payload: float(db.decode_message(513, payload)["Odo"])

    # First pass plays as captured.
    assert read(patcher.patch(513, False, _odo_frame(db, 3066.0))) == pytest.approx(3066.0)
    assert read(patcher.patch(513, False, _odo_frame(db, 3075.0))) == pytest.approx(3075.0)

    patcher.on_rewind()                                  # loop back to the top

    # Second pass continues from 3075 instead of snapping to 3066.
    assert read(patcher.patch(513, False, _odo_frame(db, 3066.0))) == pytest.approx(3075.0)
    assert read(patcher.patch(513, False, _odo_frame(db, 3070.0))) == pytest.approx(3079.0)
    assert read(patcher.patch(513, False, _odo_frame(db, 3075.0))) == pytest.approx(3084.0)

    patcher.on_rewind()
    assert read(patcher.patch(513, False, _odo_frame(db, 3066.0))) == pytest.approx(3084.0)


def test_monotonic_preserves_a_genuine_forward_jump(patcher, db):
    """Only backward steps are corrected.

    A playlist of non-consecutive capture chunks skips real kilometres between
    them. Pinning the odometer to "no step at all" would erase distance the
    vehicle actually covered, so a forward jump is left alone.
    """
    patcher.set_monotonic([("Dash", "Odo")])
    read = lambda payload: float(db.decode_message(513, payload)["Odo"])

    assert read(patcher.patch(513, False, _odo_frame(db, 3071.7))) == pytest.approx(3071.7)
    patcher.on_rewind()                                  # next item: a later chunk
    assert read(patcher.patch(513, False, _odo_frame(db, 3075.1))) == pytest.approx(3075.1)
    patcher.on_rewind()                                  # loop: back to the earlier chunk
    assert read(patcher.patch(513, False, _odo_frame(db, 3071.7))) == pytest.approx(3075.1)


def test_monotonic_keeps_climbing_over_many_loops(patcher, db):
    patcher.set_monotonic([("Dash", "Odo")])
    read = lambda payload: float(db.decode_message(513, payload)["Odo"])
    last = 0.0
    for _ in range(20):
        for km in (3066.0, 3070.0, 3075.0):
            value = read(patcher.patch(513, False, _odo_frame(db, km)))
            assert value >= last - 1e-6, "odometer went backwards"
            last = value
        patcher.on_rewind()
    # Pass 1 ends at 3075; each later pass adds the file's own 9 km rise. The
    # seam repeats the boundary value rather than stepping, by design.
    assert last == pytest.approx(3075.0 + 19 * 9.0, abs=0.2)


def test_counter_is_regenerated_and_wraps(patcher, db):
    patcher.set_counters([("Batt", "Counter")])
    seen = [int(db.decode_message(512, patcher.patch(512, False, bytes(8)))["Counter"])
            for _ in range(18)]
    assert seen[:5] == [0, 1, 2, 3, 4]
    assert seen[16] == 0 and seen[17] == 1            # 4-bit field wraps at 16


def test_counter_does_not_reset_at_a_seam(patcher, db):
    patcher.set_counters([("Batt", "Counter")])
    for _ in range(5):
        patcher.patch(512, False, bytes(8))
    patcher.on_rewind()
    nxt = int(db.decode_message(512, patcher.patch(512, False, bytes(8)))["Counter"])
    assert nxt == 5, "a regenerated counter must be seamless by construction"


def test_checksum_is_recomputed_after_patching(patcher, db):
    patcher.set_override("Batt", "Soc", 8.0)
    patcher.set_checksum("Batt", "Csum", "sum8")
    out = patcher.patch(512, False, bytes.fromhex("FF" * 8))
    assert out[7] == (sum(out[:7]) & 0xFF)


def test_checksum_xor8(patcher):
    patcher.set_checksum("Batt", "Csum", "xor8")
    out = patcher.patch(512, False, bytes.fromhex("0102030405060700"))
    expected = 0
    for b in out[:7]:
        expected ^= b
    assert out[7] == expected


def test_checksum_none_is_the_default_and_removes_the_rule(patcher):
    patcher.set_checksum("Batt", "Csum", "sum8")
    assert patcher.config()["checksums"]
    patcher.set_checksum("Batt", "Csum", "none")
    assert not patcher.config()["checksums"]


def test_non_byte_aligned_checksum_is_refused(patcher):
    with pytest.raises(ValueError):
        patcher.set_checksum("Batt", "Counter", "sum8")     # 4-bit nibble
    with pytest.raises(ValueError):
        patcher.set_checksum("Batt", "Volt", "sum8")        # 16-bit


def test_unknown_checksum_algorithm_is_refused(patcher):
    with pytest.raises(ValueError):
        patcher.set_checksum("Batt", "Csum", "crc8-magic")


# ----- candidate detection ------------------------------------------------
def test_analyze_finds_the_odometer_and_the_counter(db, tmp_path):
    from tests.test_replay import _row, _write_vspy
    from ucando import logstore

    rows = []
    for i in range(60):
        odo = bytearray(8)
        _field(db, "Dash", "Odo").write(odo, 3066.0 + i * 0.1)     # rises
        rows.append(_row(len(rows) + 1, 1.0 + i * 0.05, "HS CAN", "201", odo.hex().upper()))
        cnt = bytearray(8)
        _field(db, "Batt", "Counter").write(cnt, i % 16)           # rolls
        _field(db, "Batt", "Soc").write(cnt, 83.0)                # constant
        rows.append(_row(len(rows) + 1, 1.0 + i * 0.05, "HS CAN", "200", cnt.hex().upper()))
    path = _write_vspy(tmp_path / "analyze.csv", rows)

    store = logstore.load(path, use_cache=False)
    found = txpatch.analyze(store, store.indices("HS CAN"), db)
    assert ("Dash", "Odo") in [(e["message"], e["signal"]) for e in found["monotonic"]]
    assert ("Batt", "Counter") in [(e["message"], e["signal"]) for e in found["counters"]]
    # A name that reads like an accumulator ranks first, but is only a hint.
    assert found["monotonic"][0]["signal"] == "Odo"
    assert found["monotonic"][0]["accumulator_hint"] is True
    # A constant signal is neither — there is nothing to continue.
    names = [(e["message"], e["signal"]) for e in found["monotonic"] + found["counters"]]
    assert ("Batt", "Soc") not in names


def test_analyze_spans_several_files(db, tmp_path):
    """A signal flat in one chunk and rising in the next is still an accumulator.

    This is the real MG Windsor shape: the odometer does not move at all during
    the opening 41 s file (the car had not pulled away), so judging each chunk
    alone finds nothing.
    """
    from tests.test_replay import _row, _write_vspy
    from ucando import logstore

    def chunk(name, values, t0):
        rows = []
        for i, km in enumerate(values):
            buf = bytearray(8)
            _field(db, "Dash", "Odo").write(buf, km)
            rows.append(_row(i + 1, t0 + i * 0.05, "HS CAN", "201", buf.hex().upper()))
        return _write_vspy(tmp_path / name, rows)

    flat = chunk("flat.csv", [3066.0] * 10, 1.0)          # stationary
    moving = chunk("moving.csv", [3066.0 + i * 0.1 for i in range(10)], 2.0)

    stores = [logstore.load(p, use_cache=False) for p in (flat, moving)]
    per_file = [txpatch.analyze(s, s.indices("HS CAN"), db) for s in stores]
    assert per_file[0]["monotonic"] == []                  # nothing to see in chunk 1

    both = txpatch.analyze_many([(s, s.indices("HS CAN")) for s in stores], db)
    assert [(e["message"], e["signal"]) for e in both["monotonic"]] == [("Dash", "Odo")]
    assert both["monotonic"][0]["rise"] == pytest.approx(0.9, abs=0.05)


# ----- engine integration -------------------------------------------------
def test_engine_applies_the_patcher_while_transmitting(db, tmp_path):
    from tests.test_replay import _row, _write_vspy
    import time

    rows = []
    for i in range(6):
        buf = bytearray(8)
        _field(db, "Batt", "Soc").write(buf, 83.0)
        rows.append(_row(i + 1, 1.0 + i * 0.002, "HS CAN", "200", buf.hex().upper()))
    path = _write_vspy(tmp_path / "soc.csv", rows)

    eng = TxEngine()
    eng.load(path)
    patcher = FramePatcher(db, "t.dbc")
    patcher.set_override("Batt", "Soc", 8.0)
    eng.set_patcher(patcher)

    out = []
    eng.play(out.append, speed=20.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)
    assert len(out) == 6
    assert all(float(db.decode_message(512, bytes(m.data))["Soc"]) == 8.0 for m in out)


def test_engine_holds_the_seam_across_an_item_repeat(db, tmp_path):
    """Two passes of one file must not replay the odometer twice."""
    from tests.test_replay import _row, _write_vspy
    import time

    rows = [_row(i + 1, 1.0 + i * 0.002, "HS CAN", "201",
                 _odo_frame(db, 3066.0 + i).hex().upper()) for i in range(5)]
    path = _write_vspy(tmp_path / "odo.csv", rows)

    eng = TxEngine()
    eng.set_plan([{"path": path, "repeat": 3}])
    patcher = FramePatcher(db, "t.dbc")
    patcher.set_monotonic([("Dash", "Odo")])
    eng.set_patcher(patcher)

    out = []
    eng.play(out.append, speed=20.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)

    values = [float(db.decode_message(513, bytes(m.data))["Odo"]) for m in out]
    assert len(values) == 15
    assert values == sorted(values), f"odometer stepped backwards: {values}"
    assert values[-1] == pytest.approx(3066.0 + 12.0)   # 4 km gained per pass, 3 passes


def test_unpatched_replay_is_byte_identical(db, tmp_path):
    """With no rules configured, payloads must go out exactly as captured."""
    from tests.test_replay import _row, _write_vspy
    import time

    payloads = ["A5C3F0690F1234FF", "0011223344556677", "FFFFFFFFFFFFFFFF"]
    rows = [_row(i + 1, 1.0 + i * 0.002, "HS CAN", "200", p) for i, p in enumerate(payloads)]
    path = _write_vspy(tmp_path / "raw.csv", rows)

    eng = TxEngine()
    eng.load(path)
    eng.set_patcher(FramePatcher(db, "t.dbc"))          # loaded but no rules
    out = []
    eng.play(out.append, speed=20.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)
    assert [bytes(m.data).hex().upper() for m in out] == payloads


# ----- REST surface -------------------------------------------------------
def test_api_patch_flow(tmp_path):
    from fastapi.testclient import TestClient
    from ucando.server import app
    from tests.test_replay import _row, _write_vspy
    client = TestClient(app)

    dbc = tmp_path / "t.dbc"
    dbc.write_text(DBC, encoding="utf-8")
    log = _write_vspy(tmp_path / "p.csv", [
        _row(1, 1.0, "HS CAN", "200", "FF" * 8),
        _row(2, 1.01, "HS CAN", "201", "00" * 8)])

    # Overrides need a DBC first.
    assert not client.post("/api/tx/patch/override",
                           json={"message": "Batt", "signal": "Soc", "value": 8}).json().get("ok")

    r = client.post("/api/tx/patch/dbc", json={"path": str(dbc)}).json()
    assert r["ok"] and r["loaded"]
    assert {m["message"] for m in r["messages"]} == {"Batt", "Dash"}

    r = client.post("/api/tx/patch/override",
                    json={"message": "Batt", "signal": "Soc", "value": 8}).json()
    assert r["ok"] and r["active"]
    assert [(x["message"], x["signal"], x["value"]) for x in r["rules"]] == [("Batt", "Soc", 8.0)]

    client.post("/api/replay/load", json={"path": log})
    r = client.post("/api/tx/patch/analyze").json()
    assert r["ok"] and "monotonic" in r and "counters" in r

    r = client.post("/api/tx/patch/seam",
                    json={"monotonic": [["Dash", "Odo"]],
                          "counters": [["Batt", "Counter"]],
                          "checksums": [{"message": "Batt", "signal": "Csum",
                                         "algorithm": "sum8"}]}).json()
    assert r["ok"]
    kinds = {(x["signal"], x["kind"]) for x in r["rules"]}
    assert ("Odo", "monotonic") in kinds and ("Counter", "counter") in kinds
    assert ("Soc", "set") in kinds                     # the override survived
    assert r["checksums"] == [{"message": "Batt", "signal": "Csum", "algorithm": "sum8"}]

    assert client.post("/api/tx/patch/clear").json()["active"] is False
