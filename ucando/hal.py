"""Hardware Abstraction Layer.

Every module in uCANdo talks to a single :class:`CANInterface`. The concrete
backend is chosen by :func:`create_interface` from a hardware key, so the rest
of the app never imports ``can`` directly or cares which adapter is plugged in.

Supported hardware keys:

==========  ====================  ====================================
key         python-can interface  notes
==========  ====================  ====================================
virtual     virtual               in-process bus, for development
neovi       neovi                 Intrepid Neo VI (needs ``ics`` lib)
pcan        pcan                  PEAK PCAN (needs PCAN-Basic driver)
microchip   slcan                 Microchip analyzer flashed w/ SLCAN
==========  ====================  ====================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import can

# Per-hardware mapping: the python-can interface string and how the channel
# identifier must be typed before it is handed to ``can.Bus``.
BACKENDS: dict[str, dict] = {
    "virtual":   {"interface": "virtual", "channel_type": "str", "supports_fd": False},
    "neovi":     {"interface": "neovi",   "channel_type": "int", "supports_fd": True},
    "pcan":      {"interface": "pcan",    "channel_type": "str", "supports_fd": True},
    "microchip": {"interface": "slcan",   "channel_type": "str", "supports_fd": False},
}


class CANInterface(ABC):
    """The single surface the rest of the app talks to."""

    @abstractmethod
    def send(self, msg: can.Message) -> None: ...

    @abstractmethod
    def recv(self, timeout: float = 0.1) -> Optional[can.Message]: ...

    @abstractmethod
    def close(self) -> None: ...

    def recover(self) -> bool:
        """Bring the controller back after bus-off or a stuck transmit queue, without closing
        the channel. False when this adapter has no way to (the caller may reopen it)."""
        return False

    def health(self) -> Optional[dict]:
        """The controller's own error state — ``{"state": ok | error-warning |
        error-passive | bus-off | tx-full, "code": …}`` — or None when the adapter
        cannot tell. Frames can still go out in error-warning and error-passive."""
        return None


# PCAN-Basic status bits (CAN_GetStatus, PCANBasic.h) — named here, where their meaning is decided.
_PCAN_XMTFULL, _PCAN_BUSLIGHT, _PCAN_BUSHEAVY = 0x00001, 0x00004, 0x00008      # BUSHEAVY == BUSWARNING
_PCAN_BUSOFF, _PCAN_QXMTFULL, _PCAN_BUSPASSIVE = 0x00010, 0x00080, 0x40000


def pcan_state(code: int) -> str:
    """A PCAN status word, as the state a person can act on. The worst condition wins.

    On a PCAN-USB a blinking red LED is one of the error states — frames still go out while the
    controller counts errors (no ACK on some frames, a missing terminator, a bitrate mismatch);
    bus-off is the controller giving up until it is reset.
    """
    if code & _PCAN_BUSOFF:
        return "bus-off"
    if code & _PCAN_BUSPASSIVE:
        return "error-passive"
    if code & (_PCAN_BUSHEAVY | _PCAN_BUSLIGHT):
        return "error-warning"
    if code & (_PCAN_QXMTFULL | _PCAN_XMTFULL):
        return "tx-full"
    return "ok"


class PythonCANBackend(CANInterface):
    """Thin wrapper around a live ``can.Bus``."""

    def __init__(self, **kwargs):
        self.config = kwargs
        self.bus = can.Bus(**kwargs)

    def send(self, msg: can.Message) -> None:
        self.bus.send(msg)

    def recv(self, timeout: float = 0.1) -> Optional[can.Message]:
        return self.bus.recv(timeout=timeout)

    def close(self) -> None:
        try:
            self.bus.shutdown()
        except Exception:
            # Shutdown must never raise — disconnect is best-effort.
            pass

    def recover(self) -> bool:
        """PCAN: CAN_Reset — clears the transmit queue and resets the controller, what a
        Disconnect + Connect did by hand. Adapters without a reset return False."""
        reset = getattr(self.bus, "reset", None)
        if not callable(reset):
            return False
        try:
            return bool(reset())
        except Exception:
            return False

    def health(self) -> Optional[dict]:
        if self.config.get("interface") != "pcan":
            return None
        try:
            code = int(self.bus.status())
        except Exception:
            return None
        return {"state": pcan_state(code), "code": code}


def _coerce_channel(channel, channel_type: str):
    if channel_type == "int":
        return int(channel)
    return str(channel)


def create_interface(
    hw: str,
    channel,
    bitrate: int = 500_000,
    fd: bool = False,
    **extra,
) -> CANInterface:
    """Open a CAN bus for hardware ``hw`` and return it behind the HAL.

    Raises ``ValueError`` for an unknown key and lets the underlying
    python-can error propagate if the device/driver is missing.
    """
    if hw not in BACKENDS:
        raise ValueError(f"Unknown hardware {hw!r}. Known: {sorted(BACKENDS)}")

    spec = BACKENDS[hw]
    kwargs = dict(
        interface=spec["interface"],
        channel=_coerce_channel(channel, spec["channel_type"]),
        bitrate=bitrate,
    )
    if fd and spec["supports_fd"]:
        kwargs["fd"] = True
    if hw == "pcan":
        # Without it a PCAN channel that goes bus-off (a device that stops acknowledging: unpowered,
        # unplugged, unterminated) stays off until the channel is re-initialised — the user,
        # 25-11-2026: "PCAN will not retransmit until you disconnect and reconnect". With it the
        # driver resets the controller itself (PCAN_BUSOFF_AUTORESET, ~0.5 s).
        kwargs["auto_reset"] = True
    kwargs.update(extra)
    return PythonCANBackend(**kwargs)
