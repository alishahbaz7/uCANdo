# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Roadmap status

Full plan & benchmark: `docs/PRODUCT_PLAN.md`. **Auto-ID/RE design (current focus): `docs/AUTO_RE_PLAN.md`.** Target: India-first, fleet/telematics-focused CAN workbench. Worked **phase-by-phase, one branch + one merge to `main` per phase**; now on **feature branches per release** (`v0.1`, `v0.2`).

**🚗 Hardware-validated (2026-06-13):** real Intrepid neoVI FIRE → live Hyundai Aura 2023 capture (HSCAN1 @ 500k). Built the **first real OEM profile**: EngineRPM (`0x316`/`0x556`, LE ×0.25, confirmed vs OBD) + Odometer (`0x5B0`, 24-bit LE ×0.1 km, confirmed vs dash). Two RE techniques proven on real data: **OBD correlation** (dynamic signals) + **known-value matching** (static). Field tools `cli drive` / `cli sniff`. See `ucando-neovi-hardware` memory + `oem_packs/`.

| Phase | Theme | Status | Key deliverables |
|---|---|---|---|
| 0 | Foundation rails | ✅ done | `registry.py`, `storage.py`, `config.py`, `contracts.py`, pytest harness |
| 1 | RE supercharge (Pillar B) | ✅ done | `re_engines/read.py` (READ/BFR), `re_engines/diff.py` (sniffer+compare), RE UI |
| 2 | OEM CAN Database (Pillar A) | ✅ done | `oem_db.py`, fingerprint + CANMatch auto-identify, seed packs, OEM UI |
| 3 | OEM-aware visualization | ✅ done | computed signals + alarms (`derived.py`), LibreCAN correlation (`re_engines/correlate.py`) |
| 4 | Automation & simulation (Pillar C) | ✅ done | `rules.py`, `jobs.py`, `simulation.py` (restbus), `scripting.py`, `cli.py` |
| — | **Hardware bring-up + v0.1/v0.2** | ✅ done | neoVI driver-assistant (`preflight.py`/`drivers.py`), sliding-window correlator, `cli drive`/`sniff`, first real Aura profile |
| **AR** | **Auto-ID / guided RE (`docs/AUTO_RE_PLAN.md`)** | ✅ done | `confidence.py` (A/B/C) + `resession.py` (evidence/confirm/export); Mode 1 `populate_from_log`; Mode 2 `guided.py` + `protocols/*.json` + `cli guided`; Auto-RE UI (`/api/autore/*`). Remaining: field validation + provenance polish |
| 5 | Fleet / telematics | ⬜ todo | multi-vehicle registry, export pipeline (Parquet/MQTT), fleet agent |
| 6 | Polish & package | ⬜ todo | workspace UX, full UDS client, packaging |

Update this table at the end of each phase. Tests: `python -m pytest -q`. Use the project **venv** (`.venv`, Python 3.12 with `python-ics`); there are 3.12/3.13/3.14 on this machine — only `.venv` has the hardware lib.

## Commands

**Run the app** (serves the UI at `http://127.0.0.1:8765` and opens the browser):
```powershell
python main.py                       # default
python main.py --port 9000 --no-browser
python main.py --reload              # dev auto-reload (uvicorn)
```

**Install dependencies** — there are two Python installs on this machine (3.12 and 3.14). Pin one with a venv so `python main.py` and the VS Code interpreter never diverge:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Per-hardware extras are intentionally *not* in `requirements.txt`: `pip install python-ics` for Neo VI; PCAN needs the OS-level PEAK PCAN-Basic driver.

**Compile check** after edits:
```powershell
python -m compileall -q ucando main.py
```

**Tests** (pytest; no hardware needed — integration tests use the in-process virtual bus on a per-test channel):
```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```
Tests live in `tests/`; `tests/conftest.py` holds the virtual-bus harness (`wait_until`, `sender`, `vchannel`, in-memory `storage`). It also sets **`UCANDO_HOME`** to a temp dir at import time — `server.py` derives `DATA_DIR` from it, so importing `ucando.server` in a test writes its DB/logs there instead of polluting the real `data/ucando.db` (the same env var relocates app state in production). You can also smoke-test the capture path by connecting to the **virtual** bus — `ucando.sim.SyntheticTraffic` feeds it real-looking frames.

## Architecture

uCANdo is a hardware-agnostic CAN bus workbench: a **FastAPI backend + WebSocket + static single-page web UI** (no JS build step — plain `web/*.{html,css,js}`). The same app drives three adapters plus a development virtual bus.

### The central invariant: everything talks to the HAL, never to `python-can` directly

`hal.py` defines `CANInterface` (ABC: `send`/`recv`/`close`) and `create_interface(hw, channel, bitrate, fd)`, a factory that maps a hardware key → a `python-can` interface string via the `BACKENDS` table. **No module above the HAL imports `can.Bus`** — they hold a `CANInterface`. This is what makes "one utility, any adapter" work; preserve it when adding modules.

Hardware keys and their backends (`BACKENDS` in `hal.py`):

| key | python-can interface | channel | notes |
|---|---|---|---|
| `virtual` | `virtual` | `"ucando"` (str) | dev; in-process broadcast |
| `neovi` | `neovi` | `1`/`2`… (int) | needs `ics` lib |
| `pcan` | `pcan` | `"PCAN_USBBUS1"` (str) | needs PCAN driver |
| `microchip` | `slcan` | COM port (str) | analyzer flashed with SLCAN firmware |

Channel type is coerced per-backend (`channel_type` in the table), and `fd` is only forwarded to backends with `supports_fd`. The one exception to "no `can.Bus`": `device_enum.py` and `sim.py` use `can`/vendor libs directly, by necessity (enumeration and traffic generation sit *beside* the HAL, not above it).

### Foundation rails (Phase 0)

Four cross-cutting modules added to keep the app extensible without editing core (see `docs/PRODUCT_PLAN.md`):
- `registry.py` — generic `Registry` + the named global registries `RE_ENGINES`, `DECODERS`, `EXPORTERS`, `OEM_PACKS`. New engines/decoders/exporters/OEM packs **self-register** at import; `load_plugins()` auto-imports everything under `ucando/plugins/`. `server.py` calls it once and exposes `/api/plugins`. The `Protocol` classes in `registry.py` are the documented plugin contracts.
- `storage.py` — thread-safe SQLite (`Storage`, WAL, one lock for writes). Schema is a plain list of `CREATE TABLE IF NOT EXISTS` strings — append one to extend. Tables: `oem_profiles` (the India OEM DB + frame `signature` for auto-ID), `vehicles`, `captures`, `jobs`, `settings`.
- `config.py` — `Config` over the `settings` table with `DEFAULTS`; named profiles are namespaced `profile:<name>` keys. `server.py` exposes `/api/config`.
- `contracts.py` — `TypedDict` definitions of the `snapshot()` / `/ws/live` payload, the **single source of truth** for the backend↔`web/app.js` coupling. `check_snapshot()` lets tests assert the producer keeps the contract. Update this + `web/app.js` together when the snapshot shape changes.

### Reverse-engineering engines (Phase 1)

RE is pluggable. `reverse.py` now only does log I/O (`load_log_frames` → the *frames-by-id* shape `{(id,ext): {timestamps, payloads}}`) and dispatches `analyze_log(path, engine=...)` through `RE_ENGINES`. Engines are pure/bus-free and self-register via `ucando/plugins/builtin_engines.py`:
- **`read`** (`re_engines/read.py`) — the default. Bit-flip-rate (BFR) tokenization: finds signal boundaries where BFR drops (one signal's LSB abutting the next's MSB), infers endianness (big-endian from contiguous MSB-first bits; little-endian by counter-fit or smoothness), and classifies each span constant/counter/crc/multi-state/physical. Also `detect_multiplexor`. Output is a **superset** of the legacy shape (keeps `bytes[].{index,kind,entropy}` and `candidates[].{start_bit,length,name,byte_order}` that `web/app.js` reads) plus `kind`/`bfr`/`confidence`/`step`.
- **`basic`** — the original toggle-count finder (`reverse.BasicEngine`), kept for comparison.

`re_engines/diff.py` adds the **state-change sniffer** + **log compare**: `diff_frames(baseline, after)` reports per-ID which bits were constant before but changed after (→ contiguous `event` candidates). `StateSniffer` is the live, guided version — a bus tap registered in `server.py` (`bus.add_tap(sniffer.consume)`), driven by `arm`→`mark`→`result`. RE endpoints: `/api/re/engines`, `/api/re/analyze` (takes `engine`), `/api/re/sniff/{arm,mark,stop,status,result}`, `/api/re/compare`, `/api/re/promote` (seed DBC from any RE id-result, with a `min_confidence` filter).

### OEM CAN Database (Phase 2, Pillar A)

`oem_db.py` — `OemDatabase` over the `oem_profiles` table: CRUD, DBC import/export, and **save-from-DBC-builder** (the RE flywheel). Each profile carries a `dbc` + a frame **signature** (`{id_set, ids[{id,ext,dlc,period_ms}]}`). `fingerprint_frames`/`fingerprint_from_id_stats` build a signature from a log or a live `snapshot()`; `identify_from_signature` scores it against every profile (Jaccard of ID sets + DLC bonus → ranked **CANMatch-style** matches). `seed_builtins()` (called once in `server.py`, idempotent) inserts every `oem_packs/` vehicle plus a decodable **"Sim Vehicle"** profile matching the simulator — **only decodable rows are ever created**; an uncovered OEM appears in `TARGET_OEMS` (the UI's coverage list), never as an empty profile. `prune_blank()` runs alongside it at startup (and behind the Profiles panel's "Clean up" button / `/api/oem/prune`): a row with no signature IDs *and* no messages in its DBC can neither be applied nor identified against, so it is deleted; a row whose DBC parses but whose signature is empty is **repaired**, not dropped. `list_profiles` reports **`id_count` (bus fingerprint) vs `msg_count`/`signal_count` (what the DBC decodes)** — they differ on purpose (Windsor: 120 IDs seen, 55 messages decodable), counted by a `BO_ `/`SG_ ` line scan (`_dbc_counts`) rather than a cantools parse so listing every row stays cheap; `year` comes from `year_min/year_max` with a fallback that reads a year out of the profile name (RE-saved rows have no year columns). `profile_signals(pid)` expands one profile's DBC into messages + signals for the list's click-through. Endpoints: `/api/oem/profiles`, `/api/oem/profile{,/update,/delete}`, `/api/oem/profile/{pid}/signals`, `/api/oem/prune`, `/api/oem/import`, `/api/oem/from-builder` (**endpoint only — no UI entry**), `/api/oem/identify` (live), `/api/oem/identify-log`, `/api/oem/apply` (loads a profile's DBC into the Signal Viewer → decode a known vehicle with zero RE). UI: "OEM Database" view = identify + the Profiles list, whose columns are **Make · Model · IDs · Messages · Year · Status**; clicking the **Model** cell expands an inline signal list (fetched on demand, cached in `oemDetail`, styled with the Converter's `.cv-msg`/`.cv-sigtable` classes).

### OEM-aware visualization (Phase 3)

- `derived.py` — `ComputedSignals` (math channels: `sig('MSG.SIGNAL')` + whitelisted math, evaluated in a no-builtins namespace) and `AlarmMonitor` (per-signal min/max with trip/clear state + count). `SignalViewer` owns both: `consume` updates `_latest`, evaluates computed (stored under `COMPUTED.<name>` series), then alarms. Endpoints `/api/signals/{computed,alarms,derived}`; UI panel in the Signal Viewer.
- `re_engines/correlate.py` — **LibreCAN-style** auto-labeling: decodes OBD-II PID ground truth from a log, reconstructs READ candidates, and Pearson-correlates + linear-regresses each candidate against the ground truth to recover **label + scale + offset**. `/api/re/correlate`; UI "Correlate vs OBD" in the RE view; promote carries scale/offset (`seed_from_re` now passes through `scale/offset/unit/byte_order`).
- `/api/oem/auto-apply` — identify the live vehicle and apply the top confident decodable profile to the Signal Viewer in one call (zero-DBC decode); UI "Identify & apply".

### Automation & simulation (Phase 4, Pillar C)

- `rules.py` — `RulesEngine`: edge-triggered `when` expressions (`sig('MSG.SIGNAL')` syntax) → actions (`log`/`transmit`/`job`), with cooldown. Subscribes to `SignalViewer.add_value_subscriber` (called per frame outside the lock); rules persist via the `settings` table. `/api/rules*`.
- `jobs.py` — `JobRunner` over the `jobs` table: `"every:<seconds>"` periodic or manual jobs dispatched by `kind` to **handlers** registered in `server.py` (`scan`, `record`). One daemon loop; `run_now` for manual. `/api/jobs*`.
- `simulation.py` — `RestbusSimulator`: cyclically transmits every message of a cantools DB (from the DBC Builder or an OEM profile) via `bus.send` so an ECU under test sees a full vehicle; per-message overrides via `set_value`. `/api/restbus/*`.
- `scripting.py` — `run_script` executes a snippet in a no-builtins namespace exposing `ctx` (`send`/`latest`/`log`/`sleep`) on a worker thread with a timeout. Internal-tool hardening, not a security boundary. `/api/script/run`.
- `cli.py` — headless `python -m ucando.cli {log,identify,replay}` for fleet agents/CI; routes through the same HAL + subsystems.

### Dependency direction (keep acyclic)

```
hal → (device_enum, sim) → logger → bus_manager → server → web/
                                       ▲
   replay, reverse, dbc_builder, signals, scheduler, protocol ─┘  (all sit beside, wired in by server)
```
- `device_enum.py` — `enumerate_all()` populates the connect dropdown. Every `list_*` is fully guarded: a missing vendor lib/driver returns `[]`, never raises. PCAN has no enumeration API so it *probes* `PCAN_USBBUS1..8`. Microchip is detected by CP210x VID `0x10C4`; non-matching COM ports are listed but flagged "verify".
- `sim.py` — `SyntheticTraffic` opens its *own* virtual `can.Bus` on the same channel and emits four deliberately-distinct signals (sine-ramp `0x100`, monotonic counter `0x200`, high-entropy noise `0x301`, constant heartbeat `0x7DF`) so offline RE has real entropy/variance to find. Uses an LCG, not `random`.
- `logger.py` — `CanLogger` owns one background recv thread bound to a `CANInterface`. Each frame fans out under a lock to: a rolling recent-frames deque, an aggregated per-ID table (count + EMA period estimate + last payload), global stats, and any active recording writer. **Frame taps** (`add_tap`) run *outside* the lock — that's how Signal Viewer / Protocol Decoder observe live traffic without a second recv thread. `snapshot()` is the single read API the UI consumes.
- `replay.py` / `scheduler.py` — transmitters. Neither opens a bus; both take a `send` callable (`BusManager.send`) so they stay adapter-agnostic. Each runs its own daemon thread with event-based pause/stop.
- `reverse.py` — pure-stdlib (`math` only) log analysis. Bit indices are **sequential MSB-first** (bit 0 = byte0/bit7); `dbc_builder.re_candidate_to_signal` converts that to cantools' big-endian start bit.
- `dbc_builder.py` — `DbcModel` keeps plain JSON-able dicts as the source of truth (the UI reads/writes them); cantools is only touched at export/import. **cantools 41.x uses a `conversion` object, not `scale`/`offset` kwargs** — see `_to_cantools_db`. `re_candidate_to_signal` converts a sequential-MSB-first bit index to a cantools big-endian start bit (reused by `convert.py`).
- `framedecode.py` — decode raw hex frames against a cantools DB into the BusMaster-style view: data bytes, per-signal raw/physical/unit/choice/OOR, and the `(byte,bit)` grid cells. `signal_cells`/`signal_msb_lsb` derive cells via the cantools packer (encode all-ones / a single bit) so Intel & Motorola both work without hand-rolled math. `_fmt_physical` does scale-aware decimals. **A payload shorter than the DLC pads on the *right*** (`_normalize`, and the same rule in `jsondecode.decode_frame`) — CAN payload bytes are positional, so byte 0 must stay byte 0; the earlier left-pad ("restore dropped leading zeros") silently shifted real short-DLC frames (MG Commute `0x120` is DLC 5: its odometer decoded 0.00 instead of the dash-confirmed 3066.53 km). Backs the Frame Decoder (`/api/decode/dbc-import`, `/api/decode/frames`). The Frame Decoder UI (`web/app.js`) has two modes: **Single** (one payload → byte view + signal table + Vector-style bit grid) and **Trace** (paste many payloads of one ID → change-highlighted matrix + const/varies summary + collapse-duplicates + CSV export); `/api/decode/frames` already takes a list of frames, so Trace decodes the whole sequence in one call with no backend change.
- `jsondecode.py` — self-contained decoder for the cloud **Signature JSON** (no cantools; the format carries no enums/min-max/units). Convention **validated against the Ziptron DBC** (see `docs/JSON_SIGNATURE_DECODE.md`): CAN-ID keys are **decimal in some exports, hex in others** — `detect_id_base` decides **per file** (a `0x` prefix, a hex letter, or zero-padding anywhere ⇒ the whole file is hex; else decimal), because `"120"` alone is ambiguous; `parse_frame_id`/`message_name`/`signal_list` are shared with `convert.json_to_model` so both readers agree. For **big-endian** (`reverse 0`) `startingBit` is **MSB-first sequential** (bit 0 = byte0 MSB) read MSB-first — equals the DBC Motorola layout, cantools start `= (start//8)*8 + (7 - start%8)`; for **little-endian** (`reverse 1`) it's LSB-first sequential; `signed`=two's complement. Ground truth: Ziptron 0x244 frame `5251 0047 C000 BA56` → `DTeInfo=287`, `HVBattSoCPercen=93`. Output dict shape **matches `framedecode`** so the Frame Decoder UI renders identically for DBC or JSON. `/api/decode/json-import`.
- `canplus.py` — importer for **CanPlus / telematics "vehicle library" configs** (`*.Config.XML`, root `<CanData>`). Decodes the 22-byte `<VarDesc>` records (verified: `b2-3`=VarID, `b8-9`=mult, `b10-11`=div, `b12-13`=offset, `b17-19`=source-frame signature) → canonical model grouped by frame-cluster. CAN id + bit layout are encrypted in the file, so only the two **field-validated** signals (Odometer `0x540`, Range/DTE `0x2A2`) get real layout; the rest are non-overlapping **placeholders** flagged in each signal's comment. Self-registers as a 4th Converter source format (`detect_format` matches `<CanData`); import-only (no serializer). See `docs/CANPLUS_CONFIG_DECODE.md`.
- `convert.py` — the model carries an **`id_base`** so JSON keys are written in the base the data came from: DBC ⇒ **16** (`"00000120"` — a DBC stores `BO_ 288` but the bus reads `0x120`, and cloud keys are hex), JSON ⇒ the detected base, CSV ⇒ **unset/decimal** (it has both id columns, so it cannot claim one; claiming hex would flip a decimal JSON on a CSV round trip). A **DBC hop cannot preserve the base or `evData`** — both are reported. DBC-sourced signals get **`ev_data: 1`** (a DBC has no such field and these are EV packs; it used to emit 0 for every signal), and **duplicate signal names are qualified by their message name**, not their CAN ID (`PackVoltage_HvPower`, not `PackVoltage_287`) because JSON consumers key on `fieldName` while a DBC scopes names per message — the message name says *why* two signals differ, and a DBC already guarantees names are unique within a message so it always disambiguates. `_qualifiers` strips a leading bus tag (`HSC_HvPower` → `HvPower`) detected as *few distinct first segments over many messages* (not "all share one prefix" — this DBC is 54 × `HSC_` + 1 × `MSC_Hvac`), keeps the strip **only if the shortened names stay unique**, and falls back to the hex id when a message has no real name (a JSON source auto-names them `MSG_<id>`). Renaming fires on duplicates *in the model being serialised*, so exporting a subset only renames what collides in that file. **DBC ⇄ JSON ⇄ CSV** converter over one canonical model (DbcModel-shaped dicts). `parse(text)`/`serialize(model,fmt)` + one-shot `convert()`; `detect_format` auto-detects source. Canonical `start_bit` is the JSON convention (MSB-first-seq for BE, LSB-seq for LE); JSON & CSV use it directly, and the **DBC** boundary converts via the self-inverse `(x//8)*8 + (7 - x%8)` for big-endian — exact both ways (no sub-byte ambiguity). CSV carries both `CAN ID (HEX)` & `CAN ID (Dec)`, `Motorola`/`Intel`, value tables. Endpoints `/api/convert` (one-shot) + `/api/convert/{parse,export}` (the upload→edit/select→download workbench).
- `signals.py` — `SignalViewer.consume` is the tap: decodes each frame against a loaded DBC into bounded per-signal `(t, value)` ring buffers. Non-numeric (choice) signals are skipped, not raised. `decode_frames_offline` is the log-playback counterpart (read-only w.r.t. the live buffers). `info()` also returns each signal's `minimum`/`maximum`/`length`/`is_signed` — the Signal Viewer's summary panel flags decoded values that fall outside the DBC's own declared range, the fastest tell for a wrong scale/length/signedness.
- **Signal Viewer front end (`web/app.js`)** — two views over one dataset, toggled Table/Chart with **Table as the default**. Both read the same decoded series, so the table needs no backend. Key invariants: rows are built **lazily for the visible window only** (`sigBuildRows` walks a forward cursor per column into the already-sorted series — never materialise a matrix); a value is **stale/grey when older than ~3× *that signal's own* median period** (`sigBuildMeta`), *not* when a grid row carries no fresh frame — the naive rule makes a healthy 100 ms signal strobe grey on a 10 ms grid; one **zoom** drives both the chart window and the table row interval so "time resolution" means one thing. Chart mode centres the playhead (log) / trails it (live). Export: CSV is client-side, `.xlsx` goes through `/api/signals/export-xlsx` because only Excel can carry the held/changed cell colouring. `LIVE_ONLY_VIEWS` + `applyAvailability()` dim (never disable) bus-dependent views.
- `dashboard.py` — `Dashboard.consume` is a tap that decodes *standardised* parameters (no DBC): `OBD_PIDS` (Mode-01 PID responses) and `J1939_PGNS` (SPN tables, little-endian, with 0xFF.. = not-available). Keeps only the latest value per parameter, grouped by standard; entries older than 3 s are flagged `stale`. Extend by adding table rows — consume/snapshot need no changes. The simulator (`sim._emit_standard`) emits matching OBD-II + J1939 demo frames so the Dashboard populates on the virtual bus.
- `dtc.py` — `DtcMonitor.consume` is a tap decoding trouble codes: OBD-II Mode 03/07/0A (`0x43/0x47/0x4A`, 2-byte → `P/C/B/U`), UDS `0x59` ReadDTCInformation (3-byte DTC + status byte → flag names; records start *after* SID+subfunc+availability-mask), and J1939 DM1/DM2 (`PGN 0xFECA/0xFECB`, 4-byte → SPN/FMI/OC). Dedupes by code with an occurrence (`seen`) counter; >5 s old = `stale`. OBD/UDS need a request, so `/api/dtc/scan` transmits Mode 03/07 + a J1939 DM1 request; J1939 DM1 is broadcast so it appears passively. `/api/dtc/clear` clears only the local list; `/api/dtc/clear-ecu` sends OBD Mode 04 (a real vehicle write — UI confirms first). Demo frames come from `sim._emit_standard`.
- `protocol.py` — stateful `ProtocolDecoder` with ISO-TP reassembly (First/Consecutive frames buffered per ID). 29-bit IDs are decoded as J1939; OBD falls through to UDS when the mode isn't a known OBD mode (handles a `0x7F` NRC on a `0x7E8` ID).
- `bus_manager.py` — **one** `BusManager` instance (held by `server.py`) is the whole app's mutable bus state: current `iface`, its `CanLogger`, the optional `sim` feeder, plus a persistent **tap registry** re-applied to each new logger on connect (so taps survive reconnects) and a `send` passthrough.
- `server.py` — instantiates one of every subsystem, registers `viewer.consume` + `_proto_tap` as bus taps once at import, and exposes the REST control plane + `/ws/live` (pushes `logger.snapshot()` **and** `replayer.status()` at ~5 Hz). Static mount of `web/` is registered **last** so `/api` and `/ws` win.

### Recording vs. live capture

The logger always captures into in-memory stats once connected. **Recording** is separate: `start_recording(fmt, path)` opens a `python-can` writer (`ASCWriter`/`BLFWriter`/`CSVWriter` per the `_WRITERS` map) and streams frames straight to disk under `data/logs/`, so arbitrarily long logs never accumulate in memory. The active writer is fed inside the same locked `_ingest` path.

### Gotchas

- **Two label-layout-style twins don't exist here, but a similar coupling does:** when you change the `snapshot()` shape in `logger.py`, update `web/app.js` `render()` which reads those exact keys.
- **WebSocket pushes aggregates, not per-frame events** — at 290+ fps, per-frame WS would flood the UI. Keep new live data in the snapshot, not in new high-rate socket messages.
- **Threading:** all of `CanLogger`'s mutable state is guarded by `self._lock`; any new read/write of stats must take it. The recv thread is a daemon and joined with a timeout on stop.
- **All seven modules are implemented.** The capture→analyze→transmit loop is closed: Logger records → RE finds candidate signals → DBC Builder emits a `.dbc` → Signal Viewer decodes the live bus → Replay/Scheduler transmit. New work extends this; the per-PID/PGN tables in `protocol.py` and the candidate-signal heuristics in `reverse.py` are the most likely places to deepen.
- **Path arg gotcha:** REST endpoints that take a log/DBC `path` receive it as JSON — Windows backslash paths are invalid JSON escapes. The UI uploads files (multipart → `data/uploads/`) and passes the returned server path, so this only bites hand-rolled `curl` tests; use forward slashes there.
- **The UI is plain JS, polled per-view.** `web/app.js` switches a single `pollTimer` on nav change (signals/scheduler/decoder poll their REST endpoints; logger + replay ride the WebSocket). Strip charts are hand-drawn on `<canvas>` — no chart library.
