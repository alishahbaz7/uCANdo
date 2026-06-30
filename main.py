"""CANForge entry point.

Starts the FastAPI server and opens the local UI in the default browser.

    python main.py            # serve on http://127.0.0.1:8765
    python main.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="CANForge — Unified CAN Workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not auto-open the browser")
    parser.add_argument("--reload", action="store_true", help="dev auto-reload")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    print(f"uCANdo serving at {url}  (close this window to stop)")
    if getattr(sys, "frozen", False):
        # In a packaged build, import the app object directly (no reload import-string).
        from canforge.server import app
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        uvicorn.run("canforge.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
