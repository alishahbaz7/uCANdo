"""Scripting API — a small, sandboxed Python runner (our CAPL equivalent).

Lets a user automate the bus with a short Python snippet that talks to a
restricted ``ctx`` object:

    for i in range(3):
        ctx.send(0x100, "11 22 33")
        ctx.log("speed = %s" % ctx.latest("VEHICLE.Speed"))

The script runs with **no real builtins** (no ``import``/``open``/``eval``) — only
a curated safe subset plus ``ctx`` — and on a worker thread with a wall-clock
timeout. This is sufficient hardening for an *internal* tool; it is **not** a
security boundary for untrusted code. ``ctx`` is wired by the server to the live
bus (``send``) and the Signal Viewer (``latest``).
"""

from __future__ import annotations

import threading
import time


def _safe_builtins() -> dict:
    src = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    names = ("range", "len", "min", "max", "abs", "round", "enumerate", "zip",
             "sum", "int", "float", "str", "bool", "list", "dict", "tuple",
             "sorted", "map", "filter")
    return {n: src[n] for n in names if n in src}


class ScriptContext:
    def __init__(self, send=None, latest=None, sleep_cap: float = 2.0):
        self._send = send
        self._latest = latest or (lambda k, d=None: d)
        self._sleep_cap = sleep_cap
        self.logs: list[str] = []

    def send(self, arb_id, data="", is_extended=False) -> None:
        if self._send is None:
            raise RuntimeError("not connected")
        import can
        if isinstance(data, str):
            data = bytes(int(b, 16) for b in data.replace(",", " ").split())
        self._send(can.Message(arbitration_id=int(arb_id), data=bytes(data),
                               is_extended_id=bool(is_extended)))

    def latest(self, key, default=None):
        return self._latest(key, default)

    def log(self, *args) -> None:
        self.logs.append(" ".join(str(a) for a in args))

    def sleep(self, seconds: float) -> None:
        time.sleep(min(float(seconds), self._sleep_cap))


def run_script(code: str, ctx: ScriptContext, timeout: float = 5.0) -> dict:
    """Execute ``code`` against ``ctx`` with a timeout. Returns {ok, logs, error}."""
    result = {"ok": True, "error": None}
    g = {"__builtins__": _safe_builtins(), "ctx": ctx}

    def _target():
        try:
            exec(compile(code, "<script>", "exec"), g, {})
        except Exception as exc:
            result["ok"] = False
            result["error"] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=_target, name="script-run", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        result["ok"] = False
        result["error"] = f"timeout after {timeout}s"
    result["logs"] = list(ctx.logs)
    return result
