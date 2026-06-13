"""Headless CLI smoke tests (virtual bus, no hardware)."""

import os

from canforge.cli import main


def test_cli_log_records_file(tmp_path):
    out = str(tmp_path / "cap")
    rc = main(["--channel", f"cli-{os.getpid()}", "log", "--seconds", "0.5", "--out", out])
    assert rc == 0
    assert os.path.exists(out + ".asc")
    assert os.path.getsize(out + ".asc") > 0


def test_cli_identify_runs(capsys):
    rc = main(["--channel", f"cliid-{os.getpid()}", "identify", "--seconds", "0.5"])
    assert rc == 0
    # It should have observed traffic and printed something (matches or "no match").
    assert capsys.readouterr().out.strip() != ""
