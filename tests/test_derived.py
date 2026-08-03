"""Computed signals and alarms."""

import pytest

from ucando.derived import AlarmMonitor, ComputedSignals, safe_eval


def test_safe_eval_math_and_sig():
    assert safe_eval("sig('a') * 2 + 1", {"a": 10}) == 21
    assert safe_eval("sqrt(sig('x'))", {"x": 9}) == 3


def test_safe_eval_blocks_builtins():
    with pytest.raises(Exception):
        safe_eval("__import__('os').system('echo hi')", {})


def test_computed_skips_missing_and_nonnumeric():
    c = ComputedSignals()
    c.set([{"name": "P", "expr": "sig('V') * sig('I')"},
           {"name": "bad", "expr": "sig('missing') + 1"}])
    out = c.evaluate({"V": 12.0, "I": 2.0})
    assert out == {"P": 24.0}            # 'bad' skipped (missing -> None + 1 errors)


def test_alarm_trips_and_clears():
    a = AlarmMonitor()
    a.set([{"name": "Overspeed", "key": "Speed", "max": 100}])
    a.evaluate({"Speed": 120})
    snap = a.snapshot()
    assert snap["active_count"] == 1
    assert snap["alarms"][0]["count"] == 1
    a.evaluate({"Speed": 50})
    assert a.snapshot()["active_count"] == 0
    a.evaluate({"Speed": 130})           # re-trip increments count
    assert a.snapshot()["alarms"][0]["count"] == 2


def test_alarm_min_bound():
    a = AlarmMonitor()
    a.set([{"key": "Volt", "min": 11.0}])
    a.evaluate({"Volt": 10.5})
    assert a.snapshot()["active_count"] == 1
