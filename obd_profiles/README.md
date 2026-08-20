# OBD profiles — diagnostic databases for gateway-isolated vehicles

Some vehicles broadcast **nothing** on the OBD-2 connector. A gateway firewalls
the internal buses, and the only traffic on pins 6/14 is diagnostic
request/response — which means **a passive listener sees an empty bus, and only a
tool that asks questions gets answers.**

Those cars cannot have an `oem_packs/` entry, because there is no broadcast bus
to describe. What they *can* have is a **diagnostic profile**: which PIDs this
vehicle's ECUs actually answer, how to ask, and how to decode the reply. That is
what lives here.

```
obd_profiles/
└── <Make>/
    └── <make>_<model>_<fuel>_<year>_obd.dbc
```

## Why these are not in `oem_packs/`

`oem_packs/` feeds auto-identify. A profile whose IDs are `0x7DF`/`0x7E8` would
match **any** vehicle that happens to have a scan tool plugged in — a
false-positive machine. Worse, `oem_db.prune_blank()` *repairs* an empty
signature by deriving one from the DBC, so it cannot simply be suppressed with a
blank `signature.json`.

**Identify a gated vehicle by its VIN instead**, which is exact rather than a
similarity score. That is what `vehicle.json` and `identify_from_vin()` are for.

## Current contents

| Make | Vehicle | File | Source |
|---|---|---|---|
| Suzuki | Dzire petrol 2026 | `suzuki_dzire_petrol_2026_obd.dbc` | [docs/SUZUKI_DZIRE_2026_GATEWAY.md](../docs/SUZUKI_DZIRE_2026_GATEWAY.md) |

---

# Maruti Suzuki Dzire 2026 — how to talk to it

Bus: **ISO 15765-4 CAN, 11-bit IDs, 500 kbit/s.** Confirmed VIN
`MA3ZFDFSK…` (prefix only).

## 1. How to find out what a vehicle will answer — ask it

Do not guess PIDs, and do not poll all 256. **Every OBD-II ECU publishes a bitmap
of the PIDs it supports.** Four requests give you the whole map:

| Ask on `0x7DF` | Returns support for |
|---|---|
| `02 01 00 00 00 00 00 00` | PIDs 01–20 |
| `02 01 20 00 00 00 00 00` | PIDs 21–40 |
| `02 01 40 00 00 00 00 00` | PIDs 41–60 |
| `02 01 60 00 00 00 00 00` | PIDs 61–80 |

The reply is 4 data bytes, **MSB first = lowest PID**. If bit 31 of the `PID 00`
reply is set, PID 01 is supported; bit 30 → PID 02, and so on. The last bit of
each bitmap says whether the *next* bitmap exists — so keep walking while it is
set.

**This car's answers:**

| Responder | `PID 00` | `PID 20` | `PID 40` |
|---|---|---|---|
| `0x7E8` ECM | `BE 3F A8 13` | `80 15 B0 01` | `6A D0 00 00` |
| `0x7EE` module 2 | `80 00 00 01` | `80 01 80 01` | `40 00 00 00` |

Decoded: the **ECM supports 33 PIDs**, the second module supports **7**.

> A bitmap is a *claim*. 20 of the ECM's PIDs were seen answering in the capture;
> 11 more are claimed but were never polled. Trust the confirmed ones; try the
> claimed ones and verify.

## 2. Requests that work on this car

Every Mode-01 read is three bytes padded to eight: `02 01 <PID>`, sent to
**`0x7DF`**. Replies arrive on `0x7E8` (and `0x7EE` for its seven).

**Confirmed answering** — request frame on the left:

| Request | PID | Parameter | Decode |
|---|---|---|---|
| `02 01 04` | 04 | Calculated engine load | `A·100/255` % |
| `02 01 05` | 05 | Coolant temperature | `A−40` °C |
| `02 01 06` | 06 | Short-term fuel trim B1 | `A·100/128−100` % |
| `02 01 0B` | 0B | Intake manifold pressure | `A` kPa |
| `02 01 0C` | 0C | **Engine RPM** | `(A·256+B)/4` |
| `02 01 0D` | 0D | Vehicle speed | `A` km/h |
| `02 01 0E` | 0E | Timing advance | `A/2−64` ° |
| `02 01 0F` | 0F | Intake air temperature | `A−40` °C |
| `02 01 10` | 10 | MAF rate | `(A·256+B)/100` g/s |
| `02 01 11` | 11 | Throttle position | `A·100/255` % |
| `02 01 1F` | 1F | Run time since start | `A·256+B` s |
| `02 01 21` | 21 | Distance with MIL on | `A·256+B` km |
| `02 01 2C` | 2C | Commanded EGR | `A·100/255` % |
| `02 01 31` | 31 | Distance since codes cleared | `A·256+B` km |
| `02 01 33` | 33 | Barometric pressure | `A` kPa |
| `02 01 42` | 42 | Control module voltage | `(A·256+B)/1000` V |
| `02 01 43` | 43 | Absolute load | `(A·256+B)·100/255` % |
| `02 01 47` | 47 | Absolute throttle B | `A·100/255` % |
| `02 01 4A` | 4A | Accelerator pedal E | `A·100/255` % |
| `01 03` | — | Read stored DTCs | `43 00` = none |

**Claimed but untested** (should answer; verify before relying on them):
`03 07 13 15 1C 2E 30 34 45 49 4C`.

**Polling rate:** the reference session ran ~20 PIDs on a loop at **~85 ms per
request** with no dropped replies. That is a safe working rate.

## 3. The VIN — the one that catches people out

This vehicle **ignores** the two obvious requests:

| Request | Result |
|---|---|
| `02 09 02` — OBD-II Mode 09 VIN | **no reply** |
| `02 1A 90` — KWP ReadEcuIdentification | **no reply** |
| `03 22 F1 90` — **UDS ReadDataByIdentifier, DID F190** | **answers** |

And it must be sent to the **physical** ECM address `0x7E0`, not `0x7DF`. The
reply is multi-frame, so the tester has to send flow control:

```
0x7E0 →  03 22 F1 90 00 00 00 00      request
0x7E8 ←  10 14 62 F1 90 4D 41 33      First frame: 0x14 = 20 bytes, "MA3"
0x7E0 →  30 00 00 00 00 00 00 00      Flow control: send the rest
0x7E8 ←  21 5A 46 44 46 53 4B 54      "ZFDFSKT"
0x7E8 ←  22 46 35 31 33 31 38 34      "F513184"
```

Strip the PCI byte from each frame, concatenate, drop the `62 F1 90` header, and
the remaining 17 bytes are the ASCII VIN.

**If your device shows no VIN, it is probably sending Mode 09 and giving up, or
not sending flow control.**

## 4. What you cannot get here

- **The odometer.** Generic OBD-II has no odometer PID, and this vehicle exposes
  no manufacturer PID for it. A Teltonika in the same session showed
  `OEM Total Mileage 0 km` and `No OEM file found`. The nearest available figure
  is `PID 31` distance-since-codes-cleared, which is **not** the odometer.
- **Anything only on the internal bus** — doors, lights, seatbelt, fuel level,
  indicators. On the older Dzire and the WagonR these came from broadcast
  frames. Reading them on this car needs a tap **behind the gateway**.

## 5. Using the DBC

`suzuki_dzire_petrol_2026_obd.dbc` models the exchange with `ParameterID` as a
**multiplexor**, which is the standard way to express OBD-II in a DBC. It loads
in cantools, Vector CANdb++, PCAN-Explorer, BUSMASTER and SavvyCAN, and every
signal comment records whether that PID was **CONFIRMED** answering or only
**CLAIMED** by the bitmap.

Validated by decoding the real capture: **0 decode errors across every
single-frame message**, 23 ECM signals recovered, and all 15 values that the
Teltonika displayed in the same session reproduced within tolerance.

> **One limitation, by design:** a DBC cannot decode the multi-frame VIN. In an
> ISO-TP First or Consecutive frame, byte 2 is payload, not a PID, so the
> multiplexor is meaningless. Use §3 and an ISO-TP reassembler for that — in this
> repo, `ucando/protocol.py`.

## 6. If your device takes a config rather than a DBC

Many telematics units (Teltonika among them) do not accept DBCs. Everything they
need is in §2 and §3: the request bytes, the responder ID, and the decode
formula. Configure the PID list from the **confirmed** column, poll no faster
than ~85 ms per request, and request the VIN per §3.
