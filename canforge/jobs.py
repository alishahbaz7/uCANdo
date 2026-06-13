"""Job scheduler — run automation tasks on an interval or on demand.

Jobs live in the ``jobs`` table (created in Phase 0). Each job has a ``kind``
that maps to a **handler** callable registered by the server (e.g. ``scan`` runs
a DTC scan, ``record`` pulses a recording, ``export`` dumps signals). The
``schedule`` is either ``"every:<seconds>"`` for periodic jobs or ``""`` for
trigger-only jobs that run via :meth:`run_now`.

A single background thread wakes every second, finds due periodic jobs, and runs
their handler, stamping ``last_run``. Handlers are injected so the runner has no
dependency on the bus, recorder, or DTC subsystems — it just dispatches by kind,
which keeps it testable with a dummy handler.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable


def _interval_s(schedule: str):
    if isinstance(schedule, str) and schedule.startswith("every:"):
        try:
            return max(1.0, float(schedule.split(":", 1)[1]))
        except ValueError:
            return None
    return None


class JobRunner:
    def __init__(self, storage):
        self._s = storage
        self._handlers: dict[str, Callable[[dict], dict]] = {}
        self._thread = None
        self._running = False
        self._last_result: dict[int, dict] = {}

    def register_handler(self, kind: str, fn: Callable[[dict], dict]) -> None:
        self._handlers[kind] = fn

    # ----- CRUD ------------------------------------------------------------
    def add_job(self, name: str, kind: str, *, schedule: str = "",
                spec: dict | None = None, enabled: bool = True) -> dict:
        jid = self._s.insert("jobs", name=name, kind=kind, schedule=schedule,
                             spec=json.dumps(spec or {}), enabled=int(enabled))
        return self.get_job(jid)

    def get_job(self, jid: int) -> dict | None:
        row = self._s.get("jobs", jid)
        if row:
            row["spec"] = json.loads(row.get("spec") or "{}")
            row["last_result"] = self._last_result.get(jid)
        return row

    def list_jobs(self) -> list[dict]:
        rows = self._s.list("jobs")
        for r in rows:
            r["spec"] = json.loads(r.get("spec") or "{}")
            r["last_result"] = self._last_result.get(r["id"])
        return rows

    def remove_job(self, jid: int) -> None:
        self._s.delete("jobs", jid)

    def set_enabled(self, jid: int, enabled: bool) -> None:
        self._s.execute("UPDATE jobs SET enabled = ? WHERE id = ?", (int(enabled), jid))

    # ----- execution -------------------------------------------------------
    def run_now(self, jid: int) -> dict:
        job = self.get_job(jid)
        if not job:
            raise KeyError(jid)
        return self._run(job)

    def _run(self, job: dict) -> dict:
        handler = self._handlers.get(job["kind"])
        now = round(time.time(), 3)
        self._s.execute("UPDATE jobs SET last_run = ? WHERE id = ?", (now, job["id"]))
        if handler is None:
            res = {"ok": False, "error": f"no handler for kind {job['kind']!r}"}
        else:
            try:
                res = handler(job["spec"]) or {"ok": True}
            except Exception as exc:
                res = {"ok": False, "error": str(exc)}
        res = {"ts": now, **res}
        self._last_result[job["id"]] = res
        return res

    # ----- background loop -------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            for job in self.list_jobs():
                if not job["enabled"]:
                    continue
                interval = _interval_s(job["schedule"])
                if interval is None:
                    continue
                last = job["last_run"] or 0.0
                if now - last >= interval:
                    self._run(job)
            time.sleep(1.0)
