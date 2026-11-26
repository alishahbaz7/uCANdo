"""TX Replay — log loading, network selection, repeat modes and pacing.

No hardware: playback sends into a plain list (the engine only ever needs a
``send`` callable), so these tests assert exactly what would go on the wire.
"""

import os
import time

import can
import pytest

from ucando import logstore, txproject
from ucando.replay import TxEngine

# --------------------------------------------------------------------------
# A synthetic Vehicle Spy 3 export. Two CAN networks at *different* bitrates
# (the real MG Windsor capture holds HS CAN + MS CAN) plus a LIN network that
# must be ignored, and one Tx=T row — the capture tool's own traffic.
# --------------------------------------------------------------------------
_HEAD = """Vehicle Spy 3 Bus Traffic File
Save Date,8/01/2026
Save Time,3:35:03 pm
Start Date,8/01/2026
Start Time,2:52:41 pm
System Time,197672700
Notes,Buffer Save Count,12

Network Description,Hardware,Network,Protocol,Baud Rate
HS CAN,Default,HS CAN,CAN,500000,
MS CAN,Default,MS CAN,CAN,125000,
LIN,Default,LIN,LIN,10417,

Line,Abs Time(Sec),Rel Time (Sec),Status,Er,Tx,Description,Network,Node,ID,Cycle,Ch,B1-256,Dyn,Symbol Type,Strt-PPI-NULL-Sync-Res,H-CRC,CRC,Tframe,Tss Length,Value,Trigger,Signals
Line,Abs Time(Sec),Rel Time (Sec),Status,Er,Tx,Description,Network,Node,Arb ID,Remote,Xtd,B1,B2,B3,B4,B5,B6,B7,B8,Value,Trigger,Signals
"""


def _row(line, t, net, id_hex, data_hex, tx="F", xtd="F"):
    cols = [data_hex[i:i + 2] for i in range(0, len(data_hex), 2)]
    cols += [""] * (8 - len(cols))
    return (f"{line},{t!r},0,67371008,F,{tx},{net} ${id_hex},{net},,{id_hex},F,{xtd},"
            + ",".join(cols) + ",,,")


def _write_vspy(path, rows):
    path.write_text(_HEAD + "\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def two_network_log(tmp_path):
    """4 HS CAN frames (one of them tool-transmitted) + 2 MS CAN frames."""
    rows = [
        _row(1, 100.000, "HS CAN", "1B2", "0011223344556677"),
        _row(2, 100.001, "MS CAN", "3A0", "AABB"),
        _row(3, 100.002, "HS CAN", "094", "01"),
        _row(4, 100.003, "HS CAN", "7DF", "0201050000000000", tx="T"),   # our own request
        _row(5, 100.004, "MS CAN", "3A1", "CC"),
        _row(6, 100.005, "HS CAN", "1B2", "8899AABBCCDDEEFF"),
        _row(7, 100.006, "LIN", "22", "01"),                             # not CAN — ignored
    ]
    return _write_vspy(tmp_path / "capture.csv", rows)


@pytest.fixture
def fast_log(tmp_path):
    """1000 HS CAN frames at exactly 1 ms — a 1 s log at ~1 kHz."""
    rows = [_row(i + 1, 10.0 + i * 0.001, "HS CAN", f"{0x100 + (i % 8):03X}", "0011223344556677")
            for i in range(1000)]
    return _write_vspy(tmp_path / "fast.csv", rows)


# ----- logstore -----------------------------------------------------------
def test_logstore_reads_vehicle_spy_csv(two_network_log):
    """can.LogReader cannot read this dialect at all — logstore must sniff it."""
    store = logstore.load(two_network_log)
    assert store.source == "vspy"
    assert len(store) == 6                                  # LIN row dropped
    assert set(store.networks) == {"HS CAN", "MS CAN"}
    nets = {n["name"]: n for n in store.network_summary()}
    assert nets["HS CAN"]["frames"] == 4 and nets["HS CAN"]["baud"] == 500_000
    assert nets["MS CAN"]["frames"] == 2 and nets["MS CAN"]["baud"] == 125_000
    assert nets["HS CAN"]["tx_frames"] == 1
    # Short DLCs survive as short payloads, not padded to 8.
    assert store.payload(2) == bytes([0x01])
    assert store.message(0).arbitration_id == 0x1B2
    # Networks disagree on bitrate, so there is no single one to connect at.
    assert store.summary()["baud_hint"] is None


def test_logstore_reads_python_can_log(tmp_path):
    p = tmp_path / "plain.csv"
    with can.CSVWriter(str(p)) as w:
        for i in range(5):
            w.on_message_received(can.Message(timestamp=1.0 + i * 0.01, arbitration_id=0x123,
                                              data=bytes([i]), is_extended_id=False))
    store = logstore.load(str(p))
    assert store.source == "python-can" and len(store) == 5
    assert store.payload(3) == bytes([3])
    assert store.network_summary()[0]["baud"] is None       # no bitrate in the format


def test_logstore_single_baud_hint(tmp_path):
    """One CAN network carrying frames -> that is the bitrate to connect at."""
    rows = [_row(1, 1.0, "HS CAN", "100", "00"), _row(2, 1.001, "HS CAN", "101", "01")]
    store = logstore.load(_write_vspy(tmp_path / "one.csv", rows))
    assert store.summary()["baud_hint"] == 500_000


# ----- selection ----------------------------------------------------------
def test_load_defaults_to_busiest_network(two_network_log):
    meta = TxEngine().load(two_network_log)
    assert meta["network"] == "HS CAN"
    assert meta["frames"] == 3                              # 4 HS CAN minus the Tx=T frame
    assert meta["baud"] == 500_000
    assert meta["tx_frames_skipped"] == 1
    assert meta["ids"] == [0x94, 0x1B2]
    assert [n["name"] for n in meta["networks"]] == ["HS CAN", "MS CAN"]


def test_select_switches_network_without_reparsing(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    meta = eng.select("MS CAN")
    assert meta["network"] == "MS CAN" and meta["frames"] == 2
    assert meta["baud"] == 125_000                          # per-network, not the file's first
    assert meta["ids"] == [0x3A0, 0x3A1]


def test_select_keeps_tool_tx_frames_when_asked(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    assert eng.select(skip_tx=False)["frames"] == 4
    assert 0x7DF in eng.meta()["ids"]


# ----- playback -----------------------------------------------------------
def _play(eng, **kw):
    """Play to completion (or timeout) and return the frames that went out."""
    out = []
    eng.play(out.append, **kw)
    deadline = time.time() + 10
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)
    return out


def test_play_once_sends_selected_frames_in_order(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    sent = _play(eng, speed=50.0)
    assert [m.arbitration_id for m in sent] == [0x1B2, 0x94, 0x1B2]
    assert sent[0].data == bytes.fromhex("0011223344556677")
    st = eng.status()
    assert st["state"] == "done" and st["sent"] == 3 and st["progress"] == 1.0


def test_repeat_count_plays_exactly_n_passes(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    sent = _play(eng, speed=50.0, repeat=3)
    assert len(sent) == 9
    assert eng.status()["pass_no"] == 3


def test_repeat_zero_is_endless_until_stopped(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    out = []
    eng.play(out.append, speed=50.0, repeat=0)
    time.sleep(0.3)
    assert eng.status()["state"] == "playing"
    eng.stop()
    assert len(out) > 3                                     # more than one pass
    assert eng.status()["state"] == "ready"


def test_loop_flag_is_the_legacy_spelling_of_endless(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    eng.play([].append, speed=50.0, loop=True)
    assert eng.status()["loop"] is True and eng.status()["passes"] == 0
    eng.stop()


def test_filter_ids_restricts_what_goes_out(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    sent = _play(eng, speed=50.0, filter_ids=[0x1B2])
    assert {m.arbitration_id for m in sent} == {0x1B2} and len(sent) == 2


def test_step_sends_one_frame_at_a_time(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    out = []
    assert eng.step(out.append)["sent"] is True
    assert eng.step(out.append)["sent"] is True
    assert [m.arbitration_id for m in out] == [0x1B2, 0x94]
    assert eng.status()["cursor"] == 2


def test_pause_resume_does_not_burst_the_backlog(two_network_log):
    """A pause must not become catch-up traffic — the clock re-anchors on resume."""
    eng = TxEngine()
    eng.load(two_network_log)
    out = []
    eng.play(out.append, speed=1.0)                          # 5 ms of log, real time
    eng.pause()
    assert eng.status()["state"] == "paused"
    time.sleep(0.2)                                          # 40× the log's duration
    paused_count = len(out)
    eng.resume()
    time.sleep(0.2)
    assert len(out) == 3 and paused_count <= 3               # never more than the log holds
    eng.stop()


# ----- pacing (the reason this engine exists) -----------------------------
def test_holds_a_1khz_log_in_near_real_time(fast_log):
    """1000 frames spaced 1 ms must take ~1 s, not ~15 s.

    This is the regression test for deadline scheduling: a ``send(); sleep(gap)``
    loop cannot pace sub-millisecond gaps on Windows (the OS wait granularity is
    an order of magnitude larger than the gap), so it would run many times too
    slow and drift further behind with every frame.
    """
    eng = TxEngine()
    meta = eng.load(fast_log)
    assert meta["frames"] == 1000 and abs(meta["duration_s"] - 0.999) < 0.01

    t0 = time.perf_counter()
    sent = _play(eng, speed=1.0)
    elapsed = time.perf_counter() - t0

    assert len(sent) == 1000
    assert 0.7 < elapsed < 2.2, f"1 s log took {elapsed:.2f}s"
    h = eng.status()["health"]
    assert h["sent"] == 1000
    assert abs(h["drift_ms"]) < 600
    assert h["burst_max"] >= 1


def test_drift_survives_a_mid_flight_speed_change(fast_log):
    """Drift is per speed segment.

    Log time played at 5× owes a fifth of the wall clock. Dividing the whole
    cumulative log time by whatever speed happens to be set *now* would rewrite
    history the moment the knob moves and report seconds of phantom drift.
    """
    eng = TxEngine()
    eng.load(fast_log)
    eng.play([].append, speed=5.0, repeat=0)
    time.sleep(0.3)
    assert abs(eng.status()["health"]["drift_ms"]) < 300
    eng.set_speed(1.0)
    time.sleep(0.3)
    drift = eng.status()["health"]["drift_ms"]
    eng.stop()
    assert abs(drift) < 300, f"speed change invented {drift} ms of drift"


def test_health_freezes_when_playback_ends(two_network_log):
    """A finished run keeps its final numbers instead of decaying toward zero."""
    eng = TxEngine()
    eng.load(two_network_log)
    _play(eng, speed=50.0)
    first = eng.status()["health"]
    time.sleep(0.4)
    assert eng.status()["health"] == first


def test_stop_does_not_turn_the_rewind_into_drift(fast_log):
    """``stop()`` rewinds the cursor; the frozen drift must not absorb that."""
    eng = TxEngine()
    eng.load(fast_log)
    eng.play([].append, speed=2.0, repeat=0)
    time.sleep(0.4)
    eng.stop()
    st = eng.status()
    assert st["cursor"] == 0                                 # rewound, as documented
    assert abs(st["health"]["drift_ms"]) < 300, st["health"]


def test_keeping_up_flags_a_rate_the_machine_cannot_deliver(fast_log):
    """A speed multiplier can demand more frames/s than one thread can send.

    Health must say so outright — silently smearing a 'real-time' replay is the
    worst outcome on a bench, because the device under test looks at fault.
    """
    eng = TxEngine()
    eng.load(fast_log)
    eng.play([].append, speed=1.0, repeat=0)
    time.sleep(0.6)
    assert eng.status()["health"]["keeping_up"] is True
    eng.stop()

    slow_send = lambda m: time.sleep(0.002)          # 500 fps ceiling vs 1000 fps needed
    eng.play(slow_send, speed=1.0, repeat=0)
    time.sleep(1.2)
    h = eng.status()["health"]
    eng.stop()
    assert h["keeping_up"] is False
    assert h["drift_ms"] > 250


def test_speed_scales_the_timeline(fast_log):
    eng = TxEngine()
    eng.load(fast_log)
    t0 = time.perf_counter()
    sent = _play(eng, speed=20.0)                            # 1 s log -> ~50 ms
    elapsed = time.perf_counter() - t0
    assert len(sent) == 1000
    assert elapsed < 0.6, f"20x replay took {elapsed:.2f}s"


# ----- failure handling ---------------------------------------------------
def test_a_bus_that_stops_taking_frames_is_waited_for_not_given_up_on(fast_log):
    """No ACK / bus-off / an adapter pulled: say so and wait — never stop and leave the bench
    silent until someone disconnects and reconnects (the user, 25-11-2026: "PCAN will not
    retransmit until you disconnect and reconnect"). Only Stop ends the wait."""
    eng = TxEngine()
    eng.load(fast_log)
    calls, recovers = [], []
    eng.set_recover(lambda reopen: recovers.append(reopen) or False)

    def boom(msg):
        calls.append(msg)
        raise can.CanOperationError("no ack")

    eng.play(boom, speed=200.0)
    deadline = time.time() + 5
    while eng.status()["state"] == "playing" and time.time() < deadline:
        time.sleep(0.01)
    st = eng.status()
    assert st["state"] == "recovering"
    assert "no ack" in st["error"] and st["recovering"] is not None
    assert st["sent"] == 0 and st["health"]["errors"] >= 32
    time.sleep(0.9)                                        # a few tries, growing pauses
    assert len(calls) < 60                                 # not hammering a dead bus
    assert recovers and recovers[0] is False               # the adapter's reset first
    eng.stop()
    st = eng.status()
    assert st["state"] == "ready" and st["health"]["outage_s"] > 0


def test_playback_resumes_by_itself_when_the_bus_comes_back(fast_log):
    """The frame that met the outage is retried, not dropped, and the rest follow on a fresh
    clock: nothing skipped after it, no burst of the backlog, the outage counted — not drift."""
    eng = TxEngine()
    eng.load(fast_log)
    down = {"left": 34}                                    # 32 in the burst + 2 retries, then it takes them
    out, recovers = [], []
    eng.set_recover(lambda reopen: recovers.append(reopen) or True)

    def flaky(msg):
        if down["left"] > 0:
            down["left"] -= 1
            raise can.CanOperationError("bus-off")
        out.append(msg)

    eng.play(flaky, speed=50.0)
    deadline = time.time() + 10
    seen_recovering = False
    while eng.status()["state"] in ("playing", "recovering") and time.time() < deadline:
        seen_recovering = seen_recovering or eng.status()["state"] == "recovering"
        time.sleep(0.005)
    st = eng.status()
    assert seen_recovering
    assert st["state"] == "done" and st["error"] == ""
    h = st["health"]
    assert h["recoveries"] == 1 and h["outage_s"] > 0
    # 31 frames dropped before the outage was called (each failed once); the 32nd was retried
    assert len(out) == 1000 - 31 and st["sent"] == len(out)
    # exactly the log from the retried frame (#32) on: in order, nothing skipped, nothing twice
    assert [m.arbitration_id for m in out] == [0x100 + (i % 8) for i in range(31, 1000)]
    assert abs(h["drift_ms"]) < 250                        # the wait is not counted as drift


def test_the_bus_manager_reopens_only_a_bus_the_person_still_wants():
    from ucando.bus_manager import BusManager
    bus = BusManager()
    bus.connect("virtual", "recover-test", simulate=False)
    try:
        assert bus.recover(reopen=False) is False          # the virtual bus has no reset
        first = bus.iface
        assert bus.recover(reopen=True) is True            # what Disconnect + Connect did by hand
        assert bus.connected and bus.iface is not first
        assert bus.health() is None                        # only PCAN reports a controller state
    finally:
        bus.disconnect()
    assert bus.recover(reopen=True) is False and not bus.connected   # never behind the person's back


def test_play_without_a_log_raises(tmp_path):
    with pytest.raises(RuntimeError):
        TxEngine().play([].append)


def test_select_during_playback_is_refused(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    eng.play([].append, speed=1.0, repeat=0)
    with pytest.raises(RuntimeError):
        eng.select("MS CAN")
    eng.stop()


def test_step_during_playback_is_refused(two_network_log):
    eng = TxEngine()
    eng.load(two_network_log)
    eng.play([].append, speed=1.0, repeat=0)
    with pytest.raises(RuntimeError):
        eng.step([].append)
    eng.stop()


# ----- playlist (TX-2) ----------------------------------------------------
@pytest.fixture
def session_chunks(tmp_path):
    """Two files from one capture session: B starts 0.5 s after A ends.

    This is the Vehicle Spy buffer-save shape — a long drive split into chunks
    that share one session clock.
    """
    a = _write_vspy(tmp_path / "chunk_a.csv", [
        _row(1, 100.000, "HS CAN", "100", "AA"),
        _row(2, 100.010, "HS CAN", "101", "BB"),
        _row(3, 100.020, "HS CAN", "102", "CC"),
    ])
    b = _write_vspy(tmp_path / "chunk_b.csv", [
        _row(1, 100.520, "HS CAN", "200", "11"),
        _row(2, 100.530, "HS CAN", "201", "22"),
    ])
    return a, b


def test_playlist_plays_items_in_order(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    meta = eng.set_plan([{"path": a}, {"path": b}])
    assert meta["item_count"] == 2 and meta["frames"] == 5
    sent = _play(eng, speed=20.0)
    assert [m.arbitration_id for m in sent] == [0x100, 0x101, 0x102, 0x200, 0x201]


def test_playlist_per_item_repeat_does_not_copy_frames(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    meta = eng.set_plan([{"path": a, "repeat": 3}, {"path": b}])
    assert meta["frames"] == 3 * 3 + 2
    sent = _play(eng, speed=50.0)
    assert [m.arbitration_id for m in sent] == \
        [0x100, 0x101, 0x102] * 3 + [0x200, 0x201]
    # Repeats reference one segment; the plan holds each file exactly once.
    assert len(eng.plan().segments) == 2


def test_playlist_repeat_applies_at_both_levels(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    eng.set_plan([{"path": a, "repeat": 2}, {"path": b}])
    sent = _play(eng, speed=50.0, repeat=2)              # 2 plan passes
    assert len(sent) == (3 * 2 + 2) * 2


def test_same_file_twice_is_parsed_once(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    eng.set_plan([{"path": a}, {"path": b}, {"path": a}])
    segs = eng.plan().segments
    assert len(segs) == 3
    assert segs[0].store is segs[2].store                # one FrameStore, three segments


def test_auto_gap_reconstructs_the_real_pause(session_chunks):
    a, b = session_chunks
    plan = txproject.build([{"path": a}, {"path": b, "gap_before_ms": "auto"}])
    assert plan.segments[0].gap_s == 0.0                 # nothing precedes the first item
    assert abs(plan.segments[1].gap_s - 0.5) < 1e-6      # 100.520 - 100.020
    assert abs(plan.span_s - (0.02 + 0.5 + 0.01)) < 1e-6


def test_auto_gap_is_zero_across_unrelated_sessions(tmp_path):
    """Different folders -> different session clocks -> the delta is meaningless."""
    (tmp_path / "s1").mkdir()
    (tmp_path / "s2").mkdir()
    one = _write_vspy(tmp_path / "s1" / "a.csv", [_row(1, 5.0, "HS CAN", "100", "AA")])
    two = _write_vspy(tmp_path / "s2" / "b.csv", [_row(1, 9000.0, "HS CAN", "200", "BB")])
    plan = txproject.build([{"path": one}, {"path": two, "gap_before_ms": "auto"}])
    assert plan.segments[1].gap_s == 0.0


def test_fixed_gap_delays_the_next_item(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    eng.set_plan([{"path": a}, {"path": b, "gap_before_ms": 300}])
    t0 = time.perf_counter()
    sent = _play(eng, speed=1.0)
    elapsed = time.perf_counter() - t0
    assert len(sent) == 5
    assert 0.28 < elapsed < 0.8, f"300 ms gap not honoured (took {elapsed:.2f}s)"


def test_gap_scales_with_speed(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    eng.set_plan([{"path": a}, {"path": b, "gap_before_ms": 400}])
    t0 = time.perf_counter()
    _play(eng, speed=8.0)
    assert time.perf_counter() - t0 < 0.35, "gap ignored the speed factor"


def test_trim_selects_a_window_of_one_file(session_chunks):
    a, _ = session_chunks
    eng = TxEngine()
    eng.set_plan([{"path": a, "trim_start_s": 0.005, "trim_end_s": 0.015}])
    sent = _play(eng, speed=50.0)
    assert [m.arbitration_id for m in sent] == [0x101]


def test_status_tracks_the_current_item(session_chunks):
    a, b = session_chunks
    eng = TxEngine()
    eng.set_plan([{"path": a, "repeat": 40}, {"path": b}])
    eng.play([].append, speed=1.0)
    time.sleep(0.15)
    st = eng.status()
    eng.stop()
    assert st["item"] == 0 and st["item_count"] == 2
    assert st["item_label"] == "chunk_a"                 # filenames are the event names
    assert 0 < st["progress"] < 1


def test_select_retargets_every_item(session_chunks, two_network_log):
    eng = TxEngine()
    eng.set_plan([{"path": two_network_log}, {"path": two_network_log}])
    meta = eng.select("MS CAN")
    assert meta["frames"] == 4                           # 2 MS CAN frames × 2 items
    assert all(s.network == "MS CAN" for s in eng.plan().segments)


def test_mixed_bitrate_playlist_warns(tmp_path, two_network_log):
    """One bus runs at one bitrate; a playlist that mixes them cannot play."""
    slow = _write_vspy(tmp_path / "slow.csv", [
        _row(1, 1.0, "MS CAN", "300", "AA"), _row(2, 1.01, "MS CAN", "301", "BB")])
    plan = txproject.build([{"path": two_network_log}, {"path": slow}])
    assert any("mixes bitrates" in w for w in plan.warnings)


def test_endless_item_before_others_warns(session_chunks):
    a, b = session_chunks
    plan = txproject.build([{"path": a, "repeat": 0}, {"path": b}])
    assert any("never play" in w for w in plan.warnings)


def test_empty_playlist_is_refused():
    with pytest.raises(ValueError):
        txproject.build([])


def test_scenarios_round_trip(storage, session_chunks):
    a, b = session_chunks
    items = [txproject.TxItem(path=a, repeat=2, gap_before_ms="auto"),
             txproject.TxItem(path=b, trim_start_s=0.001)]
    txproject.save(storage, "bench", items)
    assert txproject.list_saved(storage) == ["bench"]
    back = txproject.load_saved(storage, "bench")
    assert [i.to_dict() for i in back] == [i.to_dict() for i in items]
    txproject.delete_saved(storage, "bench")
    assert txproject.list_saved(storage) == []


# ----- parse cache --------------------------------------------------------
def test_cache_round_trips_a_store(two_network_log):
    fresh = logstore.load(two_network_log, use_cache=False)
    logstore.load(two_network_log)                       # populates the cache
    cached = logstore._cache_read(two_network_log, os.stat(two_network_log))
    assert cached is not None
    assert len(cached) == len(fresh)
    assert cached.networks == fresh.networks
    assert cached.network_summary() == fresh.network_summary()
    assert [cached.payload(i) for i in range(len(cached))] == \
           [fresh.payload(i) for i in range(len(fresh))]


def test_cache_is_invalidated_when_the_log_changes(tmp_path):
    p = tmp_path / "edit.csv"
    _write_vspy(p, [_row(1, 1.0, "HS CAN", "100", "AA")])
    assert len(logstore.load(str(p))) == 1
    _write_vspy(p, [_row(1, 1.0, "HS CAN", "100", "AA"),
                    _row(2, 1.01, "HS CAN", "101", "BB")])
    assert len(logstore.load(str(p))) == 2               # not the stale one-frame copy


def test_corrupt_cache_falls_back_to_parsing(two_network_log):
    logstore.load(two_network_log)
    with open(logstore.cache_path(two_network_log), "r+b") as fh:
        fh.seek(0)
        fh.write(b"{ this is not json")
    assert len(logstore.load(two_network_log)) == 6      # parsed, not crashed


# ----- REST surface -------------------------------------------------------
def test_api_load_select_and_warnings(two_network_log):
    from fastapi.testclient import TestClient
    from ucando.server import app
    client = TestClient(app)

    r = client.post("/api/replay/load", json={"path": two_network_log}).json()
    assert r["ok"] and r["meta"]["network"] == "HS CAN"
    joined = " ".join(r["warnings"])
    assert "2 networks" in joined and "MS CAN" in joined     # the discarded bus is named
    assert "transmitted itself" in joined                    # tool-TX frames skipped

    r = client.post("/api/replay/select", json={"network": "MS CAN"}).json()
    assert r["ok"] and r["meta"]["frames"] == 2 and r["meta"]["baud"] == 125_000

    # Transmitting needs a bus; without one this must fail loudly, not silently.
    r = client.post("/api/replay/play", json={"speed": 1.0}).json()
    assert not r.get("ok") and "onnect" in r["error"]


def test_api_playlist_and_scenarios(session_chunks):
    from fastapi.testclient import TestClient
    from ucando.server import app
    client = TestClient(app)
    a, b = session_chunks

    r = client.post("/api/tx/plan", json={"items": [
        {"path": a, "repeat": 2},
        {"path": b, "gap_before_ms": "auto"}]}).json()
    assert r["ok"] and r["meta"]["item_count"] == 2
    assert r["meta"]["frames"] == 3 * 2 + 2
    assert [i["label"] for i in r["meta"]["items"]] == ["chunk_a", "chunk_b"]
    assert abs(r["meta"]["items"][1]["gap_s"] - 0.5) < 1e-6

    assert client.post("/api/tx/save", json={"name": "bench-a"}).json()["ok"]
    assert "bench-a" in client.get("/api/tx/scenarios").json()["scenarios"]

    client.post("/api/replay/load", json={"path": a})            # clobber the plan
    assert client.get("/api/replay/status").json()["meta"]["item_count"] == 1

    r = client.post("/api/tx/load", json={"name": "bench-a"}).json()
    assert r["ok"] and r["meta"]["item_count"] == 2              # restored intact

    client.post("/api/tx/delete", json={"name": "bench-a"})
    assert "bench-a" not in client.get("/api/tx/scenarios").json()["scenarios"]


def test_api_save_without_a_name_is_refused(session_chunks):
    from fastapi.testclient import TestClient
    from ucando.server import app
    client = TestClient(app)
    client.post("/api/tx/plan", json={"items": [{"path": session_chunks[0]}]})
    assert not client.post("/api/tx/save", json={"name": "  "}).json().get("ok")


def test_api_logs_finds_files_in_subfolders(tmp_path, monkeypatch):
    """Real captures arrive as a folder per session, not loose files."""
    from fastapi.testclient import TestClient
    from ucando import server

    nested = tmp_path / "MG Commute 01Aug26" / "Moving Data"
    nested.mkdir(parents=True)
    (nested / "drive.csv").write_text("x", encoding="utf-8")
    (tmp_path / "top.asc").write_text("x", encoding="utf-8")

    monkeypatch.setattr(server, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_active_log_dir", lambda: str(tmp_path))
    logs = TestClient(server.app).get("/api/logs").json()["logs"]
    names = {l["name"] for l in logs}
    assert "top.asc" in names
    assert "MG Commute 01Aug26/Moving Data/drive.csv" in names


def test_unload_forgets_the_log_so_play_has_nothing_to_send(two_network_log):
    """TX replay -> Source -> Clear. Clearing only the page left the plan loaded, and Play then
    transmitted a log the screen no longer showed: unload must empty the engine itself."""
    eng = TxEngine()
    eng.load(two_network_log)
    assert eng.status()["state"] == "ready" and eng.plan() is not None
    eng.unload()
    st = eng.status()
    assert st["state"] == "empty" and eng.plan() is None and eng.meta() == {}
    eng.unload()                                  # twice, or on an empty engine: harmless
    with pytest.raises(Exception):
        eng.play(lambda msg: None)                # nothing loaded: nothing to send


# ----- notes that are news, not noise -------------------------------------------------------
def _chunk(tmp_path, name, t0, n=5, step=0.1):
    return _write_vspy(tmp_path / name, [_row(i + 1, t0 + i * step, "HS CAN", "120", "00")
                                         for i in range(n)])


def test_separate_captures_play_back_to_back_without_a_line_per_file(tmp_path):
    """A bench's S0-S8 scenarios share one start clock, so each "overlaps" the one before. With
    real gaps kept that used to raise a warning per file for a perfectly good playlist — the
    user asked twice what was wrong. None follows on from another: they are separate
    captures, back-to-back is the only sensible play, and nothing needs saying."""
    files = [_chunk(tmp_path, f"S{i}.csv", 10.0) for i in range(4)]
    plan = txproject.build([{"path": f, "gap_before_ms": "auto"} for f in files], use_cache=False)
    assert all(s.gap_s == 0.0 for s in plan.segments)
    assert not [w for w in plan.warnings if "overlap" in w]


def test_an_overlap_inside_one_session_is_still_flagged(tmp_path):
    """Chunks of one recording that follow on from each other, and one that does not — a
    duplicated or misordered file. That one is news."""
    a = _chunk(tmp_path, "a.csv", 10.0)            # 10.0 – 10.4
    b = _chunk(tmp_path, "b.csv", 10.6)            # follows a after 0.2 s
    c = _chunk(tmp_path, "c.csv", 10.2)            # starts inside b
    plan = txproject.build([{"path": p, "gap_before_ms": "auto"} for p in (a, b, c)], use_cache=False)
    assert plan.segments[1].gap_s == pytest.approx(0.2, abs=1e-6)
    overlaps = [w for w in plan.warnings if "overlap" in w]
    assert len(overlaps) == 1 and overlaps[0].startswith("c.csv")


def test_an_assumed_bitrate_is_only_mentioned_when_it_can_matter():
    """A .trc records no bitrate, so 500 k is assumed. Connected at exactly that, the note had
    nothing to act on; before connecting, or connected at another bitrate, it does."""
    from ucando import server
    meta = {"baud": 500_000, "baud_source": "assumed", "networks": []}
    said = lambda: [w for w in server._replay_warnings(meta) if "assum" in w]
    server.bus.disconnect()
    assert said() and "declare it" in said()[0]                     # not connected: what to connect at
    server.bus.connect("virtual", "baud-note", bitrate=500_000, simulate=False)
    try:
        assert said() == []                                         # connected at the assumed rate
        server.bus.connect("virtual", "baud-note", bitrate=250_000, simulate=False)
        assert said() and "250,000" in said()[0]                    # a mismatch is always said
    finally:
        server.bus.disconnect()
