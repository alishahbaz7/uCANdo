# Auto-Identification & Reverse-Engineering — Roadmap & Flow

Two ways to turn raw CAN frames into named, trustworthy signals. Both feed **one
shared engine**: a *confidence-scored evidence pipeline* that produces a tiered
result and grows the OEM database (the flywheel).

---

## ✅ Progress so far (2026-06-13)

Foundation is built and **proven on real hardware**:
- **Hardware:** Intrepid neoVI FIRE live on a **Hyundai Aura 2023** (HSCAN1 @ 500k), 87k-frame drive log captured (`data/logs/aura_drive.asc`).
- **Signals extracted & verified** (first real OEM profile, `oem_packs/Hyundai/Aura/Petrol_2023/hyundai_aura_petrol_2023.dbc`):
  - **Engine RPM** — `0x316` & `0x556`, bytes 2-3 LE, ×0.25 → matches OBD exactly (mean 1844 rpm).
  - **Odometer** — `0x5B0`, 24-bit LE, ×0.1 km → 19335.3 km, matches the dash.
- **Both RE techniques work on real data:** OBD sliding-window correlation (dynamic) + known-value matching (static).
- **Engines/tools in place:** READ (structure), `correlate.py` (sliding-window), `diff.py` sniffer, OEM DB + CANMatch, `cli drive` / `cli sniff` field tools, neoVI driver-assistant (`preflight.py`/`drivers.py`).

## 🎯 What we must achieve next (the gap)

The pieces produce *outputs*; they don't yet produce a **confidence-tiered, user-facing identification** or run a **guided protocol**. To get there:
1. **Confidence engine + RE Session** — merge all evidence into A/B/C tiers (the spine). *(build first)*
2. **Guided protocol runner + Petrol protocol** (Mode 2) — controlled stimuli → High-confidence labels fast; then Diesel & EV as data.
3. **Auto-RE workspace UI** — tiered A/B/C view, Confirm/Reject/Relabel for B, behaviour explorer for C, save-to-profile.
4. **Passive log pipeline** (Mode 1) — continuous/upload analysis on the same spine.
5. **Provenance + confidence on every saved signal**, so CANMatch auto-applies on the next same-model car (flywheel closes).

Target signal set (starter, telematics-essential): RPM✓, Coolant, Odometer✓, VSS, Intake Air Temp, MAF, Gear, AC, Headlight, Indicator, Hazard, APP, Brake sw, Clutch sw, Door, Seatbelt, MIL.

---

## 0. The unifying concept — confidence from evidence

Every candidate signal (a `(frame_id, start_bit, length, byte_order)`) accumulates
**evidence** from one or more sources. Confidence is a function of the strongest
evidence **plus corroboration** (independent sources agreeing bumps it up).

| Evidence source | Technique | Base confidence |
|---|---|---|
| DB match (CANMatch fingerprint → shipped profile) | passive | **High** (prior knowledge) |
| OBD correlation, r ≥ 0.95 | passive/guided | **High** |
| Known-value match (odometer/fuel entered by user, exact) | guided | **High** |
| Event isolation — one bit flips exactly when a control is toggled | guided | **High** |
| OBD correlation, 0.70 ≤ r < 0.95 (or rev-only ambiguity) | passive | **Medium** |
| Event — several bits changed (noisy toggle) | guided | **Medium** |
| Structural only (READ says physical/counter/crc, no meaning) | passive | **Low** |
| **Corroboration**: ≥2 independent sources agree | — | **+1 tier** |

**Output tiers (what you described):**
- **A · High / confirmed** → shown on the dashboard with name + PID/SPN + confidence %, live-decoded (e.g. RPM, Coolant, Odometer).
- **B · Medium / needs a check** → "Suspected" list with the tool's best guess + a one-click **Confirm / Reject / Relabel**. On confirm → promotes to A and writes to the profile.
- **C · Low / unknown** → "Unknown fields" explorer: shows the bits + behaviour (counter/crc/physical/enum) and confidence, so an expert can dig or a guided step can resolve it.

This tiering is the single output contract for **both** modes.

---

## 1. Mode 1 — Passive Log Analysis (drive & record, or upload a log)

> "Keep recording; tell me what you can, with confidence."

**Flow:**
```
ingest (live capture OR uploaded .asc/.blf/.csv)
  → frames-by-id
  → [A] STRUCTURAL pass (READ): boundaries, types, counters, CRCs, mux   → all candidates @ Low
  → [B] DB-MATCH pass (CANMatch): fingerprint vs OEM DB                   → matched signals @ High ("from DB")
  → [C] CORRELATION pass: if OBD PIDs present, sliding-window vs ground   → labels + scale @ High/Medium by r
  → [D] KNOWN-VALUE pass: user-entered static values (odo, fuel, VIN)     → exact matches @ High
  → CONFIDENCE ENGINE merges evidence, dedups, assigns A/B/C
  → DASHBOARD: A live-decoded w/ confidence; B in "confirm" queue; C in explorer
  → user confirms B → promote to A → save to profile (flywheel)
```
Runs continuously while logging; confidence rises as more data arrives (e.g. speed
stays Medium until the car actually moves, then jumps to High).

## 2. Mode 2 — Instructed / Guided RE (fuel-type protocol)

> "Walk me through a scripted set of actions; isolate each signal as I do it."

Each fuel type has an ordered **protocol** of steps. A step is one of three kinds,
and each maps to a technique that yields **High** confidence *because the stimulus
is controlled and isolated*:

| Step kind | What the tool does | Finds |
|---|---|---|
| **stimulus** ("turn on AC", "open door") | baseline → you act → diff → the bit that flipped | discrete status |
| **ramp** ("drive 20–30 km/h", "rev") | record + correlate the varying value vs OBD/IMU | analog sensors |
| **known-value** ("enter odo / fuel %") | search frames for a field equal to your number | static values |

**Petrol protocol (your example) → technique → expected result:**
| # | Instruction | Kind | Target (confidence) |
|---|---|---|---|
| i | Turn on IGN (don't start) | baseline | establishes "engine-off" reference |
| ii | Start engine | stimulus/ramp | **RPM** appears & rises (High) |
| iii | Drive 20–30 km/h | ramp | **VSS / wheel speed** separates from RPM (High); APP, MAF |
| iv | AC on → off | stimulus | **AC status** bit (High) |
| iv | Door open → close | stimulus | **Door status** bit (High) |
| iv | Headlight on → off | stimulus | **Headlight status** bit (High) |
| iv | Indicators / Hazard | stimulus | **Indicator / Hazard** bits (High) |
| iv | Brake / Clutch press | stimulus | **Brake / Clutch switch** (High) |
| v | Enter current odometer | known-value | **Odometer** field + scale (High) |
| vi | Enter approx fuel level | known-value | **Fuel level** field + scale (High) |

**Diesel** adds: boost/MAP, DPF state, glow-plug, EGT. **EV** replaces RPM/coolant
with: **SoC, motor RPM, regen, pack voltage/current/temp, charge status** (and
"enter SoC %" as a known-value step). Protocols are **data** (`protocols/petrol.json`
etc.) so adding a fuel type or step = editing data, not code.

The guided run produces a high-confidence profile in one sitting — this is the
fastest path to a complete vehicle, and it's how we seed the India OEM DB.

---

## 3. Shared architecture (both modes → one pipeline)

```
            ┌─────────────── Mode 1: passive ───────────────┐
 live/upload │  READ ─ DB-match ─ correlate ─ known-value     │
            └───────────────┬───────────────────────────────┘
                            ▼
                   ┌──────────────────┐      ┌─────────────────────┐
                   │  RE SESSION       │ ───▶ │ CONFIDENCE ENGINE    │ ──▶ tiered result (A/B/C)
                   │ (accumulates       │      │ evidence → tier      │       │
                   │  candidates +      │      └─────────────────────┘       ▼
                   │  evidence, dedups) │                              DASHBOARD (A live, B confirm, C explore)
                   └──────────────────┘                                     │ user confirms
            ┌───────────────┴───────────────────────────────┐               ▼
 guided run │  Mode 2: protocol steps (stimulus/ramp/known)  │        OEM DB profile (flywheel) + provenance
            └───────────────────────────────────────────────┘
```

**What we already have ✓**
- READ structural engine, sliding-window OBD correlation, state-change sniffer,
  known-value matching (prototyped on the odometer), OEM DB + CANMatch identify,
  `cli drive` / `cli sniff` field tools.

**What to build (new) 🆕**
1. **`resession.py` — RE Session**: one object that holds all candidates and their
   evidence across passes/steps, dedups overlapping windows, and is the single
   thing the UI/profile reads.
2. **`confidence.py` — Confidence engine**: maps evidence → A/B/C with corroboration.
3. **`protocols/` + a runner**: fuel-type JSON protocols (petrol/diesel/ev) and a
   step executor that brackets stimuli (reusing sniffer/correlate/known-value).
4. **Auto-RE workspace (UI)**: pick mode → run → tiered A/B/C view with live decode
   for A, Confirm/Reject/Relabel for B, behaviour explorer for C; "save profile".
5. **Provenance + confidence stored on each signal** in the profile (so the DB
   records *how* we know each signal and how sure we are).

---

## 4. Recommended build order

1. **Confidence engine + RE Session** (the spine — unifies everything we already
   produce into A/B/C). Small, high-leverage.
2. **Guided protocol runner + Petrol protocol** (Mode 2) — deterministic, highest
   confidence, and directly seeds the OEM DB. Diesel/EV protocols follow as data.
3. **Auto-RE workspace UI** with the tiered view + confirm flow.
4. **Mode 1 continuous pipeline** wired to the same engine (passive learning while
   logging / on uploaded logs).
5. Feed confirmed signals → profile with provenance; CANMatch then auto-applies on
   the next same-model vehicle (flywheel closes).

**Best way to achieve it:** build the **shared spine first** (confidence + session),
then **Mode 2 (guided)** because controlled stimuli give the cleanest, highest-
confidence labels and the fastest complete profile — and Mode 1 reuses the exact
same engine for passive/upload analysis. One brain, two front doors.
