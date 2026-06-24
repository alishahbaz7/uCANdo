"""FastAPI application: REST control plane + live WebSocket + static UI.

Holds one instance of every subsystem and the single :class:`BusManager`.
Subsystems that observe live traffic (Signal Viewer, Protocol monitor) register
a tap on the bus manager so they survive reconnects; subsystems that transmit
(Replay, TX Scheduler) call ``bus.send``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import deque

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __app_name__, __version__
from . import applog
from .bus_manager import BusManager
import can

from .config import Config
from .dashboard import Dashboard
from .device_enum import enumerate_all
from .dbc_builder import DbcModel
from .drivers import DriverAssistant
from .dtc import DtcMonitor
from .jobs import JobRunner
from . import preflight
from .oem_db import TARGET_OEMS, OemDatabase, fingerprint_from_id_stats
from .protocol import ProtocolDecoder
from .rules import RulesEngine
from .scripting import ScriptContext, run_script
from .simulation import RestbusSimulator
from .registry import RE_ENGINES, describe_all, load_plugins
from .replay import LogReplayer
from .re_engines.diff import StateSniffer, compare_logs
from .re_engines.correlate import correlate_log
from .resession import RESession, populate_from_log
from .guided import list_protocols
from .reverse import analyze_log
from .scheduler import TxScheduler
from .signals import SignalViewer
from .storage import Storage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DRIVER_DIR = os.path.join(DATA_DIR, "drivers")
for d in (LOG_DIR, UPLOAD_DIR, DRIVER_DIR):
    os.makedirs(d, exist_ok=True)

# Rotating error/activity log → data/ucando.log (captures crashes for diagnosis).
applog.setup_logging(os.path.join(DATA_DIR, "ucando.log"))
log = logging.getLogger("canforge.server")
log.info("uCANdo %s starting up", __version__)

app = FastAPI(title=f"{__app_name__} API", version=__version__)


@app.exception_handler(Exception)
async def _log_unhandled(request, exc):
    """Last-resort handler: log the full traceback, return a graceful 500."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"ok": False, "error": "internal error (logged to data/ucando.log)"})

# ----- foundation rails (persistence, config, plugins) ---------------------
storage = Storage()
config = Config(storage)
oem = OemDatabase(storage)
oem.seed_builtins()               # demo profile + OEM placeholders (idempotent)
driver_assistant = DriverAssistant(DRIVER_DIR)
loaded_plugins = load_plugins()   # auto-imports canforge/plugins/* (self-register)

# ----- subsystems ----------------------------------------------------------
bus = BusManager()
replayer = LogReplayer()
scheduler = TxScheduler()
dbc = DbcModel()
viewer = SignalViewer()
dashboard = Dashboard()
dtc = DtcMonitor()
sniffer = StateSniffer()

# ----- automation & simulation (Phase 4, Pillar C) -------------------------
restbus = RestbusSimulator(bus.send)
auto_session = RESession()        # current Auto-RE identification session (A/B/C)
jobs_runner = JobRunner(storage)
rules = RulesEngine(storage, send=bus.send, trigger_job=jobs_runner.run_now)
viewer.add_value_subscriber(rules.on_values)   # rules see decoded signal values

# Protocol monitor: a decoder + bounded buffer fed by a live tap.
proto_decoder = ProtocolDecoder()
proto_recent: deque = deque(maxlen=300)


def _proto_tap(msg):
    res = proto_decoder.decode(msg.arbitration_id, bytes(msg.data), bool(msg.is_extended_id))
    res = {"ts": round(msg.timestamp, 4), "id_hex":
           f"{msg.arbitration_id:0{8 if msg.is_extended_id else 3}X}", **res}
    proto_recent.appendleft(res)


# Live observers registered once; BusManager re-applies them on every connect.
bus.add_tap(viewer.consume)
bus.add_tap(_proto_tap)
bus.add_tap(dashboard.consume)
bus.add_tap(dtc.consume)
bus.add_tap(sniffer.consume)


# ----- job handlers (dispatched by JobRunner by `kind`) --------------------
def _dtc_scan_send() -> dict:
    """Transmit the standard DTC requests (shared by /api/dtc/scan and the job)."""
    bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                         data=bytes([0x01, 0x03, 0, 0, 0, 0, 0, 0])))
    bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                         data=bytes([0x01, 0x07, 0, 0, 0, 0, 0, 0])))
    req_id = (6 << 26) | (0xEA << 16) | (0xFF << 8) | 0xF9
    bus.send(can.Message(arbitration_id=req_id, is_extended_id=True,
                         data=bytes([0xCA, 0xFE, 0x00])))
    return {"ok": True, "sent": 3}


def _job_scan(spec):
    if not bus.connected:
        return {"ok": False, "error": "not connected"}
    return _dtc_scan_send()


def _job_record(spec):
    """Pulse a recording for spec['duration_s'] seconds (non-blocking)."""
    if not bus.logger:
        return {"ok": False, "error": "not connected"}
    name = spec.get("name", "job-capture")
    fmt = spec.get("format", "asc")
    dur = float(spec.get("duration_s", 5))
    bus.logger.start_recording(fmt, os.path.join(LOG_DIR, name))
    threading.Timer(dur, lambda: bus.logger and bus.logger.stop_recording()).start()
    return {"ok": True, "recording_s": dur}


jobs_runner.register_handler("scan", _job_scan)
jobs_runner.register_handler("record", _job_record)
jobs_runner.start()


# ----- request models ------------------------------------------------------
class ConnectReq(BaseModel):
    hw: str
    channel: str
    bitrate: int = 500_000
    fd: bool = False
    simulate: bool = True


class RecordReq(BaseModel):
    format: str = "asc"
    name: str | None = None


class PathReq(BaseModel):
    path: str


class PlayReq(BaseModel):
    speed: float = 1.0
    loop: bool = False
    filter_ids: list[int] | None = None


class DbcModelReq(BaseModel):
    messages: list = []


class TxAddReq(BaseModel):
    id: int
    data: str = ""
    cycle_ms: int = 100
    mode: str = "cyclic"
    is_extended: bool = False
    name: str = ""


class TxUpdateReq(BaseModel):
    uid: int
    patch: dict


class DecodeReq(BaseModel):
    id: int
    data: str
    is_extended: bool = False


def _err(msg: str, code: int = 400):
    return JSONResponse(status_code=code, content={"ok": False, "error": msg})


def _save_upload(file: UploadFile) -> str:
    dest = os.path.join(UPLOAD_DIR, os.path.basename(file.filename))
    with open(dest, "wb") as fh:
        fh.write(file.file.read())
    return dest


# ===========================================================================
# Core / hardware
# ===========================================================================
@app.get("/api/info")
def info():
    return {"app": __app_name__, "version": __version__,
            "plugins_loaded": len(loaded_plugins)}


@app.get("/api/plugins")
def plugins():
    """Every registered plugin (RE engines, decoders, exporters, OEM packs)."""
    return describe_all()


@app.get("/api/config")
def config_get():
    return config.all()


class ConfigSetReq(BaseModel):
    key: str
    value: object


@app.post("/api/config")
def config_set(req: ConfigSetReq):
    config.set(req.key, req.value)
    return {"ok": True, "config": config.all()}


@app.get("/api/devices")
def devices():
    return {"devices": enumerate_all()}


# ----- hardware preflight & driver assistant -------------------------------
@app.get("/api/drivers/status")
def drivers_status():
    """Per-adapter readiness; attaches live download progress where relevant."""
    backends = preflight.check_all()
    for b in backends:
        if b.get("remedy", {}).get("type") == "installer":
            b["download"] = driver_assistant.status(b["hw"])
    return {"backends": backends}


@app.post("/api/drivers/download")
def drivers_download(hw: str):
    try:
        return {"ok": True, **driver_assistant.start_download(hw)}
    except Exception as exc:
        return _err(str(exc))


@app.get("/api/drivers/download/status")
def drivers_download_status(hw: str):
    return driver_assistant.status(hw)


@app.post("/api/drivers/launch")
def drivers_launch(hw: str):
    """Extract (if a zip) and launch the vendor installer for an elevated install."""
    try:
        return driver_assistant.prepare_and_launch(hw)
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/connect")
def connect(req: ConnectReq):
    try:
        conn = bus.connect(req.hw, req.channel, req.bitrate, req.fd, req.simulate)
        log.info("connected: hw=%s channel=%s bitrate=%s sim=%s",
                 req.hw, req.channel, req.bitrate, req.simulate)
        return {"ok": True, "connection": conn}
    except Exception as exc:
        log.error("connect failed (hw=%s channel=%s): %s", req.hw, req.channel, exc)
        return _err(str(exc))


@app.post("/api/disconnect")
def disconnect():
    log.info("disconnect requested")
    return {"ok": True, **bus.disconnect()}


@app.get("/api/status")
def status():
    return bus.status()


# ===========================================================================
# CAN Logger
# ===========================================================================
@app.post("/api/logger/clear")
def logger_clear():
    if not bus.logger:
        return _err("Not connected")
    bus.logger.clear()
    return {"ok": True}


def _active_log_dir() -> str:
    """Configured log folder, or the default data/logs."""
    d = config.get("log_dir") or LOG_DIR
    os.makedirs(d, exist_ok=True)
    return d


@app.post("/api/logger/record/start")
def record_start(req: RecordReq):
    if not bus.logger:
        return _err("Not connected")
    path = os.path.join(_active_log_dir(), req.name or "capture")
    try:
        return {"ok": True, **bus.logger.start_recording(req.format, path)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/logger/record/stop")
def record_stop():
    if not bus.logger:
        return _err("Not connected")
    return {"ok": True, **bus.logger.stop_recording()}


@app.get("/api/logger/log-dir")
def get_log_dir():
    return {"dir": _active_log_dir(), "default": LOG_DIR,
            "custom": bool(config.get("log_dir"))}


class LogDirReq(BaseModel):
    dir: str = ""        # absolute folder; "" resets to the default data/logs


@app.post("/api/logger/log-dir")
def set_log_dir(req: LogDirReq):
    d = req.dir.strip()
    if d:
        try:
            os.makedirs(d, exist_ok=True)
            if not os.path.isdir(d):
                return _err("not a folder")
        except Exception as exc:
            return _err(f"cannot use folder: {exc}")
    config.set("log_dir", d)
    return {"ok": True, "dir": _active_log_dir()}


@app.get("/api/logs")
def list_logs():
    out = []
    dirs = [UPLOAD_DIR, _active_log_dir()]
    seen = set()
    for base in dirs:
        if base in seen or not os.path.isdir(base):
            continue
        seen.add(base)
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if os.path.isfile(p) and name.lower().endswith((".asc", ".blf", ".csv", ".log")):
                out.append({"name": name, "path": p, "size": os.path.getsize(p)})
    return {"logs": out}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    return {"ok": True, "path": _save_upload(file)}


# ===========================================================================
# TX Replay
# ===========================================================================
@app.post("/api/replay/load")
def replay_load(req: PathReq):
    try:
        return {"ok": True, "meta": replayer.load(req.path)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/replay/play")
def replay_play(req: PlayReq):
    if not bus.connected:
        return _err("Connect a bus before replaying")
    try:
        replayer.play(bus.send, req.speed, req.loop, req.filter_ids)
        return {"ok": True}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/replay/pause")
def replay_pause():
    replayer.pause(); return {"ok": True}


@app.post("/api/replay/resume")
def replay_resume():
    replayer.resume(); return {"ok": True}


@app.post("/api/replay/stop")
def replay_stop():
    replayer.stop(); return {"ok": True}


@app.post("/api/replay/step")
def replay_step():
    if not bus.connected:
        return _err("Connect a bus first")
    try:
        return {"ok": True, **replayer.step(bus.send)}
    except Exception as exc:
        return _err(str(exc))


@app.get("/api/replay/status")
def replay_status():
    return replayer.status()


# ===========================================================================
# Reverse Engineering
# ===========================================================================
class ReAnalyzeReq(BaseModel):
    path: str
    engine: str = "read"


@app.get("/api/re/engines")
def re_engines():
    return {"engines": RE_ENGINES.describe()}


@app.post("/api/re/analyze")
def re_analyze(req: ReAnalyzeReq):
    try:
        return {"ok": True, "result": analyze_log(req.path, engine=req.engine)}
    except Exception as exc:
        return _err(str(exc))


# ----- state-change sniffer (guided RE) ------------------------------------
@app.post("/api/re/sniff/arm")
def sniff_arm():
    if not bus.connected:
        return _err("Connect a bus first")
    return {"ok": True, **sniffer.arm()}


@app.post("/api/re/sniff/mark")
def sniff_mark():
    return {"ok": True, **sniffer.mark()}


@app.post("/api/re/sniff/stop")
def sniff_stop():
    return {"ok": True, **sniffer.stop()}


@app.get("/api/re/sniff/status")
def sniff_status():
    return sniffer.status()


@app.get("/api/re/sniff/result")
def sniff_result():
    return {"ok": True, "result": sniffer.result()}


# ----- compare two logs ----------------------------------------------------
class CompareReq(BaseModel):
    path_a: str        # baseline
    path_b: str        # after


@app.post("/api/re/compare")
def re_compare(req: CompareReq):
    try:
        return {"ok": True, "result": compare_logs(req.path_a, req.path_b)}
    except Exception as exc:
        return _err(str(exc))


# ----- LibreCAN correlation: label unknown signals vs OBD ground truth -----
class CorrelateReq(BaseModel):
    path: str
    r_threshold: float = 0.9


@app.post("/api/re/correlate")
def re_correlate(req: CorrelateReq):
    try:
        return {"ok": True, "result": correlate_log(req.path, r_threshold=req.r_threshold)}
    except Exception as exc:
        return _err(str(exc))


# ----- promote an analysed ID straight into the DBC Builder ----------------
class PromoteReq(BaseModel):
    id_result: dict            # one entry from an analyze/compare/sniff result
    min_confidence: float = 0.0


@app.post("/api/re/promote")
def re_promote(req: PromoteReq):
    """Seed the DBC Builder from an RE result, keeping candidates above a
    confidence floor (candidates without a confidence are always kept)."""
    try:
        re_id = dict(req.id_result)
        re_id["candidates"] = [
            c for c in re_id.get("candidates", [])
            if c.get("confidence", 1.0) >= req.min_confidence
        ]
        dbc.seed_from_re(re_id)
        return {"ok": True, **dbc.to_json()}
    except Exception as exc:
        return _err(str(exc))


# ===========================================================================
# OEM CAN Database (Pillar A)
# ===========================================================================
class OemProfileReq(BaseModel):
    oem: str
    name: str
    model: str = ""
    dbc: str = ""
    status: str = "draft"


class OemUpdateReq(BaseModel):
    id: int
    patch: dict


class OemFromBuilderReq(BaseModel):
    oem: str
    name: str
    model: str = ""


@app.get("/api/oem/profiles")
def oem_profiles(oem_filter: str | None = None):
    return {"targets": TARGET_OEMS, "profiles": oem.list_profiles(oem_filter)}


@app.get("/api/oem/profile/{pid}")
def oem_profile_get(pid: int):
    p = oem.get_profile(pid)
    return p or _err("No such profile", 404)


@app.post("/api/oem/profile")
def oem_profile_create(req: OemProfileReq):
    try:
        pid = oem.add_profile(req.oem, req.name, model=req.model, dbc=req.dbc, status=req.status)
        return {"ok": True, "id": pid, "profile": oem.get_profile(pid)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/oem/profile/update")
def oem_profile_update(req: OemUpdateReq):
    return {"ok": True, "profile": oem.update_profile(req.id, req.patch)}


@app.post("/api/oem/profile/delete")
def oem_profile_delete(pid: int):
    oem.delete_profile(pid)
    return {"ok": True}


@app.post("/api/oem/import")
async def oem_import(file: UploadFile = File(...), oem_name: str = "Unknown",
                     name: str | None = None):
    try:
        text = (await file.read()).decode("utf-8", "replace")
        pid = oem.import_dbc(oem_name, name or file.filename, text)
        return {"ok": True, "id": pid, "profile": oem.get_profile(pid)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/oem/from-builder")
def oem_from_builder(req: OemFromBuilderReq):
    """Save the current DBC Builder model as an OEM profile (the RE flywheel)."""
    try:
        pid = oem.save_from_dbc_model(dbc, req.oem, req.name, model=req.model)
        return {"ok": True, "id": pid, "profile": oem.get_profile(pid)}
    except Exception as exc:
        return _err(str(exc))


@app.get("/api/oem/identify")
def oem_identify():
    """Auto-identify the currently-connected vehicle from live traffic."""
    if not bus.logger:
        return _err("Connect a bus first")
    snap = bus.logger.snapshot()
    cap_sig = fingerprint_from_id_stats(snap.get("ids", []))
    return {"ok": True, "observed_ids": len(cap_sig["id_set"]),
            "matches": oem.identify_from_signature(cap_sig)}


class OemIdentifyLogReq(BaseModel):
    path: str


@app.post("/api/oem/identify-log")
def oem_identify_log(req: OemIdentifyLogReq):
    from .reverse import load_log_frames
    try:
        return {"ok": True, "matches": oem.identify(load_log_frames(req.path))}
    except Exception as exc:
        return _err(str(exc))


def _apply_profile(pid: int) -> dict:
    p = oem.get_profile(pid)
    if not p:
        return _err("No such profile", 404)
    if not p.get("dbc"):
        return _err("Profile has no DBC yet (contribute via RE)")
    viewer.load_dbc_string(p["dbc"], f"{p['oem']} · {p['name']}")
    return {"ok": True, "applied": {"id": pid, "name": p["name"], "oem": p["oem"]}, **viewer.info()}


@app.post("/api/oem/apply")
def oem_apply(pid: int):
    """Load a profile's DBC into the Signal Viewer — decode a known vehicle, no RE."""
    try:
        return _apply_profile(pid)
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/oem/auto-apply")
def oem_auto_apply(min_score: float = 0.5):
    """Identify the live vehicle and, if a confident decodable match exists,
    apply its profile to the Signal Viewer in one step (zero-DBC decode)."""
    if not bus.logger:
        return _err("Connect a bus first")
    cap_sig = fingerprint_from_id_stats(bus.logger.snapshot().get("ids", []))
    matches = oem.identify_from_signature(cap_sig)
    for m in matches:
        if m["score"] >= min_score:
            prof = oem.get_profile(m["profile_id"])
            if prof and prof.get("dbc"):
                try:
                    return {**_apply_profile(m["profile_id"]), "match": m}
                except Exception as exc:
                    return _err(str(exc))
    return {"ok": False, "reason": "no confident decodable match", "matches": matches}


# ===========================================================================
# Auto-RE / identification (confidence-tiered A/B/C)
# ===========================================================================
class AutoReAnalyzeReq(BaseModel):
    path: str
    known_values: dict = {}      # {label: value}, e.g. {"Odometer": 19335}


class SignalRef(BaseModel):
    frame_id: int
    start_bit: int
    length: int
    byte_order: str = "big_endian"
    ext: bool = False
    label: str | None = None


@app.get("/api/autore/protocols")
def autore_protocols():
    return {"protocols": list_protocols()}


@app.post("/api/autore/analyze-log")
def autore_analyze_log(req: AutoReAnalyzeReq):
    """Mode 1: run a recorded log through the RE session, return the A/B/C report."""
    global auto_session
    try:
        auto_session = RESession(req.path)
        # numeric known-values only
        knowns = {k: float(v) for k, v in (req.known_values or {}).items()
                  if str(v).strip() not in ("", "None")}
        populate_from_log(auto_session, req.path, known_values=knowns, oem_db=oem)
        return {"ok": True, "report": auto_session.report()}
    except Exception as exc:
        return _err(str(exc))


@app.get("/api/autore/report")
def autore_report():
    return auto_session.report()


@app.post("/api/autore/confirm")
def autore_confirm(req: SignalRef):
    auto_session.confirm(req.frame_id, req.start_bit, req.length,
                         byte_order=req.byte_order, ext=req.ext, label=req.label)
    return {"ok": True, "report": auto_session.report()}


@app.post("/api/autore/reject")
def autore_reject(req: SignalRef):
    auto_session.reject(req.frame_id, req.start_bit, req.length,
                        byte_order=req.byte_order, ext=req.ext)
    return {"ok": True, "report": auto_session.report()}


class AutoReSaveReq(BaseModel):
    oem: str
    name: str
    tiers: list[str] = ["A"]


@app.post("/api/autore/save-profile")
def autore_save_profile(req: AutoReSaveReq):
    """Export the chosen tiers of the current session as an OEM profile."""
    try:
        model = auto_session.to_dbc_model(tuple(req.tiers))
        pid = oem.save_from_dbc_model(model, req.oem, req.name)
        return {"ok": True, "id": pid, "profile": oem.get_profile(pid)}
    except Exception as exc:
        return _err(str(exc))


# ===========================================================================
# DBC Builder
# ===========================================================================
@app.get("/api/dbc")
def dbc_get():
    return dbc.to_json()


@app.post("/api/dbc/set")
def dbc_set(req: DbcModelReq):
    dbc.load_json({"messages": req.messages})
    return {"ok": True, **dbc.to_json()}


@app.post("/api/dbc/seed")
def dbc_seed(re_id: dict):
    dbc.seed_from_re(re_id)
    return {"ok": True, **dbc.to_json()}


@app.get("/api/dbc/export")
def dbc_export():
    try:
        return PlainTextResponse(dbc.to_dbc_string(), media_type="text/plain")
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/dbc/import")
async def dbc_import(file: UploadFile = File(...)):
    try:
        dbc.import_dbc_string((await file.read()).decode("utf-8", "replace"))
        return {"ok": True, **dbc.to_json()}
    except Exception as exc:
        return _err(str(exc))


# ===========================================================================
# Signal Viewer
# ===========================================================================
@app.post("/api/signals/use-builder")
def signals_use_builder():
    try:
        viewer.load_dbc_string(dbc.to_dbc_string(), "DBC Builder model")
        return {"ok": True, **viewer.info()}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/signals/import")
async def signals_import(file: UploadFile = File(...)):
    try:
        viewer.load_dbc_string((await file.read()).decode("utf-8", "replace"), file.filename)
        return {"ok": True, **viewer.info()}
    except Exception as exc:
        return _err(str(exc))


@app.get("/api/signals")
def signals_info():
    return viewer.info()


@app.get("/api/signals/series")
def signals_series(keys: str | None = None):
    key_list = keys.split(",") if keys else None
    return viewer.series(key_list)


@app.post("/api/signals/clear")
def signals_clear():
    viewer.clear(); return {"ok": True}


class DefsReq(BaseModel):
    defs: list = []


@app.get("/api/signals/derived")
def signals_derived():
    """Computed-signal definitions + current alarm states."""
    return viewer.derived()


@app.post("/api/signals/computed")
def signals_computed(req: DefsReq):
    """Set math-channel definitions, e.g. {name, expr: \"sig('M.A')*2\"}."""
    return {"ok": True, **viewer.set_computed(req.defs)}


@app.post("/api/signals/alarms")
def signals_alarms(req: DefsReq):
    """Set threshold alarms, e.g. {name, key: \"M.Speed\", max: 120}."""
    return {"ok": True, **viewer.set_alarms(req.defs)}


# ===========================================================================
# TX Scheduler
# ===========================================================================
@app.get("/api/tx")
def tx_table():
    return scheduler.table()


@app.post("/api/tx/add")
def tx_add(req: TxAddReq):
    try:
        return {"ok": True, "entry": scheduler.add(req.id, req.data, req.cycle_ms,
                                                    req.mode, req.is_extended, req.name)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/tx/update")
def tx_update(req: TxUpdateReq):
    try:
        return {"ok": True, "entry": scheduler.update(req.uid, req.patch)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/tx/remove")
def tx_remove(uid: int):
    scheduler.remove(uid); return {"ok": True}


@app.post("/api/tx/start")
def tx_start():
    if not bus.connected:
        return _err("Connect a bus first")
    scheduler.start(bus.send); return {"ok": True}


@app.post("/api/tx/stop")
def tx_stop():
    scheduler.stop(); return {"ok": True}


@app.post("/api/tx/send-once")
def tx_send_once(uid: int):
    if not bus.connected:
        return _err("Connect a bus first")
    try:
        return {"ok": True, **scheduler.send_once(uid, bus.send)}
    except Exception as exc:
        return _err(str(exc))


# ===========================================================================
# Automation: rules, jobs, restbus simulation, scripting (Pillar C)
# ===========================================================================
class RuleReq(BaseModel):
    name: str = ""
    when: str
    action: dict
    cooldown_s: float = 0.0


@app.get("/api/rules")
def rules_table():
    return rules.table()


@app.post("/api/rules/add")
def rules_add(req: RuleReq):
    try:
        return {"ok": True, "rule": rules.add(req.name, req.when, req.action,
                                              cooldown_s=req.cooldown_s)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/rules/remove")
def rules_remove(uid: int):
    rules.remove(uid); return {"ok": True}


@app.post("/api/rules/enable")
def rules_enable(uid: int, enabled: bool = True):
    rules.set_enabled(uid, enabled); return {"ok": True}


class JobReq(BaseModel):
    name: str
    kind: str                 # scan | record
    schedule: str = ""        # "every:<seconds>" or "" for manual
    spec: dict = {}


@app.get("/api/jobs")
def jobs_list():
    return {"jobs": jobs_runner.list_jobs()}


@app.post("/api/jobs/add")
def jobs_add(req: JobReq):
    return {"ok": True, "job": jobs_runner.add_job(req.name, req.kind,
                                                   schedule=req.schedule, spec=req.spec)}


@app.post("/api/jobs/remove")
def jobs_remove(jid: int):
    jobs_runner.remove_job(jid); return {"ok": True}


@app.post("/api/jobs/enable")
def jobs_enable(jid: int, enabled: bool = True):
    jobs_runner.set_enabled(jid, enabled); return {"ok": True}


@app.post("/api/jobs/run")
def jobs_run(jid: int):
    try:
        return {"ok": True, "result": jobs_runner.run_now(jid)}
    except Exception as exc:
        return _err(str(exc))


# ----- restbus simulation --------------------------------------------------
@app.post("/api/restbus/load-builder")
def restbus_load_builder():
    """Build the restbus plan from the current DBC Builder model."""
    try:
        import cantools
        db = cantools.database.load_string(dbc.to_dbc_string(), database_format="dbc")
        return {"ok": True, **restbus.load_db(db)}
    except Exception as exc:
        return _err(str(exc))


class RestbusProfileReq(BaseModel):
    profile_id: int


@app.post("/api/restbus/load-profile")
def restbus_load_profile(req: RestbusProfileReq):
    p = oem.get_profile(req.profile_id)
    if not p or not p.get("dbc"):
        return _err("Profile has no DBC")
    try:
        import cantools
        db = cantools.database.load_string(p["dbc"], database_format="dbc")
        return {"ok": True, **restbus.load_db(db)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/restbus/start")
def restbus_start():
    if not bus.connected:
        return _err("Connect a bus first")
    return {"ok": True, **restbus.start()}


@app.post("/api/restbus/stop")
def restbus_stop():
    return {"ok": True, **restbus.stop()}


@app.get("/api/restbus/status")
def restbus_status():
    return restbus.status()


# ----- scripting -----------------------------------------------------------
class ScriptReq(BaseModel):
    code: str
    timeout: float = 5.0


@app.post("/api/script/run")
def script_run(req: ScriptReq):
    send = bus.send if bus.connected else None
    ctx = ScriptContext(send=send, latest=lambda k, d=None: viewer._latest.get(k, d))
    return {"ok": True, **run_script(req.code, ctx, timeout=min(req.timeout, 15.0))}


# ===========================================================================
# Protocol Decoder
# ===========================================================================
@app.get("/api/decode/live")
def decode_live():
    return {"connected": bus.connected, "frames": list(proto_recent)}


@app.post("/api/decode/clear")
def decode_clear():
    proto_recent.clear()
    return {"ok": True}


@app.post("/api/decode/frame")
def decode_frame(req: DecodeReq):
    try:
        data = bytes(int(b, 16) for b in req.data.replace(",", " ").split())
        return {"ok": True, "result": ProtocolDecoder().decode(req.id, data, req.is_extended)}
    except Exception as exc:
        return _err(str(exc))


# ----- Frame decoder (BusMaster-style byte/bit view) -----------------------
# Two interchangeable signal sources feed the SAME decode UI:
#   • a DBC  → cantools DB, decoded by framedecode (full: enums/min-max/units)
#   • a cloud Signature JSON → jsondecode (limited; no cantools needed)
# Only one is active at a time; loading one clears the other.
import cantools as _cantools           # noqa: E402  (local to this feature)
from .framedecode import decode_frames as _decode_frames
from . import jsondecode as _jsondecode

_decode_db = None                      # cantools DB (DBC source)
_decode_json = None                    # signature message map (JSON source)


@app.post("/api/decode/dbc-import")
async def decode_dbc_import(file: UploadFile = File(...)):
    """Load a DBC for the frame decoder; returns its message/signal catalogue."""
    global _decode_db, _decode_json
    try:
        text = (await file.read()).decode("utf-8", "replace")
        _decode_db = _cantools.database.load_string(text, database_format="dbc")
        _decode_json = None            # DBC now active; drop any JSON source
        msgs = [{"id_hex": f"{m.frame_id:X}", "name": m.name, "length": m.length,
                 "signals": [s.name for s in m.signals]} for m in _decode_db.messages]
        return {"ok": True, "dbc": file.filename, "messages": msgs}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/decode/json-import")
async def decode_json_import(file: UploadFile = File(...)):
    """Load a cloud Signature JSON for the frame decoder; returns its catalogue.

    Format: ``{"<decimal_id>": [{fieldName, startingBit, size, multiplier,
    offset, signed, reverse, evData}, ...], ...}``. See ``jsondecode`` and
    ``docs/JSON_SIGNATURE_DECODE.md`` for the (validated) bit/byte convention.
    """
    global _decode_db, _decode_json
    try:
        text = (await file.read()).decode("utf-8", "replace")
        _decode_json = _jsondecode.load_signature(text)
        _decode_db = None              # JSON now active; drop any DBC source
        return {"ok": True, "json": file.filename,
                "messages": _jsondecode.signature_messages(_decode_json)}
    except Exception as exc:
        return _err(str(exc))


class DecodeFramesReq(BaseModel):
    frames: list = []                  # [{id: "94"|148, data: "0006320040001C00"}]


@app.post("/api/decode/frames")
def decode_frames_route(req: DecodeFramesReq):
    if _decode_json is not None:
        return {"ok": True, "frames": _jsondecode.decode_frames(_decode_json, req.frames)}
    if _decode_db is not None:
        return {"ok": True, "frames": _decode_frames(_decode_db, req.frames)}
    return _err("Upload a .dbc or .json first")


# ----- Format converter (DBC ⇄ JSON ⇄ CSV) ---------------------------------
from . import convert as _convert_mod


@app.post("/api/convert")
async def convert_route(to: str, file: UploadFile = File(...), src: str | None = None):
    """One-shot convert an uploaded DBC / Signature-JSON / CSV to format ``to``.

    Source format auto-detected from the filename/content unless ``src`` given.
    Returns the converted text plus a summary and any (loss) warnings.
    """
    try:
        text = (await file.read()).decode("utf-8", "replace")
        res = _convert_mod.convert(text, to_fmt=to, from_fmt=src, filename=file.filename or "")
    except Exception as exc:
        return _err(str(exc))
    stem = (file.filename or "converted").rsplit(".", 1)[0] or "converted"
    return {"ok": True, "filename": f"{stem}.{to}", "content": res["content"],
            "warnings": res["warnings"], "summary": res["summary"]}


@app.post("/api/convert/parse")
async def convert_parse_route(file: UploadFile = File(...), src: str | None = None):
    """Parse an uploaded file into the editable canonical model (workbench)."""
    try:
        text = (await file.read()).decode("utf-8", "replace")
        res = _convert_mod.parse(text, from_fmt=src, filename=file.filename or "")
    except Exception as exc:
        return _err(str(exc))
    stem = (file.filename or "converted").rsplit(".", 1)[0] or "converted"
    return {"ok": True, "source_fmt": res["from"], "source_name": stem,
            "model": res["model"], "warnings": res["warnings"], "summary": res["summary"]}


class ConvertExportReq(BaseModel):
    model: dict
    to: str
    source_name: str | None = "converted"


@app.post("/api/convert/export")
def convert_export_route(req: ConvertExportReq):
    """Serialize an edited/filtered canonical model to ``to`` with a stamped name."""
    import datetime
    try:
        res = _convert_mod.serialize(req.model, req.to)
    except Exception as exc:
        return _err(str(exc))
    ts = datetime.datetime.now().strftime("%d%m%y_%H%M%S")
    stem = (req.source_name or "converted").strip() or "converted"
    prefix = "Signature_" if req.to == "json" else ""    # JSON = cloud Signature file
    return {"ok": True, "filename": f"{prefix}{stem}_{ts}.{req.to}",
            "content": res["content"], "warnings": res["warnings"]}


# ===========================================================================
# Dashboard (standard decoded values)
# ===========================================================================
@app.get("/api/dashboard")
def dashboard_get():
    return {"connected": bus.connected, **dashboard.snapshot()}


@app.post("/api/dashboard/clear")
def dashboard_clear():
    dashboard.clear()
    return {"ok": True}


# ===========================================================================
# Diagnostic Trouble Codes
# ===========================================================================
@app.get("/api/dtc")
def dtc_get():
    return {"connected": bus.connected, **dtc.snapshot()}


@app.post("/api/dtc/clear")
def dtc_clear():
    """Clear the locally collected DTC list (does not touch the vehicle)."""
    dtc.clear()
    return {"ok": True}


@app.post("/api/dtc/scan")
def dtc_scan():
    """Transmit standard DTC requests (OBD-II Mode 03 & 07, J1939 DM1 request)."""
    if not bus.connected:
        return _err("Connect a bus first")
    try:
        # OBD-II functional requests on 0x7DF (single frame: len, mode).
        bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                             data=bytes([0x01, 0x03, 0, 0, 0, 0, 0, 0])))   # stored
        bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                             data=bytes([0x01, 0x07, 0, 0, 0, 0, 0, 0])))   # pending
        # J1939 request for DM1 (PGN 0xEA00, requested PGN 0xFECA little-endian, global dest).
        req_id = (6 << 26) | (0xEA << 16) | (0xFF << 8) | 0xF9
        bus.send(can.Message(arbitration_id=req_id, is_extended_id=True,
                             data=bytes([0xCA, 0xFE, 0x00])))
        return {"ok": True}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/dtc/clear-ecu")
def dtc_clear_ecu():
    """Send OBD-II Mode 04 (clear DTCs) to the vehicle — a real write action."""
    if not bus.connected:
        return _err("Connect a bus first")
    try:
        bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                             data=bytes([0x01, 0x04, 0, 0, 0, 0, 0, 0])))
        return {"ok": True}
    except Exception as exc:
        return _err(str(exc))


# ===========================================================================
# Live WebSocket (CAN Logger)
# ===========================================================================
@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            # Capture the logger reference once: a concurrent disconnect can swap
            # bus.logger to None between an `if` check and the deref.
            logger = bus.logger
            payload = logger.snapshot() if logger else {"running": False}
            payload["connected"] = bus.connected
            payload["replay"] = replayer.status()
            await ws.send_json(payload)
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, Exception):
        return


# ----- static UI (mounted last) --------------------------------------------
# Serve index.html through a route so the single app __version__ is injected into
# the asset URLs (?v=) — one version number drives both the UI chip and cache-busting.
_INDEX_PATH = os.path.join(WEB_DIR, "index.html")


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def _serve_index():
    try:
        with open(_INDEX_PATH, encoding="utf-8") as fh:
            return HTMLResponse(fh.read().replace("__VER__", __version__))
    except OSError:
        return HTMLResponse("<h1>uCANdo</h1><p>UI not found.</p>", status_code=500)


if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
