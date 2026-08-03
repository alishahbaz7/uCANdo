# Format Converter — Design & Clarification

**Goal:** A new **Converter** segment that converts a signal database among the
three formats in **any** direction:

```
        ┌──────┐
        │ DBC  │
        └──┬───┘
     ┌─────┴─────┐
┌────▼───┐   ┌───▼────┐
│  JSON  │◄─►│  CSV   │
└────────┘   └────────┘
   (all 6 directions: DBC↔JSON, DBC↔CSV, JSON↔CSV)
```

- **JSON** = the exact cloud Signature format already supported (see
  `docs/JSON_SIGNATURE_DECODE.md`).
- **CSV** = a flat, Excel-friendly table; header template proposed below.
- **DBC** = standard Vector database (via cantools).

Upload one file → pick the target format → download the converted file.

---

## 1. The three formats carry different information

| Field | DBC | JSON (Signature) | CSV (proposed) |
|---|:--:|:--:|:--:|
| CAN ID | ✅ hex | ✅ **decimal** | ✅ (Q1) |
| Extended (29-bit) flag | ✅ | ❌ | ✅ |
| Message name | ✅ | ❌ (auto `MSG_<id>`) | ✅ |
| DLC | ✅ | ❌ (inferred) | ✅ |
| Signal name | ✅ | ✅ `fieldName` | ✅ |
| Start bit | ✅ cantools conv. | ✅ Intel LSB-seq | ✅ (Q2) |
| Length (bits) | ✅ | ✅ `size` | ✅ |
| Byte order | ✅ | ✅ `reverse` | ✅ (Q3) |
| Signed | ✅ | ✅ | ✅ |
| Scale / multiplier | ✅ | ✅ | ✅ |
| Offset | ✅ | ✅ | ✅ |
| Min / Max | ✅ | ❌ | ✅ |
| Unit | ✅ | ❌ | ✅ |
| Value table (enums / `VAL_`) | ✅ | ❌ | ✅ (Q6) |
| Comment | ✅ | ❌ | ✅ |
| `evData` flag | ❌ | ✅ | ✅ |
| Multiplexing | ✅ | ❌ | ❌ (Q7) |

**Consequence — some conversions are lossy (unavoidable):**
- **→ JSON** drops message name, DLC, min/max, unit, value tables, comments
  (the JSON format simply has no place for them).
- **JSON →** synthesizes the missing parts (name `MSG_<id>`, DLC computed,
  empty unit/min/max).
- **DBC ⇄ CSV** is the *fullest-fidelity* pair (CSV is the union of fields).

The converter will **report exactly what was dropped** per conversion so the
loss is never silent.

---

## 2. CSV template (LOCKED — per your answers)

One **row per signal**; message-level columns repeat on each of a message's
rows. UTF-8, comma-separated, header row, blank for "not set".
**Decisions:** `can_id` = **decimal** · `byte_order` = **Motorola/Intel** ·
value tables **included**.

```csv
message_name,can_id,is_extended,dlc,signal_name,start_bit,length,byte_order,signed,scale,offset,min,max,unit,value_table,comment,ev_data
MSG_900,900,0,8,Seat_belt_passenger,8,1,Motorola,0,1,0,,,,,,0
MSG_900,900,0,8,Seat_belt_driver,12,1,Motorola,0,1,0,,,,,,0
MSG_912,912,0,8,canOdometer,0,24,Motorola,0,1,0,0,16777215,km,,,0
MSG_909,909,0,9,soc,24,16,Motorola,0,0.1,0,0,100,%,,,0
MSG_909,909,0,9,Batt_Current,56,16,Motorola,0,0.05,1000,,,A,,,0
MSG_902,902,0,8,transmission__selctor,24,3,Motorola,0,1,0,0,7,,0:P;1:R;2:N;3:D,gear,0
```

| Column | Meaning |
|---|---|
| `message_name` | message name (DBC `BO_` name; JSON has none → `MSG_<id>`) |
| `can_id` | CAN arbitration ID — **decimal** (matches the JSON format) |
| `is_extended` | `1` = 29-bit, `0` = 11-bit |
| `dlc` | data length in bytes |
| `signal_name` | signal / `fieldName` |
| `start_bit` | start-bit position — **Intel/LSB-first sequential**, same as JSON (Q2) |
| `length` | signal length in bits |
| `byte_order` | **`Motorola`** (big-endian) or **`Intel`** (little-endian) |
| `signed` | `1` = two's complement |
| `scale` | multiplier |
| `offset` | offset (physical = raw·scale + offset) |
| `min`, `max` | physical range (blank if none) |
| `unit` | engineering unit |
| `value_table` | enum map, `;`-separated `raw:label` pairs (blank if none) |
| `comment` | free text |
| `ev_data` | JSON `evData` passthrough (`0`/`1`) |

> On import the parser also accepts `big_endian`/`little_endian` and `0`/`1`
> for `byte_order` (case-insensitive), but **writes** `Motorola`/`Intel`.

---

## 3. Bit-position handling (the technical core)

JSON `start_bit` is **Intel/LSB-first sequential** (validated last session:
passenger=1, odometer=75971). DBC/cantools uses a **different** start-bit
numbering (Intel = LSB position; Motorola = MSB sawtooth position). The
converter holds a single **canonical model** and converts at each boundary,
reusing the validated mapping in `ucando/jsondecode.py` /
`dbc_builder.re_candidate_to_signal`:

- **little-endian**: JSON `start_bit` == cantools `start` (direct).
- **big-endian, byte-aligned**: cantools `start = (start_bit // 8) * 8 + 7`
  (verified on `canOdometer`).
- **big-endian, sub-byte**: *ambiguous* — only `Time_to_charging_`
  (id 908, start 38, size 10) hits this. Flagged for review (Q9); all other
  multi-byte BE signals in the sample are byte-aligned.

**Proposal:** CSV uses the **same Intel/LSB-seq** `start_bit` as JSON (one
mental model across the two simple formats; cantools conversion happens only at
the DBC boundary). Confirm in Q2.

---

## 4. Decisions & defaults

**Answered by the user:**
- **Q1 — `can_id` base → DECIMAL** (matches the JSON Signature format; DBC
  export still renders hex internally).
- **Q3 — `byte_order` → `Motorola` / `Intel`** (import also accepts
  `big_endian`/`little_endian`/`0`/`1`).
- **Q6 — Value tables → INCLUDED** (`value_table` column; survive DBC⇄CSV,
  dropped only on →JSON).
- **Q10 — Scope → ALL 6 DIRECTIONS** in v1.

**Defaults I'll use unless you say otherwise:**
- **Q2 — `start_bit` = Intel/LSB-first sequential** (identical to JSON; the one
  validated convention). cantools conversion happens only at the DBC boundary.
- **Q4 — Lossy →JSON**: synthesize `MSG_<id>` names, drop unit/min/max/enums/
  comment, and **report** every dropped field in the conversion summary.
- **Q5 — DLC for JSON→DBC**: computed length (≥8 bytes, grows for the EV
  battery/range messages) — same rule as the decoder.
- **Q7 — Multiplexed DBC signals**: skipped in v1 with a warning (rare in this
  fleet/telematics context).
- **Q8 — CSV dialect**: comma-separated, UTF-8, one header row, fields with
  commas quoted (Excel-compatible).
- **Q9 — Sub-byte big-endian**: byte-aligned BE converted exactly; the rare
  sub-byte BE case (`Time_to_charging_`) is converted best-effort **and flagged**
  in warnings.

---

## 5. Proposed implementation (after Q1–Q10 are settled)

1. **`ucando/convert.py`** — a **canonical model** (reuse the DBC-Builder dict
   shape: name, frame_id, dlc, signals[start_bit, length, byte_order, scale,
   offset, min, max, unit, choices, comment, ev_data]) plus six functions:
   `dbc_to_model` / `json_to_model` / `csv_to_model` and
   `model_to_dbc` / `model_to_json` / `model_to_csv`, with one
   `convert(src_fmt, dst_fmt, text) -> (text, warnings)` dispatcher.
   - DBC via cantools (reuse `dbc_builder` import/export paths).
   - JSON reuses `jsondecode` for parsing + the bit mapping.
   - CSV via stdlib `csv`.
2. **API** — `POST /api/convert` (multipart upload + `to=dbc|json|csv`,
   `from=` optional/auto-detected) → `{ok, filename, content, warnings,
   summary:{messages, signals, dropped:[...]}}`.
3. **UI** — new **Converter** nav item: drop/upload a file (auto-detect by
   extension + content), choose target format, **Convert**, see a summary +
   warnings, **Download** (timestamped filename like the DBC export).
4. **Tests** — round-trip fidelity (DBC→CSV→DBC equal where lossless;
   DBC→JSON→DBC equal on the fields JSON preserves), plus the two validated
   frames still decode after a JSON→DBC→JSON round-trip.

**Status: IMPLEMENTED & TESTED.**
- `ucando/convert.py` — canonical model + 6 parsers/serializers + `convert()`.
- `server.py` — `POST /api/convert?to=<fmt>` (multipart upload, auto-detected source).
- `web/` — **Converter** nav segment: choose file → pick target → Convert & Download,
  with a conversion summary + loss/warning notes.
- `tests/test_convert.py` — 7 tests (all 6 directions, CSV↔DBC round-trip stable,
  JSON↔DBC preserves validated signals, sub-byte BE flagged). Full suite: 130 passed.

**Open validation item — non-byte-aligned big-endian.** Three signals are
big-endian *and* not whole-byte-aligned: `Time_to_charging_` (908, 10b),
`Batt_Voltage` (909, 11b), `Motor_speed` (913, 12b). For these, the cloud's bit
model (as implemented in `jsondecode`) and standard DBC Motorola place the
sub-byte bits differently, so DBC export is flagged as approximate. **One sample
frame + expected value for any one of them** (e.g. `Motor_speed`) resolves it for
all three — and would also confirm/adjust the Frame Decoder's decode of them.
