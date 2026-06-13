"""Computed (virtual) signals and alarms over decoded signal values.

Two small, pure helpers that sit on top of whatever produces a
``{signal_key: value}`` map (the Signal Viewer feeds them per frame):

* :class:`ComputedSignals` — math channels. A computed signal is
  ``{"name": "Power", "expr": "sig('BATT.Volts') * sig('BATT.Amps')"}``; the
  expression references other signals via ``sig('MSG.SIGNAL')`` and may use a
  whitelist of math functions. Evaluated in a restricted namespace with no
  builtins — safe enough for this internal tool (don't expose to untrusted input).
* :class:`AlarmMonitor` — per-signal thresholds. An alarm is
  ``{"name": "Overspeed", "key": "VEHICLE.Speed", "max": 120}``; on each
  evaluation it tracks whether the value is out of range, when it first tripped,
  and how many times.

Both are deliberately stateless w.r.t. the bus — they only see values handed to
them, so they're trivial to test.
"""

from __future__ import annotations

import math
import time

# Whitelisted names available inside a computed-signal expression.
_SAFE_NS = {k: getattr(math, k) for k in
            ("sqrt", "sin", "cos", "tan", "log", "log2", "log10", "exp",
             "pi", "e", "floor", "ceil", "fabs", "pow", "atan", "atan2")}
_SAFE_NS.update({"abs": abs, "min": min, "max": max, "round": round})


def safe_eval(expr: str, values: dict):
    """Evaluate ``expr`` with a ``sig(key)`` accessor and math funcs only."""
    def sig(key, default=None):
        return values.get(key, default)
    ns = dict(_SAFE_NS)
    ns["sig"] = sig
    return eval(compile(expr, "<computed>", "eval"), {"__builtins__": {}}, ns)


class ComputedSignals:
    def __init__(self):
        self._defs: list[dict] = []

    def set(self, defs: list[dict]) -> None:
        # Keep only well-formed {name, expr} entries.
        self._defs = [{"name": d["name"], "expr": d["expr"]}
                      for d in defs if d.get("name") and d.get("expr")]

    def defs(self) -> list[dict]:
        return list(self._defs)

    def evaluate(self, values: dict) -> dict:
        """Return ``{name: numeric_value}`` for every expression that evaluates."""
        out = {}
        for d in self._defs:
            try:
                v = safe_eval(d["expr"], values)
            except Exception:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[d["name"]] = float(v)
        return out


class AlarmMonitor:
    def __init__(self):
        self._defs: list[dict] = []
        # name -> {active, value, since, count, last_ts}
        self._state: dict[str, dict] = {}

    def set(self, defs: list[dict]) -> None:
        self._defs = []
        for d in defs:
            key = d.get("key")
            if not key:
                continue
            self._defs.append({
                "name": d.get("name") or key,
                "key": key,
                "min": d.get("min"),
                "max": d.get("max"),
            })
        self._state = {d["name"]: self._state.get(d["name"], {
            "active": False, "value": None, "since": None, "count": 0, "last_ts": None})
            for d in self._defs}

    def defs(self) -> list[dict]:
        return list(self._defs)

    def evaluate(self, values: dict) -> None:
        now = time.time()
        for d in self._defs:
            v = values.get(d["key"])
            st = self._state[d["name"]]
            if v is None:
                continue
            st["value"] = v
            st["last_ts"] = round(now, 3)
            out = ((d["min"] is not None and v < d["min"]) or
                   (d["max"] is not None and v > d["max"]))
            if out and not st["active"]:
                st["since"] = round(now, 3)
                st["count"] += 1
            if not out:
                st["since"] = None
            st["active"] = out

    def snapshot(self) -> dict:
        items = []
        for d in self._defs:
            st = self._state[d["name"]]
            items.append({**d, **st})
        return {"alarms": items, "active_count": sum(1 for i in items if i["active"])}

    def clear(self) -> None:
        for st in self._state.values():
            st.update({"active": False, "since": None, "count": 0})
