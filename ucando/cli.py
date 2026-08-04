"""Headless CLI — capture / identify / replay without the web UI.

For fleet agents, CI, and unattended logging. Everything routes through the same
HAL + subsystems the server uses, so behaviour matches the UI exactly.

    python -m ucando.cli log     --hw virtual --channel ucando --seconds 5 --out data/logs/run.asc
    python -m ucando.cli identify --hw virtual --channel ucando --seconds 3
    python -m ucando.cli replay  --hw virtual --channel ucando --file data/logs/run.asc
"""

from __future__ import annotations

import argparse
import os
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


def cmd_tx(args) -> int:
    """Play a saved scenario or an ad-hoc list of files, in order.

    The unattended form of the TX Simulator: same engine, no UI, so a bench
    soak or a CI regression against a telematics unit is one command.
    """
    import json as _json
    from . import txproject

    if args.scenario:
        if os.path.isfile(args.scenario):
            items = _json.load(open(args.scenario, encoding="utf-8"))
            items = items.get("items", items)          # accept a bare list too
        else:
            items = [i.to_dict() for i in txproject.load_saved(Storage(), args.scenario)]
    else:
        items = [{"path": p, "network": args.network, "repeat": args.item_repeat,
                  "gap_before_ms": args.gap} for p in args.files]

    bus = _connect(args)
    rep = LogReplayer()
    meta = rep.set_plan(items)
    print(f"playlist: {meta['item_count']} item(s) · {meta['frames']:,} frames/pass · "
          f"{meta['duration_s']:.1f}s · {meta.get('network') or 'bus'}"
          + (f" · {meta['baud']:,} bit/s" if meta.get("baud") else ""))
    for i, it in enumerate(meta["items"], 1):
        print(f"  {i:2}. {it['label']}  {it['frames']:,} frames · {it['duration_s']:.1f}s"
              + (f" ×{it['repeat']}" if it["repeat"] != 1 else "")
              + (f" · +{it['gap_s']:.2f}s gap" if it["gap_s"] else ""))
    for w in rep.warnings():
        print(f"  ! {w}")

    rep.play(bus.send, speed=args.speed, repeat=args.repeat)
    last = -1
    while rep.status()["state"] in ("playing", "paused"):
        st = rep.status()
        if st["item"] != last:
            last = st["item"]
            print(f"  -> {st['item_label']}")
        time.sleep(0.2)
    st = rep.status()
    bus.disconnect()
    h = st["health"]
    print(f"sent {st['sent']:,} frames · {h['fps']:.0f} fps · drift {h['drift_ms']:.0f} ms · "
          f"late {h['late_pct']:.1f}% (max {h['max_late_ms']:.1f} ms) · errors {h['errors']}")
    if st["state"] == "error":
        print(f"stopped: {st['error']}")
        return 1
    return 0


def cmd_replay(args) -> int:
    bus = _connect(args)
    rep = LogReplayer()
    meta = rep.load(args.file, args.network)
    baud = f", captured at {meta['baud']:,} bit/s" if meta.get("baud") else ""
    print(f"replaying {meta['frames']} frames ({meta['duration_s']}s) on "
          f"{meta.get('network') or 'bus'} at {args.speed}x{baud}")
    for net in meta.get("networks", []):
        if net["frames"] and net["name"] != meta.get("network"):
            print(f"  note: skipping {net['frames']:,} frames on {net['name']} "
                  f"(separate bus — use --network to play it instead)")
    rep.play(bus.send, speed=args.speed, repeat=args.repeat)
    while rep.status()["state"] in ("playing", "paused"):
        time.sleep(0.2)
    st = rep.status()
    bus.disconnect()
    h = st["health"]
    print(f"sent {st['sent']} frames · {h['fps']:.0f} fps · drift {h['drift_ms']:.0f} ms · "
          f"late {h['late_pct']:.1f}% (max {h['max_late_ms']:.1f} ms) · errors {h['errors']}")
    if st["state"] == "error":
        print(f"stopped: {st['error']}")
        return 1
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


def cmd_guided(args) -> int:
    """Mode 2: walk a fuel-type protocol, capturing + labelling each step."""
    import can
    from .guided import load_protocol, GuidedRunner, FrameCollector
    bus = _connect(args)
    proto = load_protocol(args.fuel)
    runner = GuidedRunner(proto)
    coll = FrameCollector(); bus.add_tap(coll.consume)
    steps = runner.steps()
    print(f"=== {proto['title']} ===  ({len(steps)} steps)")
    try:
        for i, step in enumerate(steps, 1):
            print(f"\n[{i}/{len(steps)}] {step['instruction']}")
            kind = step["kind"]
            if step.get("optional") and input("    optional — do this step? [y/N] ").strip().lower() != "y":
                continue
            if kind == "baseline":
                input(f"    Enter to record {step.get('capture_s', 5):.0f}s baseline (hold steady)...")
                coll.reset(); time.sleep(step.get("capture_s", 5))
                print(f"    baseline captured ({len(coll.frames)} IDs)")
            elif kind == "stimulus":
                input(f"    Enter to record {step.get('baseline_s', 4):.0f}s baseline — don't act yet...")
                coll.reset(); time.sleep(step.get("baseline_s", 4)); base = coll.snapshot()
                input("    now PERFORM the action, then Enter to capture...")
                coll.reset(); time.sleep(step.get("action_s", 6)); after = coll.snapshot()
                d = runner.apply_stimulus(step, base, after)
                hits = ", ".join(f"0x{c['id_hex']} bits {c['changed_bits']}" for c in d["changed"])
                print(f"    -> {step['label']}: {hits or 'no change detected (retry?)'}")
            elif kind == "ramp":
                dur = step.get("capture_s", 30)
                input(f"    Enter, then perform the activity for {dur:.0f}s (OBD polling)...")
                coll.reset()
                pids = [0x05, 0x0C, 0x0D, 0x0F, 0x10, 0x11, 0x04, 0x49]
                t0 = time.time()
                while time.time() - t0 < dur:
                    if step.get("obd"):
                        for pid in pids:
                            try:
                                bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                                                     data=bytes([0x02, 0x01, pid, 0, 0, 0, 0, 0])))
                            except Exception:
                                pass
                    time.sleep(0.25)
                print(f"    -> correlated {runner.apply_ramp(step, coll.snapshot())} field(s)")
            elif kind == "known_value":
                coll.reset(); time.sleep(step.get("capture_s", 3)); frames = coll.snapshot()
                raw = input(f"    enter {step['label']} ({step.get('unit', '')}): ").strip()
                try:
                    best = runner.apply_known(step, frames, float(raw))
                    print(f"    -> {step['label']} @ 0x{best['id_hex']} x{best['scale']}" if best else "    -> not found")
                except ValueError:
                    print("    skipped (no value)")
    finally:
        bus.disconnect()
    rep = runner.report()
    print(f"\n=== RESULT  A={rep['counts']['A']}  B={rep['counts']['B']}  C={rep['counts']['C']} ===")
    for x in rep["A"] + rep["B"]:
        tag = "A " if x["tier"] == "A" else "B?"
        print(f"  {tag}  0x{x['id_hex']:<4} {x['label'] or '-':<16} conf={x['confidence']:.2f}")
    if args.save:
        from .oem_db import OemDatabase
        from .storage import Storage
        pid = OemDatabase(Storage()).add_profile(args.oem or "Unknown", args.save,
                                                 dbc=runner.to_dbc_string(), status="draft")
        print(f"saved profile '{args.save}' (id {pid})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ucando.cli", description="uCANdo headless CLI")
    p.add_argument("--hw", default="virtual")
    p.add_argument("--channel", default="ucando")
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
    rp.add_argument("--network", default=None,
                    help="bus to transmit when the log holds several (default: the busiest)")
    rp.add_argument("--repeat", type=int, default=1,
                    help="passes to transmit: 1 once, n a count, 0 endless")
    rp.set_defaults(func=cmd_replay)

    tx = sub.add_parser("tx", help="play a playlist of logs, in order (vehicle mimic)")
    tx.add_argument("files", nargs="*", help="log files, in playback order")
    tx.add_argument("--scenario", default=None,
                    help="a saved scenario name, or a .json playlist file")
    tx.add_argument("--speed", type=float, default=1.0)
    tx.add_argument("--network", default=None, help="bus to transmit (default: the busiest)")
    tx.add_argument("--repeat", type=int, default=1,
                    help="passes of the whole playlist: 1 once, n a count, 0 endless")
    tx.add_argument("--item-repeat", type=int, default=1,
                    help="passes of each file within a playlist pass")
    tx.add_argument("--gap", default=0.0,
                    help="ms of silence before each file, or 'auto' to use the "
                         "real pause recorded between session chunks")
    tx.set_defaults(func=cmd_tx)

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

    gd = sub.add_parser("guided", help="run a guided fuel-type RE protocol (Mode 2)")
    gd.add_argument("--fuel", default="petrol", help="petrol | diesel | ev")
    gd.add_argument("--save", default="", help="save the result as an OEM profile with this name")
    gd.add_argument("--oem", default="", help="OEM name for the saved profile")
    gd.set_defaults(func=cmd_guided)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
