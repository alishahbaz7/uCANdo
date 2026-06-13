"""Phase 4: rules engine, job scheduler, restbus simulation, scripting."""

import cantools

from canforge.jobs import JobRunner, _interval_s
from canforge.rules import RulesEngine
from canforge.scripting import ScriptContext, run_script
from canforge.simulation import RestbusSimulator


# ----- rules ---------------------------------------------------------------
def test_rule_edge_triggered_fires_once(storage):
    fired = []
    eng = RulesEngine(storage, send=None)
    eng._trigger_job = None
    eng.add("hi", "sig('A') > 10", {"type": "log", "message": "hot"})
    eng.on_values({"A": 5})      # below
    eng.on_values({"A": 15})     # rising edge -> fire
    eng.on_values({"A": 16})     # stays true -> no new fire
    eng.on_values({"A": 5})      # reset
    eng.on_values({"A": 20})     # rising again -> fire
    events = eng.table()["events"]
    assert len(events) == 2


def test_rule_transmit_action(storage):
    sent = []
    eng = RulesEngine(storage, send=lambda m: sent.append(m))
    eng.add("tx", "sig('Speed') > 100", {"type": "transmit", "id": 0x123, "data": "01 02"})
    eng.on_values({"Speed": 120})
    assert sent and sent[0].arbitration_id == 0x123
    assert bytes(sent[0].data) == b"\x01\x02"


def test_rules_persist(storage):
    RulesEngine(storage).add("r", "sig('X') > 1", {"type": "log"})
    # A fresh engine on the same storage reloads the rule.
    assert len(RulesEngine(storage).table()["rules"]) == 1


# ----- jobs ----------------------------------------------------------------
def test_interval_parse():
    assert _interval_s("every:30") == 30.0
    assert _interval_s("") is None


def test_job_run_now_dispatches_handler(storage):
    runner = JobRunner(storage)
    runner.register_handler("scan", lambda spec: {"ok": True, "did": spec.get("n", 0)})
    job = runner.add_job("s", "scan", spec={"n": 7})
    res = runner.run_now(job["id"])
    assert res["ok"] and res["did"] == 7
    assert runner.get_job(job["id"])["last_run"] is not None


def test_job_unknown_kind(storage):
    runner = JobRunner(storage)
    job = runner.add_job("x", "nope")
    assert runner.run_now(job["id"])["ok"] is False


# ----- restbus -------------------------------------------------------------
def _two_msg_db():
    db = cantools.database.Database()
    for fid, name in [(0x100, "A"), (0x200, "B")]:
        db.messages.append(cantools.database.can.Message(
            frame_id=fid, name=name, length=8, signals=[], is_extended_frame=False))
    db.refresh()
    return db


def test_restbus_loads_and_transmits():
    sent = []
    sim = RestbusSimulator(lambda m: sent.append(m))
    st = sim.load_db(_two_msg_db())
    assert st["messages"] == 2
    sim.start()
    import time
    time.sleep(0.3)
    sim.stop()
    ids = {m.arbitration_id for m in sent}
    assert {0x100, 0x200} <= ids


# ----- scripting -----------------------------------------------------------
def test_script_send_and_log():
    sent = []
    ctx = ScriptContext(send=lambda m: sent.append(m), latest=lambda k, d=None: 42 if k == "RPM" else d)
    res = run_script("ctx.send(0x10, '01 02')\nctx.log('rpm', ctx.latest('RPM'))", ctx)
    assert res["ok"]
    assert sent[0].arbitration_id == 0x10
    assert "rpm 42" in res["logs"][0]


def test_script_blocks_import():
    res = run_script("import os", ScriptContext())
    assert res["ok"] is False
    assert "error" in res and res["error"]
