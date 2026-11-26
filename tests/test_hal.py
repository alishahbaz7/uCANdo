"""HAL factory and the virtual backend."""

import can
import pytest

from ucando.hal import BACKENDS, CANInterface, create_interface


def test_unknown_hardware_raises():
    with pytest.raises(ValueError):
        create_interface("nosuchhw", "x")


def test_channel_type_coercion():
    # int-typed backends coerce the channel; the table drives it.
    assert BACKENDS["virtual"]["channel_type"] == "str"
    assert BACKENDS["neovi"]["channel_type"] == "int"


def test_virtual_interface_send_recv(vchannel):
    a = create_interface("virtual", vchannel)
    b = create_interface("virtual", vchannel)
    assert isinstance(a, CANInterface)
    try:
        a.send(can.Message(arbitration_id=0x123, data=b"\x01\x02", is_extended_id=False))
        msg = b.recv(timeout=1.0)
        assert msg is not None
        assert msg.arbitration_id == 0x123
        assert bytes(msg.data) == b"\x01\x02"
    finally:
        a.close()
        b.close()


def test_close_is_safe_to_call_twice(vchannel):
    iface = create_interface("virtual", vchannel)
    iface.close()
    iface.close()   # must never raise


# ---- PCAN: bus-off recovery and the controller's state --------------------------------------
def test_pcan_opens_with_the_drivers_bus_off_auto_reset(monkeypatch):
    """Without it a PCAN channel that goes bus-off stays off until re-initialised — the user had
    to disconnect and reconnect to get TX going again (25-11-2026)."""
    from ucando import hal
    seen = {}

    class FakeBus:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(hal.can, "Bus", FakeBus)
    hal.create_interface("pcan", "PCAN_USBBUS1", bitrate=500_000)
    assert seen["interface"] == "pcan" and seen["auto_reset"] is True
    seen.clear()
    hal.create_interface("virtual", "x")
    assert "auto_reset" not in seen                         # only PCAN takes it


def test_pcan_state_names_what_the_red_led_means():
    from ucando.hal import pcan_state
    assert pcan_state(0) == "ok"
    assert pcan_state(0x00008) == "error-warning"           # BUSHEAVY / BUSWARNING: frames still go out
    assert pcan_state(0x00004) == "error-warning"           # BUSLIGHT
    assert pcan_state(0x40000) == "error-passive"
    assert pcan_state(0x00010) == "bus-off"
    assert pcan_state(0x00010 | 0x00008) == "bus-off"       # the worst condition wins
    assert pcan_state(0x00080) == "tx-full"


def test_recover_and_health_use_the_adapters_own_calls():
    from ucando.hal import PythonCANBackend

    class Pcan:
        resets = 0

        def reset(self):
            Pcan.resets += 1
            return True

        def status(self):
            return 0x00010

    b = PythonCANBackend.__new__(PythonCANBackend)
    b.config, b.bus = {"interface": "pcan"}, Pcan()
    assert b.recover() is True and Pcan.resets == 1
    assert b.health() == {"state": "bus-off", "code": 0x10}
    b.config, b.bus = {"interface": "virtual"}, object()    # no reset, no controller state
    assert b.recover() is False and b.health() is None
