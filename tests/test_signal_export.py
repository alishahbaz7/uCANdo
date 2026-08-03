"""Signal-table export (/api/signals/export-xlsx) + the DBC limits that the
summary view flags against (SignalViewer.info()).

The UI builds the time x signal matrix client-side; only the .xlsx writer
lives on the server, because CSV cannot carry the held/changed cell colouring.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from ucando.server import app
from ucando.signals import SignalViewer

client = TestClient(app)

DBC_LIMITS = """VERSION ""

BU_:

BO_ 256 ENGINE: 8 Vector__XXX
 SG_ EngineRPM : 0|16@1+ (0.25,0) [0|8000] "rpm" Vector__XXX
 SG_ Gear : 16|4@1+ (1,0) [0|6] "" Vector__XXX
"""


def test_info_carries_dbc_limits_for_range_flagging():
    """The summary panel flags a decoded value that falls outside the DBC's own
    declared range — which needs those limits to reach the client."""
    viewer = SignalViewer()
    viewer.load_dbc_string(DBC_LIMITS, "limits.dbc")
    by_key = {s["key"]: s for s in viewer.info()["signals"]}

    rpm = by_key["ENGINE.EngineRPM"]
    assert rpm["minimum"] == 0 and rpm["maximum"] == 8000
    assert rpm["unit"] == "rpm"
    assert rpm["length"] == 16
    assert rpm["is_signed"] is False
    assert by_key["ENGINE.Gear"]["maximum"] == 6


def test_info_without_dbc_limits_reports_none():
    """A DBC that omits [min|max] must yield None, not 0 — otherwise every
    signal would look like it were pinned to a zero-width range."""
    viewer = SignalViewer()
    viewer.load_dbc_string(
        'VERSION ""\n\nBU_:\n\nBO_ 100 M: 1 Vector__XXX\n'
        ' SG_ S : 0|8@1+ (1,0) [0|0] "" Vector__XXX\n',
        "nolimits.dbc",
    )
    sig = viewer.info()["signals"][0]
    assert sig["minimum"] is None and sig["maximum"] is None


def _payload(rows=None):
    return {
        "source": "capture.csv",
        "interval_ms": 100.0,
        "truncated": 0,
        "columns": [{"key": "ENGINE.EngineRPM", "unit": "rpm", "decimals": 2},
                    {"key": "ENGINE.Gear", "unit": "", "decimals": 0}],
        "summary": [
            {"key": "ENGINE.EngineRPM", "state": "varies", "min": 0, "max": 9000,
             "range": 9000, "distinct": 40, "unit": "rpm", "period_ms": 100.0,
             "samples": 3, "dbc_min": 0, "dbc_max": 8000,
             "notes": "outside DBC [0, 8000]"},
            # A constant signal: range 0 (it never moved) but 1 unique value
            # (itself) — two different questions, both columns present.
            {"key": "ENGINE.Gear", "state": "CONST", "min": 2, "max": 2,
             "range": 0, "distinct": 1, "unit": "", "period_ms": 100.0,
             "samples": 3, "dbc_min": 0, "dbc_max": 6, "notes": "constant"},
        ],
        "rows": rows if rows is not None else [
            {"t": 0.0, "cells": [{"v": 800.0, "s": "fresh", "ch": False},
                                 {"v": 2.0, "s": "fresh", "ch": False}]},
            {"t": 0.1, "cells": [{"v": 9000.0, "s": "fresh", "ch": True}, None]},
            {"t": 0.2, "cells": [{"v": 9000.0, "s": "stale", "ch": False},
                                 {"v": 2.0, "s": "fresh", "ch": False}]},
        ],
    }


def test_export_xlsx_returns_a_real_workbook():
    r = client.post("/api/signals/export-xlsx", json=_payload())
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    # .xlsx is a zip container — proves we returned a workbook, not an error page.
    assert r.content[:2] == b"PK"

    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Data", "About"]

    data = wb["Data"]
    assert [c.value for c in data[1]] == ["t (s)", "ENGINE.EngineRPM (rpm)", "ENGINE.Gear"]
    assert data.cell(row=2, column=2).value == 800.0
    # A cell with no value yet must stay empty rather than inventing a number.
    assert data.cell(row=3, column=3).value is None
    # Changed cells keep a fill; held ones are greyed. That colouring is the
    # whole reason this endpoint exists instead of just emitting CSV.
    assert data.cell(row=3, column=2).fill.fgColor.rgb.endswith("D6E9FF")
    assert data.cell(row=4, column=2).font.italic is True

    summary = wb["Summary"]
    header = [c.value for c in summary[1]]
    # "Range" (max-min) and "Unique" (count of different values) are distinct
    # questions; a lone ambiguous column reads as the wrong one.
    assert "Range" in header and "Unique" in header and "Distinct" not in header
    assert summary.cell(row=2, column=1).value == "ENGINE.EngineRPM"
    assert summary.cell(row=2, column=1).fill.fgColor.rgb.endswith("FBD5D5")
    gear = [c.value for c in summary[3]]
    assert gear[header.index("Range")] == 0        # never moved
    assert gear[header.index("Unique")] == 1       # ...but it does have one value


def test_export_xlsx_accepts_an_empty_selection():
    """No rows is a legitimate export (e.g. changes-only filtered everything
    out) — it must still produce a workbook rather than a 500."""
    r = client.post("/api/signals/export-xlsx", json=_payload(rows=[]))
    assert r.status_code == 200
    assert r.content[:2] == b"PK"


def test_export_xlsx_tolerates_short_cell_rows():
    """A row carrying fewer cells than there are columns must not raise —
    the writer pads rather than trusting the client's row length."""
    r = client.post("/api/signals/export-xlsx", json=_payload(rows=[
        {"t": 0.0, "cells": [{"v": 1.0, "s": "fresh", "ch": False}]},
    ]))
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
