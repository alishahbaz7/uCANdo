"""RE Session — the spine that turns raw analysis into a tiered identification.

One :class:`RESession` accumulates **evidence** about candidate signals from
every technique (READ structure, OBD correlation, known-value match, toggle
events, DB match, user confirmation), keyed by their bit location. It dedups,
scores each candidate via :mod:`canforge.confidence`, and emits the **A / B / C**
report the UI shows — and can export the confirmed signals straight to a DBC /
OEM profile (closing the flywheel).

Both product modes feed this one object:
* **Mode 1 (passive)** — :func:`populate_from_log` runs READ + OBD correlation
  over a recorded log.
* **Mode 2 (guided)** — the protocol runner calls :meth:`add_evidence` per step
  (event / ramp / known-value).

No bus access; pure accumulation + scoring, so it's fully unit-testable.
"""

from __future__ import annotations

from .confidence import score
from .dbc_builder import DbcModel

# Two candidate locations are "the same signal" if in the same frame and their
# bit ranges overlap by at least this fraction (handles READ vs correlation
# finding slightly different boundaries for one field).
_OVERLAP = 0.6


def _id_hex(frame_id: int, ext: bool) -> str:
    return f"{frame_id:0{8 if ext else 3}X}"


class RESession:
    def __init__(self, name: str = ""):
        self.name = name
        # location key -> candidate {frame_id, ext, start_bit, length, byte_order, evidence[]}
        self._cands: dict[tuple, dict] = {}

    @staticmethod
    def _key(frame_id, ext, start_bit, length, byte_order):
        return (int(frame_id), bool(ext), int(start_bit), int(length), byte_order)

    # ----- accumulate ------------------------------------------------------
    def add_evidence(self, frame_id, start_bit, length, *, byte_order="big_endian",
                     ext=False, source="structural", label=None,
                     scale=None, offset=None, unit=None, **detail) -> dict:
        """Record one piece of evidence about a located field."""
        key = self._key(frame_id, ext, start_bit, length, byte_order)
        cand = self._cands.get(key)
        if cand is None:
            cand = {"frame_id": int(frame_id), "ext": bool(ext), "start_bit": int(start_bit),
                    "length": int(length), "byte_order": byte_order, "evidence": []}
            self._cands[key] = cand
        for k, v in (("scale", scale), ("offset", offset), ("unit", unit)):
            if v is not None:
                detail[k] = v
        cand["evidence"].append({"source": source, "label": label, "detail": detail})
        return cand

    def confirm(self, frame_id, start_bit, length, *, byte_order="big_endian",
                ext=False, label=None) -> None:
        """User confirms a candidate (promotes to tier A)."""
        self.add_evidence(frame_id, start_bit, length, byte_order=byte_order, ext=ext,
                          source="user", label=label, confirmed=True)

    def reject(self, frame_id, start_bit, length, *, byte_order="big_endian", ext=False) -> None:
        """User rejects a candidate (forces tier C)."""
        self.add_evidence(frame_id, start_bit, length, byte_order=byte_order, ext=ext,
                          source="user", confirmed=False)

    # ----- read ------------------------------------------------------------
    @staticmethod
    def _pick(cand: dict, field: str):
        """Take a detail value from the labelled evidence first, else any."""
        labelled = [e for e in cand["evidence"] if e.get("label")]
        for e in labelled + cand["evidence"]:
            if field in (e.get("detail") or {}):
                return e["detail"][field]
        return None

    def _signal(self, cand: dict) -> dict:
        sc = score(cand["evidence"])
        # Surface the READ "kind" (counter/crc/physical/...) so even unknown
        # fields carry intelligence about what they *do*.
        kind = next((e["detail"].get("kind") for e in cand["evidence"]
                     if e.get("source") == "structural" and (e.get("detail") or {}).get("kind")), None)
        return {
            "frame_id": cand["frame_id"], "id_hex": _id_hex(cand["frame_id"], cand["ext"]),
            "ext": cand["ext"], "start_bit": cand["start_bit"], "length": cand["length"],
            "byte_order": cand["byte_order"],
            "label": sc["label"], "tier": sc["tier"], "confidence": sc["score"],
            "sources": sc["sources"], "kind": kind,
            "scale": self._pick(cand, "scale"), "offset": self._pick(cand, "offset"),
            "unit": self._pick(cand, "unit"),
        }

    def report(self) -> dict:
        """Tiered result: ``{"A": [...], "B": [...], "C": [...], "counts": {...}}``."""
        out = {"A": [], "B": [], "C": []}
        for cand in self._cands.values():
            sig = self._signal(cand)
            out[sig["tier"]].append(sig)
        for tier in out:
            out[tier].sort(key=lambda s: (-s["confidence"], s["frame_id"]))
        out["counts"] = {t: len(out[t]) for t in ("A", "B", "C")}
        return out

    # ----- export ----------------------------------------------------------
    def to_dbc_model(self, tiers=("A",)) -> DbcModel:
        """Build a DBC from signals in the given confidence tiers (default: A only)."""
        rep = self.report()
        wanted = [s for t in tiers for s in rep.get(t, [])]
        model = DbcModel()
        by_msg: dict[int, list] = {}
        for s in wanted:
            by_msg.setdefault(s["frame_id"], []).append(s)
        for fid, sigs in by_msg.items():
            ext = sigs[0]["ext"]
            model.add_message(fid, f"MSG_{_id_hex(fid, ext)}", length=8, is_extended=ext)
            used, occupied = set(), set()
            for s in sigs:                                # sigs arrive in confidence order
                # Skip a signal overlapping a higher-confidence one already kept,
                # so the exported DBC is always valid (no overlapping signals).
                span = set(range(s["start_bit"] // 8, (s["start_bit"] + s["length"] + 7) // 8))
                if span & occupied:
                    continue
                occupied |= span
                name = (s["label"] or f"sig_{s['start_bit']}_{s['length']}").replace(" ", "")
                while name in used:                      # avoid duplicate signal names
                    name += "_"
                used.add(name)
                model.add_signal(fid, {
                    "name": name, "start_bit": s["start_bit"], "length": s["length"],
                    "byte_order": s["byte_order"], "is_signed": False,
                    "scale": s["scale"] if s["scale"] is not None else 1.0,
                    "offset": s["offset"] if s["offset"] is not None else 0.0,
                    "unit": s["unit"] or "",
                })
        return model


def apply_db_match(session: RESession, frames: dict, oem_db, min_present: float = 0.5) -> dict | None:
    """CANMatch: recognise the vehicle from the OEM DB and apply its known signals.

    Picks the profile whose message IDs are most present on this bus (≥
    ``min_present`` fraction) and adds each of its signals as **db_match**
    evidence (tier A) — so a previously-RE'd vehicle decodes with no ground
    truth at all. Returns ``{profile, oem, present, of}`` or None.
    """
    import cantools
    log_ids = set(frames.keys())
    best = None
    for row in oem_db.list_profiles():
        prof = oem_db.get_profile(row["id"])
        if not prof.get("dbc"):
            continue
        try:
            db = cantools.database.load_string(prof["dbc"], database_format="dbc")
        except Exception:
            continue
        keys = [(m.frame_id, bool(m.is_extended_frame)) for m in db.messages]
        if not keys:
            continue
        present = sum(1 for k in keys if k in log_ids)
        if present / len(keys) >= min_present and (best is None or present > best[1]):
            best = (prof, present, db)
    if not best:
        return None
    prof, present, db = best
    for m in db.messages:
        if (m.frame_id, bool(m.is_extended_frame)) not in log_ids:
            continue
        for s in m.signals:
            session.add_evidence(m.frame_id, s.start, s.length, byte_order=s.byte_order,
                                 ext=bool(m.is_extended_frame), source="db_match", label=s.name,
                                 scale=s.scale, offset=s.offset, unit=s.unit, profile=prof["name"])
    return {"profile": prof["name"], "oem": prof["oem"], "present": present, "of": len(db.messages)}


def populate_from_log(session: RESession, path: str, r_threshold: float = 0.70,
                      known_values: dict | None = None, oem_db=None) -> RESession:
    """Mode 1: feed a recorded log through DB-match + READ + OBD correlation.

    * ``oem_db`` — if given, recognise the vehicle and apply known signals (CANMatch).
    * ``known_values`` maps a label to a static dash reading (e.g.
      ``{"Odometer": 19335}``), resolved by known-value matching.
    """
    from .reverse import load_log_frames
    from .re_engines.read import analyze_id_read
    from .re_engines.correlate import _obd_ground_truth, correlate_windows, known_value_matches

    frames = load_log_frames(path)

    # DB-match first (High) — recognise a known vehicle even with no ground truth.
    if oem_db is not None:
        apply_db_match(session, frames, oem_db)

    # Structural evidence (Low) — every READ candidate, so unknown fields still surface.
    for (arb, ext), data in frames.items():
        if arb == 0x7DF or 0x7E0 <= arb <= 0x7EF:
            continue
        info = analyze_id_read(data["payloads"])
        for c in info["candidates"]:
            session.add_evidence(arb, c["start_bit"], c["length"], byte_order=c["byte_order"],
                                 ext=ext, source="structural", kind=c["kind"])

    # OBD correlation evidence (High/Medium by r) — semantic labels + scale/offset.
    gt = _obd_ground_truth(frames)
    for s in correlate_windows(frames, gt, r_threshold=r_threshold):
        session.add_evidence(s["id"], s["start_bit"], s["length"], byte_order=s["byte_order"],
                             ext=s["ext"], source="obd_correlation", label=s["label"],
                             scale=s["scale"], offset=s["offset"], r=s["r"])

    # Known-value evidence (High) — static dash readings the user supplied.
    for label, target in (known_values or {}).items():
        matches = known_value_matches(frames, target)
        if matches:
            m = matches[0]
            session.add_evidence(m["id"], m["start_bit"], m["length"], byte_order=m["byte_order"],
                                 ext=m["ext"], source="known_value", label=label,
                                 scale=m["scale"], offset=0, exact=(m["error"] < 1.0))
    return session
