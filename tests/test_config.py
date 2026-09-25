from voffice.cli import load_config, DEFAULT_CONFIG


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_config() == {
        "server": {"port": 8787, "poll_interval_seconds": 3},
        "status": {"working_max_seconds": 90, "idle_max_seconds": 900, "agent_ttl_hours": 24},
        "rooms": {"rename": {}, "hidden": []},
    }


def test_overrides_merge_per_key(tmp_path):
    f = tmp_path / "voffice.toml"
    f.write_text(
        '[server]\nport = 9000\n'
        '[status]\nworking_max_seconds = 60\n'
        '[rooms]\nrename = { teraflow = "TF" }\nhidden = ["zcode-workspace"]\n',
        encoding="utf-8",
    )
    config = load_config(f)
    assert config["server"]["port"] == 9000
    assert config["server"]["poll_interval_seconds"] == 3
    assert config["status"]["working_max_seconds"] == 60
    assert config["status"]["idle_max_seconds"] == 900
    assert config["rooms"]["rename"] == {"teraflow": "TF"}
    assert config["rooms"]["hidden"] == ["zcode-workspace"]


def test_unknown_sections_ignored(tmp_path):
    f = tmp_path / "voffice.toml"
    f.write_text('[typos]\nfoo = 1\n[status]\nworking_max_seconds = 30\n')
    config = load_config(f)
    assert "typos" not in config
    assert config["status"]["working_max_seconds"] == 30


def test_default_config_shape():
    assert DEFAULT_CONFIG["rooms"]["rename"] == {}
