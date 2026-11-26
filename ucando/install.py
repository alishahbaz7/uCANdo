"""How this copy of uCANdo is installed — read by the data folder, the updater and the packaging.

A release is the frozen build (PyInstaller). Installed by the launcher it sits in a version folder:

    <install>\\uCANdo.exe                                    the launcher people pin
    <install>\\data\\                                        shared by every version
    <install>\\versions\\uCANdo-v<x.y.z>\\uCANdo-v<x.y.z>.exe  one folder per version

A copy unzipped by hand without that layout (a pre-1.6 ``uCANdo\\uCANdo.exe``) and a run from source
are not launcher installs: their data sits beside the program (or in the repo), and an update opens
the release page instead of installing in place.

Imports nothing heavy: ``channel.py`` reads it before the server is loaded.
"""

from __future__ import annotations

import os
import re
import sys

from . import __version__

APP_NAME = "uCANdo"                  # as copies are named in the usage list and in latest.json
LAUNCHER_EXE = "uCANdo.exe"
VERSIONS_DIR = "versions"
VERSION_FOLDER = re.compile(r"^uCANdo-v(\d+)\.(\d+)\.(\d+)$")

FROZEN = bool(getattr(sys, "frozen", False))

# How the running server was started (``--port``, ``--host``), so a restart into a new version
# serves on the same address. Set by main.py.
SERVE_ARGS: list[str] = []


def release_name(version: str = __version__) -> str:
    """Everything in a release carries this one name: the zip, the version folder, the program."""
    return f"{APP_NAME}-v{version}"


def launcher_root(executable: str | None = None) -> str | None:
    """The install folder when the program runs from ``<install>/versions/uCANdo-v<x>/``, else None."""
    exe = os.path.abspath(executable or sys.executable)
    version_dir = os.path.dirname(exe)
    versions = os.path.dirname(version_dir)
    name = os.path.basename(version_dir)
    if os.path.basename(versions).lower() != VERSIONS_DIR:
        return None
    if not VERSION_FOLDER.match(name):
        return None
    if os.path.splitext(os.path.basename(exe))[0] != name:
        return None
    return os.path.dirname(versions)
