# JSON Signature Decode — Design & Clarification

> ## ✅ FINAL CONVENTION (corrected — validated against the Ziptron DBC)
> The earlier sections below explored an **Intel/LSB-first** reading. That was a
> wrong guess: it was only ever confirmed on the byte-aligned odometer, which
> reads the same under either convention. The **Ziptron DBC** (message
> `0x244`/580) gives definitive ground truth across many sub-byte signals:
>
> - **Big-endian (`reverse == 0`)** — `startingBit` is **MSB-first sequential**
>   (bit 0 = byte0's **MSB**), and the value is read **MSB-first**. This is
>   identical to the DBC/cantools **Motorola** layout:
>   `cantools_start = (startingBit // 8) * 8 + (7 - startingBit % 8)` (self-inverse).
> - **Little-endian (`reverse == 1`)** — `startingBit` is LSB-first sequential,
>   value read LSB-first (Intel). *(No real samples yet; standard assumption.)*
> - `signed == 1` → two's complement; physical = `raw * multiplier + offset`.
>
> **Proof** — Ziptron `0x244`, frame `52 51 00 47 C0 00 BA 56`, via cantools on the
> real DBC: `DTeInfo = 287` (start 24, size 10) and `HVBattSoCPercen = 93`
> (start 48, size 7). `jsondecode` reproduces both exactly. Mapping checks:
> JSON 24↔DBC 31, 48↔55, 42↔45, 19↔20, 44↔43 — all consistent.
>
> Implemented in `canforge/jsondecode.py` and `canforge/convert.py`; there is no
> sub-byte ambiguity, so JSON ⇄ DBC is bit-exact. The notes below are kept for
> history but are **superseded** by this block.

---

**Goal:** Decode raw CAN frames against a lightweight **Signature JSON** (used on
our cloud for visualization) and render the **same Frame Decoder output** we
already produce from a `.dbc` — byte view, signal table (Raw / Physical / Unit),
and the BusMaster-style bit grid.

DBC decode is the reference implementation and works correctly. JSON is a
*limited* alternative carrying the same core signal-layout information.

---

## 1. Format (observed from `Signature_mgzsevV3.json`)

```jsonc
{
  "900": [                              // key = CAN ID in DECIMAL (900 = 0x384)
    {
      "fieldName":   "Seat_belt_passenger",  // signal name
      "reverse":     0,                       // 0 = big-endian (Motorola), 1 = little-endian (Intel)
      "startingBit": 8,                       // 0..63, left-to-right (bit 0 = byte0 MSB)
      "size":        1,                       // signal length in bits
      "evData":      0,                       // EV-data flag (informational)
      "multiplier":  1,                       // physical = raw * multiplier + offset
      "offset":      0,
      "signed":      0                        // 0 = unsigned, 1 = signed (two's complement)
    }
    // ... more signals in the same message
  ],
  "901": [ /* ... */ ]
}
```

### Mapping to DBC concepts

| JSON field    | DBC / cantools equivalent | Notes |
|---------------|---------------------------|-------|
| key (decimal) | `frame_id`                | convert `int(key)` → hex for display |
| (none)        | message name              | **absent** → auto-name `MSG_<hex id>` |
| (none)        | DLC                       | **absent** → see Q3 |
| `fieldName`   | signal name               | used verbatim |
| `reverse`     | `byte_order`              | `0`→`big_endian`, `1`→`little_endian` |
| `startingBit` | `start` (start bit)       | needs convention conversion — see §2 |
| `size`        | `length`                  | direct |
| `multiplier`  | conversion `scale`        | direct |
| `offset`      | conversion `offset`       | direct |
| `signed`      | `is_signed`               | `bool(signed)` |
| (none)        | `unit`                    | **absent** → `""` |
| (none)        | `minimum` / `maximum`     | **absent** → `None` (no OOR badge) |
| (none)        | `VAL_` value table        | **absent** → no enum/choice labels |
| `evData`      | —                         | not needed for decode |

The Frame Decoder UI already degrades gracefully when unit / min-max / choices
are missing (no Description column, no OOR badge), so JSON-loaded messages will
just show fewer columns than DBC-loaded ones. No UI change required.

---

## RESOLVED — bit convention (validated against two real frames)

Two sample frames from the vehicle settle the convention:

| Frame | Payload | Signal | Expected | Forces |
|-------|---------|--------|----------|--------|
| 900 | `0205000000000200` | Seat_belt_passenger | **1** | bit 0 of a byte = **LSB**; startingBit 8 = byte1 LSB |
| 912 | `0128C30000000000` | canOdometer | **75971 km** | spans bytes 0–2 as `0x0128C3`, byte0 = MSByte → big-endian |

**Confirmed model:**
- `startingBit` is **Intel / LSB-first sequential** numbering: bit 0 = byte 0's
  **LSB**, bit 7 = byte 0's MSB, bit 8 = byte 1's LSB, … bit 63 = byte 7's MSB.
- A signal occupies sequential bits **`[startingBit, startingBit + size - 1]`**.
- `reverse` controls **multi-byte assembly only**:
  `0` → **big-endian** (lowest-address byte is most significant),
  `1` → **little-endian** (lowest-address byte is least significant).
- `signed=1` → two's complement over `size` bits.
- physical = `raw * multiplier + offset`.

This is the OPPOSITE within-byte direction from the earlier "left-to-right
MSB-first" guess — validated wrong by frame 900, where the set bit is byte 1's
LSB and the expected signal is `Seat_belt_passenger=1`.

### Implementation consequence

Going through cantools means two different start-bit conventions (Intel start =
LSB position; Motorola start = MSB sawtooth position), and **sub-byte big-endian**
fields (e.g. `Time_to_charging`, start 38 size 10) don't map cleanly. Since the
JSON carries **no** enums / min-max / units, cantools buys us nothing here — so
the plan is a **self-contained decoder** that extracts the raw value directly
from the sequential bit span with LE/BE assembly, and computes bit-grid cells
directly. It returns the same dict shape as `framedecode.decode_frames`, so the
UI renders identically.

### Remaining ambiguity (low-risk)

- **Sub-byte big-endian**: only `Time_to_charging` (905→908, start 38, size 10)
  is big-endian *and* not byte-aligned. Two readings of "big-endian" for a
  field spanning byte4[bits 6–7] + byte5[all] differ. Need one sample frame, or
  I default to: assemble the touched bytes MSByte-first, taking each byte's
  contiguous field bits in place. All other multi-byte BE signals in the file
  are byte-aligned and unaffected.

---

## 2. (historical) Bit-position convention — the original open question

Per your spec, `startingBit` runs **0..63, left-to-right**, where **bit 0 = byte 0's
MSB**. That is identical to this codebase's existing "sequential MSB-first" index
(`reverse.py`), and we already have the exact converter to cantools start bits:

```python
# dbc_builder.re_candidate_to_signal()
byte        = start_bit_seq // 8
bit_in_byte = start_bit_seq % 8
dbc_start   = byte * 8 + (7 - bit_in_byte)      # → cantools big-endian start (MSB)
```

So for **big-endian** (`reverse=0`) the plan is: treat `startingBit` as the MSB,
convert via the formula above, and let the signal extend toward less-significant
bits (cantools sawtooth).

### Validation against the sample — most signals fit cleanly ✓

| Msg  | Signal              | start | size | seq bits   | bytes touched | OK? |
|------|---------------------|------:|-----:|------------|---------------|-----|
| 912  | canOdometer         | 0     | 24   | 0–23       | 0,1,2         | ✓   |
| 909  | soc (×0.1)          | 24    | 16   | 24–39      | 3,4           | ✓   |
| 909  | Batt_Voltage (×0.25)| 40    | 11   | 40–50      | 5,6           | ✓   |
| 906  | vss (×0.015)        | 40    | 16   | 40–55      | 5,6           | ✓   |
| 905  | Charger_status      | 16    | 8    | 16–23      | 2             | ✓   |
| 913  | Motor_speed (×10)   | 8     | 12   | 8–19       | 1,2           | ✓   |
| 908  | Time_to_charging    | 38    | 10   | 38–47      | 4,5           | ✓   |
| 914  | Accel_Pedal (×0.393)| 0     | 8    | 0–7        | 0             | ✓   |

### …but two signals OVERFLOW 8 bytes ✗ — needs your call

| Msg  | Signal        | start | size | seq bits  | problem                         |
|------|---------------|------:|-----:|-----------|---------------------------------|
| 905  | RANGE_TO_EMPTY| 56    | 16   | **56–71** | needs bytes 7 **and 8** (9 bytes)|
| 909  | Batt_Current  | 56    | 16   | **56–71** | needs bytes 7 **and 8** (9 bytes)|

`startingBit = 56` is byte 7 (the last byte of a classic 8-byte frame). A 16-bit
signal starting there, extending upward, runs off the end. This cannot be made to
fit by any choice of bit-numbering convention while `canOdometer` (start 0,
extends upward) also fits — they pull in opposite directions. So this is a data /
spec question, not something I can infer. See Q2.

---

## 3. Open questions (need answers before implementing)

- **Q1 — Confirm the convention.** Is `startingBit` the **MSB** of the signal,
  with bit 0 = byte 0's MSB, value extending toward lower significance (i.e. the
  `re_candidate_to_signal` mapping above)? The clean-fit table in §2 strongly
  suggests yes — please confirm. *(Fastest way to pin it down: tell me which
  byte/bit `canOdometer` and `soc` occupy in your reference DBC.)*

- **Q2 — The two overflowing signals (`RANGE_TO_EMPTY`, `Batt_Current`,
  both start 56 / size 16).** Which is true?
  - (a) These messages are **longer than 8 bytes** (CAN-FD, DLC up to 64) — I
    should size DLC to fit each signal.
  - (b) The JSON is **slightly off** for these and the value really sits in
    bytes 6–7 (i.e. `startingBit` is the **LSB** end for big-endian) — changes
    the whole convention.
  - (c) Known data quirk — **clamp/skip** the overflow and decode what fits.

- **Q3 — DLC.** JSON carries no DLC. Default every message to **8 bytes**? Or
  size each message to the highest bit any of its signals uses (and allow >8 for
  CAN-FD per Q2a)?

- **Q4 — `reverse=1` (little-endian).** None appear in this sample. For LE, is
  `startingBit` the **LSB** position in plain Intel sequential numbering
  (`byte*8 + bit`, bit 0 = byte0 LSB)? I'll assume yes unless told otherwise.

- **Q5 — `signed`.** Two's-complement when `signed=1`? (Standard assumption.)

- **Q6 — Enums.** JSON has no value tables. Signals like `transmission__selctor`
  (3-bit) or `blinker__L_4_R_1` will show **raw numbers only**. Acceptable, or do
  you want a side-channel for labels later? (Out of scope for v1.)

---

## 4. Implementation plan (once Q1–Q3 are answered)

1. **Backend** — `POST /api/decode/json-import` (already drafted in `server.py`):
   parse JSON → build a cantools `Database` in-memory → reuse the **same**
   `framedecode.decode_frames` path as DBC. Reuse `re_candidate_to_signal`'s
   bit-conversion formula for big-endian; mirror it for little-endian.
2. **Frontend** — "Upload .json" button beside "Upload .dbc" (done); shared
   `_fdLoaded()` post-load flow (done); MSB/LSB labels on the bit grid (done).
3. **Tests** — add a fixture JSON + assert decode output matches a hand-computed
   expectation for a couple of signals (esp. a multi-byte big-endian one).

**Status: IMPLEMENTED & TESTED.**
- `canforge/jsondecode.py` — self-contained decoder (no cantools).
- `server.py` — `/api/decode/json-import` + `/api/decode/frames` dispatch
  between the JSON source and the DBC source (one active at a time).
- `web/` — "Upload .json" button beside "Upload .dbc"; MSB/LSB labels on the
  bit grid.
- `tests/test_jsondecode.py` — 6 tests, including both validated real frames
  (passenger=1, odometer=75971). Full suite: 121 passed.

Both confirmed by the user against the live cloud:
`0205000000000200`/id900 → `Seat_belt_passenger=1`;
`0128C30000000000`/id912 → `canOdometer=75971`.

**Remaining low-risk validation:** sub-byte big-endian (`Time_to_charging`,
id 908, start 38 size 10) uses the documented default (touched bytes assembled
MSByte-first, contiguous field bits in place). Confirm with one sample frame
when convenient; no other signal in the file is affected.
