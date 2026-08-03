"""Vehicle Spy 3 (Intrepid neoVI) CAN trace CSV import — see canforge/vspy.py."""

from canforge import vspy
from canforge.reverse import load_log_frames

# A trimmed real capture: metadata + Network Description + the 3 alternate
# header rows + data rows including short-DLC frames (1/2/3/6 bytes) that
# exercise the "blank past DLC" convention.
SAMPLE = """Vehicle Spy 3 Bus Traffic File
Save Date,7/04/2026
Save Time,12:39:38 pm
Start Date,7/04/2026
Start Time,12:27:07 pm
System Time,101206748
Notes,Buffer Save Count,1

Network Description,Hardware,Network,Protocol,Baud Rate
HS CAN,Default,HS CAN,CAN,500000,
LIN,Default,LIN,LIN,10417,



Line,Abs Time(Sec),Rel Time (Sec),Status,Er,Tx,Description,Network,Node,ID,Cycle,Ch,B1-256,Dyn,Symbol Type,Strt-PPI-NULL-Sync-Res,H-CRC,CRC,Tframe,Tss Length,Value,Trigger,Signals
Line,Abs Time(Sec),Rel Time (Sec),Status,Er,Tx,Description,Network,Node,Arb ID,Remote,Xtd,B1,B2,B3,B4,B5,B6,B7,B8,Value,Trigger,Signals
Line,Abs Time(Sec),Rel Time (Sec),Status,Er,Tx,Description,Network,Node,PT,Trgt,Src,B1,B2,B3,B4,B5,B6,B7,B8,Value,Trigger,Signals
1,739.6553467512131,0,67371008,F,F,HS CAN $1B2,HS CAN,,1B2,F,F,00,00,00,00,00,00,00,00,,,
4,739.6560813188553,0.0002380609512329102,321057462681600,F,F,HS CAN $94,HS CAN,,94,F,F,00,06,26,00,40,75,44,0A,,,
9,739.6572635173798,0.0001959800720214844,67371008,F,F,HS CAN $169,HS CAN,,169,F,F,3B,11,40,F7,14,00,,,,,
15,739.6586256027222,0.0001360177993774414,67371008,F,F,HS CAN $1F2,HS CAN,,1F2,F,F,20,00,,,,,,,,,
19,739.659485578537,0.0001159906387329102,67371008,F,F,HS CAN $40A,HS CAN,,40A,F,F,03,,,,,,,,,,
20,739.6596395969391,0.0001540184020996094,67371008,F,F,HS CAN $41F,HS CAN,,41F,F,F,02,70,01,,,,,,,,
21,739.6659953594208,0.006355762481689453,316659416170496,F,F,HS CAN $94,HS CAN,,94,F,F,00,06,26,00,40,74,44,0A,,,
"""


def test_is_vspy_csv():
    assert vspy.is_vspy_csv(SAMPLE)
    assert not vspy.is_vspy_csv("VERSION \"\"\nBO_ 1 X: 8 Vector__XXX")


def test_parse_frames_count_and_order():
    frames = vspy.parse_frames(SAMPLE)
    assert len(frames) == 7
    assert [f["id_hex"] for f in frames] == ["1B2", "94", "169", "1F2", "40A", "41F", "94"]
    assert frames[0]["timestamp"] == 739.6553467512131
    assert all(f["network"] == "HS CAN" and not f["is_extended"] for f in frames)


def test_short_dlc_frames_inferred_from_populated_columns():
    # id 94 appears twice in the sample; find(...) always returns the first.
    find = lambda id_hex: next(f for f in vspy.parse_frames(SAMPLE) if f["id_hex"] == id_hex)
    assert find("40A")["data"] == bytes([0x03])                       # 1 byte
    assert find("1F2")["data"] == bytes([0x20, 0x00])                 # 2 bytes
    assert find("41F")["data"] == bytes([0x02, 0x70, 0x01])           # 3 bytes
    assert find("169")["data"] == bytes.fromhex("3B1140F71400")       # 6 bytes
    assert find("94")["data"] == bytes.fromhex("000626004075440A")    # 8 bytes


def test_to_frames_by_id_matches_reverse_shape():
    frames = vspy.parse_frames(SAMPLE)
    by_id = vspy.to_frames_by_id(frames)
    assert (0x94, False) in by_id
    bucket = by_id[(0x94, False)]
    assert bucket["payloads"] == [
        bytes.fromhex("000626004075440A"), bytes.fromhex("000626004074440A")]
    assert bucket["timestamps"] == [739.6560813188553, 739.6659953594208]


def test_load_log_frames_dispatches_to_vspy(tmp_path):
    p = tmp_path / "capture.csv"
    p.write_text(SAMPLE, encoding="utf-8")
    frames = load_log_frames(str(p))
    assert (0x1B2, False) in frames
    assert frames[(0x94, False)]["payloads"][0] == bytes.fromhex("000626004075440A")


def test_log_catalogue_and_trace_endpoints():
    from fastapi.testclient import TestClient
    from canforge.server import app
    c = TestClient(app)
    up = c.post("/api/upload", files={"file": ("mg6.csv", SAMPLE.encode(), "text/csv")}).json()
    assert up["ok"]
    path = up["path"]

    cat = c.post("/api/log/catalogue", json={"path": path}).json()
    assert cat["ok"]
    ids = {m["id_hex"]: m for m in cat["messages"]}
    assert ids["94"]["count"] == 2
    assert ids["94"]["ext"] is False
    assert set(ids) == {"1B2", "94", "169", "1F2", "40A", "41F"}

    tr = c.post("/api/log/trace", json={"path": path, "id": 0x94, "ext": False}).json()
    assert tr["ok"] and len(tr["frames"]) == 2
    assert tr["frames"][0]["data"] == "000626004075440A"
    assert tr["frames"][0]["label"] == "739.656"

    miss = c.post("/api/log/trace", json={"path": path, "id": 0x999, "ext": False}).json()
    assert not miss["ok"]


def test_bus_event_rows_are_skipped():
    """Vehicle Spy interleaves adapter status rows among the frames.

    They are numbered like data rows and sit on a CAN network, but the *Arb ID*
    column holds free text (``CAN Rx/Tx REGS - TEC: 0 - REC: 1``) rather than
    hex. Real captures from the MG Windsor charging session contain these, and
    they used to crash the parser on ``int(id_hex, 16)``.
    """
    with_event = SAMPLE.replace(
        "19,739.659485578537,0.0001159906387329102,67371008,F,F,HS CAN $40A,HS CAN,,40A,F,F,03,,,,,,,,,,",
        "18,739.6594,0.00011,562950020792833,T,F,CAN Bus Event,HS CAN,,"
        "CAN Rx/Tx REGS - TEC: 0 - REC: 1,F,F,00,01,00,,,,,,,,\n"
        "19,739.659485578537,0.0001159906387329102,67371008,F,F,HS CAN $40A,HS CAN,,40A,F,F,03,,,,,,,,,,",
    )
    frames = vspy.parse_frames(with_event)
    # the bus-event row is dropped; every real frame still survives, in order
    assert len(frames) == 7
    assert [f["id_hex"] for f in frames] == ["1B2", "94", "169", "1F2", "40A", "41F", "94"]
    assert vspy.parse_frames(with_event) == vspy.parse_frames(SAMPLE)


def test_load_log_frames_ignores_non_can_network_rows():
    lin_row = SAMPLE.replace(
        "1,739.6553467512131,0,67371008,F,F,HS CAN $1B2,HS CAN,,1B2,F,F,00,00,00,00,00,00,00,00,,,",
        "1,739.6553467512131,0,67371008,F,F,HS CAN $1B2,HS CAN,,1B2,F,F,00,00,00,00,00,00,00,00,,,\n"
        "2,739.6554,0,0,F,F,LIN $05,LIN,,05,0,,,,,,,,,,,",
    )
    frames = vspy.parse_frames(lin_row)
    assert not any(f["network"] == "LIN" for f in frames)
