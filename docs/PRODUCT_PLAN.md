# CANForge — Product Plan, Benchmark & Roadmap

> Vision: the smartest CAN workbench in the market — an **India-first**, automation-led
> alternative to CANoe / CANalyzer / BusMaster / SavvyCAN, optimized for
> **aftermarket / fleet / telematics** work where you decode many vehicle variants
> with minimal manual effort.

Scoping decisions (locked 2026-06-13):

| Decision | Choice | Consequence |
|---|---|---|
| Primary user | **Aftermarket / fleet / telematics** | RE + multi-variant decode are the crown jewels, not extras |
| OEM DB scope | **Tata, Mahindra, Maruti, MG, Nissan, VW, Honda** + standards (OBD-II/J1939/UDS) first | India CAN database is the moat |
| Licensing | **Internal tool** | License-flexible (GPL OK), no activation/DRM needed |
| Hardware | **Virtual + all adapters equally** | Keep the HAL strict; no single-vendor lock-in |

---

## 1. Competitive benchmark

| Capability | Vector CANoe/CANalyzer | BusMaster | SavvyCAN | **CANForge (target)** |
|---|---|---|---|---|
| Cost | €€€€ (₹10–30L+/seat) | Free (Win-only) | Free, cross-platform | Free / internal |
| Live capture + stats | ✅ best-in-class | ✅ | ✅ | ✅ (have) → ⭐ |
| DBC author/import/export | ✅ (+LDF/ARXML/FIBEX) | ✅ | partial | ✅ (have, DBC) |
| **Automated reverse engineering** | ❌ manual | ❌ | ⚠️ manual sniffer/range views | ⭐ **multi-engine auto-RE** |
| **India OEM signal DB** | ❌ | ❌ | ❌ | ⭐ **built-in, growing** |
| Restbus / node simulation | ✅ (CAPL) | ✅ | ⚠️ inject only | 🎯 planned |
| Scripting / automation | ✅ CAPL + COM | limited | limited | 🎯 Python rules + jobs |
| Diagnostics (UDS/OBD/J1939) | ✅ deep | partial | partial | ✅ (have core) → ⭐ |
| Fleet / multi-vehicle | ❌ (single bench) | ❌ | ❌ | ⭐ **first-class** |
| Web/remote UI | ❌ (desktop) | ❌ | ❌ desktop | ✅ (have, web) |
| Cross-platform | Windows | Windows | Win/Linux/Mac | ✅ (Python) |

**Where the market leaves a gap we can own:**
1. **No tool ships an India-market CAN database.** OpenDBC (300+ models) is US-focused and
   decodes mostly ADAS signals — Tata/Mahindra/Maruti/MG are absent. This is the moat.
2. **No mainstream tool does *automated* RE.** SavvyCAN is the RE reference but is still
   manual (you eyeball the sniffer/range views). Academia solved most of this (READ,
   LibreCAN, CANMatch) — nobody productized it well.
3. **No tool is fleet/telematics-native.** All are single-bench. We can be multi-vehicle from day one.
4. **CANoe is the feature ceiling but is desktop, Windows, single-seat, and very expensive.**
   Our web architecture already gives us remote/multi-user for free.

---

## 2. Strategic pillars (our three "unfair advantages")

### Pillar A — India-first OEM CAN database
A versioned, data-driven signal library keyed by `(OEM, platform, model-year, bus)`.
Decode known vehicles **without any RE**. Every RE session a user completes feeds back into
the DB (with review), so coverage compounds — exactly the OpenDBC flywheel, but for India.

### Pillar B — Automated reverse engineering (multi-engine)
Combine the three proven academic techniques, each as a pluggable RE engine:
- **READ** (bit-flip-rate tokenization + signal classification) — upgrade of our current
  `reverse.py` toggle analysis. Finds signal *boundaries* and *types* automatically.
- **LibreCAN-style correlation** — drive the car while logging OBD-II PIDs (speed, RPM,
  temp) + phone/IMU; linear-regression-correlate unknown bits against ground truth to label
  signals and recover scale/offset automatically.
- **CANMatch-style frame matching** — fingerprint an unknown vehicle's frames against the
  OEM DB; auto-apply matching signal definitions. This is what makes "1000 vehicles, minimal
  effort" possible — most signals come for free, RE only fills the gaps.

### Pillar C — Automation that removes the human, but stays fully manual when wanted
Every workflow has an **auto mode** (one click / scheduled / rule-triggered) *and* a
**manual mode** with full customization. A rules engine ("when SPN 100 < 100 kPa for 3s →
log + alert + run routine") plus a job scheduler removes the operator from routine tasks.

---

## 3. Feature list (by module)

Legend: ✅ have · ⭐ enhance existing · 🎯 new

### 3.1 Capture & Live Analysis
- ✅ Live capture, per-ID table (count/period/last payload), fps, bus-load, rolling recent
- ⭐ **Multi-bus / multi-channel** capture in one session (CANoe parity)
- ⭐ Hardware/software **timestamp accuracy** + drift correction
- 🎯 **Trigger & filter engine** (pre/post-trigger capture, complex filters, "trigger on signal value")
- 🎯 **Bus health**: error frames, bus-off, overload, ACK errors, load over time chart
- 🎯 **Diff / compare** two captures (great for RE: "what changed when I pressed the button?")
- 🎯 Search across capture; bookmarks; mark/annotate frames

### 3.2 Reverse Engineering (Pillar B)
- ✅ Per-bit toggle, per-byte entropy, byte classification, contiguous-bit candidate signals
- ⭐ **READ engine**: proper bit-flip-rate analysis, endianness detection, counter/CRC/physical
  classification, multiplexor detection
- 🎯 **State-change sniffer** (SavvyCAN parity): record baseline, perform an action, auto-highlight
  the bits/IDs that changed (door, indicator, button)
- 🎯 **Range/correlation view**: drive + log OBD ground truth → auto-label speed/RPM/temp with
  recovered scale & offset (LibreCAN)
- 🎯 **DB frame-matching** (CANMatch): auto-suggest signals from the OEM DB for an unknown bus
- 🎯 **Guided RE wizard**: step the operator through actions, capture deltas, propose a DBC, one-click
  promote candidates → DBC → save to OEM DB (closes the flywheel)
- 🎯 **Checksum/counter auto-detect** (per-message rolling counter & CRC algorithm guesser)

### 3.3 OEM CAN Database (Pillar A)
- 🎯 Versioned DB schema keyed by `(oem, platform, model, year_range, bus, speed)`
- 🎯 Seed packs for **Tata, Mahindra, Maruti, MG, Nissan, VW, Honda** (start with standard
  PIDs/PGNs always-on, grow proprietary from RE)
- 🎯 **Auto-identify vehicle**: fingerprint live bus → suggest matching DB profile
- 🎯 Import existing DBC/community packs; export profiles; merge/curate with review queue
- 🎯 **Contribution flywheel**: completed RE sessions → proposed DB entries → reviewed → shipped

### 3.4 Decode & Visualization (OEM-aware)
- ✅ DBC-driven signal decode → strip charts; DBC-free OBD/J1939 dashboard
- ⭐ **OEM-DB-driven dashboard** (no DBC needed for known vehicles) — the headline demo
- ⭐ Richer **live viz**: configurable gauge/chart grid, multi-signal overlay, min/max/avg,
  XY plots, dark/light, full-screen "vehicle dashboard"
- 🎯 **Computed/virtual signals** (math channels: e.g. power = V×I)
- 🎯 Signal **alarms/thresholds** with visual + audible + log actions
- 🎯 Map view (when GPS present) + signal-over-route playback (telematics)

### 3.5 Transmit & Simulation
- ✅ Log replay (timing-accurate, speed, loop, filter, step) + TX scheduler (cyclic/once)
- 🎯 **Restbus simulation**: simulate absent ECUs from the DBC/OEM DB so a single ECU thinks
  it's in a full vehicle (CANoe's killer feature)
- 🎯 **Node/ECU simulation** with reactive logic (respond to requests) via the scripting layer
- 🎯 Interactive **signal transmit** (send by physical value, not raw bytes; auto-encode via DBC)
- 🎯 Sequence/test builder (send A, wait for B, assert C)

### 3.6 Diagnostics
- ✅ OBD-II / UDS (ISO-TP) / J1939 decode; DTC monitor; scan; clear-ECU
- ⭐ Full **UDS client**: sessions, security access, ReadDataByIdentifier browser, routine control
- 🎯 **Guided diagnostic flows** for service techs (one-click "full vehicle health scan" report)
- 🎯 DTC **decode DB** per OEM (P/C/B/U + manufacturer-specific descriptions)
- 🎯 Multi-frame (ISO-TP) DTC list reassembly (noted gap in `dtc.py`)
- 🎯 Freeze-frame, readiness monitors, Mode 06 test results

### 3.7 Automation & Scripting (Pillar C)
- 🎯 **Rules engine**: condition (signal/DTC/event) → action (log, alert, transmit, run job)
- 🎯 **Job scheduler**: scheduled/triggered capture, scan, export, report
- 🎯 **Python scripting API** (our CAPL equivalent) — safe sandbox, event hooks, the HAL exposed
- 🎯 **Headless / CLI mode** for CI, fleet agents, and unattended logging
- 🎯 Report generation (PDF/HTML) — scan results, RE findings, health reports

### 3.8 Fleet / Telematics
- 🎯 **Multi-vehicle session model** (vehicle registry, per-vehicle profile + history)
- 🎯 Export pipeline: Parquet/CSV/InfluxDB/MQTT for downstream analytics
- 🎯 Lightweight **fleet agent** (headless logger that streams decoded signals up)
- 🎯 Aggregate fleet dashboard (later)

### 3.9 UI/UX
- ⭐ Modernize the web UI: dockable/configurable **workspace layouts**, saved views
- 🎯 **Command palette** (Ctrl-K) — every action keyboard-reachable
- 🎯 Onboarding + "connect → auto-identify → decode" happy path in <60s
- 🎯 Localization-ready (English first); responsive for tablet use in a vehicle
- 🎯 Accessibility + keyboard-first; undo/redo in DBC editor

### 3.10 Platform & Architecture
- 🎯 **Plugin registry** for: HAL backends, RE engines, decoders, exporters, OEM DB packs
- 🎯 Config & profiles (per-vehicle, per-user) persisted; project files
- 🎯 Test suite (unit + virtual-bus integration) — currently none
- 🎯 Packaging (PyInstaller/MSIX) + versioned releases
- 🎯 Persistence layer (SQLite) for captures index, OEM DB, vehicles, jobs

---

## 4. Architecture evolution (scalable + token-efficient)

The current architecture is already strong: a strict HAL, the **tap** pattern, a single
`BusManager`, and excellent per-module docstrings. We extend it without breaking the core
invariant (*everything talks to the HAL, never `can.Bus`*).

**Scalability moves**
1. **Registry/plugin pattern everywhere.** New OEM DB, RE engine, decoder, or exporter =
   *drop in a file / data pack*, not edit core. Mirrors today's `BACKENDS` table idea.
2. **Data-driven, not code-driven.** Decoders & OEM signals live in data (JSON/SQLite/DBC),
   loaded at runtime. Adding a vehicle ≠ writing Python. (Today's `OBD_PIDS`/`J1939_PGNS`
   tables are the seed of this.)
3. **Persistence layer (SQLite)** for the OEM DB, vehicle registry, capture index, jobs.
4. **Stable contracts**: one documented schema for `snapshot()` and the WS payload; the UI
   reads only documented keys. (Already a CLAUDE.md gotcha — formalize it.)
5. **Split the frontend per view** as it grows (today's single `app.js` won't scale) — one
   module per workspace panel, shared API client.

**Token-efficiency moves** (so any AI agent — including future-us — works cheaply):
- Keep **one subsystem per file** with a top docstring stating its contract (already the norm).
- Keep `CLAUDE.md` as the **map**; add a short `docs/` per pillar so an agent reads the doc,
  not the whole module tree.
- **Data over code**: an agent adds a vehicle by editing a data file it can find in one grep,
  never by tracing call graphs.
- **Pure, testable cores** (like `reverse.py`) — easy to reason about in isolation, no bus needed.
- Stable, named contracts mean an agent changes one place, not "find every reader."

```
hal → (device_enum, sim) → logger → bus_manager → server → web/
                                       ▲
  plugins:  re_engines/*  oem_db/*  decoders/*  exporters/*  rules/  scripting/
  persistence:  sqlite (oem_db, vehicles, captures, jobs)
```

---

## 5. Roadmap (phased)

Each phase ships something usable. Phases are ordered to put the **moat (India DB + auto-RE)**
early, because that's the differentiator for the fleet/telematics user.

### Phase 0 — Foundation hardening *(small, do first)*
- Test suite (pytest) + virtual-bus integration harness; `compileall` in CI
- SQLite persistence layer + config/profiles scaffolding
- Plugin/registry scaffolding (RE engines, decoders, exporters, OEM packs)
- Fix known gaps: ISO-TP multi-frame DTC reassembly; WS `bus.logger` race; stale comment in `sim.py`
- Formalize the `snapshot()`/WS contract in one schema module

### Phase 1 — Reverse-engineering supercharge *(Pillar B core)* — ✅ DONE
- ✅ READ engine (BFR tokenization, endianness, counter/CRC/physical classification, mux detect) — `re_engines/read.py`
- ✅ State-change sniffer + capture diff/compare — `re_engines/diff.py`
- ✅ Guided RE wizard → one-click promote candidates to DBC (`/api/re/sniff/*`, `/api/re/promote`) + RE UI (engine selector, sniffer, compare, confidence chips)
- ✅ Counter/CRC auto-detect (in READ classification)
- _Deferred to later:_ LibreCAN OBD/IMU correlation engine moved to Phase 3; CANMatch frame-matching is Phase 2.

### Phase 2 — OEM CAN Database framework *(Pillar A core)*
- Versioned DB schema + storage; import/export; review/merge queue
- Vehicle auto-identify (fingerprint) + CANMatch-style frame matching
- Seed: standards always-on; begin Tata/Mahindra/Maruti/MG/Nissan/VW/Honda packs from RE
- Flywheel: RE session → proposed DB entry → reviewed → shipped

### Phase 3 — OEM-aware visualization *(the demo that sells it)*
- OEM-DB-driven dashboard (decode a known vehicle with **zero** DBC/RE)
- Configurable gauge/chart workspace, computed signals, alarms/thresholds
- LibreCAN correlation engine (OBD/IMU ground-truth auto-labeling with scale/offset)

### Phase 4 — Automation & simulation *(Pillar C)*
- Rules engine + job scheduler + report generation
- Python scripting API (sandboxed) — CAPL equivalent
- Restbus + node/ECU simulation; interactive physical-value transmit
- Headless/CLI mode

### Phase 5 — Fleet / telematics
- Multi-vehicle registry + per-vehicle profiles/history
- Export pipeline (Parquet/MQTT/InfluxDB) + lightweight fleet agent
- Map view + route playback

### Phase 6 — Polish & package
- Workspace layouts, command palette, onboarding, accessibility
- Full UDS client + guided diagnostic flows + OEM DTC DB
- Packaging + versioned releases

---

## 6. Recommended first move

**Phase 0 + the READ engine (start of Phase 1).** It's low-risk, immediately upgrades the
feature we already have (`reverse.py`), needs no hardware (testable on the virtual bus), and
lays the registry + persistence rails that every later pillar rides on.

## Sources
- [Vector CANoe — Testing/Automation](https://www.vector.com/gb/en/products/products-a-z/software/canoe/testing/) · [CANalyzer](https://www.vector.com/int/en/products/products-a-z/software/canalyzer/)
- [BUSMASTER (RBEI/ETAS)](https://github.com/rbei-etas/busmaster)
- [SavvyCAN](https://github.com/collin80/SavvyCAN) · [SavvyCAN for RE (CSS Electronics)](https://www.csselectronics.com/pages/can-bus-interface-savvycan)
- [comma.ai OpenDBC](https://github.com/commaai/opendbc) · [Supported cars (CARS.md)](https://github.com/commaai/opendbc/blob/master/docs/CARS.md)
- [READ / LibreCAN: Automated CAN Message Translator](https://www.researchgate.net/publication/337090721_LibreCAN_Automated_CAN_Message_Translator)
- [CANMatch: Frame-matching RE](https://orbilu.uni.lu/bitstream/10993/48502/1/FINAL%20VERSION.pdf)
</content>
</invoke>
