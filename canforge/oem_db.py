"""OEM CAN Database (Pillar A) — the India-first signal library.

Stores reusable **profiles** (a DBC + a frame *signature*) keyed by
``(oem, model, year-range, bus)`` in the ``oem_profiles`` table, so a *known*
vehicle decodes with **zero reverse engineering**. The flywheel: an RE/DBC
session is saved back as a draft profile, reviewed, then shipped — coverage
compounds over time, exactly the OpenDBC model but for Indian vehicles.

Two capabilities sit on top of the store:

* **Fingerprinting** — reduce a capture (or a profile's own DBC) to the set of
  arbitration IDs present, with DLC/period hints.
* **Auto-identify (CANMatch-style)** — score a live/recorded fingerprint against
  every stored profile (Jaccard overlap of ID sets + DLC bonus) and rank the
  matches, so connecting a vehicle suggests "this looks like an XUV700" and
  offers to apply that profile.

Pure logic over :class:`canforge.storage.Storage`; no bus access.
"""

from __future__ import annotations

import json

from .dbc_builder import DbcModel

# OEMs we intend to cover first (drives the placeholder seed + the UI list).
TARGET_OEMS = ["Tata", "Mahindra", "Maruti Suzuki", "MG", "Nissan", "Volkswagen", "Honda"]


def fingerprint_frames(frames_by_id: dict) -> dict:
    """Reduce a frames-by-id map to a signature: id set + per-id DLC/period."""
    ids = []
    for (arb_id, ext), data in frames_by_id.items():
        payloads = data.get("payloads", [])
        ts = data.get("timestamps", [])
        period_ms = 0.0
        if len(ts) > 1:
            period_ms = round((ts[-1] - ts[0]) / (len(ts) - 1) * 1000.0, 2)
        ids.append({
            "id": arb_id, "ext": bool(ext),
            "dlc": len(payloads[0]) if payloads else 0,
            "period_ms": period_ms,
        })
    ids.sort(key=lambda r: (r["ext"], r["id"]))
    return {"ids": ids, "id_set": [f"{('x' if r['ext'] else '')}{r['id']:X}" for r in ids]}


def fingerprint_from_id_stats(stats: list[dict]) -> dict:
    """Build a signature from a logger snapshot's per-ID stats (live identify)."""
    ids = []
    for s in stats:
        ext = bool(s.get("ext"))
        ids.append({"id": int(s["id"]), "ext": ext,
                    "dlc": int(s.get("dlc", 0)), "period_ms": s.get("period_ms", 0.0)})
    ids.sort(key=lambda r: (r["ext"], r["id"]))
    return {"ids": ids, "id_set": [f"{('x' if r['ext'] else '')}{r['id']:X}" for r in ids]}


def _signature_from_dbc(dbc_text: str) -> dict:
    """Build a signature from a DBC's message frame IDs (no capture needed)."""
    model = DbcModel()
    try:
        model.import_dbc_string(dbc_text)
    except Exception:
        return {"ids": [], "id_set": []}
    ids = []
    for m in model.messages.values():
        ext = bool(m.get("is_extended"))
        ids.append({"id": int(m["frame_id"]), "ext": ext,
                    "dlc": int(m.get("length", 0)), "period_ms": 0.0})
    ids.sort(key=lambda r: (r["ext"], r["id"]))
    return {"ids": ids, "id_set": [f"{('x' if r['ext'] else '')}{r['id']:X}" for r in ids]}


def _score(profile_sig: dict, cap_sig: dict) -> dict:
    """Jaccard overlap of ID sets, with a small bonus for matching DLCs."""
    pset = set(profile_sig.get("id_set", []))
    cset = set(cap_sig.get("id_set", []))
    if not pset or not cset:
        return {"score": 0.0, "matched": 0, "profile_ids": len(pset)}
    inter = pset & cset
    union = pset | cset
    jaccard = len(inter) / len(union)
    # DLC bonus: of the matched IDs, how many share the same DLC.
    pdlc = {f"{('x' if r['ext'] else '')}{r['id']:X}": r["dlc"] for r in profile_sig.get("ids", [])}
    cdlc = {f"{('x' if r['ext'] else '')}{r['id']:X}": r["dlc"] for r in cap_sig.get("ids", [])}
    dlc_ok = sum(1 for k in inter if pdlc.get(k) == cdlc.get(k))
    dlc_bonus = (dlc_ok / len(inter)) * 0.1 if inter else 0.0
    return {"score": round(min(1.0, jaccard + dlc_bonus), 4),
            "matched": len(inter), "profile_ids": len(pset)}


class OemDatabase:
    def __init__(self, storage):
        self._s = storage

    # ----- CRUD ------------------------------------------------------------
    def add_profile(self, oem: str, name: str, *, model: str = "", dbc: str = "",
                    signature: dict | None = None, year_min: int | None = None,
                    year_max: int | None = None, bus: str = "CAN",
                    bitrate: int = 500_000, status: str = "draft") -> int:
        if signature is None:
            signature = _signature_from_dbc(dbc) if dbc else {"ids": [], "id_set": []}
        return self._s.insert(
            "oem_profiles", oem=oem, model=model, name=name, dbc=dbc,
            signature=json.dumps(signature), year_min=year_min, year_max=year_max,
            bus=bus, bitrate=bitrate, status=status, version=1)

    def get_profile(self, pid: int) -> dict | None:
        row = self._s.get("oem_profiles", pid)
        if row:
            row["signature"] = json.loads(row.get("signature") or "{}")
        return row

    def list_profiles(self, oem: str | None = None) -> list[dict]:
        rows = self._s.list("oem_profiles", order="oem, model, name")
        if oem:
            rows = [r for r in rows if r["oem"] == oem]
        for r in rows:
            sig = json.loads(r.get("signature") or "{}")
            r["id_count"] = len(sig.get("id_set", []))
            r.pop("signature", None)          # keep the list payload light
            r.pop("dbc", None)
        return rows

    def update_profile(self, pid: int, patch: dict) -> dict | None:
        allowed = {"oem", "model", "name", "dbc", "year_min", "year_max",
                   "bus", "bitrate", "status"}
        sets, params = [], []
        for k, v in patch.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                params.append(v)
        if "dbc" in patch:                    # refresh signature when DBC changes
            sets.append("signature = ?")
            params.append(json.dumps(_signature_from_dbc(patch["dbc"])))
        if sets:
            params.append(pid)
            self._s.execute(f"UPDATE oem_profiles SET {', '.join(sets)} WHERE id = ?", tuple(params))
        return self.get_profile(pid)

    def delete_profile(self, pid: int) -> None:
        self._s.delete("oem_profiles", pid)

    # ----- import / save-from-builder -------------------------------------
    def import_dbc(self, oem: str, name: str, dbc_text: str, *, model: str = "",
                   status: str = "draft") -> int:
        DbcModel().import_dbc_string(dbc_text)   # validate (raises on bad DBC)
        return self.add_profile(oem, name, model=model, dbc=dbc_text, status=status)

    def save_from_dbc_model(self, dbc_model: DbcModel, oem: str, name: str,
                            *, model: str = "", status: str = "draft") -> int:
        return self.add_profile(oem, name, model=model,
                                dbc=dbc_model.to_dbc_string(), status=status)

    # ----- auto-identify ---------------------------------------------------
    def identify_from_signature(self, cap_sig: dict, top: int = 5,
                                min_score: float = 0.1) -> list[dict]:
        out = []
        for r in self._s.list("oem_profiles"):
            sig = json.loads(r.get("signature") or "{}")
            sc = _score(sig, cap_sig)
            if sc["score"] >= min_score:
                out.append({"profile_id": r["id"], "oem": r["oem"], "model": r["model"],
                            "name": r["name"], "status": r["status"], **sc})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top]

    def identify(self, frames_by_id: dict, top: int = 5, min_score: float = 0.1) -> list[dict]:
        return self.identify_from_signature(fingerprint_frames(frames_by_id), top, min_score)

    # ----- seeding ---------------------------------------------------------
    def seed_builtins(self) -> int:
        """Insert the demo profile + OEM placeholders if absent. Idempotent."""
        existing = {(r["oem"], r["name"]) for r in self._s.list("oem_profiles")}
        added = 0

        # A real, decodable demo profile matching the virtual-bus simulator, so
        # auto-identify works end-to-end offline (and the flywheel is testable).
        if ("uCANdo", "Sim Vehicle") not in existing:
            m = DbcModel()
            m.add_message(0x100, "ENGINE", length=8)
            m.add_signal(0x100, {"name": "EngineRPM", "start_bit": 7, "length": 16,
                                 "byte_order": "big_endian", "scale": 1, "offset": 0, "unit": "rpm"})
            m.add_message(0x200, "COUNTER", length=4)
            m.add_signal(0x200, {"name": "RollingCounter", "start_bit": 7, "length": 8,
                                 "byte_order": "big_endian"})
            self.add_profile("uCANdo", "Sim Vehicle", model="virtual",
                             dbc=m.to_dbc_string(), status="shipped")
            added += 1

        # Placeholder entries for the target OEMs — coverage grows via RE.
        for oem in TARGET_OEMS:
            if (oem, f"{oem} (no data yet)") not in existing:
                self.add_profile(oem, f"{oem} (no data yet)", status="draft")
                added += 1
        return added
