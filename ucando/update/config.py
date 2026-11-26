"""Where uCANdo's releases are published, and how copies find them — one place, read by the app and
by packaging/build_release.py, so the two cannot disagree.

Releases are this repo's own GitHub releases. Copies read the channel without logging in, so the
repo is **public** (the user's choice, 2026-11-26, renaming CAN-utlity to uCANdo). Copies read GitHub's ``releases/latest/download/`` redirect — no API, no rate limit, no
token. A release must be published as *latest*, not as a pre-release, or copies never see it.
"""

from __future__ import annotations

import os

from .. import install
from ..channel import CHANNEL

REPO = os.environ.get("UCANDO_UPDATE_REPO") or "alishahbaz7/uCANdo"
MANIFEST_NAME = "latest.json"
# A run from source checks only when pointed at a test channel on purpose (a local rehearsal:
# UCANDO_UPDATE_MANIFEST_URL=http://127.0.0.1:8000/latest.json); it also redirects a release.
TEST_MANIFEST_URL = os.environ.get("UCANDO_UPDATE_MANIFEST_URL")
MANIFEST_URL = TEST_MANIFEST_URL or f"https://github.com/{REPO}/releases/latest/download/{MANIFEST_NAME}"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


def asset_url(version: str) -> str:
    """Where a release's Windows zip is downloaded from."""
    return f"https://github.com/{REPO}/releases/download/v{version}/{install.release_name(version)}.zip"


def enabled() -> bool:
    return CHANNEL == "release" or bool(TEST_MANIFEST_URL)


def disabled_reason() -> str | None:
    return None if enabled() else "A run from source does not check for updates — only the packaged uCANdo does."
