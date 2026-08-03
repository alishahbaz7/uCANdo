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
from pathlib import Path

from . import vin as vin_mod
from .dbc_builder import DbcModel

# OEMs we intend to cover first (drives the UI's coverage list, not DB rows —
# an OEM with no data is a gap in the list, never an empty profile).
TARGET_OEMS = ["Tata", "Mahindra", "Maruti Suzuki", "MG", "Nissan", "Volkswagen", "Honda"]

#: Marks a profile row as owned by the ``oem_packs/`` folder tree (stored in the
#: otherwise-unused ``platform`` column). Only these rows are pruned when their
#: pack disappears, so hand-made and RE-saved profiles are never touched.
PACK_ORIGIN = "oem_pack"


def iter_packs(packs_dir) -> list[dict]:
    """Discover vehicle packs in the ``oem_packs/`` library.

    Layout is ``<Make>/<Model>/<Fuel>_<Year>/<file>.dbc`` (see
    ``oem_packs/README.md``), so a new vehicle is added by dropping files in a
    folder — no code change. An optional sibling ``signature.json`` supplies a
    **capture-derived** fingerprint (real DLCs and periods, and every ID on the
    bus rather than only those the DBC happens to describe), which identifies far
    better than the DBC-derived fallback: the Windsor DBC covers 53 of the 147
    IDs its bus actually carries, so a DBC-only signature would score ~0.36
    Jaccard against a live capture instead of ~1.0.

    A leaf folder may hold **more than one DBC** — the same vehicle tapped at a
    different point sees a different bus segment (an OBD-2 port and a
    powertrain-local tap do not carry the same IDs). Name those
    ``..._<year>_<bus>.dbc``; the suffix after the year becomes the profile's
    ``bus`` and is appended to its name, so the two never collide. Each DBC may
    carry its own ``<stem>.signature.json``, falling back to a folder-wide
    ``signature.json``.

    Malformed packs are skipped rather than raised — one bad folder must not
    stop the app from starting.
    """
    root = Path(packs_dir)
    if not root.is_dir():
        return []
    packs = []
    for dbc_path in sorted(root.glob("*/*/*/*.dbc")):
        variant = dbc_path.parent.name                    # EV_2026
        model = dbc_path.parent.parent.name               # Windsor
        oem = dbc_path.parent.parent.parent.name          # MG
        fuel, _, year = variant.partition("_")
        try:
            dbc_text = dbc_path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Anything in the filename after "<model>_<fuel>[_<year>]" names the tap.
        stem = dbc_path.stem.lower()
        lead = "_".join(x for x in (oem, model, fuel, year) if x).lower()
        bus = stem[len(lead):].strip("_") if stem.startswith(lead) else ""
        signature = None
        for cand in (dbc_path.with_suffix(".signature.json"),
                     dbc_path.parent / "signature.json"):
            if cand.is_file():
                try:
                    signature = json.loads(cand.read_text(encoding="utf-8"))
                    break
                except (OSError, ValueError):
                    continue                              # try the fallback
        meta = {}
        meta_path = dbc_path.parent / "vehicle.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        yr = int(year) if year.isdigit() else None
        name = " ".join(x for x in (model, fuel, year) if x)
        packs.append({"oem": oem, "model": model, "fuel": fuel, "year": yr,
                      "bus": bus or "CAN",
                      "name": f"{name} ({bus})" if bus else name,
                      "dbc": dbc_text, "signature": signature,
                      "vin_patterns": list(meta.get("vin_patterns") or [])})
    return packs


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


def _dbc_counts(dbc_text: str) -> tuple[int, int]:
    """``(messages, signals)`` defined in a DBC, counted off the text.

    A line scan rather than a cantools parse: the Profiles list renders every
    row on each refresh and the biggest pack DBC is ~30 KB, so parsing them all
    just to show two numbers is waste. The ``BO_ ``/``SG_ `` prefixes are
    unambiguous — the other keywords that start with them (``BO_TX_BU_``,
    ``SG_MUL_VAL_``) have no space at that position.
    """
    msgs = sigs = 0
    for line in dbc_text.splitlines():
        s = line.lstrip()
        if s.startswith("BO_ "):
            msgs += 1
        elif s.startswith("SG_ "):
            sigs += 1
    return msgs, sigs


def _year_label(row: dict) -> str:
    """Model year for display: the stored range, else a year in the name.

    Profiles saved from an RE session have no year columns, but their name
    almost always carries one ("Aura 2023 (HSCAN1)") — reading it back keeps the
    column meaningful instead of mostly em-dashes.
    """
    lo, hi = row.get("year_min"), row.get("year_max")
    if lo and hi and lo != hi:
        return f"{lo}–{hi}"
    if lo or hi:
        return str(lo or hi)
    for tok in str(row.get("name", "")).replace("(", " ").replace(")", " ").split():
        if len(tok) == 4 and tok.isdigit() and 1980 <= int(tok) <= 2099:
            return tok
    return ""


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
                    bitrate: int = 500_000, status: str = "draft",
                    platform: str = "") -> int:
        if signature is None:
            signature = _signature_from_dbc(dbc) if dbc else {"ids": [], "id_set": []}
        return self._s.insert(
            "oem_profiles", oem=oem, model=model, name=name, dbc=dbc,
            signature=json.dumps(signature), year_min=year_min, year_max=year_max,
            bus=bus, bitrate=bitrate, status=status, platform=platform, version=1)

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
            # id_count is what the *bus* carries (capture-derived where a pack
            # ships a signature); msg_count is what the DBC can actually decode.
            # They differ on purpose — Windsor sees 116 IDs, decodes 53.
            r["id_count"] = len(sig.get("id_set", []))
            r["msg_count"], r["signal_count"] = _dbc_counts(r.get("dbc") or "")
            r["year"] = _year_label(r)
            r.pop("signature", None)          # keep the list payload light
            r.pop("dbc", None)
        return rows

    def profile_signals(self, pid: int) -> dict | None:
        """Expand a profile's DBC into its messages and signals.

        Backs the Profiles list's click-through: the row shows counts, this
        shows what those counts are made of. ``None`` when there is no such
        profile; an unparseable DBC yields empty messages + an ``error`` rather
        than raising, so one bad profile can't break the view.
        """
        p = self.get_profile(pid)
        if p is None:
            return None
        head = {"id": pid, "oem": p["oem"], "model": p["model"], "name": p["name"],
                "bus": p.get("bus") or "CAN", "status": p.get("status"),
                "year": _year_label(p), "messages": []}
        model = DbcModel()
        try:
            model.import_dbc_string(p.get("dbc") or "")
        except Exception as exc:
            return {**head, "error": str(exc)}
        for m in sorted(model.messages.values(), key=lambda m: m["frame_id"]):
            width = 8 if m.get("is_extended") else 3
            head["messages"].append({
                "frame_id": m["frame_id"], "id_hex": f"{m['frame_id']:0{width}X}",
                "name": m["name"], "length": m.get("length", 0),
                "is_extended": bool(m.get("is_extended")),
                "signals": m.get("signals", []),
            })
        head["msg_count"] = len(head["messages"])
        head["signal_count"] = sum(len(m["signals"]) for m in head["messages"])
        return head

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

    def prune_blank(self) -> int:
        """Drop profiles that carry nothing decodable; repair stale signatures.

        A row is *blank* when its signature holds no IDs **and** its DBC yields
        no messages — an empty placeholder, or a save that produced a
        header-only DBC. Such rows can neither be applied nor identified
        against, so they are pure noise in the Profiles list.

        A row whose DBC *does* parse but whose signature is empty (written
        before the signature was computed, or by an older version) is repaired
        rather than deleted. Idempotent; safe to run on every startup.
        """
        removed = 0
        for r in self._s.list("oem_profiles"):
            if json.loads(r.get("signature") or "{}").get("id_set"):
                continue
            sig = _signature_from_dbc(r.get("dbc") or "")
            if sig["id_set"]:                      # DBC is fine, signature was stale
                self._s.execute("UPDATE oem_profiles SET signature = ? WHERE id = ?",
                                (json.dumps(sig), r["id"]))
            else:
                self.delete_profile(r["id"])
                removed += 1
        return removed

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

    def identify_from_vin(self, vin: str, packs_dir) -> list[dict]:
        """Identify a vehicle from its VIN — exact, unlike fingerprint scoring.

        Patterns are read from the pack folders rather than the profile rows:
        the ``oem_profiles`` table has no VIN column and this store has no
        migration framework, and the folder tree is already the source of truth
        for packs. Each hit is joined back to its DB profile so the caller can
        apply it by ``id``.

        Ranked by pattern specificity, so a model-level pattern beats a
        marque-wide one. Returns ``[]`` for a malformed VIN rather than
        guessing.
        """
        if not vin_mod.is_valid_format(vin):
            return []
        by_key = {(r["oem"], r["name"]): r for r in self._s.list("oem_profiles")}
        out = []
        for pack in iter_packs(packs_dir):
            hit = vin_mod.best_pattern_match(vin, pack.get("vin_patterns"))
            if not hit:
                continue
            row = by_key.get((pack["oem"], pack["name"]))
            out.append({"id": row["id"] if row else None,
                        "oem": pack["oem"], "name": pack["name"],
                        "model": pack["model"], "year": pack["year"],
                        "matched_pattern": hit,
                        "specificity": sum(1 for c in hit if c not in "*?"),
                        "decodable": bool(pack["dbc"])})
        out.sort(key=lambda d: -d["specificity"])
        return out

    # ----- seeding ---------------------------------------------------------
    def seed_builtins(self, packs_dir=None) -> int:
        """Insert the demo profile and any ``oem_packs/`` vehicles that are
        absent. Idempotent. Only *decodable* profiles are ever created — an
        uncovered OEM shows up in ``TARGET_OEMS``, not as an empty row.

        ``packs_dir`` is opt-in so the library stays pure and tests stay
        deterministic; ``server.py`` passes the bundled ``oem_packs/``.
        """
        existing = {(r["oem"], r["name"]) for r in self._s.list("oem_profiles")}
        added = 0

        packs = iter_packs(packs_dir) if packs_dir else []
        # Adopt rows an older build seeded before pack-origin tagging existed,
        # so they become managed (and therefore prunable) from now on. Limited
        # to 'shipped' rows that still match a pack exactly.
        by_key = {(r["oem"], r["name"]): r for r in self._s.list("oem_profiles")}
        for pack in packs:
            r = by_key.get((pack["oem"], pack["name"]))
            if r and r.get("status") == "shipped" and not r.get("platform"):
                self._s.execute("UPDATE oem_profiles SET platform = ? WHERE id = ?",
                                (PACK_ORIGIN, r["id"]))

        for pack in packs:
            if (pack["oem"], pack["name"]) in existing:
                continue
            self.add_profile(pack["oem"], pack["name"], model=pack["model"],
                             dbc=pack["dbc"], signature=pack["signature"],
                             year_min=pack["year"], year_max=pack["year"],
                             bus=pack["bus"], platform=PACK_ORIGIN, status="shipped")
            existing.add((pack["oem"], pack["name"]))
            added += 1

        # The folder tree is the source of truth: renaming a pack folder (say
        # ZS EV -> ZS EV 2026) must not leave the old profile behind, or the DB
        # lists one vehicle twice and mis-identifies it. Only rows this seeder
        # created are eligible — user-made and RE-saved profiles are untouched.
        if packs_dir:
            live = {(p["oem"], p["name"]) for p in packs}
            for r in self._s.list("oem_profiles"):
                if r.get("platform") == PACK_ORIGIN and (r["oem"], r["name"]) not in live:
                    self.delete_profile(r["id"])

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
        return added
