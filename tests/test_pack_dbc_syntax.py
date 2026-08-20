"""Every shipped ``oem_packs/`` DBC must parse in a *strict* DBC tool.

``cantools`` is lenient: it accepted a pack file whose ``VAL_`` block sat before
its ``BA_DEF_`` block, and Vector/PCAN-class tools rejected the same file with
"line 141: syntax error". A pack is handed to colleagues who open it in those
tools, so loading in cantools is necessary but not sufficient — these tests
assert the structure the strict parsers actually enforce.
"""

import re

import cantools
import pytest

from ucando.server import OEM_PACKS_DIR

#: Canonical DBC section order. A keyword may repeat, but its first appearance
#: must not precede a keyword that outranks it.
SECTION_ORDER = [
    "VERSION", "NS_", "BS_", "BU_", "VAL_TABLE_", "BO_", "BO_TX_BU_", "EV_",
    "ENVVAR_DATA_", "CM_", "BA_DEF_", "BA_DEF_REL_", "BA_DEF_DEF_",
    "BA_DEF_DEF_REL_", "BA_", "BA_REL_", "VAL_", "SIG_VALTYPE_",
]

#: `M` marks a multiplexor and `m<n>` a multiplexed signal — an OBD-II style
#: database needs both, so the pattern must allow the marker before the colon.
SG_RE = re.compile(
    r"^SG_ \w+(?: (?:M|m\d+))? *: \d+\|\d+@[01][+-] \([^)]*\) \[[^\]]*\] "
    r"\"[^\"]*\" .+$")
BO_RE = re.compile(r"^BO_ \d+ \w+ *: \d+ \w+$")


def _packs():
    return sorted(OEM_PACKS_DIR.glob("*/*/*/*.dbc")) if hasattr(
        OEM_PACKS_DIR, "glob") else sorted(__import__("pathlib").Path(
            OEM_PACKS_DIR).glob("*/*/*/*.dbc"))


PACKS = _packs()


def _statements(text):
    """Top-level statement lines, i.e. everything the NS_ block doesn't own."""
    for n, raw in enumerate(text.split("\n"), 1):
        # Indentation must be tested on the RAW line: the NS_ block lists
        # BA_DEF_, VAL_ and friends as indented keywords with no ';'.
        if raw.startswith(("\t", " ")) or not raw.strip():
            continue
        yield n, raw.rstrip()


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_loads_in_cantools(path):
    db = cantools.database.load_file(str(path))
    assert db.messages, f"{path.name} defines no messages"


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_section_order(path):
    """VAL_ before BA_DEF_ is the exact bug that shipped once — never again."""
    rank, prev = -1, None
    for n, line in _statements(path.read_text(encoding="utf-8")):
        kw = line.split()[0].rstrip(":")
        if kw not in SECTION_ORDER:
            continue
        r = SECTION_ORDER.index(kw)
        assert r >= rank, (
            f"{path.name}:{n}: {kw} appears after {prev}; DBC section order is "
            + " -> ".join(SECTION_ORDER))
        rank, prev = r, kw


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_statement_syntax(path):
    for n, line in _statements(path.read_text(encoding="utf-8")):
        s = line.strip()
        if s.startswith(("CM_ ", "BA_DEF_", "BA_DEF_DEF_", "BA_ ", "VAL_ ")):
            assert s.endswith(";"), f"{path.name}:{n}: missing ';' -> {s[:60]}"
            assert s.count('"') % 2 == 0, \
                f"{path.name}:{n}: unbalanced quotes -> {s[:60]}"
        if s.startswith("BO_ "):
            assert BO_RE.match(s), f"{path.name}:{n}: malformed BO_ -> {s[:60]}"


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_signal_lines(path):
    for n, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        s = raw.strip()
        if s.startswith("SG_ "):
            assert SG_RE.match(s), f"{path.name}:{n}: malformed SG_ -> {s[:70]}"


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_references_resolve(path):
    """A CM_/BA_/VAL_ pointing at a message that isn't defined breaks tools."""
    text = path.read_text(encoding="utf-8")
    ids = {int(m.group(1)) for m in re.finditer(r"^BO_ (\d+) ", text, re.M)}
    ref = re.compile(r'^(?:VAL_|CM_ BO_|CM_ SG_|BA_ "[^"]+" BO_) *(\d+)')
    for n, line in _statements(text):
        m = ref.match(line.strip())
        if m:
            assert int(m.group(1)) in ids, \
                f"{path.name}:{n}: references undefined message {m.group(1)}"


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_has_no_empty_messages(path):
    """See "What belongs in a pack DBC" in oem_packs/README.md."""
    db = cantools.database.load_file(str(path))
    empty = [m.name for m in db.messages if not m.signals]
    assert not empty, f"{path.name}: messages with no signals: {empty}"


#: Packs written before the confidence convention. Do not add to this list —
#: grade the signals instead. Removing a name here is always an improvement.
UNGRADED_LEGACY = {
    "mg_commute_ev_2026", "mg_windsor_pro_ev_2026", "mg_zs_ev_2026",
    "mg_zs_ev_2022", "mg_comet_ev_2024",
}

CONFIDENCE_VALUES = ("A_Confirmed", "B_Corroborated", "C_Inferred")


@pytest.mark.skipif(not PACKS, reason="no packs installed")
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.stem)
def test_pack_signals_state_confidence(path):
    """A number nobody can grade is a number nobody should act on.

    Every signal carries its confidence twice: in the comment, so it is visible
    in any DBC tool, and as a ``SignalConfidence`` enum attribute, so it can be
    sorted and filtered.
    """
    if path.stem in UNGRADED_LEGACY:
        pytest.skip(f"{path.stem} predates the confidence convention")
    db = cantools.database.load_file(str(path))
    for msg in db.messages:
        for sig in msg.signals:
            where = f"{path.name} {msg.name}.{sig.name}"
            assert sig.comment, f"{where}: no comment"
            assert sig.comment.startswith("CONFIDENCE "), \
                f"{where}: comment must open with the confidence grade"
            attr = (sig.dbc.attributes or {}).get("SignalConfidence")
            assert attr is not None, f"{where}: no SignalConfidence attribute"
            assert CONFIDENCE_VALUES[int(attr.value)] in CONFIDENCE_VALUES, \
                f"{where}: bad SignalConfidence {attr.value}"
