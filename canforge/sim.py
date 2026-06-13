"""Synthetic traffic generator for the development virtual bus.

Without hardware the virtual bus is silent, so there is nothing for the CAN
Logger to capture. This feeder emits a small set of realistic-looking frames
(ramping engine RPM, a rolling counter, a noisy sensor, a fixed status frame)
on its own ``can.Bus`` connected to the same virtual channel. Every other bus
on that channel — including the one the logger reads — receives them.

The varied signals also give the future Reverse-Engineering module something
real to chew on (a monotonic counter, a slow ramp, high-entropy noise, and a
constant) when developing offline.
"""

from __future__ import annotations

import math
import struct
import threading
import time

import can


class SyntheticTraffic:
    def __init__(self, channel: str = "canforge", bitrate: int = 500_000):
        self.channel = channel
        self.bitrate = bitrate
        self._bus: can.Bus | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._bus = can.Bus(interface="virtual", channel=self.channel, bitrate=self.bitrate)
        self._running = True
        self._thread = threading.Thread(target=self._run, name="synthetic-traffic", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._bus:
            try:
                self._bus.shutdown()
            finally:
                self._bus = None

    def _run(self) -> None:
        counter = 0
        # Pseudo-random without Math.random/time-seeding: a simple LCG.
        rng = 0x1234_5678
        tick = 0
        while self._running and self._bus is not None:
            tick += 1
            # 0x100 — engine RPM ramping 800..6000 as a sine sweep (2 bytes, big-endian).
            rpm = int(3400 + 2600 * math.sin(tick / 40.0))
            self._emit(0x100, struct.pack(">HHHH", rpm, rpm // 4, 0, tick & 0xFFFF))

            # 0x200 — rolling 8-bit counter + constant marker.
            counter = (counter + 1) & 0xFF
            self._emit(0x200, bytes([counter, 0xA5, 0x00, 0x00]))

            # 0x301 — high-entropy "sensor" noise (2 bytes) + steady 0x7F.
            rng = (1103515245 * rng + 12345) & 0x7FFF_FFFF
            noise = rng & 0xFFFF
            self._emit(0x301, struct.pack(">HH", noise, 0x007F))

            # 0x7DF — a constant status/heartbeat frame (low rate).
            if tick % 10 == 0:
                self._emit(0x7DF, bytes([0x02, 0x01, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x00]))

            # ~10 Hz: standard-protocol frames so the Dashboard populates.
            if tick % 10 == 0:
                self._emit_standard(tick, rpm)

            time.sleep(0.01)  # ~100 frames/s aggregate

    def _emit_standard(self, tick: int, rpm: int) -> None:
        """OBD-II Mode-01 responses + J1939 broadcast frames for the Dashboard."""
        speed = int(40 + 30 * math.sin(tick / 90.0))           # km/h
        coolant = int(85 + 8 * math.sin(tick / 200.0))         # °C
        throttle = int(20 + 60 * (0.5 + 0.5 * math.sin(tick / 60.0)))  # %

        # OBD-II single-frame responses on 0x7E8 (mode 0x41), rotating PIDs.
        obd_cycle = (tick // 10) % 4
        if obd_cycle == 0:      # RPM (PID 0x0C), raw = rpm*4
            r = rpm * 4
            self._emit(0x7E8, bytes([0x04, 0x41, 0x0C, (r >> 8) & 0xFF, r & 0xFF, 0, 0, 0]))
        elif obd_cycle == 1:    # Vehicle speed (PID 0x0D)
            self._emit(0x7E8, bytes([0x03, 0x41, 0x0D, speed & 0xFF, 0, 0, 0, 0]))
        elif obd_cycle == 2:    # Coolant temp (PID 0x05), raw = °C + 40
            self._emit(0x7E8, bytes([0x03, 0x41, 0x05, (coolant + 40) & 0xFF, 0, 0, 0, 0]))
        else:                   # Throttle position (PID 0x11), raw = %*255/100
            self._emit(0x7E8, bytes([0x03, 0x41, 0x11, int(throttle * 255 / 100) & 0xFF, 0, 0, 0, 0]))

        # J1939 EEC1 (PGN 0xF004): engine speed at bytes 3-4 LE, scale 0.125.
        es = int(rpm / 0.125) & 0xFFFF
        self._emit(self._j1939_id(0xF0, 0x04), bytes([0xFF, 0xFF, (125 + 30) & 0xFF,
                   es & 0xFF, (es >> 8) & 0xFF, 0xFF, 0xFF, 0xFF]), extended=True)
        # J1939 ET1 (PGN 0xFEEE): coolant temp byte 0 = °C + 40.
        self._emit(self._j1939_id(0xFE, 0xEE), bytes([(coolant + 40) & 0xFF, (50 + 40) & 0xFF,
                   0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), extended=True)
        # J1939 CCVS (PGN 0xFEF1): wheel speed bytes 1-2 LE, scale 1/256.
        ws = int(speed * 256) & 0xFFFF
        self._emit(self._j1939_id(0xFE, 0xF1), bytes([0xFF, ws & 0xFF, (ws >> 8) & 0xFF,
                   0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), extended=True)

        # ---- Diagnostic Trouble Codes (low rate, ~every 5 s) ----
        if tick % 500 == 0:
            # OBD-II Mode 03 response: count=2, P0133 (0x0133) + P0420 (0x0420).
            self._emit(0x7E8, bytes([0x06, 0x43, 0x02, 0x01, 0x33, 0x04, 0x20, 0x00]))
        if tick % 100 == 0:
            # J1939 DM1 (PGN 0xFECA): lamp bytes + one DTC SPN 100 (oil pressure), FMI 1, OC 1.
            self._emit(self._j1939_id(0xFE, 0xCA),
                       bytes([0x00, 0xFF, 0x64, 0x00, 0x01, 0x01, 0xFF, 0xFF]), extended=True)

    @staticmethod
    def _j1939_id(pf: int, ps: int, priority: int = 3, source: int = 0x00) -> int:
        return (priority << 26) | (pf << 16) | (ps << 8) | source

    def _emit(self, arb_id: int, data: bytes, extended: bool = False) -> None:
        try:
            self._bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=extended))
        except Exception:
            pass
