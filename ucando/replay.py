"""TX Replay — mimic a vehicle by transmitting a recorded log onto the bus.

Loads a log through :mod:`ucando.logstore` (so Vehicle Spy 3 / neoVI CSVs work
alongside every ``python-can`` format), then a background thread re-transmits
one network's frames preserving their original inter-frame timing, scaled by a
speed factor. Supports pause/resume, single-frame stepping, ID filtering, and
**once / N passes / endless** repeat.

The replayer never opens its own bus — it transmits through a ``send`` callable
supplied by the caller (``BusManager.send``), keeping it adapter agnostic like
everything above the HAL.

Pacing
------
Real captures are fast: an MG Windsor HS CAN capture runs ~1 870 frames/s, a
mean gap of **535 µs**. The obvious loop — ``send(); sleep(gap)`` — cannot play
that back. On Windows a sub-millisecond sleep returns after ~1–15 ms, so every
gap inflates and the log crawls; worse, sleeping *after* doing the work adds the
send cost to every gap, so error accumulates over the whole file.

So this engine schedules on **absolute deadlines** against one clock anchor
(``_epoch``), and each wake-up sends *every frame now due* as a burst before
sleeping to the next deadline. Timing error therefore cannot accumulate — a
late wake-up is absorbed by the next burst instead of shifting all later
frames — and no busy-wait is needed. What the OS clock cannot deliver shows up
as **jitter within a ~1 ms window** rather than as drift, and the engine reports
it (``health.max_late_ms``, ``late_pct``) instead of hiding it. The bus itself
re-serialises a burst at line rate, so receivers see correct frame order and
near-correct spacing.

``timeBeginPeriod(1)`` is requested for the duration of playback so those 1 ms
waits are actually 1 ms on Windows.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Callable, Optional

import can

from . import txproject
from .txproject import TxPlan

#: Frames sent per scheduler wake-up before the loop re-checks pause/stop.
_MAX_BURST = 512

#: A frame later than this past its deadline counts as "late" in health stats.
_LATE_S = 0.005

#: Cumulative lag past which playback is no longer real-time. One thread and one
#: adapter have a throughput ceiling (~30k frames/s on the virtual bus here), so
#: a large speed multiplier can demand more than the machine can deliver.
_BEHIND_S = 0.25

#: Consecutive send failures that mean the bus is gone (no ACK / bus-off /
#: unplugged adapter) rather than one unlucky frame — stop instead of hammering.
_MAX_CONSEC_ERRORS = 32

_DEFAULT_TICK = 0.001


@contextlib.contextmanager
def _timer_resolution(ms: int = 1):
    """Raise the Windows system timer resolution for the duration of playback.

    Without this the default ~15.6 ms tick makes millisecond waits useless.
    No-op (and never fatal) on other platforms.
    """
    winmm = None
    if sys.platform == "win32":
        try:
            import ctypes
            winmm = ctypes.WinDLL("winmm")
            winmm.timeBeginPeriod(ms)
        except Exception:
            winmm = None
    try:
        yield
    finally:
        if winmm is not None:
            try:
                winmm.timeEndPeriod(ms)
            except Exception:
                pass


def _blank_health() -> dict:
    return {"sent": 0, "errors": 0, "late": 0, "late_sum": 0.0, "max_late": 0.0,
            "bursts": 0, "burst_max": 0}


class TxEngine:
    """Deadline-scheduled log transmitter."""

    def __init__(self):
        self._lock = threading.Lock()
        self._plan: Optional[TxPlan] = None
        self._meta: dict = {}
        self._thread: Optional[threading.Thread] = None
        self._state = "empty"              # empty | ready | playing | paused | done | error
        self._error = ""
        self._item = 0                     # index into self._plan.segments
        self._item_pass = 0                # completed passes of the current item
        self._cursor = 0                   # index into the current segment's sel
        self._speed = 1.0
        self._tick = _DEFAULT_TICK
        self._passes = 1                   # 0 = endless
        self._pass_no = 0
        self._network: Optional[str] = None
        self._filter: Optional[set[int]] = None
        self._skip_tx = True
        self._sent = 0
        self._health = _blank_health()
        self._consec_errors = 0
        self._epoch = 0.0                  # perf_counter anchor for the current pass
        self._base = 0.0                   # log timestamp that _epoch corresponds to
        self._play_started = 0.0
        self._paused_total = 0.0
        self._elapsed_frozen: Optional[float] = None
        self._expected_frozen: Optional[float] = None
        # Drift is measured per speed segment: log time played at 5× costs a
        # fifth of the wall clock, so one "log_time / current_speed" division
        # would rewrite history every time the speed knob moves.
        self._expected_wall = 0.0          # wall seconds owed by finished speed segments
        self._speed_seg_log = 0.0          # timeline position when the speed last changed
        self._pause_evt = threading.Event()
        self._stop_evt = threading.Event()
        # Optional FramePatcher: live signal overrides + loop-seam continuity.
        # Read (never mutated) by the worker, so no lock is needed for the swap.
        self._patcher = None

    # ----- loading ---------------------------------------------------------
    def load(self, path: str, network: Optional[str] = None) -> dict:
        """Parse one log and select a network to transmit.

        A single file is just a one-item playlist, so everything below — repeat,
        gaps, health — works the same whether you loaded one log or thirty.
        Defaults to the network carrying the most frames: a Vehicle Spy file
        holds several physically separate buses and only one can go out of a
        single-channel adapter.
        """
        return self.set_plan([txproject.TxItem(path=path, network=network)])

    def set_plan(self, items, name: str = "") -> dict:
        """Install a playlist (list of :class:`~ucando.txproject.TxItem`/dicts)."""
        plan = txproject.build(items, name=name)
        with self._lock:
            if self._state == "playing":
                raise RuntimeError("Stop playback before changing the playlist")
            self._install_locked(plan)
        return self.meta()

    def select(self, network: Optional[str] = None, filter_ids: Optional[list[int]] = None,
               skip_tx: Optional[bool] = None) -> dict:
        """Re-target every item in the playlist — network and/or ID filter.

        Applies to all items on purpose: a playlist is one vehicle on one bus,
        and the parse cache means rebuilding is cheap.
        """
        with self._lock:
            if self._plan is None:
                raise RuntimeError("No log loaded")
            if self._state == "playing":
                raise RuntimeError("Stop playback before changing the selection")
            items = []
            for seg in self._plan.segments:
                item = seg.item
                items.append(txproject.TxItem(
                    path=item.path,
                    network=network or item.network,
                    repeat=item.repeat,
                    filter_ids=(list(filter_ids) if filter_ids else None)
                               if filter_ids is not None else item.filter_ids,
                    skip_tx=item.skip_tx if skip_tx is None else bool(skip_tx),
                    trim_start_s=item.trim_start_s, trim_end_s=item.trim_end_s,
                    gap_before_ms=item.gap_before_ms, label=item.label))
            name = self._plan.name
        plan = txproject.build(items, name=name)
        with self._lock:
            self._install_locked(plan)
        return self.meta()

    def _install_locked(self, plan: TxPlan) -> None:
        self._plan = plan
        self._item = 0
        self._item_pass = 0
        self._cursor = 0
        self._sent = 0
        self._pass_no = 0
        self._health = _blank_health()
        self._error = ""
        self._meta = plan.meta()
        self._state = "ready" if plan.frames else "empty"

    def meta(self) -> dict:
        with self._lock:
            return dict(self._meta)

    def warnings(self) -> list[str]:
        with self._lock:
            return list(self._plan.warnings) if self._plan else []

    def plan(self) -> Optional[TxPlan]:
        with self._lock:
            return self._plan

    def set_patcher(self, patcher) -> None:
        """Install (or clear with ``None``) a :class:`~ucando.txpatch.FramePatcher`.

        Safe to call while transmitting — the worker reads the attribute once per
        frame, so an override takes effect on the next frame out.
        """
        self._patcher = patcher

    # ----- current position helpers (call under the lock) -------------------
    def _seg(self):
        segs = self._plan.segments if self._plan else []
        return segs[self._item] if 0 <= self._item < len(segs) else None

    # ----- playback control ------------------------------------------------
    def play(self, send: Callable[[can.Message], None], speed: float = 1.0,
             loop: bool = False, filter_ids: Optional[list[int]] = None,
             repeat: Optional[int] = None, tick: float = _DEFAULT_TICK) -> None:
        """Start (or resume) transmitting.

        *repeat* is the number of passes: ``1`` once, ``n`` a limited count,
        ``0`` endless. ``loop=True`` is the legacy spelling of ``repeat=0``.
        """
        with self._lock:
            if self._plan is None or not self._plan.frames:
                raise RuntimeError("No log loaded")
            if self._state == "playing":
                return
        if filter_ids is not None:
            self.select(filter_ids=filter_ids)     # rebuilds the plan; parse cache keeps it cheap
        with self._lock:
            self._speed = max(0.01, float(speed))
            self._tick = max(0.0002, float(tick))
            self._passes = 0 if loop else max(0, int(repeat if repeat is not None else 1))
            if self._state in ("done", "error") or self._cursor >= self._seg_frames_locked():
                self._item = self._item_pass = self._cursor = 0
            self._pass_no = 0
            self._sent = 0
            self._health = _blank_health()
            self._consec_errors = 0
            self._error = ""
            self._state = "playing"
            self._play_started = time.perf_counter()
            self._paused_total = 0.0
            self._elapsed_frozen = None
            self._expected_frozen = None
            self._expected_wall = 0.0
            self._rebase_locked()
            self._speed_seg_log = self._log_position_locked()
            self._stop_evt.clear()
            self._pause_evt.set()          # not paused
        self._thread = threading.Thread(
            target=self._run, args=(send,), name="tx-replay", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        with self._lock:
            if self._state == "playing":
                self._state = "paused"
                self._pause_evt.clear()

    def resume(self) -> None:
        with self._lock:
            if self._state == "paused":
                self._state = "playing"
                self._pause_evt.set()      # the worker re-anchors its clock on wake

    def stop(self) -> None:
        self._stop_evt.set()
        self._pause_evt.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        with self._lock:
            self._freeze_locked()
            if self._state != "error":
                self._state = "ready" if (self._plan and self._plan.frames) else "empty"
            self._item = self._item_pass = self._cursor = 0
            self._pass_no = 0

    def set_speed(self, speed: float) -> None:
        with self._lock:
            self._close_speed_segment_locked()   # bank what the old speed owed
            self._speed = max(0.01, float(speed))
            self._rebase_locked()                # keep the deadline map continuous

    def step(self, send: Callable[[can.Message], None]) -> dict:
        """Send exactly one frame and advance, crossing into the next item."""
        with self._lock:
            if self._state == "playing":
                raise RuntimeError("Pause before stepping")
            while True:
                seg = self._seg()
                if seg is None:
                    self._state = "done"
                    return {"sent": False, "cursor": self._cursor}
                if self._cursor < seg.frames:
                    break
                if not self._advance_locked():
                    return {"sent": False, "cursor": self._cursor}
            idx = seg.sel[self._cursor]
            self._cursor += 1
            msg = self._message(seg.store, idx)
        send(msg)
        with self._lock:
            self._sent += 1
            self._health["sent"] += 1
        return {"sent": True, "cursor": self._cursor, "item": self._item}

    # ----- position & clock bookkeeping ------------------------------------
    def _seg_frames_locked(self) -> int:
        seg = self._seg()
        return seg.frames if seg else 0

    def _log_position_locked(self) -> float:
        """Position on the plan timeline, in log seconds, across passes.

        The timeline is ``sum(item.repeat × (gap + duration))`` per plan pass,
        so a playlist behaves like one long log — which is what lets drift,
        progress and the deadline clock stay a single concept.
        """
        plan = self._plan
        if plan is None or not plan.segments:
            return 0.0
        if self._state == "done":
            # Every pass is already counted in _pass_no. Adding the parked
            # cursor's in-item offset on top would double-count the last pass.
            return self._pass_no * plan.span_s
        item = min(self._item, len(plan.segments) - 1)
        seg = plan.segments[item]
        in_seg = 0.0
        if self._cursor and len(seg.sel):
            cur = min(self._cursor, seg.frames - 1)
            in_seg = seg.store.t[seg.sel[cur]] - seg.first_t
            if self._cursor >= seg.frames:
                in_seg = seg.duration_s
        return (self._pass_no * plan.span_s + plan.cum_before[item]
                + self._item_pass * seg.span_s + seg.gap_s + in_seg)

    def _close_speed_segment_locked(self) -> None:
        """Bank the wall time the current speed owes, before the speed changes."""
        pos = self._log_position_locked()
        self._expected_wall += max(0.0, pos - self._speed_seg_log) / self._speed
        self._speed_seg_log = pos

    def _expected_wall_locked(self) -> float:
        """Wall seconds this timeline should have taken so far."""
        if self._expected_frozen is not None:
            return self._expected_frozen
        return self._expected_wall + \
            max(0.0, self._log_position_locked() - self._speed_seg_log) / self._speed

    def _elapsed_locked(self) -> float:
        if self._elapsed_frozen is not None:
            return self._elapsed_frozen
        if not self._play_started:
            return 0.0
        return max(0.0, time.perf_counter() - self._play_started - self._paused_total)

    def _freeze_locked(self) -> None:
        """Stop the health clock so a finished run keeps its final numbers.

        Both halves of drift must freeze together: ``stop()`` rewinds the cursor
        to the top, so a live-computed "expected" would collapse to zero and
        report the whole run as drift.
        """
        self._elapsed_frozen = self._elapsed_locked()
        self._expected_frozen = self._expected_wall_locked()

    # ----- worker ----------------------------------------------------------
    def _rebase_locked(self, now: Optional[float] = None) -> None:
        """Anchor the clock so the frame at the cursor is due at *now*."""
        seg = self._seg()
        if seg is not None and seg.frames:
            i = min(self._cursor, seg.frames - 1)
            self._base = seg.store.t[seg.sel[i]]
        else:
            self._base = 0.0
        self._epoch = now if now is not None else time.perf_counter()

    def _message(self, store, idx: int) -> can.Message:
        """The frame to transmit, after any signal patching."""
        msg = store.message(idx)
        patcher = self._patcher
        if patcher is not None:
            patched = patcher.patch(msg.arbitration_id, msg.is_extended_id, msg.data)
            if patched is not None:
                msg.data = bytearray(patched)
        return msg

    def _run(self, send: Callable[[can.Message], None]) -> None:
        # The store comes from the current segment each iteration — a playlist
        # walks several of them.
        with _timer_resolution(1):
            while not self._stop_evt.is_set():
                if not self._pause_evt.is_set():
                    paused_at = time.perf_counter()
                    self._pause_evt.wait()
                    if self._stop_evt.is_set():
                        return
                    with self._lock:
                        self._paused_total += time.perf_counter() - paused_at
                        self._rebase_locked()

                with self._lock:
                    seg = self._seg()
                    sel = seg.sel if seg else ()
                    store = seg.store if seg else None
                    i = self._cursor
                    speed, tick = self._speed, self._tick
                    epoch, base = self._epoch, self._base

                if seg is None or i >= len(sel):
                    if not self._advance():        # next item / pass, or finish
                        return
                    continue

                # Send every frame whose deadline has arrived (plus one tick of
                # look-ahead, so sub-tick gaps coalesce instead of stalling).
                now = time.perf_counter()
                horizon = base + (now - epoch + tick) * speed
                sent = errors = late = 0
                late_sum = max_late = 0.0
                while i < len(sel) and sent < _MAX_BURST and not self._stop_evt.is_set():
                    idx = sel[i]
                    if store.t[idx] > horizon:
                        break
                    due = epoch + (store.t[idx] - base) / speed
                    try:
                        send(self._message(store, idx))
                    except Exception as exc:
                        errors += 1
                        self._consec_errors += 1
                        if self._consec_errors >= _MAX_CONSEC_ERRORS:
                            self._fail(f"bus send failed {self._consec_errors}× "
                                       f"(no ACK / bus-off?): {exc}", sent, errors,
                                       late, late_sum, max_late, i)
                            return
                    else:
                        self._consec_errors = 0
                        sent += 1
                        lateness = time.perf_counter() - due
                        if lateness > 0:
                            late_sum += lateness
                            max_late = max(max_late, lateness)
                            if lateness > _LATE_S:
                                late += 1
                    i += 1

                with self._lock:
                    self._cursor = i
                    self._sent += sent
                    h = self._health
                    h["sent"] += sent
                    h["errors"] += errors
                    h["late"] += late
                    h["late_sum"] += late_sum
                    h["max_late"] = max(h["max_late"], max_late)
                    if sent:
                        h["bursts"] += 1
                        h["burst_max"] = max(h["burst_max"], sent)

                if i >= len(sel):
                    continue                       # let _advance decide

                # Sleep to the next deadline. Never shorter than one tick: the
                # OS cannot honour it, and waking early just burns CPU.
                due = epoch + (store.t[sel[i]] - base) / speed
                remaining = due - time.perf_counter()
                if remaining > 0 and self._stop_evt.wait(max(remaining, tick)):
                    return

    def _advance(self) -> bool:
        with self._lock:
            return self._advance_locked()

    def _advance_locked(self) -> bool:
        """End of an item: repeat it, move to the next, loop the plan, or finish.

        Returns whether playback continues. Item repeats replay the *same*
        segment — no frames are copied, so "idle ×1000" costs nothing extra.
        """
        plan = self._plan
        seg = self._seg()
        if plan is None or seg is None:
            self._state = "done"
            self._freeze_locked()
            return False

        self._item_pass += 1
        endless_item = seg.item.repeat == 0
        if endless_item or self._item_pass < seg.passes:
            self._cursor = 0
            self._start_item_locked()
            return True

        self._item += 1
        self._item_pass = 0
        if self._item < len(plan.segments):
            self._cursor = 0
            self._start_item_locked()
            return True

        # Whole playlist done.
        self._pass_no += 1
        if self._passes == 0 or self._pass_no < self._passes:
            self._item = self._cursor = 0
            self._start_item_locked()
            return True
        # Park at the end so status() reports 100 %, not a rewind.
        self._item = len(plan.segments) - 1
        self._item_pass = max(0, plan.segments[self._item].passes - 1)
        self._cursor = plan.segments[self._item].frames
        self._state = "done"
        self._freeze_locked()
        return False

    def _start_item_locked(self) -> None:
        """Anchor the clock for the item at the cursor, honouring its gap.

        The gap is just a later epoch — the normal deadline path then sleeps to
        it, so nothing in the scheduler needs to know gaps exist. It scales with
        speed like everything else on the timeline.

        Every item boundary is a seam, not just a loop: a playlist can put an
        earlier capture after a later one, which steps the odometer backwards
        exactly like looping does. So the patcher is told every time.
        """
        seg = self._seg()
        gap = (seg.gap_s / self._speed) if seg else 0.0
        self._rebase_locked(time.perf_counter() + gap)
        if self._patcher is not None:
            self._patcher.on_rewind()

    def _fail(self, message: str, sent: int, errors: int, late: int,
              late_sum: float, max_late: float, cursor: int) -> None:
        with self._lock:
            self._cursor = cursor
            self._sent += sent
            h = self._health
            h["sent"] += sent
            h["errors"] += errors
            h["late"] += late
            h["late_sum"] += late_sum
            h["max_late"] = max(h["max_late"], max_late)
            self._state = "error"
            self._error = message
            self._freeze_locked()

    # ----- status ----------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            plan = self._plan
            seg = self._seg()
            total = seg.frames if seg else 0
            mid_item = total and self._cursor < total
            cur_offset = (seg.store.t[seg.sel[self._cursor]] - seg.first_t) if mid_item \
                else (seg.duration_s if seg else 0.0)
            elapsed = self._elapsed_locked()
            expected = self._expected_wall_locked()
            span = plan.span_s if plan else 0.0
            in_pass = max(0.0, self._log_position_locked() - self._pass_no * span)
            # An endless *item* loops without ever completing a plan pass, so its
            # position runs past one span — wrap it so the bar shows loop
            # progress instead of sitting pinned at 100 %.
            if span > 0 and in_pass > span:
                in_pass %= span
            h = self._health
            return {
                "state": self._state,
                "error": self._error,
                "meta": dict(self._meta),
                "cursor": self._cursor,
                "total": total,
                "sent": self._sent,
                "cursor_s": round(cur_offset, 3),
                "speed": self._speed,
                "loop": self._passes == 0,
                "passes": self._passes,
                "pass_no": self._pass_no + (1 if self._state in ("playing", "paused") else 0),
                "network": seg.network if seg else None,
                # Playlist position. `progress` spans the whole plan (time-based,
                # so a 40 s item doesn't advance the bar as fast as a 4 s one);
                # `item_progress` is the current file alone.
                "progress": 1.0 if self._state == "done"
                            else (round(min(1.0, in_pass / span), 4) if span else 0.0),
                "item": self._item,
                "item_count": len(plan) if plan else 0,
                "item_label": seg.label if seg else "",
                # 1-based while running; a finished item reads "n/n", not "0/n".
                "item_pass": (seg.passes if (self._state == "done" and seg)
                              else self._item_pass +
                              (1 if self._state in ("playing", "paused") else 0)),
                "item_repeat": seg.item.repeat if seg else 1,
                "item_progress": round(self._cursor / total, 4) if total else 0.0,
                "plan_frames": plan.frames if plan else 0,
                "health": {
                    "sent": h["sent"],
                    "errors": h["errors"],
                    "late": h["late"],
                    "late_pct": round(100.0 * h["late"] / h["sent"], 1) if h["sent"] else 0.0,
                    "avg_late_ms": round(1000.0 * h["late_sum"] / h["sent"], 2) if h["sent"] else 0.0,
                    "max_late_ms": round(1000.0 * h["max_late"], 2),
                    "fps": round(h["sent"] / elapsed, 1) if elapsed > 0.05 else 0.0,
                    "target_fps": round((self._meta.get("fps") or 0.0) * self._speed, 1),
                    # Wall time minus the time this timeline should have taken:
                    # the honest "did the replay keep real time?" number.
                    "drift_ms": round(1000.0 * (elapsed - expected), 1) if elapsed > 0 else 0.0,
                    "burst_max": h["burst_max"],
                    "tick_ms": round(1000.0 * self._tick, 2),
                    # False once the timeline is measurably behind the wall
                    # clock — the engine sends flat out but a speed multiplier
                    # (or a slow adapter) can demand more frames/s than one
                    # thread and one bus can deliver. Better said plainly than
                    # left for the operator to infer from late_pct.
                    "keeping_up": not (elapsed > 0.5 and (elapsed - expected) > _BEHIND_S),
                },
            }


#: Legacy name — ``cli.py`` and older callers construct ``LogReplayer()``.
LogReplayer = TxEngine
