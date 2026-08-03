"""Driver assistant — fetch & launch the official vendor installer on demand.

When :mod:`ucando.preflight` reports a backend's driver is missing, this
downloads the vendor's *official* installer (the URL declared in
``preflight.REQUIREMENTS``) into a local cache — **never** committed to git — and
launches it so the user can complete an elevated install. It reuses an existing
copy (cache or the user's Downloads) instead of re-downloading.

It deliberately does not silently install: OS driver installs require an
interactive, elevated (UAC) step. uCANdo removes the *find-it-yourself* pain;
the admin click stays with the user.

Downloads run on a background thread with progress, so the UI can show a bar for
a large kit (the Intrepid kit is ~1 GB). Stdlib only (``urllib``/``zipfile``).
"""

from __future__ import annotations

import os
import threading
import urllib.request
import zipfile

from .preflight import REQUIREMENTS

_INSTALLER_HINTS = ("setup", "install", "kit", "driver")


class DriverAssistant:
    def __init__(self, cache_dir: str):
        self.cache = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._progress: dict[str, dict] = {}   # hw -> {state, downloaded, total, path, error}

    # ----- helpers ---------------------------------------------------------
    def _installer(self, hw: str) -> dict:
        spec = REQUIREMENTS.get(hw, {}).get("installer")
        if not spec:
            raise ValueError(f"no installer defined for {hw!r}")
        return spec

    def _filename(self, hw: str) -> str:
        return self._installer(hw)["url"].rstrip("/").split("/")[-1] or f"{hw}-installer"

    def cached_path(self, hw: str):
        """Return a usable local copy (cache, then ~/Downloads), or None."""
        name = self._filename(hw)
        candidates = [os.path.join(self.cache, name),
                      os.path.join(os.path.expanduser("~"), "Downloads", name)]
        for p in candidates:
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
        return None

    # ----- download --------------------------------------------------------
    def status(self, hw: str) -> dict:
        with self._lock:
            prog = dict(self._progress.get(hw, {"state": "idle"}))
        spec = REQUIREMENTS.get(hw, {}).get("installer", {})
        prog["cached"] = self.cached_path(hw) is not None
        prog["installer"] = spec
        return prog

    def start_download(self, hw: str) -> dict:
        spec = self._installer(hw)
        if spec.get("kind") == "page":
            # Nothing to download — the vendor only offers a web page.
            return {"state": "page", "url": spec["url"]}
        cached = self.cached_path(hw)
        if cached:
            return {"state": "done", "path": cached, "reused": True}
        with self._lock:
            if self._progress.get(hw, {}).get("state") == "downloading":
                return self._progress[hw]
            self._progress[hw] = {"state": "downloading", "downloaded": 0, "total": 0}
        t = threading.Thread(target=self._download, args=(hw, spec["url"]),
                             name=f"drv-dl-{hw}", daemon=True)
        t.start()
        return self.status(hw)

    def _download(self, hw: str, url: str) -> None:
        dest = os.path.join(self.cache, self._filename(hw))
        part = dest + ".part"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "uCANdo"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as fh:
                total = int(resp.headers.get("Content-Length", 0))
                with self._lock:
                    self._progress[hw].update(total=total)
                done = 0
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    with self._lock:
                        self._progress[hw].update(downloaded=done)
            os.replace(part, dest)
            with self._lock:
                self._progress[hw] = {"state": "done", "downloaded": done,
                                      "total": total, "path": dest}
        except Exception as exc:
            with self._lock:
                self._progress[hw] = {"state": "error", "error": str(exc)}
            try:
                os.path.exists(part) and os.remove(part)
            except OSError:
                pass

    # ----- extract + launch ------------------------------------------------
    def prepare_and_launch(self, hw: str) -> dict:
        spec = self._installer(hw)
        if spec.get("kind") == "page":
            return {"ok": False, "open_url": spec["url"],
                    "note": "Open this page and install the driver manually."}
        path = self.cached_path(hw)
        if not path:
            return {"ok": False, "error": "not downloaded yet — start the download first"}

        installer = path
        if spec.get("kind") == "zip" and path.lower().endswith(".zip"):
            installer = self._extract_installer(hw, path)
            if not installer:
                return {"ok": False, "error": "could not find an installer inside the kit",
                        "extracted_to": os.path.join(self.cache, hw)}

        if os.name == "nt":
            try:
                os.startfile(installer)   # triggers the installer's own UAC prompt
                return {"ok": True, "launched": installer,
                        "note": "Approve the Administrator (UAC) prompt, finish the wizard, then re-plug the device."}
            except Exception as exc:
                return {"ok": False, "error": str(exc), "installer": installer}
        return {"ok": False, "installer": installer,
                "note": "Run this installer manually (non-Windows host)."}

    def _extract_installer(self, hw: str, zip_path: str):
        out = os.path.join(self.cache, hw)
        os.makedirs(out, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            installers = [n for n in names if n.lower().endswith((".exe", ".msi"))]
            # Prefer obvious installer names (setup/install/kit/driver).
            ranked = sorted(installers, key=lambda n: (
                not any(h in n.lower() for h in _INSTALLER_HINTS), len(n)))
            to_extract = ranked or names
            for n in to_extract:
                z.extract(n, out)
            if ranked:
                return os.path.join(out, ranked[0])
        # No exe/msi inside — return the extraction dir so the user can browse.
        return None
