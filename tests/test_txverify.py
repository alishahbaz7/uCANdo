"""TX verification — what we transmitted vs what the cloud reported.

The load-bearing test in this file is
:func:`test_transmitted_bytes_are_identical_to_the_log`: it is the machine-checked
form of "no manipulation in TX". Everything else supports reading the result.
"""

import json
import time

import pytest

from ucando import logstore, txverify
from ucando.replay import TxEngine
from ucando.txpatch import FramePatcher
from ucando.txverify import TxRecorder

from tests.test_replay import _row, _write_vspy


def _run(eng, recorder=None, **kw):
    out = []
    if recorder is not None:
        eng.set_tx_tap(recorder.consume)
    eng.play(out.append, **kw)
    deadline = time.time() + 10
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)
    return out


@pytest.fixture
def mixed_dlc_log(tmp_path):
    """Every DLC the real MG Windsor capture contains: 5, 6 and 8 bytes."""
    payloads = ["0011223344", "AABBCCDDEEFF", "0102030405060708",
                "FF", "C1C1000000000000", "3B1140F71400"]
    rows = [_row(i + 1, 1.0 + i * 0.002, "HS CAN", f"{0x300 + i:03X}", p)
            for i, p in enumerate(payloads)]
    return _write_vspy(tmp_path / "dlc.csv", rows), payloads


# ----- the requirement: no manipulation in TX -----------------------------
def test_transmitted_bytes_are_identical_to_the_log(mixed_dlc_log):
    """Short-DLC frames must go out at their own length, never padded.

    This is the regression guard for the MG Commute `0x120` class of bug: a
    DLC-5 frame silently padded to 8 shifts every byte a receiver reads, and the
    odometer decodes to nonsense. A byte-fidelity claim to the cloud team is only
    as good as this test.
    """
    path, payloads = mixed_dlc_log
    eng = TxEngine()
    eng.load(path)
    rec = TxRecorder()
    rec.start_recording()
    sent = _run(eng, rec, speed=20.0)

    assert [bytes(m.data).hex().upper() for m in sent] == payloads
    assert [m.dlc for m in sent] == [len(p) // 2 for p in payloads]
    # And the recording agrees with the wire, byte for byte and length for length.
    store = rec.store()
    assert [store.payload(i).hex().upper() for i in range(len(store))] == payloads


def test_recorder_captures_post_patch_bytes(mixed_dlc_log):
    """The record must be what LEFT the machine, not what the file held.

    Comparing the cloud against the *file* while patching is active would report
    a mismatch that is entirely our own doing.
    """
    path, _ = mixed_dlc_log
    import cantools
    db = cantools.database.load_string(
        'VERSION ""\n\nBO_ 768 M: 5 Vector__XXX\n'
        ' SG_ S : 7|8@0+ (1,0) [0|255] "" Vector__XXX\n', database_format="dbc")

    eng = TxEngine()
    eng.load(path)
    patcher = FramePatcher(db, "t.dbc")
    patcher.set_override("M", "S", 0x99)
    eng.set_patcher(patcher)
    rec = TxRecorder()
    rec.start_recording()
    _run(eng, rec, speed=20.0)

    store = rec.store()
    first = next(store.payload(i) for i in range(len(store)) if store.ids[i] == 0x300)
    assert first[0] == 0x99                      # patched value, as transmitted
    assert logstore.load(path, use_cache=False).payload(0)[0] == 0x00   # file untouched


def test_recorder_tracks_ids_and_a_recent_window(mixed_dlc_log):
    path, payloads = mixed_dlc_log
    eng = TxEngine()
    eng.load(path)
    rec = TxRecorder()
    _run(eng, rec, speed=20.0, repeat=2)

    assert rec.status()["frames"] == 12
    rows = rec.ids()
    assert len(rows) == 6 and all(r["count"] == 2 for r in rows)
    assert rows[0]["id_hex"] == "300" and rows[0]["dlc"] == 5
    assert len(rec.recent(limit=4)) == 4
    assert len(rec.recent(frame_id=0x300)) == 2


def test_tap_failure_never_breaks_a_transmit(mixed_dlc_log):
    path, payloads = mixed_dlc_log
    eng = TxEngine()
    eng.load(path)
    eng.set_tx_tap(lambda *a: 1 / 0)             # a broken recorder
    out = []
    eng.play(out.append, speed=20.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)
    assert len(out) == 6                          # every frame still went out


# ----- cloud log parsing --------------------------------------------------
def test_parse_cloud_log_csv():
    text = ("timestamp,canId,payload\n"
            "1.000,0x300,00 11 22 33 44\n"
            "1.002,0x301,AABBCCDDEEFF\n")
    got = txverify.parse_cloud_log(text)
    assert got["dialect"] == "csv"
    assert [f["id"] for f in got["frames"]] == [0x300, 0x301]
    assert got["frames"][0]["data"] == bytes.fromhex("0011223344")


def test_parse_cloud_log_decimal_ids_and_byte_arrays():
    text = json.dumps([{"ts": 1.0, "can_id": 768, "bytes": [0, 17, 34, 51, 68]}])
    got = txverify.parse_cloud_log(text)
    assert got["frames"][0]["id"] == 768
    assert got["frames"][0]["data"] == bytes.fromhex("0011223344")


def test_parse_cloud_log_json_lines_and_nesting():
    lines = "\n".join(json.dumps({"id": "300", "data": "0011223344"}) for _ in range(3))
    assert txverify.parse_cloud_log(lines)["dialect"] == "json-lines"
    nested = json.dumps({"device": "tcu-1", "records": {"can": [
        {"id": "0x301", "hex": "AABBCCDDEEFF"}]}})
    got = txverify.parse_cloud_log(nested)
    assert got["frames"][0]["id"] == 0x301


def test_parse_cloud_log_plain_text():
    got = txverify.parse_cloud_log("1.000 300 00 11 22 33 44\n1.002 301 AA BB CC DD EE FF\n")
    assert got["dialect"] == "text"
    assert [f["id"] for f in got["frames"]] == [0x300, 0x301]


def test_parse_cloud_log_reports_what_it_tried():
    """A wrong guess must be visible, not a silently empty diff."""
    with pytest.raises(ValueError) as exc:
        txverify.parse_cloud_log("some prose with no frames in it at all\n")
    assert "JSON" in str(exc.value) and "payload" in str(exc.value)
    with pytest.raises(ValueError):
        txverify.parse_cloud_log("")


# ----- the comparison -----------------------------------------------------
def _store(pairs):
    st = logstore.FrameStore("<tx>", "tx")
    for i, (fid, hexs) in enumerate(pairs):
        st.append(i * 0.01, fid, bytes.fromhex(hexs), network="tx")
    return st


def test_identical_streams_are_byte_identical():
    pairs = [(0x300, "0011223344"), (0x301, "AABBCCDDEEFF"), (0x300, "0011223345")]
    rep = txverify.compare(_store(pairs), [{"id": f, "data": bytes.fromhex(h)} for f, h in pairs])
    assert rep["ok"] and rep["verdict"] == "byte-identical"
    assert rep["unknown_payloads"] == 0 and rep["matched_frames"] == 3
    assert {r["verdict"] for r in rep["per_id"]} == {"complete"}


def test_a_payload_the_cloud_invented_is_flagged_corrupt():
    """The one outcome that means something is really wrong."""
    tx = _store([(0x300, "0011223344")])
    rep = txverify.compare(tx, [{"id": 0x300, "data": bytes.fromhex("00FF223344")}])
    assert not rep["ok"] and rep["unknown_payloads"] == 1
    row = rep["per_id"][0]
    assert row["verdict"] == "corrupt"
    assert row["unknown_samples"] == ["00FF223344"]          # evidence for the bug report
    assert row["first_divergence"]["cloud_data"] == "00FF223344"
    assert row["first_divergence"]["expected_near"] == ["0011223344"]


def test_a_downsampling_tcu_is_not_a_failure():
    """A TCU forwards a subset of the bus — that is 'sampled', not corruption."""
    pairs = [(0x300, f"00112233{i:02X}") for i in range(10)]
    tx = _store(pairs)
    cloud = [{"id": 0x300, "data": bytes.fromhex(h)} for _, h in pairs[::3]]
    rep = txverify.compare(tx, cloud)
    assert rep["ok"] and rep["unknown_payloads"] == 0
    row = rep["per_id"][0]
    assert row["verdict"] == "sampled" and row["matched"] == 4
    assert row["delivery_pct"] == 40.0


def test_ids_that_never_arrived_and_ids_we_never_sent():
    tx = _store([(0x300, "00"), (0x301, "11")])
    rep = txverify.compare(tx, [{"id": 0x300, "data": b"\x00"},
                                {"id": 0x555, "data": b"\x22"}])
    assert rep["ids_never_arrived"] == [0x301]
    assert rep["ids_only_at_cloud"] == [0x555]
    by_id = {r["id"]: r for r in rep["per_id"]}
    assert by_id[0x301]["verdict"] == "not forwarded"
    assert by_id[0x555]["verdict"] == "unexpected id"


def test_out_of_order_beyond_the_window_is_a_divergence():
    """Reordering inside the window is tolerated; a payload nowhere ahead is not."""
    tx = _store([(0x300, "AA"), (0x300, "BB")])
    ok = txverify.compare(tx, [{"id": 0x300, "data": b"\xbb"}])
    assert ok["ok"] and ok["per_id"][0]["matched"] == 1      # skipping ahead is fine
    bad = txverify.compare(tx, [{"id": 0x300, "data": b"\xbb"}, {"id": 0x300, "data": b"\xaa"}])
    assert bad["per_id"][0]["first_divergence"]["cloud_index"] == 1


def test_report_states_patching_and_filters_explicitly():
    """A byte-fidelity claim is void if we rewrote signals on the way out."""
    tx = _store([(0x300, "00")])
    rep = txverify.compare(tx, [{"id": 0x300, "data": b"\x00"}],
                           patched=["HSC_BatterySoh.SocPercent"],
                           filtered={"network": "HS CAN",
                                     "networks_not_sent": [{"name": "MS CAN", "frames": 23304}]})
    assert rep["patching_active"] is True
    assert rep["patched_signals"] == ["HSC_BatterySoh.SocPercent"]
    assert rep["tx_filters"]["networks_not_sent"][0]["frames"] == 23304


def test_compare_without_a_recording_says_what_to_do():
    with pytest.raises(ValueError) as exc:
        txverify.compare(None, [])
    assert "start TX recording" in str(exc.value)


def test_api_decode_explains_an_id_the_definition_does_not_cover(tmp_path):
    """A DBC covering part of a bus is normal, not an error.

    The real MG pack describes 54 of the 116 IDs its own capture transmits, and
    cantools raises a bare ``KeyError(296)`` for the rest — which reads as
    nonsense in a UI and looks like "the DBC didn't load".
    """
    from fastapi.testclient import TestClient
    from ucando import server
    client = TestClient(server.app)

    dbc = tmp_path / "partial.dbc"
    dbc.write_text('VERSION ""\n\nBO_ 291 Known: 8 Vector__XXX\n'
                   ' SG_ S : 7|8@0+ (1,0) [0|255] "" Vector__XXX\n', encoding="utf-8")
    log = _write_vspy(tmp_path / "two.csv", [
        _row(1, 1.0, "HS CAN", "123", "1122334455667788"),      # 291, in the DBC
        _row(2, 1.002, "HS CAN", "456", "9988776655443322")])   # 1110, not in it

    server.tx_recorder.reset()
    client.post("/api/replay/load", json={"path": log})
    eng = server.replayer
    eng.play([].append, speed=20.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)

    with open(dbc, "rb") as fh:
        client.post("/api/tx/live/definition", files={"file": ("partial.dbc", fh, "text/plain")})

    live = client.get("/api/tx/live").json()
    assert live["def_ids"] == [291]                  # lets the UI mark decodable rows
    assert {r["id"] for r in live["ids"]} == {291, 1110}

    ok = client.get("/api/tx/live/decode", params={"frame_id": 291}).json()
    assert ok["ok"] and ok["signals"][0]["name"] == "S"

    miss = client.get("/api/tx/live/decode", params={"frame_id": 1110}).json()
    assert miss["ok"] is False
    assert "0x456" in miss["error"] and "1 messages" in miss["error"]
    assert "raw bytes are still shown" in miss["error"]


def test_signature_json_id_base_is_a_real_footgun():
    """A bare "244" key is decimal, so it decodes frame 0xF4 — not 0x244.

    This bites precisely this workflow: you point the verifier at the cloud's own
    Signature JSON, every ID silently fails to match, and it looks like the TCU
    is dropping everything. `jsondecode.detect_id_base` decides per *file* (a 0x
    prefix, a hex letter, or zero-padding anywhere ⇒ hex), so the fix is to feed
    it the padded export, not to patch the reader.
    """
    from ucando import jsondecode
    sig = [{"fieldName": "X", "startingBit": 0, "size": 8, "reverse": 0,
            "signed": 0, "multiplier": 1, "offset": 0}]

    ambiguous = jsondecode.load_signature(json.dumps({"244": sig}))
    assert 244 in ambiguous and 0x244 not in ambiguous          # read as decimal

    padded = jsondecode.load_signature(json.dumps({"00000244": sig}))
    assert 0x244 in padded

    # Any hex letter anywhere in the file also settles it for the whole file.
    lettered = jsondecode.load_signature(json.dumps({"244": sig, "1AB": sig}))
    assert 0x244 in lettered and 0x1AB in lettered


# ----- REST surface -------------------------------------------------------
def test_api_live_decode_and_verify(tmp_path):
    from fastapi.testclient import TestClient
    from ucando import server
    client = TestClient(server.app)

    log = _write_vspy(tmp_path / "v.csv", [
        _row(1, 1.0, "HS CAN", "120", "5251004780BA"),
        _row(2, 1.002, "HS CAN", "244", "52510047C000BA56")])

    server.tx_recorder.reset()
    client.post("/api/replay/load", json={"path": log})
    assert client.post("/api/tx/record/start").json()["recording"] is True

    eng = server.replayer
    out = []
    eng.play(out.append, speed=20.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)

    live = client.get("/api/tx/live").json()
    assert live["ok"] and live["frames"] == 2
    assert {r["id_hex"] for r in live["ids"]} == {"120", "244"}
    assert live["ids"][0]["dlc"] == 6                    # DLC 6 preserved, not padded

    # Decode what we sent against the cloud's own Signature JSON convention.
    # The key is zero-padded so the file is unambiguously hex — see
    # test_signature_json_id_base_is_a_real_footgun below.
    sig = {"00000244": [{"fieldName": "DTeInfo", "startingBit": 0, "size": 16,
                         "reverse": 0, "signed": 0, "multiplier": 1, "offset": 0}]}
    sig_path = tmp_path / "sig.json"
    sig_path.write_text(json.dumps(sig), encoding="utf-8")
    with open(sig_path, "rb") as fh:
        r = client.post("/api/tx/live/definition",
                        files={"file": ("sig.json", fh, "application/json")}).json()
    assert r["ok"] and "Signature JSON" in r["definition"]

    r = client.get("/api/tx/live/decode", params={"frame_id": 0x244}).json()
    assert r["ok"] and r["source"] == "json"
    assert any(s["name"] == "DTeInfo" for s in r["signals"])

    # Cloud export that matches exactly -> byte-identical.
    cloud = "canId,data\n0x120,5251004780BA\n0x244,52510047C000BA56\n"
    cloud_path = tmp_path / "cloud.csv"
    cloud_path.write_text(cloud, encoding="utf-8")
    with open(cloud_path, "rb") as fh:
        rep = client.post("/api/tx/verify", files={"file": ("cloud.csv", fh, "text/csv")}).json()
    assert rep["ok"] and rep["verdict"] == "byte-identical"
    assert rep["cloud_dialect"] == "csv" and rep["unknown_payloads"] == 0
    assert rep["tx_filters"]["network"] == "HS CAN"

    # And a corrupted one is caught.
    bad_path = tmp_path / "bad.csv"
    bad_path.write_text("canId,data\n0x120,5251004780BB\n", encoding="utf-8")
    with open(bad_path, "rb") as fh:
        rep = client.post("/api/tx/verify", files={"file": ("bad.csv", fh, "text/csv")}).json()
    assert rep["ok"] is False and rep["unknown_payloads"] == 1
    assert client.get("/api/tx/verify/report").json()["report"]["unknown_payloads"] == 1
