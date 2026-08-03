"""Wire contracts between backend and UI — one source of truth.

The live snapshot pushed over ``/ws/live`` is consumed key-by-key by
``web/app.js``'s ``render()``. That coupling was previously only a warning in
CLAUDE.md; this module makes the shape explicit so a change in
:meth:`ucando.logger.CanLogger.snapshot` is made in lockstep with the UI.

These :class:`typing.TypedDict` definitions cost nothing at runtime (they are
plain dicts) — they document the contract and let tests assert the producer
keeps to it via :func:`check_snapshot`. If you add a key to ``snapshot()``, add
it here and update ``web/app.js``.
"""

from __future__ import annotations

from typing import Optional, TypedDict


class FrameDict(TypedDict):
    """One captured frame as serialized by ``logger._frame_dict``."""
    ts: float
    id: int
    id_hex: str
    ext: bool
    rtr: bool
    fd: bool
    dlc: int
    channel: str
    data: str            # space-separated upper-hex bytes


class IdStat(TypedDict):
    """Aggregated per-arbitration-ID statistics row."""
    id: int
    id_hex: str
    ext: bool
    count: int
    dlc: int
    data: str
    first_ts: float
    last_ts: float
    period_ms: float


class LoggerSnapshot(TypedDict):
    """The shape returned by ``CanLogger.snapshot()``."""
    running: bool
    total: int
    unique_ids: int
    fps: float
    bus_load_pct: float
    elapsed_s: float
    recording: bool
    record_path: Optional[str]
    record_frames: int
    ids: list[IdStat]
    recent: list[FrameDict]


class ReplayStatus(TypedDict):
    """The shape returned by ``LogReplayer.status()``."""
    state: str
    meta: dict
    cursor: int
    total: int
    sent: int
    cursor_s: float
    speed: float
    loop: bool
    progress: float


class LiveWsPayload(LoggerSnapshot, total=False):
    """What ``/ws/live`` sends each tick: a snapshot plus these extra keys."""
    connected: bool
    replay: ReplayStatus


# The keys the UI depends on existing in every /ws/live payload (even when not
# yet connected, where only `running`/`connected` are present). Used by tests.
SNAPSHOT_KEYS: frozenset[str] = frozenset(LoggerSnapshot.__annotations__)
WS_EXTRA_KEYS: frozenset[str] = frozenset({"connected", "replay"})


def check_snapshot(snapshot: dict) -> list[str]:
    """Return the list of contract keys missing from ``snapshot`` (empty == ok).

    Tests assert this is empty so the producer can't silently drop a key the UI
    reads.
    """
    return sorted(SNAPSHOT_KEYS - set(snapshot))
