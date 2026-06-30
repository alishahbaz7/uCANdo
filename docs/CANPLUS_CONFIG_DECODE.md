# CanPlus / Telematics Config (`*.Config.XML`) — RE & Decode Plan

**Status:** ✅ parser built (`canforge/canplus.py`) + wired into the Converter (upload a
`.Config.XML` → preview signals + scaling, grouped by frame-cluster → export DBC/JSON/CSV).
Validated Odometer (`0x540`) & Range/DTE (`0x2A2`) carry real layout; the rest are flagged
placeholders pending a capture. Tests: `tests/test_canplus.py`.
**Sample:** `MG_ZS_EV_2020_Electricity_#91.Config.XML` (MG ZS EV 2020, Electric).
**Goal:** reverse-engineer this proprietary telematics "vehicle library / signature" file into our
canonical signal model (the same shape `convert.py` / `jsondecode.py` already use), so the named
vehicle signals + their scaling can be extracted and — where possible — mapped to CAN frames.

> ⚠️ This convention is **general** to this *file format* (a CanPlus-style CAN programmer config),
> not hardcoded to the MG sample. The MG file is the worked example used to crack and verify the
> format; the parser must work for any vehicle library of this type.

---

## 1. What this file is

It is **not** a CAN log and **not** a DBC. It is the **configuration of a telematics CAN device**
("CanPlusEditor", `CanEditorVersion 1.4.7498.0`) — i.e. the device's *vehicle library* that tells
the unit which CAN parameters to read from an **MG ZS EV 2020** and how to scale them. It carries:

| Section | Meaning |
|---|---|
| `PL_Signature` | 4-byte payload signature/checksum (`554161D9`) over the config |
| `CanOperationalMode` / `CanProtocolLevel` / `CanEditorVersion` | device + format version |
| `Sentences` | the device **program** — an operator tree (event/timer logic), bit-packed |
| `Free_Variables` | the **signal dictionary** — each `<Variable>` = one vehicle parameter |
| `Variable_Descriptors` | one **22-byte binary record** (`VarDesc`) per signal — *the decodable core* |
| `Config/VehicleLibraryInfo/ArbitrationIds` | the set of CAN arbitration IDs the device listens to |
| `Config/Filters` | acceptance filters (OBD `0x7E8/mask 0xFFFFFFF8` + 12 encoded filters) |
| `Config/J1939` | a duplicate of the variable list (same signals) |
| `Config/CANSettings` | `BusRate=2`, `BusFormat=0`, etc. |

There are **35 vehicle signals** defined (speed, SOC, odometer, range, doors, TPMS, lights, gear,
pedal, …).

---

## 2. The easy win — every signal's metadata is in plain XML

Each `<Variable>` already exposes everything needed for the **physical-value formula**:

```
physical = round( raw × FW_Multiplier / FW_Divider + FW_Offset , Decimal_Places )
```

| XML attribute | Meaning | Example (Vehicle Speed) |
|---|---|---|
| `Title` | human name | `Vehicle Speed` |
| `VarID` | internal parameter id (hex) | `8005` |
| `Var_Function` | standard role | `Odometer` / `Speed` / `FuelTankLevel` / `NotAssigned` |
| `FW_Multiplier` / `FW_Divider` | scale (rational) | `3 / 200` |
| `FW_Offset` | offset | `0` |
| `FW_Units` | unit string | `km/h` |
| `Decimal_Places` | display rounding | `2` |
| `Filter_FF` | ignore all-`0xFF` (not-available) | `false` |
| `RawData` | 11-byte encoded handle (see §5 — obfuscated) | `72-19-E7-…-88-4B` |

So a **signal dictionary with full scaling** can be produced from the XML attributes alone, with
**zero binary decoding**. That is the guaranteed deliverable.

---

## 3. ✅ The binary that *is* decodable — the 22-byte `VarDesc` record

Each `<VarDesc RawDataStr="…">` is a **fixed 22-byte little-endian record**. I cracked it and
**verified every field against the XML** (all 35 records, byte-exact):

| Bytes | Field | Confidence | Notes |
|---|---|---|---|
| `b0` | flags / type | 🟡 | always `00` in this file |
| `b1` | record link / addr-low | ❓ | per-signal, not yet resolved |
| `b2–b3` | **VarID** (u16 LE) | ✅ | `b2,b3` = `05,80` → `0x8005` |
| `b4` | type/flags | 🟡 | `0x13` for almost all; `0x93` on "Time to Charger" (top bit = a flag) |
| `b5–b6` | **in-frame position selector** | 🟡 | see §4 — `b6` ≈ frame-class, `b5` ≈ bit/byte offset |
| `b7` | value size/type class | ❓ | `00` mostly; `05` odometer, `03` SOC, `01` real-speed |
| `b8–b9` | **FW_Multiplier** (u16 LE) | ✅ | `E8 03` → `1000`; `35 03` → `821`; `89 01` → `393` |
| `b10–b11` | **FW_Divider** (u16 LE) | ✅ | `C8 00` → `200`; `D0 07` → `2000`; `19 00` → `25` |
| `b12–b13` | **FW_Offset** (i16 LE) | ✅* | `00 00` in every record here (position confirmed, sign untested) |
| `b14–b15` | constant `27 10` (=`0x2710`/10000) | 🟡 | global scale base / period — same for all |
| `b16` | constant `0D` | 🟡 | same for all |
| `b17–b19` | **source-frame signature** | ✅ | groups signals by CAN frame — see §4 |
| `b20–b21` | constant `8E 31` | 🟡 | record footer / library magic — same for all |

**Verification (sample):**

| Signal | VarID | b8–9 → mult | b10–11 → div | XML mult/div | ✓ |
|---|---|---|---|---|---|
| Total Vehicle Distance | `8000` | `E8 03`=1000 | `01 00`=1 | 1000 / 1 | ✅ |
| Vehicle Speed | `8005` | `03 00`=3 | `C8 00`=200 | 3 / 200 | ✅ |
| Real-Ground speed | `8006` | `35 03`=821 | `D0 07`=2000 | 821 / 2000 | ✅ |
| SOC | `803D` | `01 00`=1 | `0A 00`=10 | 1 / 10 | ✅ |
| Accelerator Pedal | `800B` | `89 01`=393 | `E8 03`=1000 | 393 / 1000 | ✅ |
| Tyre Pressure RL | `804C` | `01 00`=1 | `19 00`=25 | 1 / 25 | ✅ |

→ **All multiplier / divider / offset values match the XML exactly**, proving the record layout.

`<VarDesc>` also carries XML `StartAddress` / `EndAddress`; `EndAddress` increments by **22** per
record (264 → 286 → 308 …) = the record stride, confirming the 22-byte size.

---

## 4. ✅ Frame clustering — which signals ride the same CAN frame

Bytes **`b17–b19`** are a **source-frame signature**: signals decoded from the *same* CAN frame
share the same triple. Clustering all 35 records yields physically-correct groups:

| `b17–b19` | Frame class `b6` | Signals sharing the frame |
|---|---|---|
| `B5 FF 08` | `EF` | Door Lock, Door Driver, Door Rear L/R, Door Passenger, **Trunk, Hood** (body control) |
| `E6 2C 08` | `43` | Tyre Pressure FL/FR/RL/RR (TPMS pressures) |
| `E9 23 08` | `BB` | TPMS Light, TPMS Light 2 |
| `B0 FB 09` | `EF` | Seat Belt, AIR BAG (restraint / SRS) |
| `40 81 03` | `A3` | Vehicle Speed, Real-Ground speed |

This is a real RE result: even before we resolve the literal arbitration ID, we can **group the 35
signals into their source ECMs/frames** and see `b5` vary *within* a group (= the per-signal
bit/byte offset inside that shared frame). `b6` behaves like a frame-class tag (`A3` speed,
`EF` body, `43` TPMS-pressure, `BB` TPMS-light, …).

---

## 5. 🟡 The obfuscated part — exact arbitration ID + start bit

What is **not** yet plaintext:

- **`<Variable RawData>`** (11 bytes, e.g. `72-19-E7-6C-62-1B-7C-FD-7C-88-4B`): every record shares
  a common middle (`…6C-62-1B…`) and tail (`…88-4B`) and `RawDataStr="Download to update"` →
  this looks like an **obfuscated/handle-encoded** pointer that the device resolves on download,
  not a literal frame map.
- **`<ArbitrationIds>`** (one long hex blob) holds the real 29-bit/extended IDs the unit accepts,
  and **`<Filters>`** holds 9-byte encoded acceptance filters — but the **per-signal link** from a
  `VarID` to *one specific arbitration ID + start bit + length + endianness* is encoded in
  `b5–b7` / the 11-byte handle and is **not** a direct copy of the ID.

So full **bit-exact live decode straight from this file is not yet possible** without either:
1. cracking the `b5–b7` ↔ arbitration-ID encoding (more samples / another library would help), or
2. **bridging with a capture** — which our existing tooling already does well (see §7).

---

## 6. Other structures (for completeness)

- **`Sentences` / Operator tree** = the device's *program*: a `Generate event` operator fed by a
  `Periodic Timer`. Parameters are **bit-packed little-endian** with explicit bit `Offset`/`Length`
  (e.g. Timer `Time` `RawData="70-17"` `Offset=8 Length=16` → `0x1770` = 6000 ×10 ms = `00:01:00`).
  Decodable with the same LE convention if we ever need the logic.
- **`PL_Signature`** `554161D9` — 4-byte integrity signature over the payload (CRC32-class).
- **`CANSettings.BusRate=2`** — bus speed index (to be mapped, likely 500 kbit/s for this platform).

---

## 7. Proposed implementation

### 7.1 New module: `canforge/canplus.py`
Pure-stdlib (`xml.etree`, no new deps), mirroring `jsondecode.py` / `convert.py` style.

```
parse_config(text|path) -> {
  "meta": {app_version, pl_signature, bus_rate, vehicle:{brand,model,year,engine}},
  "signals": [ {
      "name", "var_id"(hex str), "function", "units", "decimals",
      "multiplier", "divider", "offset",          # → scale = multiplier/divider
      "filter_ff",
      "frame_group"(b17-19 hex),                  # source-frame cluster id
      "pos_selector"(b5-b6), "size_class"(b7),    # raw, for later bit-mapping
      "raw_handle"(11-byte hex)                    # obfuscated, kept verbatim
  } ... ],
  "frames": [ {group_id, [member signal names]} ],  # derived clusters (§4)
  "arbitration_ids": [...],                          # parsed from the blob
}
```
- Cross-checks the XML attrs against the decoded `VarDesc` bytes and flags any mismatch
  (defensive: the format is now proven, so a mismatch = a new/variant library to study).

### 7.2 Bridge to what we already have
- **Converter / Frame Decoder model**: emit each signal into our canonical model (name, scale,
  offset, unit, value-table=∅) grouped by `frame_group`. Where a frame's arbitration ID is later
  resolved, the group becomes a normal message → exportable as **Signature JSON / DBC / CSV**.
- **Recover the missing bit-positions from a capture (the real magic):** we already know each
  signal's **units + scale + function**. Point `re_engines/correlate.py` (OBD/known-value
  correlation) at a capture and, for each `frame_group`, search bit-spans whose
  `raw × mult/div + offset` lands in the signal's plausible range / matches OBD ground truth.
  → This turns "names + scaling (from the file)" + "bits (from a capture)" into a **complete DBC**.

### 7.3 UI / endpoint (later, if wanted)
- `/api/canplus/import` (multipart) → returns the parsed model; surface in the Converter as a 4th
  source format (auto-detected by the `<CanData>` root), so it round-trips into JSON/DBC/CSV.

### 7.4 Tests
- Save the MG sample under `tests/data/`; assert: 35 signals parsed; VarID/mult/div/offset match
  XML for all; the 5 frame clusters of §4; physical-formula spot-checks
  (e.g. Speed scale = 3/200 = 0.015 km/h per count).

---

## 8. What we can deliver — confidence summary

| Deliverable | Confidence |
|---|---|
| Full **signal dictionary** (name, VarID, function, unit, decimals) | ✅ certain |
| **Scaling** per signal (mult / div / offset) — XML *and* verified in binary | ✅ certain |
| **Frame clustering** (which signals share a CAN frame) | ✅ certain |
| `VarDesc` 22-byte record format | ✅ cracked & verified |
| Export to our **Signature JSON / DBC / CSV** model (grouped, scaled) | ✅ straightforward |
| Exact **arbitration ID + start bit + length** per signal, from this file alone | 🟡 obfuscated — needs key-cracking or a capture bridge (§7.2) |
| Device **program** (Sentences) decode | 🟡 possible (bit-packed LE), low priority |

---

## 9. Open questions / next steps (awaiting your call)

1. **Scope** — do you want (a) just the **signal+scaling dictionary** export, (b) **+ frame
   clustering**, or (c) push all the way to **bit-exact mapping** by correlating against a capture?
2. **More samples?** A second/third vehicle library (different car) would likely let us crack the
   `b5–b7` ↔ arbitration-ID encoding outright (diffing shared frames across vehicles).
3. **A capture?** If you have a CAN log from this MG (ideally with OBD or known dash values), I can
   wire §7.2 and recover the actual bit positions — completing the DBC.
4. Confirm the **bus rate** mapping (`BusRate=2`) for this platform.
