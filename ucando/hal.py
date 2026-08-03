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
    kwargs.update(extra)
    return PythonCANBackend(**kwargs)
