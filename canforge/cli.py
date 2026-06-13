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


def cmd_drive(args) -> int:
    """Record while polling standard OBD-II PIDs, for correlation-based labeling."""
    import can
    bus = _connect(args)
    print(f"drive capture {args.seconds}s on {args.hw}:{args.channel} -> {args.out}  (polling OBD)")
    print("DRIVE NOW: vary speed + throttle; let it warm up. Ctrl+C won't be needed.")
    bus.logger.start_recording(args.format, args.out)
    PIDS = [0x05, 0x0C, 0x0D, 0x0F, 0x10, 0x11, 0x04, 0x2F, 0x49]  # coolant,rpm,speed,IAT,MAF,thr,load,fuel,APP
    t0 = time.time()
    while time.time() - t0 < args.seconds:
        for pid in PIDS:
            try:
                bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                                     data=bytes([0x02, 0x01, pid, 0, 0, 0, 0, 0])))
            except Exception:
                pass
        time.sleep(0.2)
    res = bus.logger.stop_recording(); snap = bus.logger.snapshot()
    bus.disconnect()
    print(f"done: {res.get('frames', 0)} frames, {snap['unique_ids']} IDs -> {res.get('path')}")
    print("analyze: deep_correlate_log() labels VSS / IAT / MAF / APP / coolant by correlation")
    return 0


def cmd_sniff(args) -> int:
    """Find a discrete signal (door, indicator, brake...) by toggling its control."""
    from .re_engines.diff import StateSniffer
    bus = _connect(args)
    snf = StateSniffer(); bus.add_tap(snf.consume)
    snf.arm()
    print(f"[baseline] keep everything STEADY — do NOT touch '{args.label}' for {args.baseline:.0f}s ...")
    time.sleep(args.baseline)
    snf.mark()
    print(f">>> NOW TOGGLE: {args.label}  (on/off several times) for {args.action:.0f}s <<<")
    time.sleep(args.action)
    res = snf.result(); bus.disconnect()
    changed = res.get("changed", [])
    if not changed:
        print("no bit changed — toggle more distinctly (or it's on another bus) and retry")
        return 0
    print(f"=== '{args.label}' -> ===")
    for c in changed:
        byts = ",".join(str(b["index"]) for b in c["changed_bytes"])
        print(f"  0x{c['id_hex']}  changed bits {c['changed_bits']}  (byte {byts})")
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

    dr = sub.add_parser("drive", help="record + poll OBD PIDs (for correlation labeling)")
    dr.add_argument("--seconds", type=float, default=120.0)
    dr.add_argument("--out", default="data/logs/drive")
    dr.add_argument("--format", default="asc")
    dr.set_defaults(func=cmd_drive)

    sn = sub.add_parser("sniff", help="find a discrete signal by toggling its control")
    sn.add_argument("--label", required=True, help="name of the control, e.g. 'Left indicator'")
    sn.add_argument("--baseline", type=float, default=4.0)
    sn.add_argument("--action", type=float, default=6.0)
    sn.set_defaults(func=cmd_sniff)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
