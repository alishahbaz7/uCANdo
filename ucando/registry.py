"""Plugin registries — the extension rails for uCANdo.

The product plan calls for new **RE engines**, **protocol decoders**, **exporters**
and **OEM database packs** to be added as *drop-in files*, never by editing core
modules. This module provides one tiny, dependency-free :class:`Registry` and the
named global instances those plugins register into.

A plugin module registers itself at import time::

    from ucando.registry import RE_ENGINES

    @RE_ENGINES.register("read", description="Bit-flip-rate tokenizer (READ)")
    class ReadEngine:
        def analyze(self, frames): ...

and the rest of the app discovers it by name or by iterating the registry — it
never imports the plugin directly. To make a plugin package auto-load, drop it
under ``ucando/plugins/`` and call :func:`load_plugins` once at startup.

The :class:`typing.Protocol` definitions below are the *contracts*: they are not
enforced at runtime (registration accepts any object), but they document exactly
what each plugin kind must provide, so an implementer reads one class, not the
whole codebase.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable, Generic, Iterator, Optional, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


class Registry(Generic[T]):
    """A name → object map with decorator registration and ordered iteration.

    Generic over the kind of thing stored. Insertion order is preserved so the
    UI can present plugins in a stable order. Registration is idempotent-safe:
    re-registering the same name raises unless ``override=True``.
    """

    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, T] = {}
        self._meta: dict[str, dict] = {}

    def register(self, name: str, *, override: bool = False, **meta) -> Callable[[T], T]:
        """Decorator/callable that registers ``obj`` under ``name``.

        Extra keyword args (e.g. ``description=``) are stored as metadata and
        surfaced by :meth:`describe`, so the UI can list plugins without
        instantiating them.
        """
        def _add(obj: T) -> T:
            self.add(name, obj, override=override, **meta)
            return obj
        return _add

    def add(self, name: str, obj: T, *, override: bool = False, **meta) -> T:
        if name in self._items and not override:
            raise ValueError(f"{self.kind} {name!r} already registered")
        self._items[name] = obj
        self._meta[name] = dict(meta)
        return obj

    def get(self, name: str) -> Optional[T]:
        return self._items.get(name)

    def require(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"No {self.kind} named {name!r}. "
                           f"Known: {sorted(self._items)}") from None

    def names(self) -> list[str]:
        return list(self._items)

    def describe(self) -> list[dict]:
        """List registered plugins as ``{name, kind, **meta}`` dicts (for the UI)."""
        return [{"name": n, "kind": self.kind, **self._meta[n]} for n in self._items]

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __iter__(self) -> Iterator[tuple[str, T]]:
        return iter(self._items.items())

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# Plugin contracts (documentation, not enforced at registration time).
# ---------------------------------------------------------------------------
@runtime_checkable
class ReEngine(Protocol):
    """Reverse-engineering engine: turn grouped frames into signal candidates.

    Implementations: READ (bit-flip-rate), LibreCAN (OBD/IMU correlation),
    CANMatch (DB frame-matching). See docs/PRODUCT_PLAN.md Pillar B.
    """
    def analyze(self, frames_by_id: dict, **opts) -> dict: ...


@runtime_checkable
class Decoder(Protocol):
    """Stateless or stateful protocol decoder for a single frame."""
    def decode(self, arb_id: int, data: bytes, is_extended: bool = False) -> dict: ...


@runtime_checkable
class Exporter(Protocol):
    """Export decoded/captured data to an external sink (CSV, Parquet, MQTT…)."""
    name: str
    def export(self, rows, dest: str, **opts) -> dict: ...


@runtime_checkable
class OemPack(Protocol):
    """A loadable OEM database pack contributing vehicle signal definitions.

    Packs are primarily *data* (DBC/JSON), but a pack may expose a loader object
    so it can be discovered and described uniformly alongside code plugins.
    """
    oem: str
    def profiles(self) -> list[dict]: ...


# ---------------------------------------------------------------------------
# The named global registries plugins register into.
# ---------------------------------------------------------------------------
RE_ENGINES: Registry[Any] = Registry("re_engine")
DECODERS: Registry[Any] = Registry("decoder")
EXPORTERS: Registry[Any] = Registry("exporter")
OEM_PACKS: Registry[Any] = Registry("oem_pack")

ALL_REGISTRIES = {
    "re_engine": RE_ENGINES,
    "decoder": DECODERS,
    "exporter": EXPORTERS,
    "oem_pack": OEM_PACKS,
}


def load_plugins(package: str = "ucando.plugins") -> list[str]:
    """Import every submodule of ``package`` so its plugins self-register.

    Returns the list of imported module names. Missing package → empty list
    (plugins are optional). Import errors in one plugin are swallowed per-module
    so a single broken pack never takes the app down.
    """
    try:
        pkg = importlib.import_module(package)
    except ModuleNotFoundError:
        return []
    imported: list[str] = []
    for info in pkgutil.iter_modules(pkg.__path__, prefix=f"{package}."):
        try:
            importlib.import_module(info.name)
            imported.append(info.name)
        except Exception:
            continue
    return imported


def describe_all() -> dict:
    """Every registered plugin across all registries (for an `/api/plugins` view)."""
    return {kind: reg.describe() for kind, reg in ALL_REGISTRIES.items()}
