"""Compact, format-agnostic frame store for TX replay.

One recorded log = one :class:`FrameStore`: parallel packed arrays instead of a
list of ``can.Message`` objects. A real capture is big — an Intrepid neoVI
Vehicle Spy buffer save is 100 000 frames per file, and a drive session is
dozens of those — and a ``can.Message`` costs a couple of hundred bytes each,
so the object-per-frame shape runs to ~1 GB for one session. Packed arrays cost
~27 bytes per frame, and the ``can.Message`` is built lazily at send time.

Two other things a replay needs that ``can.LogReader`` alone does not give:

* **Vehicle Spy 3 CSVs.** ``can.LogReader`` dispatches ``.csv`` to its own
  ``timestamp,arbitration_id,...`` dialect and cannot read a neoVI export at
  all, so this module sniffs the file and routes to :mod:`ucando.vspy`.
* **Networks.** One Vehicle Spy file interleaves every bus the tool was wired
  to — a real MG Windsor capture holds ``HS CAN`` *and* ``MS CAN`` in the same
  CSV. Those are physically separate buses; transmitting them onto one channel
  merges traffic that never coexisted. So every frame keeps its network index
  and TX plays one network at a time (see :meth:`indices`).

The per-network summary also recovers the **bitrate** the log was taken at
(Vehicle Spy records it in the ``Network Description`` table) and an estimated
bus load, which is what makes the replay's "connect at 500 kbit/s" prompt and
"this log needs 43 % of the bus" warning possible.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from array import array
from typing import Iterable, Optional

import can

from . import vspy

#: :attr:`FrameStore.flags` bits.
FLAG_EXT = 0x01
FLAG_REMOTE = 0x02
FLAG_TX = 0x04          # the capturing tool sent this frame, it is not vehicle traffic

#: Frame overhead in bits on classic CAN, excluding the data field and bit
#: stuffing: SOF/ID/RTR/IDE/r0/DLC/CRC+delim/ACK+delim/EOF plus the 3-bit
#: inter-frame space. Used for the bus-load estimate only.
_BITS_STD = 47
_BITS_EXT = 67

_DEFAULT_NETWORK = "bus"


class FrameStore:
    """Packed frames in capture order, grouped by network."""

    def __init__(self, path: str = "", source: str = ""):
        self.path = path
        self.source = source                 # "vspy" | "python-can"
        self.t = array("d")                  # absolute capture timestamp, seconds
        self.ids = array("L")
        self.flags = bytearray()
        self.dlc = bytearray()
        self.net = bytearray()               # index into self.networks
        self.off = array("L")                # start of this frame's bytes in self.data
        self.data = bytearray()
        self.networks: list[str] = []
        self.meta: dict[str, dict] = {}      # network name -> {"baud": int|None, "protocol": str}
        self._net_idx: dict[str, int] = {}
        self._stats: list[dict] = []         # per network index, accumulated during load

    # ----- building --------------------------------------------------------
    def network_index(self, name: str) -> int:
        name = name or _DEFAULT_NETWORK
        idx = self._net_idx.get(name)
        if idx is None:
            idx = len(self.networks)
            self._net_idx[name] = idx
            self.networks.append(name)
            self._stats.append({"frames": 0, "bits": 0, "first": None, "last": None,
                                "ids": set(), "tx": 0, "remote": 0})
        return idx

    def append(self, timestamp: float, arb_id: int, data: bytes, *,
               network: str = _DEFAULT_NETWORK, extended: bool = False,
               remote: bool = False, tx: bool = False, dlc: Optional[int] = None) -> None:
        n = self.network_index(network)
        flags = (FLAG_EXT if extended else 0) | (FLAG_REMOTE if remote else 0) | (FLAG_TX if tx else 0)
        length = len(data) if dlc is None else int(dlc)
        self.t.append(float(timestamp))
        self.ids.append(int(arb_id))
        self.flags.append(flags)
        self.dlc.append(min(length, 64))
        self.net.append(n)
        self.off.append(len(self.data))
        self.data += data

        st = self._stats[n]
        st["frames"] += 1
        st["bits"] += (_BITS_EXT if extended else _BITS_STD) + 8 * len(data)
        if st["first"] is None:
            st["first"] = timestamp
        st["last"] = timestamp
        st["ids"].add(int(arb_id))
        if tx:
            st["tx"] += 1
        if remote:
            st["remote"] += 1

    # ----- reading ---------------------------------------------------------
    def __len__(self) -> int:
        return len(self.t)

    def payload(self, i: int) -> bytes:
        start = self.off[i]
        return bytes(self.data[start:start + self.dlc[i]])

    def message(self, i: int) -> can.Message:
        """Build the transmittable ``can.Message`` for frame *i*."""
        return can.Message(
            arbitration_id=self.ids[i],
            data=self.payload(i),
            is_extended_id=bool(self.flags[i] & FLAG_EXT),
            is_remote_frame=bool(self.flags[i] & FLAG_REMOTE),
        )

    def indices(self, network: Optional[str] = None, ids: Optional[Iterable[int]] = None,
                skip_tx: bool = True) -> array:
        """Frame indices to play: one network, optionally an ID whitelist.

        *skip_tx* drops frames the capturing tool transmitted — replaying the
        previous tester's requests is virtually never what you want, and on a
        bench it can double-answer the device under test.
        """
        want_net = self._net_idx.get(network) if network else None
        want_ids = set(ids) if ids else None
        out = array("L")
        for i in range(len(self.t)):
            if want_net is not None and self.net[i] != want_net:
                continue
            if skip_tx and (self.flags[i] & FLAG_TX):
                continue
            if want_ids is not None and self.ids[i] not in want_ids:
                continue
            out.append(i)
        return out

    # ----- summary ---------------------------------------------------------
    def network_summary(self) -> list[dict]:
        out = []
        for n, name in enumerate(self.networks):
            st = self._stats[n]
            first, last = st["first"] or 0.0, st["last"] or 0.0
            dur = max(0.0, last - first)
            info = self.meta.get(name, {})
            baud = info.get("baud")
            fps = (st["frames"] / dur) if dur > 0 else 0.0
            out.append({
                "name": name,
                "protocol": info.get("protocol", "CAN"),
                "frames": st["frames"],
                "ids": len(st["ids"]),
                "tx_frames": st["tx"],
                "first_s": round(first, 3),
                "last_s": round(last, 3),
                "duration_s": round(dur, 3),
                "fps": round(fps, 1),
                "baud": baud,
                # Nominal load: frame overhead + data bits, no stuffing allowance,
                # so treat it as a floor (real load runs a few percent higher).
                "load_pct": round(100.0 * st["bits"] / dur / baud, 1)
                            if (dur > 0 and baud) else None,
            })
        return out

    def summary(self) -> dict:
        nets = self.network_summary()
        total_dur = (self.t[-1] - self.t[0]) if len(self.t) > 1 else 0.0
        return {
            "path": self.path,
            "source": self.source,
            "frames": len(self.t),
            "duration_s": round(total_dur, 3),
            "networks": nets,
            # The bitrate to connect at: only meaningful when every network that
            # actually carries frames agrees, which is the common case.
            "baud_hint": _single_baud(nets),
        }


def _single_baud(nets: list[dict]) -> Optional[int]:
    bauds = {n["baud"] for n in nets if n["frames"] and n["baud"]}
    return bauds.pop() if len(bauds) == 1 else None


def _sniff_vspy(path: str) -> Optional[str]:
    """Return the file text if it is a Vehicle Spy CSV, else ``None``."""
    if not path.lower().endswith(".csv"):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.readline()
            if not vspy.is_vspy_csv(head):
                return None
            return head + fh.read()
    except OSError:
        return None


def load(path: str, use_cache: bool = True) -> FrameStore:
    """Read any supported log into a :class:`FrameStore`.

    Vehicle Spy 3 CSVs are detected by content (not extension) and parsed by
    :mod:`ucando.vspy`; everything else goes through ``can.LogReader``.

    Parsing is cached (see :func:`cache_path`) because a TX playlist re-reads
    the same files every time it is built — a 33-file drive session costs ~23 s
    of CSV parsing and ~0.5 s from cache.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    stat = os.stat(path)
    if use_cache:
        cached = _cache_read(path, stat)
        if cached is not None:
            return cached
    store = _parse(path)
    if use_cache:
        _cache_write(store, stat)
    return store


def _parse(path: str) -> FrameStore:
    text = _sniff_vspy(path)
    if text is not None:
        store = FrameStore(path, "vspy")
        table = vspy.network_table(text)
        for frame in vspy.iter_frames(text):
            store.append(frame["timestamp"], frame["id"], frame["data"],
                         network=frame["network"], extended=frame["is_extended"],
                         remote=frame["is_remote"], tx=frame.get("is_tx", False))
        # Attach baud/protocol for the networks that actually carried frames.
        store.meta = {name: table.get(name, {"protocol": "CAN", "baud": None})
                      for name in store.networks}
        return store

    store = FrameStore(path, "python-can")
    with can.LogReader(path) as reader:
        for msg in reader:
            if msg.is_error_frame:
                continue                    # never re-transmit an error frame
            store.append(msg.timestamp, msg.arbitration_id, bytes(msg.data or b""),
                         network=str(msg.channel) if msg.channel is not None else _DEFAULT_NETWORK,
                         extended=bool(msg.is_extended_id),
                         remote=bool(msg.is_remote_frame))
    store.meta = {name: {"protocol": "CAN", "baud": None} for name in store.networks}
    return store


# ===========================================================================
# Parse cache
# ---------------------------------------------------------------------------
# A cache entry is a JSON header line followed by the raw array bytes, keyed by
# (path, size, mtime) so an edited log is never served stale. Every failure
# path — missing, truncated, corrupt, written by a different Python build —
# falls back to parsing, so the cache can only ever cost time, never
# correctness.
# ===========================================================================
_CACHE_VERSION = 2
_CACHE_ARRAYS = (("t", "d"), ("ids", "L"), ("off", "L"))
_CACHE_BYTES = ("flags", "dlc", "net")


def cache_dir() -> str:
    """Where parsed-log caches live — ``<app home>/data/cache``.

    Mirrors ``server.APP_HOME``: in a **frozen** build ``__file__`` points inside
    the PyInstaller bundle, so deriving the path from it would write the cache
    into the program folder instead of beside the exe with the rest of the
    writable state.
    """
    home = os.environ.get("UCANDO_HOME") or os.environ.get("CANFORGE_HOME")
    if not home:
        home = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(home, "data", "cache")


def cache_path(path: str) -> str:
    digest = hashlib.sha1(os.path.abspath(path).encode("utf-8", "replace")).hexdigest()[:16]
    name = os.path.splitext(os.path.basename(path))[0][:40]
    return os.path.join(cache_dir(), f"{name}.{digest}.ucstore")


def _cache_header(store: FrameStore, stat: os.stat_result) -> dict:
    return {
        "v": _CACHE_VERSION,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "path": store.path,
        "source": store.source,
        "frames": len(store),
        "networks": store.networks,
        "meta": store.meta,
        # itemsize travels with the file: array("L") is 4 bytes on Windows and
        # 8 on most Linux builds, so a cache copied between them must be refused.
        "itemsize": {code: array(code).itemsize for _, code in _CACHE_ARRAYS},
        "data_len": len(store.data),
        "stats": [{**s, "ids": sorted(s["ids"])} for s in store._stats],
    }


def _cache_read(path: str, stat: os.stat_result) -> Optional[FrameStore]:
    cpath = cache_path(path)
    try:
        with open(cpath, "rb") as fh:
            head = json.loads(fh.readline().decode("utf-8"))
            if (head.get("v") != _CACHE_VERSION
                    or head.get("size") != stat.st_size
                    or head.get("mtime_ns") != stat.st_mtime_ns
                    or head.get("itemsize") != {c: array(c).itemsize for _, c in _CACHE_ARRAYS}):
                return None
            n = head["frames"]
            store = FrameStore(head["path"], head["source"])
            for name, code in _CACHE_ARRAYS:
                arr = array(code)
                arr.frombytes(fh.read(n * arr.itemsize))
                if len(arr) != n:
                    return None
                setattr(store, name, arr)
            for name in _CACHE_BYTES:
                buf = bytearray(fh.read(n))
                if len(buf) != n:
                    return None
                setattr(store, name, buf)
            store.data = bytearray(fh.read(head["data_len"]))
            if len(store.data) != head["data_len"]:
                return None
        store.networks = list(head["networks"])
        store._net_idx = {name: i for i, name in enumerate(store.networks)}
        store.meta = head["meta"]
        store._stats = [{**s, "ids": set(s["ids"])} for s in head["stats"]]
        return store
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_write(store: FrameStore, stat: os.stat_result) -> None:
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir(), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(json.dumps(_cache_header(store, stat)).encode("utf-8") + b"\n")
                for name, _ in _CACHE_ARRAYS:
                    fh.write(getattr(store, name).tobytes())
                for name in _CACHE_BYTES:
                    fh.write(bytes(getattr(store, name)))
                fh.write(bytes(store.data))
            os.replace(tmp, cache_path(store.path))     # atomic: no half-written entry
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass                                            # cache is an optimisation, never required
