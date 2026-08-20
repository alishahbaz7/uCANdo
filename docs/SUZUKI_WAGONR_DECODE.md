# Maruti Suzuki WagonR (petrol + CNG) — CAN decode (2026-08-20)

Reverse-engineering record for a **Maruti Suzuki WagonR S-CNG** (factory bi-fuel,
petrol + CNG), captured with **Vehicle Spy 3 / neoVI 3G**. Artefact:
`oem_packs/Suzuki/WagonR/CNG/suzuki_wagonr_cng.dbc`
(**16 messages, 34 signals**, loads clean in cantools).

Conventions: `.claude/skills/dbc-pack/SKILL.md`. Confidence counts: **A = 13,
B = 3, C = 18**.

> **The headline is the cross-match.** This is the second Maruti Suzuki in the
> library, and it **partially matches the Dzire pack at 0.729** on bus fingerprint
> — 28 of the Dzire's 31 signature IDs, and **all 13 of its decodable messages**.
> More than ID overlap: three Dzire signal *definitions* were checked against this
> capture's own OBD-II ground truth and matched exactly. See §3.

## 1. Capture set

`data/uploads/Wagon R/Petrol + CNG/wag 8-20-2026 11-31-08 am.csv` — Vehicle Spy 3
Bus Traffic File (detected by banner and parsed by `ucando/vspy.py`; `can.LogReader`
cannot read this dialect). One **HS CAN at 500 kbit/s**, 49 901 frames, **33 s**,
**41 IDs**. Plus seven photographs from the same session.

**One capture, stationary, engine idling, running on CNG.** No event isolation, no
crank, no motion. That is the opposite of the Dzire session and it shapes
everything below: what this capture *does* have is a scan tool.

### Ground truth — three independent sources

**1. An OBD-II scan tool was live during the capture.** `0x7DF` requests with
`0x7E8`/`0x7EE` responses, polling 20 Mode-01 PIDs roughly every 1.5 s. This is
the best ground truth in the library so far, because unlike a dash photo it is
**calibrated and time-aligned to the frame**:

| PID | Parameter | Observed |
|---|---|---|
| 04 | Calculated engine load | 28.24 – 45.10 % |
| 05 | Coolant temperature | 90 – 91 °C |
| 0B | Intake manifold pressure | 36 – 56 kPa |
| 0C | Engine RPM | 822.75 – 868.25 |
| 0D | Vehicle speed | 0 |
| 0E | Timing advance | −13.5 – +7.5 ° |
| 0F | Intake air temperature | 56 – 57 °C |
| 10 | MAF rate | 1.83 – 2.99 g/s |
| 11 | Throttle position | 17.25 – 19.22 % |
| 1F | Run time since start | 249 – 280 s |
| 33 | Barometric pressure | 98 kPa |
| 42 | Control module voltage | 13.19 – 13.76 V |
| 43 | Absolute load | 22.35 – 35.69 % |

**2. Instrument cluster photo** — odometer **146282 km**, speed 0, the **CNG**
indicator lit, seatbelt warning lamp lit, and **two fuel gauges** (petrol and CNG)
both reading roughly a third.

**3. The vehicle's build plate** — `MARUTI SUZUKI INDIA LTD.`, VIN
`MA3JMTB1S NK792585`, `ENGINE NO. K10CN` (the K10C DualJet in CNG form). The plate
prints the split at exactly character 9, which is the boundary this project stores
VIN patterns to.

## 2. Bus architecture

38 vehicle IDs plus 3 scan-tool IDs. **`signature.json` excludes `0x7DF`,
`0x7E8` and `0x7EE`** — a tool was plugged in, and a fingerprint that includes it
describes the bench rather than the car. (Same reasoning that excludes the Dzire's
ignition-on burst.)

Same platform conventions as the Dzire, now confirmed on a second vehicle:

- **No per-frame checksum.** `sum8`, `xor8`, `negsum` and `sum8+id` were tested
  against every varying byte of every frame with ≥5 distinct payloads, and all
  rejected — exactly as on the Dzire.
- **2-bit rolling counters**, now in **ten** frames: `0x111`, `0x114`, `0x120`,
  `0x122`, `0x124`, `0x1AC`, `0x1AF`, `0x1B6`, `0x3A0`, `0x3A2`. All 100 % clean
  over the whole capture. The six the Dzire has are a subset.
- **Signal duplication** — `0x111` bytes 3 and 4 carry the same value.

Ten IDs are WagonR-only against the Dzire: `0x111 0x123 0x130 0x135 0x1B6 0x3A2
0x3EF 0x3F4 0x3F5 0x3F6`. Three Dzire IDs are absent here: `0x32E 0x3BA 0x463` —
all three carry no named signals in the Dzire pack, so **nothing decodable is
lost**.

## 3. The cross-match with the Dzire pack

Fingerprint scoring is necessary but not sufficient — the same ID can carry
different content on a different model. The decisive test is whether Dzire signal
*definitions* reproduce this capture's OBD-II ground truth. They do:

| Dzire definition | Decoded on WagonR | OBD-II | |
|---|---|---|---|
| `EngineSpeed` `0x124` b1-2 ×0.25 | 852.5 rpm | 852.0 rpm | ✅ |
| `EngineSpeed2` `0x13F` b1-2 ×0.25 | 852.0 rpm | 852.0 rpm | ✅ |
| `EngineCoolantTemp` `0x310` b1 −40 | 90 °C | 90 °C | ✅ |
| `Odometer` `0x460` b0-2 ×1 | 146282 km | **dash 146282 km** | ✅ |
| `VIN` `0x500` | `MA3JMTB1S…` | **build plate** | ✅ |
| `DriverSeatbeltFastened` `0x3D1` | unfastened | **dash lamp lit** | ✅ |

**Verdict: partial match, strongly — the decodable core transfers intact.** Every
other MG/Hyundai pack in the library scores ≤ 0.07, i.e. noise.

Auto-identify after adding this pack (a regression worth checking, since two
same-platform packs could confuse each other):

| Capture | 1st | 2nd |
|---|---|---|
| WagonR | **WagonR CNG 1.000** | Dzire Petrol 0.729 |
| Dzire (running) | **Dzire Petrol 1.000** | WagonR CNG 0.776 |
| Dzire (ignition-on) | **Dzire Petrol 0.856** | WagonR CNG 0.642 |

Each car identifies as itself with its sibling a clear runner-up, which is the
right shape. **VIN identify separates them exactly** — `MA3JMTB1S*` vs
`MA3CZF63S*` differ in the VDS.

### Two Dzire mysteries solved by this capture

The Dzire RE record listed `0x314` byte 6 as "changes on almost every frame, not a
checksum, unidentified" and `0x122` byte 4 as an uncalibrated `EngineLoadRaw`. The
WagonR's scan tool names both:

- **`0x314` byte 6 = manifold absolute pressure** (r = +0.975 vs PID 0B)
- **`0x122` byte 4 = throttle position** (r = +0.994 vs PID 11)

Both have been **fed back into the Dzire pack**, graded **C** there with the
provenance stated in the signal comment — they were identified on a sibling
vehicle, not on that car. On Dzire data they behave correctly: MAP sits ~49 kPa at
idle and climbs to 82 kPa on throttle blips, which is the right physics.

## 4. Tier A — confirmed against OBD-II, the dash, or the plate

| Signal | ID | Layout | Scale | Evidence |
|---|---|---|---|---|
| **EngineCoolantTemp** | `0x310` | byte 1 | 1, −40 °C | **r = +1.0000, rms 0.000** vs PID 05 |
| **EngineLoad** | `0x135` | bytes 0-1 BE | **1/512 %** | r = +0.9997 vs PID 04; clean scale fits as well as free regression |
| **EngineSpeed** | `0x124` | bytes 1-2 BE | 0.25 rpm | r = +0.996 vs PID 0C |
| **EngineSpeed2** | `0x13F` | bytes 1-2 BE | 0.25 rpm | median matches PID 0C exactly |
| **IgnitionTimingAdvance** | `0x3F6` | byte 2 | **0.5, −64 °** | r = +0.977 vs PID 0E; bus uses OBD's own encoding |
| **Odometer** | `0x460` | bytes 0-2 BE | 1 km | dash 146282 = decoded 146282 |
| **VIN** | `0x500` | 3 ASCII blocks | — | matches the build plate character for character |

`EngineLoad` and `IgnitionTimingAdvance` are on **WagonR-only frames** — genuinely
new to the library, not inherited.

On every fit the alias family was resolved to the **byte-aligned** member, and a
clean textbook scale was tested against the free regression. Where the clean scale
fits as well (1/512 for load, 0.5/−64 for timing, 0.25 for rpm) the clean one is
used, because a fitted constant carries the sampling error of a 21-point poll.

## 5. Tier B

- **`ManifoldAbsolutePressure` — `0x314` byte 6.** r = +0.975 vs PID 0B, fit
  0.286 × raw + 9.0 kPa, giving 35.9-53.9 against a reported 36-56. **The scale is
  fitted, not clean, and rms is 1.5 kPa** — approximate. The identity is not in
  doubt. *Gotcha:* the byte reads 0 with the engine stopped, which decodes to a
  meaningless 9 kPa through the offset — gate on `EngineNotRunning`.
- **`EngineNotRunning`, `DriverSeatbeltFastened`** — see §3; the seatbelt is
  confirmed on this car by the lit dash lamp, but only in the unfastened state.

## 6. Tier C — inherited, or too weakly constrained

Everything the Dzire pack established by **event isolation** is here graded **C**,
because the WagonR capture actuated nothing: brake, headlamp, indicators, doors,
AC, ignition, accelerator, throttle state. They decode to sensible steady values
consistent with a parked idling car, and the platform transfer is well supported,
but consistency is not proof. Each comment says so.

Also **C**: `ThrottlePosition` (r = +0.994, but over **six distinct raw counts** in
a 2 % idle band — the scale is the conventional 0-255 → 0-100 %, not a fit, and is
unverified outside idle) and the two fuel gauges (§7).

## 7. The CNG question — what this capture cannot answer

The car is factory bi-fuel and was **running on CNG** (dash indicator lit), with
two fuel gauges on the cluster. The honest position:

**`0x3B9` byte 4 and byte 5 are probably the two tanks.** Byte 4 wanders over raw
81-89 in 33 s — float-sender behaviour. Byte 5 is dead constant at 87. On the
mono-fuel Dzire these two bytes track each other within two counts, so the
asymmetry is real and is the shape you would expect from one float gauge and one
pressure-derived CNG reading. Both decode near 33 %, and both dash gauges read
about a third. **This is a hypothesis, not a finding** — they ship as
`FuelLevelPrimary` / `FuelLevelSecondary`, graded C, with no tank named.

**No fuel-mode flag was identified, and none could be.** The changeover is the
event that isolates it, and this capture never changes over — every candidate bit
is constant for all 33 s. Likewise no CNG tank pressure: `0x3EF`, `0x3F4`, `0x3F5`
carry live data on WagonR-only IDs and are the obvious place to look, but nothing
in this capture distinguishes a pressure from any other slowly-drifting byte.

> **The capture that settles all of it:** start on petrol, drive until the system
> switches to CNG, and keep recording across the switchover — ideally with the
> scan tool still attached. One changeover event isolates the mode flag, and a
> tank that empties over a longer drive separates the two gauges. This is the
> single highest-value follow-up for this vehicle.

## 8. Negative results

- **No system/battery voltage on the bus.** OBD PID 42 reports 13.19-13.76 V, and
  **no field on any vehicle frame correlates with it**. The Dzire reached the same
  conclusion by a completely different route (an engine crank collapses battery
  voltage, and no byte showed that shape). Two vehicles, two methods, same answer.
- **MAF rate is not identified.** Two candidates on `0x3F5` correlate at r ≈ 0.988,
  but each has only 5-7 distinct values over a 1 g/s span and needs a large
  *negative* offset — physically wrong for a mass-flow reading. Rejected rather
  than shipped.
- **`0x1B6` bytes 6-7 is not an accumulator.** It looked like a 16-bit counter;
  it steps backwards 1336 times in 3342 frames.
- **No motion data.** OBD PID 0D reads 0 throughout, so wheel speeds are 0 and the
  odometer quantum is unproven — same limitation as the Dzire.
- **`0x123` is all zeros** for the whole capture.

## 9. Reproducing

```powershell
python -m ucando.cli identify --log "data/uploads/Wagon R/Petrol + CNG/wag 8-20-2026 11-31-08 am.csv"
```

Scores **1.000 (38/38 IDs)** on its own pack. All 16 messages decode against real
frames; 16/16 validation checks pass, including all six OBD-correlated signals.

## 10. Open items

1. **Capture a petrol↔CNG changeover** (§7). Nothing else comes close for this
   vehicle.
2. **Drive it.** Resolves speed, wheel speeds and the odometer quantum — the same
   open item the Dzire has, and one drive would close it for both.
3. **Identify `0x3EF` / `0x3F4` / `0x3F5`** — live data on WagonR-only IDs, most
   likely the CNG subsystem.
4. **Re-poll OBD across a rev range.** Throttle and MAF are both stuck at C only
   because idle gives them a 2 % window; a few blips with the tool attached would
   promote both.
5. **Model year unknown.** VIN position 10 is `N` (ISO 3779 → 2022), not confirmed
   for an Indian marque, so the folder carries no year — see `oem_packs/README.md`.
