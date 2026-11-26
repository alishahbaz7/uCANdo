# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for uCANdo — bundles the FastAPI server + static web UI into
a self-contained Windows folder (dist/uCANdo/uCANdo.exe). No Python needed on the
target machine. See docs/RELEASE_PACKAGING.md."""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)            # project root (spec lives in packaging/)
import sys
sys.path.insert(0, ROOT)
from ucando.install import release_name  # noqa: E402
# uCANdo-v<version>: the program the launcher starts from versions/uCANdo-v<version>/ (app-updates)
NAME = release_name()

# read-only assets bundled next to the code
datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "ucando", "protocols"), os.path.join("ucando", "protocols")),
    # server.py seeds the OEM DB from BUNDLE/oem_packs on every start; without
    # this the packaged app ships an empty OEM Database.
    (os.path.join(ROOT, "oem_packs"), "oem_packs"),
]
binaries = []
# dynamic / plugin-style imports PyInstaller can't see statically
hiddenimports = [
    "ucando.plugins.builtin_engines",
    "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
]
hiddenimports += collect_submodules("uvicorn")
# python-can resolves `can.interfaces.<name>` by string at connect time, so no
# backend is statically reachable — a build with only `virtual` fails on a real
# adapter with a bare ImportError. Pull every interface in; the ones whose vendor
# library is absent stay dormant (device_enum guards each one).
hiddenimports += collect_submodules("can")

# cantools ships data + lazy submodules — pull it all in
for pkg in ("cantools",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "PyInstaller", "matplotlib", "pytest"], noarchive=False,
)
pyz = PYZ(a.pure)
# uCANdo's logo on the exe — also what a button pinned from uCANdo's window shows (desktop.py)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME,
          icon=os.path.join(SPECPATH, "ucando.ico"),
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
