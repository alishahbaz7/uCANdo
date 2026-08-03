"""CanLogger capture, stats, taps and the snapshot contract."""

import can

from ucando.contracts import check_snapshot
from ucando.hal import create_interface
from ucando.logger import CanLogger
from tests.conftest import wait_until


def test_logger_captures_and_aggregates(vchannel, sender):
    iface = create_interface("virtual", vchannel)
    logger = CanLogger(iface)
    logger.start()
    try:
        for i in range(5):
            sender.send(can.Message(arbitration_id=0x200, data=bytes([i]), is_extended_id=False))
        assert wait_until(lambda: logger.snapshot()["total"] >= 5)
        snap = logger.snapshot()
        assert snap["unique_ids"] == 1
        ids = {s["id_hex"]: s for s in snap["ids"]}
        assert "200" in ids
        assert ids["200"]["count"] >= 5
    finally:
        logger.stop()
        iface.close()


def test_snapshot_satisfies_contract(vchannel):
    iface = create_interface("virtual", vchannel)
    logger = CanLogger(iface)
    logger.start()
    try:
        assert check_snapshot(logger.snapshot()) == []
    finally:
        logger.stop()
        iface.close()


def test_taps_fire_outside_lock(vchannel, sender):
    seen = []
    iface = create_interface("virtual", vchannel)
    logger = CanLogger(iface, taps=[seen.append])
    logger.start()
    try:
        sender.send(can.Message(arbitration_id=0x321, data=b"\xAA", is_extended_id=False))
        assert wait_until(lambda: len(seen) >= 1)
        assert seen[0].arbitration_id == 0x321
    finally:
        logger.stop()
        iface.close()


def test_clear_resets_stats(vchannel, sender):
    iface = create_interface("virtual", vchannel)
    logger = CanLogger(iface)
    logger.start()
    try:
        sender.send(can.Message(arbitration_id=0x10, data=b"\x00", is_extended_id=False))
        assert wait_until(lambda: logger.snapshot()["total"] >= 1)
        logger.clear()
        snap = logger.snapshot()
        assert snap["total"] == 0
        assert snap["unique_ids"] == 0
    finally:
        logger.stop()
        iface.close()
