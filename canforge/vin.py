"""VIN parsing and pattern matching — identify a vehicle *before* touching CAN.

Fingerprinting a bus (``oem_db.identify_from_signature``) needs the vehicle
connected, running, and broadcasting; it then scores a Jaccard overlap that can
be ambiguous between closely-related models. A **VIN** settles the question
outright, is readable over OBD-II Mode 09 PID 02 or UDS DID ``F190``, and is
printed on the door pillar — so it works even with the ignition off.

Packs declare which VINs they cover with glob patterns in ``vehicle.json``::

    {"vin_patterns": ["MZ72D5FEF*"]}

Only a **prefix** is ever stored. Characters 1-9 describe the manufacturer and
the model/body/powertrain; the unit-specific part (serial, plant) lives in
12-17 and is deliberately never recorded, so a pattern identifies a *model*,
not a car.

.. warning::
   **Do not decode the model year from position 10 for Indian-market MG.** ISO
   3779 assigns that character a year code, but the observed MG Windsor Pro VIN
   ``MZ72D5FEF8H030876`` carries ``8`` at position 10, which ISO reads as 2008
   for a vehicle confirmed to be a 2026 model. JSW MG Motor India evidently
   uses its own scheme there, so :func:`split` reports the raw character and
   refuses to interpret it.
"""

from __future__ import annotations

import re

#: ISO 3779 excludes I, O and Q so they cannot be confused with 1 and 0.
_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
_VIN_RE = re.compile(rf"^[{_VIN_CHARS}]{{17}}$")


def normalise(vin: str) -> str:
    """Upper-case and strip separators. Does not validate."""
    return re.sub(r"[^A-Za-z0-9]", "", vin or "").upper()


def is_valid_format(vin: str) -> bool:
    """17 characters from the ISO 3779 alphabet. Structure only — the North
    American check digit is not verified because Indian-market VINs do not
    reliably carry one."""
    return bool(_VIN_RE.match(normalise(vin)))


def split(vin: str) -> dict:
    """Break a VIN into its ISO 3779 sections.

    ``year_code`` is the *raw* character at position 10 — see the module
    warning; it is never turned into a year here.
    """
    v = normalise(vin)
    if not is_valid_format(v):
        return {}
    return {"vin": v, "wmi": v[0:3], "vds": v[3:9], "vis": v[9:17],
            "year_code": v[9], "plant": v[10], "serial": v[11:17]}


def matches(vin: str, pattern: str) -> bool:
    """Glob-match a VIN against a pattern using ``*`` (any run) and ``?`` (one).

    Matching is anchored at both ends, so ``MZ7*`` matches any MG India VIN
    while ``MZ7`` alone matches nothing — a pattern must describe the whole
    string. Case and separators are normalised away first.
    """
    v, p = normalise(vin), normalise(pattern).replace("STAR", "*")
    if not v or not pattern:
        return False
    # normalise() strips '*' and '?', so build the regex from the raw pattern
    raw = (pattern or "").upper().strip()
    rx = "".join("." if c == "?" else ".*" if c == "*" else re.escape(c) for c in raw)
    return re.fullmatch(rx, v) is not None


def best_pattern_match(vin: str, patterns) -> str | None:
    """Return the **most specific** matching pattern, or None.

    Specificity is the count of literal (non-wildcard) characters, so a pack
    claiming ``MZ72D5FEF*`` wins over one claiming the whole-marque ``MZ7*``.
    """
    hits = [p for p in patterns or [] if matches(vin, p)]
    if not hits:
        return None
    return max(hits, key=lambda p: sum(1 for c in p if c not in "*?"))
