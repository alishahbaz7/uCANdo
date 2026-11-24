"""TX playlist — several logs, in order, as one transmit scenario.

A real capture session is not one file. Vehicle Spy chunks a drive into buffer
saves (the MG Windsor "Moving Data" folder is 33 files covering 22 continuous
minutes), and the event captures are named for what was pressed — ``Brake
Padel``, ``Door Lock``, ``Head light``. Both cases want the same thing: play
these files, in this order, this many times.

A :class:`TxItem` is one entry in that list; :func:`build` resolves the list
into a :class:`TxPlan` of :class:`Segment` objects — a loaded
:class:`~ucando.logstore.FrameStore` plus the exact frame indices to transmit —
which :class:`~ucando.replay.TxEngine` walks. Nothing here transmits or opens a
bus; the plan is pure data so it can be saved, shared and diffed.

Two details the vehicle data forces:

* **Gaps.** Consecutive buffer saves share one session clock — file N+1 starts
  where N stopped — so ``gap_before_ms="auto"`` reconstructs the real pause
  between them instead of splicing them into a discontinuity. Between unrelated
  files "auto" resolves to 0, because their timestamps are not comparable.
* **Per-item repeat.** Segments are *referenced*, never copied, so "idle ×1000"
  costs no more memory than "idle ×1" — the engine replays the same index array.
"""

from __future__ import annotations

import os
from array import array
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from . import logstore
from .logstore import FrameStore

#: Largest inferred pause between two files. Beyond this the timestamps are
#: assumed to come from different sessions and are not comparable, so "auto"
#: means "no gap" rather than "wait 40 minutes".
_AUTO_GAP_MAX_S = 300.0

AUTO = "auto"


@dataclass
class TxItem:
    """One entry in the playlist. Plain data — JSON round-trips exactly."""
    path: str
    network: Optional[str] = None          # None = the file's busiest CAN network
    repeat: int = 1                        # passes of this item, 0 = endless
    filter_ids: Optional[list[int]] = None
    skip_tx: bool = True
    trim_start_s: Optional[float] = None   # seconds from this item's first frame
    trim_end_s: Optional[float] = None
    gap_before_ms: Union[float, str] = 0.0   # number, or "auto"
    label: str = ""
    #: Bitrate this log was captured at, when the operator knows it and the file
    #: does not. A ``.trc`` records no bitrate at any version, so the reader
    #: assumes 500 kbit/s; declaring the real value here overrides that and is
    #: what the bus-load estimate and the bitrate-mismatch check then use.
    baud: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path, "network": self.network, "repeat": self.repeat,
            "filter_ids": list(self.filter_ids) if self.filter_ids else None,
            "skip_tx": self.skip_tx, "trim_start_s": self.trim_start_s,
            "trim_end_s": self.trim_end_s, "gap_before_ms": self.gap_before_ms,
            "label": self.label, "baud": self.baud,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TxItem":
        if isinstance(d, str):                       # bare path shorthand
            return cls(path=d)
        gap = d.get("gap_before_ms", 0.0)
        return cls(
            path=d["path"],
            network=d.get("network"),
            repeat=int(d.get("repeat", 1)),
            filter_ids=[int(i) for i in d["filter_ids"]] if d.get("filter_ids") else None,
            skip_tx=bool(d.get("skip_tx", True)),
            trim_start_s=_opt_float(d.get("trim_start_s")),
            trim_end_s=_opt_float(d.get("trim_end_s")),
            gap_before_ms=gap if gap == AUTO else float(gap or 0.0),
            label=d.get("label") or "",
            baud=int(d["baud"]) if d.get("baud") else None,
        )


def _opt_float(v) -> Optional[float]:
    return None if v is None or v == "" else float(v)


@dataclass
class Segment:
    """A resolved item: the frames that will actually go out, and when."""
    item: TxItem
    store: FrameStore
    sel: array
    network: Optional[str]
    label: str
    first_t: float
    last_t: float
    duration_s: float
    gap_s: float = 0.0                     # resolved pause before each pass
    #: The pause actually measured between this item and the previous one, kept
    #: even when :attr:`gap_s` does not reproduce it. On a PCAN event-capture
    #: session the real pauses are minutes long (a human was operating a
    #: control between recordings) and nobody wants a bench run to sit idle for
    #: 35 minutes — but they should be told that is what was skipped.
    real_gap_s: Optional[float] = None
    baud: Optional[int] = None
    baud_source: str = "none"              # "log" | "declared" | "assumed" | "none"
    min_baud: Optional[int] = None         # bitrate floor the file itself proves
    load_pct: Optional[float] = None
    skipped_tx: int = 0

    @property
    def frames(self) -> int:
        return len(self.sel)

    @property
    def passes(self) -> int:
        """Passes of this item within one plan pass (0 = endless -> treat as 1)."""
        return max(1, self.item.repeat)

    @property
    def span_s(self) -> float:
        """Timeline length of one pass of this item, gap included."""
        return self.gap_s + self.duration_s

    def summary(self) -> dict:
        return {
            "path": self.item.path,
            "name": os.path.basename(self.item.path),
            "label": self.label,
            "network": self.network,
            "frames": self.frames,
            "duration_s": round(self.duration_s, 3),
            "gap_s": round(self.gap_s, 3),
            "real_gap_s": round(self.real_gap_s, 3) if self.real_gap_s is not None else None,
            "repeat": self.item.repeat,
            "baud": self.baud,
            "baud_source": self.baud_source,
            "min_baud": self.min_baud,
            "load_pct": self.load_pct,
            "ids": len({self.store.ids[i] for i in self.sel}),
            "trim_start_s": self.item.trim_start_s,
            "trim_end_s": self.item.trim_end_s,
        }


class TxPlan:
    """An ordered, resolved playlist ready for :class:`~ucando.replay.TxEngine`."""

    def __init__(self, segments: list[Segment], warnings: Optional[list[str]] = None,
                 name: str = ""):
        self.segments = segments
        self.warnings = warnings or []
        self.name = name
        # Timeline offset at which each segment's first pass starts, within one
        # plan pass. Precomputed so status() stays O(1) at 5 Hz.
        self.cum_before: list[float] = []
        acc = 0.0
        for seg in segments:
            self.cum_before.append(acc)
            acc += seg.passes * seg.span_s
        self.span_s = acc

    def __len__(self) -> int:
        return len(self.segments)

    @property
    def frames(self) -> int:
        """Frames transmitted in one plan pass."""
        return sum(s.frames * s.passes for s in self.segments)

    def meta(self) -> dict:
        """The shape the UI and CLI read. Single-item plans look exactly like a
        plain single-file load, so nothing downstream needs to know about
        playlists it isn't using."""
        segs = self.segments
        first = segs[0] if segs else None
        ids = sorted({int(s.store.ids[i]) for s in segs for i in s.sel})
        bauds = {s.baud for s in segs if s.baud}
        duration = self.span_s
        frames = self.frames
        return {
            "path": first.item.path if first else "",
            "frames": frames,
            "duration_s": round(duration, 3),
            "ids": ids,
            "channels": list(first.store.networks) if first else [],
            "source": first.store.source if first else "",
            "network": first.network if first else None,
            # The network picker lists the *first* file's buses: a playlist is
            # one vehicle, and select() applies a chosen network to every item.
            "networks": first.store.network_summary() if first else [],
            "total_frames": len(first.store) if first else 0,
            "baud": bauds.pop() if len(bauds) == 1 else None,
            "baud_hint": None if len(bauds) != 1 else next(iter({s.baud for s in segs if s.baud})),
            # Where that bitrate came from, and the floor the files themselves
            # prove. Both travel with it: a bus-load figure and a "reconnect at
            # the right bitrate" warning are only as true as their input, and a
            # replay must never state an assumed number as if the log said it.
            "baud_source": _one_source(segs),
            "min_baud": max([s.min_baud for s in segs if s.min_baud], default=None),
            "load_pct": max([s.load_pct for s in segs if s.load_pct is not None], default=None),
            "fps": round(frames / duration, 1) if duration > 0 else 0.0,
            "skip_tx": first.item.skip_tx if first else True,
            "tx_frames_skipped": sum(s.skipped_tx for s in segs),
            "filter_ids": sorted(first.item.filter_ids) if (first and first.item.filter_ids) else None,
            # playlist view
            "name": self.name,
            "items": [s.summary() for s in segs],
            "item_count": len(segs),
        }

    def to_dict(self) -> dict:
        return {"name": self.name, "items": [s.item.to_dict() for s in self.segments]}


# ---------------------------------------------------------------------------
def build(items: list[Union[TxItem, dict, str]], name: str = "",
          use_cache: bool = True) -> TxPlan:
    """Load every item and resolve it into transmittable segments."""
    resolved = [it if isinstance(it, TxItem) else TxItem.from_dict(it) for it in items]
    if not resolved:
        raise ValueError("playlist is empty")

    segments: list[Segment] = []
    warnings: list[str] = []
    stores: dict[str, FrameStore] = {}
    for item in resolved:
        # One path listed twice (a loop of A,B,A) is parsed once.
        store = stores.get(os.path.abspath(item.path))
        if store is None:
            store = logstore.load(item.path, use_cache=use_cache)
            stores[os.path.abspath(item.path)] = store
        segments.append(_resolve(item, store, warnings))

    # A reader may have things to say about its file that no amount of plan
    # inspection could find — rows it counted but could not transmit, a bitrate
    # it had to assume, an adapter unplugged mid-capture. `warnings` is already
    # the channel the UI reads, so they go there rather than into new plumbing.
    for path in dict.fromkeys(os.path.abspath(i.path) for i in resolved):
        store = stores[path]
        for note in store.notes:
            warnings.append(f"{os.path.basename(store.path)}: {note}")

    _resolve_gaps(segments, warnings)
    _check_consistency(segments, warnings)
    return TxPlan(segments, warnings, name)


def _resolve(item: TxItem, store: FrameStore, warnings: list[str]) -> Segment:
    network = item.network or _busiest(store)
    if item.network and item.network not in store.networks:
        warnings.append(f"{os.path.basename(item.path)}: no network named "
                        f"{item.network!r} — using {_busiest(store)!r}")
        network = _busiest(store)

    sel = store.indices(network, item.filter_ids, skip_tx=item.skip_tx)
    if not len(sel):
        warnings.append(f"{os.path.basename(item.path)}: nothing to transmit "
                        f"on {network} with the current filter")
        return Segment(item, store, sel, network, item.label or _auto_label(item), 0.0, 0.0, 0.0)

    first_t = store.t[sel[0]]
    if item.trim_start_s is not None or item.trim_end_s is not None:
        lo = item.trim_start_s if item.trim_start_s is not None else float("-inf")
        hi = item.trim_end_s if item.trim_end_s is not None else float("inf")
        sel = array("L", [i for i in sel if lo <= (store.t[i] - first_t) <= hi])
        if not len(sel):
            warnings.append(f"{os.path.basename(item.path)}: trim "
                            f"{item.trim_start_s}–{item.trim_end_s}s selects no frames")
            return Segment(item, store, sel, network, item.label or _auto_label(item),
                           first_t, first_t, 0.0)
        first_t = store.t[sel[0]]

    last_t = store.t[sel[-1]]
    net = next((n for n in store.network_summary() if n["name"] == network), {})
    # Precedence: what the operator declared, then what the file recorded, then
    # whatever the reader had to assume. Bus load is recomputed when a
    # declaration overrides an assumption, or it would still be a percentage of
    # the wrong bitrate.
    baud = item.baud or net.get("baud")
    baud_source = "declared" if item.baud else net.get("baud_source", "none")
    min_b = net.get("min_baud")
    load_pct = net.get("load_pct")
    if item.baud and min_b:
        load_pct = round(100.0 * min_b / item.baud, 1)
    if item.baud and min_b and item.baud < min_b:
        warnings.append(f"{os.path.basename(item.path)}: declared {item.baud:,} bit/s but "
                        f"the capture carries {min_b:,} bit/s of traffic — impossible, "
                        f"the real bus is at least that fast")
    return Segment(
        item=item, store=store, sel=sel, network=network,
        label=item.label or _auto_label(item),
        first_t=first_t, last_t=last_t, duration_s=max(0.0, last_t - first_t),
        baud=baud, baud_source=baud_source, min_baud=min_b, load_pct=load_pct,
        skipped_tx=net.get("tx_frames", 0) if item.skip_tx else 0,
    )


def _resolve_gaps(segments: list[Segment], warnings: list[str]) -> None:
    """Turn each item's ``gap_before_ms`` into concrete seconds.

    ``"auto"`` reconstructs the real pause between two chunks of one capture
    session (same folder, one shared clock, the next file starting after this
    one ends). Anything else — different sessions, reordered files — has no
    comparable timebase, so auto means 0.
    """
    for i, seg in enumerate(segments):
        gap = seg.item.gap_before_ms
        if gap != AUTO:
            seg.gap_s = max(0.0, float(gap or 0.0) / 1000.0)
            continue
        if i == 0:
            seg.gap_s = 0.0
            continue
        prev = segments[i - 1]
        same_session = (os.path.dirname(os.path.abspath(prev.item.path))
                        == os.path.dirname(os.path.abspath(seg.item.path)))
        delta = seg.first_t - prev.last_t
        if same_session:
            seg.real_gap_s = delta          # measured, whether or not it is reproduced
        if same_session and 0.0 <= delta <= _AUTO_GAP_MAX_S:
            seg.gap_s = delta
        else:
            seg.gap_s = 0.0
            if same_session and delta < 0:
                warnings.append(
                    f"{os.path.basename(seg.item.path)} overlaps the previous file by "
                    f"{-delta:.1f}s — playing back-to-back instead")
            elif same_session and delta > _AUTO_GAP_MAX_S:
                # Not clamped to the cap: a bench run should not sit idle for
                # half an hour. But the operator has to be told, or "auto" looks
                # like it decided the files were contiguous.
                warnings.append(
                    f"{os.path.basename(seg.item.path)}: real pause before this file was "
                    f"{_hms(delta)} — playing back-to-back instead; set an explicit "
                    f"gap if the pause matters")


def _check_consistency(segments: list[Segment], warnings: list[str]) -> None:
    bauds = {s.baud for s in segments if s.baud}
    if len(bauds) > 1:
        warnings.append("playlist mixes bitrates (" +
                        ", ".join(f"{b:,}" for b in sorted(bauds)) +
                        ") — one bus can only run at one, split the scenario")
    nets = {s.network for s in segments if s.network}
    if len(nets) > 1:
        warnings.append("playlist mixes networks (" + ", ".join(sorted(nets)) +
                        ") — those are separate buses on the vehicle")
    if any(s.item.repeat == 0 for s in segments[:-1]):
        first = next(s for s in segments[:-1] if s.item.repeat == 0)
        warnings.append(f"{os.path.basename(first.item.path)} repeats endlessly — "
                        f"later items will never play")


def _one_source(segs: list[Segment]) -> str:
    """The plan's bitrate provenance — ``"mixed"`` when the items disagree."""
    got = {s.baud_source for s in segs if s.baud}
    if not got:
        return "none"
    return got.pop() if len(got) == 1 else "mixed"


def _hms(seconds: float) -> str:
    """``2129.8`` -> ``'35m30s'`` — a pause between captures is read, not computed."""
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"


def _auto_label(item: TxItem) -> str:
    """Capture filenames are the event names: 'Brake Padel 8-01-2026 3-07-28 pm'."""
    stem = os.path.splitext(os.path.basename(item.path))[0]
    return stem.strip()


def _busiest(store: FrameStore) -> Optional[str]:
    nets = store.network_summary()
    return max(nets, key=lambda n: n["frames"])["name"] if nets else None


# ----- persistence ---------------------------------------------------------
_KEY = "txplan:"


def save(storage, name: str, items: list[Union[TxItem, dict]], ) -> None:
    """Store a scenario under its name (namespaced settings key, like profiles)."""
    payload = [(it if isinstance(it, dict) else it.to_dict()) for it in items]
    storage.set_setting(_KEY + name, {"items": payload})


def load_saved(storage, name: str) -> list[TxItem]:
    data = storage.get_setting(_KEY + name, None)
    if not data:
        raise KeyError(f"no saved scenario named {name!r}")
    return [TxItem.from_dict(d) for d in data.get("items", [])]


def list_saved(storage) -> list[str]:
    return sorted(k[len(_KEY):] for k, v in storage.all_settings().items()
                  if k.startswith(_KEY) and v)


def delete_saved(storage, name: str) -> None:
    # The settings table has no delete API; a falsy value is the tombstone that
    # list_saved() and load_saved() both treat as absent.
    storage.set_setting(_KEY + name, None)
