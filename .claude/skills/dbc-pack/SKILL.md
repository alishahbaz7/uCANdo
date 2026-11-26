---
name: dbc-pack
description: Build, grade or review a uCANdo OEM vehicle DBC pack from a CAN capture. Use when reverse-engineering a vehicle log into signals, writing or editing any file under oem_packs/, deciding what belongs in a .dbc, grading signal confidence, or when a DBC fails to load in a CAN tool. Covers the A/B/C confidence convention, bit-numbering conversion, DBC section order, and the required pack artifacts.
---

# Building a uCANdo OEM pack

A pack is a decode of one real vehicle, handed to a colleague who will open it in
Vector CANdb++, PCAN-Explorer or BUSMASTER and **trust the numbers**. Everything
below exists because that trust is the deliverable.

## 1. The one rule

**A DBC decodes a bus. It does not inventory one.**

A message ships only if it carries at least one signal you can *name*. Empty
frames, constant bytes, power-up one-shots, rolling counters and unidentified
byte dumps go in the `docs/<VEHICLE>_DECODE.md` record instead. A tree of
`UNK_3A1` / `INIT_4E0` nodes costs the reader attention, returns nothing, and
buries the signals that matter.

This is free: `signature.json` is **capture-derived and independent of the DBC**,
so trimming never weakens auto-identify. The Dzire pack went 41 messages → 13
with its identify score unchanged at 1.000.

Same for near-duplicates. Buses commonly send a value twice — a copy, a
complement, or the same state from several ECUs. Keep **one**, and name the
mirrors in its comment.

## 2. Confidence — every signal, no exceptions

A number nobody can grade is a number nobody should act on. Every signal states
its grade **twice**: opening its `CM_ SG_` comment (visible in every tool) and as
a `SignalConfidence` enum attribute (sortable, filterable, machine-readable).

| Grade | Means | Earns it |
|---|---|---|
| **A_Confirmed** | Matched byte-exact against **external** ground truth | Dash photo, a second decoder (telematics unit, OBD scan tool), a documented value |
| **B_Corroborated** | Isolated by controlled experiment, or forced by unambiguous physics | Bit moves in exactly one labelled capture and nowhere else; coolant settling at thermostat temperature |
| **C_Inferred** | Structural inference only — layout plausible, **scale/mapping unverified** | Four identical fields on an ABS-priority ID; an indicator blinking at 1.4 Hz whose *side* is unknown |

Rules that keep the grade honest:

- **Grade the decoded value, not the discovery.** If the field's identity is
  certain but its scale rests on one calibration point, it is **B**, not A — the
  user consumes the number, not your reasoning. Say so in the comment:
  *"IDENTITY is confirmed … the SCALE is not."*
- **Partial knowledge is C.** A bit you know is a turn indicator but cannot
  assign to left or right is C, and the comment says which half is missing.
- A **C** comment must contain an explicit "do not trust the number" style
  warning and, where relevant, the raw unit (`RAW COUNTS, NOT km/h`).
- Never upgrade a grade to make a pack look better. `oem_packs/README.md` has a
  Verified column that readers use to decide whether to trust scales.

`tests/test_pack_dbc_syntax.py::test_pack_signals_state_confidence` enforces
this. Packs predating the convention are listed in `UNGRADED_LEGACY`; **never add
to that list** — grade the signals instead.

## 3. Bit numbering — where mistakes actually happen

The project canonical index is **sequential MSB-first**: bit 0 = byte 0's MSB.
`reverse.py`, `jsondecode.py` and `txpatch.py` all use it. DBC Motorola start
bits use the sawtooth numbering instead. Convert with the self-inverse:

```python
def mot(msb_seq):                       # canonical -> DBC Motorola start bit
    return (msb_seq // 8) * 8 + (7 - msb_seq % 8)
```

Two shortcuts that follow from it, and cover most signals:

| Field | DBC Motorola start | Length |
|---|---|---|
| whole byte `b` | `b*8 + 7` | 8 |
| multi-byte starting at byte `b` | `b*8 + 7` | 8×n |
| single bit, LSB-numbered `k` in byte `b` | `b*8 + k` | 1 |

**Generate the DBC from a script, never by hand.** Hand-written start bits are
where packs go wrong silently — the file loads, and every value is subtly off.

## 4. Beware the alias family

Known-value matching returns a *family*, not a hit. If bytes 0-2 hold 201618 at
scale 1, then start-bit+1 at scale 0.5 and start-bit+2 at scale 0.25 read the
same number. **The byte-aligned member is the real one.** Report the family in
the RE record so the next reader sees you considered it.

## 5. RE techniques that produce gradeable evidence

Ordered by the confidence they can earn:

1. **Second-decoder oracle (A).** A telematics unit already decoding the vehicle
   is independent ground truth. Its *greyed-out* parameters are evidence too —
   they say what the bus does **not** carry.
2. **Known-value matching (A).** Scan every (id, offset, length, endianness,
   scale) for a field reading a photographed dash value. Mind §4.
3. **Event isolation (B).** Capture one actuation per file with the folder name
   recording it. A bit that moves in exactly one capture and nowhere else is
   identified *by construction* — the label is the independent variable, so this
   beats correlation.
4. **State-transition diffing (B).** Ignition-on and engine-crank are often the
   only state changes in an idle session. Diff a window either side, keep bits
   constant within each window and different between them. A crank is also the
   cleanest **battery-voltage** test there is: voltage collapses ~1 s then
   recovers above rest, and *no byte with that shape* proves the bus has none.
5. **Physical behaviour (B).** Coolant settling at 89-90 °C for 80 minutes;
   fuel falling monotonically at a rate that matches a plausible burn.
6. **Structure (C).** Four identical fields on an ABS ID; `0x3FFF` as a 14-bit
   not-available code; ASCII in a multiplexed frame.

**Record negative results.** "No gear signal — the car is a manual", "no wipers
on this bus", "no battery voltage" each save the next person a day.

### Two traps

- **Checksum false positives.** On an all-zero payload every byte equals the
  sum of the others. Exclude frames with fewer than ~5 distinct payloads before
  testing `sum8`/`xor8`/CRC-8, or you will "find" a checksum on every dead frame.
- **Duplicate-looking signals that lag.** Two copies of a value may disagree
  during transients because one is sampled a tick later. Compare only frames
  where the value was steady before calling the copy broken.

## 6. File format rules

Section order is fixed by the grammar. **cantools is lenient and will load a
wrong file that Vector/PCAN reject** — this exact bug shipped once as
`line 141: syntax error`:

```
VERSION → NS_ → BS_ → BU_ → BO_ → CM_ → BA_DEF_ → BA_DEF_DEF_ → BA_ → VAL_
```

Also required, all enforced by `tests/test_pack_dbc_syntax.py`:

- `CM_` / `BA_` / `VAL_` statements end with `;` and have balanced quotes.
- Every `CM_` / `BA_` / `VAL_` references a message that exists.
- `BU_:` stays empty and transmitters stay `Vector__XXX` unless you have
  *proven* which ECU sends the frame. Message-name prefixes (`ECM_`, `BCM_`)
  carry that inference; a structured field should not.
- Add `GenMsgCycleTime` per message so a tool can flag a missing frame.
- Give every boolean and enum a `VAL_` table. `1 "Open" 0 "Closed"` beats `1`.

## 7. Pack layout and artifacts

```
oem_packs/<Make>/<Model>/<Fuel>[_<Year>]/
├── <make>_<model>_<fuel>[_<year>].dbc     required
├── signature.json                          strongly recommended
└── vehicle.json                            optional (VIN patterns)
```

Full layout rules — including multi-bus tap suffixes — are in
`oem_packs/README.md`. Beyond it:

- **`signature.json` is capture-derived**, listing every ID on the bus with real
  DLC and period — not just what the DBC describes. `id_set` must be **uppercase
  hex strings** (`"1B8"`), `x`-prefixed for extended IDs; integers silently score
  zero. Exclude one-shot power-up frames: a live identify never sees them, so
  including them only depresses the score.
- **Omit the year rather than invent one.** ISO 3779 position 10 is unreliable
  for Indian marques — an MG Windsor reads 2008 for a confirmed 2026 car. Rename
  the folder once the year is established.
- **`vehicle.json` stores VIN characters 1-9 only** — manufacturer plus
  model/body/powertrain. The tail identifies a *car*; never commit it.
- **A pack without provenance is not trustworthy.** Write
  `docs/<VEHICLE>_DECODE.md` and link it from the `oem_packs/README.md` table.

## 8. The RE record

Mirror `docs/SUZUKI_DZIRE_DECODE.md`: capture set with a chronology table,
ground truth, bus architecture, frame-integrity convention, signals by
confidence tier, **what was deliberately left out of the DBC and why**, negative
results, how to reproduce, and open items ranked by value.

State caveats where they will be read. A scale resting on one calibration point
gets a blockquote in the doc *and* a sentence in the signal comment.

## 9. Before you call it done

```powershell
python -m pytest tests/test_pack_dbc_syntax.py -q   # syntax, order, confidence
python -m pytest -q                                  # full suite
```

- [ ] Loads in cantools **and** passes the strict structural test
- [ ] Every signal graded A/B/C, in both the comment and the attribute
- [ ] No message without signals; no signal that is constant for a bad reason
- [ ] Decoded against real capture frames and checked against ground truth
- [ ] Auto-identify scores as expected on a capture the pack should match
- [ ] `docs/` record written; `oem_packs/README.md` table and Pending updated
- [ ] Year omitted unless established; VIN prefix only

Never commit, tag or merge without explicit confirmation.
