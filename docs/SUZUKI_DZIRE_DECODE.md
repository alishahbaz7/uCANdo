# Maruti Suzuki Dzire (petrol) — CAN decode (OBD-2 capture, 2026-08-19)

Reverse-engineering record for a **Maruti Suzuki Dzire petrol**, captured through the
OBD-2 port with **PCAN-View v5.2**. Artefact:
`oem_packs/Suzuki/Dzire/Petrol/suzuki_dzire_petrol.dbc`
(**13 messages, 30 signals**, loads clean in cantools).

Follows the project RE method: **decode the pattern, then prove it byte-exact against
ground truth**, and state plainly what is *not* proven.

> **What goes in the DBC.** A message is in the file only if it carries at least one
> signal we can **name**. Constant bytes, empty frames, one-shot init frames and
> unidentified byte dumps are recorded in §7 of this document instead. A DBC is for
> decoding a bus, not for inventorying it — a tree full of `UNK_*` nodes costs the reader
> attention and returns nothing. The bus inventory is still complete here, and
> `signature.json` still carries **all 31 IDs**, so auto-identify is unaffected.
>
> **Confidence travels with the signal.** Every signal opens its DBC comment with its
> grade and carries a machine-readable `SignalConfidence` attribute, so the caveats below
> are visible in the tool rather than only in this document. Counts: **A = 11, B = 11,
> C = 8**. The convention is defined in `.claude/skills/dbc-pack/SKILL.md` and enforced by
> `tests/test_pack_dbc_syntax.py`.
>
> | Grade | Meaning |
> |---|---|
> | **A_Confirmed** | Matched byte-exact against external ground truth |
> | **B_Corroborated** | Isolated by controlled experiment, or forced by unambiguous physics |
> | **C_Inferred** | Structural inference only — scale and/or mapping unverified |
>
> Note the grade describes **the decoded value, not the discovery**. `AccelPedalPosition`
> is graded **B** even though its identity is certain, because its scale rests on a single
> calibration point — the user consumes the number, not the reasoning.

## 1. Capture set

All under `data/uploads/Swift desire 19082026/`, PEAK `.trc` v2.0 (read by
`can.LogReader`, so `logstore.load()` and `reverse.load_log_frames()` both handle them
with no new code). One 500 kbit/s bus, **31 steady-state IDs**, ~1 000 fps.

The session is an **event-isolated matrix**: the engine idled for 81 minutes while one
control at a time was actuated, with the folder name recording which. That is what makes
the body signals provable — a bit that moves in exactly one capture and nowhere else is
identified by construction, not by guesswork.

| # | Clock | Capture | Actuation |
|---|---|---|---|
| 1 | 16:18 | `Ign ON/Ignition ON only` | **ignition-on transition**, engine never started |
| 2 | 16:21 | `Ign ON_AC ON_Vehicle Start` | **engine crank** |
| 3 | 16:27 | `…Hazard and head light` | headlamps, indicators |
| 4 | 16:30 | `…break padel` | brake pedal ×4 |
| 5 | 16:31 | `…accelaretor padel` | throttle blips |
| 6 | 16:33 | `…door status` | door open/close ×2 |
| 7 | 16:37 | `…wipper status` | wipers |
| 8 | 16:40 | `…gear status` | gear selection |
| 9 | 16:45 | `…parking light` | parking lamps |
| 10 | 16:48 | `…driver and co driver sheat belt` | belt buckle/unbuckle ×4 |
| 11 | 16:51 | `…AC Status` | AC on/off ×3 |
| 12 | 17:26 | `PCAN with FMB150/Ign ON RPM` | throttle blips, **FMB150 fitted** |
| 13 | 17:31 | `PCAN with FMB150/ign on ODO` | steady idle, **FMB150 fitted** |
| 14 | 17:39 | `PCAN with FMB150/PCAN Data` | steady idle, **FMB150 fitted** |

Captures 1 and 2 are worth as much as the labelled ones: they are the only **state
transitions** in the set, and §4 recovers three signals from them that no amount of
staring at steady-state idle would have produced.

**The vehicle never moved.** Every capture is stationary, and this is the single biggest
limitation of the dataset — see §8.

### Ground truth

Two independent sources, both photographed:

**Instrument cluster** (`ODO.jpeg`): odometer **201618 km**, speed 0, fuel ≈ 8/10 bars,
seatbelt and brake warning lamps lit.

**Teltonika FMB150 configurator** — a commercial telematics unit that already decodes
this vehicle, so its readout is an independent decode to check ours against. Its *green*
rows are the parameters this car actually publishes on CAN:

| Photo | Speed | Pedal | RPM | Total mileage | Fuel | Door |
|---|---|---|---|---|---|---|
| `ign on ODO/ODO.JPG` | 0 | 0 % | **849** | 201 618 000 m | 78 % | 0 |
| `Ign ON RPM/before.JPG` | 0 | 0 % | **854** | 201 618 000 m | 79 % | 0 |
| `Ign ON RPM/1.JPG` | 0 | 0 % | **1418** | 201 618 000 m | 78 % | 0 |
| `Ign ON RPM/2.JPG` | 0 | **5 %** | **1683** | 201 618 000 m | 78 % | **256** |

Greyed rows (`-`) tell us what is *absent*: no engine worktime, no fuel-consumed, no
engine-load, no oil level, no AdBlue on this bus. The two "(counted)" rows the device
does fill are Teltonika accumulators, not CAN signals.

### Bus architecture

The map (`0x114`, `0x120`, `0x122`, `0x124`, `0x13F`, `0x1AC`, `0x1B8`, `0x310`, `0x318`,
`0x3D0`, `0x3D1`, `0x460`, `0x500`) does **not** resemble any other pack in this library —
none of the MG (GM Global A) or Hyundai IDs appear, so **no signal transfers** from an
existing pack. It was decoded from scratch.

Three tiers of frame:

- **6 always-on** (`0x3D0`, `0x3D1`, `0x3D4`, `0x3D5`, `0x3D9`, `0x3E8`) — present before
  ignition; the body/BCM segment.
- **25 ignition-on cyclic**, starting together at t = 21.8 s in capture 1.
- **10 one-shot** (`0x0D0`–`0x0D2`, `0x400`, `0x40B`, `0x4E0/1/4/5`, `0x4ED`) — 1 to 5
  frames each inside a one-second burst at ignition-on, then never again. Excluded from
  both the DBC and `signature.json`: a live identify on a running car never sees them, so
  including them would only depress the match score.

**The FMB150 injects nothing.** Captures 12–14 have the device fitted and carry exactly
the same 31 IDs as captures 1–11. It is a pure listener — worth knowing before blaming a
telematics unit for bus load.

## 2. Frame integrity convention

Unlike the MG bus, this one has **no per-frame checksum**. `sum8`, `sum8+id`, `sum8+dlc`,
`xor8`, `~sum8`, `0x100-sum` and CRC-8 across eight polynomials × four seeds × both
reflections were all tested against every varying byte and all rejected. (An early
apparent hit was a false positive from all-zero payloads — any byte trivially equals the
sum of seven zeros. Frames with fewer than five distinct payloads are excluded from the
test for that reason.)

What it does carry is a **2-bit rolling counter**, verified at 100 % over 4 000 frames in
six frames at once: `0x114` byte 5 bits 0-1 (mirrored at byte 6 bits 4-5), `0x120` byte 5,
`0x122` byte 3, `0x124` byte 6, `0x1AF` byte 2 bits 4-5, `0x32E` byte 3. They are useful
for frame-loss detection but decode to nothing a user wants to read, so they are recorded
here rather than in the DBC.

There is also a pervasive **signal-duplication convention**: safety-relevant values are
sent twice inside the same frame, sometimes as a straight copy and sometimes as a
complement. Accelerator (`0x122` byte 1 / byte 2), fuel (`0x3B9` byte 4 / byte 5),
seatbelt (`0x3D0` byte 5 bit 3 / byte 6 bit 4, complementing `0x3D1` byte 5 bits 7/6),
pedal state (`0x318` byte 0 bits 0/1), engine-stopped (four ECUs at once). Recognising
this early prevents counting one signal several times — the DBC keeps **one** copy of
each and names the mirrors in the signal comments.

## 3. Tier A — confirmed against external ground truth

| Signal | ID | Bits (MSB-first seq) | Len | Scale | Confirmation |
|---|---|---|---|---|---|
| **Odometer** | `0x460` | 0 | 24 | **1 km** | raw **201618** vs dash **201618 km** — exact |
| **EngineSpeed** | `0x124` | 8 | 16 | **0.25 rpm** | all four Teltonika values present exactly |
| **EngineSpeed2** | `0x13F` | 8 | 16 | 0.25 rpm | tracks `0x124` to mean \|Δ\| 16 rpm |
| **AccelPedalPosition** | `0x122` | 8 | 8 | ≈0.4 % | raw 0 at both 0 % photos, raw 15 at the 5 % photo |
| **VIN** | `0x500` | mux byte 1 | 3×6 ASCII | — | reassembles to a valid 17-char VIN, WMI `MA3` |

**Odometer.** Byte-aligned bytes 0-2 big-endian, scale 1. The scan also reported hits at
start bits 1, 2, 3, 5, 6 with scales 0.5, 0.25, 0.125 — those are **bit-shift aliases of
the same field** (shifting left one bit and halving the scale reads the same number), not
independent candidates. The byte-aligned member of an alias family is the real one. Note
the vehicle was stationary throughout, so the 1 km **quantum is not proven** — only that
the field reads the dash value exactly. Teltonika reporting `201618000 m` confirms the
same number at metre resolution.

**EngineSpeed.** `0x124` bytes 1-2 reads exactly 0 in the engine-off capture and contains
849, 854, 1418 and 1683 rpm as exact values — all four photographed readings, none
missing. The scale is **independently corroborated by the crank profile** (§4): the
starter turns the engine at 100 → 215 rpm before it catches, which is exactly where a
starter motor sits. A wrong scale would put cranking at an impossible speed.

`0x13F` also carries engine speed and is the finer of the two: `0x124`'s raw is always
even (0.5 rpm effective quantum) while `0x13F` uses all values (0.25 rpm). `0x124` is the
primary because it is faster (10 ms vs 20 ms) and reproduces all four readings, whereas
`0x13F` misses 1683.

**AccelPedalPosition.** `0x122` byte 1, duplicated one tick later in byte 2. Reads 0 at
both photos that report 0 % and 15-17 at the photo reporting 5 %.

> **PEDAL SCALE CAVEAT.** There is exactly **one non-zero** ground-truth point, so the
> scale is *not* pinned. 0.4 %/bit is the OEM-standard mapping (0-255 → 0-102 %) and is
> what the DBC uses, but it renders the 5 % photo as 6 %. A scale near ⅓ would hit 5 %
> exactly. Because the photo instant cannot be time-aligned to a specific frame — 1683 rpm
> occurs on both the up-ramp and the down-ramp of a blip, with very different pedal — the
> observed raw could be anywhere in 15-17. **Treat this scale as ±1 percentage point.** A
> capture with the pedal held at several known positions would settle it.

**VIN.** `0x500` at 200 ms, byte 0 a constant `0x75` tag, byte 1 a block index 1/2/3, and
bytes 2-7 ASCII. Block 1 leads with a `0x00` pad; strip it and concatenate for the full
17-character VIN. **WMI `MA3` = Maruti Suzuki India**, which independently confirms the
make from the bus itself. Only the 9-character prefix is committed
(`oem_packs/Suzuki/Dzire/Petrol/vehicle.json`) — never a whole VIN of a real car.

## 4. Tier B — recovered from the two state transitions

Captures 1 and 2 contain the only state changes in the set. Diffing a window before each
against a window after, and keeping only bits that are **constant throughout both
windows and different between them**, isolates state signals cleanly.

The crank profile itself, from `0x124`:

```
 t=15.05s     0 rpm   ignition on, engine stopped
 t=15.19s   103 rpm   starter engaged
 t=15.43s   185 rpm   cranking
 t=15.65s   214 rpm   cranking
 t=15.76s   587 rpm   first firing
 t=16.08s  1247 rpm   catch and flare
 t=17.38s   877 rpm   settling to idle
```

| Signal | ID | Location | Evidence |
|---|---|---|---|
| **EngineNotRunning** | `0x310` | byte 0 bit 0 | 1 with ignition on and engine stopped, 0 once running. Matches `EngineSpeed > 0` on **100 %** of frames outside the crank window. |
| **IgnitionOn** | `0x3D0` | byte 1 bit 6 | 0 for the first 21.8 s of capture 1, 1 for the remaining 81 minutes. |
| **EngineThrottleState** | `0x318` | byte 0 bits 0-1 | 2-bit enum: **0** engine off, **1** running/throttle closed, **2** running/throttle applied. Value 3 never occurs in 14 captures. |

**EngineNotRunning is published by four ECUs at once** — `0x310` byte 0 bit 0, `0x120`
byte 0 bit 0, `0x3C3` byte 0 bit 5, `0x318` byte 1 bit 6, plus `0x310` byte 3 bit 6 and
`0x3D0` byte 0 bit 0. All six agree on all fourteen captures. The DBC keeps the `0x310`
copy, alongside coolant temperature.

The 100 % cross-check against `EngineSpeed > 0` has exactly one class of deviation, and
it is *correct*: during the crank window the engine is **turning but has not caught**, so
rpm is non-zero while the flag still reads stopped. That is the distinction a "running"
flag exists to make, and it is why this signal is worth more than a threshold on rpm.

**EngineThrottleState** replaces what an earlier pass modelled as two complementary
booleans (`AccelPedalApplied` / `AccelPedalReleased`). They are the two bits of one 2-bit
field, and reading them as an enum also captures the engine-off state that neither
boolean expressed.

## 5. Tier B — isolated by controlled experiment

Each of these moves in **exactly one** capture and is quiet in all thirteen others. That
is a stronger claim than correlation: the folder name is the independent variable.

| Signal | ID | Location | Evidence |
|---|---|---|---|
| **BrakePedal** | `0x318` | byte 0 bit 2 | 4 clean presses in the brake capture, **0 elsewhere** |
| **HeadlampOn** | `0x3D0` | byte 0 bit 5 | 2 on/off cycles in the light capture, **0 elsewhere** |
| **HeadlampOffIndication** | `0x3B8` | byte 7 bit 4 | inverse of the above, clearing at exactly the same instants (bits 3 and 0 are copies) |
| **AuxLampStatus** | `0x3B8` | byte 0 bit 2 | 3 cycles in the same capture on a *different* schedule → second circuit |
| **TurnIndicatorA/B** | `0x3D0` | byte 4 bits 6, 7 | blink at ≈1.4 Hz (0.35 s on/off); both together = hazard |
| **DriverSeatbeltFastened** | `0x3D1` | byte 5 bit 7 | set only while buckled in the belt capture; reads unfastened everywhere else, matching the lit dash lamp |
| **DoorOpen** | `0x3D5` | byte 3 bit 7 | 2 open/close cycles in the door capture; **matches Teltonika `Door Status` flipping 0 → 256** |
| **DoorOpenSecond** | `0x3D1` | byte 0 bit 1 | a second aperture on its own schedule |
| **AcCompressorOn** | `0x3D0` | byte 1 bit 4 | 0 before engine start, 1 while AC runs, toggles ×3 in the AC capture |

**EngineCoolantTemp — `0x310` byte 1, offset −40 °C, scale 1.** Not isolated by an
experiment but proven by thermal behaviour: it reads **91-92 °C** in the engine-off
capture (heat-soaked from the drive that put 201 618 km on the car), then settles to
**89-90 °C and holds there for the entire 80-minute idle**. A thermostat-controlled
coolant loop is the only thing on a vehicle that does that, and the offset −40
convention lands it exactly in the expected band.

**FuelLevel — `0x3B9` byte 4, duplicated in byte 5, ≈0.4 %/bit.** Falls **monotonically
209 → 185** across the session, tracking the chronology file by file with no reversals.
Teltonika reported 78 % where raw was 197 (×0.4 = 78.8 %). Cross-check: 24 counts over
81 minutes is 9.6 % of a ~37 L tank ≈ 3.5 L, i.e. **≈2.6 L/h** — consistent for a 1.2 L
petrol idling with AC on and repeated revving.

> **FUEL SCALE CAVEAT.** Like the pedal, this rests on a single calibration point.
> 0.4 %/bit fits it to within 1 percentage point and the consumption cross-check is
> physically sane, but 100/255 fits nearly as well. Do not trust it to better than ±1 pt.

## 6. In the DBC, but uncalibrated

**`0x1B8` — four 16-bit wheel-speed fields.** Each reads `0x3FFF` (14-bit all-ones, the
classic *not-available* code) for the first ~20 s after ignition while the ABS
initialises, then `0x0000`. Four identical fields on a 10 ms ABS-priority ID is a wheel
speed frame. Kept because it is the only motion-related data on the bus and a user who
drives the car will see it move immediately — but the signals are named `WheelSpeedRaw1..4`
and carry **raw counts, not km/h**. **Scale and wheel-to-field mapping are unknown.**

## 7. Deliberately NOT in the DBC

Everything below is real and was measured; none of it decodes to something a user can
act on. It is here so the next person does not re-derive it, and so it can be promoted
the moment it is identified.

| Frame / field | What it does | Why excluded |
|---|---|---|
| `0x0D0-0x0D2`, `0x400`, `0x40B`, `0x4E0/1/4/5`, `0x4ED` | 1-5 frames in a one-second burst at ignition-on | no signals; never seen on a running bus |
| `0x1EF`, `0x32F`, `0x3A1`, `0x3D4`, `0x3BF` | payload all zero in all 14 captures | nothing to decode |
| `0x3A0`, `0x3BA`, `0x3D9`, `0x3E8`, `0x114` bytes 3-4, `0x463` | fixed constants (`0x01/0x40`, `0x40`, `0x08`, `0x03 FF`, `0x0FFF`, `0x0D68`) | constant in every capture — configuration, not measurement |
| rolling counters (§2) | 2-bit mod-4, six frames | useful for frame-loss detection, meaningless to read |
| `0x120` two 10-bit channels | **the strongest open lead.** Both read exactly **800** engine-off, 696-887 running; track each other at r = 0.94; rise with accelerator (r = 0.68) but **not** rpm (r = 0.04). Top 6 bits are flags, one set only when the engine is stopped. | quantity not identified. MAP was considered and rejected — idle vacuum would pull it far lower |
| `0x122` byte 4 = `0x124` byte 5 (100 % identical) | ≈17 at idle, ≈31 on throttle | load- or throttle-like, nothing calibrates it |
| `0x2A0` byte 3 bit 0 = `0x314` byte 4 bit 0 | latched on at 16:33, cleared by 17:39 | real state change, but **no capture isolates it**. Parking brake is the leading guess |
| `0x1AC` bytes 2-3 (12 ms) | few distinct values spread over a wide range; correlates with neither rpm nor pedal | not identified; possibly a security/rolling code |
| `0x314` byte 6, `0x318` byte 2, `0x3D1` byte 6 | vary continuously | not identified; `0x314` byte 6 and `0x3D1` byte 6 were both tested as checksums and rejected |

## 8. Negative results

Stating these matters as much as the finds — they stop the next person re-running the
same search.

- **No gear signal.** The gear capture produced *nothing blocky* on any ID. The car is a
  **manual**, and manual Dzires do not publish gear position.
- **No wiper signal.** The wiper capture moved only `0x3D1` byte 6 (an unidentified
  analogue that drifts in every capture) and `0x3B9` bytes 4-5 (fuel). Wipers are not on
  this bus.
- **No system/battery voltage.** A crank is the cleanest voltage test there is — the
  battery collapses for ~1 s and recovers above its resting value once the alternator
  comes online. **No byte on the bus shows that shape.** This agrees with the Teltonika
  panel, which offers no battery parameter for this vehicle.
- **No usable vehicle-speed signal.** Teltonika lists Vehicle Speed as supported, so it
  *is* published, but every candidate field reads zero in all fourteen captures because
  the car never moved. `0x1B8` is the structural best guess. **A short drive would resolve
  speed, wheel speeds and the odometer quantum in one run** — by far the highest-value
  next capture.
- **No parking-light signal isolated.** The parking-light capture moved only counters and
  the unidentified `0x3D1` byte 6.
- **No per-frame checksum** (§2).

## 9. Reproducing

```powershell
# identify the vehicle from any capture in the set
python -m ucando.cli identify --log "data/uploads/Swift desire 19082026/Swift desire 19082026/PCAN with FMB150/PCAN Data.trc"
```

Auto-identify scores **1.000 (31/31 IDs)** on every engine-running capture and **0.856**
on the ignition-on capture — the shortfall is precisely the ten one-shot init frames the
signature deliberately omits (§1). VIN identify on `MA3CZF63S…` resolves to this pack
exactly. Note the signature is **capture-derived and independent of the DBC**, so
trimming the DBC to 13 messages did not weaken identification at all.

## 10. Open items

1. **Drive the car and re-capture.** Resolves speed, wheel speeds and the odometer
   quantum. Nothing else in this list comes close in value.
2. **Identify `0x120`** (§7) — the most dynamic unexplained data on the bus.
3. **Pin the pedal and fuel scales** with held-position and tank-level references (§3, §5).
4. **Name the `0x2A0`/`0x314` latch** with a handbrake-isolated capture.
5. **Model year is unknown.** VIN position 10 is `J`, which ISO 3779 reads as 2018, but
   the pack folder deliberately carries **no year** — `oem_packs/README.md` records that an
   Indian marque's VIN year code cannot be trusted (the MG Windsor's reads 2008 for a
   confirmed 2026 car). Rename `Petrol/` → `Petrol_<year>/` once the year is established
   from the registration or build plate.
