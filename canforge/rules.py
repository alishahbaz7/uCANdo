"""Rules engine — "when this, do that" automation over live signals.

A rule is ``{name, when, action}`` where ``when`` is a boolean expression over
decoded signals (same ``sig('MSG.SIGNAL')`` syntax as computed signals) and
``action`` is one of:

* ``{"type": "log", "message": "..."}``      — record an event (always available),
* ``{"type": "transmit", "id": 0x100, "data": "11 22", "is_extended": false}``
  — send a frame via the injected ``send`` callable,
* ``{"type": "job", "job_id": 3}``           — trigger a scheduler job.

Rules are **edge-triggered**: the action fires once when ``when`` goes
false→true, not on every frame it stays true, with an optional ``cooldown_s`` to
rate-limit re-fires. The engine is fed the latest ``{key: value}`` map by the
Signal Viewer (it subscribes), so it sees the same decoded values the charts do.

Rules persist via the storage ``settings`` table so they survive restarts. Pure
logic apart from the injected ``send`` / ``trigger_job`` callables — testable
without a bus.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from .derived import safe_eval

SETTINGS_KEY = "rules"


def _parse_data(data) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        return bytes(int(b, 16) for b in data.replace(",", " ").split())
    return bytes(int(b) & 0xFF for b in (data or []))


class RulesEngine:
    def __init__(self, storage=None, send=None, trigger_job=None):
        self._lock = threading.Lock()
        self._storage = storage
        self._send = send                # callable(can.Message) — set by server
        self._trigger_job = trigger_job  # callable(job_id)
        self._rules: list[dict] = []
        self._state: dict[int, dict] = {}    # rule index -> {active, last_fire}
        self._events: deque = deque(maxlen=200)
        self._next_id = 1
        if storage is not None:
            self._load()

    # ----- persistence -----------------------------------------------------
    def _load(self) -> None:
        saved = self._storage.get_setting(SETTINGS_KEY, [])
        if saved:
            self._rules = saved
            self._next_id = max((r.get("uid", 0) for r in saved), default=0) + 1

    def _save(self) -> None:
        if self._storage is not None:
            self._storage.set_setting(SETTINGS_KEY, self._rules)

    # ----- management ------------------------------------------------------
    def add(self, name: str, when: str, action: dict, *, cooldown_s: float = 0.0,
            enabled: bool = True) -> dict:
        with self._lock:
            rule = {"uid": self._next_id, "name": name or f"rule_{self._next_id}",
                    "when": when, "action": action, "cooldown_s": float(cooldown_s),
                    "enabled": bool(enabled), "fired": 0}
            self._next_id += 1
            self._rules.append(rule)
            self._save()
            return dict(rule)

    def remove(self, uid: int) -> None:
        with self._lock:
            self._rules = [r for r in self._rules if r["uid"] != uid]
            self._save()

    def set_enabled(self, uid: int, enabled: bool) -> None:
        with self._lock:
            for r in self._rules:
                if r["uid"] == uid:
                    r["enabled"] = bool(enabled)
            self._save()

    def table(self) -> dict:
        with self._lock:
            return {"rules": [dict(r) for r in self._rules],
                    "events": list(self._events)}

    # ----- evaluation (subscribed to the Signal Viewer) --------------------
    def on_values(self, values: dict) -> None:
        now = time.time()
        with self._lock:
            for r in self._rules:
                if not r.get("enabled"):
                    continue
                try:
                    cond = bool(safe_eval(r["when"], values))
                except Exception:
                    continue
                st = self._state.setdefault(r["uid"], {"active": False, "last_fire": 0.0})
                rising = cond and not st["active"]
                st["active"] = cond
                if rising and (now - st["last_fire"]) >= r.get("cooldown_s", 0.0):
                    st["last_fire"] = now
                    r["fired"] = r.get("fired", 0) + 1
                    self._fire(r, now)

    def _fire(self, rule: dict, now: float) -> None:
        action = rule.get("action") or {}
        kind = action.get("type", "log")
        detail = ""
        try:
            if kind == "transmit" and self._send is not None:
                import can
                self._send(can.Message(arbitration_id=int(action["id"]),
                                       data=_parse_data(action.get("data", "")),
                                       is_extended_id=bool(action.get("is_extended", False))))
                detail = f"tx 0x{int(action['id']):X}"
            elif kind == "job" and self._trigger_job is not None:
                self._trigger_job(int(action["job_id"]))
                detail = f"job {action['job_id']}"
            else:
                detail = action.get("message", "")
        except Exception as exc:
            detail = f"action error: {exc}"
        self._events.appendleft({"ts": round(now, 3), "rule": rule["name"],
                                 "action": kind, "detail": detail})
