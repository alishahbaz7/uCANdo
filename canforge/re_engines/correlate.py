"""LibreCAN-style correlation: auto-label unknown signals against ground truth.

Given a log that contains both proprietary frames *and* standard OBD-II PID
responses (captured while driving), this:

1. decodes the OBD-II PIDs (speed, RPM, coolant temp, …) into ground-truth time
   series — these are the "known" physical quantities;
2. runs the READ engine on every non-OBD ID to get candidate signals and
   reconstructs each candidate's raw value over time;
3. correlates each candidate against each ground-truth series (Pearson r) and,
   for strong matches, recovers the **scale** and **offset** via linear
   regression — so an unknown signal comes back labelled "Engine RPM, scale 1.0,
   offset 0" with no manual work.

This is the automated alternative to eyeballing the sniffer: drive the car with
an OBD logger attached and the proprietary signals label themselves. Pure stdlib
(``math``); the only inputs are the loaded frames and the OBD PID table.
"""

from __future__ import annotations

import math

from ..dashboard import OBD_PIDS, OBD_RESPONSE_IDS
from .read import analyze_id_read, value_be, value_le

MIN_PAIRS = 5


def _obd_ground_truth(frames: dict) -> dict:
    """Decode OBD-II Mode-01 PID responses into ``{name: (ts[], val[])}``."""
    series: dict[str, tuple[list, list]] = {}
    for (arb, _ext), data in frames.items():
        if arb not in OBD_RESPONSE_IDS:
            continue
        for p, t in zip(data["payloads"], data["timestamps"]):
            if not p or (p[0] >> 4) != 0:
                continue
            ln = p[0] & 0x0F
            payload = p[1:1 + ln]
            if len(payload) < 2 or payload[0] != 0x41:
                continue
            entry = OBD_PIDS.get(payload[1])
            if not entry:
                continue
            name, _unit, fn = entry
            try:
                val = fn(payload[2:])
            except Exception:
                val = None
            if val is None:
                continue
            ts_list, val_list = series.setdefault(name, ([], []))
            ts_list.append(t)
            val_list.append(float(val))
    return series


def _reconstruct(payload: bytes, cand: dict) -> float:
    if (cand["byte_order"] == "little_endian"
            and cand["start_bit"] % 8 == 0 and cand["length"] % 8 == 0):
        return float(value_le(payload, cand["start_bit"], cand["length"]))
    return float(value_be(payload, cand["start_bit"], cand["length"]))


def _align(cand_ts: list, cand_vals: list, gt_ts: list, gt_vals: list):
    """Pair each candidate sample with the latest ground-truth value (ZOH)."""
    xs, ys, j = [], [], 0
    if not gt_ts:
        return xs, ys
    for t, v in zip(cand_ts, cand_vals):
        while j + 1 < len(gt_ts) and gt_ts[j + 1] <= t:
            j += 1
        if gt_ts[j] <= t:
            xs.append(v)
            ys.append(gt_vals[j])
    return xs, ys


def _pearson_fit(xs: list, ys: list):
    """Return ``(r, slope, intercept)`` regressing ys on xs, or None."""
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    r = sxy / math.sqrt(sxx * syy)
    slope = sxy / sxx
    return r, slope, my - slope * mx


def correlate_log(path: str, r_threshold: float = 0.9, max_frames_per_id: int = 20000) -> dict:
    from ..reverse import load_log_frames
    frames = load_log_frames(path, max_frames_per_id)
    gt = _obd_ground_truth(frames)

    labeled_ids = []
    for (arb, ext), data in frames.items():
        if arb in OBD_RESPONSE_IDS or arb == 0x7DF:
            continue
        payloads, ts = data["payloads"], data["timestamps"]
        info = analyze_id_read(payloads)
        labeled = []
        for cand in info["candidates"]:
            if cand["kind"] in ("constant",):
                continue
            cand_vals = [_reconstruct(p, cand) for p in payloads]
            best = None
            for gname, (gts, gvals) in gt.items():
                xs, ys = _align(ts, cand_vals, gts, gvals)
                fit = _pearson_fit(xs, ys)
                if fit and abs(fit[0]) >= r_threshold and (best is None or abs(fit[0]) > abs(best["r"])):
                    r, slope, intercept = fit
                    best = {"label": gname, "r": round(r, 3),
                            "scale": round(slope, 6), "offset": round(intercept, 3)}
            if best:
                labeled.append({**cand, **best, "name": best["label"].replace(" ", "")})
        if labeled:
            labeled_ids.append({"id": arb, "id_hex": f"{arb:0{8 if ext else 3}X}",
                                "ext": ext, "labeled": labeled})

    labeled_ids.sort(key=lambda r: r["id"])
    return {"path": path, "ground_truth": sorted(gt.keys()), "labeled_ids": labeled_ids}
