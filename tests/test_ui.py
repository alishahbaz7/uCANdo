"""The house look and the nav contract, held over time — static checks a screenshot cannot keep true.

uCANdo's UI is one page (web/index.html + shell.js + app.js + style.css) on the house standard
(user skill ``utility-ui``; repo skill ``ui-hygiene``). Ported from Runway's tests/test_ui.py, plus
the uCANdo-specific contract: one ``NAV`` definition, the ``VIEW_READY`` readiness kinds, and the
usage-reporting pieces (user skill ``app-control``).

* One icon map (shell.js): every icon the page names exists in it — a missing one renders as an
  empty button with no error anywhere — and no other script draws its own icon SVG.
* Sentence case: nothing forces text to capitals; the rail's labels read as sentences.
* No glyphs standing in for icons, no browser dialogs, no rule on a bare structural element,
  no colour outside the tokens, no inline style in the page.
* NAV ↔ sections ↔ VIEW_READY agree, and nothing that must open can be held back.
* The font ships with the app and is served as a font; every asset is cache-busted.
* The first start is a welcome, not a notice; the banner names the app, the person and the page.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
SHELL = (WEB / "shell.js").read_text(encoding="utf-8")
APP = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "style.css").read_text(encoding="utf-8")
SCRIPTS = {"shell.js": SHELL, "app.js": APP}

# Glyphs that once stood in for icons on buttons and labels.
GLYPHS = "▲▼▸▾⤓⤒✕●■▶↻⟳⇄⇪▤◉↗🔁ⓘ✈⟲✓✗⚠🗑⚙🔍✎◀"


def _code(js: str) -> str:
    """The script without its comments (a comment may name a glyph or a browser dialog)."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?<![:\"'\\])//[^\n]*", "", js)


def _css_code(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _html_code(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def _icon_map() -> set[str]:
    start = SHELL.index("const B = {")
    block = SHELL[start:SHELL.index("\n  };", start)]
    return set(re.findall(r'^\s*"([a-z-]+)":\s*\'', block, re.M))


def _nav() -> list[dict]:
    block = APP[APP.index("const NAV = ["):APP.index("const NAV_ITEMS")]
    groups = []
    for g in re.finditer(r'\{ group: "([^"]+)", items: \[(.*?)\] \}', block, re.S):
        items = [dict(id=m[0], label=m[1], icon=m[2], desc=m[3]) for m in
                 re.findall(r'\{ id: "([a-z]+)", label: "([^"]+)", icon: "([a-z-]+)",\s*desc: "([^"]+)" \}', g[2])]
        groups.append({"group": g[1], "items": items})
    return groups


def _view_ready() -> dict[str, dict]:
    block = APP[APP.index("const VIEW_READY = {"):]
    block = block[:block.index("\n};")]
    out = {}
    for m in re.finditer(r'^\s*(\w+): \{ kind: "(\w+)"(?:, pill: "(\w+)")?, why: "([^"]*)" \}', block, re.M):
        out[m[1]] = {"kind": m[2], "pill": m[3], "why": m[4]}
    return out


NAV = _nav()
NAV_IDS = [it["id"] for g in NAV for it in g["items"]]
READY = _view_ready()


# ---- icons ---------------------------------------------------------------------------------------
def test_the_icon_map_is_found():
    assert len(_icon_map()) > 50


def test_every_icon_used_exists():
    icons = _icon_map()
    used: set[str] = set(re.findall(r'data-icon="([a-z-]+)"', HTML))
    for js in SCRIPTS.values():
        js = _code(js)
        used |= set(re.findall(r'\bUI\.(?:ico|icon)\("([a-z-]+)"', js))
        used |= set(re.findall(r'\bUI\.setLabel\([^,()]*(?:\([^()]*\))?,\s*"([a-z-]+)"', js))
        used |= set(re.findall(r'\bsetLabel\([^,()]*(?:\([^()]*\))?,\s*"([a-z-]+)"', js))
    used |= {it["icon"] for g in NAV for it in g["items"]}
    missing = sorted(used - icons)
    assert not missing, f"icons used but not in shell.js: {missing}"


def test_the_local_icon_names_resolve():
    """app.js keeps camelCase names over UI.ico(...); every ICONS.x it reads must be one of them."""
    block = APP[APP.index("const ICONS = {"):APP.index("};", APP.index("const ICONS = {"))]
    local = set(re.findall(r"\b([a-zA-Z]+): UI\.ico\(", block))
    read = set(re.findall(r"\bICONS\.([a-zA-Z]+)\b", _code(APP)))
    assert not sorted(read - local), f"ICONS.x read but not defined: {sorted(read - local)}"


def test_no_script_draws_its_own_icons():
    """Icons are 24×24 line SVGs from shell.js only. (The dashboard's animated bus is an
    illustration, not an icon, and stays in app.js.)"""
    assert 'viewBox="0 0 24 24"' not in _code(APP)
    assert "<svg" not in _html_code(HTML), "index.html: an inline <svg> — use data-icon"


# ---- type and copy ---------------------------------------------------------------------------------
def test_sentence_case_nothing_forced_to_capitals():
    for name, text in (("style.css", CSS), ("index.html", HTML), ("app.js", APP), ("shell.js", SHELL)):
        assert "uppercase" not in text, f"{name}: text forced to capitals"


def test_rail_labels_read_as_sentences():
    labels = [g["group"] for g in NAV] + [it["label"] for g in NAV for it in g["items"]]
    assert len(labels) > 15
    for label in labels:
        for word in re.split(r"[\s-]+", label)[1:]:
            assert word.islower() or word.isupper(), f"rail label not in sentence case: {label!r}"


def test_no_glyphs_standing_in_for_icons():
    found = sorted({g for g in GLYPHS if g in _html_code(HTML)})
    assert not found, f"index.html: {found} — use an icon from shell.js"
    for name, js in SCRIPTS.items():
        found = sorted({g for g in GLYPHS if g in _code(js)})
        assert not found, f"{name}: {found} — use an icon from shell.js"


def test_no_browser_dialogs():
    for name, js in SCRIPTS.items():
        hits = re.findall(r"(?<![\w.$])(?:window\.)?(?:confirm|prompt|alert)\(", _code(js))
        assert not hits, f"{name}: {hits} — use UI.confirm / UI.prompt / UI.notice"


# ---- styles ----------------------------------------------------------------------------------------
def test_stylesheet_braces_balance():
    css = _css_code(CSS)
    assert css.count("{") == css.count("}")


def test_no_rule_on_a_bare_structural_element():
    css = _css_code(CSS)
    for selectors in re.findall(r"(?:^|[{}])\s*([^{}@;]+?)\s*{", css):
        for sel in selectors.split(","):
            sel = sel.strip()
            assert not re.match(r"(main|aside|section|header|nav)(?=$|[\s>+~:])", sel), \
                f"style.css: a rule on bare {sel!r} — style it by its class or id"


def _rules(css: str):
    """(selector, body) for every innermost block, @media wrappers unwrapped."""
    css = _css_code(css)
    out, stack, start = [], [], 0
    for i, ch in enumerate(css):
        if ch == "{":
            stack.append((css[start:i].strip(), i + 1))
            start = i + 1
        elif ch == "}":
            sel, body_at = stack.pop()
            if "{" not in css[body_at:i]:
                out.append((sel.split(";")[-1].strip(), css[body_at:i]))
            start = i + 1
    return out


def test_colours_come_from_the_tokens():
    """Every colour is a token on :root (dark, light, auto). The bit grid's MSB amber and the ink
    on bright fills are documented fixed swatches — and they are tokens too."""
    hexes = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    for sel, body in _rules(CSS):
        if sel.startswith(":root") or sel.startswith("@font-face"):
            continue
        bad = hexes.findall(body)
        assert not bad, f"style.css {sel!r}: {bad} — use a token"


#: The only colours a script may name: the favicon is a data-URI SVG, which cannot read CSS
#: variables, and a tab icon does not follow the theme anyway.
FIXED_SWATCHES = {"#4ea1ff": "favicon tile (the brand blue)", "#04121d": "favicon mark ink"}


def test_scripts_take_colours_from_the_tokens():
    for name, js in SCRIPTS.items():
        found = re.findall(r"""["'\s(:](#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))(?=["'\s;,)])""", _code(js))
        bad = [h for h in found if h.lower() not in FIXED_SWATCHES]
        assert not bad, f"{name}: hard-coded colours {bad} — read a CSS variable"


def test_the_page_has_no_inline_styles():
    assert not re.search(r"\sstyle=\"", _html_code(HTML)), "index.html: inline style= — use a class"


# ---- the frame and the nav contract -------------------------------------------------------------
def test_nav_is_one_definition_and_every_view_has_its_section():
    assert NAV_IDS and len(NAV_IDS) == len(set(NAV_IDS))
    for g in NAV:
        for it in g["items"]:
            assert f'id="view-{it["id"]}"' in HTML, f"NAV {it['id']}: no section view-{it['id']}"
            assert it["desc"].strip(), f"NAV {it['id']}: no description (the page name's hold-tip)"
    sections = set(re.findall(r'<section[^>]*id="view-([a-z]+)"', HTML))
    assert sections == set(NAV_IDS), f"sections without a NAV item: {sorted(sections - set(NAV_IDS))}"


def test_view_ready_is_honest():
    assert READY, "VIEW_READY not found"
    for vid, r in READY.items():
        assert vid in NAV_IDS, f"VIEW_READY {vid}: not a NAV view"
        assert r["kind"] in ("soon", "bus", "input"), f"VIEW_READY {vid}: kind {r['kind']!r}"
        assert r["why"].strip(), f"VIEW_READY {vid}: says nothing (its why is the pill's hold-tip)"
        if r["kind"] == "input":
            assert r["pill"], f"VIEW_READY {vid}: an input view names what to feed it"


def test_nothing_that_must_open_is_held_back():
    """The startup view and every goView() target would dead-end if held back."""
    soon = {v for v, r in READY.items() if r["kind"] == "soon"}
    assert "dashboard" not in soon
    targets = set(re.findall(r"""goView\(\\?['"]([a-z]+)\\?['"]\)""", APP))
    assert targets, "no goView targets found"
    assert not (targets & soon), f"goView targets held back: {sorted(targets & soon)}"


def test_every_pill_explains_itself():
    block = APP[APP.index("const PILL_TIPS = {"):APP.index("};", APP.index("const PILL_TIPS = {"))]
    tips = dict(re.findall(r'(\w+): "([^"]+)"', block))
    assert {"Preview", "Bus"} <= set(tips)
    assert all(t.strip() for t in tips.values())
    assert "nav-legend" not in HTML, "a legend is back — pills explain themselves"


def test_the_banner_names_the_app_the_person_and_the_page():
    """The user, 13-11-2026 (Runway): a fixed banner with the application name, the greeting and
    the page name — on every view, so the greeting lives there, not on the Dashboard."""
    for part in ('id="banner"', "u<b>CAN</b>do", 'id="bannerHello"', 'id="bannerPage"', 'id="viewTitle"'):
        assert part in HTML, part
    code = _code(APP)
    assert '$("bannerHelloT").textContent = name ? "Hello, " + name' in code


# ---- usage reporting (app-control) ----------------------------------------------------------------
def test_the_first_start_is_a_welcome_not_a_notice():
    """The user, 12-11-2026, on "Who is using Runway? Runway reports your name, this computer…":
    "Not acceptable at all" — it read as being watched. Every app greets with the same words."""
    page = _html_code(HTML) + _code(APP)
    assert "Hi! May I have your name, please?" in page
    assert "We'll use it to greet you and to make uCANdo better for you. " \
           "Settings → Usage reporting shows what is shared." in page
    for notice in ("Who is using", "reports your name", "this computer, the app version"):
        assert notice not in page, f"{notice!r} — the first start welcomes, it does not warn"


def test_the_first_start_cannot_be_dismissed():
    code = _code(APP)
    assert 'if (nameDlg && !nameDlg.edit) e.preventDefault()' in code          # Esc refused
    assert "if (d && !d.edit && !d.saved) { $(\"welcomeDlg\").showModal()" in code   # and reopened


def test_the_usage_card_shows_the_facts_and_the_actions():
    sec = HTML[HTML.index('id="setUsage"'):HTML.index('id="setAbout"')]
    for fact in ("Name", "Install ID", "Reporting to", "Last sent", "Waiting"):
        assert f"<dt>{fact}</dt>" in sec, fact
    assert 'id="btnUsageName"' in sec and 'id="btnUsageSend"' in sec
    assert "Never reported" in sec, "the card's hold-tip says what is never sent"


def test_only_nav_views_are_counted():
    from ucando import usage

    assert set(NAV_IDS) == set(usage.VIEWS), "ucando/usage.py VIEWS must be exactly the NAV ids"


# ---- the font and the assets ---------------------------------------------------------------------
def test_the_font_ships_with_the_app():
    """Inter is bundled, never fetched: uCANdo runs offline. Its licence goes with it."""
    urls = re.findall(r'@font-face\s*{[^}]*url\("([^"]+)"\)', CSS)
    assert urls, "no @font-face"
    for u in urls:
        assert not u.startswith(("http:", "https:", "//")), f"{u}: a font from the network"
        assert (WEB / u).is_file(), f"{u}: missing"
    assert (WEB / "fonts" / "Inter-LICENSE.txt").is_file()


def test_the_font_is_served_as_a_font():
    """Windows' MIME table often has no .woff2; the server must not send the font as text/plain."""
    from fastapi.testclient import TestClient

    from ucando import server

    r = TestClient(server.app).get("/fonts/InterVariable.woff2")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/woff2"


def test_every_script_and_stylesheet_is_cache_busted():
    from ucando import server

    on_disk = {p.name for p in WEB.glob("*.js")} | {p.name for p in WEB.glob("*.css")}
    assert on_disk == set(server._ASSETS), f"_ASSETS misses {sorted(on_disk - set(server._ASSETS))}"
    for name in on_disk:
        assert f"/{name}?v=__VER__" in HTML, f"index.html loads {name} without the version token"
