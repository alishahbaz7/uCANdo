# OEM Packs — vehicle DBC library

Reverse-engineered and validated CAN databases, one leaf folder per concrete
vehicle variant.

> **Building or reviewing a pack?** `.claude/skills/dbc-pack/SKILL.md` is the
> working playbook — signal-confidence grading, bit-numbering conversion, RE
> techniques ranked by the confidence they earn, and the pre-flight checklist.
> This file is the library's *layout and inventory*; that one is the *method*.

## Layout

```
oem_packs/
└── <Make>/                  MG, Hyundai, Suzuki, Mahindra, Tata, ...
    └── <Model>/             Windsor, ZS, Aura, Bolero, ...
        └── <Fuel>_<Year>/   EV_2026, Petrol_2023, Diesel_2021, Hybrid_2024
            └── <make>_<model>_<fuel>_<year>.dbc
```

Three levels, then the file:

| Level | Value | Rule |
|---|---|---|
| 1 — Make | `MG` | Brand as sold in India, PascalCase, no spaces |
| 2 — Model | `Windsor` | Model line only — no variant/trim, no fuel, no year |
| 3 — Fuel + Year | `EV_2026` | One of **`Petrol`**, **`Diesel`**, **`EV`**, **`Hybrid`**, **`CNG`**, then `_` and the 4-digit model year |
| File | `mg_windsor_ev_2026.dbc` | lowercase `<make>_<model>_<fuel>_<year>.dbc` |

The filename repeats the whole path on purpose: a DBC copied out of the tree and
handed to a colleague still says exactly which vehicle it belongs to.

**Why fuel and year sit together at level 3:** the same model line is often sold
with several powertrains at once (ZS petrol vs ZS EV), and the CAN map changes
across model years. Both together identify a unique bus layout — which is the
thing a DBC is actually valid for.

**Year may be omitted** (`EV/` rather than `EV_2022/`) when it genuinely isn't
known. A pack with a missing year is better than one with an invented year —
rename the folder once it is established.

### More than one bus per vehicle

A vehicle tapped at two points yields two different views: an OBD-2 port and a
powertrain-local tap near the accelerator-position sensor do **not** carry the
same arbitration IDs. Put both DBCs in the same leaf folder and add a tap
suffix after the year:

```
MG/ZS/EV_2022/
├── mg_zs_ev_2022_obd.dbc            -> profile "ZS EV 2022 (obd)", bus=obd
├── mg_zs_ev_2022_obd.signature.json
├── mg_zs_ev_2022_aps.dbc            -> profile "ZS EV 2022 (aps)", bus=aps
└── mg_zs_ev_2022_aps.signature.json
```

The suffix becomes the profile's `bus` and is appended to its name, so the two
never collide. Without a suffix the profile is plain `CAN`.

### vehicle.json — VIN patterns

Optional. Lets a vehicle be identified from its **VIN** instead of its bus
fingerprint, which is exact rather than a similarity score, and works with the
ignition off (the VIN is on the door pillar, and readable over OBD-II Mode 09
PID 02 / UDS DID `F190`):

```json
{"vin_patterns": ["MZ72D5FEF*"]}
```

`*` matches any run, `?` one character, and the pattern must describe the whole
VIN. When several packs match, the **most specific** pattern wins, so a
model-level `MZ72D5FEF*` beats a marque-wide `MZ7*`.

**Store a prefix only.** Characters 1-9 give manufacturer + model/body/
powertrain; 12-17 are the plant and serial. Omitting the tail means a pattern
identifies a *model*, not a car — no VIN of a real vehicle is ever committed.

> **Marque-specific.** A 2026 Maruti Suzuki Dzire reads `T` at position 10,
> which ISO 3779 gives as 2026 — correct. So Maruti appears to follow the code
> where MG does not. One confirmation is not enough to name folders by it; see
> [docs/SUZUKI_DZIRE_2026_GATEWAY.md](../docs/SUZUKI_DZIRE_2026_GATEWAY.md) §4.

> **Never infer the model year from a VIN for MG India.** ISO 3779 puts a year
> code at position 10, but the observed Windsor Pro VIN has `8` there — ISO
> reads that as 2008 for a confirmed 2026 car. `vin.split()` reports the raw
> character and refuses to interpret it.

One VIN is not enough to write a good pattern: it cannot tell you which
characters are model-discriminating and which are unit-specific. Collect
several per model and widen or narrow accordingly. Record your confidence in
the file (`vin_pattern_confidence`).

### signature.json

Optional, and worth adding. It holds a **capture-derived** fingerprint — every
ID actually on the bus, with real DLCs and periods. Auto-identify falls back to
deriving one from the DBC, but that is much weaker: the Windsor DBC describes 53
of the 147 IDs its bus carries, so a DBC-derived signature would score ~0.36
Jaccard against a live capture instead of ~1.0.

Per-DBC (`<stem>.signature.json`) wins over a folder-wide `signature.json`.

## Current contents

| Make | Model | Variant | Signals | Sig IDs | Verified? | Provenance |
|---|---|---|---|---|---|---|
| MG | Commute | `EV_2026` | 301 | 116 | ✅ full | [docs/MG_COMMUTE_DECODE.md](../docs/MG_COMMUTE_DECODE.md) — OBD-2, 2026-08-01, **114S** LFP. Capture: `data/uploads/MG Commute 01Aug26/`. |
| MG | Windsor Pro | `EV_2026` | 301 | 120 | ✅ full | Same platform as Commute, **98S** pack. Derived from the Commute DBC and validated against its own dash photo: ODO 19010, SoC 42 %, DTE 176, gear P, cell-sum 322.286 V vs reported 322.2 — all exact. Carries a **VIN pattern**. |
| MG | Comet | `EV_2024` | 61 | — | ⚠️ none | Supplied DBC. Its `0x140` had DLC 3 with a signal at bit 26 — **cantools refused to load it**; corrected to DLC 4. Its odometer scale `0.01565` is a rounded 1/64 and reads 3071 where 1/64 reads the correct 3066 on Windsor data. |
| MG | ZS | `EV_2026` | 33 | 56 | ⚠️ none | Earlier in-house RE. Identity confirmed: 10/15 of its IDs (incl. `0x540` odo, `0x2A2` range, `0x3AC` SoC) appear in all six July-2026 MG captures. |
| MG | ZS | `EV_2022` | 33 | — | ⚠️ none | Accelerator-position-sensor tap. **Functionally identical to the `EV_2026` pack** — same 15 messages, same 33 signals, byte-differences only in whitespace/metadata. See *Pending*. |
| Hyundai | Aura | `Petrol_2023` | 3 | — | ✅ partial | Petrol car, neoVI 2026-06-13. Engine rpm (`0x316`/`0x556`) and odometer (`0x5B0`, 0.1 km). Shares its bus map with the CNG pack below, which re-confirmed all three. |
| Hyundai | Aura | `CNG_2024` | 12 | 30 | ✅ full | [docs/HYUNDAI_AURA_DECODE.md](../docs/HYUNDAI_AURA_DECODE.md) — **petrol + CNG bi-fuel**, 17 captures 2026-08-20 **incl. 4 MOVING**. The only pack with motion data: odometer 0.1 km confirmed against a recorded drive, and vehicle + 4 wheel speeds proved at 1/32 km/h by integrating to that distance. Clutch, brake, parking brake, headlamp, driver door and AC isolated by labelled captures. The four wheel-speed fields on `0x386` are documented but **deliberately not shipped** — their wheel-to-field mapping was never established and `VehicleSpeed` carries the same information. Carries a **VIN pattern**. |
| Suzuki | Dzire | `Petrol` | 32 | 31 | ✅ partial | [docs/SUZUKI_DZIRE_DECODE.md](../docs/SUZUKI_DZIRE_DECODE.md) — PCAN-View, 2026-08-19, 14 event-isolated captures. Odometer, rpm, pedal and VIN confirmed against a dash photo **and** a Teltonika FMB150 readout. Carries a **VIN pattern**. **Year unknown — see Pending.** |
| Suzuki | WagonR | `CNG` | 34 | 38 | ✅ partial | [docs/SUZUKI_WAGONR_DECODE.md](../docs/SUZUKI_WAGONR_DECODE.md) — Vehicle Spy 3 / neoVI 3G, 2026-08-20. Factory bi-fuel (petrol + CNG). An **OBD-II scan tool was live during the capture**, so rpm, coolant, load and timing are calibrated against Mode-01 PIDs; odometer and VIN confirmed against a dash photo and the **build plate**. **Partially matches the Dzire pack (0.729)** — same platform, all 13 decodable Dzire messages present. Carries a **VIN pattern**. **Year unknown.** |

`Mahindra/` is a placeholder.

**Verified** means signals were proved against ground truth (dash readings, or an
internal cross-check such as cell-sum vs reported pack voltage). An unverified
pack still auto-identifies a vehicle, but do not trust its scales.

## A pack must load in a *strict* DBC tool, not just cantools

`cantools` is lenient. It happily loaded a Dzire pack whose `VAL_` block sat
*before* its `BA_DEF_` block, and Vector/PCAN-class tools rejected that same file
with `line 141: syntax error`. Packs get handed to colleagues who open them in
those tools, so "cantools loads it" is necessary but **not sufficient**.

DBC section order is fixed by the grammar and must be:

```
VERSION → NS_ → BS_ → BU_ → BO_ → CM_ → BA_DEF_ → BA_DEF_DEF_ → BA_ → VAL_
```

`tests/test_pack_dbc_syntax.py` enforces this — plus statement termination,
balanced quotes, `BO_`/`SG_` line shape, and that every `CM_`/`BA_`/`VAL_`
references a message that exists — across **every** DBC in this tree.

## What belongs in a pack DBC

**A message goes in the DBC only if it carries at least one signal you can name.**
Empty frames, constant bytes, one-shot power-up frames and unidentified byte dumps
belong in the RE record under `docs/`, not in the database. A `.dbc` is opened to
*decode a bus*; a tree of `UNK_3A1` / `INIT_4E0` nodes costs the reader attention and
returns nothing, and it buries the signals that do matter.

This costs nothing in identification: `signature.json` is **capture-derived and
independent of the DBC**, so it still carries every ID on the bus. The Dzire pack
dropped from 41 messages to 13 and its auto-identify score stayed at **1.000**.

Same rule for near-duplicates. Buses commonly send a value twice (a copy, a
complement, or the same state from several ECUs). Keep **one** and name the mirrors in
the signal comment — the Dzire's `EngineNotRunning` is published by four ECUs and
appears once.

## Adding a vehicle

1. Create `<Make>/<Model>/<Fuel>_<Year>/` and drop the `.dbc` in, named per the
   rule above.
2. Add a row to the table here.
3. Write the RE record under `docs/` and link it — **a pack without provenance
   is not trustworthy**. State what was confirmed against ground truth and what
   was inferred; the Windsor doc is the model to follow (Tier A / B / C).

## Pending

- **The two ZS packs are content-identical but genuinely different cars** —
  `EV_2022` (accelerator-position-sensor tap) and `EV_2026` (earlier in-house
  RE). Confirmed intentional: the same signal set was found to apply to both
  model years. Both are kept; neither has independent verification.
- **VIN patterns exist for only one pack** (Windsor Pro), from a single VIN, so
  confidence is low. Every other pack falls back to fingerprint identification.
- **No RE record for the ZS or Comet packs.** Their signals have not been proved
  against ground truth the way the Commute car's were.
- **Feed the Comet's odometer scale back.** Its `0.01565` is a rounded 1/64; on
  Windsor data 1/64 matches the dash exactly and `0.01565` is 5 km out at
  3000 km. Very likely the Comet wants 1/64 too, but that needs a Comet capture
  with a dash reading to confirm — not changed on a guess.
- **The Aura pack's folder year is disputed.** It is named `Petrol_2023` but the
  vehicle captured on 2026-08-20 has `S` at VIN position 10, which ISO 3779 reads
  as 2025. Either the folder is wrong or two model years share one bus map — the
  original three signals decode correctly on both capture sets, so the map is
  shared either way. Resolve before trusting the folder name.
- **The Aura is the only vehicle in the library that has been driven.** Its
  1.1 km reference pins speed to about +/-9 %; a longer drive would tighten that
  and reveal any speedometer bias. Coolant, fuel level, passenger door, blinker
  and gear are all still open on it - a cold-start capture is the cheapest next
  step (see its RE record).
- **A gateway-isolated vehicle yields no pack.** The 2026 Maruti Suzuki Dzire
  broadcasts nothing on its OBD-2 port — only diagnostic request/response — so
  there is no bus to describe and deliberately no pack for it. Packing that
  vehicle needs a tap on an internal bus, behind the gateway. See
  [docs/SUZUKI_DZIRE_2026_GATEWAY.md](../docs/SUZUKI_DZIRE_2026_GATEWAY.md).
- **The WagonR was captured in one fuel mode only.** It is factory bi-fuel and was
  running on CNG for the whole 33 s, so no fuel-mode flag could be isolated and the
  two `0x3B9` fuel bytes are not assigned to tanks. Capture a **petrol-to-CNG
  changeover** to settle both at once.
- **Dzire `ManifoldAbsolutePressure` and `ThrottlePosition` are inherited from the
  WagonR**, where an OBD-II scan tool named them. They are graded C in the Dzire
  pack and have never been checked on that car. A scan tool on a Dzire would
  promote them.
- **The Dzire pack has no model year.** VIN position 10 is `J` (ISO 3779 → 2018), but the
  MG note above is exactly why that is not enough for an Indian marque. Rename
  `Suzuki/Dzire/Petrol/` → `Petrol_<year>/` (and the `.dbc` with it) once the year is
  confirmed from the registration or build plate.
- **The Dzire car never moved during its capture.** Speed, wheel speeds and the odometer
  quantum are therefore unproven, and no gear signal exists (it is a manual). One short
  drive would close all of these at once — the highest-value follow-up capture in the
  library.
- **July 2026 captures are loose** in `data/uploads/` (`MG1`, `MG2`, `MG3`,
  `ak3`, `mg6*`). They are the ZS EV session; worth moving into a dated folder.
  `MG3` and `RAW MG3` are byte-identical.
