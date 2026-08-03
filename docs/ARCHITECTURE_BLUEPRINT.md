# Utility Architecture Blueprint (reference: uCANdo)

A reusable architecture prompt distilled from uCANdo. Written generically so it applies to
**any** new utility — paste it at the start of a new project to keep the same shape,
patterns, and folder layout. The *why* (advantage) is called out for each choice.
Complements `WAY_WE_WORK.md` (how we collaborate) and `CLAUDE.md` (this codebase).

## 0. The core shape
Build every utility as a **local, single-process web app**: a Python backend that serves a
plain static UI on `127.0.0.1`, with an embedded database and pluggable I/O.
FastAPI + WebSocket backend · plain-JS single-page UI (no build step) · embedded SQLite ·
an abstraction layer over the external world (hardware / API / device) · self-registering
plugins. Runs offline on localhost; packages to one self-contained folder.
**Why:** zero-install for users, no toolchain, trivial to reason about, easy to package.

## 1. Layered architecture + strict acyclic dependency direction
```
io_layer → (enumerate, simulate) → engine/logger → manager → server → web/
                                        ▲
   parsers, decoders, analyzers, transmitters ─┘  (sit *beside*, wired in by server)
```
- Lower layers never import upward. The `server` is the only place that instantiates
  subsystems and wires them together.
**Why:** you can test/replace any layer in isolation; no import cycles; new features attach
at the edges without editing the core.

## 2. Abstraction Layer (the single most important pattern) — "HAL"
Define an **ABC + factory** for whatever external thing you touch (CAN adapter, serial
device, cloud API, DB engine). Map a string key → concrete backend in one table. **Nothing
above this layer imports the concrete/vendor library** — they hold the abstract interface.
Always ship a **virtual/in-memory implementation** of the interface.
**Why / benefit:** "one utility, any backend"; the virtual impl makes the whole app runnable
and testable with no hardware/credentials; swapping vendors is a one-line table change.

## 3. Foundation rails (add these four to every utility, up front)
| Rail | What | Why |
|---|---|---|
| **registry.py** | named registries; plugins **self-register at import**; `load_plugins()` auto-imports everything under `plugins/` | extend without editing core; features are discoverable & listable by the UI |
| **storage.py** | thread-safe embedded SQLite (WAL, one write lock); schema = a plain list of `CREATE TABLE IF NOT EXISTS` | zero-setup persistence; extend by appending one string; concurrency-safe |
| **config.py** | key-value over a `settings` table with `DEFAULTS`; named profiles namespaced `profile:<name>` | user settings persist; no config files to manage |
| **contracts.py** | `TypedDict` of the exact backend↔frontend payload — the **single source of truth** for the wire shape | frontend/back can't drift; a test asserts the producer keeps the contract |

## 4. Backend/server logic
- **One `server` module** creates one of each subsystem, registers observers, exposes REST
  + one `/ws/live` WebSocket. Mount static UI **last** so `/api` and `/ws` win.
- **Observer / "tap" pattern:** one producer (recv/poll thread) fans out to registered
  taps; taps run **outside the lock**. New observers (decoders, viewers) attach as taps —
  no second thread. **Why:** many consumers, one source, no contention.
- **One `snapshot()` read API** the UI polls; the WebSocket pushes **aggregates, not
  per-event** (never flood the UI at high event rates). **Why:** UI stays smooth at load.
- **Threading discipline:** all mutable state under one lock; background threads are daemons
  joined with a timeout. **Why:** clean shutdown, no races.
- **Separate "live view" from "recording"**: in-memory rolling stats always on; writing to
  disk is a separate opt-in stream. **Why:** long runs never blow up memory.

## 5. Data connection & storage
- **Embedded SQLite** (WAL mode, single write-lock) — no server to run, one file to back up.
- **Read-only bundled assets vs writable app data are separate**: resolve paths
  frozen-aware — bundled assets from the package, user data (db, logs, uploads) written
  **next to the executable**. **Why:** the packaged app persists user data correctly.
- Uploads/logs land in a `data/` tree created on startup.

## 6. Canonical-model pattern (for any converter / multi-format tool)
Parse every input format **into one canonical model**, serialize **out of** it. N formats
reuse the same two halves; add `detect_format()` for auto-detection; import-only formats are
fine (parser, no serializer). **Why:** N formats need N parsers + N serializers, not N²
converters; every pair "just works".

## 7. Frontend / UI
- **Plain HTML/CSS/JS, no build step.** One `app.js`, one `style.css`, one `index.html`.
- **Per-view polling of REST + a WebSocket for live data**; switch a single poll timer on
  nav change. **Why:** dead-simple mental model, instant edit→reload, tiny deploy.
- The `contracts.py` payload is what `render()` reads — keep them in lockstep.
- **Inline SVG icon set** (no emoji, no icon font); **theme-aware** (light/dark); custom
  visuals hand-drawn on `<canvas>` (no chart library). **Why:** self-contained, offline,
  crisp, no CDN/CSP issues.
- **Single version source** (`__version__`) injected into asset URLs for cache-busting via a
  templated index route. **Why:** users always get fresh JS/CSS after a release.
- Consistent UX: **Upload/Download** verbs, per-view **title + one-line description** header.

## 8. Cross-cutting
- **Logging + crash capture** from day one: rotating file handler + `sys.excepthook` /
  thread excepthook; third-party at WARNING, your package at INFO. **Why:** field crashes
  are diagnosable.
- **Testing** rides the virtual/in-memory backend — no hardware/network; assert contracts
  and byte-exact parser output. Keep the suite 100% green.
- **Packaging**: PyInstaller **onedir** (not onefile — onefile wipes the writable temp dir);
  frozen-aware paths; localhost-only, offline. **Why:** hand a teammate a zip, they run it.

## 9. File & folder structure
```
<pkg>/                  the app package
  io_layer.py           ABC + factory (the "HAL"): abstract the external world
  <enumerate>.py        discover available backends (guarded — missing lib → [], never raise)
  <simulate>.py         synthetic/virtual data source beside the io_layer
  <engine/logger>.py    the core producer thread + snapshot() + taps
  <manager>.py          the one mutable app-state holder (current backend, taps registry)
  registry.py storage.py config.py contracts.py     <- foundation rails
  plugins/              self-registering plugins (auto-imported)
  parsers/decoders/...  pure, bus-free logic that sits beside and is wired in by server
  server.py             FastAPI: instantiate everything, taps, REST + /ws, static mount last
web/                    index.html · app.js · style.css   (plain, no build)
data/                   runtime: db, logs, uploads   (git-ignored; written next to exe)
packaging/              PyInstaller .spec + build script
docs/                   design/analysis docs (understand-first artifacts)
tests/                  pytest; conftest provides the virtual backend + in-memory storage
main.py                 launcher: serve + open browser; app-object when frozen
```
**Why this layout:** the dependency arrow reads top-to-bottom; rails and plugins are obvious;
`web/` and `data/` are cleanly separable for packaging; docs capture decisions.

---
**One-line summary to keep consistent:** *local web app = FastAPI + plain-JS UI + SQLite,
everything external behind an ABC+factory with a virtual impl, features self-register as
plugins/taps, one canonical model per converter, packaged offline onedir.*
