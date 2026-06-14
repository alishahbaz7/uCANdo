"""Guided RE (Mode 2) — fuel-type protocols + a step runner.

A **protocol** (data in ``canforge/protocols/<fuel>.json``) is an ordered list of
steps; each step's ``kind`` maps to one RE technique that yields high-confidence
evidence *because the stimulus is controlled*:

* ``baseline``     — record an idle reference window
* ``stimulus``     — user toggles a control; diff after-vs-baseline → the bit that
  flipped (event evidence; single changed bit ⇒ high confidence)
* ``ramp``         — record while a value varies; correlate vs OBD ground truth
* ``known_value``  — user enters a dash reading; known-value match

All techniques feed one :class:`~canforge.resession.RESession`, so guided runs
produce the same A/B/C report and exportable profile as the passive mode. The
:class:`GuidedRunner` methods are pure (operate on captured frames passed in);
the live capture/timing/prompting lives in ``canforge.cli guided``.
"""

from __future__ import annotations

import json
import os

from .resession import RESession

PROTO_DIR = os.path.join(os.path.dirname(__file__), "protocols")


def list_protocols() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(PROTO_DIR) if f.endswith(".json"))


def load_protocol(fuel: str) -> dict:
    path = os.path.join(PROTO_DIR, f"{fuel.lower()}.json")
    if not os.path.isfile(path):
        raise ValueError(f"no protocol for fuel {fuel!r}; have {list_protocols()}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class FrameCollector:
    """A bus tap that accumulates frames into the frames-by-id shape for a window."""

    def __init__(self):
        self.frames: dict = {}

    def consume(self, msg) -> None:
        key = (msg.arbitration_id, bool(msg.is_extended_id))
        b = self.frames.get(key)
        if b is None:
            b = {"payloads": [], "timestamps": []}
            self.frames[key] = b
        b["payloads"].append(bytes(msg.data))
        b["timestamps"].append(msg.timestamp)

    def reset(self) -> None:
        self.frames = {}

    def snapshot(self) -> dict:
        return {k: {"payloads": list(v["payloads"]), "timestamps": list(v["timestamps"])}
                for k, v in self.frames.items()}


class GuidedRunner:
    """Applies protocol steps to captured frames, accumulating into an RE session."""

    def __init__(self, protocol: dict, session: RESession | None = None):
        self.protocol = protocol
        self.session = session or RESession(protocol.get("title", ""))

    def steps(self) -> list[dict]:
        return self.protocol.get("steps", [])

    # ----- per-technique appliers (pure: operate on passed-in frames) ------
    def apply_stimulus(self, step: dict, baseline_frames: dict, after_frames: dict) -> dict:
        """Diff after-vs-baseline; label the changed bits with the step's signal."""
        from .re_engines.diff import diff_frames
        d = diff_frames(baseline_frames, after_frames)
        for ch in d["changed"]:
            for cand in ch.get("candidates", []):
                self.session.add_evidence(
                    ch["id"], cand["start_bit"], cand["length"],
                    byte_order=cand["byte_order"], ext=ch["ext"], source="event",
                    label=step.get("label"), single_bit=(cand["length"] == 1))
        return d

    def apply_ramp(self, step: dict, frames: dict) -> int:
        """Correlate every candidate field against the OBD ground truth in the window."""
        from .re_engines.correlate import _obd_ground_truth, correlate_windows
        gt = _obd_ground_truth(frames)
        n = 0
        for s in correlate_windows(frames, gt, r_threshold=step.get("r_threshold", 0.80)):
            self.session.add_evidence(
                s["id"], s["start_bit"], s["length"], byte_order=s["byte_order"],
                ext=s["ext"], source="obd_correlation", label=s["label"],
                scale=s["scale"], offset=s["offset"], r=s["r"])
            n += 1
        return n

    def apply_known(self, step: dict, frames: dict, value: float):
        """Locate the field carrying a user-supplied static reading."""
        from .re_engines.correlate import known_value_matches
        matches = known_value_matches(frames, float(value))
        if not matches:
            return None
        best = matches[0]
        self.session.add_evidence(
            best["id"], best["start_bit"], best["length"], byte_order=best["byte_order"],
            ext=best["ext"], source="known_value", label=step.get("label"),
            scale=best["scale"], offset=0, exact=(best["error"] < 1.0))
        return best

    # ----- read / export ---------------------------------------------------
    def report(self) -> dict:
        return self.session.report()

    def to_dbc_string(self) -> str:
        return self.session.to_dbc_model(("A",)).to_dbc_string()
