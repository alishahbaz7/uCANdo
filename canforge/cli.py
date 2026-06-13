"""Headless CLI — capture / identify / replay without the web UI.

For fleet agents, CI, and unattended logging. Everything routes through the same
HAL + subsystems the server uses, so behaviour matches the UI exactly.

    python -m canforge.cli log     --hw virtual --channel canforge --seconds 5 --out data/logs/run.asc
    python -m canforge.cli identify --hw virtual --channel canforge --seconds 3
    python -m canforge.cli replay  --hw virtual --channel canforge --file data/logs/run.asc
"""

from __future__ import annotations

import argparse
import time

from .bus_manager import BusManager
from .oem_db import OemDatabase, fingerprint_from_id_stats
from .replay import LogReplayer
from .storage import Storage


def _connect(args) -> BusManager:
    bus = BusManager()
    bus.connect(args.hw, args.channel, bitrate=args.bitrate,
                simulate=(args.hw == "virtual" and not args.no_sim))
    return bus


def cmd_log(args) -> int:
    bus = _connect(args)
    print(f"capturing {args.seconds}s on {args.hw}:{args.channel} -> {args.out}")
    bus.logger.start_recording(args.format, args.out)
    time.sleep(args.seconds)
    res = bus.logger.stop_recording()
    snap = bus.logger.snapshot()
    bus.disconnect()
    print(f"done: {res.get('frames', 0)} frames, {snap['unique_ids']} IDs -> {res.get('path')}")
    return 0


def cmd_identify(args) -> int:
    bus = _connect(args)
    print(f"observing {args.seconds}s ...")
    time.sleep(args.seconds)
    snap = bus.logger.snapshot()
    bus.disconnect()
    db = OemDatabase(Storage())
    matches = db.identify_from_signature(fingerprint_from_id_stats(snap.get("ids", [])))
    if not matches:
        print("no profile match")
        return 0
    for m in matches:
        print(f"  {m['score']*100:5.1f}%  {m['oem']:12} {m['name']}  ({m['matched']}/{m['profile_ids']} IDs)")
    return 0


def cmd_replay(args) -> int:
    bus = _connect(args)
    rep = LogReplayer()
    meta = rep.load(args.file)
    print(f"replaying {meta['frames']} frames ({meta['duration_s']}s) at {args.speed}x")
    rep.play(bus.send, speed=args.speed)
    while rep.status()["state"] == "playing":
        time.sleep(0.2)
    bus.disconnect()
    print(f"sent {rep.status()['sent']} frames")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="canforge.cli", description="CANForge headless CLI")
    p.add_argument("--hw", default="virtual")
    p.add_argument("--channel", default="canforge")
    p.add_argument("--bitrate", type=int, default=500_000)
    p.add_argument("--no-sim", action="store_true", help="don't start virtual synthetic traffic")
    sub = p.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("log", help="record for N seconds")
    lg.add_argument("--seconds", type=float, default=5.0)
    lg.add_argument("--out", default="data/logs/cli-capture")
    lg.add_argument("--format", default="asc")
    lg.set_defaults(func=cmd_log)

    idf = sub.add_parser("identify", help="fingerprint the bus against the OEM DB")
    idf.add_argument("--seconds", type=float, default=3.0)
    idf.set_defaults(func=cmd_identify)

    rp = sub.add_parser("replay", help="replay a log onto the bus")
    rp.add_argument("--file", required=True)
    rp.add_argument("--speed", type=float, default=1.0)
    rp.set_defaults(func=cmd_replay)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
