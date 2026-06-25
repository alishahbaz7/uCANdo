"""uCANdo — Unified CAN Workbench.

A hardware-agnostic CAN bus utility for day-to-day automotive engineering:
logging, replay, reverse engineering, DBC building, visualization and TX.

All hardware access flows through the HAL in :mod:`canforge.hal`, so every
module above it is independent of whether a Neo VI, PCAN, Microchip/SLCAN
adapter, or the development virtual bus is in use.
"""

__version__ = "0.4.7"
__app_name__ = "uCANdo"
