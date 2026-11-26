"""One command that walks the whole UI and fails on any page JavaScript error.

    .\\.venv\\Scripts\\python.exe tools\\ui_smoke.py [--port 8790] [--views all]

Starts a private copy (tools/shoot.py — its own port and data folder, the database copied),
connects the virtual bus with the simulator on so the views have real traffic, then for dark and
light: every rail view, the Settings dialog, the three Sidebar modes and a 900 px window. Every
state is a screenshot in %TEMP%\\ucando-shoot\\shots — look at them; passing only means nothing
threw. ``--views all`` also switches on the views held back from this release (Settings → Views),
so a held-back view cannot rot unseen.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from shoot import REPO, SHOTS, Session


def nav_ids() -> list[str]:
    app = (REPO / "web" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("const NAV = ["):app.index("const NAV_ITEMS")]
    return re.findall(r'\{ id: "([a-z]+)"', block)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--views", choices=("shown", "all"), default="shown")
    a = p.parse_args(argv)
    views = nav_ids()
    with Session(port=a.port, home="home-smoke", fresh_home=True) as s:
        s.api("/api/connect", {"hw": "virtual", "channel": "ui-smoke", "bitrate": 500000, "simulate": True})
        s.open("/")
        if a.views == "all":
            s.js("NAV_ITEMS && Object.keys(NAV_ITEMS).forEach(id => setViewShown(id, true))")
            time.sleep(.3)
        shown = s.js("[...document.querySelectorAll('#railNav .rail-item')].map(b => b.dataset.view)")
        print(f"rail: {len(shown)} of {len(views)} views shown")
        for theme in ("dark", "light"):
            s.theme(theme)
            for v in shown:
                s.view(v, 1.2)
                s.shot(f"{theme}-{v}")
            s.click("#btnSettings", .8)
            s.shot(f"{theme}-settings")
            s.key("Escape")
            for mode in ("collapsed", "hover", "expanded"):
                s.js(f"UI.setRailMode('{mode}')")
                time.sleep(.4)
                s.shot(f"{theme}-rail-{mode}")
        s.size(900, 900)
        s.view("dashboard", .8)
        s.shot("narrow-dashboard")
        s.size(1440, 900)
        s.collect_errors("end")
        errors = s.errors
    print(f"screenshots: {SHOTS}")
    if errors:
        print("JavaScript errors:", *errors, sep="\n  ")
        return 1
    print("no JavaScript errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
