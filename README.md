# CANForge — Unified CAN Workbench

A hardware-agnostic CAN bus utility for day-to-day automotive engineering.
One app, three adapters (Intrepid **Neo VI**, **PCAN**, **Microchip/SLCAN**),
plus a built-in **virtual bus** for development without hardware.

## Status

| Module | State |
|---|---|
| **Dashboard** — live OBD-II PID + J1939 SPN values, no DBC needed | ✅ done |
| **DTC Codes** — OBD-II (03/07/0A), UDS 0x19, J1939 DM1/DM2 + scan/clear | ✅ done |
| HAL + device enumeration | ✅ done |
| **CAN Logger** — capture, per-ID stats, record `.asc`/`.blf`/`.csv` | ✅ done |
| **TX Replay** — load a log, play/pause/loop/speed/filter/step | ✅ done |
| **Reverse Engineering** — per-ID entropy/bit-flip + candidate signals | ✅ done |
| **DBC Builder** — signal editor, import/export `.dbc`, seed from RE | ✅ done |
| **Signal Viewer** — live decode via DBC + strip charts | ✅ done |
| **TX Scheduler** — cyclic / one-shot predefined frames | ✅ done |
| **Protocol Decoder** — OBD-II, UDS (ISO-TP), J1939 | ✅ done |

## Architecture

```
hal.py            CANInterface abstraction + create_interface() factory
device_enum.py    enumerate adapters that are actually present
sim.py            synthetic traffic feeder for the virtual bus (dev)
logger.py         CanLogger — receive thread, stats, recording, frame taps
replay.py         LogReplayer — timed log playback with speed/loop/filter
reverse.py        analyze_log — entropy / bit-flip / candidate-signal finder
dbc_builder.py    DbcModel — edit + import/export .dbc (cantools), seed from RE
signals.py        SignalViewer — live DBC decode into time-series buffers
dashboard.py      Dashboard — standard OBD-II PID + J1939 SPN live values
dtc.py            DtcMonitor — trouble codes (OBD-II / UDS 0x19 / J1939 DM1·DM2)
scheduler.py      TxScheduler — cyclic / one-shot frame transmission
protocol.py       ProtocolDecoder — OBD-II / UDS (ISO-TP) / J1939
bus_manager.py    one BusManager: connect / disconnect / status / taps / send
server.py         FastAPI REST + /ws/live WebSocket + static UI
web/              dark single-page UI (all module screens)
main.py           launches uvicorn and opens the browser
```

Everything above the HAL is adapter-independent — modules talk only to
`CANInterface`, never to `can.Bus` directly. Observers (Signal Viewer,
Protocol Decoder) register a **frame tap** on the logger; transmitters (TX
Replay, TX Scheduler) call `BusManager.send`.

### The capture → analyze → transmit loop

The modules chain: **Logger** records `.asc`/`.blf` → **RE** finds candidate
signals in that log → **DBC Builder** turns candidates into a `.dbc` →
**Signal Viewer** decodes the live bus with that `.dbc` → **TX Replay** /
**Scheduler** transmit recorded or synthesized frames back onto the bus.

## Run

```powershell
pip install -r requirements.txt
python main.py
```

Opens `http://127.0.0.1:8765`. Click **Connect → Virtual bus (development)**
to capture synthetic traffic immediately, no hardware needed.

### Real hardware

- **Neo VI** — `pip install python-ics` (the `ics` library). Channel `1` = HSCAN1.
- **PCAN** — install the PEAK PCAN-Basic driver; channels are `PCAN_USBBUS1..16`.
- **Microchip** — flash the analyzer with SLCAN firmware; it appears as a COM port.

Recorded logs are written to `data/logs/`.
