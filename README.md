# uCANdo — Unified CAN Workbench

> **India-first, fleet/telematics-focused CAN bus workbench.**
> One tool. Any adapter. Log → Decode → Analyse → Reverse-engineer → Transmit.

[![version](https://img.shields.io/badge/release-v1.6.0-brightgreen)](#release-history)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.11x-green)](https://fastapi.tiangolo.com/)

---

## What's New — v1.6 *(current)*

| Feature | Details |
|---|---|
| **Updates itself** | Pin `uCANdo.exe` (now a small launcher) once: each start checks for a newer version and offers it with its notes; *Update* downloads it, checks its SHA-256, installs it beside the running one and restarts into it. Your `data` stays put; Shift while starting picks an earlier version. Releases are published to a public releases-only repo (`docs/RELEASE_PACKAGING.md`) |
| **The house design** | The look shared by this user's utilities: Supabase's palette and the Inter font (bundled, offline), Auto / Light / Dark, a fixed banner (uCANdo · *Hello, Name* · the page), a resizable rail with *Expanded / Collapsed / Expand on hover*, house dialogs, sentence case, no help text on screen — explanations are hold-tips |
| **Its own window** | `python main.py` / `uCANdo.exe` open uCANdo as an app window, not a browser tab — its own taskbar button with uCANdo's logo (pin it and it starts uCANdo), the title bar following the theme |
| **Release and dev side by side** | The packaged exe on **8765**, a run from source on **8865** (marked *Dev*), separate data folders; a second start just opens a window on the running copy |
| **Settings → Views** | Hide any view you don't use, or preview one held back from this release |
| **TX replay, faster to set up** | Upload several logs at once (a playlist in file-name order), *Remove* logs from the list (never deleted — *Show all* brings them back), *Clear* the source, and *Now sending ‹file› · file k of n* while it plays |
| **Transmit signal: Tiles or Bytes** | What left the machine, two ways. *Tiles*: every signal of the uploaded JSON/DBC as the device's cloud panel shows it — pin the fields your cloud shows and hold the two side by side; a changed value lights up, a silent ID greys, a Patch-forced value says *Forced*. *Bytes*: every transmitted ID with changed bytes lit, an *All / In DBC* filter, and one ID's bit layout — a tile opens straight into it |
| **TX rides out a lost bus** | Unplug the device under test, or let the bus go bus-off, and TX replay no longer stops with an error: it says *Waiting for the bus*, resets the adapter (PCAN `CAN_Reset`, then a reopen), and carries on from the frame it could not send. The outage is reported, never counted as drift; only *Stop* ends the wait. The bus chip shows the adapter's error state (error-warning / error-passive is PCAN's blinking red LED) |
| **Usage reporting** (release builds) | The first start asks your name, to greet you. The packaged exe reports who uses it and how — counts, never CAN data — to the shared usage server; *Settings → Usage reporting* shows exactly what is sent (`docs/RELEASE_PACKAGING.md`) |
| **UI guard rails** | `tests/test_ui.py` holds the design rules; `tools/ui_smoke.py` drives every view in both themes and fails on any page error |

## What's New — v1.4

| Feature | Details |
|---|---|
| **Identify a vehicle from its VIN** | Parse an ISO 3779 VIN into WMI / VDS / VIS and glob-match it against the pack library — identify the car *before* touching CAN (`vin.py`, `/api/oem/identify-vin`) |
| **OEM pack library** | Packs now live at `<Make>/<Model>/<Fuel>_<Year>/`, walked automatically — adding a vehicle is a folder, not a code change. MG (Comet, Commute, Windsor Pro, ZS), Hyundai, Mahindra and Suzuki in tree (`oem_packs/README.md`) |
| **MG Commute EV 2026 decoded** | Tier-A signals confirmed against dash photos — odometer, SoC, range, gear, pack voltage/current, cell voltages — with a checksum model verified on 410/410 frames (`docs/MG_COMMUTE_DECODE.md`) |
| **Signature JSON: hex *or* decimal IDs** | Two exporters exist in the field and `"120"` is ambiguous in both bases, so the base is detected **per file** and reported. A hex-keyed export used to fail outright with `invalid literal for int() with base 10: '000000E1'` |
| **Short frames decode correctly** | Payloads shorter than the assumed length now pad on the **right** — CAN bytes are positional, so byte 0 stays byte 0. Left-padding had silently shifted real short-DLC frames (a DLC-5 odometer read `0.00` instead of `3066.53 km`) |
| **Converter errors that locate the fault** | A JSON with no bit layout names the missing fields; an overlap that blocks DBC export reports the CAN ID and both bit spans instead of two bare signal names |
| **Vehicle Spy 3 log import** | New parser (`vspy.py`) reads Intrepid neoVI/Vehicle Spy CSV traces (metadata header + Network Description table + CAN/LIN/J1939-style data rows, short-DLC frames as blank trailing columns) — plugs straight into the existing `load_log_frames()` dispatch, so RE analysis, CANMatch, and OBD-correlate all work on Vehicle Spy logs with no further changes |
| **Signal Viewer: log playback** | Upload a log + DBC and decode the *whole* capture once, then scrub it like a video: play/pause, ±speed, a scrubber bar, and a time-window view centred on the playhead — instead of only live-bus decoding |
| **Signal table (default view)** | A time × signal matrix, one of three views (Table / Tiles / Chart). Rows are built lazily for the visible window only, with four cell states — blank (not seen yet), fresh, **grey** (held; the message stopped arriving), and **highlighted** (changed on this row) — plus a changes-only filter and sticky header/time column |
| **Tile view** | A stat tile per signal — name on top, the value at the playhead as the hero, min/max underneath — carrying the same four states, with out-of-DBC-range values flagged red |
| **Fold + filter + pin the signal list** | Collapse the list to give the data pane full width, filter a hundreds-of-signals DBC by name, and **pin** the signals you care about so they lead every view (table columns, tiles, charts, exports). Both panes share one height, so they start scrolling together |
| **Transport without the mouse** | Click any table row to seek to that instant; Space play/pause, ←/→ step a row (Shift for ten), Home/End, +/− zoom — inert outside the Signal Viewer and never stealing keys from a text field |
| **Per-signal staleness** | A value greys once it is older than ~3× *that signal's own* period, not once a row carries no fresh frame — so a healthy 100 ms signal on a 10 ms grid stays fresh instead of strobing |
| **Signal summary** | Per-signal const-or-varies, min/max, distinct count, period and sample count, with values outside the DBC's own declared range flagged red and full-scale maxima (255 / 65535 / …) flagged amber — the fast verdict on whether a DBC is right |
| **Unified time zoom** | One control sets time resolution for both views — chart window width and table row interval scale together — with a full-log overview strip above a scrubber that spans only a slice, so precise seeking works on long captures |
| **Signal export** | CSV (values + summary) client-side, or `.xlsx` via the server with the held/changed cell colouring preserved, over the visible window or the whole log |
| **Feature availability** | Views that need a bus are dimmed with the reason while disconnected — still clickable, with an in-view banner and a Connect shortcut — and Computed signals & alarms is removed entirely during playback (and with no DBC loaded), where it would do nothing |
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
# Opens http://127.0.0.1:8865 (a run from source; the packaged uCANdo.exe uses 8765)

# 3. Connect → Virtual bus (development) to capture synthetic traffic immediately
```

### Run options
```powershell
python main.py                        # source run: port 8865, opens browser
python main.py --port 9000 --no-browser
python main.py --reload               # dev auto-reload
```
The packaged release (port **8765**) and a run from source (port **8865**) can be open at the
same time: each keeps its own data folder, and the source copy is marked *Dev* in the banner.
Starting a second copy of the same one just opens the copy that is already running.

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

### v1.4.1 — One name everywhere: **uCANdo** *(current)*
The product was renamed CANForge → uCANdo back in v0.3, but the repository and the Python package never followed, so three names were in play at once. They are now one:

| | Was | Now |
|---|---|---|
| Repository / folder | `CAN-utlity` | `uCANdo` |
| Python package | `canforge/` | `ucando/` |
| CLI | `python -m canforge.cli` | `python -m ucando.cli` |
| Database | `data/canforge.db` | `data/ucando.db` |
| Env var | `CANFORGE_HOME` | `UCANDO_HOME` |

- **Breaking for external scripts only** — anything doing `import canforge` or `python -m canforge.cli` must switch to `ucando`. Nothing inside the app changed behaviour; the package rename went through `git mv`, so file history is intact.
- **Your existing database is adopted automatically.** On first start under the new name, `storage.adopt_legacy_db` copies `data/canforge.db` → `data/ucando.db` via sqlite's backup API — not a file copy, so an uncheckpointed WAL comes across too — and leaves the original in place as a backup. Without this, the rename would have looked like total data loss: a new empty DB beside a perfectly good old one.
- **`CANFORGE_HOME` is still honoured** as a fallback for `UCANDO_HOME`, so existing shortcuts, service definitions and CI configs keep working.
- Tests: 279 passing (3 added for the migration: WAL carry-over, never clobbering an existing DB, no-op with no legacy file)

### v1.4 — VIN identify, OEM pack library & Signature-JSON hardening
- **VIN identification** (`vin.py`) — parse an ISO 3779 VIN into WMI / VDS / VIS, glob-match it against pack patterns, and identify a vehicle *before* touching CAN. `/api/oem/identify-vin`
- **OEM pack library restructured** to `<Make>/<Model>/<Fuel>_<Year>/` with the filename repeating the path (`oem_packs/README.md` documents the rule); `oem_db.iter_packs` walks the tree, so adding a vehicle is a folder, not a code change. Hyundai Aura moved into the new layout; MG (Comet, Commute, Windsor Pro, ZS), Mahindra and Suzuki added
- **MG Commute EV 2026 decoded** (`docs/MG_COMMUTE_DECODE.md`) — Tier-A signals confirmed against dash photos: Odometer (`0x120`, 32-bit ×1/64 km), StateOfCharge, RangeToEmpty, GearSelector, PackVoltage/PackCurrent/CellVoltMax, plus a checksum model verified on 410/410 frames
- **Profiles list click-through** — `/api/oem/profile/{pid}/signals` expands a profile's DBC inline; `/api/oem/prune` drops rows that can neither be applied nor identified against, and repairs those whose signature is merely empty
- **EV charge computed signals** — `/api/signals/computed/ev-charge` seeds charge-power/SoC math channels from a pack size
- **Signature JSON: hex *or* decimal CAN-ID keys.** Two exporters are in the field and `"120"` is ambiguous, so `jsondecode.detect_id_base` decides once per file (a `0x` prefix, a hex letter, or zero-padding anywhere ⇒ hex) and the Converter reports which base it read. Previously a hex-keyed file failed outright with `invalid literal for int() with base 10: '000000E1'`
- **Short payloads now pad right, not left** — CAN payload bytes are positional, so byte 0 must stay byte 0. Left-padding silently shifted real short-DLC frames: MG Commute `0x120` is DLC 5 and its odometer decoded `0.00` instead of the dash-confirmed `3066.53 km`
- **Actionable converter errors** — a JSON carrying no bit layout names the missing fields instead of raising `TypeError`; a DBC export blocked by overlapping signals reports the CAN ID and both bit spans (`0x287 PackCurrent bits 1-16 overlaps PackVoltage3 bits 16-31`)
- Tests: 275 passing

### v1.3 — Signal table, staleness model & validation verdict
- **Time × signal table**, now the Signal Viewer's default view (Table/Chart toggle). Rows are built lazily for the visible window via a forward cursor per column, so cost is (rows × columns) regardless of log length — nothing is materialised
- **Four cell states** — blank (not seen yet) / fresh / grey (held over) / highlighted (changed on this row) — plus changes-only filtering, sticky header and time column, and a playhead row locked in view
- **Per-signal staleness** keyed to each signal's *own* median period (grey at >3×), so slow-but-healthy signals don't strobe on a fine grid
- **Signal summary** — const/varies, min/max, **Range** (max−min; 0 when the signal never moved) and **Unique** (how many different values it took; 1 for a constant), period, samples; out-of-DBC-range flagged red, full-scale maxima amber. `SignalViewer.info()` now carries `minimum`/`maximum`/`length`/`is_signed` to make that comparison possible
- **Tile view** — a third view mode: stat tile per signal (name / hero value at the playhead / min–max footer) sharing the table's four states, out-of-range flagged red
- **Signal list** — foldable to give the data pane full width, with a name filter and per-signal **pin** (pinned signals lead the table columns, tiles, charts and exports); both panes share one height so they scroll together
- **Seek by click + keyboard transport** — click a table row to put the playhead on it; Space / ←→ / Home / End / +− drive playback while reading the table
- **Sticky transport** — the playback bar pins to the top of the view, so scrubbing stays reachable however far the page is scrolled
- **Stable series colour** — a signal's colour now follows the signal, not its position in the current selection, so filtering or deselecting no longer repaints the survivors
- **Centred playhead** in chart mode (see the approach *and* the aftermath of a transition), a full-log overview strip, a window band on the scrubber, and one unified time-zoom driving both views
- **Export** — CSV client-side; `.xlsx` via `/api/signals/export-xlsx` (openpyxl) keeping the held/changed colouring that CSV cannot carry
- **Feature availability** — live-only views dimmed with a stated reason while disconnected (still clickable); Computed signals & alarms hidden outright during playback and with no DBC loaded, since it is inert in both cases
- **Fixes** — a constant signal no longer renders as a line glued to the chart floor (indistinguishable from zero or broken); `[hidden]` now actually hides `.panel` elements, which author `display:flex` had been overriding; **bare `<input>` fields are themed** (the shared rule only matched `input[type=text]`, so every field written without a `type` — the signal filter, the computed/alarm boxes — kept the browser's white default on a dark UI); whole-log max-timestamp no longer spreads a huge array into `Math.max`
- Tests: 225 passing (`test_signal_export.py` added)

### v1.2 — Vehicle Spy log import & offline signal playback
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
- Rebranded: CANForge → **uCANdo** *(the product name; the Python package followed in v1.4.1)*
- UI: Segoe UI Variable Display, dark scrollbars, 2-col layout, unified buttons

### v0.2 — Auto-RE + Hardware bring-up
- Auto-ID / guided RE: confidence-tiered (A/B/C) signal identification
- CANMatch: fingerprint live/log frame IDs against OEM profile DB
- Guided RE protocols: petrol / diesel / EV step-by-step stimulus (JSON-driven)
- Mode 1: passive log → OBD correlation + known-value + structural analysis
- Hardware validated: neoVI FIRE → Hyundai Aura 2023 (HSCAN1 @ 500 kbps)
- First real OEM profile: EngineRPM + Odometer confirmed vs OBD + dash
- Field tools: `python -m ucando.cli drive` / `sniff` / `guided`
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
