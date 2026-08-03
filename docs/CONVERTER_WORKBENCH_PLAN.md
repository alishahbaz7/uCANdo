# Converter v2 — Upload → Preview / Edit / Select → Export

Evolves the one-shot Converter into a small **workbench**: upload a file, see
what's inside, optionally edit fields and pick a subset of signals, then export
to any format (or re-save the same format after editing).

The conversion core (`ucando/convert.py`, canonical model + 6 serializers) is
already done and stays the engine; this is a **flow + UI + two thin endpoints**
layer on top.

---

## 1. The new flow

```
┌─────────┐   Upload    ┌──────────────────────────┐   Download    ┌──────────┐
│  pick   │ ──────────► │  PREVIEW / EDIT / SELECT  │ ────────────► │ file out │
│  file   │   (parse)   │  messages + signals table │   (export)    │          │
└─────────┘             └──────────────────────────┘               └──────────┘
                          ▲ edit fields · tick signals · choose target format
```

1. **Upload** (button 1) → parse the file into the canonical model, show a
   preview. *No download yet.*
2. **Preview / Edit / Select** → table of messages & signals, each with a
   checkbox; fields editable; ambiguous params flagged.
3. **Download** (button 2) → serialize the (edited, filtered) model to the
   chosen format and save it.

This directly implements your points **#2 (preview), #3 (select), #4 (two
buttons), #7 (edit then export same/other format)**.

---

## 2. Point-by-point

### #1 — No same-format conversion (reconciled with #7)
The **Export-as** selector lists only the **other two** formats by default
(so DBC→DBC etc. never shows as a pointless "conversion"). **The moment you edit
anything, the source format is added back** to the selector, labelled
`DBC (save edits)` — that's how #7's "upload DBC → edit → download DBC" works.
*(Alternative: two explicit buttons "Convert to…" + "Save edits". See Q1.)*

### #2 — Preview after upload
After upload, a read-only preview lists every message
(`can_id · name · DLC · #signals`) and, expanded, its signals
(`name · start · len · order · scale/offset · unit`) — same columns the Frame
Decoder catalogue uses, so it's familiar. A header strip shows
`source: DBC · 15 messages · 33 signals`.

### #3 — Partial / full selection
- A checkbox on every **signal** and every **message** (message checkbox =
  select/clear all its signals).
- A global **Select all / none** + a live **"12 of 33 signals selected"** counter.
- Only ticked signals (and the messages that still have ≥1 signal) are exported.

### #4 — Upload and Download are separate buttons
- **Upload** → parse + preview (button 1).
- **Download** → export the current selection/edits (button 2), disabled until a
  file is loaded and ≥1 signal is selected.

### #5 — Filename convention
- **JSON** → `Signature_{sourceStem}_DDMMYY_HHMMSS.json`
- **DBC**  → `{sourceStem}_DDMMYY_HHMMSS.dbc`  *(Q2)*
- **CSV**  → `{sourceStem}_DDMMYY_HHMMSS.csv`  *(Q2)*

`sourceStem` = uploaded filename without extension. Timestamp generated at
export. (Browsers can't pick the save folder programmatically — the file goes to
the browser's Downloads dir; the filename is what we control.)

### #6 — Comments for uncertain parameters
When a parameter can't be represented exactly in the target, the converter
**annotates that signal** rather than failing silently:
- **→ DBC**: a `CM_` signal comment, e.g.
  `uCANdo: sub-byte big-endian (size 11) — verify bit layout`.
- **→ CSV**: the same text appended to the `comment` column.
- **→ JSON**: JSON has no comment field → reported in the on-screen warnings list
  (and, if the user confirms, we *could* add a non-standard `"_note"` key — but
  that would deviate from your cloud format, so **off by default**, see Q3).
The current sub-byte-big-endian self-check already finds these cases; this just
routes the note into the file.

### #7 — Edit then export (same or different format)
The preview is also an **editor**. Editable per signal: name, start_bit, length,
byte_order, signed, scale, offset, min, max, unit, value_table, comment. Per
message: name, can_id, dlc, is_extended. After any edit the source format becomes
a valid export target (see #1), so "upload DBC → tweak a scale → download DBC"
works, as does exporting the edits to a different format.

---

## 3. Architecture (small, reuses the engine)

The canonical model is already plain JSON-able dicts, so it travels to the
browser, gets edited there, and comes back:

- **`POST /api/convert/parse`** *(multipart upload)* →
  `{ok, source_fmt, source_name, model, warnings, summary}`.
- **`POST /api/convert/export`** *(JSON body
  `{model, to, source_fmt, source_name}`)* → `{ok, filename, content, warnings}`.
  Filtering (selection) happens client-side before sending; editing mutates the
  model in JS. The endpoint just runs the existing `model_to_*` serializer +
  filename rule + doubt-comment injection.
- The existing one-shot `POST /api/convert` stays for the simple path / tests.

`ucando/convert.py` gains: `model_to_dbc`/`model_to_csv` inject doubt comments;
a tiny `inject_doubts(model)` helper marks sub-byte-BE signals; everything else
unchanged.

**UI** — the Converter view becomes: upload bar → summary strip → editable
message/signal table with checkboxes → export bar (format selector + Download).
Built in plain JS like the rest; the model lives in a JS variable.

---

## 4. My feedback & suggestions (to enhance the experience)

- **Live loss-preview**: when you pick a target format, show *before* download
  what will be dropped — e.g. choosing JSON greys out and lists "units, min/max,
  value tables, message names will be dropped (8 signals affected)". Turns #6
  from a post-hoc note into upfront clarity.
- **⚠ marker in the preview** on ambiguous signals (sub-byte big-endian), with a
  tooltip — so you see the doubt while selecting, not only after export.
- **Search / filter box** in the preview (real DBCs have hundreds of signals).
- **Inline edit validation** (soft, non-blocking): flag `start_bit+length`
  overflowing the DLC, overlapping signals, duplicate names — caught before you
  ship a broken file.
- **"Send to DBC Builder / Signal Viewer"** action from the preview, so a parsed
  file flows into the rest of uCANdo (decode it live, etc.).
- **Remember last export format** and **drag-and-drop** upload — small polish.
- **Scope note / overlap**: editing + multi-format here overlaps the DBC Builder.
  Suggest the Converter stays "load → trim/tweak → re-emit", and deep authoring
  (adding messages/signals from scratch) remains the DBC Builder's job — unless
  you want the Converter to also add/delete rows (Q4). Sharing one editor widget
  between the two later would avoid duplication.

---

## 5. Decisions (locked)

- **Q1 — Same-format UX → auto-add source format after an edit.** Export
  selector shows the other two formats; editing anything adds the source format
  back as `<FMT> (save edits)`.
- **Q2 — Filenames → `{stem}_DDMMYY_HHMMSS.ext`**, with JSON additionally
  prefixed `Signature_`. No type prefix on DBC/CSV.
- **Q3 — JSON doubt notes → on-screen only.** JSON stays byte-for-byte the cloud
  format; DBC (`CM_`) and CSV (`comment` column) still get inline notes.
- **Q4 — Edit scope → edit existing fields + select subset.** No add/delete of
  messages/signals in v1 (that stays in the DBC Builder).
- **Q5 — Selection → signal-level + message-level checkboxes** + select-all.

**Status: IMPLEMENTED & TESTED.**
1. ✅ `convert.py`: `_be_doubt()` + `inject_doubts()`; `parse()`/`serialize()` split;
   doubt comments injected into DBC (`CM_`) and CSV (`comment` col); signal
   comments now exported to DBC.
2. ✅ `POST /api/convert/parse` (→ editable model) + `POST /api/convert/export`
   (model → file, with the `Signature_…`/`{stem}_DDMMYY_HHMMSS` filename rule).
3. ✅ Converter UI: Upload → source chip + summary → editable message/signal
   table with per-signal & per-message checkboxes, filter box, ⚠ doubt markers,
   live loss-preview, "N of M selected" counter; **Download** disabled until ≥1
   signal selected; same-format option appears only after an edit.
4. ✅ `tests/test_convert.py` — 12 tests (all directions, round-trips, doubt
   tagging/commenting, subset export, parse/export endpoints, filename rule).
   Full suite: **135 passed**.
