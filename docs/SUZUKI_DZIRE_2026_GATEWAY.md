# Maruti Suzuki Dzire 2026 — a gateway-isolated OBD port (2026-08-20)

**There is no reverse-engineering artifact from this vehicle, and that is the
finding.** This record exists to explain why, and to say what uCANdo has to do
differently to be useful on cars built this way.

Capture: `data/uploads/Swift dzire 2026/` — Vehicle Spy 3 / neoVI 3G on the OBD-2
port, HS CAN @ 500 kbit/s. Two files; **`DIZER1` is an exact byte-prefix of
`DIZER2`**, so they are one 338 s session saved twice, not two runs.

## 1. The question

> Nothing appears on the data lines at the OBD port. Plug in a different OBD-2
> CAN analyzer and the data is there.

Both observations are correct, and they are not in conflict.

## 2. The answer

**This vehicle's OBD-2 port carries diagnostics only. It carries no vehicle
broadcast traffic at all.** The whole 338 s capture contains exactly **four**
arbitration IDs:

| ID | Role | Frames |
|---|---|---|
| `0x7DF` | OBD-II functional **request** (tester → all ECUs) | 3 991 |
| `0x7E0` | UDS physical **request** + ISO-TP flow control (tester → ECM) | 2 |
| `0x7E8` | ECM **response** | 3 964 |
| `0x7EE` | second module **response** | 876 |

Every single frame is either a question or an answer. **Not one frame is a
vehicle broadcast.** None of `0x120`, `0x122`, `0x124`, `0x310`, `0x460`, `0x500`
— the Suzuki map that the 2018-era Dzire and the WagonR both broadcast freely
onto their OBD connectors — appears here.

So:

- **A passive listener sees nothing, and that is correct behaviour, not a fault.**
  uCANdo recording this port has nothing to record until something asks a
  question.
- **The other analyzer sees data because it is a scan tool, not a sniffer.** It
  *transmits* `0x7DF` Mode-01 requests in a loop at ~85 ms and displays the
  replies. It is generating the traffic it shows you. One of the session photos
  identifies it: a **Teltonika FMB001** in OBD-II mode.

The capture proves this rather than infers it — the neoVI was sniffing the same
wire while the FMB001 polled, so the requests are visible in the log.

### It is not a wiring, bitrate or termination problem

Worth ruling out explicitly, because those are the usual suspects:

- The neoVI exchanged nothing but **still saw** the FMB001's traffic on the same
  pins at 500 kbit/s — so pins, bitrate and termination are all correct.
- The Vehicle Spy screenshot reports **"No Bus Errors"**.
- If the bitrate were wrong we would see error frames, not clean traffic.

This is a **gateway** decision by the vehicle, not a fault in the setup. It is
the direction the whole industry is moving under UN R155 / R156 cybersecurity
rules: the OBD connector is firewalled from the internal buses, and only a
diagnostic session reaches through.

## 3. What IS available, and what is not

The ECM (`0x7E8`) supports **33 PIDs**; the second module (`0x7EE`) supports 7.

| Available (Mode 01) | Observed in this session |
|---|---|
| Engine RPM | 745.5 – 982.0 |
| Coolant temperature | 93 °C (constant) |
| Intake air temperature | 68 – 69 °C |
| Calculated engine load | 20.8 – 40.8 % |
| Absolute load | 16.1 – 31.4 % |
| Manifold pressure | 35 – 61 kPa |
| Timing advance | −15.5 – +16.5 ° |
| MAF rate | 0.69 – 4.89 g/s |
| Short-term fuel trim | −3.9 – +3.9 % |
| Vehicle speed | 0 (stationary throughout) |
| Run time since start | 1351 – 1677 s |
| Barometric pressure | 98 kPa |
| Control module voltage | 13.21 – 13.78 V |
| Commanded EGR, distance-with-MIL | 0 |
| Distance since codes cleared | 5214 km |

**Stored DTCs: none** (Mode 03 → `43 00` from both ECUs).

**Not available:** the odometer. The Teltonika screen shows `OEM Total Mileage
0 km` and, at the top of its OBD panel, **"No OEM file found"** — with no
manufacturer profile it falls back to generic OBD-II, and generic OBD-II has no
odometer PID. On the older Dzire and the WagonR the odometer came from the
*broadcast* frame `0x460`, which this car does not expose.

### The VIN is available — but not where you would first look

The tool asked for the VIN three different ways. Two were ignored:

- **OBD-II Mode 09 PID 02** (the standard VIN request) — asked twice, **no reply**.
- **KWP `1A 90`** — asked four times, **no reply**.
- **UDS `22 F1 90`** on the *physical* address `0x7E0` — **answered**.

The answer is a multi-frame ISO-TP exchange, and it only completes because the
tester sends a flow-control frame:

```
0x7E0 →  03 22 F1 90                     ReadDataByIdentifier, DID F190
0x7E8 ←  10 14 62 F1 90 4D 41 33         First frame, 20 bytes, "MA3"
0x7E0 →  30 00 00                        Flow control: continue
0x7E8 ←  21 5A 46 44 46 53 4B 54         "ZFDFSKT"
0x7E8 ←  22 46 35 31 33 31 38 34         "F513184"
```

**VIN = `MA3ZFDFSKTF513184`** — reassembled from the raw frames here, and matching
the Teltonika screen character for character.

> **Practical rule:** on a gated car, request the VIN with **UDS `22 F190` on the
> physical ECU address**, and be ready to send flow control. Mode 09 may simply
> be ignored.

## 4. A VIN model-year finding

`oem_packs/README.md` carries a hard-won warning: *never infer the model year
from a VIN for MG India* — the Windsor Pro reads `8` (ISO: 2008) on a confirmed
2026 car. That warning is MG-specific, and this capture gives the first
**confirmed** Maruti data point pointing the other way.

| Vehicle | VIN pos. 10 | ISO 3779 | Actual |
|---|---|---|---|
| Dzire (this car) | `T` | **2026** | **2026 — confirmed** |
| Dzire (earlier pack) | `J` | 2018 | consistent with 3rd-gen + 201 618 km |
| WagonR | `N` | 2022 | consistent with 3rd-gen |

**Maruti Suzuki India appears to follow the ISO year code where MG does not.**
One confirmation plus two consistent cases is suggestive, not conclusive, so the
`Petrol/` and `CNG/` folders still carry no year. **Recommendation:** collect the
year from one more Maruti with independent proof (registration or build plate),
and if it holds, rename those folders and record the marque-specific rule
alongside the MG one. That is a naming decision with artifact consequences, so
it is flagged here rather than made unilaterally.

## 5. What this means for uCANdo — a real capability gap

This vehicle class is where the India fleet/telematics market is heading, so this
matters more than one car.

**uCANdo is passive where it needs to be active.**

- `Dashboard` is fed by a **bus tap** (`bus.add_tap(dashboard.consume)`). It
  decodes OBD PID *responses* that happen to be on the wire but never *asks*. On
  a gated car it stays empty forever — which is exactly what was observed.
- The polling logic **already exists**, in `ucando/cli.py` `cmd_drive`: a loop
  transmitting nine PIDs on `0x7DF` every 200 ms. It lives only in the headless
  CLI, not in the server or the UI.
- `/api/dtc/scan` is the one active requester in the app, and it sends Mode 03/07
  only.
- **Nothing in the codebase transmits an ISO-TP flow-control frame.**
  `protocol.py` *reassembles* First + Consecutive frames passively, but a tester
  must *send* `0x30` to receive them. So uCANdo can watch someone else read a
  VIN and cannot read one itself. `vin.py` and `server.py` already document that
  the VIN lives at Mode 09 / `F190` — the knowledge is there, the requester is
  not.

Three changes would make the tool work on this car:

1. **An active OBD-II PID poller in the server**, start/stop from the Dashboard,
   reusing the `cmd_drive` loop. Poll only PIDs the ECU reports as supported
   (`PID 00/20/40/60` bitmaps) rather than blindly.
2. **An ISO-TP tester**: send a request, reply with flow control, reassemble.
   That unlocks VIN and every UDS DID, and is a prerequisite for a real UDS
   client (already on the Phase 6 list).
3. **Say so in the UI.** A connected bus with zero frames currently looks broken.
   It should read as *"connected, no broadcast traffic — this port may be
   gateway-isolated; start an OBD poll"* — the same honesty principle as the
   nav-readiness pills.

## 6. The deliverable: an OBD diagnostic profile

There is no `oem_packs/` entry, but there **is** a usable database:
`obd_profiles/Suzuki/suzuki_dzire_petrol_2026_obd.dbc`, with the practical
request/response reference in [obd_profiles/README.md](../obd_profiles/README.md).

It models the exchange with `ParameterID` as a DBC **multiplexor** (the standard
OBD-II idiom) and records per signal whether that PID was **confirmed answering**
(20) or only **claimed by the ECU's bitmap** (11). Validated against this
capture: 0 decode errors on every single-frame message, 23 ECM signals recovered,
and all 15 values shown on the Teltonika screen in the same session reproduced.

**The general method for "which PIDs will answer?"** is in that README §1: ask
the vehicle. `02 01 00`, `02 01 20`, `02 01 40`, `02 01 60` return bitmaps of
supported PIDs, MSB = lowest PID, and the last bit of each says whether the next
bitmap exists. Never guess, never sweep all 256.

## 7. Why there is no oem_pack

`oem_packs/` describes **vehicle broadcast buses**. This car exposes none, so a
DBC would either be empty or would describe `0x7DF`/`0x7E8` — which is generic
OBD-II that `dashboard.py` already decodes for every vehicle, and is not
vehicle-specific knowledge. Shipping that as a "Dzire 2026 pack" would imply a
decode that does not exist.

**To pack this vehicle you must tap an internal bus**, not the OBD connector —
behind the gateway, at the ECM or the instrument cluster. `oem_packs/README.md`
already supports this: two taps on one vehicle go in the same leaf folder with a
tap suffix (`..._obd.dbc`, `..._ecm.dbc`).

## 8. Next steps

1. **Tap an internal bus** (cluster or ECM harness) if a broadcast-level decode
   of this vehicle is wanted. Nothing at the OBD port will ever give it.
2. **Build the active OBD poller** (§5). It is the difference between uCANdo
   working and not working on every gated vehicle, and most of the code exists.
3. **Re-poll while driving.** Everything here is stationary idle; PID 0D never
   left 0.
4. **Confirm the Maruti VIN year rule** on one more car (§4).

## 9. An analysis trap worth remembering

Two ECUs answer the same PID with different values. Collapsing `0x7E8` and
`0x7EE` into one series made PID 31 look like *"5214 → 5217 km, the car moved
3 km"*. It did not: each ECU reports its own constant (ECM 5214, second module
5217) and vehicle speed was 0 for all 338 s. **Always key OBD responses by
responder ID**, or you will manufacture signal out of two constants.
