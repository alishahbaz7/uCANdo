"""Offline log -> Signal Viewer decode (SignalViewer.decode_frames_offline,
reverse.flatten_frames_by_id, /api/log/signals) — visualize a log against
whatever DBC is loaded, without touching the live bus ring buffers."""

import os
import tempfile

import cantools

from ucando.reverse import flatten_frames_by_id, load_log_frames
from ucando.signals import SignalViewer
from tests.test_vspy import SAMPLE          # the trimmed real Vehicle Spy capture

DBC_94 = """VERSION ""

BU_:

BO_ 148 HS_CAN__94: 7 Vector__XXX
 SG_ Motor_speed : 3|12@0+ (10,0) [0|40950] "" Vector__XXX
 SG_ PARKING_BRAKES : 48|1@0+ (1,0) [0|1] "" Vector__XXX
"""


def _sample_path(tmp_path):
    p = tmp_path / "mg6.csv"
    p.write_text(SAMPLE, encoding="utf-8")
    return str(p)


def test_flatten_frames_by_id_is_chronological_across_ids():
    flat = flatten_frames_by_id({
        (0x94, False): {"timestamps": [10.0, 12.0], "payloads": [b"\x00", b"\x01"]},
        (0x1B2, False): {"timestamps": [11.0], "payloads": [b"\x02"]},
    })
    assert [f["timestamp"] for f in flat] == [10.0, 11.0, 12.0]
    assert [f["id"] for f in flat] == [0x94, 0x1B2, 0x94]


def test_decode_frames_offline_without_dbc_reports_not_loaded():
    viewer = SignalViewer()
    assert viewer.decode_frames_offline([]) == {"loaded": False, "series": {}}


def test_decode_frames_offline_matches_cantools_and_skips_unknown_ids(tmp_path):
    db = cantools.database.load_string(DBC_94, database_format="dbc")
    viewer = SignalViewer()
    viewer.load_dbc_string(DBC_94, "test.dbc")

    flat = flatten_frames_by_id(load_log_frames(_sample_path(tmp_path)))
    result = viewer.decode_frames_offline(flat)

    assert result["loaded"] is True
    assert result["frames_seen"] == len(flat) == 7          # every frame in SAMPLE
    assert result["frames_decoded"] == 2                    # only the two id-0x94 frames match this DBC

    pts = result["series"]["HS_CAN__94.Motor_speed"]
    assert len(pts) == 2
    # First decodable frame anchors t=0 (mirrors the live consume() semantics).
    assert pts[0][0] == 0.0 and pts[1][0] > 0

    expected = [db.decode_message(0x94, f["data"])["Motor_speed"]
                for f in flat if f["id"] == 0x94]
    assert [v for _, v in pts] == expected

    # ids the DBC doesn't define (1B2, 169, ...) contribute no series at all.
    assert not any(k.split(".")[0] not in ("HS_CAN__94",) for k in result["series"])

    # ...and are reported as "unknown to this DBC", not silently dropped —
    # 5 other ids appear once each in SAMPLE (169, 1B2, 1F2, 40A, 41F).
    assert result["decode_errors"] == []
    unknown = {u["id_hex"]: u["count"] for u in result["unknown_ids"]}
    assert unknown == {"169": 1, "1B2": 1, "1F2": 1, "40A": 1, "41F": 1}


def test_decode_frames_offline_tolerates_short_dlc_via_allow_truncated():
    """A frame shorter than the DBC's declared length must still decode
    whichever signals fit, instead of the whole frame being dropped — this is
    the fix for logs whose real-world DLC is sometimes shorter than the DBC
    assumes (very common; was silently starving the decoded-frame count)."""
    viewer = SignalViewer()
    viewer.load_dbc_string(DBC_94, "test.dbc")
    frames = [{"id": 148, "timestamp": 0.0, "data": bytes.fromhex("0006")}]  # 2 bytes, not 7

    result = viewer.decode_frames_offline(frames)

    assert result["frames_decoded"] == 1
    assert result["decode_errors"] == [] and result["unknown_ids"] == []
    assert result["series"]["HS_CAN__94.Motor_speed"] == [(0.0, 60.0)]
    assert "HS_CAN__94.PARKING_BRAKES" not in result["series"]  # needs byte 6 — not present


def test_decode_frames_offline_does_not_touch_live_ring_buffers(tmp_path):
    """A log-playback decode must be invisible to a connected live session."""
    viewer = SignalViewer()
    viewer.load_dbc_string(DBC_94, "test.dbc")
    flat = flatten_frames_by_id(load_log_frames(_sample_path(tmp_path)))

    viewer.decode_frames_offline(flat)

    live = viewer.series()
    assert live["series"] == {}
    assert live["frames_seen"] == 0 and live["frames_decoded"] == 0


def test_log_signals_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from ucando.server import app, viewer as server_viewer
    c = TestClient(app)

    # /api/log/signals decodes against the server's shared Signal Viewer DBC —
    # save/restore it so this test doesn't leak state into the rest of the suite.
    saved_db, saved_name = server_viewer._db, server_viewer._dbc_name
    try:
        server_viewer.load_dbc_string(DBC_94, "test.dbc")
        up = c.post("/api/upload", files={"file": ("mg6.csv", SAMPLE.encode(), "text/csv")}).json()
        assert up["ok"]

        r = c.post("/api/log/signals", json={"path": up["path"]}).json()
        assert r["ok"] and r["loaded"]
        assert len(r["series"]["HS_CAN__94.Motor_speed"]) == 2
    finally:
        server_viewer.clear()
        with server_viewer._lock:
            server_viewer._db, server_viewer._dbc_name = saved_db, saved_name
