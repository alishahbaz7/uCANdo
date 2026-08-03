"""Device enumeration that populates the hardware-selector dropdown.

Each ``list_*`` function is fully guarded: if the vendor library or driver is
absent it returns ``[]`` rather than raising, so the selector degrades to
whatever is actually available (always at least the virtual bus).

Returned device dicts share a common shape::

    {"hw": <key>, "label": <human text>, "channel": <str>, ...}
"""

from __future__ import annotations


def list_virtual_devices() -> list[dict]:
    return [{"hw": "virtual", "label": "Virtual bus (development)", "channel": "ucando"}]


def list_neovi_devices() -> list[dict]:
    """Intrepid Neo VI devices via the ``ics`` library."""
    try:
        import ics  # type: ignore
    except Exception:
        return []
    try:
        devices = ics.find_devices()
    except Exception:
        return []
    out = []
    for i, dev in enumerate(devices):
        sn = getattr(dev, "SerialNumber", "?")
        out.append({
            "hw": "neovi",
            "label": f"Neo VI #{i} — SN {sn}",
            "channel": str(i + 1),  # 1 = HSCAN1, 2 = HSCAN2, ...
            "serial": str(sn),
        })
    return out


def list_pcan_devices() -> list[dict]:
    """PCAN has no enumeration API — probe the fixed channel names."""
    try:
        import can
    except Exception:
        return []
    found = []
    for i in range(1, 9):
        ch = f"PCAN_USBBUS{i}"
        try:
            bus = can.Bus(interface="pcan", channel=ch, bitrate=500_000)
            bus.shutdown()
        except Exception:
            continue
        found.append({"hw": "pcan", "label": f"PCAN {ch}", "channel": ch})
    return found


def list_microchip_devices() -> list[dict]:
    """Microchip analyzer exposes a CP210x USB-serial bridge (VID 0x10C4)."""
    try:
        import serial.tools.list_ports as list_ports  # type: ignore
    except Exception:
        return []
    out = []
    for port in list_ports.comports():
        is_cp210x = getattr(port, "vid", None) == 0x10C4
        suffix = "" if is_cp210x else "  (verify — not a CP210x)"
        out.append({
            "hw": "microchip",
            "label": f"Microchip CAN — {port.device}{suffix}",
            "channel": port.device,
            "cp210x": is_cp210x,
        })
    return out


def enumerate_all(include_virtual: bool = True) -> list[dict]:
    """All adapters detected right now, virtual bus first."""
    devices: list[dict] = []
    if include_virtual:
        devices += list_virtual_devices()
    devices += list_neovi_devices()
    devices += list_pcan_devices()
    devices += list_microchip_devices()
    return devices
