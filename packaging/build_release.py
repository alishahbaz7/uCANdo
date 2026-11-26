"""Assemble a uCANdo release: the launcher install, its zip, latest.json and the release notes.

    python packaging/build_release.py                    # build what is missing, then package
    python packaging/build_release.py --rebuild          # force a fresh program and launcher build
    python packaging/build_release.py --minimum X.Y.Z    # copies below X.Y.Z must update (critical fixes only)

(``packaging\\build.ps1`` runs this.) Everything carries one name, ``uCANdo-v<version>`` — the zip,
the version folder and the program (``ucando.install.release_name``; ``uCANdo.spec`` uses it too).
The install people pin:

    uCANdo\\uCANdo.exe                                    the launcher (never versioned)
    uCANdo\\README.txt, CHANGELOG.md
    uCANdo\\versions\\uCANdo-v<version>\\uCANdo-v<version>.exe  + _internal\\
    uCANdo\\data\\                                        created on first start, shared by every version

Outputs in dist/:

    uCANdo-v<version>.zip   unzip anywhere the person can write, pin uCANdo.exe; copies that already
                            run a launcher install take it as their update
    uCANdo-v<version>/      the same install, runnable from here (a data/ made by running it survives)
    latest.json             the version, the notes and the zip's SHA-256 — what copies read
    notes.md                the CHANGELOG section, for the release text

Publish both files as a GitHub release of the repo named in ucando/update/config.py (this repo,
public), as the *latest* release, tag ``v<version>`` — never a pre-release, which
copies cannot see. The build never zips or deletes a ``data/`` folder.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ucando import __version__ as VER  # noqa: E402
from ucando.install import LAUNCHER_EXE, release_name  # noqa: E402

RELEASE_NAME = release_name(VER)
EXE_NAME = f"{RELEASE_NAME}.exe"
INSTALL_FOLDER = "uCANdo"              # the zip's top folder: the install people unzip and pin
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PROGRAM_DIR = BUILD / "pyinstaller" / RELEASE_NAME
LAUNCHER = BUILD / "launcher" / LAUNCHER_EXE

GUIDE = """\
uCANdo {ver} - Unified CAN Workbench (Windows 64-bit)
=====================================================

INSTALL
  Unzip this folder somewhere you can write - not Program Files. Pin
  uCANdo.exe to the taskbar or Start: it is the one program to start.

  Coming from uCANdo 1.5 or earlier: unzip this over the old uCANdo folder,
  so its "data" folder (your database, logs and recordings) stays beside
  uCANdo.exe. Or move that "data" folder here before the first start.

RUN IT
  1. Start uCANdo.exe. uCANdo opens in its own window; it also answers at
     http://127.0.0.1:8765 in any browser.
       - If Windows SmartScreen warns (unsigned):  More info -> Run anyway.
  2. The first start asks your name once.
  3. To stop uCANdo, close its console window.

UPDATES
  uCANdo checks for a newer version each time it starts and offers it;
  Update installs it beside this one and restarts into it. Your data stays
  where it is. The way back: hold Shift while starting uCANdo.exe and pick
  an earlier version.

YOUR DATA
  The "data" folder beside uCANdo.exe holds the database, logs, recordings
  and the parse cache - shared by every version. Keep this folder somewhere
  writable.

HARDWARE
  Virtual bus        works out of the box (no adapter needed - good for a tour)
  PCAN               needs the PEAK PCAN-Basic driver installed
  Neo VI (Intrepid)  needs the Intrepid API/driver kit installed
  Microchip/SLCAN    needs the analyzer flashed with SLCAN firmware
  The Dashboard shows a hardware-readiness panel if a driver is missing.

YOUR NAME
  The first start asks your name - to greet you, and to make uCANdo better
  for you. Settings -> Usage reporting shows what is shared: never CAN data,
  logs, DBCs or VINs. Set UCANDO_USAGE=off to switch it off.

COMMAND LINE (optional)
  versions\\{rel}\\{exe} --port 9000 --no-browser
"""


def changelog_section(text: str, version: str) -> str:
    """The CHANGELOG section for ``version`` (``## [x.y.z] — …``), without its heading."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if re.match(rf"^## \[?{re.escape(version)}\]?(\s|$)", ln)), None)
    if start is None:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    body = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        body.append(ln)
    return "\n".join(body).strip()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(*, notes: str, sha: str, size: int, minimum: str | None) -> dict:
    from ucando.update import config

    manifest = {
        "app": "uCANdo",
        "version": VER,
        "published": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "notes": notes,
        "assets": {"windows": {"file": f"{RELEASE_NAME}.zip", "url": config.asset_url(VER),
                               "sha256": sha, "size": size}},
    }
    if minimum:
        manifest["minimumVersion"] = minimum
    return manifest


def _build_program(rebuild: bool) -> None:
    if rebuild or not (PROGRAM_DIR / EXE_NAME).exists():
        print(f"Building {RELEASE_NAME} (one folder) ...")
        subprocess.run([sys.executable, "-m", "PyInstaller", "packaging/uCANdo.spec", "--noconfirm",
                        "--distpath", str(BUILD / "pyinstaller"), "--workpath", str(BUILD / "pyi"),
                        "--log-level", "WARN"], cwd=ROOT, check=True)
    if rebuild or not LAUNCHER.exists():
        print("Building the launcher ...")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(ROOT / "packaging" / "launcher" / "build.ps1")], cwd=ROOT, check=True)


def main() -> int:
    # its messages carry arrows and dashes; a console in the Windows code page cannot encode them
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = sys.argv[1:]
    rebuild = "--rebuild" in args
    minimum = args[args.index("--minimum") + 1] if "--minimum" in args else None

    from ucando import usage_client
    print(f"Packaging {RELEASE_NAME}")
    # A copy released without the usage channel can never be monitored afterwards.
    print(f"  Usage reports go to {usage_client.URL.split('/')[2]}" if usage_client.URL
          else "  WARNING: usage reporting is not set - copies of this release cannot be monitored, ever")

    _build_program(rebuild)
    if not (PROGRAM_DIR / EXE_NAME).exists() or not LAUNCHER.exists():
        print("ERROR: the program or the launcher is missing after the build", file=sys.stderr)
        return 1
    # the bundle must carry what the app reads at runtime — find out here, not on a teammate's PC
    for rel in ("_internal/web/index.html", "_internal/web/app.js", "_internal/web/shell.js",
                "_internal/oem_packs", "_internal/ucando/protocols"):
        if not (PROGRAM_DIR / rel).exists():
            print(f"ERROR: the bundle is missing {rel} - check datas in packaging/uCANdo.spec", file=sys.stderr)
            return 1

    # The staging folder doubles as a runnable install: replace only what the build makes,
    # so a data/ folder created by running it from here survives a rebuild.
    stage = DIST / RELEASE_NAME
    stage.mkdir(parents=True, exist_ok=True)
    for p in stage.iterdir():
        if p.name == "data":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()

    shutil.copy2(LAUNCHER, stage / LAUNCHER_EXE)
    shutil.copytree(PROGRAM_DIR, stage / "versions" / RELEASE_NAME)
    (stage / "README.txt").write_text(GUIDE.format(ver=VER, exe=EXE_NAME, rel=RELEASE_NAME), encoding="utf-8")
    shutil.copy2(ROOT / "CHANGELOG.md", stage / "CHANGELOG.md")

    files = sorted(p for p in stage.rglob("*")
                   if p.is_file() and p.relative_to(stage).parts[0] != "data")
    zpath = DIST / f"{RELEASE_NAME}.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, Path(INSTALL_FOLDER) / p.relative_to(stage))

    notes = changelog_section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), VER)
    if not notes:
        print(f"ERROR: the CHANGELOG section for {VER} is empty - copies would be offered an update "
              "with no notes. Write it, then build again.", file=sys.stderr)
        return 1
    sha, size = sha256_of(zpath), zpath.stat().st_size
    (DIST / "latest.json").write_text(json.dumps(build_manifest(notes=notes, sha=sha, size=size, minimum=minimum),
                                                 indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (DIST / "notes.md").write_text(notes + "\n", encoding="utf-8")

    print(f"\nRelease ready: {zpath}  ({size / (1024 * 1024):.1f} MB, sha256 {sha[:16]}...)")
    print(f"  {DIST / 'latest.json'}\n  {DIST / 'notes.md'}")
    print(f"  {len(files)} files; the program: versions/{RELEASE_NAME}/{EXE_NAME}")
    from ucando.update import config
    print(f"\nPublish: github.com/{config.REPO} -> new release, tag v{VER}, title \"uCANdo {VER}\", "
          f"the text from notes.md, attach {zpath.name} and latest.json, publish as LATEST (not a pre-release).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
