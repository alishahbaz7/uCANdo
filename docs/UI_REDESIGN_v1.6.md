# uCANdo v1.6.0: Runway's house design, plus usage monitoring

## Status (25-11-2026): all stages done, uncommitted

| Stage | Result |
|---|---|
| 0 Housekeeping | v1.5.2 committed (d4a3fbd, 106d151); branch `v1.6.0`, `__version__ = "1.6.0"` |
| 1 Tokens, font, kit | Supabase tokens dark/light/auto, bundled Inter, global kit; contrast ≥ 4.5:1 |
| 2 Shell | fixed banner, rail + Sidebar control, `window.UI` (`web/shell.js`), house dialogs, toasts |
| 3 Every view | 14 views in the house style; tokens only; sentence case; no help text on screen |
| 4 Usage (`app-control`) | `ucando/usage.py`, first-start welcome, "Hello, Name", Settings → Usage reporting, view counts; release builds only; `check_server.py` READY + PRIVATE; release docs rewritten |
| 5 Guard rails, docs | `tests/test_ui.py` (25 checks, each proven to bite); `tools/shoot.py` + `tools/ui_smoke.py`; CLAUDE.md, WAY_WE_WORK, `ui-hygiene`, `utility-ui` |

Added along the way at the user's request: release (8765) and dev (8865) side by side
(`ucando/channel.py`), the own app window (`ucando/desktop.py`), Settings → Views (hide or show
any view), copyable text, TX replay multi-file upload, Remove / Show all (hide, never delete),
Clear that also clears the server, "Now sending ‹file›", the stale-code chip on a dev copy, and
TX replay → Transmit signal **Tiles / Bytes** (every transmitted signal as a tile, pins, change
flash, stale and forced states; All / In DBC filter and changed-byte highlight in Bytes), its own
taskbar button and logo per app (window profiles `uCANdoWindow` / `uCANdoDevWin`), and **TX
riding out a lost bus**: PCAN bus-off recovery with state `recovering`, adapter reset and reopen,
and the PCAN error state on the bus chip. Bench test still due: play, unplug the TCU for about
10 s, plug it back, and playback must resume by itself.

Left for later versions: self-update (`app-updates`); multi-channel TX (v1.7.0); a size cap on TX
recording (it keeps every frame in memory).

## Context

You asked to bring Runway's design to uCANdo and make it the best utility you ship, using every skill that applies.

The house standard is the user-level `utility-ui` skill. Its look comes from Supabase Studio: a near-black canvas, hairline borders, the Inter font and one green brand colour. Runway is the web reference for it (`D:\shahbaz\Miscellenious\Code\Runway\runway\web\style.css` and `shell.js`). Today uCANdo is on the older version of that standard:
- blue accent, Segoe font, dark theme only
- a top bar inside the main column, not a full-width banner
- UPPERCASE group labels and a legend block at the foot of the rail
- about 19 explanatory sentences and 15 instructional placeholders on screen
- 45 hard-coded colours, 5 `window.confirm`/`prompt` calls, glyphs used as icons (⚠ ▾ ⟳ ◀ ▶ ✕)
- four separate icon maps
- no welcome dialog, greeting or usage reporting

The skill lists uCANdo as "change them when next touched". This version is that change.

**Your decisions:**
- Scope is the UI plus usage monitoring (`app-control`). Self-update (`app-updates`) comes later as its own version.
- Commit the open v1.5.2 work first, then open branch **v1.6.0**.
- Only release builds report usage.
- I send screenshots after each stage and wait for your OK before the next.

**Fixed for the whole job:**
- No build step, framework or CDN.
- The single-page view model stays: nav `<button>`s, `VIEW_READY`, and one `pollTimer` with the WebSocket.
- The HAL invariant and `contracts.py` are untouched.
- Nothing of the redesign is committed or pushed until you ask. The only commit you approved is the v1.5.2 one in stage 0.

## Stage 0: Housekeeping (no UI change)
1. On `v1.5.2`, commit the PCAN `.trc` work: `pcantrc.py`, its tests, and the logstore/replay/server/txproject/app.js/index.html edits. Commit `.vscode/launch.json` separately. Set the branch description's "Next" line to v1.6.0.
2. Create `v1.6.0` from it and set `ucando/__init__.py` to `__version__ = "1.6.0"`.
3. Set the v1.6.0 description to "House design + usage monitoring", with "Next: v1.7.0 – multi-channel TX".
4. Add a v1.6.0 row to the CLAUDE.md roadmap table.
5. Save this plan as `docs/UI_REDESIGN_v1.6.md`. `WAY_WE_WORK` asks for an analysis document before non-trivial work.

## Stage 1: Tokens, font, global kit → screenshot gate
- **Font:** copy `Runway\runway\web\fonts\InterVariable.woff2` and `Inter-LICENSE.txt` into `web/fonts/`, with an `@font-face` rule. In `ucando/server.py`, add `mimetypes.add_type("font/woff2", ".woff2")` and extend `_ASSETS` (currently `app.js`, `style.css`, around L1942) so new files bust the cache.
- **Tokens** (`web/style.css` `:root`): take Runway's token block for dark and light (bg, panel, panel-2, hover, border/-subtle/-strong, text, dim, muted, accent green, primary-bg/-border/-text, btn-bg, raised, info, ok/warn/danger and their -ink forms, tint, radius scale, shadows).
  - Add **Auto/Light/Dark** as `utility-ui` §5 asks: `@media (prefers-color-scheme: light)` under `:root:not([data-theme="dark"])`, then each explicit choice. Runway itself only has dark and light. Dark is the default.
  - Old names (`--line`, `--green`, `--red`, `--accent-soft`) become aliases, so nothing breaks during the move. They are removed at the end of stage 3.
  - Keep uCANdo's own blue as **`--brand`** for the logo only. The accent becomes green, the logo stays blue.
  - The bit-grid MSB amber stays a documented fixed swatch.
- **Global kit:**
  - `color-scheme` set in every theme state
  - thin themed scrollbars (`scrollbar-color` plus WebKit)
  - solid `select option` colours
  - focus ring
  - `prefers-reduced-motion` handling
  - `[hidden]{display:none!important}`
  - form controls inherit the font, including `textarea`
- **Contrast:** a short script computes every grey against bg, panel and panel-2 in both themes. All must reach at least 4.5:1.

## Stage 2: Shell (banner, rail, dialogs) → screenshot gate
- **New `web/shell.js`:** uCANdo's version of Runway's shell kit, loaded before `app.js` with `?v=__VER__`. It holds:
  - one `ICONS` map, merging `ICONS`, `NAV_ICONS`, `BTN_ICONS`, `CV_ICON` and `_SWAP_ICON` from app.js
  - `icon()` and `paint()`
  - hold-tips (`data-tip`, shown after 5 s)
  - `resizable()`
  - `menu()`
  - `confirm`/`notice`/`prompt` built on `<dialog class="ui-dlg">`
  - `toast()`

  It is exposed as `window.UI`. Runway's version assumes one HTML file per page and rebuilds the banner from each page's header, so I port its parts rather than copy the file.
- **One nav definition:** a `NAV` array in app.js (group, id, label, icon, description, readiness) replaces the separate nav buttons in index.html, `VIEW_META` and `NAV_ICONS`. It builds the rail, the page name in the banner and its hold-tip, and the tests read it. `VIEW_READY` keeps its meaning and invariants.
- **Fixed banner, 48 px:**
  - On the left: logo tile, "u**CAN**do" with "Version 1.6.0" nested under it in small dim text, then "Hello, Name" (once usage is in), then the page name with its icon. The view description becomes the page name's hold-tip.
  - On the right: a bus chip ("Live · neoVI 1 · 500 k" / "Idle"; a click opens Connect or Disconnect, so the chip is the way in and no second button), a REC chip while recording, the Record button, and the theme button cycling Auto/Light/Dark.
  - The footer status bar goes: `setStatus()` becomes a toast with the same name, so its 77 calls stay as they are, and the recording details move into the REC chip.
- **Rail:**
  - Active item: a quiet raised fill with no coloured bar.
  - Group labels in sentence case, 12 px.
  - Readiness pills (Bus/Log/DBC/File/Soon) each explain themselves in a hold-tip, so `.nav-legend` and the "Unified CAN Workbench" subtitle are removed.
  - The rail is resizable from 180 to 380 px, double-click resets it, and the width is remembered.
  - A **Sidebar control** menu at the foot: Expanded / Collapsed / Expand on hover.
  - The hardware chip moves from the rail into the banner bus chip.
  - A **Settings** rail item opens the Settings dialog, which gets its Usage card in stage 4.
- **Inline `<head>` boot script:** applies the theme and rail mode before the first paint, so the page never opens wide and snaps shut. All `localStorage` access is in try/catch under the prefix `ucando.`. The old `ucando_nav_mode` key is migrated.
- **Browser dialogs replaced:** the 5 `window.confirm`/`prompt` calls (app.js L587, 607, 1145, 2129, 3141) move to house dialogs. The ECU DTC clear (Mode 04) is red and confirmed.

## Stage 3: Every view in the house style (two batches, a gate after each)
Batch 3a: Dashboard, CAN logger, TX replay (with TX monitor), TX scheduler, Automation, DTC codes.
Batch 3b: Frame decoder, Converter, OEM database, Signal viewer, plus the four views held back as Soon (RE, Auto-RE, DBC builder, Protocol decoder), so they are ready when they ship.

In each view:
- **Components:** cards (panel head with title and count, actions on the right), buttons (one green primary per area, the rest quiet, destructive red and confirmed), pills, fields (34 px, labels above), segmented controls, notices (ok/warn/bad with an icon), and tiles (outlined over a soft gradient of their colour).
- **Tables:** one `.data-grid` class with a header band, hairline rows, no zebra stripes, a faint hover, monospace IDs, right-aligned tabular numbers, and draggable column widths that are remembered. The existing lazy row building, staleness rule, time and zoom model, and canvas charts keep their logic and change only their look.
- **Sentence case:** "CAN logger", "TX replay", "Reverse engineering", "DTC codes", "Protocol decoder". `uppercase` is removed everywhere, including app.js L1779/1782. "Export CSV/Excel" becomes "Download CSV/Excel", per `WAY_WE_WORK`.
- **Help text:** the static explanatory sentences (index.html L90, 201, 227, 310, 330, 357, 392, 479, 528, 754 and similar) become hold-tips, empty states with an action button, or are dropped. Instructional placeholders become a format or nothing (`sig('BATT.V')`). The three empty "heroes" stay as a heading and one line plus their action cards.
- **Icons:** glyph icons become SVG from the one icon map, always with a word beside them.
- **Colours:**
  - Hard-coded colours in JS read CSS variables: `KIND_COLOR`, the bit-grid palette, multiplexor chips, alarm chips, the chart playhead `#4ea1ff`, and `cvWarnBox`.
  - The canvases re-read the tokens when the theme changes, through a `MutationObserver` on `data-theme`.
  - The `--ok`/`--bad` references at app.js L1863 point at tokens that don't exist; they get real tokens.
  - The malformed inline style at index.html L85 is fixed.
  - Inline styles in the parts I touch move into classes.
- **Old token aliases** are removed at the end of 3b.

## Stage 4: Usage monitoring (`app-control`) → gate
- Copy `C:\Users\GT2575\.claude\skills\app-control\assets\python\usage_client.py` to `ucando/usage_client.py`, and its 17 tests to `tests/test_usage_client.py`. Runway's `runway/usage.py` is the model.
- **New `ucando/usage.py`:** one `UsageReporter(app="uCANdo", version, data_dir=DATA_DIR, enabled=CHANNEL=="release", build=CHANNEL)`.
  - `CHANNEL` is `"release"` when the app runs as the packaged exe (`sys.frozen`), otherwise `"dev"`.
  - `UCANDO_USAGE=off` switches it off, and `tests/conftest.py` sets that.
  - Metrics are counts only, never CAN data: connects by adapter type, recordings, replays started, logs analysed, profiles identified, views opened.
- **`ucando/server.py`:**
  - Add a FastAPI lifespan that runs `usage.start()` and `usage.stop()` (there is no lifespan today).
  - Call `usage.record_error()` in the unhandled-exception handler (around L93).
  - Add routes `GET /api/usage`, `POST /api/usage/name`, `POST /api/usage/send`, and `POST /api/usage/view`. The last one is needed because a single-page app's view switches never reach the server.
- **Page side:**
  - The first-start welcome uses the skill's exact wording: "Hi! May I have your name, please?" / "We'll use it to greet you and to make uCANdo better for you…". It cannot be dismissed and is never a notice of what is reported.
  - "Hello, Name" appears in the banner.
  - Settings gets a **Usage reporting** card: Name, Install ID, Reporting to, Last sent, Waiting, with *Edit name* and *Send now*. What is shared goes in the card's hold-tip.
- **Docs:** `docs/RELEASE_PACKAGING.md` (L37–40) and the README written by `packaging/build.ps1` promise the app "does not call home". Both are rewritten to say exactly what a release build sends.

## Stage 5: Guard rails and docs
- **New `tests/test_ui.py`**, ported from Runway's `tests/test_ui.py`. It checks:
  - no `uppercase` anywhere
  - stylesheet braces balance
  - every icon name used exists in `ICONS`
  - no `confirm(`/`prompt(`/`alert(` calls
  - no glyphs standing in for icons
  - no CSS rule on a bare `main`/`aside`/`section`/`header`/`nav`
  - the font ships and is served as `font/woff2`
  - every `NAV` item has a section, a description and a valid readiness
  - every readiness pill has its tip
  - the dashboard and `goView` targets are never Soon
  - `_ASSETS` covers every `web/*.js|css` file
  - no hex colour outside the tokens, except the documented swatch
  - the first start is a welcome, not a notice
  - the banner names the app, the person and the page
- **Docs and skills updated:**
  - Rewrite the repo skill `.claude/skills/ui-hygiene/SKILL.md`: tokens, theme, frame, readiness pills without a legend, hold-tips in place of hint lines, `window.UI`, `NAV`.
  - In the user-level skill `utility-ui`, update the uCANdo row and drop "still have the subtitle, chip and legend".
  - Update the UI sections of CLAUDE.md.
  - Update the UI bar in `docs/WAY_WE_WORK.md`.
  - Update memory.

## Files

| Change | Files |
|---|---|
| Main | `web/index.html`, `web/style.css`, `web/app.js`, new `web/shell.js`, new `web/fonts/*`, `ucando/server.py`, `ucando/__init__.py` |
| New | `ucando/usage.py`, `ucando/usage_client.py`, `tests/test_ui.py`, `tests/test_usage_client.py`, `tests/test_usage_api.py` |
| Touched | `tests/conftest.py`, `tests/test_server.py` (the asset-token test grows with `_ASSETS`), `docs/*`, `packaging/build.ps1`, the skills, CLAUDE.md |

## Verification (every stage)
1. **Static checks:** `.\.venv\Scripts\python.exe -m pytest -q` passes; `python -m compileall -q ucando main.py` passes.
2. **Run a private copy** on a spare port with `UCANDO_HOME` pointing at a scratchpad copy of `data/`, connected to the **virtual bus with the simulator on**, so the tables, charts and dashboard show real traffic. Load data into the views:
   - a real Dzire `.trc` in TX replay
   - a pack DBC in Signal viewer and Frame decoder
   - an OEM identify
3. **Drive it in headless Edge over the DevTools protocol** (`utility-ui` §13; Runway's `scratchpad/shoot.py` is the model):
   - click each nav item
   - open every dialog
   - fold and unfold the rail in all three modes
   - switch Light, Dark and Auto
   - narrow the window to 900 px
   - fail on any page JavaScript error
   - screenshot each state, read the screenshots myself, then send them to you
4. **Stage 4 only:** the welcome dialog and greeting are shown with reporting forced on, with `HTTPS_PROXY=http://127.0.0.1:9` so nothing actually leaves the machine. `python -I scripts/check_server.py` from the skill reports READY and PRIVATE. A real release run that reaches Supabase happens only with your OK.
5. **Finish:** a report listing what changed and what stays open. The redesign is left uncommitted until you ask.
