"""LibreCAN-style correlation engine."""

import math
import struct

import can

from canforge.re_engines.correlate import correlate_log, _pearson_fit


def test_pearson_fit_recovers_line():
    xs = list(range(20))
    ys = [3 * x + 5 for x in xs]
    r, slope, intercept = _pearson_fit(xs, ys)
    assert round(r, 3) == 1.0
    assert round(slope, 3) == 3.0
    assert round(intercept, 3) == 5.0


def _write_log(path):
    w = can.ASCWriter(path)
    for i in range(300):
        rpm = int(2000 + 1500 * math.sin(i / 30.0))
        # raw proprietary frame: rpm big-endian in bytes 0-1
        w.on_message_received(can.Message(
            arbitration_id=0x100, data=struct.pack(">HHHH", rpm, 0, 0, i & 0xFFFF),
            is_extended_id=False, timestamp=i * 0.05))
        # OBD-II RPM response (PID 0x0C), raw = rpm * 4
        r = rpm * 4
        w.on_message_received(can.Message(
            arbitration_id=0x7E8, data=bytes([0x04, 0x41, 0x0C, (r >> 8) & 0xFF, r & 0xFF, 0, 0, 0]),
            is_extended_id=False, timestamp=i * 0.05 + 0.01))
    w.stop()


def test_correlate_labels_signal_against_obd(tmp_path):
    p = str(tmp_path / "drive.asc")
    _write_log(p)
    res = correlate_log(p)
    assert "Engine RPM" in res["ground_truth"]
    labeled = [L for d in res["labeled_ids"] if d["id_hex"] == "100" for L in d["labeled"]]
    assert labeled, "expected 0x100 to correlate with an OBD signal"
    best = max(labeled, key=lambda L: abs(L["r"]))
    assert best["label"] == "Engine RPM"
    assert abs(best["r"]) > 0.95
    assert abs(best["scale"] - 1.0) < 0.1          # recovered ~1:1 scale
