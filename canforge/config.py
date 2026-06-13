"""Application configuration & saved profiles.

A thin layer over :class:`canforge.storage.Storage`'s ``settings`` table. Config
is a flat key→JSON store with sensible defaults; "profiles" are just namespaced
keys (e.g. ``profile:bench-1``) so the same machinery serves both without a new
table. Unknown keys fall back to :data:`DEFAULTS`, so reading config never fails
on a fresh database.
"""

from __future__ import annotations

from typing import Any

from .storage import Storage

DEFAULTS: dict[str, Any] = {
    "default_bitrate": 500_000,
    "default_hw": "virtual",
    "default_channel": "canforge",
    "simulate_virtual": True,
    "ws_push_hz": 5,
    "recent_frames": 250,
    "ui_theme": "dark",
    "auto_identify_vehicle": True,   # fingerprint live bus against the OEM DB on connect
    "log_dir": "",                   # where recordings are saved ("" = server default data/logs)
}


class Config:
    def __init__(self, storage: Storage):
        self._s = storage

    def get(self, key: str, default: Any = None) -> Any:
        sentinel = object()
        val = self._s.get_setting(key, sentinel)
        if val is not sentinel:
            return val
        return DEFAULTS.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._s.set_setting(key, value)

    def all(self) -> dict:
        """Effective config: defaults overlaid with stored overrides."""
        return {**DEFAULTS, **self._s.all_settings()}

    # ----- named profiles (namespaced settings keys) -----------------------
    def save_profile(self, name: str, data: dict) -> None:
        self._s.set_setting(f"profile:{name}", data)

    def load_profile(self, name: str) -> dict:
        return self._s.get_setting(f"profile:{name}", {})

    def list_profiles(self) -> list[str]:
        return [k.split(":", 1)[1] for k in self._s.all_settings() if k.startswith("profile:")]
