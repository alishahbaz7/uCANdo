# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Roadmap status

Full plan & benchmark: `docs/PRODUCT_PLAN.md`. Target: India-first, fleet/telematics-focused CAN workbench. Working **phase-by-phase, one git branch + one merge to `main` per phase**.

| Phase | Theme | Status | Key deliverables |
|---|---|---|---|
| 0 | Foundation rails | ✅ done | `registry.py`, `storage.py`, `config.py`, `contracts.py`, pytest harness, gap fixes |
| 1 | RE supercharge (Pillar B) | ✅ done | `re_engines/read.py` (READ/BFR), `re_engines/diff.py` (sniffer+compare), RE UI, promote-to-DBC |
| 2 | OEM CAN Database (Pillar A) | ✅ done | `oem_db.py` (profiles on `oem_profiles`), fingerprint + CANMatch auto-identify, seed packs, OEM UI, apply-to-viewer |
| 3 | OEM-aware visualization | ✅ done | computed signals + alarms (`derived.py`), LibreCAN correlation (`re_engines/correlate.py`), one-click auto-identify-&-apply (zero-DBC decode) |
| 4 | Automation & simulation (Pillar C) | 🚧 next | rules engine, job scheduler, scripting API, restbus/node sim |
| 5 | Fleet / telematics | ⬜ todo | multi-vehicle registry, export pipeline (Parquet/MQTT), fleet agent |
| 6 | Polish & package | ⬜ todo | workspace UX, full UDS client, packaging |

Update this table at the end of each phase. Tests: `python -m pytest -q`.

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
python -m compileall -q canforge main.py
```

**Tests** (pytest; no hardware needed — integration tests use the in-process virtual bus on a per-test channel):
```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```
Tests live in `tests/`; `tests/conftest.py` holds the virtual-bus harness (`wait_until`, `sender`, `vchannel`, in-memory `storage`). You can also smoke-test the capture path by connecting to the **virtual** bus — `canforge.sim.SyntheticTraffic` feeds it real-looking frames.

## Architecture

CANForge is a hardware-agnostic CAN bus workbench: a **FastAPI backend + WebSocket + static single-page web UI** (no JS build step — plain `web/*.{html,css,js}`). The same app drives three adapters plus a development virtual bus.

### The central invariant: everything talks to the HAL, never to `python-can` directly

`hal.py` defines `CANInterface` (ABC: `send`/`recv`/`close`) and `create_interface(hw, channel, bitrate, fd)`, a factory that maps a hardware key → a `python-can` interface string via the `BACKENDS` table. **No module above the HAL imports `can.Bus`** — they hold a `CANInterface`. This is what makes "one utility, any adapter" work; preserve it when adding modules.

Hardware keys and their backends (`BACKENDS` in `hal.py`):

| key | python-can interface | channel | notes |
|---|---|---|---|
| `virtual` | `virtual` | `"canforge"` (str) | dev; in-process broadcast |
| `neovi` | `neovi` | `1`/`2`… (int) | needs `ics` lib |
| `pcan` | `pcan` | `"PCAN_USBBUS1"` (str) | needs PCAN driver |
| `microchip` | `slcan` | COM port (str) | analyzer flashed with SLCAN firmware |

Channel type is coerced per-backend (`channel_type` in the table), and `fd` is only forwarded to backends with `supports_fd`. The one exception to "no `can.Bus`": `device_enum.py` and `sim.py` use `can`/vendor libs directly, by necessity (enumeration and traffic generation sit *beside* the HAL, not above it).

### Foundation rails (Phase 0)

Four cross-cutting modules added to keep the app extensible without editing core (see `docs/PRODUCT_PLAN.md`):
- `registry.py` — generic `Registry` + the named global registries `RE_ENGINES`, `DECODERS`, `EXPORTERS`, `OEM_PACKS`. New engines/decoders/exporters/OEM packs **self-register** at import; `load_plugins()` auto-imports everything under `canforge/plugins/`. `server.py` calls it once and exposes `/api/plugins`. The `Protocol` classes in `registry.py` are the documented plugin contracts.
- `storage.py` — thread-safe SQLite (`Storage`, WAL, one lock for writes). Schema is a plain list of `CREATE TABLE IF NOT EXISTS` strings — append one to extend. Tables: `oem_profiles` (the India OEM DB + frame `signature` for auto-ID), `vehicles`, `captures`, `jobs`, `settings`.
- `config.py` — `Config` over the `settings` table with `DEFAULTS`; named profiles are namespaced `profile:<name>` keys. `server.py` exposes `/api/config`.
- `contracts.py` — `TypedDict` definitions of the `snapshot()` / `/ws/live` payload, the **single source of truth** for the backend↔`web/app.js` coupling. `check_snapshot()` lets tests assert the producer keeps the contract. Update this + `web/app.js` together when the snapshot shape changes.

### Reverse-engineering engines (Phase 1)

RE is pluggable. `reverse.py` now only does log I/O (`load_log_frames` → the *frames-by-id* shape `{(id,ext): {timestamps, payloads}}`) and dispatches `analyze_log(path, engine=...)` through `RE_ENGINES`. Engines are pure/bus-free and self-register via `canforge/plugins/builtin_engines.py`:
- **`read`** (`re_engines/read.py`) — the default. Bit-flip-rate (BFR) tokenization: finds signal boundaries where BFR drops (one signal's LSB abutting the next's MSB), infers endianness (big-endian from contiguous MSB-first bits; little-endian by counter-fit or smoothness), and classifies each span constant/counter/crc/multi-state/physical. Also `detect_multiplexor`. Output is a **superset** of the legacy shape (keeps `bytes[].{index,kind,entropy}` and `candidates[].{start_bit,length,name,byte_order}` that `web/app.js` reads) plus `kind`/`bfr`/`confidence`/`step`.
- **`basic`** — the original toggle-count finder (`reverse.BasicEngine`), kept for comparison.

`re_engines/diff.py` adds the **state-change sniffer** + **log compare**: `diff_frames(baseline, after)` reports per-ID which bits were constant before but changed after (→ contiguous `event` candidates). `StateSniffer` is the live, guided version — a bus tap registered in `server.py` (`bus.add_tap(sniffer.consume)`), driven by `arm`→`mark`→`result`. RE endpoints: `/api/re/engines`, `/api/re/analyze` (takes `engine`), `/api/re/sniff/{arm,mark,stop,status,result}`, `/api/re/compare`, `/api/re/promote` (seed DBC from any RE id-result, with a `min_confidence` filter).

### OEM CAN Database (Phase 2, Pillar A)

`oem_db.py` — `OemDatabase` over the `oem_profiles` table: CRUD, DBC import/export, and **save-from-DBC-builder** (the RE flywheel). Each profile carries a `dbc` + a frame **signature** (`{id_set, ids[{id,ext,dlc,period_ms}]}`). `fingerprint_frames`/`fingerprint_from_id_stats` build a signature from a log or a live `snapshot()`; `identify_from_signature` scores it against every profile (Jaccard of ID sets + DLC bonus → ranked **CANMatch-style** matches). `seed_builtins()` (called once in `server.py`, idempotent) inserts a decodable **"Sim Vehicle"** profile matching the simulator + draft placeholders for the `TARGET_OEMS`. Endpoints: `/api/oem/profiles`, `/api/oem/profile{,/update,/delete}`, `/api/oem/import`, `/api/oem/from-builder`, `/api/oem/identify` (live), `/api/oem/identify-log`, `/api/oem/apply` (loads a profile's DBC into the Signal Viewer → decode a known vehicle with zero RE). UI: "OEM Database" view (identify, profile list, save-from-builder, apply).

### OEM-aware visualization (Phase 3)

- `derived.py` — `ComputedSignals` (math channels: `sig('MSG.SIGNAL')` + whitelisted math, evaluated in a no-builtins namespace) and `AlarmMonitor` (per-signal min/max with trip/clear state + count). `SignalViewer` owns both: `consume` updates `_latest`, evaluates computed (stored under `COMPUTED.<name>` series), then alarms. Endpoints `/api/signals/{computed,alarms,derived}`; UI panel in the Signal Viewer.
- `re_engines/correlate.py` — **LibreCAN-style** auto-labeling: decodes OBD-II PID ground truth from a log, reconstructs READ candidates, and Pearson-correlates + linear-regresses each candidate against the ground truth to recover **label + scale + offset**. `/api/re/correlate`; UI "Correlate vs OBD" in the RE view; promote carries scale/offset (`seed_from_re` now passes through `scale/offset/unit/byte_order`).
- `/api/oem/auto-apply` — identify the live vehicle and apply the top confident decodable profile to the Signal Viewer in one call (zero-DBC decode); UI "Identify & apply".

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
- `dbc_builder.py` — `DbcModel` keeps plain JSON-able dicts as the source of truth (the UI reads/writes them); cantools is only touched at export/import. **cantools 41.x uses a `conversion` object, not `scale`/`offset` kwargs** — see `_to_cantools_db`.
- `signals.py` — `SignalViewer.consume` is the tap: decodes each frame against a loaded DBC into bounded per-signal `(t, value)` ring buffers. Non-numeric (choice) signals are skipped, not raised.
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
