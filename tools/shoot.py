"""Drive a private uCANdo copy in headless Edge, click the real controls and screenshot it.

User skill ``utility-ui`` §13 and docs/WAY_WE_WORK.md: a UI change is done when it has been driven
and looked at, not when it compiles — and a screenshot of an empty page proves nothing. So this
starts its **own** server on a spare port with ``UCANDO_HOME`` in a work folder (never the repo's
``data/``; the database is *copied* there so OEM profiles exist), drives the page over the Chrome
DevTools protocol, and collects every page JavaScript error.

    from shoot import Session
    with Session(port=8791) as s:
        s.api("/api/connect", {"hw": "virtual", "channel": "shoot", "simulate": True})
        s.open("/")
        s.view("dashboard"); s.shot("dash-dark")
        assert not s.errors

Things learned the hard way, kept here so they are not learned again:

* Edge forks renderer/GPU children that outlive ``kill()`` and keep the DevTools port, so the next
  run attaches to a stale browser: the whole tree is killed, then a sweep by this run's profile.
* ``click()`` is a real pointer click (pointer events, user activation). A synthetic ``.click()``
  has no user activation, so Chrome groups the dialogs it opens and one Esc closes them all. A
  click off-screen lands nowhere — ``click()`` scrolls the control into view first.
* The first document is ``about:blank``, already "complete": ``open()`` waits for our URL.
* Runtime.evaluate runs in the global scope: wrap ``const`` in ``{…}`` or the second call fails.

Needs Edge or Chrome (``ucando.desktop.find_browser``) and ``websockets`` (from uvicorn[standard]).
Work files go to ``%TEMP%/ucando-shoot`` unless ``UCANDO_SHOOT_DIR`` says otherwise.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ucando.desktop import find_browser  # noqa: E402

PY = REPO / ".venv" / "Scripts" / "python.exe"
WORK = Path(os.environ.get("UCANDO_SHOOT_DIR") or Path(tempfile.gettempdir()) / "ucando-shoot")
SHOTS = WORK / "shots"

ERR_HOOK = (
    "window.__errs=[];"
    "addEventListener('error',e=>__errs.push(String(e.message)+' @'+(e.filename||'')+':'+(e.lineno||'')));"
    "addEventListener('unhandledrejection',e=>__errs.push('rejection: '+String(e.reason)));"
)


class Session:
    def __init__(self, port=8791, width=1440, height=900, home="home", env=None, fresh_home=False):
        self.port, self.width, self.height = port, width, height
        self.base = f"http://127.0.0.1:{port}"
        self.home = WORK / home
        self.extra_env = env or {}
        self.fresh_home = fresh_home
        self._id = 0
        self.errors: list[str] = []

    # ---- lifecycle ---------------------------------------------------------
    def __enter__(self):
        browser = find_browser()
        if not browser:
            raise RuntimeError("no Edge or Chrome found")
        if self.fresh_home and self.home.exists():
            shutil.rmtree(self.home, ignore_errors=True)
        (self.home / "data").mkdir(parents=True, exist_ok=True)
        db = REPO / "data" / "ucando.db"                  # server: DATA_DIR = UCANDO_HOME/data
        if db.exists() and not (self.home / "data" / "ucando.db").exists():
            shutil.copy2(db, self.home / "data" / "ucando.db")   # a copy: the real DB is never touched
        # usage reporting stays off unless the caller turns it on (and points it somewhere harmless)
        env = {**os.environ, "UCANDO_HOME": str(self.home), "UCANDO_USAGE": "off", **self.extra_env}
        self.log = open(WORK / f"server-{self.port}.log", "w", encoding="utf-8")
        py = PY if PY.exists() else Path(sys.executable)
        self.srv = subprocess.Popen([str(py), "main.py", "--port", str(self.port), "--no-browser"],
                                    cwd=REPO, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self._wait_http(self.base + "/api/info", 40)
        self.profile = WORK / f"edge-{self.port}"
        shutil.rmtree(self.profile, ignore_errors=True)
        dbg = self.port + 1000
        self.edge = subprocess.Popen([
            browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--no-proxy-server",
            f"--remote-debugging-port={dbg}", "--remote-allow-origins=*",
            f"--user-data-dir={self.profile}", f"--window-size={self.width},{self.height}", "about:blank"])
        tgt = None
        for _ in range(100):
            try:
                tgts = json.load(urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json", timeout=2))
                tgt = next(t for t in tgts if t["type"] == "page")
                break
            except Exception:
                time.sleep(.2)
        if not tgt:
            raise RuntimeError("the browser's DevTools never came up")
        self.ws = connect(tgt["webSocketDebuggerUrl"], max_size=200_000_000, open_timeout=10)
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("Page.addScriptToEvaluateOnNewDocument", source=ERR_HOOK)
        self.size(self.width, self.height)
        SHOTS.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc):
        tree_kill = lambda: subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.edge.pid)],
                                           capture_output=True)
        sweep = lambda: subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | Where-Object { $_.CommandLine -like '*"
             + str(self.profile) + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True)
        for closer in (lambda: self.ws.close(), tree_kill, sweep, lambda: self.srv.kill(),
                       lambda: self.log.close()):
            try:
                closer()
            except Exception:
                pass

    @staticmethod
    def _wait_http(url, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                urllib.request.urlopen(url, timeout=2).read()
                return
            except Exception:
                time.sleep(.25)
        raise RuntimeError(f"server never answered {url}")

    # ---- DevTools ----------------------------------------------------------
    def cmd(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=60))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr, await_promise=True):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError(f"JS failed: {expr[:120]} -> {d.get('exception', {}).get('description', d)}")
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=15, what=None):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.js(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(.2)
        raise TimeoutError(what or expr)

    def size(self, w, h):
        self.width, self.height = w, h
        self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)

    def scheme(self, light: bool | None):
        """Emulate the OS colour scheme (for Auto). None clears it."""
        feats = [] if light is None else [{"name": "prefers-color-scheme", "value": "light" if light else "dark"}]
        self.cmd("Emulation.setEmulatedMedia", features=feats)

    # ---- the app -------------------------------------------------------------
    def api(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        return json.load(urllib.request.urlopen(req, timeout=120))

    def open(self, path="/", ready="document.readyState==='complete'"):
        self.cmd("Page.navigate", url=self.base + path)
        time.sleep(.3)
        self.wait(f"location.href.startsWith({json.dumps(self.base)}) && {ready}", 20, "page load")
        time.sleep(.6)

    def view(self, name, settle=1.0):
        """Open a view through its real rail item."""
        self.js(f"(document.querySelector('[data-view=\"{name}\"]')||{{click(){{throw new Error('no nav {name}')}}}}).click()")
        time.sleep(settle)

    def center(self, sel):
        r = self.js(f"""(()=>{{const e=document.querySelector({json.dumps(sel)}); if(!e) return null;
            const r=e.getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2];}})()""")
        if not r:
            raise RuntimeError(f"no element {sel}")
        return r

    def hover(self, sel=None, xy=None):
        x, y = xy or self.center(sel)
        self.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    def click(self, sel, settle=.5, scroll=True):
        """A real pointer click at the control's centre, scrolled into view first."""
        if scroll:
            self.js(f"(document.querySelector({json.dumps(sel)})||{{scrollIntoView(){{}}}}).scrollIntoView({{block:'nearest'}})")
            time.sleep(.15)
        x, y = self.center(sel)
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.cmd("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)
        time.sleep(settle)

    def upload(self, sel, paths, settle=1.5):
        """Put real files (one path or a list) into an <input type=file> and fire its change."""
        paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
        root = self.cmd("DOM.getDocument")["root"]["nodeId"]
        node = self.cmd("DOM.querySelector", nodeId=root, selector=sel)["nodeId"]
        self.cmd("DOM.setFileInputFiles", files=[str(p) for p in paths], nodeId=node)
        self.js(f"document.querySelector({json.dumps(sel)}).dispatchEvent(new Event('change', {{bubbles:true}}))")
        time.sleep(settle)

    def key(self, key="Escape", code=None, vk=27):
        for t in ("keyDown", "keyUp"):
            self.cmd("Input.dispatchKeyEvent", type=t, key=key, code=code or key, windowsVirtualKeyCode=vk)
        time.sleep(.3)

    def theme(self, t):
        """auto / light / dark, the way the page sets it."""
        self.js(f"UI.setTheme('{t}')")
        time.sleep(.4)

    def shot(self, name, full=False):
        params = {"format": "png"}
        if full:
            h = self.js("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)")
            params["clip"] = {"x": 0, "y": 0, "width": self.width, "height": h, "scale": 1}
            params["captureBeyondViewport"] = True
        data = self.cmd("Page.captureScreenshot", **params)["data"]
        out = SHOTS / f"{name}.png"
        out.write_bytes(base64.b64decode(data))
        self.collect_errors(name)
        return out

    def collect_errors(self, where=""):
        errs = json.loads(self.js("JSON.stringify(window.__errs||[])") or "[]")
        if errs:
            self.errors += [f"[{where}] {e}" for e in errs]
            self.js("window.__errs=[]")
        return errs


if __name__ == "__main__":
    print("a library — see tools/ui_smoke.py for a run that uses it", file=sys.stderr)
