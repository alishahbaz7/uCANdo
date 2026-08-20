---
name: ui-hygiene
description: Build or review uCANdo web UI — any change to web/index.html, web/style.css or web/app.js. Use when adding a view or panel, styling anything, wiring a REST/WebSocket read into the UI, showing an empty/loading/error state, marking a feature unavailable, or reviewing UI for consistency. Covers the design tokens, the nav-readiness contract, view lifecycle, table/chart rules, and the honesty rules the platform is held to.
---

# uCANdo UI hygiene

The UI is **plain `web/*.{html,css,js}` — no framework, no build step**. Three
files, loaded directly. That is deliberate: the app ships as a PyInstaller bundle
a field engineer runs offline, and a toolchain is one more thing to break.

Work *with* that constraint. Do not introduce npm, a bundler, a framework, a
chart library, a CSS framework, or a CDN link. If something seems to need one,
say so and ask — don't smuggle it in.

## 1. Design tokens — never hard-code a colour

Everything comes from the `:root` custom properties in `style.css`:

| Token | Use |
|---|---|
| `--bg` | page ground, and the well behind inputs |
| `--panel` / `--panel-2` | card/panel surface, and its raised header or control |
| `--line` | every border and divider |
| `--text` / `--muted` | primary copy / secondary copy, labels, units |
| `--accent` / `--accent-soft` | selection, focus, active nav, highlighted bit |
| `--green` / `--green-bg` | connected, OK, download-ready |
| `--red` | error, out-of-range, recording |
| `--warn` | advisory — a pre-flight note that is **not** an error |
| `--mono` | every payload, ID, bit, and numeric field |

Rules:

- **A literal hex in a rule is a bug** unless it is a one-off swatch that must
  not move with the theme (the bit-grid MSB amber `#e0a82e` is the precedent,
  and it is paired in `.bit-legend .sw-msb`).
- Any raw CAN data — IDs, payloads, bit values, timestamps — is `var(--mono)`.
  Numeric columns also get `font-variant-numeric: tabular-nums` so digits stop
  jittering as values update.
- The palette is dark-only by design. Don't add a light theme unless asked.

## 2. Structure: sidebar + topbar + one `.view` per feature

```
.app  (grid: 250px rail | main)
├── .sidebar   .brand · .nav-group-label · .nav buttons · .hw-chip · .nav-legend
└── .main
    ├── .topbar     #viewTitle + #viewDesc + .topbar-actions
    ├── section.view#view-<name>   ← exactly one visible, others .hidden
    └── .statusbar  #statusText
```

Adding a view means touching **four** places, and all four or none:

1. `index.html` — a `<button class="nav" data-view="x">` under the right
   `.nav-group-label`, and a `<section id="view-x" class="view hidden">`.
2. `app.js` `VIEW_META` — `{ t: "Title", d: "one-line description" }`. The
   description is a promise about what the view does; write it for someone who
   has never opened it.
3. `app.js` `VIEW_READY` — only if the view is *not* click-and-it-works (§3).
4. `app.js` `startPolling()` — only if it needs a poll (§4).

Inside a view, the established building blocks are `.toolbar` (controls row),
`.panel` + `.panel-head` (titled card), `.table-wrap` + `.data-table` (scrolling
table with sticky header), `.cards` + `.card` (stat tiles), and `.btn` /
`.btn-mini` / `.btn.ghost`. Reach for these before inventing a class.

**Reuse across views is expected**: the OEM profile drill-down renders with the
Converter's `.cv-msg` / `.cv-sigtable`. But don't refactor a working view to
share code — when the TX Monitor needed a bit grid, duplicating ~30 lines beat
coupling it to the Frame Decoder's selection state. Say so in a comment when you
make that trade.

## 3. The nav-readiness contract — the platform's honesty rule

`VIEW_READY` in `app.js` is the single source of truth for "can I use this yet?".
**A view absent from that table is a promise that it works as-is.** Keep the
table honest; that promise is what makes the rail readable.

| kind | Treatment | For |
|---|---|---|
| `bus` | Dimmed + **"Bus"** pill *only while disconnected*; **still clickable**; in-view `.view-gate` repeats the reason with a Connect button | Built, but does nothing without an adapter |
| `input` | Full brightness, standing **"Log"/"DBC"/"File"** pill | Built, works offline, needs a file first |
| `soon` | Greyed, **navigation blocked**, "Soon" pill | Not available to the user |

The reasoning behind each, which you must preserve:

- **`bus` stays clickable.** A disabled nav item hides what the tool can do; a
  dimmed one with a stated reason teaches. The pill disappears on connect,
  because a pill only earns rail space while it is telling the truth.
- **`soon` blocks navigation.** An empty reachable panel is what reads as broken.
- **`soon` means "not available to the user", not "not written."** Several views
  are fully implemented and test-covered but held back by product decision. Each
  such line records the `kind` to restore when it ships — keep that note.

Two invariants that silently dead-end the app if broken:

- The startup view (`dashboard`) must never be `soon`.
- No `goView()` target (`framedec`, `convert`) may be `soon`.

`index.html`'s `.nav-legend` block explains this convention to the user and
**must stay in sync with the pill strings**.

## 4. Data flow: WebSocket for live aggregates, REST poll per view

- `/ws/live` pushes `logger.snapshot()` + `replayer.status()` at ~5 Hz. Logger
  and TX ride it. **Never add a per-frame WebSocket message** — at 1 000+ fps
  that floods the UI. New live data belongs *in the snapshot*.
- Everything else polls its own REST endpoint through the single `pollTimer`,
  swapped on nav change in `startPolling()`. One timer, one view. Intervals in
  use are 400-700 ms; match a neighbour rather than inventing a rate.
- **`contracts.py` is the source of truth for the snapshot shape.** Change it and
  `app.js` `render()` together, in the same commit, or the UI reads keys that no
  longer exist.

Helpers, use them: `$(id)`, `api(path, opts)`, `POST(path, body)`,
`apiUpload(path, file)`. Icons come from the inline `ICONS` map (Feather-style,
`currentColor`) — no icon font, no image files.

**Windows path gotcha:** REST endpoints taking a `path` receive JSON, and
backslashes are invalid JSON escapes. The UI uploads files (multipart →
`data/uploads/`) and passes the server path back. Keep doing that.

## 5. States: empty, stale, error, advisory

A panel that shows nothing must say why. The app has a ladder — pick the rung
that matches:

- `.empty-anim` / `.idle-hero` — a first-run or no-data state worth making
  inviting (animated bus, quick-start cards, rotating tips).
- `.view-gate` — this view needs a bus; auto-inserted for `bus` views.
- `.placeholder` / `.fd-placeholder` — "pick something on the left".
- `.muted-line` — a quiet standing hint under a control.
- `.warn-line` (`--warn`) — **advisory, not an error.** Pre-flight notes before
  a transmit live here.
- `.err` (`--red`) — an actual failure.
- `setStatus()` — transient feedback in the status bar.

**Staleness is per-signal, not per-tick.** A value is stale when it is older than
`SIG_STALE_FACTOR ×` *that signal's own* median period (`sigBuildMeta`). The
naive "no fresh frame this row" rule makes a healthy 100 ms signal strobe grey on
a 10 ms grid. Stale renders as dimmed with a `title` explaining it is held.

Never let a computed value look authoritative when it isn't. Values outside the
DBC's own declared range are flagged red — `.sig-tile.oor` on a tile, `td.tc-oor`
in a table — because that is the fastest tell for a wrong scale or signedness.

## 6. Tables and charts

- Build rows **lazily for the visible window only** — walk a forward cursor into
  the already-sorted series. Never materialise a full matrix.
- One **zoom** control drives both the chart window and the table row interval,
  so "time resolution" means one thing in the view.
- Charts are hand-drawn on `<canvas>`. **No chart library.**
- Export: CSV is built client-side; `.xlsx` goes through
  `/api/signals/export-xlsx` because only Excel can carry the held/changed cell
  colouring.
- Long text in a table cell gets a bounded `max-width` and wraps (`.fd-desc`);
  everything else is `white-space: nowrap` with `text-overflow: ellipsis`. A
  table must never push the layout wide.

## 7. Traps already paid for — don't re-introduce

- **`[hidden]` loses to any author `display` rule.** `.panel { display: flex }`
  beat the UA's `[hidden] { display: none }`, so panels never hid. `style.css`
  restores it with `[hidden] { display: none !important; }` — keep that rule, and
  prefer the `.hidden` class in markup.
- **Bare `<input>` has no `type`.** Styling only `input[type=text]` left most of
  this app's fields as white boxes on a dark UI. The selector list covers
  `input:not([type])` — extend that list, don't add a parallel one.
- **Form controls don't inherit the page font**; the global
  `button, input, select, textarea { font-family: inherit }` fixes it.
- Honour `@media (prefers-reduced-motion: reduce)` for anything that animates —
  every existing animation already does.

## 8. Accessibility and interaction basics

- Nav items are `<button>`, not `<div>`. `aria-disabled` tracks `soon`.
- Every icon-only control needs a `title`.
- Focus is visible: `border-color: var(--accent)` plus a soft ring — never
  `outline: none` without a replacement.
- Anything destructive (clearing ECU codes, deleting a profile) confirms first,
  and reads as destructive (`.btn-clear`).

## 9. Before you call it done

- [ ] No hard-coded colours; tokens used throughout
- [ ] Raw CAN data in `var(--mono)`; numeric columns `tabular-nums`
- [ ] New view registered in all four places (§2)
- [ ] `VIEW_READY` honest; `.nav-legend` still matches the pills
- [ ] Startup view and every `goView()` target are not `soon`
- [ ] `contracts.py` and `app.js` `render()` changed together, if either changed
- [ ] Empty / stale / error states all say *why*
- [ ] Run it and look: `python main.py` (see the `run` skill), click the view
      both connected and disconnected

Verify in the real app, not just by reading the diff — the disconnected state is
the one that regresses unnoticed.
