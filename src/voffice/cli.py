"""Entry point CLI voffice."""

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

DEFAULT_CONFIG = {
    "server": {"port": 8787, "poll_interval_seconds": 3},
    "status": {"working_max_seconds": 90, "idle_max_seconds": 900, "agent_ttl_hours": 24},
    "rooms": {"rename": {}, "hidden": []},
}

DEFAULT_DB_PATH = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> dict:
    config = {section: dict(values) for section, values in DEFAULT_CONFIG.items()}
    source = path or Path("voffice.toml")
    if not source.exists():
        return config
    with open(source, "rb") as f:
        raw = tomllib.load(f)
    for section, values in raw.items():
        if section in config and isinstance(values, dict):
            config[section].update(values)
    return config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voffice", description="Dashboard kantor buat agent ZCode"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="Jalankan server dashboard")
    p_run.add_argument("--port", type=int, default=None, help="Override port (default 8787)")
    p_run.add_argument("--no-open", action="store_true", help="Jangan buka browser otomatis")
    p_run.add_argument("--db", default=None, help="Override path db ZCode")
    sub.add_parser("test", help="Jalankan pytest")
    p_snap = sub.add_parser("snapshot", help="Print JSON snapshot sekali ke stdout")
    p_snap.add_argument("--db", default=None, help="Override path db ZCode")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = load_config()
    if args.command == "run":
        return cmd_run(args, config)
    if args.command == "test":
        return cmd_test()
    if args.command == "snapshot":
        return cmd_snapshot(args, config)
    return 1


def cmd_run(args, config: dict) -> int:
    from voffice.collector import Collector
    from voffice.server import run_server

    db_path = args.db or str(DEFAULT_DB_PATH)
    if args.port is not None:
        config["server"]["port"] = args.port
    collector = Collector(db_path, config)
    collector.start()
    static_dir = Path(__file__).parent / "static"
    print(f"voidlight-office di http://127.0.0.1:{config['server']['port']} (db: {db_path})")
    run_server(collector, config, static_dir, db_path=db_path, open_browser=not args.no_open)
    return 0


def cmd_test() -> int:
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(PROJECT_ROOT))
    return result.returncode


def cmd_snapshot(args, config: dict) -> int:
    from voffice.collector import load_snapshot

    db_path = args.db or str(DEFAULT_DB_PATH)
    snap = load_snapshot(db_path, config)
    print(json.dumps(snap))
    return 0
