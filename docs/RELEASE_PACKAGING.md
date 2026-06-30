# Packaging uCANdo for release (Windows)

uCANdo ships as a **self-contained folder** — a teammate just unzips and double-clicks
`uCANdo.exe`. No Python, no `pip`, no internet required.

## Build

```powershell
.\packaging\build.ps1
```

This runs PyInstaller against [`packaging/uCANdo.spec`](../packaging/uCANdo.spec) and produces:

- `dist\uCANdo\uCANdo.exe` — the app (onedir bundle, ~35 MB unpacked)
- `dist\uCANdo_v<version>.zip` — the shareable artifact (~18 MB), with a `README.txt`

The version comes from `canforge.__version__`, so bump that first for a new release.

## What's inside / how paths work

`canforge/server.py` is **frozen-aware**:

| | source run | packaged (`frozen`) |
|---|---|---|
| read-only assets (`web/`, `canforge/protocols/`) | project root | `sys._MEIPASS` (bundled) |
| writable data (`data/` — logs, recordings, `canforge.db`) | project root | **next to `uCANdo.exe`** |

So a packaged user's captures/logs/DB persist in `dist\uCANdo\data\` across runs (the
onefile temp dir would be wiped; onedir keeps them beside the exe).

The spec bundles `web/`, the guided-RE `protocols/*.json`, all of `cantools`, and the
dynamic imports PyInstaller can't see statically (`canforge.plugins.*`, the virtual CAN
backend, uvicorn's loop/protocol submodules).

## Sharing & network note

uCANdo binds to **`127.0.0.1:8765`** (localhost only). It is **not** a network service —
it does not open external ports, call home, or touch the internet, so it cannot affect a
machine's existing internet/network functionality. Hardware CAN access (Neo VI / PCAN /
SLCAN) needs the vendor driver installed separately; the **virtual bus** works out of the box.

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
