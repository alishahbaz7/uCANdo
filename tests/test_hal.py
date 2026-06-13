"""HAL factory and the virtual backend."""

import can
import pytest

from canforge.hal import BACKENDS, CANInterface, create_interface


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
