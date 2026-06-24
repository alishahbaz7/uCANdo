# uCANdo — Unified CAN Workbench

> **India-first, fleet/telematics-focused CAN bus workbench.**
> One tool. Any adapter. Log → Decode → Analyse → Reverse-engineer → Transmit.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.11x-green)](https://fastapi.tiangolo.com/)

---

## What's New — v0.3

| Feature | Details |
|---|---|
| **Frame Decoder** | Upload any `.dbc` → browse every message + signal. Edit per-ID hex payload live → byte view, signal table (Raw / Physical / Unit / DBC description), BusMaster-style 8×8 bit grid with clicked-signal highlighting |
| **Value descriptions** | Enum/choice labels from DBC `VAL_` table shown as green chips alongside numeric physical value |
| **OOR indicator** | Out-of-Range badge (red `OOR`) when physical value exceeds DBC `[min…max]` |
| **Scale-aware formatting** | Physical values formatted to scale's decimal places (capped at 2), e.g. scale=0.1 → `6502.4` not `6502.400000001` |
| **Payload validation** | Hex-only input, auto-strips non-hex chars, `maxlength` = DLC×2, live byte counter |
| **DBC export timestamp** | Export filename is `DDMMYY_HHMMSS.dbc` |
| **Rebrand** | Renamed from CANForge → **uCANdo** |
| **UI polish** | Segoe UI Variable Display font, dark webkit scrollbars, 2-column Frame Decoder split, unified button hierarchy, `#` serial column, tabular numerals |
| **Auto-RE** | CANMatch DB recognition wired into passive log analysis — known vehicles (e.g. Hyundai Aura) auto-decode RPM + Odometer in tier A without ground truth |

---

## Features

### Capture & Replay
- **CAN Logger** — live capture, per-ID stats (count, EMA period, last payload), record `.asc` / `.blf` / `.csv`
- **TX Replay** — load a log file, play / pause / loop / speed control / filter / step-by-step
- **TX Scheduler** — cyclic or one-shot predefined frame transmission

### Decode & Visualise
- **Frame Decoder** *(new in v0.3)* — upload DBC, browse all messages, edit payload per-ID, live byte/bit/signal decode
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

### v0.3 — Frame Decoder + uCANdo rebrand *(current)*
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
