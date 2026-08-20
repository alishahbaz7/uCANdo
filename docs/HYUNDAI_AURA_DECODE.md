# Hyundai Aura (petrol + CNG bi-fuel) — CAN decode (2026-08-20)

Reverse-engineering record for a **Hyundai Aura petrol + CNG (bi-fuel)**,
captured with **Vehicle Spy 3 / neoVI 3G** on the OBD-2 port. Artefact:
`oem_packs/Hyundai/Aura/CNG_2024/hyundai_aura_cng_2024.dbc`
(**9 messages, 15 signals**).

> **This is a bi-fuel CNG vehicle, not the petrol car of the `Petrol_2023` pack.**
> Two independent signs say so: OBD-II PID 51 reported **fuel type 13 = "bifuel
> running CNG"**, and the cluster photo shows a **CNG · PETROL** indicator with CNG
> active, a dedicated CNG gauge under the tachometer, and the petrol gauge near
> empty with its low-fuel lamp lit. An earlier revision of this record wrongly
> merged these findings into `Petrol_2023`; they now live in their own pack. The
> two share a bus map — the petrol pack's three signals decode correctly here —
> and each records that.

Conventions: `.claude/skills/dbc-pack/SKILL.md`. Confidence: **A = 4, B = 10,
C = 1**.

> **This is the first capture set in the library with the vehicle in motion**, and
> it settles the question every other pack left open: the odometer quantum, and
> the scale of speed and wheel-speed signals. Those had been unverifiable on every
> previous vehicle because none of them ever moved.

## 1. Capture set

`data/uploads/Aura/Aura/` — 17 Vehicle Spy 3 files, one HS CAN at 500 kbit/s,
**30 IDs identical in every file**, ~940 000 frames. No scan-tool traffic: this
vehicle broadcasts freely on the OBD-2 connector, unlike the 2026 Dzire.

| Group | Files | Purpose |
|---|---|---|
| `Normal data` | 1 | baseline, ignition on, idling |
| `RPM` | 1 | engine revved to redline |
| Event-isolated | 11 | seat belt, brake, parking brake, clutch, gear, driver door, passenger door, AC, headlight, hazard, blinker |
| **`Moving`** | **4** | **a 1.1 km drive, with the odometer recorded either side** |

### Ground truth

**`Moving/odo.txt`** — `Start 40241`, `End 40243`. The single most valuable line
in the dataset.

**A Teltonika FMB001** was read at 14:23, eight minutes before the captures
begin — same session, same idling engine, but **not time-aligned**, so it pins
scales rather than proving byte-exact matches: engine 931 rpm, coolant 90 °C,
intake air 64 °C, ambient 20 °C, fuel 86 %, MAP 59 kPa, throttle 7 %, 0 DTCs,
**VIN `MALB241CLSM372433`** (WMI `MAL` = Hyundai Motor India).

## 2. The odometer, and an arithmetic trap

The existing pack said `0x5B0`, 24-bit little-endian, **0.1 km**. The drive
confirms it — and shows how the obvious calculation goes wrong.

```
raw 402419  ->  40241.9 km     dash recorded 40241   (cluster floors to whole km)
raw 402430  ->  40243.0 km     dash recorded 40243
```

Both displayed integers are reproduced exactly, and the real distance covered is
**1.10 km**, not 2.

> **The trap:** dividing the *displayed* 2 km by the 11 raw counts gives
> 0.18 km/count, which is wrong. The endpoints are floored display values, not
> measurements. 0.1 km/count is the only scale that reproduces both integers *and*
> a sane absolute reading — 1 km/count would put the car at 402 419 km.

## 3. Tier A — speed and wheel speed, proved by integration

With motion available the test is not "does it look like speed" but **does
integrating it reproduce the distance the odometer recorded**.

| Signal | ID | Layout | Scale | Integrated | vs odometer |
|---|---|---|---|---|---|
| **VehicleSpeed** | `0x200` | bytes 4-5 LE, 16-bit | **1/32 km/h** | 1.162 km | +5.7 % |
| **WheelSpeed1** | `0x386` | bytes 0-1 LE, 14-bit | **1/32 km/h** | 1.150 km | +4.6 % |
| WheelSpeed2 | `0x386` | bytes 2-3 | 1/32 | 1.148 km | +4.4 % |
| WheelSpeed3 | `0x386` | bytes 4-5 | 1/32 | 1.143 km | +3.9 % |
| WheelSpeed4 | `0x386` | bytes 6-7 | 1/32 | 1.136 km | +3.3 % |

Peaks: 35.3 – 35.6 km/h, **four independent wheel sensors agreeing within
0.3 km/h**. That mutual agreement is what identifies the frame; the top 2 bits of
each 16-bit word are flags, leaving 14 bits of value.

**On the +4 % residual.** It is *inside the odometer's own resolution*: 11 counts
of 0.1 km carries about ±0.1 km, i.e. ±9 %. So 1/32 km/h is confirmed to the
precision the reference allows, and no bias can be claimed from this drive. A
longer drive would tighten it — the MG Commute record found a ~2.5 % bias the
other way over 4.1 km, which is the kind of comparison worth repeating here.

**Which wheel is which is not established.** The fields are numbered in byte
order, and the signal comment says so.

### Engine speed re-confirmed

`0x316` and `0x556`, bytes 2-3 LE, ×0.25 — carried unchanged from the 2026-06-13
pack. Idle median **929 rpm** against the device's 931; the rev capture sweeps
**905 → 5386 rpm**; the two IDs agree to under 1 rpm at idle.

## 4. Tier B — event isolation

Eleven labelled captures, one control each. A bit that steps cleanly in the
matching capture and is quiet elsewhere is identified by construction.

| Signal | ID | Bit | Evidence |
|---|---|---|---|
| **HeadlampOn** | `0x541` | byte 4 bit 0 | 5 clean cycles in the headlamp capture, **0 in all twelve others** |
| **DoorOpenDriver** | `0x541` | byte 1 bit 0 | steps only in the driver-door capture |
| **ClutchPedal** | `0x329` | byte 3 bit 7 | 10 transitions in clutch, 2 in gear, **exactly 0 in all eleven others** |
| **BrakePedal** | `0x329` | byte 4 bit 1 | 5 presses in brake, also moves in parking-brake |
| **ParkingBrake** | `0x18F` | byte 5 bit 4 | 1 for the first four captures, changes during the parking-brake test, 0 for every capture after |
| **AcCompressorOn** | `0x18F` | byte 5 bit 3 | 5 toggles in the AC capture |

**Two of these move in two captures, and that is the confirmation rather than a
weakness:**

- `ClutchPedal` moves in the clutch *and gear* captures — **you have to press the
  clutch to change gear.** A signal that moved only in the clutch capture would
  be more suspicious, not less.
- `BrakePedal` moves in the brake *and parking-brake* captures — the foot brake is
  pressed while setting the handbrake.

`AcCompressorOn` also blips once during the parking-brake capture, consistent
with the compressor cycling on its own thermostat.

`ParkingBrake` is a one-way observation: it was released during its capture and
left off, so the transition is seen once, in the right file, and the state
persists correctly afterwards.

## 5. Tier C

**`DriverSeatbeltUnfastened` — `0x547` byte 2 bit 0.** Changes in the seatbelt
capture but also in six others, which is what a belt does when people get in and
out for the door tests — consistent, not isolated. **Polarity is not
established.** Shipped as a lead.

## 6. Negative results

- **Coolant temperature not identified.** Every capture is at operating
  temperature, so it is constant, and *eight* different bytes sit at a value that
  decodes to 88-91 °C with the usual −40 offset. Nothing discriminates them. **A
  cold-start capture would isolate it in one run** — the warm-up ramp is
  unmistakable.
- **Fuel and CNG level not identified** — see §7 for the full reasoning.
- **Passenger door not isolated.** `0x541` byte 1 is clearly a door bitfield —
  bit 2 is set in three earlier captures — but the passenger-door capture moved
  no byte cleanly.
- **Turn indicators are not on this bus.** The first pass missed them by method:
  it looked for long, blocky runs, which *by construction* rejects a lamp that
  toggles every ~0.35 s. A second pass hunted specifically for blink rate —
  regular square wave, 1-2 Hz, ~50 % duty — and **every candidate came back
  irregular** (coefficient of variation on run length 1.2-2.4, i.e. jitter on the
  low bits of fast analogue bytes, not blinking). The last survivor, `0x557`
  byte 1 bits 3-4, turned out to be the middle bits of an *analogue* byte drifting
  107-122 across the session; the apparent bit toggles were it crossing bit
  boundaries. Rejected.
- **Gear position is not broadcast — demonstrated, not assumed.** The car is a
  manual, so rpm/speed is constant per gear. Over the drive that ratio resolves
  into **four clean bands** (1st ≈ 145, 2nd ≈ 85, 3rd ≈ 55, 4th ≈ 40 rpm per
  km/h; 30 / 555 / 338 / 18 samples), so the gearbox demonstrably went through
  four gears. **No byte on any of the 30 IDs is a clean function of that band.**
  Consistent with a manual gearbox, which usually has no gear-position sensor —
  at most reverse and neutral switches.
- **`0x445` is the strongest unexplained signal in the set.** A 5-bit field
  (byte 1 is always a multiple of 8) falling **25 → 9 over 33 minutes, 13 falls
  and 0 rises, one step every ~2 minutes regardless of engine load**. It is the
  only clean monotonic faller on the bus. Rejected as a fuel gauge on rate — ~12×
  too fast for CNG tank pressure and ~25× too fast for petrol — and its
  load-independence makes it look like a timer. Worth naming if anyone gets a
  longer session.
- **No VIN on the bus** — and this is a data limitation, not a capability one.
  The Teltonika got the VIN by *asking* for it over OBD; these seventeen captures
  are purely passive, with no scan tool attached, so no request and therefore no
  response exists in them. The same reassembly on the 2026 Dzire capture — where a
  tool *was* on the bus — recovered its VIN in full. **Nothing about the Aura's
  VIN is hidden; it simply was not asked for while recording.**
- **MAF, throttle position and DTC count are absent for the same reason.** The
  Teltonika reported all three because it polls OBD PIDs 10, 11 and Mode 03. MAF
  and throttle are very likely on the broadcast bus too, but with no calibrated,
  time-aligned reference there is nothing to correlate them against. DTC count
  never will be broadcast — Mode 03 is request/response by definition.

## 7. Fuel and CNG level — NOT identified, and why

The car has **two** gauges. Neither could be located, and the reasons are
concrete rather than a shrug:

- **Neither level moves.** The car ran on CNG the whole session, so the petrol
  level is untouched, and 33 minutes of idling barely dents a CNG tank. With no
  variation there is nothing to correlate or isolate — **~25 constant bytes are
  equally good candidates** and nothing separates them.
- **The 86 % is not a usable known-value match.** It came from the Teltonika's
  **OBD-II request** (PID 2F), not from a broadcast frame. It proves the ECU
  *answers* a fuel-level PID; it says nothing about whether the value is
  broadcast, or in what units. (It is the **CNG** level — the OBD PID reports the
  *active* fuel.)
- **The one arithmetically-attractive hit is unconvincing.** `0x492` byte 5 = 56,
  which is 87.5 % of 64. But it is dead constant across all seventeen captures —
  a real CNG gauge would have moved a little — and the rest of that frame
  (`40 FE 0F 00 00 38 00`) looks like fixed configuration.
- **`0x445` was rejected on rate.** It is the only clean monotonic faller in the
  set (25 → 9 over 33 min, 13 falls / 0 rises, one step every ~2 minutes
  regardless of load). Tempting, but ~12× too fast for CNG tank pressure and
  ~25× too fast for a petrol gauge. It behaves like a timer.

**What would settle it, cheapest first:**

1. **Poll OBD PID 2F while capturing.** Gives a calibrated, time-aligned
   reference — exactly what made the WagonR's signals Tier A.
2. **Switch to petrol mid-capture.** The petrol level starts falling and the CNG
   level goes flat: whichever field swaps behaviour is which.
3. **Refuel during a capture.** A tank going from near-empty to full is an
   unmissable step, and it isolates the low-fuel lamp bit at the same time.

## 8. A year discrepancy to resolve

The pack folder is `Petrol_2023`, from the 2026-06-13 capture that created it.
This vehicle's VIN has **`S` at position 10, which ISO 3779 reads as 2025**.

Either the folder year is wrong, or these are two different model years sharing
one bus map. **The map is shared either way** — the original pack's three signals
decode correctly on both capture sets. Flagged rather than renamed, because
renaming a pack folder has artifact consequences and one VIN is thin evidence.
This is the second marque where the ISO year code looks trustworthy (see the
Maruti note in `oem_packs/README.md`), MG remaining the exception.

## 9. Reproducing

```powershell
python -m ucando.cli identify --log "data/uploads/Aura/Aura/Normal data/Normal data on vehicle ON 8-20-2026 2-31-08 pm.csv"
```

Scores **1.000 (30/30 IDs)**. 16/16 validation checks pass, including both
integration tests against the recorded odometer. Adding this pack did not disturb
the Suzuki packs: WagonR and Dzire still identify at 1.000, and the Aura's
runner-up is ZS EV at 0.124 — the Hyundai map shares nothing with the Suzuki one.

## 10. Open items

1. **Poll OBD PID 2F, or capture a fuel switchover** (§7) — the only way to get
   either fuel level.
2. **A cold-start capture** — isolates coolant temperature, and probably intake
   air and ambient with it. Cheapest high-value follow-up.
2. **A longer drive** to tighten the speed scale beyond the ±9 % this 1.1 km
   reference allows, and to look for a systematic speedo bias.
4. **Re-run the passenger-door test** with nothing else touched — the driver door
   isolated cleanly, the passenger one did not.
4. **Resolve the model year** (§7).
5. **Fuel level** — capture across a refuel, or a long enough drive to see it
   fall.
