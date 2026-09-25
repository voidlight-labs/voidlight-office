"""Entry point CLI voffice."""

import argparse
import tomllib
from pathlib import Path

DEFAULT_CONFIG = {
    "server": {"port": 8787, "poll_interval_seconds": 3},
    "status": {"working_max_seconds": 90, "idle_max_seconds": 900, "agent_ttl_hours": 24},
    "rooms": {"rename": {}, "hidden": []},
}


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
    _build_parser().parse_args(argv)
    return 0
