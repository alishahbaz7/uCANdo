"""Hardware preflight — is each adapter actually ready to use on this machine?

The first time uCANdo runs on a new PC, a vendor driver or Python lib is often
missing (the neoVI needs Intrepid's driver + ``icsneo40.dll``; PCAN needs PEAK's
driver; Microchip/SLCAN needs the CP210x VCP driver). Rather than failing with a
cryptic error at connect time, this module checks each backend's prerequisites
up front and returns a clear status plus **remediation** the UI can act on
(install the right driver, pip-install the lib, or just plug a device in).

Each backend declares its requirements in :data:`REQUIREMENTS` (data-driven, like
the HAL ``BACKENDS`` table). The actual installer download/launch lives in
:mod:`ucando.drivers`; this module only *diagnoses*.
"""

from __future__ import annotations

import importlib.util

# Per-backend prerequisites + how to fix each failure mode.
# `installer` describes an official, on-demand download (never bundled in git).
REQUIREMENTS: dict[str, dict] = {
    "virtual": {
        "label": "Virtual bus (development)",
        "always_ready": True,
    },
    "neovi": {
        "label": "Intrepid neoVI / ValueCAN",
        "python_module": "ics",
        "installer": {
            "name": "Intrepid Hardware Installation Kit",
            "url": "https://cdn.intrepidcs.net/updates/files/RP1210KitInstall.zip",
            "kind": "zip",
            "approx_mb": 1077,
            "info_url": "https://intrepidcs.com/support/support-resources/",
            "note": "Installs the neoVI USB driver + a current icsneo40.dll.",
        },
        "pip": "python-ics",
    },
    "pcan": {
        "label": "PEAK PCAN-USB",
        "dll": "PCANBasic.dll",
        "installer": {
            "name": "PEAK PCAN-Basic driver",
            "url": "https://www.peak-system.com/quick/DrvSetup",
            "kind": "page",
            "info_url": "https://www.peak-system.com/PCAN-Basic.239.0.html",
            "note": "Install the PCAN-Basic / device driver from PEAK, then re-plug.",
        },
    },
    "microchip": {
        "label": "Microchip / SLCAN analyzer (CP210x)",
        "python_module": "serial",
        "installer": {
            "name": "Silicon Labs CP210x VCP driver",
            "url": "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers",
            "kind": "page",
            "info_url": "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers",
            "note": "Install the CP210x VCP driver so the analyzer shows up as a COM port.",
        },
        "pip": "pyserial",
    },
}

# Human-readable meaning + whether the backend is usable, per status code.
_STATUS = {
    "ready":          (True,  "Ready"),
    "no_device":      (True,  "Driver OK — no device connected"),
    "lib_missing":    (False, "Python library not installed"),
    "driver_missing": (False, "Vendor driver / DLL missing or too old"),
    "error":          (False, "Check failed"),
}


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _probe_neovi() -> tuple[str, str, int]:
    if not _has_module("ics"):
        return "lib_missing", "python-ics not installed", 0
    try:
        import ics
        devs = ics.find_devices()
    except Exception as exc:
        msg = str(exc)
        if "127" in msg or "icsneo40" in msg.lower() or "library" in msg.lower():
            return "driver_missing", "icsneo40.dll missing or too old", 0
        return "error", msg, 0
    n = len(devs)
    return ("ready", f"{n} device(s) found", n) if n else ("no_device", "no device connected", 0)


def _probe_dll(dll: str) -> bool:
    import ctypes
    try:
        ctypes.WinDLL(dll)        # Windows only; raises if not found
        return True
    except Exception:
        return False


def check_backend(hw: str) -> dict:
    spec = REQUIREMENTS.get(hw)
    if not spec:
        return {"hw": hw, "ready": False, "status": "error", "detail": "unknown backend"}

    if spec.get("always_ready"):
        return {"hw": hw, "label": spec["label"], "ready": True,
                "status": "ready", "detail": "always available"}

    if hw == "neovi":
        status, detail, devices = _probe_neovi()
    elif hw == "pcan":
        ok = _probe_dll(spec["dll"])
        status, detail, devices = ("no_device", "driver present", 0) if ok else \
            ("driver_missing", f"{spec['dll']} not found", 0)
    else:  # module-based backends (microchip)
        mod = spec.get("python_module")
        if mod and not _has_module(mod):
            status, detail, devices = "lib_missing", f"{mod} not installed", 0
        else:
            status, detail, devices = "no_device", "library present", 0

    ready, label_status = _STATUS.get(status, (False, status))
    result = {"hw": hw, "label": spec["label"], "ready": ready, "status": status,
              "status_label": label_status, "detail": detail, "devices": devices}
    # Attach remediation when not ready.
    if not ready:
        if status == "lib_missing" and spec.get("pip"):
            result["remedy"] = {"type": "pip", "package": spec["pip"],
                                "command": f"pip install {spec['pip']}"}
        elif status == "driver_missing" and spec.get("installer"):
            result["remedy"] = {"type": "installer", **spec["installer"]}
    return result


def check_all() -> list[dict]:
    return [check_backend(hw) for hw in REQUIREMENTS]
