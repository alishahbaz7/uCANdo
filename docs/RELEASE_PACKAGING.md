# Packaging uCANdo for release (Windows)

uCANdo ships as a **self-contained folder** — a teammate unzips it and pins `uCANdo.exe`.
No Python, no `pip`, no internet required (usage reports and the update check wait until one
is there — see below). **Since v1.6.0 it updates itself** (user skill `app-updates`): pin it
once, and every later version arrives as an offer inside the app.

## Build

```powershell
.\packaging\build.ps1              # build what is missing, then package
.\packaging\build.ps1 --rebuild    # a fresh program and launcher build
```

`build.ps1` runs [`packaging/build_release.py`](../packaging/build_release.py), which builds the
program with PyInstaller ([`packaging/uCANdo.spec`](../packaging/uCANdo.spec)) and the launcher
(`packaging/launcher/`: C#, built by the compiler that ships with Windows — nothing to install),
then writes to `dist\`:

| File | What it is |
|---|---|
| `uCANdo-v<version>.zip` | the shareable install (~19 MB) — unzip, pin `uCANdo.exe` |
| `latest.json` | the version, the notes and the zip's SHA-256: what running copies read |
| `notes.md` | this version's `CHANGELOG.md` section: the release text, and the offer's notes |
| `uCANdo-v<version>\` | the same install, runnable from here (a `data\` made by running it survives rebuilds) |

The version comes from `ucando.__version__`, so bump that first, and write its `CHANGELOG.md`
section — the build refuses an empty one, because a copy would be offered an update with no notes.

## What's inside / how paths work

```
uCANdo\uCANdo.exe                                       the launcher: pinned, never versioned (32 KB)
uCANdo\README.txt, CHANGELOG.md
uCANdo\versions\uCANdo-v<version>\uCANdo-v<version>.exe  + _internal\  (the PyInstaller one-folder build)
uCANdo\data\                                            created at the first start, shared by every version
```

The launcher starts the newest complete version folder and exits; **Shift** while starting it
picks an earlier one (the way back). `ucando/channel.py` puts `data\` **beside the launcher**
(`ucando/install.py` `launcher_root`), so an update never moves or copies it; a pre-1.6 copy
unzipped by hand keeps `data\` beside its exe. Coming from 1.5 or earlier: unzip 1.6 **over** the
old folder, so the old `data\` is already in the right place.

| | source run | packaged (`frozen`) |
|---|---|---|
| read-only assets (`web/`, `ucando/protocols/`) | project root | `sys._MEIPASS` (bundled) |
| writable data (`data/` — logs, recordings, `ucando.db`) | project root | **beside the launcher `uCANdo.exe`** |

## Updates and publishing a release

Copies read `https://github.com/alishahbaz7/uCANdo/releases/latest/download/latest.json`
— GitHub's redirect, no API, no token, no rate limit (`ucando/update/config.py`). A copy cannot log
in, so the repo is **public** (the user's choice, 2026-11-26, when CAN-utlity became uCANdo).
Never commit customer or bench material: it lives in the git-ignored `docs/private/`, and device
logs never enter the repo at all.

On start a release copy checks the channel (60 s at most, whatever the network does), offers a
newer version once per run — after the first-start name — with its notes and what the restart
will stop (a TX replay, a recording, the connected bus), and *Later* leaves an **Update** chip in
the banner. *Update* downloads into `versions\.download`, **installs nothing unless the SHA-256
matches `latest.json`**, unpacks to `uCANdo-v<x>.partial`, renames it into place, and restarts
through the launcher; the page follows and reloads on the new version. A failure anywhere leaves
the running version as it was and is said only in Settings → Updates. The next start keeps the
running version, the newest and the one before, and removes the rest. Each step is reported as a
usage event (`update_offered`, `update_installed`, `update_failed`, …).

To publish (only on the user's word — a published release reaches every copy):

1. `.\packaging\build.ps1 --rebuild` → `dist\uCANdo-v<version>.zip`, `latest.json`, `notes.md`.
2. github.com/alishahbaz7/uCANdo → *Releases* → *Draft a new release* → tag `v<version>`, title
   `uCANdo <version>`, the text from `notes.md`, attach the zip **and** `latest.json`.
3. Publish it as the **latest** release — never a pre-release, which copies cannot see.
4. Watch a copy of the previous version offer it, install it and restart into it.

`--minimum X.Y.Z` makes copies below that version update before anything else (critical fixes
only: it removes *Later*). A local rehearsal needs no publishing: serve a folder holding a newer
build's zip and a `latest.json` (its `url` may be just the file name) with `python -m http.server`,
and start the older install with `UCANDO_UPDATE_MANIFEST_URL=http://127.0.0.1:8000/latest.json`.

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
