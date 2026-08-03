# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for uCANdo — bundles the FastAPI server + static web UI into
a self-contained Windows folder (dist/uCANdo/uCANdo.exe). No Python needed on the
target machine. See docs/RELEASE_PACKAGING.md."""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)            # project root (spec lives in packaging/)

# read-only assets bundled next to the code
datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "ucando", "protocols"), os.path.join("ucando", "protocols")),
]
binaries = []
# dynamic / plugin-style imports PyInstaller can't see statically
hiddenimports = [
    "ucando.plugins.builtin_engines",
    "can.interfaces.virtual",                # the dev/virtual bus
    "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
]
hiddenimports += collect_submodules("uvicorn")

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
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="uCANdo",
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="uCANdo")
