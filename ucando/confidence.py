"""Confidence engine — turn RE *evidence* into A / B / C tiers.

Every candidate signal collects **evidence** from one or more sources (DB match,
OBD correlation, known-value match, a toggle event, or just structural shape).
This module maps a candidate's evidence to a confidence tier — the three buckets
the product exposes:

* **A — high / confirmed**  → show on the dashboard with name + confidence
* **B — medium / suspected** → needs a one-click user confirmation
* **C — low / unknown**       → behaviour only, no trustworthy meaning yet

A single strong source sets the tier; **corroboration** (two independent sources
agreeing on the same label) promotes B → A. Pure functions, no state — see
:mod:`ucando.resession` for the object that accumulates evidence.

Each *evidence* item is a plain dict::

    {"source": "obd_correlation", "label": "Engine RPM", "detail": {"r": 0.96, ...}}

``source`` is one of: db_match, obd_correlation, known_value, event, user,
structural.
"""

from __future__ import annotations

TIER_A, TIER_B, TIER_C = "A", "B", "C"
_RANK = {TIER_C: 0, TIER_B: 1, TIER_A: 2}


def _evidence_tier(ev: dict) -> tuple[str, float]:
    """Map one evidence item to ``(tier, score 0..1)`` from its source + detail."""
    src = ev.get("source")
    d = ev.get("detail") or {}
    if src == "user":                       # explicit human confirm / reject
        return (TIER_A, 1.0) if d.get("confirmed", True) else (TIER_C, 0.0)
    if src == "db_match":                   # matched a known shipped profile
        return TIER_A, 0.97
    if src == "known_value":                # field equals a value the user supplied
        return (TIER_A, 0.98) if d.get("exact", True) else (TIER_B, 0.75)
    if src == "obd_correlation":            # correlated against an OBD ground truth
        r = abs(d.get("r", 0.0))
        if r >= 0.95:
            return TIER_A, r
        if r >= 0.70:
            return TIER_B, r
        return TIER_C, r
    if src == "event":                      # bit flipped when a control was toggled
        return (TIER_A, 0.92) if d.get("single_bit") else (TIER_B, 0.70)
    if src == "structural":                 # READ shape only (counter/crc/physical)
        return TIER_C, 0.30
    return TIER_C, 0.0


def score(evidence: list[dict]) -> dict:
    """Combine a candidate's evidence into ``{tier, score, label, sources}``."""
    if not evidence:
        return {"tier": TIER_C, "score": 0.0, "label": None, "sources": []}

    rated = [(_evidence_tier(e), e) for e in evidence]
    (tier, sc), best_ev = max(rated, key=lambda t: (_RANK[t[0][0]], t[0][1]))
    label = best_ev.get("label")

    # Corroboration: a Medium result with >=2 independent sources agreeing on the
    # same label is as trustworthy as a single High source — promote it.
    if tier == TIER_B and label:
        agreeing = {e["source"] for (t, _s), e in rated
                    if _RANK[t] >= 1 and e.get("label") == label}
        if len(agreeing) >= 2:
            tier, sc = TIER_A, max(sc, 0.90)

    return {"tier": tier, "score": round(sc, 3), "label": label,
            "sources": sorted({e.get("source") for e in evidence})}
