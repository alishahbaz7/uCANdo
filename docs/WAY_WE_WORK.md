# Way We Work — session starter for uCANdo

Paste this at the top of a new session (or hand it to a teammate's assistant) to pick up
the working style, expectations, and conventions we follow on uCANdo. Complements
`CLAUDE.md` (which covers the codebase itself).

---

## The project
uCANdo — an India-first, fleet/telematics **CAN bus workbench**. Stack: FastAPI +
WebSocket backend, **plain-JS single-page UI (no build step)**, cantools, on Windows
(Python 3.12 in `.venv` — it's the only interpreter with the hardware lib `python-ics`).
Architecture invariant: everything talks to the HAL (`hal.py`), never to `python-can`
directly. The capture → decode → RE → transmit loop is the spine. Read `CLAUDE.md` first.

## Who I am / how I talk
- I'm an automotive/CAN engineer. My messages are short and sometimes have typos —
  infer intent and act; don't make me over-specify.
- I think in hex, real vehicles, and ground-truth values (dash readings, OBD, DBCs).
- When I say "go-ahead" / "sure" / "build it", proceed fully. When I give feedback like
  "this looks good but…", iterate in place.

## How we build (the loop)
1. **Understand-first for anything non-trivial.** Before coding a new format/feature,
   write a short *implementation/analysis doc* under `docs/`, show me the findings, and
   **wait for my go-ahead**. (We did this for the JSON decoder, the Converter, CanPlus.)
2. Then implement in **small, verifiable steps**. I'll check it in the UI and steer.
3. **Put it in the UI.** A feature isn't done until it's usable in the app, not just the
   backend. Wire new source formats into the Converter / Frame Decoder, add endpoints.
4. **Bump `ucando.__version__` on every change** (single source of version; it drives
   cache-busting). Restart + hard-reload to see UI changes.

## Testing & dev conventions
- Run `python -m pytest -q` via `.venv`; keep it **100% green**. Add tests for every new
  parser/contract (byte-exact assertions against known values, plus an endpoint test).
- `python -m compileall -q ucando main.py` after edits.
- Prefer the in-process virtual bus for tests — no hardware needed.

## Git rules (strict — I care about this)
- **NEVER merge, tag, or force-push without my explicit confirmation.** Commit/push only
  when I ask.
- **Branch per feature/release** (`v0.4`, `feature-…`, `v1.0.0`). Validate (tests green)
  before committing.
- Commit messages: a one-line summary + bulleted **major one-liner changes**, ending with
  the `Co-Authored-By:` trailer.

## UI/UX bar
- **No emoji** in the UI — use the consistent inline-SVG icon set.
- Terminology: **Upload / Download** (never Import/Export). Each view gets a short fixed
  **title + one-line description** header.
- "Beauty *and* brain": polished, engaging (tasteful animation is welcome), but every
  flourish should also be useful. Honor `prefers-reduced-motion`; keep it offline/self-contained.

## Reverse-engineering method I expect
- **Decode by finding the pattern, then prove it byte-exact against ground truth**
  (e.g. multiplier/divider from a binary record must match the XML; a bit layout must
  reproduce a validated dash value).
- **Stay general — never hardcode logic to a sample file.** Sample files are for
  learning/validation only.
- **Cross-validate across multiple samples/vehicles** before claiming a rule.
- **Be honest about limits.** If something is encrypted/obfuscated or unverifiable, say so
  plainly and propose the bridge (e.g. correlate against a capture / OEM DBC) — do **not**
  fabricate CAN IDs or bit positions.

## How I want you to communicate
- **Lead with the result/answer**, then the detail. Use tables and short headers.
- Give a recommendation, not an exhaustive menu; then offer the next-step choices.
- **Confirm before irreversible or outward-facing actions** (folder renames, pushes,
  merges, tags, anything hitting GitHub).
- State outcomes faithfully — if a test failed or a step is a placeholder, say so.
