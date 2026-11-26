"""Release and dev copies run side by side (user skill utility-ui §11)."""
import socket

import main
from ucando import channel


def test_release_and_dev_default_to_different_ports():
    assert channel.DEFAULT_PORT["release"] == 8765        # the address the packaged README gives
    assert channel.DEFAULT_PORT["dev"] != channel.DEFAULT_PORT["release"]


def test_a_source_run_is_the_dev_channel():
    assert channel.CHANNEL == "dev"                        # tests never run frozen


def test_probe_reports_a_free_port_as_free():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                              # free again: nothing listens
    assert main.probe("127.0.0.1", port) is None


def test_probe_tells_another_program_from_ucando():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        # something holds the port but answers no /api/info → "another program"
        assert main.probe("127.0.0.1", srv.getsockname()[1]) == {}
    finally:
        srv.close()
