"""TX Replay — load a recorded log and play it back onto the live bus.

Reads any format python-can understands (`.asc`, `.blf`, `.csv`, `.log`) via
``can.LogReader``, then a background thread re-transmits the frames preserving
their original inter-frame timing, scaled by a speed factor. Supports
pause/resume, looping, ID filtering and single-frame stepping.

The replayer never opens its own bus — it transmits through a ``send``
callable supplied by the caller (``BusManager.send``), keeping it adapter
agnostic like everything above the HAL.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import can


class LogReplayer:
    def __init__(self):
        self._lock = threading.Lock()
        self._frames: list[tuple[float, can.Message]] = []  # (rel_offset_s, msg)
        self._meta: dict = {}
        self._thread: Optional[threading.Thread] = None
        self._state = "empty"          # empty | ready | playing | paused | done
        self._cursor = 0               # index of next frame to send
        self._speed = 1.0
        self._loop = False
        self._filter: Optional[set[int]] = None
        self._sent = 0
        self._pause_evt = threading.Event()
        self._stop_evt = threading.Event()

    # ----- loading ---------------------------------------------------------
    def load(self, path: str) -> dict:
        frames: list[tuple[float, can.Message]] = []
        ids: set[int] = set()
        channels: set[str] = set()
        t0 = None
        with can.LogReader(path) as reader:
            for msg in reader:
                if t0 is None:
                    t0 = msg.timestamp
                frames.append((msg.timestamp - t0, msg))
                ids.add(msg.arbitration_id)
                if msg.channel is not None:
                    channels.add(str(msg.channel))
        duration = frames[-1][0] if frames else 0.0
        with self._lock:
            self._frames = frames
            self._cursor = 0
            self._sent = 0
            self._state = "ready" if frames else "empty"
            self._meta = {
                "path": path,
                "frames": len(frames),
                "duration_s": round(duration, 3),
                "ids": sorted(ids),
                "channels": sorted(channels),
            }
        return dict(self._meta)

    # ----- playback control ------------------------------------------------
    def play(self, send: Callable[[can.Message], None], speed: float = 1.0,
             loop: bool = False, filter_ids: Optional[list[int]] = None) -> None:
        with self._lock:
            if not self._frames:
                raise RuntimeError("No log loaded")
            if self._state == "playing":
                return
            self._speed = max(0.01, float(speed))
            self._loop = bool(loop)
            self._filter = set(filter_ids) if filter_ids else None
            if self._state in ("done", "ready"):
                self._cursor = 0 if self._state == "done" else self._cursor
            self._state = "playing"
            self._stop_evt.clear()
            self._pause_evt.set()  # not paused
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
                self._pause_evt.set()

    def stop(self) -> None:
        self._stop_evt.set()
        self._pause_evt.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        with self._lock:
            self._state = "ready"
            self._cursor = 0

    def set_speed(self, speed: float) -> None:
        with self._lock:
            self._speed = max(0.01, float(speed))

    def step(self, send: Callable[[can.Message], None]) -> dict:
        """Send exactly one (filtered) frame and advance the cursor."""
        with self._lock:
            if self._state == "playing":
                raise RuntimeError("Pause before stepping")
            while self._cursor < len(self._frames):
                _, msg = self._frames[self._cursor]
                self._cursor += 1
                if self._filter and msg.arbitration_id not in self._filter:
                    continue
                send(msg)
                self._sent += 1
                return {"sent": True, "cursor": self._cursor}
            self._state = "done"
            return {"sent": False, "cursor": self._cursor}

    # ----- worker ----------------------------------------------------------
    def _run(self, send: Callable[[can.Message], None]) -> None:
        while not self._stop_evt.is_set():
            with self._lock:
                frames = self._frames
                idx = self._cursor
            if idx >= len(frames):
                if self._loop and not self._stop_evt.is_set():
                    with self._lock:
                        self._cursor = 0
                    continue
                with self._lock:
                    self._state = "done"
                return

            offset, msg = frames[idx]
            next_offset = frames[idx + 1][0] if idx + 1 < len(frames) else offset
            with self._lock:
                speed = self._speed
                flt = self._filter
                self._cursor += 1

            if not flt or msg.arbitration_id in flt:
                try:
                    send(msg)
                    with self._lock:
                        self._sent += 1
                except Exception:
                    pass

            # Wait the (scaled) gap to the next frame, honouring pause/stop.
            gap = max(0.0, (next_offset - offset) / speed)
            self._pause_evt.wait()           # block while paused
            if self._stop_evt.wait(timeout=gap):
                return

    # ----- status ----------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            total = len(self._frames)
            cur_offset = self._frames[self._cursor][0] if (total and self._cursor < total) \
                else self._meta.get("duration_s", 0.0)
            return {
                "state": self._state,
                "meta": dict(self._meta),
                "cursor": self._cursor,
                "total": total,
                "sent": self._sent,
                "cursor_s": round(cur_offset, 3),
                "speed": self._speed,
                "loop": self._loop,
                "progress": round(self._cursor / total, 4) if total else 0.0,
            }
