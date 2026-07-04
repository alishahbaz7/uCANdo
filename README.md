# uCANdo — Unified CAN Workbench

> **India-first, fleet/telematics-focused CAN bus workbench.**
> One tool. Any adapter. Log → Decode → Analyse → Reverse-engineer → Transmit.

[![version](https://img.shields.io/badge/release-v1.2.4-brightgreen)](#release-history)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.11x-green)](https://fastapi.tiangolo.com/)

---

## What's New — v1.2 *(current)*

| Feature | Details |
|---|---|
| **Vehicle Spy 3 log import** | New parser (`vspy.py`) reads Intrepid neoVI/Vehicle Spy CSV traces (metadata header + Network Description table + CAN/LIN/J1939-style data rows, short-DLC frames as blank trailing columns) — plugs straight into the existing `load_log_frames()` dispatch, so RE analysis, CANMatch, and OBD-correlate all work on Vehicle Spy logs with no further changes |
| **Signal Viewer: log playback** | Upload a log + DBC and decode the *whole* capture once, then scrub it like a video: play/pause, ±speed, a scrubber bar, and a trailing time-window strip chart — instead of only live-bus decoding |
| **Frame Decoder: load from log** | Trace mode can pull real captured frames (with real timestamps) straight from an uploaded log, instead of only pasted payloads |
| **Log coverage diagnostics** | Decode results split into *decoded*, *unknown to this DBC* (expected — the id just isn't in the file), and *in the DBC but failed to decode* (a real problem, with the actual error) — replaces one opaque "X/Y decoded" count |
| **Decode fix: `allow_truncated`** | A frame with a shorter real DLC than the DBC declares no longer drops the whole frame — recovers every signal that still fits, matching the convention already used in the Frame Decoder |
| **Signal Viewer UX** | Select-all / none for the signal checklist; switching or clearing the DBC now actually empties stale strip charts instead of leaving orphaned ones behind |

---

## What's New — v1.0.0

| Feature | Details |
|---|---|
| **Packaged Windows app** | Self-contained `uCANdo.exe` bundle (PyInstaller) — unzip & double-click, no Python/pip/internet. Runs on `127.0.0.1` only; user data persists in `data\` beside the exe. Build with `.\packaging\build.ps1` → `dist\uCANdo_v<ver>.zip` |
| **CanPlus vehicle-library import** | Converter reads a telematics **`.Config.XML`** (`<CanData>`): decodes the 22-byte `VarDesc` records (VarID, multiplier, divider, offset — verified byte-exact) into a signal dictionary grouped by **frame-cluster**, exportable to DBC/JSON/CSV |
| **RE finding documented** | The CanPlus CAN id + bit position are **obfuscated** (not recoverable from the file — proven across two vehicles); the relationship is established by matching signature signals to an OEM DBC. See `docs/CANPLUS_CONFIG_DECODE.md` |
| **Animated idle hero** | Live `<canvas>` CAN-network on empty Dashboard/Converter/DTC views — glowing bus, streaking packets, hover-to-ripple mesh, quick-start cards |

---

## What's New — v0.4

| Feature | Details |
|---|---|
| **Multi-frame Trace view** | Frame Decoder `Single / Trace` toggle: paste many payloads of one ID → change-highlighted matrix (frames × signals), const/varies summary, collapse-duplicates, raw/physical toggle, and **CSV export** (`Frame No, Message ID, RAW payload`, then one column per parsed signal) |
| **JSON Signature support** | Frame Decoder **and** Converter read the cloud **Signature JSON** (decimal CAN IDs; big-endian `startingBit` is MSB-first sequential = DBC Motorola layout) — bit/byte convention validated against the Ziptron DBC (`DTeInfo=287`, `HVBattSoCPercen=93`) |
| **Converter clean ordering** | Upload preview and downloaded file sort messages by CAN ID and signals by start bit |
| **Vector-style bit layout** | Frame Decoder bit grid shows the whole message layout (all signals coloured) when none selected, LSB→MSB direction arrows, highlighted header row/column, and per-cell sequential bit index |
| **Format Converter** | New segment: **upload → preview → edit / select → download** among **DBC ⇄ JSON ⇄ CSV** in any direction. Source auto-detected; per-signal checkboxes; lossy fields reported. JSON↔DBC bit layout is exact |
| **CSV with both CAN ID bases** | CSV carries `CAN ID (HEX)` **and** `CAN ID (Dec)`; `Motorola`/`Intel` byte order; value tables round-trip DBC ⇄ CSV |
| **Smart single Upload** | One **Upload** button auto-detects `.dbc` vs `.json` (no separate buttons) |
| **MSB/LSB bit highlighting** | Frame Decoder bit grid marks a signal's **MSB (gold)** and **LSB (green)**, endianness-aware, with a legend |
| **Raw as hex** | Frame Decoder Raw column shows the raw bit-pattern in hex (e.g. `0x0128C3`), distinct from the scaled Physical value |
| **Professional iconography** | All emoji replaced with a consistent inline-SVG icon set across sidebar, topbar, and tools |
| **Collapsible sidebar** | Three modes — **locked-open / auto-hide (hover flyout) / locked-rail** — smooth animated, state persisted |
| **Title + description header** | Each view shows a short fixed title with a one-line description |
| **Consistent terminology** | **Upload / Download** everywhere (was Import / Export) |
| **Font fix** | Form controls now inherit the page font (nav/buttons no longer fall back to the browser's default control font) |

---

## Features

### Capture & Replay
- **CAN Logger** — live capture, per-ID stats (count, EMA period, last payload), record `.asc` / `.blf` / `.csv`
- **TX Replay** — load a log file, play / pause / loop / speed control / filter / step-by-step
- **TX Scheduler** — cyclic or one-shot predefined frame transmission

### Decode & Visualise
- **Frame Decoder** *(new in v0.3)* — upload DBC or Signature JSON, browse all messages, edit payload per-ID, live byte/bit/signal decode
- **Converter** *(new in v0.3)* — DBC ⇄ JSON ⇄ CSV in any direction, source auto-detected, lossy fields reported
- **Signal Viewer** — live DBC decode into scrollable strip charts
- **Dashboard** — standard OBD-II PID + J1939 SPN values, no DBC required
- **Protocol Decoder** — OBD-II, UDS with ISO-TP reassembly, J1939

### Reverse Engineering
- **Auto-RE** — confidence-tiered (A/B/C) identification: CANMatch DB lookup + OBD correlation + known-value matching + structural analysis
- **Guided RE** — fuel-type protocol runners (petrol / diesel / EV) with step-by-step stimulus
- **State Sniffer** — arm / mark / compare to find event-driven signals
- **OBD Correlate** — Pearson-fit raw CAN fields against OBD-II ground truth

### OEM & Database
- **OEM Database** — store, fingerprint, and auto-apply vehicle DBC profiles (CANMatch)
- **DBC Builder** — GUI signal editor, import/export `.dbc`, seed from RE candidates

### Diagnostics & Automation
- **DTC Codes** — OBD-II (Mode 03/07/0A), UDS 0x19, J1939 DM1/DM2, scan + clear
- **Rules Engine** — edge-triggered signal expressions → log / transmit / job
- **Job Runner** — periodic or manual jobs (scan, record)
- **Restbus Simulator** — cycle all messages of a DBC to keep an ECU alive
- **Scripting** — Python snippets with `ctx.send` / `ctx.latest` / `ctx.log`

---

## Hardware Adapters

| Adapter | Key | Notes |
|---|---|---|
| Virtual bus (dev) | `virtual` | In-process, no hardware needed |
| Intrepid **Neo VI** | `neovi` | `pip install python-ics`; channel = 1, 2… |
| **PCAN** | `pcan` | Install PEAK PCAN-Basic OS driver; `PCAN_USBBUS1..16` |
| **Microchip / SLCAN** | `microchip` | Flash with SLCAN firmware; appears as COM port |

Hardware-validated with: **Intrepid neoVI FIRE → Hyundai Aura 2023** (HSCAN1 @ 500 kbps). First real OEM profile: EngineRPM (`0x316`/`0x556`) + Odometer (`0x5B0`) confirmed vs OBD + dash.

---

## Quick Start

```powershell
# 1. Create venv (Python 3.12 required for python-ics)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Run
python main.py
# Opens http://127.0.0.1:8765

# 3. Connect → Virtual bus (development) to capture synthetic traffic immediately
```

### Run options
```powershell
python main.py                        # default port 8765, opens browser
python main.py --port 9000 --no-browser
python main.py --reload               # dev auto-reload
```

### Tests
```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

---

## Architecture

```
hal.py           CANInterface ABC + create_interface() factory
device_enum.py   enumerate attached adapters (Neo VI / PCAN / Microchip / virtual)
sim.py           SyntheticTraffic feeder for the virtual bus
logger.py        CanLogger — recv thread, stats, recording, frame taps
replay.py        LogReplayer — timed log playback
reverse.py       analyze_log — entropy / BFR / candidate-signal finder
re_engines/      read (BFR), diff (sniffer/compare), correlate (OBD Pearson)
confidence.py    evidence → A/B/C tier scoring
resession.py     RESession — accumulate evidence, export to DBC
guided.py        GuidedRunner — protocol-driven stimulus/capture
dbc_builder.py   DbcModel — GUI signal editor + cantools DBC I/O
framedecode.py   decode raw hex frames against a DBC with bit-grid cells
jsondecode.py    decode frames against the cloud Signature JSON (self-contained)
convert.py       DBC ⇄ JSON ⇄ CSV converter over one canonical model
signals.py       SignalViewer — live DBC decode → ring buffers → charts
dashboard.py     OBD-II PID + J1939 SPN live values
dtc.py           DtcMonitor — trouble codes (OBD-II / UDS / J1939)
scheduler.py     TxScheduler — cyclic / one-shot TX
protocol.py      ProtocolDecoder — OBD-II / UDS ISO-TP / J1939
oem_db.py        OemDatabase — profiles, fingerprint, CANMatch identify
rules.py         RulesEngine — edge-triggered signal → action
jobs.py          JobRunner — periodic / manual jobs
simulation.py    RestbusSimulator — cycle all DBC messages
scripting.py     run_script — sandboxed Python snippets
bus_manager.py   BusManager — connect / disconnect / taps / send
server.py        FastAPI REST + /ws/live WebSocket
web/             Dark SPA — no JS build step (plain HTML/CSS/JS)
main.py          uvicorn launcher + browser open
```

Everything above the HAL is adapter-independent — modules hold a `CANInterface`, never `can.Bus` directly. Observers register **frame taps**; transmitters call `BusManager.send`.

---

## Release History

### v1.2 — Vehicle Spy log import & offline signal playback *(current)*
- **Vehicle Spy 3 CSV import** (`vspy.py`) — parses Intrepid neoVI/Vehicle Spy captures into the canonical `load_log_frames()` shape; sniffed automatically alongside `.asc`/`.blf`/`.trc`
- **Signal Viewer log playback** — decode a whole log once server-side, then play/pause/scrub/speed it client-side against the loaded DBC; VCR-style transport bar (`sigPbScrub`, `sigPbSpeed`, play/step controls)
- **Log coverage diagnostics** — per-decode breakdown of unknown-id vs decode-error counts (with the actual exception) so gaps in coverage are explainable instead of a single number
- **Decode fix** — `SignalViewer` now passes `allow_truncated=True` (matching `framedecode.py`), recovering signals from frames shorter than the DBC's declared length that were previously dropped whole
- **Signal Viewer UX** — select/deselect-all signal checkboxes; loading or clearing a DBC now clears stale strip-chart selections from the previous DBC
- Tests: 220 passing (`test_vspy.py`, `test_log_signals.py` added)

### v1.0.0 — First packaged release
- **Shareable Windows bundle** — PyInstaller onedir (`packaging/uCANdo.spec` + `build.ps1`); frozen-aware paths (bundled assets read-only, `data/` writable beside the exe). Localhost-only, offline. See `docs/RELEASE_PACKAGING.md`
- **CanPlus `.Config.XML` import** (`canplus.py`) wired into the Converter as a 4th source format; 22-byte `VarDesc` decode verified byte-exact; signals grouped by frame-cluster
- **Reverse-engineering write-up** (`docs/CANPLUS_CONFIG_DECODE.md`): proved the CAN id/bit position are obfuscated in the signature (no CRC fit; clusters span multiple ids across two vehicles) → relationship is via OEM-DBC name matching
- **Animated idle/empty states** — live canvas CAN-network hero with hover-to-ripple mesh + quick-start cards
- Multi-frame **Trace view** + CSV export; Converter sort + hex ids; Vector-style bit layout (carried up from the v0.4.x line)
- Tests: 207 passing

### v0.4 — JSON signatures, Format Converter & UI overhaul
- **Frame Decoder** now reads the cloud **Signature JSON** as well as DBC (one smart Upload button, auto-detected)
- **Converter** segment: DBC ⇄ JSON ⇄ CSV in any direction — upload → preview → edit/select signals → download
- Self-contained JSON decoder (`jsondecode.py`) and format engine (`convert.py`); bit/byte convention validated on real vehicle frames
- CSV carries both `CAN ID (HEX)` and `CAN ID (Dec)`, `Motorola`/`Intel` byte order, and round-trips DBC value tables
- Frame Decoder: MSB/LSB bit-grid highlighting, Raw shown as hex, auto-spaced payload entry
- UI overhaul: inline-SVG icon set (no emoji), collapsible sidebar (open / auto-hide / rail), title+description headers, Upload/Download terminology, form-control font fix
- Endpoints: `/api/decode/json-import`, `/api/convert`, `/api/convert/{parse,export}`

### v0.3 — Frame Decoder + uCANdo rebrand
- Frame Decoder: upload DBC → per-ID editable payload → live byte/signal/bit-grid decode
- DBC value descriptions (enum labels) shown as green chips
- Physical value: scale-aware decimal formatting, OOR badge, choice label
- Payload input: hex-only validation, byte counter, maxlength = DLC×2
- DBC export: timestamped filename (`DDMMYY_HHMMSS.dbc`)
- Rebranded: CANForge → **uCANdo**
- UI: Segoe UI Variable Display, dark scrollbars, 2-col layout, unified buttons

### v0.2 — Auto-RE + Hardware bring-up
- Auto-ID / guided RE: confidence-tiered (A/B/C) signal identification
- CANMatch: fingerprint live/log frame IDs against OEM profile DB
- Guided RE protocols: petrol / diesel / EV step-by-step stimulus (JSON-driven)
- Mode 1: passive log → OBD correlation + known-value + structural analysis
- Hardware validated: neoVI FIRE → Hyundai Aura 2023 (HSCAN1 @ 500 kbps)
- First real OEM profile: EngineRPM + Odometer confirmed vs OBD + dash
- Field tools: `python -m canforge.cli drive` / `sniff` / `guided`
- Driver assistant: `preflight.py` + `drivers.py` auto-diagnosis + installer links

### v0.1 — Full workbench foundation
- CAN Logger, TX Replay, TX Scheduler
- Reverse Engineering (BFR engine + state sniffer + OBD correlate)
- DBC Builder (GUI editor + cantools round-trip)
- Signal Viewer (live decode + strip charts)
- Dashboard (OBD-II PID + J1939 SPN)
- Protocol Decoder (OBD-II / UDS ISO-TP / J1939)
- DTC Codes (OBD-II / UDS 0x19 / J1939 DM1·DM2 + scan/clear)
- Automation: Rules Engine, Job Runner, Restbus Simulator, Scripting
- OEM Database (CRUD, fingerprint, CANMatch, DBC import/export)
- Phase 0 rails: `registry.py`, `storage.py`, `config.py`, `contracts.py`

---

*Target: India-first fleet/telematics CAN workbench. Next: Phase 5 — Fleet agent, multi-vehicle registry, Parquet/MQTT export pipeline.*
