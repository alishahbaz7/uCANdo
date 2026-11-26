---
name: ui-hygiene
description: Build or review uCANdo web UI — any change to web/index.html, web/style.css, web/shell.js or web/app.js. Use when adding a view or panel, styling anything, adding an icon, wiring a REST/WebSocket read into the UI, showing an empty/loading/error state, marking a feature unavailable, opening a dialog, or reviewing UI for consistency. Covers the house tokens and theme, the banner/rail frame, the one NAV definition, the nav-readiness contract, window.UI, the component classes, view lifecycle, and the honesty rules the platform is held to.
---

# uCANdo UI hygiene

uCANdo follows the house UI every one of this user's utilities shares — the user-level
**`utility-ui`** skill (Runway's `web/style.css` + `shell.js` is its web reference). Read that for
the *why* behind the look; this skill is what is specific to uCANdo, and **wins where the two
differ**. Brought onto the house design in v1.6.0 — the plan of record is `docs/UI_REDESIGN_v1.6.md`.

The UI is **plain `web/*.{html,css,js}` — no framework, no build step, no CDN**. Four files:
`index.html` (markup), `style.css` (tokens + kit), `shell.js` (`window.UI`, the frame), `app.js`
(views). The app ships as a PyInstaller bundle run offline; a toolchain is one more thing to break.
If something seems to need npm, a bundler, a framework or a chart library, say so and ask.

## 1. Tokens and theme — never hard-code a colour

Every colour is a `:root` token in `style.css` (Supabase Studio's palette, values from Runway):

| Token | Use |
|---|---|
| `--bg` / `--panel` / `--panel-2` / `--hover` | canvas / rail, banner, cards / header bands, fields, tiles / hover and the open rail item |
| `--border` / `--border-strong` / `--frame` | hairlines / controls / a border that must be seen on dark |
| `--text` / `--dim` / `--muted` | primary / labels and secondary text / tertiary (counts, placeholders) — all ≥ 4.5:1 on every surface, both themes |
| `--accent` (+ `-soft`, `-ink`) | the brand green: focus, active segment, live dot, progress — **used sparingly** |
| `--primary-bg/-border/-text/-hover` | the one primary button per area (deep green with a green edge) |
| `--btn-bg` | every other button: a quiet fill with a `--border-strong` hairline |
| `--ok` / `--warn` / `--danger` / `--info` (+ `-bg`, `-ink`) | fill, soft background, and the colour as text |
| `--danger-fill` / `--on-danger` | the filled red button inside a confirm dialog — nowhere else |
| `--brand` (+ `-soft`) | uCANdo's own blue: the logo, "CAN" in the name, the hero's CAN-H wire. **Not an accent** — a restyle changes the accent, never the logo |
| `--series-1..8` | categorical colours: chart series, the bit-grid layout, signal swatches. JS reads them with `tok()` / `SERIES` |
| `--bit-msb`, `--ink-on-bright`, `--ink-light` | **fixed** swatches (same in both themes): the bit grid's MSB amber and the ink on bright/dark fills |
| `--mono` / `--sans` | every payload, ID, bit, hex field / everything else (bundled Inter) |

- **A literal hex in a rule or an inline style is a bug.** JS that needs a hex (canvas, the bit
  grid's luminance test) reads the token: `tok("--info")`, `SERIES[i]`. Canvases re-read on a
  theme change through `UI.onTheme(fn)` (see the hero canvas).
- **Auto / Light / Dark.** `:root` is dark; `:root[data-theme="light"]` holds the light values in
  ONE block. The person's choice (`ucando.theme`) is resolved to `data-theme` by the `<head>` boot
  script before the first paint and by `shell.js` after — Auto follows the OS and re-resolves when
  it changes. The page also saves the resolved theme to `/api/config ui_theme`, which `main.py`
  reads to open the app window dark or light (§10).
- Bundled **Inter** (`web/fonts/InterVariable.woff2` + OFL licence), served as `font/woff2`.
- Raw CAN data — IDs, payloads, bits, timestamps — is `var(--mono)`; numeric columns `class="num"`
  (right-aligned, `tabular-nums`).

## 2. The frame: banner + rail + one `.view` per feature

```
#banner   logo · u<b>CAN</b>do / Version x (Dev) · [Hello, Name] · page icon + #viewTitle (desc = hold-tip)
          … REC chip / Record · bus chip / Connect · theme button
#app
├── aside#rail   #railNav (built from NAV) · .rail-foot: Settings + Sidebar control
└── main#main    section.view#view-<id>  ← exactly one visible, the rest .hidden
```

- **One navigation definition: `NAV` in `app.js`** — group, `id`, `label` (sentence case), `icon`
  (a name in `shell.js`'s map), `desc` (the page name's hold-tip; write it for someone who has never
  opened the view). It builds the rail (`buildRail()`), titles the banner and the browser tab.
- Adding a view: a `NAV` item, a `<section id="view-<id>" class="view hidden">`, a `VIEW_READY` line
  if it is not click-and-it-works (§3), `startPolling()` if it polls, and the id in
  `ucando/usage.py` `VIEWS` (so opening it is counted).
- **Banner, one control per state:** offline → the green *Connect* button; connected → the bus
  chip ("Virtual · 500 kbit/s", pulsing) whose menu disconnects. Idle → *Record*; recording → the
  red REC chip whose click stops and saves. Never both of a pair at once.
- **Rail:** sentence-case group names; the open view a quiet raised fill (no coloured bar); Sidebar
  control (Expanded / Collapsed / Expand on hover, `ucando.rail`), always Expand on hover under
  1000 px; the edge drags 180–380 px (default 252 — so "Reverse engineering" fits beside a pill).
- **Settings** (`#settingsDlg`): Appearance (theme, sidebar), **Views** (which views the rail
  shows, §3), Recording (log folder), Usage reporting (stage 4 — `hidden` until wired), About
  (version, build, data folder, plugins). On/off choices are `input.ui-switch` (a checkbox drawn
  as a track and knob); a locked one is `disabled` with a `data-tip` saying why.

## 3. The nav-readiness contract — the platform's honesty rule

`VIEW_READY` in `app.js` is the single source of truth for "can I use this yet?". **A view absent
from that table is a promise that it works as-is.**

| kind | Treatment | For |
|---|---|---|
| `bus` | Dimmed + **"Bus"** pill *only while disconnected*; **still clickable**; in-view `.view-gate` (a warn notice + *Connect a bus*) repeats the reason | Built, does nothing without an adapter |
| `input` | Full brightness, standing **"DBC"/"File"** pill | Built, works offline, needs a file first |
| `soon` | **Left out of the rail by default**; `openView()` refuses it — unless switched on in Settings → Views, when it shows with a **"Preview"** pill and opens | Not available to the user |

- **`soon` is hidden, not greyed** — the user, 24-11-2026: "what is not developed, hide for now from
  the menu, to avoid confusion". This **overrides** `utility-ui` §3's "list unbuilt features to
  show the shape" for uCANdo. A group whose items are all hidden disappears with them.
- **Settings → Views decides what the rail shows** — the user, 24-11-2026: "add the option to hide
  and view other tabs from settings". A switch per `NAV` item, grouped as the rail is; the
  person's own choice, kept in this browser (`ucando.views`, only the views that differ from the
  default). Default: every view except `soon` ones. **Dashboard is locked on** (the app opens on
  it). Switching a `soon` view on is a *preview*: it shows with a "Preview" pill and opens.
  Hiding the view you are on goes to the Dashboard; *Reset* restores the default. The rail is
  `buildRail()` over `viewShown(id)`; never filter `NAV` anywhere else.
- **`soon` means "not available to the user", not "not written".** `re`, `autore`, `dbc`, `decoder`
  are implemented and test-covered, held back by product decision; each line records the `kind` to
  restore when it ships — keep that note.
- **Every pill explains itself on hold** (`data-tip`, `PILL_TIPS`); there is no legend. Change a
  pill string and its tip together.
- Invariants that dead-end the app if broken: the startup view (`dashboard`) and every `goView()`
  target (`framedec`, `convert`) are never `soon`.

## 4. `window.UI` (shell.js) — use it, don't re-implement it

| | |
|---|---|
| `UI.icons[name]`, `UI.ico(name, cls)`, `UI.icon(name)`, `[data-icon="name"]` + `UI.paint()` | **the one icon map** (Feather-style line SVG). No `<svg>` anywhere else — not in `index.html`, not as a private map in `app.js` (`ICONS` there is an adapter over `UI.ico`) |
| `UI.setLabel(btn, icon, text)` | an icon and a word on a button (the word as text, never parsed) |
| `UI.confirm({title, text, action, tone:"danger"})` / `UI.notice` / `UI.prompt({title,label,value})` | **never `window.confirm/prompt/alert`** |
| `UI.menu(anchor, title, items, opts)` | a small menu (bus chip, theme, Sidebar control) |
| `UI.toast(text, tone)` — via `setStatus()` | the transient line bottom right (failure wording → red automatically) |
| `UI.resizable(target, opts)` | drag an edge between a min and a max, remembered, double-click resets |
| `UI.setTheme / theme / resolvedTheme / onTheme`, `UI.setRailMode / railMode` | theme and rail |
| `UI.esc(s)` | escape anything you did not write before putting it in `innerHTML` |

All `localStorage` goes through `UI.store` (`ucando.` prefix, every access in try/catch).

## 5. The component kit — reach for these before inventing a class

- **Card:** `.panel` > `.panel-head` (`.ph-t` title + `.ui-count`, `.ph-tools` actions at the
  right) > `.panel-body` (`.row` for a control row) / `.table-wrap`. Stacked cards in a view are
  spaced by `.view > .panel + .panel`.
- **Tiles:** `.cards` > `.card` (`.card-k` label, `.card-v` figure) and the Dashboard's `.gauge` —
  outlined over a soft gradient of their tone, never a coloured left bar.
- **Data grid:** `.data-table` — header band, hairline rows, no zebra, faint hover; `th.num`/`td.num`;
  `tr.row-pick` for clickable rows; `td.row-actions` for the buttons; `.empty-row` for "No rules
  yet." Mono tables: `.data-table.mono` (headers stay in Inter).
- **Buttons:** `.btn` (quiet), `.btn.btn-primary` (one per area), `.btn.btn-danger` /
  `.btn-mini.danger` (red outline: Delete / Remove of something saved — and it **confirms**),
  `.btn-mini` (28 px), `.btn-mini.icon-only` (with `title` + `aria-label`), `.icon-btn` (playback).
  Every action has a word; an icon alone is only for move up/down, zoom ±, fold.
- **Small pills:** `.tag` (+ `.ok/.warn/.bad/.info`) for states; `.rail-pill`; `.ui-chip` in the banner.
- **Lines:** `warnLine(html)` / `badLine(html)` (icon + text) for advisories and failures;
  `.muted-line` for a status line; `.ui-count` for a count beside a heading; `.sub-h` / `.sec-h`
  for a title inside a card; `.ui-notice.ok/.warn/.bad/.muted` for a standing fact with its action.
- **Fields:** inputs 34 px on `--panel-2` with a `--frame` edge; inline labels (`<label>Network
  <select>`) in `.toolbar`, `.controls` and `.panel-body.row` style themselves; `.w-80/100/120/160/200`,
  `label.grow` for widths. **No inline `style="…"`** — `index.html` has none; keep it that way.
- **Segmented:** `.segbar` > `.seg` (`.active`).

## 6. Text — sentence case, and no help text on the page

- **Sentence case everywhere** — headings, labels, buttons, pills, rail, dialog titles. No
  `text-transform: uppercase`, no letter-spaced small caps. Acronyms and data keep their case
  (DBC, OBD-II, hex IDs via `.toUpperCase()` on *data* only). `cap()` turns a server state word
  ("playing") into "Playing".
- **No explanations printed on the page** (`utility-ui` §6, zero tolerance): not under a heading,
  not as a placeholder ("e.g. …", "(optional)"), not as a card caption, not as an empty state with
  directions. The fact stays; the explanation becomes `data-tip` on the title or control (shown
  after the pointer rests 5 s). Placeholders show a format or nothing: `100`, `11 22 AA`,
  `sig('BATT.V') * sig('BATT.I')`.
- **Upload / Download, never Import / Export** (`docs/WAY_WE_WORK.md`).
- Empty and failed states say *why* in one short line ("No rules yet.", "No DBC loaded.",
  "Nothing transmitted yet."), with the action as a button where one exists.
- No emoji or glyphs as icons (⚠ ✕ ★ ◀ ⟳ ▾ …) — an icon from the map, or a word.

## 7. Data flow: WebSocket for live aggregates, REST poll per view

- `/ws/live` pushes `logger.snapshot()` + `replayer.status()` at ~5 Hz; Logger, the banner chips and
  TX ride it. **Never add a per-frame WebSocket message.** New live data belongs in the snapshot;
  `contracts.py` and `app.js` change together.
- Everything else polls its own REST endpoint through the single `pollTimer`, swapped in
  `startPolling()`. 400–700 ms; match a neighbour.
- Work that a view needs on opening goes in `openView()` — e.g. `refreshSigList()` for the Signal
  viewer, because a DBC can arrive from elsewhere (OEM *Apply*, *Identify and apply*); without it
  the list stayed empty after an apply.
- Helpers: `$(id)`, `api()`, `POST()`, `apiUpload()`. Windows paths travel as uploads
  (multipart → `data/uploads/`), never as backslashes in JSON.

## 8. Honest states

- **Staleness is per-signal**: older than `SIG_STALE_FACTOR ×` that signal's own median period.
- **Out of the DBC's declared range is red** (`.sig-tile.oor`, `td.tc-oor`, the "Out of range" tag).
- **Say a thing only while it is true:** "Cannot sustain N× — lower the speed" shows only while
  *playing* (paused, the wall clock runs on and the figure would blame the speed for the pause).
- A bus chip, a Bus pill, a REC chip disappear the moment they stop being true.
- **Clearing clears the server too.** TX replay's Source → *Clear* and Playlist → *Clear* call
  `/api/replay/unload` (`TxEngine.unload()`): clearing only the page left the plan loaded and
  *Play* transmitted a log the screen no longer showed.
- **Text on screen can be copied** (the user, 24-11-2026: "I can select and copy the text from
  screen"): a toast takes the pointer while shown and **hovering holds it** (a saved path is worth
  copying — it used to vanish after 4.5 s, unclickable); a TX step's summary is `user-select: text`
  and the header ignores a click that ends a selection inside it. Never `user-select: none` on text
  a person might want — only on drag handles and while resizing.

## 9. Traps already paid for — don't re-introduce

- **`[hidden]` loses to any author `display` rule** — `style.css` restores it with `!important`.
- **The old `--line/--green/--red` aliases are gone**; reading one gives no colour at all.
- **`.panel + .panel` margin applied inside a grid** pushed the Logger's second card down — the
  spacing rule is `.view > .panel + .panel`.
- **A field's focus is grey, not green** (Supabase); don't add `border-color: var(--accent)` on focus.
- **Font metrics:** measure label fits only after `document.fonts` has loaded Inter — the
  fallback is narrower and hides a cut-off.
- **Bare `<input>` has no `type`** — the field selector list covers `input:not([type])`.
- **Form controls don't inherit the font** — the global `button, input, select, textarea
  { font-family: inherit }` fixes it; `select option` has solid theme colours (an option list is
  drawn in its own window).
- Honour `prefers-reduced-motion` (the global rule already stills animations).
- **A `let` read by `openView()` must be declared above it** — `openView` can run during the
  script's first pass, and a `let` below it is in its temporal dead zone (`usage` lives at the top).
- **A summary must not outlive its state**: after Clear the plan is `empty`, and a Send header
  still saying "Ready" promised a Play that would send nothing.
- **Testing dialogs:** drive them with real pointer clicks (`tools/shoot.py` `click`). A
  synthetic `.click()` has no user activation, so Chrome groups the dialogs it opens and one Esc
  closes them all — a test artefact that looks like a bug. And Chrome lets a *second* Esc through
  a prevented `cancel`: a dialog that must not be dismissed reopens itself on `close`.

## 10. Usage reporting (user skill `app-control`) — what the page owns

- **First start:** `#welcomeDlg` with the skill's exact words ("Hi! May I have your name,
  please?" / "We'll use it to greet you and to make uCANdo better for you. Settings → Usage
  reporting shows what is shared."). Name only; *Continue* disabled until typed; not
  dismissible. **Never** a notice of what is reported — `test_ui` fails on the notice phrases.
- **Greeting:** "Hello, Name" in the banner (`#bannerHello`), only when reporting is on and a
  name exists — never a line on the Dashboard.
- **Settings → Usage reporting:** Name, Install ID, Reporting to, Last sent, Waiting; *Edit name*
  reopens the welcome as "Your name" with Cancel/Save; *Send now*. A failed send is an amber
  "Not sent: …" (kept and retried — not a fault). Switched off, the card is the reason alone.
- **Views are counted** by `countView()` in `openView` → `/api/usage/view`; the server counts
  only ids in `usage.VIEWS`, which a test holds equal to the `NAV` ids.
- Only the packaged exe reports. To see it from source without reaching the server:
  `UCANDO_USAGE=on` + `UCANDO_USAGE_URL=http://127.0.0.1:9/x`.

## 11. The window, the port, the build

- `python main.py` opens uCANdo **in its own window** — Edge app mode in its own profile
  (`data/uCANdoWindow`, `data/uCANdoDevWin` from source), dark when the saved theme is dark
  (`ucando/desktop.py`); `--tab` for a browser tab. **The profile's folder name is the window's
  taskbar identity** (Edge builds the AppUserModelID from it): with `data/window` uCANdo and Runway
  were one app to Windows — one button, one icon. `WindowBrand` gives each window the relaunch
  details, so a pinned button starts uCANdo with `packaging/ucando.ico`, not Edge.
- The release (`uCANdo.exe`, port **8765**) and a source run (port **8865**) run side by side
  (`ucando/channel.py`); the source copy shows **Dev** in the banner and "Dev ·" in the tab title.
  A second start of the same one opens a window on the running copy.
- `index.html` loads `shell.js`, `app.js`, `style.css` with `?v=__VER__`; the token covers every
  file in `server._ASSETS` — add a new web asset there.

## 12. Before you call it done

- [ ] Tokens only — no hex in CSS rules, inline styles or JS (read `tok()` / `SERIES`)
- [ ] Sentence case; no `uppercase`; no help text on the page — tips in `data-tip`
- [ ] Icons from the one map; no `<svg>` in markup; no glyphs; every action has a word
- [ ] No `window.confirm/prompt/alert`; destructive = red + `UI.confirm`
- [ ] New view: `NAV` + section + `VIEW_READY` if needed + `startPolling` if needed + `usage.VIEWS`
- [ ] `VIEW_READY` honest; dashboard and `goView` targets never `soon`
- [ ] `contracts.py` and `app.js` changed together, if either changed
- [ ] Empty / stale / error states say *why*, in one line
- [ ] `python -m pytest -q tests/test_ui.py` green — it holds most of the boxes above
- [ ] **Looked at it, driven**: `tools/ui_smoke.py --views all` clean (every view, dark and
      light, rail expanded / collapsed / hover, 900 px wide — zero page JS errors), plus the
      changed flow driven through its own buttons with `tools/shoot.py`, connected and
      disconnected — then **read the screenshots**
- [ ] Left uncommitted until the user says commit
