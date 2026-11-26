"""uCANdo on the Windows desktop — it opens like an app, though it is a server underneath.

    open_app_window(url)   uCANdo in its own window (Edge's app mode: no address bar, no tabs,
                           uCANdo's title and icon), not a browser tab; a browser tab if there is
                           no Edge or Chrome

Ported from Runway's runway/desktop.py (the user's reference for "a standalone window"). The
window runs in a profile of its own (``data/uCANdoWindow``, ``data/uCANdoDevWin`` from source —
the name gives it its own taskbar button, see window_profile) so its options apply even while the
person's Edge is open — a window opened by a running Edge would take that Edge's options — and in
Edge's dark mode when uCANdo's theme is dark: an app window ignores the page's colours for its
title bar, so this is what gives it a dark one to match the banner.

Standard library only. Off Windows it opens a browser tab.
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser

IS_WINDOWS = sys.platform == "win32"


def find_browser() -> str | None:
    """Edge (on every Windows 10/11), else Chrome — both have an app mode."""
    if not IS_WINDOWS:
        return None
    import winreg

    for exe in ("msedge.exe", "chrome.exe"):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                    path = winreg.QueryValue(k, None)
                if path and os.path.isfile(path.strip('"')):
                    return path.strip('"')
            except OSError:
                pass
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            if base and os.path.isfile(os.path.join(base, rel)):
                return os.path.join(base, rel)
    return None


def app_window_command(browser: str, url: str, profile_dir: str | None = None,
                       dark: bool | None = None) -> list[str]:
    """Edge's app mode, in uCANdo's own profile when one is given."""
    cmd = [browser, f"--app={url}", "--window-size=1440,900"]
    if profile_dir:
        # its own profile never signs in or syncs: a new profile otherwise opens Edge's
        # "We are now syncing your browsing data" over uCANdo's first window
        cmd += [f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check",
                "--disable-sync"]
    if dark:
        cmd.append("--force-dark-mode")
    return cmd


def open_app_window(url: str, profile_dir: str | None = None, dark: bool | None = None) -> bool:
    """Open uCANdo in its own window. Returns False when it fell back to a browser tab."""
    browser = find_browser()
    if browser:
        try:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(app_window_command(browser, url, profile_dir, dark), creationflags=flags,
                             close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass          # no browser at all (a headless box): the URL is printed in the console
    return False


# ── the taskbar: each app its own button, with its own logo ──────────────────────────────────────
# Edge names an app window's taskbar identity (its AppUserModelID) after the address's host and the
# window profile's folder: "MSEdge.127.0.0.1_/.window.Default". uCANdo and Runway both served on
# 127.0.0.1 from a profile folder called "window", so Windows took them for ONE app — one taskbar
# button, one icon, the two windows stacked behind it (the user, 25-11-2026: "both uCANdo and
# Runway will open in independent windows with their logo"). A profile folder named after the app
# and the channel gives each its own identity; the relaunch details make a button pinned from the
# window start uCANdo with uCANdo's logo, not Edge with Edge's.

def window_profile(data_dir: str, channel: str) -> str:
    """uCANdo's own Edge profile — its name is what gives the window its own taskbar button. The
    release and a run from source get one each, so the two side by side are two buttons too.
    Twelve letters, no punctuation: Edge strips punctuation from the name and cuts its part of the
    ID to 20 characters ("uCANdo-dev-window" became "uCANdodevwow"); these come through whole."""
    return os.path.join(data_dir, "uCANdoWindow" if channel == "release" else "uCANdoDevWin")


def adopt_old_profile(data_dir: str, profile_dir: str) -> str:
    """The window profile used to be ``data/window``: move it to its new name, so the page keeps
    what it remembered — theme, sidebar, views and pins live in the profile's localStorage. An Edge
    still running from the old profile holds its files: use it once more and move it next time."""
    old = os.path.join(data_dir, "window")
    if os.path.isdir(old) and not os.path.exists(profile_dir):
        try:
            os.rename(old, profile_dir)
        except OSError:
            return old
    return profile_dir


def relaunch_details(channel: str, frozen: bool | None = None, executable: str | None = None,
                     script: str | None = None, repo: str | None = None) -> dict[str, str]:
    """What a button pinned from uCANdo's window starts, and the logo it shows: the release's own
    exe (its icon is uCANdo's), or this source run's ``python main.py`` with the repo's icon."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = os.path.abspath(executable or sys.executable)
    name = "uCANdo" if channel == "release" else "uCANdo (dev)"
    if frozen:
        return {"command": subprocess.list2cmdline([exe]), "icon": f"{exe},0", "name": name}
    root = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = script or os.path.join(root, "main.py")
    icon = os.path.join(root, "packaging", "ucando.ico")
    return {"command": subprocess.list2cmdline([exe, main]),
            "icon": f"{icon},0" if os.path.isfile(icon) else f"{exe},0", "name": name}


def edge_profile_id(profile_dir: str) -> str:
    """The part of Edge's AppUserModelID that names the profile, the way Edge (Chromium's
    ShellUtil::BuildAppUserModelId) writes it: the user-data folder's name and "Default", only
    letters, digits and dots kept, and over 20 characters cut to its first and last 10 — measured
    on a real window: "uCANdo-dev-window" → "uCANdodevwow.Default"."""
    import re
    part = re.sub(r"[^0-9A-Za-z.]", "", os.path.basename(os.path.normpath(profile_dir))) + ".Default"
    return part if len(part) <= 20 else part[:10] + part[-10:]


def owns_app_id(app_id: str | None, profile_dir: str) -> bool:
    """Whether Edge's taskbar identity for a window names this profile ("….uCANdoWindow.Default")."""
    if not app_id:
        return False
    a = app_id.lower()
    return a.startswith(("msedge.", "chrome.")) and a.endswith("." + edge_profile_id(profile_dir).lower())


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                    ("d4", ctypes.c_ubyte * 8)]

    class _PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]

    class _PROPVARIANT(ctypes.Structure):       # only the VT_LPWSTR shape is used here
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("ptr", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    def _guid(text: str) -> "_GUID":
        g = _GUID()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    _IID_PROPSTORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
    _PKEY_APPUSERMODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
    # System.AppUserModel.*: ID 5, RelaunchCommand 2, RelaunchIconResource 3, RelaunchDisplayNameResource 4
    _PID_ID, _PID_COMMAND, _PID_ICON, _PID_NAME = 5, 2, 3, 4
    _VT_LPWSTR = 31


import threading as _threading

_com = _threading.local()


def _com_ready() -> None:
    """SHGetPropertyStoreForWindow needs COM in the calling thread — once per thread (a call
    from a thread without it simply fails, and the window looks like it has no identity)."""
    if not getattr(_com, "ok", False):
        ctypes.windll.ole32.CoInitialize(None)      # S_OK, or S_FALSE when the thread has it already
        _com.ok = True


def _with_store(hwnd: int, fn):
    """Calls fn(store, vtable) with the window's property store (IPropertyStore), then releases it."""
    _com_ready()
    store = ctypes.c_void_p()
    iid = _guid(_IID_PROPSTORE)
    if ctypes.windll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(iid),
                                                         ctypes.byref(store)) != 0 or not store:
        return None
    vt = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    try:
        return fn(store, vt)
    finally:
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])(store)          # Release


def window_app_id(hwnd: int) -> str | None:
    """The window's AppUserModelID — what Windows groups taskbar buttons by."""
    if not IS_WINDOWS:
        return None

    def read(store, vt):
        get = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
                                 ctypes.POINTER(_PROPVARIANT))(vt[5])                 # GetValue
        key, pv = _PROPERTYKEY(_guid(_PKEY_APPUSERMODEL), _PID_ID), _PROPVARIANT()
        if get(store, ctypes.byref(key), ctypes.byref(pv)) != 0 or pv.vt != _VT_LPWSTR or not pv.ptr:
            return None
        try:
            return ctypes.wstring_at(pv.ptr)
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
    try:
        return _with_store(hwnd, read)
    except OSError:
        return None


def set_relaunch(hwnd: int, command: str, icon: str, name: str) -> bool:
    """Gives the window what a pinned taskbar button starts and shows. Windows reads these only
    for a window that has an AppUserModelID — Edge gives every app window one."""
    if not IS_WINDOWS:
        return False

    def write(store, vt):
        put = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
                                 ctypes.POINTER(_PROPVARIANT))(vt[6])                 # SetValue
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vt[7])          # Commit
        ok = True
        fmt = _guid(_PKEY_APPUSERMODEL)
        # Windows wants the display name and icon in place before the command takes effect
        for pid, text in ((_PID_NAME, name), (_PID_ICON, icon), (_PID_COMMAND, command)):
            buf = ctypes.create_unicode_buffer(text)              # SetValue copies it
            pv = _PROPVARIANT(vt=_VT_LPWSTR, ptr=ctypes.cast(buf, ctypes.c_void_p))
            ok = put(store, ctypes.byref(_PROPERTYKEY(fmt, pid)), ctypes.byref(pv)) == 0 and ok
        return commit(store) == 0 and ok
    try:
        return bool(_with_store(hwnd, write))
    except OSError:
        return False


def app_windows(profile_dir: str) -> list[int]:
    """Visible top-level windows Edge opened from this profile (found by their taskbar identity)."""
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value.startswith("Chrome_WidgetWin") and owns_app_id(window_app_id(hwnd), profile_dir):
                found.append(int(hwnd))
        return True

    user32.EnumWindows(each, 0)
    return found


class WindowBrand:
    """Watches for uCANdo's app windows and gives each its relaunch details — a window opened
    later (a second start, a reopened window) included. A daemon thread, a few calls every 2 s;
    every failure is swallowed: the taskbar is never worth stopping uCANdo for."""

    def __init__(self, profile_dir: str, details: dict[str, str], every: float = 2.0):
        import threading
        self.profile_dir, self.details, self.every = profile_dir, details, every
        self._done: set[int] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="window-brand", daemon=True)

    def start(self) -> "WindowBrand":
        if IS_WINDOWS:
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> int:
        """Brands the windows not yet done; returns how many it branded now."""
        n = 0
        wins = app_windows(self.profile_dir)
        self._done &= set(wins)                       # a closed window's handle may be reused
        for hwnd in wins:
            if hwnd not in self._done and set_relaunch(hwnd, **self.details):
                self._done.add(hwnd)
                n += 1
        return n

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                self.tick()
            except Exception:
                pass


def saved_theme_is_dark(data_dir: str) -> bool:
    """The theme the page last used (it saves ``ui_theme`` through /api/config), read straight
    from the settings table before the server starts. Dark unless it says light — the default."""
    import json
    import sqlite3

    db = os.path.join(data_dir, "ucando.db")
    if not os.path.isfile(db):
        return True
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            row = con.execute("SELECT value FROM settings WHERE key = 'ui_theme'").fetchone()
        finally:
            con.close()
        return not (row and json.loads(row[0]) == "light")
    except Exception:
        return True
