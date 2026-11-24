"""Import a PEAK **PCAN-View trace file** (``.trc``).

PCAN-View is the tool most Indian workshops and fleet integrators already have
on the bench — a PCAN-USB dongle in the OBD-2 port, hit record, get a ``.trc``.
The first Maruti Suzuki pack in this repo was reverse-engineered from exactly
that (see ``docs/SUZUKI_DZIRE_DECODE.md``), so the format has to work in the TX
path too: replay a recorded Dzire onto a bench bus and a telematics unit sees a
car that is not there.

``can.LogReader`` does read ``.trc``, and TX replay through it *paces*
correctly — the inter-frame deltas are right. Three things it gets wrong or
throws away, which is why this module exists:

**1. The absolute timestamp is wrong twice over.** The ``O`` column is not an
offset from ``$STARTTIME`` — it is the PCAN driver's own hardware timer, which
keeps running across trace start/stop, so a file recorded ten minutes into a
session starts at ``O = 600000`` rather than 0. ``can.LogReader`` computes
``$STARTTIME + O``, which double-counts that. On top of that it reads
``$STARTTIME`` as UTC while PCAN-View writes it in **local** time. A real
capture measured here: header says the trace began 17:39:11 local, the first
frame's offset is 131.4 s, and python-can reports 23:11:22 — off by the 5:30
timezone *and* the 131.4 s hardware offset.

Within one file none of that matters (deltas are unaffected). Across files it
matters a lot: :func:`ucando.txproject.build` reconstructs the real pause
between two captures of one session from exactly these timestamps, and on the
14-file Dzire session the uncorrected values make 10 of 13 consecutive pairs
look like they *overlap* (by up to 279 s) and the other 3 report pauses that are
real but wrong. So the anchor here is ``$STARTTIME + (O - O_first)``, with the
local/UTC question settled by the file's own ``;   Start time:`` comment rather
than by guessing.

**2. Direction and non-frame rows vanish.** ``.trc`` marks each row ``Rx``/``Tx``
and carries rows that describe the *bus* rather than a frame — bus-status
changes, error counters, and free-text events. ``can.LogReader`` drops the
latter with a debug log. One of the sample captures ends with ``Hardware
plug-out`` / ``plug-in`` / ``plug-out``: the dongle was unplugged mid-recording
and the data simply stops there. That belongs in the operator's face before a
bench run, not in a bit bucket, so :attr:`TrcLog.census` counts every row by
type and :meth:`TrcLog.notes` turns the interesting ones into sentences.

**3. There is no bitrate, at any format version.** See :data:`DEFAULT_BAUD` —
the assumption is 500 kbit/s, but it is labelled ``assumed`` all the way to the
UI so nothing downstream states it as fact.

Dispatch is by **extension**, unlike the Vehicle Spy reader which has to sniff
content: ``.csv`` is ambiguous (``can.LogReader`` has its own CSV dialect) while
``.trc`` belongs to PEAK alone. All five format versions PCAN-View and
``can.TRCWriter`` emit are handled — 1.0, 1.1, 1.3 and 2.x — 2.x by reading the
``$COLUMNS`` declaration rather than by fixed positions, because the two
producers declare different column sets (PCAN-View v5.2 writes
``N,O,T,I,d,l,D``, ``can.TRCWriter`` writes ``N,O,T,B,I,d,R,L,D``).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

#: Row type codes in the FILEVERSION 2.x ``T`` column. The 1.x layouts have no
#: type column at all: every data row is a classic frame and the direction sits
#: in its own field.
TYPES_DATA = {"DT"}                             # classic CAN data frame
TYPES_FD = {"FD", "FB", "FE", "BI"}             # CAN FD (+bitrate-switch / ESI variants)
TYPES_REMOTE = {"RR"}                           # remote transmission request

#: Rows that describe the **bus**, not a frame: ``ST`` bus-status change, ``EC``
#: error counters, ``ER`` error frame, ``EV`` free-text event. Never
#: transmitted — an error frame is a bus condition, not something to reproduce,
#: and an event row has no payload at all. They are counted and reported.
TYPES_EVENT = {"ST", "EC", "ER", "EV"}

#: What a replay may put on the wire.
TRANSMITTABLE = TYPES_DATA | TYPES_FD | TYPES_REMOTE

#: No ``.trc`` version records the bitrate, so a replay has to assume one or
#: refuse to estimate bus load. Indian passenger-car OBD-2 CAN is 500 kbit/s
#: (the Dzire capture this was written for carries ~109 kbit/s of traffic, ~22 %
#: of 500 k, and ``docs/SUZUKI_DZIRE_DECODE.md`` confirms the bus speed), so
#: that is the default. It is never presented as fact: the network summary
#: carries ``baud_source="assumed"``, the operator can declare the real value
#: per item, and :func:`min_baud` gives a floor the file itself proves.
DEFAULT_BAUD = 500_000

_OLE_EPOCH = datetime(1899, 12, 30)             # day 0 of an OLE Automation date

#: ``;   Start time: 19-08-2026 16:18:43.567.0`` — PCAN-View's own record of when
#: the trace began, in local time. It is the ground truth this module uses to
#: decide whether ``$STARTTIME`` is local or UTC, so it is worth parsing.
_RE_START_COMMENT = re.compile(r"^;\s*Start\s*time\s*:\s*(.+?)\s*$", re.IGNORECASE)
_RE_PCAN_TIME = re.compile(
    r"^(\d{1,2})[-./](\d{1,2})[-./](\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,3}))?(?:\.(\d+))?$")

#: A trace row starts with a message number; 1.x writes it with a trailing
#: ``)``. Used only to tell a data row from a stray line.
_RE_ROW_START = re.compile(r"^\d+\)?\s")

_ANCHOR_TOLERANCE_S = 2.0                       # header comment is written to ms


class TrcLog:
    """One ``.trc`` file: header, frames, and a census of what was not a frame.

    The census is a by-product of walking the rows, which is why this is a
    small object rather than the free functions :mod:`ucando.vspy` uses — the
    caller needs both the frames and, afterwards, an account of what it did not
    get.
    """

    def __init__(self, text: str):
        self.file_version: str = ""             # as written in the file, "" = absent
        self.startime: Optional[float] = None   # raw $STARTTIME, OLE days
        self.columns: dict[str, int] = {}       # 2.x $COLUMNS -> index
        self.header_time: Optional[datetime] = None
        self.header_time_text: str = ""
        self.anchor: float = 0.0                # epoch seconds of the FIRST frame
        self.anchor_source: str = "none"
        self.base_offset_ms: Optional[float] = None
        self.census: dict[str, int] = {}        # type code -> row count
        self.events: list[str] = []             # free text from EV rows, with a time
        self.bad_rows: int = 0
        self.buses: set[int] = set()
        self._lines = text.lstrip("﻿").splitlines()      # strip a UTF-8 BOM
        self._first_row = 0
        self._ncols = 0
        self._parse_header()

    # ----- header ----------------------------------------------------------
    def _parse_header(self) -> None:
        i = 0
        for i, line in enumerate(self._lines):
            s = line.strip()
            if not s:
                continue
            if not s.startswith(";"):
                break
            if s.startswith(";$FILEVERSION"):
                self.file_version = s.partition("=")[2].strip()
            elif s.startswith(";$STARTTIME"):
                try:
                    self.startime = float(s.partition("=")[2].strip())
                except ValueError:
                    pass
            elif s.startswith(";$COLUMNS"):
                cols = [c.strip() for c in s.partition("=")[2].split(",") if c.strip()]
                self.columns = {c: n for n, c in enumerate(cols)}
                self._ncols = len(cols)
            else:
                m = _RE_START_COMMENT.match(s)
                if m and self.header_time is None:
                    self.header_time_text = m.group(1)
                    self.header_time = _parse_header_time(m.group(1))
        else:
            i = len(self._lines)
        self._first_row = i
        self._resolve_anchor()

    def _resolve_anchor(self) -> None:
        """Decide the epoch that the file's first frame sits at.

        ``$STARTTIME`` is an OLE Automation date with no timezone marker, and the
        two producers disagree about what it means: PCAN-View writes local wall
        clock, ``can.TRCWriter`` writes UTC. Rather than guess, read the file's
        own ``Start time:`` comment and keep whichever reading agrees with it —
        a tz-aware comment (``...+00:00``) settles it outright, a naive one is
        compared against both candidates. Local wins when there is nothing to
        compare against, because PCAN-View is overwhelmingly the producer.
        """
        if self.startime is None:
            # FILEVERSION 1.0 has no start time. Offsets are the only clock, so
            # timestamps come out as relative seconds — same as can.LogReader.
            self.anchor, self.anchor_source = 0.0, "none"
            return
        as_utc = (_OLE_EPOCH.replace(tzinfo=timezone.utc)
                  + timedelta(days=self.startime)).timestamp()
        as_local = (_OLE_EPOCH + timedelta(days=self.startime)).timestamp()
        hdr = self.header_time
        if hdr is None:
            self.anchor, self.anchor_source = as_local, "local-assumed"
        elif hdr.tzinfo is not None:
            self.anchor, self.anchor_source = as_utc, "utc-header"
        else:
            want = hdr.timestamp()               # naive datetime == local time
            if abs(as_local - want) <= _ANCHOR_TOLERANCE_S:
                self.anchor, self.anchor_source = as_local, "local-header"
            elif abs(as_utc - want) <= _ANCHOR_TOLERANCE_S:
                self.anchor, self.anchor_source = as_utc, "utc-header"
            else:
                self.anchor, self.anchor_source = as_local, "local-assumed"

    # ----- frames ----------------------------------------------------------
    def frames(self) -> Iterator[dict]:
        """Yield one frame dict per transmittable row, in capture order.

        Shape matches :func:`ucando.vspy.iter_frames` so
        :func:`ucando.logstore.load` treats both the same:
        ``{timestamp, network, id, id_hex, is_extended, is_remote, is_tx, data}``.

        The **first transmittable row** establishes the zero point: its ``O``
        value is what ``$STARTTIME`` actually describes (see the module
        docstring), so every timestamp is ``anchor + (O - O_first)``.
        """
        parse = self._row_parser()
        for line in self._lines[self._first_row:]:
            s = line.strip()
            if not s or s.startswith(";"):
                continue
            try:
                code, row = parse(s)
            except (ValueError, IndexError):
                self.bad_rows += 1
                continue
            self.census[code] = self.census.get(code, 0) + 1
            if row is None:
                if code == "EV" and len(self.events) < 20:
                    self.events.append(_event_text(s))
                continue
            if self.base_offset_ms is None:
                self.base_offset_ms = row["offset_ms"]
            row["timestamp"] = self.anchor + (row["offset_ms"] - self.base_offset_ms) / 1000.0
            self.buses.add(row["bus"])
            yield row

    def _row_parser(self):
        v = self.file_version
        if v.startswith("2."):
            if not self.columns:
                raise ValueError(".trc 2.x file declares no $COLUMNS")
            return self._row_v2
        if v == "1.3":
            return self._row_v1_3
        if v in ("1.1", "1.2"):
            return self._row_v1_1
        return self._row_v1_0          # 1.0, or no version line at all

    # Each _row_* returns (type_code, frame|None). ``None`` means "counted, not
    # transmittable" — a bus event, an error row, a v1.0 bus-info line.
    def _row_v2(self, s: str) -> tuple[str, Optional[dict]]:
        cols = s.split(maxsplit=self._ncols - 1)
        code = cols[self.columns["T"]]
        if code not in TRANSMITTABLE:
            return code, None                    # ST/EC/ER/EV, or a code we don't know
        id_hex = cols[self.columns["I"]]
        bus = int(cols[self.columns["B"]]) if "B" in self.columns else 1
        remote = code in TYPES_REMOTE
        data = b"" if remote else _hex_bytes(cols, self.columns.get("D"))
        return code, _frame(offset_ms=float(cols[self.columns["O"]]), id_hex=id_hex,
                            data=data, bus=bus, remote=remote,
                            is_tx=cols[self.columns["d"]].strip() == "Tx"
                                  if "d" in self.columns else False)

    def _row_v1_0(self, s: str) -> tuple[str, Optional[dict]]:
        # "     1)      1234 0300  8  01 02 03 ..." — no direction, no type.
        cols = s.split()
        id_hex = cols[2]
        if id_hex.upper() == "FFFFFFFF":
            return "BI_LINE", None               # PCAN-View's bus-info row
        remote = len(cols) > 4 and cols[4].upper() == "RTR"
        return "DT", _frame(offset_ms=float(cols[1]), id_hex=id_hex,
                            data=b"" if remote else _hex_bytes(cols, 4),
                            bus=1, remote=remote, is_tx=False)

    def _row_v1_1(self, s: str) -> tuple[str, Optional[dict]]:
        # "     1)      1234 Rx 0300  8  01 02 ..."
        cols = s.split()
        d = cols[2]
        if d not in ("Rx", "Tx"):
            return d, None                       # Warng/Error/BusLight/... row
        remote = len(cols) > 5 and cols[5].upper() == "RTR"
        return "DT", _frame(offset_ms=float(cols[1]), id_hex=cols[3],
                            data=b"" if remote else _hex_bytes(cols, 5),
                            bus=1, remote=remote, is_tx=d == "Tx")

    def _row_v1_3(self, s: str) -> tuple[str, Optional[dict]]:
        # "     1)      1234  1 Rx 0300 -  8  01 02 ..."   (bus col, reserved col)
        cols = s.split()
        d = cols[3]
        if d not in ("Rx", "Tx"):
            return d, None
        remote = len(cols) > 7 and cols[7].upper() == "RTR"
        return "DT", _frame(offset_ms=float(cols[1]), id_hex=cols[4],
                            data=b"" if remote else _hex_bytes(cols, 7),
                            bus=int(cols[2]), remote=remote, is_tx=d == "Tx")

    # ----- reporting -------------------------------------------------------
    def frame_rows(self) -> int:
        return sum(n for code, n in self.census.items() if code in TRANSMITTABLE)

    def event_rows(self) -> int:
        return sum(n for code, n in self.census.items() if code in TYPES_EVENT)

    def notes(self) -> list[str]:
        """Sentences an operator should read before transmitting this file.

        Deliberately not exceptions: none of this stops a replay, but all of it
        changes how much you should trust the result. An unplugged adapter or a
        run of error frames means the recording itself is suspect.
        """
        out: list[str] = []
        events = {code: n for code, n in self.census.items() if code in TYPES_EVENT}
        if events:
            detail = ", ".join(f"{n}x {code}" for code, n in sorted(events.items()))
            out.append(f"{sum(events.values())} non-frame rows not transmitted ({detail})")
        for text in self.events:
            out.append(f"bus event during capture: {text}")
        if self.bad_rows:
            out.append(f"{self.bad_rows} unparseable rows skipped")
        if self.startime is None:
            out.append("file records no start time (FILEVERSION 1.0) — timestamps are "
                       "relative, so cross-file gaps cannot be reconstructed")
        elif self.anchor_source == "local-assumed" and self.header_time is None:
            out.append("file has no 'Start time' comment — reading $STARTTIME as "
                       "local time (PCAN-View's convention)")
        unknown = {code: n for code, n in self.census.items()
                   if code not in TRANSMITTABLE and code not in TYPES_EVENT
                   and code != "BI_LINE"}
        if unknown:
            out.append("unrecognised row types skipped: "
                       + ", ".join(f"{code} x{n}" for code, n in sorted(unknown.items())))
        return out

    def summary(self) -> dict:
        return {
            "file_version": self.file_version or "1.0 (assumed)",
            "columns": "".join(sorted(self.columns)) if self.columns else "",
            "anchor": round(self.anchor, 6),
            "anchor_source": self.anchor_source,
            "base_offset_ms": self.base_offset_ms,
            "header_start_time": self.header_time_text,
            "census": dict(self.census),
            "frame_rows": self.frame_rows(),
            "event_rows": self.event_rows(),
            "bad_rows": self.bad_rows,
            "buses": sorted(self.buses),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def is_trc(path: str) -> bool:
    """``.trc`` belongs to PEAK alone, so the extension is a safe discriminator."""
    return path.lower().endswith(".trc")


def network_name(bus: int) -> str:
    """Stable per-bus network name.

    Stability across files is load-bearing, not cosmetic:
    :func:`ucando.txproject._check_consistency` warns "playlist mixes networks —
    those are separate buses on the vehicle" as soon as a playlist holds more
    than one network name. Naming a network after its file would fire that on
    every multi-file scenario and claim 12 captures of one car were 12 buses. So
    the name comes from the bus index the format supplies (the ``B`` column in
    2.x, field 3 in 1.3, otherwise the single bus 1) and from nothing else.
    """
    return f"CAN {bus}"


def min_baud(bits: int, duration_s: float) -> Optional[int]:
    """Lowest bitrate that could have carried this traffic, from the file alone.

    Needs no declaration from anyone and cannot be wrong: the frames exist and
    they took that long, so a bus slower than this could not have carried them.
    Used to reject an impossible declared bitrate rather than to guess the real
    one — the real bus is usually several times faster than its load.
    """
    if duration_s <= 0 or bits <= 0:
        return None
    return int(bits / duration_s) + 1


def _frame(*, offset_ms: float, id_hex: str, data: bytes, bus: int,
           remote: bool, is_tx: bool) -> dict:
    id_hex = id_hex.strip()
    return {
        "offset_ms": offset_ms,
        "timestamp": 0.0,                        # filled by TrcLog.frames()
        "network": network_name(bus),
        "bus": bus,
        "id": int(id_hex, 16),
        "id_hex": id_hex.upper(),
        # PCAN-View writes an 11-bit id as 4 hex digits and a 29-bit id as 8;
        # can.TRCWriter writes 7 for extended. Anything wider than 4 is extended.
        "is_extended": len(id_hex) > 4,
        "is_remote": remote,
        "is_tx": is_tx,
        "data": data,
    }


def _hex_bytes(cols: list[str], start: Optional[int]) -> bytes:
    """Data bytes from the columns at *start* onwards.

    2.x is split with ``maxsplit`` so the whole data field arrives as one column
    with spaces in it; 1.x arrives as one column per byte. ``bytes.fromhex``
    tolerates the spaces, so joining covers both. A DLC-0 row has no data field
    at all, hence the bounds check rather than an exception.
    """
    if start is None or start >= len(cols):
        return b""
    return bytes.fromhex("".join(cols[start:]))


def _event_text(row: str) -> str:
    """``100000 839880.147 EV Hardware plug-out`` -> ``'839.880s Hardware plug-out'``."""
    parts = row.split(maxsplit=3)
    when = ""
    try:
        when = f"{float(parts[1]) / 1000.0:.3f}s "
    except (ValueError, IndexError):
        pass
    return when + (parts[3].strip() if len(parts) > 3 else "(no detail)")


def _parse_header_time(text: str) -> Optional[datetime]:
    """Parse the ``Start time:`` comment written by either producer.

    ``can.TRCWriter`` writes ``str(datetime)`` — ISO, tz-aware. PCAN-View writes
    ``DD-MM-YYYY HH:MM:SS.mmm.u``, naive local, with sub-millisecond digits after
    a *second* dot that no standard parser accepts.
    """
    text = text.strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    m = _RE_PCAN_TIME.match(text)
    if not m:
        return None
    day, month, year, hh, mm, ss, ms, _sub = m.groups()
    try:
        return datetime(int(year), int(month), int(day), int(hh), int(mm), int(ss),
                        int((ms or "0").ljust(3, "0")) * 1000)
    except ValueError:
        return None
