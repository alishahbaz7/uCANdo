# MG Commute EV — CAN decode (OBD-2 capture, 2026-08-01)

Reverse-engineering record for the **MG Commute EV**, captured through the OBD-2
port with a Vehicle Spy 3 / neoVI setup. Artefact:
`oem_packs/MG/Commute/EV_2026/mg_commute_ev_2026.dbc`
(**55 messages, 301 signals**, loads clean in cantools).

Follows the project RE method: **decode the pattern, then prove it byte-exact
against ground truth**, and state plainly what is *not* proven.

## 1. Capture set

All under `data/uploads/MG Commute 01Aug26/`, Vehicle Spy 3 CSV
(parsed by `canforge/vspy.py`). Each file is a rolling tail of ~50 000 frames
(~20 s) or ~100 000 frames (~41 s).

| Group | Files | Purpose |
|---|---|---|
| `Start phase data` | 1 | parked, ignition on, AC on, all doors closed |
| Event-isolated | 13 | one actuation each: doors, lock, belt, gear, pedals, lights, AC, EPB |
| `Moving Data/` | 34 | a 4.1 km drive, plus before/after dash photos |
| `Slow Charing/` | 5 | AC charging, plus before/after dash photos |

**Networks: HS CAN @ 500 k and MS CAN @ 500 k**, both live on the OBD-2
connector. 147 unique IDs (123 HS, 24 MS).

### Ground truth

| Moment | ODO | DTE | SOC | Other |
|---|---|---|---|---|
| Start phase | 3066 | 284 | 89 | AC on, doors closed |
| Before moving | 3066 | 274 | 86 | |
| After moving | 3075 | 263 | 83 | **gear D, 0 km/h, 0 kW** (dash photo) |
| Before charging | — | 263 | 83 | |
| After charging | — | — | 84 | |

### Bus architecture

The ID map is **GM Global A / GMLAN-flavoured** (`0x0C1`, `0x0C5`, `0x17D`,
`0x1E1`, `0x1E5`, `0x1E9`, `0x1F1`, `0x348`), consistent with SAIC's GM
joint-venture heritage. It is **not** the MG ZS EV map — none of `0x540`,
`0x2A2` or `0x3AC` from `data/uploads/mg_zs_ev.dbc` appear, so **no ZS EV signal
transfers**. Only the *gear value-table convention* turned out to be shared, and
even that with different values.

IDs appear on **both** buses (`0x155`, `0x425`, `0x43B`, `0x53D`, `0x602`,
`0x621`) with identical content, so all analysis is done **per network** —
collapsing them corrupts the payload sets.

## 2. Frame integrity convention

Most cyclic HS CAN frames carry a **rolling counter** in byte 6 and

```
byte7 == sum(bytes[0..6]) & 0xFF
```

Verified on every frame of every ID tested: `0x36A` 205/205, `0x287` 410/410,
`0x1E9` 1026/1026, `0x2AE` 205/205, `0x0E1` 41/41, `0x361` 207/207.
`0x29A` is the exception — **0/410**, it has no checksum (bytes 6-7 always zero).

This validates parsing and lets us exclude bytes 6-7 from signal search.

## 3. Tier A — confirmed

### 3.1 Against the dash

| Signal | ID | Bits (MSB-first seq) | Len | Scale | Confirmations |
|---|---|---|---|---|---|
| **Odometer** | `0x120` | 0 | 32 | **1/64 km** | 3066, 3066, 3075, 3075 |
| **StateOfCharge** | `0x36A` | 8 | 8 | **0.5 %** | 89, 86, 83, 84 |
| **RangeToEmpty** | `0x4C5` | 13 | 11 | **1 km** | 284, 274, 263 |
| **GearSelector** | `0x155` | 37 | 2 | enum | D at the photo instant |

**Odometer** is a 32-bit accumulator at 1/64 km, *not* the 24-bit × 1 km field
the static capture first suggested. Proof: over the drive it ran
196258 → 196813 = **555 counts = 8.672 km**, and a mid-drive file shows **29
monotonic +1 steps** — the low 6 bits are a fraction, not a separate field. The
dash simply floors it (3066.531 → "3066", 3075.203 → "3075"). The absolute value
also pins the scale tightly: only q ∈ [0.015622, 0.015627] maps 196258 into
[3066, 3067), and 1/64 = 0.015625 sits in the middle.

**RangeToEmpty** — the 12-bit × 0.5 alternative yields 1161 km and is excluded.

**GearSelector** — `0 = N, 1 = D, 2 = R, 3 = P`:

- `3` is constant across **every** stationary capture (start phase, charging,
  brake, pedal, RPM logs)
- `1` is constant across **every** forward-driving file
- `2` occurs in exactly the two files where the `0x16C` signed speed goes
  **negative** (−4.05 km/h — reversing out of a parking spot). Two independently
  derived signals confirming each other.
- `0` by elimination
- matches the After-Moving dash photo (D)

An earlier hypothesis putting gear at `0x1F2` byte 1 was **wrong** — it read P
throughout a file in which the car was demonstrably driving. Discarded.

### 3.2 Vehicle speed

| Signal | ID | Bits | Len | Scale | Rate |
|---|---|---|---|---|---|
| VehicleSpeed | `0x36A` | 16 | 16 | 1/64 km/h | 100 ms |
| VehicleSpeedSigned | `0x16C` | 16 | 16 | 0.01 km/h, **offset 32768** | 10 ms |

Both read **exactly 0** in every stationary capture and at the end of the last
moving file (dash photo: 0 km/h). They agree with each other to ~1 % sample by
sample. `0x16C` rests at exactly `0x8000`, making it signed — and it is the
signal that independently proved the reverse gear. Max observed **56.0 km/h**.

> **SPEED SCALE CAVEAT.** Integrated over 4.13 km across 14 windows, both
> witnesses land **~2.5 % under** the odometer distance — a consistent bias, not
> scatter. Since the odometer quantum is tightly pinned (above), the residual
> sits in the speed path; a scale of 0.016 km/h (1/62.5) would remove it. 1/64 is
> kept because it matches the vehicle's own fixed-point convention and reads
> exact zero at standstill. **A GPS-referenced drive would settle this.**

### 3.3 HV battery — cross-validated without any dash reading

**Cell block `0x5A1`–`0x5C0` @ 1 Hz.** Four 16-bit words per frame:

```
bit15..13  slot marker (1,2,3,4 — equals the word's position)
bit12      not-present flag
bit11..0   cell voltage in mV
```

Verified across **2400/2400 words**: the slot marker always equalled the word
index, and bit 12 was set **iff** the 12-bit field read `0xFFF`. That yields
**114 valid cells** at 3316–3320 mV — an **LFP** signature and a **114S** pack.

| | |
|---|---|
| Σ of the 114 decoded cells | **378.243 V** |
| `0x29A` B0-1, `0x284` B2-3 × 0.1 | **378.2 V** |
| Error | **0.04 V (0.011 %)** |

Held across 8 consecutive sweeps, all within 0.05 V. This proves three things at
once: cell unit = **mV**, pack-voltage scale = **0.1 V**, topology = **114S**.
It reconciles under every condition tested — 376.2 V mid-drive, 381.0 V charging.

| Signal | ID | Bits | Len | Scale |
|---|---|---|---|---|
| CellVolt_001..114 | `0x5A1`–`0x5C0` | 16i+4 | 12 | 0.001 V |
| PackVoltage (×3 witnesses) | `0x29A`, `0x284`, `0x287` | — | 16 | 0.1 V |
| **PackCurrent** | `0x287` | 0 | 16 | **(raw−10000) × 0.1 A** |
| CellVoltMax / Min + indices | `0x29B` | 0 / 24 | 16 | 0.001 V |

**PackCurrent sign is confirmed: positive = discharge.** The charging capture
reads **−7.0 A**, which at 380.7 V is 2.7 kW — a slow AC charge — and SOC rose
83 → 84 % across it. Drive range −23.2 A (regen) to +67.1 A.

### 3.4 Body

| Function | ID | Field | Evidence |
|---|---|---|---|
| Driver door | `0x12A` | bits 22-23 | `0xAA ↔ 0xAB`, 3 open/close cycles |
| Passenger door | `0x12A` | bits 18-19 | `0xAA ↔ 0xBA`, 2 cycles |
| Vehicle locked | `0x12A` | byte2 = `0x00` | lock log toggles `0xAA ↔ 0x00`; also `0x00` throughout the drive (auto-lock) |
| Driver seat belt | `0x0E1` | bit 12 | `0x00 ↔ 0x08`, 2 buckle cycles |
| Accel pedal | `0x155` | bytes 2 **and** 5 | full 0–100 % sweep, two identical channels |
| AC active | MS `0x3F0` | bytes 1/4/5 | `0` when off, ramps when on — **and non-zero in the AC-ON baseline** |

Door byte 2 is four 2-bit fields (`2` = closed, `3` = open, `0` = locked),
`0xAA` = all closed and unlocked.

### 3.5 Charging

Found by differencing the 5 charging captures against 6 not-charging references
(parked with AC on, driving, and several event logs).

| Signal | ID | Field | parked | driving | charging |
|---|---|---|---|---|---|
| **TimeToFullCharge** | `0x36E` | bytes 1-2 | 0 | 0 | **182 → 177 min** |
| ChargingActive | `0x295` | bit 27 | 0 | 0 | **1** |
| ChargeMode | `0x165` | bit 56 | 0 | 0 | **1** |
| PropulsionMode | `0x165` | bits 0, 3 | 1 | 1 | **0** |
| PropulsionEnabled | `0x155` | bit 4 | 1 | 1 | **0** |

**TimeToFullCharge is the strong result.** The five charging captures share one
continuous device clock (118.7 → 480.8 s), so the countdown slope is directly
measurable: **−1.01 counts per minute**, i.e. the unit is **minutes**. It reads
0 in every non-charging capture. At 83 % SoC on a 2.66 kW charge it showed
182 min; a naive `(17 % × 38 kWh) / 2.66 kW` gives 152 min, the BMS being
appropriately conservative about LFP taper.

Modelled 16-bit because byte 1 (always 0 here) must carry the high byte for any
charge longer than 255 min — **unverified**. A transient `0xFF` at buffer start
looks like a not-available marker.

`0x4F6` is almost certainly the **on-board charger** — it is the only frame that
changes shape wholesale when the cable is live:

```
parked    14 00 00 0E B8 00 00 5A
driving   14 00 00 0E A0 00 00 5A
charging  08 00 4B 0E E4 00 E6 5E
```

Byte 6 reads **230** only while charging — exactly Indian mains nominal, so it
is labelled `AcMainsVoltage` at Tier B. Byte 2 reads 75 only while charging but
reconciles with neither amps nor amps/10 at 2.66 kW / 230 V, so it is left
unidentified.

#### Two confounds that were rejected

The naive diff also flagged `0x271` and `0x29B`. Both are **artefacts of the
comparison, not charging signals**:

- `0x271` is the **HVAC frame** — the AC was on in the reference captures and off
  during charging, so of course it differs.
- `0x29B` is the **cell-summary frame** — cell voltages simply rise while
  charging (3312 → 3328 mV). Already decoded in §3.3.

This is the standard hazard of set-differencing: any variable that happens to
co-vary with the condition shows up. Both were discarded on the grounds that
their behaviour is already fully explained by a decoded signal.

#### What charging data still cannot tell us

- **Charger type (slow vs fast) is NOT determinable.** Only one charger type
  (2.66 kW AC) was ever captured. A field discriminating AC from DC cannot be
  identified from AC-only data; `0x4F6` byte 0 (`0x14` → `0x08`) is a plausible
  home for such an enum, but no mapping is claimed.
- **"Connected" cannot be separated from "charging."** Every candidate bit flips
  together, and no capture contains a plugged-in-but-idle state.
- **No plug-in edge exists** in the data — all 5 files are mid-charge.

## 4. Tier B — probable

| Signal | ID | Field | Reading | Basis |
|---|---|---|---|---|
| Temp1/2/3 | `0x2AE` | bytes 2/3/4 | 47/46/46 °C | standard −40 offset |
| SocPercent | `0x5B9` | byte 5 | 89 | independent 1 % agreement with `0x36A` |
| SohPercent | `0x5B9` | byte 4 | 88 | adjacent byte; identity unproven |
| HazardSwitch | `0x297` | byte4 `0x40` | — | one clean transition — switch, not lamp (it never blinks) |
| LightSwitchState | `0x279` | bits 28-30 | 2→3→4→5 | stepped as the switch rotated; **position labels not established** |
| AcState | `0x43B` | bits 10-11 | 1↔2 | toggles with AC; mirrored on MS CAN |
| BrakeSignal | `0x28B` | byte 1 (+byte 5 mirror) | `0x7C↔0x86` | two-state, not a pressure ramp — meaning unproven |

## 5. Tier C — flagged, not trusted

- **`0x287` bytes 4-5** — previously mislabelled a second pack current. It is
  **not**: it stayed 0–4.9 A while `PackCurrent` swung −23…+67 A during the
  drive. Identity unknown (possibly a DC-DC / auxiliary load).
- **Parking brake — unresolved.** Its candidates (`0x565` byte0 bit1,
  `0x128` byte2) also move in the Pedal and RPM logs, so they more likely mean
  "brake applied" or "stationary" than EPB.
- **Two door fields** (`0x12A` bits 16-17, 20-21) are presumed rear doors **by
  symmetry only** — never actuated.
- **`0x29A` bytes 2-3** — static 421.8, possibly a voltage limit.
- **`0x29B` bytes 6-7** — labelled CellVoltAvg but reads the block *minimum* in
  some samples.
- **Cell numbering** is assumed sequential by ID then word; the physical
  module/cell mapping is unconfirmed.

## 6. Open work

Ordered by value:

1. **A full charge-session capture** — recording *before* plug-in, through the
   handshake, into charging, then stop and unplug. This is the highest-value
   capture remaining: it is the only way to separate **connected** from
   **charging**, to see the plug-in edge, and to expose the handshake states.
2. **A DC fast-charge session** — the only way to identify a charger-type field,
   and it also confirms the `PackCurrent` offset form stays linear at high
   current.
3. **GPS-referenced drive** — settles the 2.5 % speed-scale residual.
4. **Per-position light-switch capture** — labels the `0x279` enum.
5. **A clean EPB-only capture** (ignition on, foot off both pedals) — isolates
   the parking brake.
6. **Rear-door actuation** — confirms the two presumed door fields.

### Available today without further RE

Charge state can be **derived** from already-confirmed Tier A signals, and this
is arguably more robust than an OEM-specific enum because it ports to any
vehicle:

| Derived | Expression |
|---|---|
| Charging | `PackCurrent < 0` |
| Charge power kW | `PackVoltage * PackCurrent / -1000` |
| Charger class | power band: ≤3.3 kW slow AC, ~7.4 kW fast AC, >20 kW DC |
| Time to full | `(100 - StateOfCharge) * 0.38 / charge_kW` hours (38 kWh, 114S) |

`canforge/derived.py` (`ComputedSignals`) evaluates exactly this shape of math
channel. The measured session — −7.0 A × 380.7 V = 2.66 kW — classifies
correctly as slow AC.

## 7. Method notes

- **Known-value matching was run bit-level, not byte-aligned.**
  `correlate.known_value_matches` steps by 8 bits and would have missed the
  11-bit `RangeToEmpty` at bit 13.
- **Event attribution needed temporal profiling, not just cross-log
  exclusivity.** Pure exclusivity was too strict (Parking Brake and RPM returned
  zero candidates) and got swamped by cell-voltage LSB noise (Head light
  returned 119 bits, nearly all from the BMS block). The decisive discriminator
  is **transition count**: a real switch toggles a handful of times with long
  stable runs; an LSB or counter toggles hundreds.
- **Speed was found by integration, not correlation.** A field is speed iff it
  reads ~0 parked *and* integrates to the odometer distance — and the scale then
  falls out. Cross-window consistency (windows averaging 12 to 44 km/h) rejects
  coincidental fits.
- Bit indices here are **MSB-first sequential** (bit 0 = byte 0 MSB), the project
  convention. The DBC boundary converts with the self-inverse
  `(x // 8) * 8 + (7 - x % 8)`.
- **Rejected shift artefacts.** Overlapping windows on a value with leading
  zeros always produce a family of false matches. `0x284` bits 22-33
  "= 284 × 0.1" is really pack voltage 3782 read across a byte boundary;
  `0x0C5` "= 306688 × 0.01" is a rolling counter in the top nibble of byte 0.
  Only natural alignments were kept.

## 8. Regenerating / validating the DBC

The generator + validator lives in the session scratchpad; it rebuilds the DBC
and re-runs every check in this document against the captures:

```
Start phase     Odometer=3066.53(dash 3066)OK  SoC=89(89)OK  Range=284(284)OK
Before moving   Odometer=3066.53(dash 3066)OK  SoC=86(86)OK  Range=274(274)OK
After moving    Odometer=3075.11(dash 3075)OK  SoC=83(83)OK  Range=263(263)OK
After charging  SoC=84(dash 84)OK
gear @ After-moving = D (dash photo: D) OK
gear @ parked       = P OK          speed @ parked = 0.000 / 0.000 km/h OK
cell sum (parked)   = 378.243 V vs PackVoltage 378.2 V OK
charging current    = -7.0 A (negative) OK

charging     charge=1 mode=1 prop=0/0 TimeToFull=178 min  OK
Start phase  charge=0 mode=0 prop=1/1 TimeToFull=0 min    OK
driving      charge=0 mode=0 prop=1/1 TimeToFull=0 min    OK
AC mains @ charging = 230 V OK
```

## 9. Importer bug found and fixed

The charging captures crashed `canforge/vspy.py`. Vehicle Spy interleaves
**bus-event rows** among the frames — adapter error-counter reports carrying
`Er=T`, `Description=CAN Bus Event`, and free text such as
`CAN Rx/Tx REGS - TEC: 0 - REC: 1` in the *Arb ID* column:

```
18501,127.178…,…,T,F,CAN Bus Event,HS CAN,,CAN Rx/Tx REGS - TEC: 0 - REC: 1,F,F,00,01,00,…
```

They are numbered like data rows and sit on a CAN network, so the parser fed
that text to `int(id_hex, 16)` and raised. Only 2 rows in 1 of 5 files — enough
to lose the whole capture. Fixed by requiring the Arb ID to be pure hex
(`_HEX_ID`), which is the only robust discriminator. Covered by
`tests/test_vspy.py::test_bus_event_rows_are_skipped`, which also asserts the
parse is byte-identical to the same capture without the event rows.
Released in **v1.2.5**.
