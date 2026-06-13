"""FastAPI application: REST control plane + live WebSocket + static UI.

Holds one instance of every subsystem and the single :class:`BusManager`.
Subsystems that observe live traffic (Signal Viewer, Protocol monitor) register
a tap on the bus manager so they survive reconnects; subsystems that transmit
(Replay, TX Scheduler) call ``bus.send``.
"""

from __future__ import annotations

import asyncio
import os
from collections import deque

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __app_name__, __version__
from .bus_manager import BusManager
import can

from .config import Config
from .dashboard import Dashboard
from .device_enum import enumerate_all
from .dbc_builder import DbcModel
from .dtc import DtcMonitor
from .protocol import ProtocolDecoder
from .registry import describe_all, load_plugins
from .replay import LogReplayer
from .reverse import analyze_log
from .scheduler import TxScheduler
from .signals import SignalViewer
from .storage import Storage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
for d in (LOG_DIR, UPLOAD_DIR):
    os.makedirs(d, exist_ok=True)

app = FastAPI(title=f"{__app_name__} API", version=__version__)

# ----- foundation rails (persistence, config, plugins) ---------------------
storage = Storage()
config = Config(storage)
loaded_plugins = load_plugins()   # auto-imports canforge/plugins/* (self-register)

# ----- subsystems ----------------------------------------------------------
bus = BusManager()
replayer = LogReplayer()
scheduler = TxScheduler()
dbc = DbcModel()
viewer = SignalViewer()
dashboard = Dashboard()
dtc = DtcMonitor()

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


@app.post("/api/connect")
def connect(req: ConnectReq):
    try:
        return {"ok": True, "connection": bus.connect(req.hw, req.channel, req.bitrate, req.fd, req.simulate)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/disconnect")
def disconnect():
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


@app.post("/api/logger/record/start")
def record_start(req: RecordReq):
    if not bus.logger:
        return _err("Not connected")
    path = os.path.join(LOG_DIR, req.name or "capture")
    try:
        return {"ok": True, **bus.logger.start_recording(req.format, path)}
    except Exception as exc:
        return _err(str(exc))


@app.post("/api/logger/record/stop")
def record_stop():
    if not bus.logger:
        return _err("Not connected")
    return {"ok": True, **bus.logger.stop_recording()}


@app.get("/api/logs")
def list_logs():
    out = []
    for base in (LOG_DIR, UPLOAD_DIR):
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
@app.post("/api/re/analyze")
def re_analyze(req: PathReq):
    try:
        return {"ok": True, "result": analyze_log(req.path)}
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
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
