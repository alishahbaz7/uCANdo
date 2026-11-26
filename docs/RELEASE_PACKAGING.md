# Packaging uCANdo for release (Windows)

uCANdo ships as a **self-contained folder** — a teammate just unzips and double-clicks
`uCANdo.exe`. No Python, no `pip`, no internet required (usage reports wait until one is
there — see below).

## Build

```powershell
.\packaging\build.ps1
```

This runs PyInstaller against [`packaging/uCANdo.spec`](../packaging/uCANdo.spec) and produces:

- `dist\uCANdo\uCANdo.exe` — the app (onedir bundle, ~35 MB unpacked)
- `dist\uCANdo_v<version>.zip` — the shareable artifact (~18 MB), with a `README.txt`

The version comes from `ucando.__version__`, so bump that first for a new release.

## What's inside / how paths work

`ucando/server.py` is **frozen-aware**:

| | source run | packaged (`frozen`) |
|---|---|---|
| read-only assets (`web/`, `ucando/protocols/`) | project root | `sys._MEIPASS` (bundled) |
| writable data (`data/` — logs, recordings, `ucando.db`) | project root | **next to `uCANdo.exe`** |

So a packaged user's captures/logs/DB persist in `dist\uCANdo\data\` across runs (the
onefile temp dir would be wiped; onedir keeps them beside the exe).

The spec bundles `web/`, the guided-RE `protocols/*.json`, all of `cantools`, and the
dynamic imports PyInstaller can't see statically (`ucando.plugins.*`, the virtual CAN
backend, uvicorn's loop/protocol submodules).

## Sharing & network note

uCANdo binds to **`127.0.0.1:8765`** (localhost only). It is **not** a network service —
it opens no external ports, so it cannot affect a machine's existing network setup. Hardware
CAN access (Neo VI / PCAN / SLCAN) needs the vendor driver installed separately; the
**virtual bus** works out of the box.

**Usage reporting (release builds only, since v1.6.0).** The packaged exe sends a small usage
report to the shared usage server every one of these utilities reports to (user skill
`app-control`; `ucando/usage.py`) — one HTTPS call to `zjudpkovgkavarcjxmmp.supabase.co` about
every 5 minutes, in the background:

| Sent | Never sent |
|---|---|
| the name the person typed once at the first start | CAN frames, IDs, payloads, signal values |
| this computer: Windows login, computer name, Windows version, time zone | DBCs, signature JSON, OEM profiles |
| the uCANdo version and build (`release`) | log files or their names, paths |
| how long it ran, the views opened, errors (type and message) | VINs, adapter serials |
| counts: bus connects by adapter type, recordings, replays started, identifies, decoder loads, conversions, DTC scans | anything a capture contains |

It works offline: reports wait in `data\usage.json` and go when the server can be reached; a
send that fails gives up after 30 s and backs off, so uCANdo never waits for it. The person sees
it all in **Settings → Usage reporting** (name, install ID, last sent, *Send now*).
`UCANDO_USAGE=off` in the environment switches it off on a machine. A run from source does not
report.

## Run options (same as source)

```
uCANdo.exe                      # serve on 127.0.0.1:8765, open browser
uCANdo.exe --port 9000 --no-browser
```

To stop: close the console window.

## Notes / future

- **Code-signing**: the exe is unsigned, so SmartScreen may warn on first run
  (More info → Run anyway). Sign with an org cert for a clean launch.
- A single-file `.exe` is possible (`--onefile`) but starts slower and wipes `data/` on
  exit — onedir is preferred for a tool that records data.
