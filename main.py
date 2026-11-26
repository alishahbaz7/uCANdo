"""uCANdo entry point.

Starts the FastAPI server and opens the local UI in the default browser.

    python main.py            # a source run: http://127.0.0.1:8865
    uCANdo.exe                # the packaged release: http://127.0.0.1:8765
    python main.py --port 9000 --no-browser

The release and a source run have different default ports (ucando/channel.py), so both can be
open at once. Starting a second copy of the *same* build does not fight for the port: it opens
the browser on the copy that is already running and exits.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.request
import os
from typing import Any

from ucando import desktop
from ucando.channel import CHANNEL, DEFAULT_PORT, data_dir


def window_profile() -> str:
    """uCANdo's own Edge profile (data/uCANdoWindow, or data/uCANdoDevWin from source) — its name
    gives the window its own taskbar button. The old data/window moves there the first time."""
    home = data_dir()
    return desktop.adopt_old_profile(home, desktop.window_profile(home, CHANNEL))


def open_window(url: str, tab: bool = False) -> None:
    """uCANdo in its own window (Edge app mode, its own profile), like Runway — or a plain
    browser tab with --tab, or when there is no Edge or Chrome."""
    if tab:
        import webbrowser
        webbrowser.open(url)
        return
    desktop.open_app_window(url, profile_dir=window_profile(), dark=desktop.saved_theme_is_dark(data_dir()))


def brand_windows() -> None:
    """Gives every uCANdo window (this one, one a second start opens later) what a pinned taskbar
    button starts and shows: uCANdo and its logo, not Edge. Only on a profile of uCANdo's own —
    while the old shared data/window is still in use its windows look like Runway's to Windows."""
    profile = window_profile()
    if os.path.basename(profile) == os.path.basename(desktop.window_profile(data_dir(), CHANNEL)):
        desktop.WindowBrand(profile, desktop.relaunch_details(CHANNEL)).start()


def probe(host: str, port: int) -> dict[str, Any] | None:
    """What is listening on host:port — None when nothing is; uCANdo's /api/info when it is
    uCANdo; ``{}`` when something else holds the port."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            pass
    except OSError:
        return None
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/info", timeout=2.0) as r:
            info: Any = json.loads(r.read().decode("utf-8", "replace"))
            return dict(info) if isinstance(info, dict) else {}
    except Exception:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="uCANdo - Unified CAN Workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None,
                        help=f"default {DEFAULT_PORT['release']} for the release, "
                             f"{DEFAULT_PORT['dev']} for a run from source")
    parser.add_argument("--no-browser", action="store_true", help="do not open a window")
    parser.add_argument("--tab", action="store_true",
                        help="open in a browser tab instead of uCANdo's own window")
    parser.add_argument("--reload", action="store_true", help="dev auto-reload")
    parser.add_argument("--wait-port", type=float, default=0, metavar="SECONDS",
                        help="wait this long for the port to come free (a restart into a new "
                             "version: the old one is still shutting down)")
    args = parser.parse_args()

    port: int = int(args.port or DEFAULT_PORT[CHANNEL])
    url = f"http://{args.host}:{port}/"
    # how this server was started, so the updater restarts the next version on the same address
    from ucando import install
    install.SERVE_ARGS[:] = ([] if args.port is None else ["--port", str(port)]) + \
        ([] if args.host == "127.0.0.1" else ["--host", args.host])

    if args.wait_port > 0:
        deadline = time.monotonic() + args.wait_port
        while probe(args.host, port) is not None and time.monotonic() < deadline:
            time.sleep(0.5)

    running = probe(args.host, port)
    if running is not None:
        if running.get("app") == "uCANdo":
            # Same address, already serving: a second double-click should just show it.
            print(f"uCANdo is already running at {url} - opening it.")   # ASCII: a cp1252 console
            if not args.no_browser:
                open_window(url, args.tab)
            return
        print(f"Port {port} is in use by another program. Start uCANdo on another port, "
              f"e.g.  python main.py --port {port + 1}", file=sys.stderr)
        sys.exit(1)

    if not args.no_browser:
        def _open():
            # open once the server answers, so the window never shows "can't reach this page"
            for _ in range(60):
                if probe(args.host, port):
                    break
                time.sleep(0.5)
            open_window(url, args.tab)
        threading.Thread(target=_open, daemon=True).start()

    if not args.tab:
        brand_windows()
    print(f"uCANdo ({CHANNEL}) serving at {url}  (close this window to stop)")
    # Closing this window ends the process before uvicorn shuts down; end the usage session first.
    from ucando import usage as usage_mod
    usage_mod.end_session_on_console_close(
        lambda: getattr(sys.modules.get("ucando.server"), "usage", None))
    import uvicorn
    if getattr(sys, "frozen", False):
        # In a packaged build, import the app object directly (no reload import-string).
        from ucando.server import app
        uvicorn.run(app, host=args.host, port=port)
    else:
        uvicorn.run("ucando.server:app", host=args.host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
