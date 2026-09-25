import json
import subprocess
from types import SimpleNamespace

import pytest

from conftest import sess
from voffice.cli import main

NOW = 1_790_373_040_121


def test_snapshot_command_prints_json(make_db, capsys, tmp_path, monkeypatch):
    path = make_db(
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW - 1000)]
    )
    monkeypatch.chdir(tmp_path)  # tanpa voffice.toml → default config
    rc = main(["snapshot", "--db", str(path)])
    out = capsys.readouterr().out
    snap = json.loads(out)
    assert rc == 0
    assert snap["version"] == 1
    assert snap["rooms"][0]["name"] == "teraflow"


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "voffice" in capsys.readouterr().out


def test_test_command_runs_pytest(monkeypatch):
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert main(["test"]) == 0
    assert calls["argv"][1:3] == ["-m", "pytest"]
    assert calls["cwd"] is not None
