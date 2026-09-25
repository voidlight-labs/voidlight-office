# Voidlight Office Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard lokal yang membaca db ZCode read-only dan menampilkan "kantor" top-down: ruangan per project, agent per sesi, activity feed, dan strip usage global, di-refresh tiap 3 detik.

**Architecture:** Tiga komponen lokal: Collector (background thread, tick 3 detik, baca SQLite read-only, bangun snapshot JSON via fungsi murni), Server (FastAPI + uvicorn, serve static + `GET /api/snapshot`), Frontend (satu file HTML vanilla JS, poll tiap 3 detik). Semua kecerdasan agregasi di collector; frontend dumb.

**Tech Stack:** Python 3.12+, sqlite3 stdlib, tomllib stdlib, FastAPI, uvicorn, pytest; frontend vanilla JS + inline SVG.

**Spec:** `docs/superpowers/specs/2026-09-26-voidlight-office-design.md` (baca bersama plan ini; plan berargumen dari spec).

## Interpretasi Spec (pin keputusan, hasil verifikasi ke db asli)

Bagian ini menambal celah/ambiguitas spec. Kolom db sudah diverifikasi langsung ke `C:\Users\khayren\.zcode\cli\db\db.sqlite`.

1. **Argumen tool tidak tersimpan di db.** Contoh spec "Bash: npm test (2s)" tidak mungkin, karena `tool_usage` tidak punya kolom argumen. Format baris "lagi ngapain" dipatok: tool jalan → `"Bash (jalan)"`, tool selesai → `"Bash (2s)"`.
2. **Fallback tanpa tool call:** turn terakhir `completed_at IS NULL` (in flight) → `"mikir..."`; turn terakhir sudah selesai → `"nunggu input"`; tidak ada keduanya → `null`.
3. **Status merah (error):** dari turn terakhir sesi (urut `started_at` terbesar); merah jika `error_type` terisi ATAU `cancelled_by_user = 1`. Prioritas di atas warna lain.
4. **Timestamp aktivitas sesi** = max dari `session.time_updated` dan semua baris `COALESCE(completed_at, started_at)` di turn_usage/model_usage/tool_usage.
5. **Nilai status aktual di db:** `turn_usage.status` dan `model_usage.status` = `completed | cancelled | error`; `tool_usage.status` = `completed | error | running`. Mapping feed & panel: `completed → "ok"` (hijau), `error → "error"` (merah), lainnya → `"running"` (kuning).
6. **short_name:** huruf pertama nama ruangan FINAL (setelah rename) di-uppercase + nomor urut per ruangan, urut `time_created` sesi ascending, subagent ikut dinomori dalam urutan yang sama. Contoh: "teraflow" → T1, T2; "voidlight" → V1.
7. **Config rooms:** `rename` key = nama hasil derivasi (sebelum rename); `hidden` dicek terhadap nama hasil derivasi (sebelum rename).
8. **Token agent** = sum `turn_usage.computed_total_tokens` sesi itu. **Usage global (`today_total`, `per_model`)** = dari `model_usage` semua sesi (tanpa filter visible), filter `started_at >= tengah malam lokal`.
9. **TTL:** sesi tampil jika aktivitas terakhirnya `>= now - agent_ttl_hours` (inklusif).
10. **Field tambahan di JSON** (di luar contoh shape spec, tapi diwajibkan fitur spec): room dapat `objective`, `tokens`, `last_activity` (dipakai sort, lalu dibuang sebelum serialize); agent dapat `turns` (10 terakhir), `tools` (10 terakhir), `models` (breakdown per model_id) untuk slide-over panel spec section 10 tanpa endpoint tambahan.
11. **Sesi tanpa directory** masuk ruangan `"unknown"`; subagent yang parent-nya tidak visible dirender sebagai tile biasa.
12. **Config dibaca dari `./voffice.toml`** (working directory saat CLI dijalankan); tidak ada file berarti semua default.
13. **`session_target.status` dan kolom `active_run_*` tidak dipakai di V1** (YAGNI).

## Global Constraints

- Python `>= 3.12`; runtime deps: `fastapi>=0.115`, `uvicorn>=0.30`; dev deps: `pytest>=8.3`, `httpx>=0.27`.
- DB ZCode WAJIB dibuka read-only via URI `file:...?mode=ro` (`uri=True`). Tidak ada operasi tulis ke db ZCode di kode manapun.
- Path db default: `Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"`.
- Server bind `127.0.0.1:8787` (override via config/flag). Tidak ada auth, tidak ada akses remote.
- Semua timestamp epoch milidetik.
- Warna status: kerja `#22c55e`, idle `#eab308`, quiet `#64748b`, error `#ef4444`. Threshold default: working 90s, idle 900s, ttl 24 jam.
- Snapshot `version: 1`, bentuk JSON sesuai spec + field tambahan pin no. 10.
- Frontend: satu file `src/voffice/static/index.html`, vanilla JS, tanpa build step, tanpa framework.
- Copy UI bahasa Indonesia kasual, tanpa em dash (pakai hyphen atau tanda baca lain).
- Commit message pakai conventional commits (`feat:`, `test:`, `chore:`, `docs:`).
- Test command: `python -m pytest` dari root project; `voffice test` harus hijau tanpa db ZCode asli.

---

### Task 1: Scaffold package + config loader

**Files:**
- Create: `pyproject.toml`
- Create: `voffice.toml`
- Create: `src/voffice/__init__.py`
- Create: `src/voffice/cli.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: tidak ada (task pertama).
- Produces: `voffice.cli.load_config(path: Path | None = None) -> dict` (None = baca `./voffice.toml`, file hilang = default); `voffice.cli.main(argv: list[str] | None = None) -> int` (stub, diisi penuh di Task 8); struktur config dict: `{"server": {"port", "poll_interval_seconds"}, "status": {"working_max_seconds", "idle_max_seconds", "agent_ttl_hours"}, "rooms": {"rename": dict, "hidden": list}}`.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'voffice'`

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "voidlight-office"
version = "0.1.0"
description = "Dashboard lokal buat memantau agent ZCode"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.115", "uvicorn>=0.30"]

[project.optional-dependencies]
dev = ["pytest>=8.3", "httpx>=0.27"]

[project.scripts]
voffice = "voffice.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
voffice = ["static/*"]
```

`voffice.toml` (di root, di-commit sebagai contoh config):

```toml
# Config opsional voidlight-office. Hapus/rename file ini kalau mau full default.
[server]
port = 8787
poll_interval_seconds = 3

[status]
working_max_seconds = 90        # aktivitas lebih muda dari nilai ini = hijau (kerja)
idle_max_seconds = 900          # 15 menit; lebih tua dari nilai ini = abu (quiet)
agent_ttl_hours = 24            # sesi tanpa aktivitas selebih ini tidak tampil

[rooms]
rename = { }                    # key = nama ruangan hasil derivasi, value = nama baru
hidden = []                     # daftar nama ruangan (hasil derivasi) yang disembunyikan
```

`src/voffice/__init__.py`:

```python
__version__ = "0.1.0"
```

`src/voffice/cli.py`:

```python
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
```

- [ ] **Step 4: Install package editable + run test to verify it passes**

Run:
```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_config.py -v
```
Expected: PASS semua. Lalu `voffice --help` tampil tanpa error.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml voffice.toml src/voffice/__init__.py src/voffice/cli.py tests/test_config.py
git commit -m "feat: scaffold package + config loader"
```

---

### Task 2: Fixture db sintetis (conftest)

**Files:**
- Create: `tests/conftest.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Consumes: tidak ada.
- Produces: pytest fixtures yang dipakai semua task berikutnya: `make_db` (factory, return `Path` db) dan `cfg` (dict config default). Helper builder row di module `conftest`: `sess(...)`, `target(...)`, `turn(...)`, `model(...)`, `tool(...)` - semuanya return dict sesuai kolom subset schema. Test meng-import via `from conftest import sess, turn, ...`.

- [ ] **Step 1: Write the failing test**

`tests/test_collector.py` (baru; akan terus bertambah di task berikutnya):

```python
import sqlite3

NOW = 1_790_373_040_121
MID = NOW - 7 * 3_600_000  # "tengah malam" buat test usage
HOME = "C:\\Users\\khayren"
STATUS_CFG = {"working_max_seconds": 90, "idle_max_seconds": 900, "agent_ttl_hours": 24}


def test_make_db_creates_readable_schema(make_db):
    path = make_db(
        sessions=[dict(id="sess_a", directory="C:/work/proj", time_created=NOW, time_updated=NOW)],
        turns=[dict(session_id="sess_a", turn_id="t1", status="completed", started_at=NOW, output_tokens=10)],
    )
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM session")]
    con.close()
    assert rows == [
        {"id": "sess_a", "parent_id": None, "directory": "C:/work/proj", "title": None,
         "time_created": NOW, "time_updated": NOW, "time_archived": None}
    ]


def test_cfg_fixture(cfg):
    assert cfg["status"]["working_max_seconds"] == 90
    assert cfg["rooms"]["rename"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collector.py -v`
Expected: FAIL dengan `fixture 'make_db' not found`

- [ ] **Step 3: Write minimal implementation**

`tests/conftest.py`:

```python
import sqlite3

import pytest

SCHEMA = """
CREATE TABLE session (
  id TEXT PRIMARY KEY,
  parent_id TEXT,
  directory TEXT,
  title TEXT,
  time_created INTEGER,
  time_updated INTEGER,
  time_archived INTEGER
);
CREATE TABLE session_target (
  session_id TEXT,
  target_id TEXT,
  objective TEXT,
  status TEXT,
  token_budget INTEGER,
  tokens_used INTEGER,
  time_created INTEGER,
  time_updated INTEGER
);
CREATE TABLE turn_usage (
  session_id TEXT,
  turn_id TEXT,
  status TEXT,
  started_at INTEGER,
  completed_at INTEGER,
  output_tokens INTEGER,
  computed_total_tokens INTEGER,
  error_type TEXT,
  cancelled_by_user INTEGER
);
CREATE TABLE model_usage (
  session_id TEXT,
  model_id TEXT,
  provider_id TEXT,
  started_at INTEGER,
  completed_at INTEGER,
  computed_total_tokens INTEGER,
  error_type TEXT,
  cancelled_by_user INTEGER
);
CREATE TABLE tool_usage (
  session_id TEXT,
  turn_id TEXT,
  tool_name TEXT,
  status TEXT,
  started_at INTEGER,
  completed_at INTEGER,
  duration_ms INTEGER,
  exit_code INTEGER,
  error_type TEXT,
  cancelled_by_user INTEGER
);
"""

SESSION_COLS = ["id", "parent_id", "directory", "title", "time_created", "time_updated", "time_archived"]
TARGET_COLS = ["session_id", "target_id", "objective", "status", "token_budget", "tokens_used", "time_created", "time_updated"]
TURN_COLS = ["session_id", "turn_id", "status", "started_at", "completed_at", "output_tokens", "computed_total_tokens", "error_type", "cancelled_by_user"]
MODEL_COLS = ["session_id", "model_id", "provider_id", "started_at", "completed_at", "computed_total_tokens", "error_type", "cancelled_by_user"]
TOOL_COLS = ["session_id", "turn_id", "tool_name", "status", "started_at", "completed_at", "duration_ms", "exit_code", "error_type", "cancelled_by_user"]


def sess(id="sess_a", directory="C:/work/proj", parent_id=None, title=None,
         created=0, updated=None, archived=None):
    return {"id": id, "parent_id": parent_id, "directory": directory, "title": title,
            "time_created": created, "time_updated": updated if updated is not None else created,
            "time_archived": archived}


def target(session_id="sess_a", objective="objek test", status="active",
           token_budget=0, tokens_used=0, time_updated=0):
    return {"session_id": session_id, "target_id": "tgt_1", "objective": objective,
            "status": status, "token_budget": token_budget, "tokens_used": tokens_used,
            "time_created": time_updated, "time_updated": time_updated}


def turn(session_id="sess_a", turn_id="t1", status="completed", started_at=0,
         completed_at=None, output_tokens=0, computed_total_tokens=0,
         error_type=None, cancelled_by_user=0):
    return {"session_id": session_id, "turn_id": turn_id, "status": status,
            "started_at": started_at, "completed_at": completed_at,
            "output_tokens": output_tokens, "computed_total_tokens": computed_total_tokens,
            "error_type": error_type, "cancelled_by_user": cancelled_by_user}


def model(session_id="sess_a", model_id="GLM-5.3-Flash", provider_id="zai",
          started_at=0, completed_at=None, computed_total_tokens=0,
          error_type=None, cancelled_by_user=0):
    return {"session_id": session_id, "model_id": model_id, "provider_id": provider_id,
            "started_at": started_at, "completed_at": completed_at,
            "computed_total_tokens": computed_total_tokens, "error_type": error_type,
            "cancelled_by_user": cancelled_by_user}


def tool(session_id="sess_a", turn_id="t1", tool_name="Bash", status="completed",
         started_at=0, completed_at=None, duration_ms=None, exit_code=0,
         error_type=None, cancelled_by_user=0):
    return {"session_id": session_id, "turn_id": turn_id, "tool_name": tool_name,
            "status": status, "started_at": started_at, "completed_at": completed_at,
            "duration_ms": duration_ms, "exit_code": exit_code, "error_type": error_type,
            "cancelled_by_user": cancelled_by_user}


@pytest.fixture
def make_db(tmp_path):
    def _make(name="db.sqlite", drop_tables=(), sessions=(), targets=(),
              turns=(), models=(), tools=()):
        path = tmp_path / name
        con = sqlite3.connect(path)
        con.executescript(SCHEMA)
        for table in drop_tables:
            con.execute(f"DROP TABLE {table}")

        def insert(table, columns, rows):
            if not rows:
                return
            cols = ", ".join(columns)
            marks = ", ".join("?" * len(columns))
            con.executemany(
                f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                [[row.get(c) for c in columns] for row in rows],
            )

        insert("session", SESSION_COLS, sessions)
        insert("session_target", TARGET_COLS, targets)
        insert("turn_usage", TURN_COLS, turns)
        insert("model_usage", MODEL_COLS, models)
        insert("tool_usage", TOOL_COLS, tools)
        con.commit()
        con.close()
        return path

    return _make


@pytest.fixture
def cfg():
    return {
        "server": {"port": 8787, "poll_interval_seconds": 3},
        "status": {"working_max_seconds": 90, "idle_max_seconds": 900, "agent_ttl_hours": 24},
        "rooms": {"rename": {}, "hidden": []},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collector.py tests/test_config.py -v`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_collector.py
git commit -m "test: fixture db sintetis subset schema ZCode"
```

---

### Task 3: Helper murni - nama ruangan, status, durasi, aktivitas

**Files:**
- Create: `src/voffice/collector.py`
- Modify: `tests/test_collector.py`

**Interfaces:**
- Consumes: tidak ada (fungsi murni).
- Produces (semua di `voffice.collector`):
  - `room_name_for_directory(directory: str | None, home: str) -> str` - `"unknown"` jika kosong; `"zcode-workspace"` jika di bawah `<home>/.zcode/workspace/`; else komponen folder terakhir.
  - `format_duration(ms: int | None) -> str` - `"2s"`, `"45s"`, `"1m"`, `"1m 30s"`, `"1h 5m"`, `"?"` untuk None.
  - `compute_activity_ts(time_updated: int | None, turns: list, models: list, tools: list) -> int | None` - max dari time_updated dan `COALESCE(completed_at, started_at)` tiap baris.
  - `is_last_turn_errored(turns: list) -> bool` - turn terakhir (started_at terbesar) punya `error_type` atau `cancelled_by_user`.
  - `derive_status(last_activity_ms: int | None, errored: bool, now_ms: int, working_max_seconds: int, idle_max_seconds: int) -> tuple[str, str]` - return `(status, status_detail)`.

- [ ] **Step 1: Write the failing test**

Tambah ke `tests/test_collector.py`:

```python
import pytest

from voffice.collector import (
    compute_activity_ts,
    derive_status,
    format_duration,
    is_last_turn_errored,
    room_name_for_directory,
)


@pytest.mark.parametrize("directory,expected", [
    ("C:\\Users\\khayren\\voidlight\\teraflow", "teraflow"),
    ("C:/Users/khayren/voidlight/teraflow", "teraflow"),
    ("C:\\Users\\khayren\\.zcode\\workspace\\default", "zcode-workspace"),
    ("C:/Users/khayren/.zcode/workspace", "zcode-workspace"),
    ("C:\\Users\\khayren\\.zcode\\workspace\\default\\sub", "zcode-workspace"),
    ("D:\\proj\\lain\\yang-ini", "yang-ini"),
    (None, "unknown"),
    ("", "unknown"),
])
def test_room_name_for_directory(directory, expected):
    assert room_name_for_directory(directory, HOME) == expected


@pytest.mark.parametrize("ms,expected", [
    (None, "?"),
    (0, "0s"),
    (2000, "2s"),
    (45000, "45s"),
    (60000, "1m"),
    (90000, "1m 30s"),
    (3900000, "1h 5m"),
])
def test_format_duration(ms, expected):
    assert format_duration(ms) == expected


def test_compute_activity_takes_max():
    turns = [{"started_at": 1000, "completed_at": 5000}]
    models = [{"started_at": 7000, "completed_at": None}]
    tools = [{"started_at": 3000, "completed_at": 4000}]
    assert compute_activity_ts(2000, turns, models, tools) == 7000


def test_compute_activity_prefers_completed_over_started():
    turns = [{"started_at": 1000, "completed_at": 5000}]
    assert compute_activity_ts(None, turns, [], []) == 5000


def test_compute_activity_empty_returns_none():
    assert compute_activity_ts(None, [], [], []) is None


def test_is_last_turn_errored():
    assert is_last_turn_errored([{"started_at": 1, "error_type": "api", "cancelled_by_user": 0}]) is True
    assert is_last_turn_errored([{"started_at": 1, "error_type": None, "cancelled_by_user": 1}]) is True
    earlier = {"started_at": 1, "error_type": "api", "cancelled_by_user": 0}
    later = {"started_at": 2, "error_type": None, "cancelled_by_user": 0}
    assert is_last_turn_errored([earlier, later]) is False
    assert is_last_turn_errored([]) is False


@pytest.mark.parametrize("age_s,expected_status,expected_label", [
    (89, "kerja", "kerja"),
    (90, "idle", "idle 1m"),
    (91, "idle", "idle 1m"),
    (840, "idle", "idle 14m"),
    (900, "idle", "idle 15m"),
    (960, "quiet", "diam 16m"),
    (3700, "quiet", "diam 1h"),
])
def test_derive_status_boundaries(age_s, expected_status, expected_label):
    assert derive_status(NOW - age_s * 1000, False, NOW, 90, 900) == (expected_status, expected_label)


def test_derive_status_error_has_priority():
    assert derive_status(NOW - 1000, True, NOW, 90, 900) == ("error", "error")


def test_derive_status_no_activity():
    assert derive_status(None, False, NOW, 90, 900) == ("quiet", "diam")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collector.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'voffice.collector'`

- [ ] **Step 3: Write minimal implementation**

`src/voffice/collector.py`:

```python
"""Collector: query db ZCode read-only + fungsi murni agregasi snapshot."""

WORKSPACE_DIRNAME = ".zcode/workspace"


def room_name_for_directory(directory: str | None, home: str | None) -> str:
    if not directory:
        return "unknown"
    norm = directory.replace("\\", "/").rstrip("/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return "unknown"
    if home:
        home_norm = home.replace("\\", "/").rstrip("/").lower()
        ws = home_norm + "/" + WORKSPACE_DIRNAME
        low = norm.lower()
        if low == ws or low.startswith(ws + "/"):
            return "zcode-workspace"
    return parts[-1]


def format_duration(ms: int | None) -> str:
    if ms is None:
        return "?"
    total_s = int(round(ms / 1000))
    if total_s < 60:
        return f"{total_s}s"
    m, s = divmod(total_s, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _row_ts(row: dict) -> int | None:
    return row.get("completed_at") or row.get("started_at")


def compute_activity_ts(time_updated: int | None, turns: list, models: list, tools: list) -> int | None:
    candidates = [time_updated] if time_updated is not None else []
    for rows in (turns, models, tools):
        candidates += [ts for ts in (_row_ts(r) for r in rows) if ts is not None]
    return max(candidates) if candidates else None


def is_last_turn_errored(turns: list) -> bool:
    if not turns:
        return False
    last = max(turns, key=lambda r: r.get("started_at") or 0)
    return last.get("error_type") is not None or bool(last.get("cancelled_by_user"))


def derive_status(last_activity_ms: int | None, errored: bool, now_ms: int,
                  working_max_seconds: int, idle_max_seconds: int) -> tuple[str, str]:
    if errored:
        return "error", "error"
    if last_activity_ms is None:
        return "quiet", "diam"
    age_s = max(0, (now_ms - last_activity_ms) // 1000)
    if age_s < working_max_seconds:
        return "kerja", "kerja"
    if age_s <= idle_max_seconds:
        return "idle", f"idle {max(1, age_s // 60)}m"
    if age_s < 3600:
        return "quiet", f"diam {age_s // 60}m"
    return "quiet", f"diam {age_s // 3600}h"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collector.py -v`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add src/voffice/collector.py tests/test_collector.py
git commit -m "feat: helper murni nama ruangan, status, durasi, aktivitas"
```

---

### Task 4: build_agent (dict per agent)

**Files:**
- Modify: `src/voffice/collector.py`
- Modify: `tests/test_collector.py`

**Interfaces:**
- Consumes: `compute_activity_ts`, `is_last_turn_errored`, `derive_status`, `format_duration` dari Task 3; helper row dari conftest.
- Produces:
  - `USAGE_STATUS_MAP = {"completed": "ok", "error": "error"}` (default `"running"`) dan `TOOL_STATUS_MAP` sama isinya, keduanya konstanta module-level `voffice.collector`.
  - `current_tool_line(tools: list, turns: list) -> str | None`.
  - `build_agent(session: dict, turns: list, models: list, tools: list, targets: list, *, now_ms: int, status_cfg: dict) -> dict` - target terakhir = `time_updated` terbesar. Dict field: `id, title, short_name (None, diisi Task 5), parent_id, status, status_detail, last_activity, current_tool, model, tokens, tool_calls, sparkline (max 20 output_tokens urut started_at), objective, target_used, target_budget, turns (10 terakhir: {at, output_tokens, status}), tools (10 terakhir: {tool, duration_ms, status, at}), models ({model_id: tokens}), subagents ([] di sini, diisi Task 5)`.

- [ ] **Step 1: Write the failing test**

Tambah ke `tests/test_collector.py`:

```python
from conftest import model, sess, target, tool, turn
from voffice.collector import build_agent, current_tool_line


def test_build_agent_full():
    s = sess(created=NOW - 5000, updated=NOW - 30_000)
    turns = [
        turn(started_at=NOW - 60_000, completed_at=NOW - 59_000, output_tokens=100, computed_total_tokens=250),
        turn(turn_id="t2", started_at=NOW - 40_000, completed_at=NOW - 30_000, output_tokens=300, computed_total_tokens=150),
    ]
    models = [model(started_at=NOW - 60_000, computed_total_tokens=250),
              model(model_id="GLM-4.6", started_at=NOW - 40_000, computed_total_tokens=150)]
    tools = [tool(tool_name="Bash", started_at=NOW - 35_000, completed_at=NOW - 33_000, duration_ms=2000)]
    targets = [target(objective="migrasi auth", token_budget=130000, tokens_used=80000, time_updated=NOW)]
    agent = build_agent(s, turns, models, tools, targets, now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["id"] == "sess_a"
    assert agent["status"] == "kerja"
    assert agent["status_detail"] == "kerja"
    assert agent["last_activity"] == NOW - 30_000
    assert agent["current_tool"] == "Bash (2s)"
    assert agent["model"] == "GLM-4.6"
    assert agent["tokens"] == 400
    assert agent["tool_calls"] == 1
    assert agent["sparkline"] == [100, 300]
    assert agent["objective"] == "migrasi auth"
    assert agent["target_used"] == 80000
    assert agent["target_budget"] == 130000
    assert agent["short_name"] is None
    assert agent["subagents"] == []
    assert agent["models"] == {"GLM-5.3-Flash": 250, "GLM-4.6": 150}


def test_build_agent_current_tool_running():
    tools = [tool(tool_name="Edit", status="running", started_at=NOW - 10_000)]
    agent = build_agent(sess(), tools, [], [], [], now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["current_tool"] == "Edit (jalan)"


def test_current_tool_line_variants():
    in_flight = [turn(started_at=NOW - 5000, completed_at=None)]
    done = [turn(started_at=NOW - 5000, completed_at=NOW - 1000)]
    assert current_tool_line([], in_flight) == "mikir..."
    assert current_tool_line([], done) == "nunggu input"
    assert current_tool_line([], []) is None


def test_build_agent_no_tool_no_turn():
    agent = build_agent(sess(updated=NOW - 1000), [], [], [], [], now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["current_tool"] is None


def test_build_agent_sparkline_caps_20_and_orders_by_started_at():
    turns = [turn(turn_id=f"t{i}", started_at=NOW - (30 - i) * 1000, output_tokens=i) for i in range(25)]
    agent = build_agent(sess(), turns, [], [], [], now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["sparkline"] == list(range(5, 25))


def test_build_agent_uses_latest_target():
    old = target(objective="lama", token_budget=100, tokens_used=10, time_updated=1000)
    new = target(objective="baru", token_budget=200, tokens_used=20, time_updated=2000)
    agent = build_agent(sess(), [], [], [], [old, new], now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["objective"] == "baru"
    assert agent["target_budget"] == 200


def test_build_agent_no_target_hides_budget():
    agent = build_agent(sess(), [], [], [], [], now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["objective"] is None
    assert agent["target_budget"] == 0


def test_build_agent_error_status():
    turns = [turn(started_at=NOW - 10_000, completed_at=NOW - 9_000, error_type="api_error")]
    agent = build_agent(sess(), turns, [], [], [], now_ms=NOW, status_cfg=STATUS_CFG)
    assert agent["status"] == "error"
    assert agent["status_detail"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collector.py -v`
Expected: FAIL dengan `ImportError: cannot import name 'build_agent'`

- [ ] **Step 3: Write minimal implementation**

Tambah ke `src/voffice/collector.py`:

```python
USAGE_STATUS_MAP = {"completed": "ok", "error": "error"}
TOOL_STATUS_MAP = {"completed": "ok", "error": "error"}


def _status_of(raw: str | None) -> str:
    return USAGE_STATUS_MAP.get(raw, "running")


def current_tool_line(tools: list, turns: list) -> str | None:
    if tools:
        last = max(tools, key=lambda r: r.get("started_at") or 0)
        name = last.get("tool_name") or "?"
        if last.get("status") == "running":
            return f"{name} (jalan)"
        return f"{name} ({format_duration(last.get('duration_ms'))})"
    if turns:
        last = max(turns, key=lambda r: r.get("started_at") or 0)
        if last.get("completed_at") is None:
            return "mikir..."
        return "nunggu input"
    return None


def build_agent(session: dict, turns: list, models: list, tools: list, targets: list,
                *, now_ms: int, status_cfg: dict) -> dict:
    turns = sorted(turns, key=lambda r: r.get("started_at") or 0)
    models = sorted(models, key=lambda r: r.get("started_at") or 0)
    tools = sorted(tools, key=lambda r: r.get("started_at") or 0)
    targets = sorted(targets, key=lambda r: r.get("time_updated") or 0)
    target = targets[-1] if targets else None

    activity_ts = compute_activity_ts(session.get("time_updated"), turns, models, tools)
    errored = is_last_turn_errored(turns)
    status, detail = derive_status(
        activity_ts, errored, now_ms,
        status_cfg["working_max_seconds"], status_cfg["idle_max_seconds"],
    )

    per_model: dict = {}
    for m in models:
        mid = m.get("model_id") or "unknown"
        per_model[mid] = per_model.get(mid, 0) + (m.get("computed_total_tokens") or 0)

    return {
        "id": session["id"],
        "title": session.get("title"),
        "short_name": None,
        "parent_id": session.get("parent_id"),
        "status": status,
        "status_detail": detail,
        "last_activity": activity_ts,
        "current_tool": current_tool_line(tools, turns),
        "model": models[-1].get("model_id") if models else None,
        "tokens": sum(t.get("computed_total_tokens") or 0 for t in turns),
        "tool_calls": len(tools),
        "sparkline": [t.get("output_tokens") or 0 for t in turns[-20:]],
        "objective": target.get("objective") if target else None,
        "target_used": (target.get("tokens_used") or 0) if target else 0,
        "target_budget": (target.get("token_budget") or 0) if target else 0,
        "turns": [
            {"at": t.get("started_at"), "output_tokens": t.get("output_tokens") or 0,
             "status": _status_of(t.get("status"))}
            for t in turns[-10:]
        ],
        "tools": [
            {"tool": t.get("tool_name"), "duration_ms": t.get("duration_ms"),
             "status": TOOL_STATUS_MAP.get(t.get("status"), "running"),
             "at": t.get("started_at")}
            for t in tools[-10:]
        ],
        "models": per_model,
        "subagents": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collector.py -v`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add src/voffice/collector.py tests/test_collector.py
git commit -m "feat: build_agent agregasi per sesi"
```

---

### Task 5: build_snapshot (rooms, nesting, feed, usage, meta)

**Files:**
- Modify: `src/voffice/collector.py`
- Modify: `tests/test_collector.py`

**Interfaces:**
- Consumes: semua helper Task 3-4; fixture `cfg`.
- Produces:
  - `_sorted_index(rows: list, sort_key: str) -> dict[session_id, list[dict]]` (internal).
  - `_flatten_agents(agents: list) -> list` (internal; termasuk subagent rekursif).
  - `build_snapshot(sessions, targets, turns, models, tools, *, now_ms: int, midnight_ms: int, home: str, rooms_cfg: dict, status_cfg: dict, db_path: str, errors: list | None = None, partial: bool = False) -> dict` - snapshot penuh `{"version": 1, "generated_at", "meta", "rooms", "activity", "usage"}`.
  - Room dict: `{"name", "directory", "objective", "tokens", "agents"}` (sort ruangan by aktivitas terbaru desc; `last_activity` dipakai sort lalu dibuang).
  - Activity row: `{"room", "agent", "tool", "status", "duration_ms", "at"}` max 30, terbaru di atas.
  - Usage: `{"today_total", "per_model": {model_id: tokens}, "working_count"}` (working_count termasuk subagent berstatus kerja).

- [ ] **Step 1: Write the failing test**

Tambah ke `tests/test_collector.py`:

```python
from voffice.collector import build_snapshot


def snap(sessions=(), targets=(), turns=(), models=(), tools=(), rooms_cfg=None,
         now=NOW, midnight=MID, errors=None, partial=False):
    return build_snapshot(
        list(sessions), list(targets), list(turns), list(models), list(tools),
        now_ms=now, midnight_ms=midnight, home=HOME,
        rooms_cfg=rooms_cfg or {}, status_cfg=STATUS_CFG, db_path="db.sqlite",
        errors=errors, partial=partial,
    )


def test_snapshot_two_rooms_sorted_by_activity():
    s = snap(
        sessions=[
            sess("sess_a", directory="C:/w/teraflow", created=NOW - 1000, updated=NOW - 1000),
            sess("sess_b", directory="C:/w/voidlight", created=NOW - 500, updated=NOW - 500),
        ],
    )
    assert [r["name"] for r in s["rooms"]] == ["voidlight", "teraflow"]
    assert s["rooms"][0]["directory"] == "C:/w/voidlight"
    assert s["version"] == 1
    assert s["meta"] == {"db_path": "db.sqlite", "partial": False, "errors": []}


def test_snapshot_merges_same_last_component():
    s = snap(sessions=[
        sess("sess_a", directory="C:/a/proj", created=NOW, updated=NOW),
        sess("sess_b", directory="D:/b/proj", created=NOW, updated=NOW),
    ])
    assert len(s["rooms"]) == 1
    assert s["rooms"][0]["name"] == "proj"


def test_snapshot_rename_and_hidden():
    sessions = [
        sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW),
        sess("sess_b", directory="C:/Users/khayren/.zcode/workspace/default", created=NOW, updated=NOW),
    ]
    s = snap(sessions=sessions, rooms_cfg={"rename": {"teraflow": "TF"}, "hidden": ["zcode-workspace"]})
    # hidden dicek ke nama derivasi (sebelum rename): zcode-workspace hilang, teraflow tampil sebagai TF
    assert [r["name"] for r in s["rooms"]] == ["TF"]


def test_snapshot_hidden_by_derived_name():
    sessions = [sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW)]
    s = snap(sessions=sessions, rooms_cfg={"hidden": ["teraflow"]})
    assert s["rooms"] == []


def test_snapshot_short_names_stable_by_created():
    s = snap(sessions=[
        sess("sess_a", directory="C:/w/teraflow", created=NOW - 2000, updated=NOW),
        sess("sess_b", directory="C:/w/teraflow", created=NOW - 1000, updated=NOW),
    ])
    names = {a["id"]: a["short_name"] for a in s["rooms"][0]["agents"]}
    assert names == {"sess_a": "T1", "sess_b": "T2"}


def test_snapshot_archived_and_ttl_filtered():
    s = snap(sessions=[
        sess("arch", directory="C:/w/teraflow", created=NOW, updated=NOW, archived=NOW),
        sess("old", directory="C:/w/teraflow", created=NOW - 25 * 3600 * 1000,
             updated=NOW - 25 * 3600 * 1000),
        sess("fresh", directory="C:/w/teraflow", created=NOW - 23 * 3600 * 1000,
             updated=NOW - 23 * 3600 * 1000),
    ])
    assert [a["id"] for a in s["rooms"][0]["agents"]] == ["fresh"]


def test_snapshot_subagent_nesting():
    s = snap(
        sessions=[
            sess("parent", directory="C:/w/teraflow", created=NOW - 3000, updated=NOW),
            sess("sub1", directory="C:/w/teraflow", parent_id="parent", created=NOW - 2000, updated=NOW),
            sess("sub2", directory="C:/w/teraflow", parent_id="parent", created=NOW - 1000, updated=NOW),
        ],
    )
    room = s["rooms"][0]
    assert [a["id"] for a in room["agents"]] == ["parent"]
    assert [a["id"] for a in room["agents"][0]["subagents"]] == ["sub1", "sub2"]


def test_snapshot_orphan_subagent_becomes_top_tile():
    s = snap(sessions=[
        sess("sub1", directory="C:/w/teraflow", parent_id="gone", created=NOW, updated=NOW),
    ])
    assert [a["id"] for a in s["rooms"][0]["agents"]] == ["sub1"]


def test_snapshot_room_tokens_and_objective_include_subagents():
    s = snap(
        sessions=[
            sess("parent", directory="C:/w/teraflow", created=NOW - 1000, updated=NOW),
            sess("sub1", directory="C:/w/teraflow", parent_id="parent", created=NOW, updated=NOW),
        ],
        turns=[
            turn(session_id="parent", turn_id="t1", started_at=NOW - 1000, completed_at=NOW - 900,
                 computed_total_tokens=400),
            turn(session_id="sub1", turn_id="t2", started_at=NOW - 500, completed_at=NOW - 400,
                 computed_total_tokens=600),
        ],
        targets=[target(objective="migrasi auth", time_updated=NOW - 10)],
    )
    room = s["rooms"][0]
    assert room["tokens"] == 1000
    assert room["objective"] == "migrasi auth"


def test_snapshot_activity_feed():
    s = snap(
        sessions=[
            sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW),
            sess("sess_b", directory="C:/w/voidlight", created=NOW, updated=NOW),
        ],
        tools=[
            tool(session_id="sess_a", tool_name="Bash", status="completed",
                 started_at=NOW - 3000, duration_ms=2000),
            tool(session_id="sess_b", tool_name="Edit", status="error",
                 started_at=NOW - 1000, duration_ms=500),
            tool(session_id="sess_a", tool_name="Read", status="running", started_at=NOW - 500),
        ],
    )
    feed = s["activity"]
    assert [(r["room"], r["agent"], r["tool"], r["status"]) for r in feed] == [
        ("teraflow", "T1", "Read", "running"),
        ("voidlight", "V1", "Edit", "error"),
        ("teraflow", "T1", "Bash", "ok"),
    ]
    assert feed[0]["duration_ms"] is None
    assert feed[1]["duration_ms"] == 500


def test_snapshot_activity_feed_limit_30():
    tools = [tool(session_id="sess_a", tool_name=f"T{i}", started_at=NOW - i * 1000)
             for i in range(35)]
    s = snap(sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW)],
             tools=tools)
    assert len(s["activity"]) == 30
    assert s["activity"][0]["tool"] == "T0"


def test_snapshot_usage_today_per_model_working_count():
    s = snap(
        sessions=[
            sess("kerja1", directory="C:/w/teraflow", created=NOW, updated=NOW),
            sess("idle1", directory="C:/w/voidlight", created=NOW, updated=NOW - 300_000),
        ],
        turns=[turn(session_id="kerja1", started_at=NOW - 1000, completed_at=NOW - 900)],
        models=[
            model(session_id="kerja1", model_id="GLM-5.3-Flash", started_at=MID + 1000,
                  computed_total_tokens=800),
            model(session_id="kerja1", model_id="GLM-5.3-Flash", started_at=MID + 2000,
                  computed_total_tokens=400),
            model(session_id="idle1", model_id="GLM-4.6", started_at=MID + 3000,
                  computed_total_tokens=200),
            model(session_id="idle1", model_id="GLM-4.6", started_at=MID - 1000,
                  computed_total_tokens=9999),  # sebelum tengah malam, harus terbuang
        ],
    )
    assert s["usage"]["today_total"] == 1400
    assert s["usage"]["per_model"] == {"GLM-5.3-Flash": 1200, "GLM-4.6": 200}
    assert s["usage"]["working_count"] == 1


def test_snapshot_working_count_includes_subagents():
    s = snap(
        sessions=[
            sess("parent", directory="C:/w/teraflow", created=NOW, updated=NOW),
            sess("sub1", directory="C:/w/teraflow", parent_id="parent", created=NOW, updated=NOW),
        ],
        turns=[turn(session_id="sub1", started_at=NOW - 1000, completed_at=NOW - 900)],
    )
    assert s["usage"]["working_count"] == 2


def test_snapshot_empty_db_still_valid():
    s = snap()
    assert s["rooms"] == []
    assert s["activity"] == []
    assert s["usage"] == {"today_total": 0, "per_model": {}, "working_count": 0}
    assert s["meta"]["partial"] is False


def test_snapshot_meta_errors_passed_through():
    s = snap(errors=["query tools gagal: no such table"], partial=True)
    assert s["meta"]["partial"] is True
    assert s["meta"]["errors"] == ["query tools gagal: no such table"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collector.py -v`
Expected: FAIL dengan `ImportError: cannot import name 'build_snapshot'` (test lain tetap PASS)

- [ ] **Step 3: Write minimal implementation**

Tambah ke `src/voffice/collector.py`:

```python
ACTIVITY_FEED_LIMIT = 30
SPARKLINE_TURNS = 20
PANEL_ROWS = 10


def _sorted_index(rows: list, sort_key: str) -> dict:
    idx: dict = {}
    for r in rows:
        idx.setdefault(r.get("session_id"), []).append(r)
    for lst in idx.values():
        lst.sort(key=lambda r: r.get(sort_key) or 0)
    return idx


def _flatten_agents(agents: list) -> list:
    out = []
    for a in agents:
        out.append(a)
        out.extend(_flatten_agents(a["subagents"]))
    return out


def build_snapshot(sessions, targets, turns, models, tools, *,
                   now_ms: int, midnight_ms: int, home: str,
                   rooms_cfg: dict, status_cfg: dict, db_path: str,
                   errors: list | None = None, partial: bool = False) -> dict:
    ttl_ms = status_cfg["agent_ttl_hours"] * 3_600_000
    session_turns = _sorted_index(turns, "started_at")
    session_models = _sorted_index(models, "started_at")
    session_tools = _sorted_index(tools, "started_at")
    session_targets = _sorted_index(targets, "time_updated")

    activity: dict = {}
    for s in sessions:
        activity[s["id"]] = compute_activity_ts(
            s.get("time_updated"),
            session_turns.get(s["id"], []),
            session_models.get(s["id"], []),
            session_tools.get(s["id"], []),
        )

    visible = [
        s for s in sessions
        if s.get("time_archived") is None
        and activity[s["id"]] is not None
        and activity[s["id"]] >= now_ms - ttl_ms
    ]
    visible_ids = {s["id"] for s in visible}

    grouped: dict = {}
    for s in visible:
        derived = room_name_for_directory(s.get("directory"), home)
        if derived in rooms_cfg.get("hidden", []):
            continue
        display = rooms_cfg.get("rename", {}).get(derived, derived)
        grouped.setdefault(display, []).append(s)

    room_dicts = []
    working_count = 0
    agent_by_id: dict = {}
    for display, members in grouped.items():
        members = sorted(members, key=lambda s: s.get("time_created") or 0)
        initial = display[:1].upper()
        for i, s in enumerate(members, start=1):
            agent = build_agent(
                s,
                session_turns.get(s["id"], []),
                session_models.get(s["id"], []),
                session_tools.get(s["id"], []),
                session_targets.get(s["id"], []),
                now_ms=now_ms, status_cfg=status_cfg,
            )
            agent["short_name"] = f"{initial}{i}"
            agent_by_id[s["id"]] = agent

        tops, subs = [], []
        for s in members:
            a = agent_by_id[s["id"]]
            if s.get("parent_id") is not None and s["parent_id"] in visible_ids:
                subs.append(a)
            else:
                tops.append(a)
        for a in subs:
            parent = agent_by_id.get(a["parent_id"])
            if parent is not None:
                parent["subagents"].append(a)

        everyone = _flatten_agents(tops)
        working_count += sum(1 for a in everyone if a["status"] == "kerja")

        objective, newest_target_at = None, -1
        for s in members:
            for t in session_targets.get(s["id"], []):
                if t.get("objective") and (t.get("time_updated") or 0) >= newest_target_at:
                    newest_target_at = t.get("time_updated") or 0
                    objective = t["objective"]

        newest = max(members, key=lambda s: activity[s["id"]] or 0)
        room_dicts.append({
            "name": display,
            "directory": newest.get("directory"),
            "objective": objective,
            "tokens": sum(a["tokens"] for a in everyone),
            "last_activity": max((a["last_activity"] or 0) for a in everyone),
            "agents": tops,
        })

    room_dicts.sort(key=lambda r: r["last_activity"], reverse=True)
    for r in room_dicts:
        r.pop("last_activity")

    feed = []
    for r in room_dicts:
        for a in _flatten_agents(r["agents"]):
            for t in session_tools.get(a["id"], []):
                feed.append({
                    "room": r["name"],
                    "agent": a["short_name"],
                    "tool": t.get("tool_name"),
                    "status": TOOL_STATUS_MAP.get(t.get("status"), "running"),
                    "duration_ms": t.get("duration_ms"),
                    "at": t.get("started_at"),
                })
    feed.sort(key=lambda r: r["at"] or 0, reverse=True)

    per_model: dict = {}
    for m in models:
        if (m.get("started_at") or 0) >= midnight_ms:
            mid = m.get("model_id") or "unknown"
            per_model[mid] = per_model.get(mid, 0) + (m.get("computed_total_tokens") or 0)

    return {
        "version": 1,
        "generated_at": now_ms,
        "meta": {"db_path": db_path, "partial": partial, "errors": errors or []},
        "rooms": room_dicts,
        "activity": feed[:ACTIVITY_FEED_LIMIT],
        "usage": {
            "today_total": sum(per_model.values()),
            "per_model": per_model,
            "working_count": working_count,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collector.py tests/test_config.py -v`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add src/voffice/collector.py tests/test_collector.py
git commit -m "feat: build_snapshot agregasi rooms, feed, usage"
```

---

### Task 6: DB reader + collector thread (read-only, fail soft)

**Files:**
- Modify: `src/voffice/collector.py`
- Modify: `tests/test_collector.py`

**Interfaces:**
- Consumes: `build_snapshot` (Task 5), `cfg` fixture.
- Produces:
  - `QUERIES: dict[str, str]` - 5 query SQL (sessions, targets, turns, models, tools), module-level.
  - `load_snapshot(db_path: str | Path, config: dict, now_ms: int | None = None) -> dict` - baca db read-only, hitung midnight lokal, kembalikan snapshot. db hilang / query gagal / db tak terbuka → snapshot valid dengan `meta.partial=True` + `meta.errors` terisi (fail soft, tidak raise).
  - `Collector(db_path, config, interval_seconds: float | None = None)` - `.start()`, `.stop()`, `.tick()`, `.snapshot() -> dict | None`. Thread daemon; loop `tick` tiap interval; exception di tick ditelan (snapshot lama dipertahankan).

- [ ] **Step 1: Write the failing test**

Tambah ke `tests/test_collector.py`:

```python
import time

from conftest import model, sess  # noqa: F401 (turn/tool/target diimpor di atas)
from voffice.collector import Collector, load_snapshot


def test_load_snapshot_from_fixture_db(make_db, cfg):
    path = make_db(
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW - 10_000)],
        turns=[turn(session_id="sess_a", started_at=NOW - 10_000, completed_at=NOW - 9_000,
                    output_tokens=50, computed_total_tokens=50)],
    )
    s = load_snapshot(path, cfg, now_ms=NOW)
    assert s["meta"]["partial"] is False
    assert s["meta"]["db_path"] == str(path)
    assert s["rooms"][0]["name"] == "teraflow"
    assert s["rooms"][0]["agents"][0]["tokens"] == 50


def test_load_snapshot_missing_db(tmp_path, cfg):
    s = load_snapshot(tmp_path / "nope.sqlite", cfg, now_ms=NOW)
    assert s["meta"]["partial"] is True
    assert any("db tidak ditemukan" in e for e in s["meta"]["errors"])
    assert s["rooms"] == []


def test_load_snapshot_schema_changed_partial(make_db, cfg):
    path = make_db(
        drop_tables=("tool_usage",),
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW - 1000)],
        turns=[turn(session_id="sess_a", started_at=NOW - 1000, completed_at=NOW - 900)],
    )
    s = load_snapshot(path, cfg, now_ms=NOW)
    assert s["meta"]["partial"] is True
    assert any("tools" in e for e in s["meta"]["errors"])
    assert s["rooms"][0]["agents"][0]["tool_calls"] == 0


def test_load_snapshot_empty_db(make_db, cfg):
    path = make_db()
    s = load_snapshot(path, cfg, now_ms=NOW)
    assert s["meta"]["partial"] is False
    assert s["rooms"] == []
    assert s["usage"]["today_total"] == 0


def test_collector_tick_stores_snapshot(make_db, cfg):
    path = make_db(
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW - 1000)]
    )
    c = Collector(path, cfg)
    assert c.snapshot() is None
    c.tick()
    assert c.snapshot()["rooms"][0]["name"] == "teraflow"


def test_collector_tick_fail_soft_on_missing_db(tmp_path, cfg):
    c = Collector(tmp_path / "nope.sqlite", cfg)
    c.tick()  # tidak boleh raise
    assert c.snapshot() is not None
    assert c.snapshot()["meta"]["partial"] is True


def test_collector_loop_integration(make_db, cfg):
    path = make_db(
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW - 1000)]
    )
    c = Collector(path, cfg, interval_seconds=0.05)
    c.start()
    deadline = time.time() + 2
    while c.snapshot() is None and time.time() < deadline:
        time.sleep(0.01)
    c.stop()
    assert c.snapshot() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collector.py -v -k "load_snapshot or collector"`
Expected: FAIL dengan `ImportError: cannot import name 'Collector'`

- [ ] **Step 3: Write minimal implementation**

Tambah ke `src/voffice/collector.py` (import di atas file: `import sqlite3`, `import threading`, `import time`, `from datetime import datetime`, `from pathlib import Path`):

```python
QUERIES = {
    "sessions": (
        "SELECT id, parent_id, directory, title, time_created, time_updated, time_archived "
        "FROM session"
    ),
    "targets": (
        "SELECT session_id, target_id, objective, status, token_budget, tokens_used, "
        "time_created, time_updated FROM session_target ORDER BY time_updated"
    ),
    "turns": (
        "SELECT session_id, turn_id, status, started_at, completed_at, output_tokens, "
        "error_type, cancelled_by_user FROM turn_usage ORDER BY started_at"
    ),
    "models": (
        "SELECT session_id, model_id, provider_id, started_at, completed_at, "
        "computed_total_tokens, error_type, cancelled_by_user FROM model_usage ORDER BY started_at"
    ),
    "tools": (
        "SELECT session_id, turn_id, tool_name, status, started_at, completed_at, duration_ms, "
        "error_type, cancelled_by_user FROM tool_usage ORDER BY started_at"
    ),
}


def _local_midnight_ms() -> int:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def load_snapshot(db_path, config: dict, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    db_path = str(db_path)
    errors: list[str] = []
    data: dict[str, list] = {}

    path = Path(db_path)
    con = None
    if not path.exists():
        errors.append(f"db tidak ditemukan: {db_path}")
    else:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        try:
            con = sqlite3.connect(uri, uri=True)
            con.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            errors.append(f"db tidak bisa dibuka: {db_path} ({exc})")

    if con is not None:
        try:
            for name, sql in QUERIES.items():
                try:
                    data[name] = [dict(row) for row in con.execute(sql).fetchall()]
                except sqlite3.Error as exc:
                    errors.append(f"query {name} gagal: {exc}")
        finally:
            con.close()

    return build_snapshot(
        data.get("sessions", []), data.get("targets", []), data.get("turns", []),
        data.get("models", []), data.get("tools", []),
        now_ms=now_ms, midnight_ms=_local_midnight_ms(), home=str(Path.home()),
        rooms_cfg=config["rooms"], status_cfg=config["status"], db_path=db_path,
        errors=errors, partial=bool(errors),
    )


class Collector:
    def __init__(self, db_path, config: dict, interval_seconds: float | None = None):
        self.db_path = db_path
        self.config = config
        self.interval = interval_seconds or config["server"]["poll_interval_seconds"]
        self._snapshot = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> dict | None:
        with self._lock:
            return self._snapshot

    def tick(self) -> None:
        try:
            snap = load_snapshot(self.db_path, self.config)
        except Exception:
            return  # fail soft: pertahankan snapshot terakhir
        with self._lock:
            self._snapshot = snap

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self.tick()
        while not self._stop.wait(self.interval):
            self.tick()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collector.py -v`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add src/voffice/collector.py tests/test_collector.py
git commit -m "feat: db reader read-only + collector thread fail soft"
```

---

### Task 7: FastAPI server

**Files:**
- Create: `src/voffice/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: holder protocol `.snapshot() -> dict | None` (dipenuhi `Collector` dari Task 6).
- Produces:
  - `create_app(holder, static_dir: Path, open_url: str | None = None) -> FastAPI` - route `GET /api/snapshot` (200 JSON snapshot, 503 jika holder belum punya snapshot) + mount static di `/` (html=True). `open_url` mengaktifkan auto-open browser via lifespan (Timer 1.5s).
  - `run_server(holder, config: dict, static_dir: Path, open_browser: bool = True) -> None` - blocking; uvicorn di `127.0.0.1:config["server"]["port"]`.

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from voffice.server import create_app


class FakeHolder:
    def __init__(self, snap):
        self._snap = snap

    def snapshot(self):
        return self._snap


def test_snapshot_endpoint(tmp_path):
    app = create_app(FakeHolder({"version": 1, "rooms": []}), tmp_path)
    with TestClient(app) as client:
        res = client.get("/api/snapshot")
        assert res.status_code == 200
        assert res.json() == {"version": 1, "rooms": []}


def test_snapshot_not_ready_returns_503(tmp_path):
    app = create_app(FakeHolder(None), tmp_path)
    client = TestClient(app)
    res = client.get("/api/snapshot")
    assert res.status_code == 503


def test_serves_static_index(tmp_path):
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    app = create_app(FakeHolder(None), tmp_path)
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "<html>ok</html>" in res.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'voffice.server'`

- [ ] **Step 3: Write minimal implementation**

`src/voffice/server.py`:

```python
"""Server: serve frontend statis + endpoint snapshot."""

import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


def create_app(holder, static_dir: Path, open_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if open_url:
            threading.Timer(1.5, webbrowser.open, [open_url]).start()
        yield

    app = FastAPI(title="voidlight-office", lifespan=lifespan)

    @app.get("/api/snapshot")
    def get_snapshot():
        snap = holder.snapshot()
        if snap is None:
            return JSONResponse(status_code=503, content={"error": "snapshot belum siap"})
        return snap

    # route /api didaftarkan lebih dulu supaya tidak tertelan mount "/"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def run_server(holder, config: dict, static_dir: Path, open_browser: bool = True) -> None:
    port = config["server"]["port"]
    url = f"http://127.0.0.1:{port}"
    app = create_app(holder, static_dir, open_url=url if open_browser else None)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server.py -v`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add src/voffice/server.py tests/test_server.py
git commit -m "feat: server FastAPI snapshot + static"
```

---

### Task 8: CLI lengkap (run / test / snapshot)

**Files:**
- Modify: `src/voffice/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `Collector` + `load_snapshot` (Task 6), `run_server` (Task 7).
- Produces:
  - `DEFAULT_DB_PATH: Path = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"` (module-level `voffice.cli`).
  - `main(argv) -> int`: `run` (start collector + server, buka browser kecuali `--no-open`; `--port`/`--db` override config), `test` (subprocess `python -m pytest -q` dari root project), `snapshot` (print `json.dumps(snapshot)` ke stdout, return 0).
  - Static dir = `Path(__file__).parent / "static"`; project root = `Path(__file__).resolve().parents[2]`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL, `test_snapshot_command_prints_json` dan `test_test_command_runs_pytest` (main stub tidak print/dispatch); `test_help_exits_zero` PASS dari Task 1.

- [ ] **Step 3: Write minimal implementation**

Ganti bagian bawah `src/voffice/cli.py` (setelah `_build_parser`) dan tambah import di atas: `import json`, `import subprocess`, `import sys`:

```python
DEFAULT_DB_PATH = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    run_server(collector, config, static_dir, open_browser=not args.no_open)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ -v`
Expected: PASS semua (semua test file).

- [ ] **Step 5: Smoke manual `voffice snapshot` (tanpa browser)**

Run: `voffice snapshot --db "C:/Users/khayren/.zcode/cli/db/db.sqlite" | python -c "import json,sys; s=json.load(sys.stdin); print(s['meta']); print(len(s['rooms']), 'rooms'); print(s['usage'])"`
Expected: JSON valid, `meta.partial` false, rooms > 0, usage terisi.

- [ ] **Step 6: Commit**

```bash
git add src/voffice/cli.py tests/test_cli.py
git commit -m "feat: CLI run/test/snapshot"
```

---

### Task 9: Frontend index.html (mission control, soft rooms, rich tiles)

**Files:**
- Create: `src/voffice/static/index.html`

**Interfaces:**
- Consumes: `GET /api/snapshot` (Task 7); shape JSON snapshot Task 5-6 (room: name/directory/objective/tokens/agents; agent: id/title/short_name/status/status_detail/current_tool/model/tokens/tool_calls/sparkline/objective/target_used/target_budget/turns/tools/models/subagents; activity; usage; meta).
- Produces: halaman dashboard lengkap; perilaku: poll 3s, umur data, banner (partial / server mati), klik agent = slide-over, klik header ruangan = filter feed, Escape tutup panel. Tidak ada unit test (spec section 12: frontend diuji manual).

- [ ] **Step 1: Write the full file**

`src/voffice/static/index.html`:

```html
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voidlight Office</title>
<style>
  :root {
    --bg: #0b1220; --panel: #101a30; --panel-hi: #16233f; --inset: #0e1626;
    --line: #2c3d63; --text: #dbe4f5; --muted: #7d8db0; --dim: #475569;
    --green: #22c55e; --yellow: #eab308; --gray: #64748b; --red: #ef4444; --accent: #38bdf8;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 13px/1.45 system-ui, "Segoe UI", sans-serif; }
  .topbar { display: flex; align-items: center; gap: 18px; padding: 8px 16px; background: var(--panel-hi); border-bottom: 1px solid var(--line); }
  .brand { font-weight: 700; letter-spacing: 2px; font-size: 12px; }
  .stat { color: var(--muted); font-size: 12px; }
  .stat b { color: var(--text); }
  .age { margin-left: auto; color: var(--muted); font-size: 12px; }
  .banner { padding: 6px 16px; font-size: 12px; display: none; }
  .banner.show { display: block; }
  .banner.warn { background: #3a2f12; color: var(--yellow); }
  .banner.err { background: #3a1418; color: var(--red); }
  main { display: grid; grid-template-columns: 1fr 320px; gap: 14px; padding: 14px; }
  .rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; align-content: start; }
  .room { background: linear-gradient(160deg, var(--panel-hi), var(--panel)); border: 1px solid var(--line); border-radius: 14px; padding: 14px; }
  .room-head { cursor: pointer; display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
  .room-head:hover .room-name { color: var(--accent); }
  .room-head.active .room-name { color: var(--accent); }
  .room-name { font-weight: 600; }
  .room-obj { color: var(--muted); font-size: 11px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .room-tok { color: var(--muted); font-size: 11px; flex-shrink: 0; }
  .agents { display: flex; flex-direction: column; gap: 6px; }
  .agent { display: flex; gap: 10px; align-items: center; background: var(--inset); border-radius: 8px; padding: 8px; cursor: pointer; }
  .agent:hover { outline: 1px solid var(--line); }
  .avatar { width: 30px; height: 30px; border-radius: 50%; border: 2px solid var(--gray); background: #22314f; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; flex-shrink: 0; }
  .a-main { flex: 1; min-width: 0; }
  .a-tool { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .a-meta { color: var(--muted); font-size: 11px; }
  .subs { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 10px; color: var(--muted); background: var(--inset); border-radius: 999px; padding: 3px 8px; cursor: pointer; }
  .chip i { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
  .bar { height: 6px; background: #22314f; border-radius: 3px; overflow: hidden; margin-top: 10px; }
  .bar > div { height: 100%; border-radius: 3px; }
  .feed { background: var(--inset); border: 1px solid var(--line); border-radius: 14px; padding: 10px; max-height: calc(100vh - 90px); overflow: auto; align-self: start; }
  .feed h3 { margin: 0 0 8px; font-size: 11px; letter-spacing: 1px; color: var(--muted); text-transform: uppercase; }
  .feed-title { color: var(--accent); }
  .feed-row { display: flex; gap: 8px; align-items: flex-start; font-size: 11.5px; padding: 4px 0; color: var(--muted); border-bottom: 1px solid #14203a; }
  .feed-row .who { color: var(--text); flex-shrink: 0; }
  .dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; display: inline-block; }
  .empty { color: var(--dim); padding: 60px 20px; text-align: center; }
  .slideover { position: fixed; top: 0; right: 0; height: 100%; width: 400px; max-width: 90vw; background: var(--panel-hi); border-left: 1px solid var(--accent); padding: 16px; overflow: auto; transform: translateX(105%); transition: transform .15s; z-index: 10; }
  .slideover.open { transform: none; }
  .slideover h2 { margin: 0 0 10px; font-size: 15px; display: flex; align-items: center; gap: 8px; }
  .slideover .close { position: absolute; top: 10px; right: 12px; background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }
  .kv { color: var(--muted); font-size: 12px; margin: 3px 0; }
  .kv b { color: var(--text); }
  .list { margin-top: 14px; }
  .list h4 { margin: 0 0 6px; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
  .list-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; padding: 4px 0; color: var(--muted); border-bottom: 1px solid #14203a; }
</style>
</head>
<body>
  <div class="topbar">
    <span class="brand">VOIDLIGHT OFFICE</span>
    <span class="stat" id="stat-working"></span>
    <span class="stat" id="stat-tokens"></span>
    <span class="age" id="age"></span>
  </div>
  <div class="banner" id="banner"></div>
  <main>
    <div class="rooms" id="rooms"></div>
    <div class="feed"><h3 id="feed-title">Activity</h3><div id="feed-rows"></div></div>
  </main>
  <div class="slideover" id="slideover"></div>
<script>
"use strict";

const COLORS = { kerja: "#22c55e", idle: "#eab308", quiet: "#64748b", error: "#ef4444" };
const STATUS_DOT = { ok: "var(--green)", error: "var(--red)", running: "var(--yellow)" };
const STATE = { snap: null, ok: true, filterRoom: null, selected: null };
const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtTokens(n) {
  if (n == null) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1000) return Math.round(n / 1000) + "k";
  return String(n);
}

function fmtAge(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return `diperbarui ${s}s lalu`;
  const m = Math.round(s / 60);
  if (m < 60) return `diperbarui ${m}m lalu (data beku)`;
  return `diperbarui ${Math.round(m / 60)}j lalu (data beku)`;
}

function sparkline(values, color) {
  if (!values || values.length < 2) return "";
  const w = 60, h = 18, max = Math.max(...values, 1);
  const pts = values
    .map((v, i) => `${(i / (values.length - 1) * w).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`)
    .join(" ");
  return `<svg width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
}

function agentRow(a) {
  const c = COLORS[a.status] || COLORS.quiet;
  const tool = a.current_tool || a.title || "tanpa aktivitas";
  const bar = a.target_budget > 0
    ? `<div class="bar"><div style="width:${Math.min(100, Math.round(a.target_used / a.target_budget * 100))}%;background:${c}"></div></div>`
    : "";
  return `<div class="agent" onclick="openAgent('${esc(a.id)}')">
    <div class="avatar" style="border-color:${c}">${esc(a.short_name)}</div>
    <div class="a-main">
      <div class="a-tool">${esc(tool)}</div>
      <div class="a-meta">${esc(a.status_detail)} &middot; ${esc(a.model ?? "-")} &middot; ${fmtTokens(a.tokens)} tok &middot; ${a.tool_calls} tools</div>
      ${bar}
    </div>
    ${sparkline(a.sparkline, c)}
  </div>`;
}

function roomCard(r) {
  const active = STATE.filterRoom === r.name ? "active" : "";
  const agents = r.agents.map(agentRow).join("");
  const chips = r.agents
    .filter((a) => a.subagents.length)
    .map((a) => `<span class="chip" onclick="openAgent('${esc(a.id)}')">${esc(a.short_name)} + ${a.subagents.length} sub
      ${a.subagents.map((s) => `<i style="background:${COLORS[s.status] || COLORS.quiet}"></i>`).join("")}</span>`)
    .join("");
  return `<div class="room">
    <div class="room-head ${active}" onclick="toggleFilter('${esc(r.name)}')">
      <span class="room-name">${esc(r.name)}</span>
      <span class="room-obj">${esc(r.objective ?? "")}</span>
      <span class="room-tok">${fmtTokens(r.tokens)} tok</span>
    </div>
    <div class="agents">${agents || '<div class="kv">kosong</div>'}</div>
    ${chips ? `<div class="subs">${chips}</div>` : ""}
  </div>`;
}

function renderRooms() {
  const rooms = STATE.snap?.rooms || [];
  if (!rooms.length) {
    const meta = STATE.snap?.meta;
    const msg = meta && (meta.errors || []).length ? meta.errors.join("; ") : "belum ada aktivitas";
    $("rooms").innerHTML = `<div class="empty">${esc(msg)}</div>`;
    return;
  }
  const list = STATE.filterRoom ? rooms.filter((r) => r.name === STATE.filterRoom) : rooms;
  $("rooms").innerHTML = list.map(roomCard).join("");
}

function renderFeed() {
  $("feed-title").textContent = STATE.filterRoom ? `Activity: ${STATE.filterRoom}` : "Activity";
  const rows = (STATE.snap?.activity || [])
    .filter((x) => !STATE.filterRoom || x.room === STATE.filterRoom);
  $("feed-rows").innerHTML = rows.map((x) => {
    const c = STATUS_DOT[x.status] || "var(--gray)";
    const d = x.duration_ms != null ? ` (${Math.round(x.duration_ms / 1000)}s)` : "";
    return `<div class="feed-row"><span class="dot" style="background:${c}"></span>
      <span class="who">${esc(x.room)}/${esc(x.agent)}</span><span>${esc(x.tool)}${d}</span></div>`;
  }).join("") || '<div class="kv">belum ada aktivitas</div>';
}

function renderTopbar() {
  const u = STATE.snap?.usage;
  $("stat-working").innerHTML = u ? `<b>${u.working_count}</b> agent kerja` : "";
  if (!u) { $("stat-tokens").innerHTML = ""; return; }
  const models = Object.entries(u.per_model || {})
    .map(([m, n]) => `${esc(m)} ${fmtTokens(n)}`).join(" &middot; ");
  $("stat-tokens").innerHTML = `<b>${fmtTokens(u.today_total)}</b> tok today${models ? " &middot; " + models : ""}`;
}

function renderBanner() {
  const b = $("banner");
  const meta = STATE.snap?.meta;
  if (meta && meta.partial) {
    b.className = "banner warn show";
    b.textContent = "data parsial: " + (meta.errors || []).join("; ");
  } else if (!STATE.ok) {
    b.className = "banner err show";
    b.textContent = STATE.snap
      ? "server tidak terjangkau, menampilkan data terakhir"
      : "menunggu server /api/snapshot...";
  } else {
    b.className = "banner";
  }
}

function findAgent(id) {
  for (const r of STATE.snap?.rooms || []) {
    for (const a of r.agents) {
      if (a.id === id) return a;
      const sub = a.subagents.find((s) => s.id === id);
      if (sub) return sub;
    }
  }
  return null;
}

function openAgent(id) { STATE.selected = id; renderSlideover(); }
function closeAgent() { STATE.selected = null; renderSlideover(); }
function toggleFilter(name) { STATE.filterRoom = STATE.filterRoom === name ? null : name; render(); }

function renderSlideover() {
  const el = $("slideover");
  const a = STATE.selected && findAgent(STATE.selected);
  if (!a) { el.className = "slideover"; el.innerHTML = ""; return; }
  const c = COLORS[a.status] || COLORS.quiet;
  const turns = (a.turns || []).slice().reverse().map((t) =>
    `<div class="list-row"><span><span class="dot" style="background:${STATUS_DOT[t.status] || "var(--gray)"}"></span> ${new Date(t.at).toLocaleTimeString()}</span><span>${fmtTokens(t.output_tokens)} tok</span></div>`
  ).join("");
  const tools = (a.tools || []).slice().reverse().map((t) =>
    `<div class="list-row"><span>${esc(t.tool)}</span><span>${t.status}${t.duration_ms != null ? " &middot; " + Math.round(t.duration_ms / 1000) + "s" : ""}</span></div>`
  ).join("");
  const models = Object.entries(a.models || {})
    .map(([m, n]) => `<div class="list-row"><span>${esc(m)}</span><span>${fmtTokens(n)} tok</span></div>`).join("");
  const pct = a.target_budget > 0 ? Math.min(100, Math.round(a.target_used / a.target_budget * 100)) : null;
  el.innerHTML = `
    <button class="close" onclick="closeAgent()">x</button>
    <h2><span class="avatar" style="border-color:${c}">${esc(a.short_name)}</span>${esc(a.title || a.short_name)}</h2>
    <div class="kv">status: <b>${esc(a.status_detail)}</b></div>
    <div class="kv">model: ${esc(a.model ?? "-")}</div>
    <div class="kv">token total: <b>${fmtTokens(a.tokens)}</b> &middot; ${a.tool_calls} tool calls</div>
    ${a.objective ? `<div class="kv">objective: ${esc(a.objective)}</div>` : ""}
    ${pct != null ? `<div class="bar" style="max-width:220px"><div style="width:${pct}%;background:${c}"></div></div>
      <div class="kv">${fmtTokens(a.target_used)} / ${fmtTokens(a.target_budget)} tok (${pct}%)</div>` : ""}
    <div class="list"><h4>Turn terakhir</h4>${turns || '<div class="kv">kosong</div>'}</div>
    <div class="list"><h4>Tool calls</h4>${tools || '<div class="kv">kosong</div>'}</div>
    <div class="list"><h4>Per model</h4>${models || '<div class="kv">kosong</div>'}</div>`;
  el.className = "slideover open";
}

function renderAge() { $("age").textContent = fmtAge(STATE.snap?.generated_at); }

function render() {
  renderTopbar();
  renderBanner();
  renderRooms();
  renderFeed();
  renderSlideover();
  renderAge();
}

async function tick() {
  try {
    const res = await fetch("/api/snapshot");
    if (!res.ok) throw new Error("http " + res.status);
    STATE.snap = await res.json();
    STATE.ok = true;
  } catch (e) {
    STATE.ok = false;
  }
  if (STATE.selected && !findAgent(STATE.selected)) STATE.selected = null;
  render();
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAgent(); });
setInterval(tick, 3000);
setInterval(renderAge, 1000);
tick();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify server serves it + smoke manual dengan db asli**

Run: `voffice run --no-open` lalu buka `http://127.0.0.1:8787` di browser.
Checklist manual (spec section 12):
- Topbar: jumlah agent kerja, tok today, breakdown per model.
- Rooms render per project directory; nama ruangan = nama folder; agent tile rich (ring warna status, current tool, model/tok/tools, sparkline).
- Ubah `voffice.toml` sementara: `hidden = ["<nama ruangan>"]` dan `rename`, restart `voffice run`, verify efek, lalu kembalikan.
- Klik agent tile: slide-over terbuka (objective, progress bar, turns, tools, per model); Escape menutup.
- Klik header ruangan: feed terfilter + judul feed berubah; klik lagi: kembali semua.
- Feed: 30 baris terbaru, terbaru di atas, dot warna sesuai status.
- Tutup server (Ctrl+C): banner "server tidak terjangkau" muncul, render terakhir tetap; umur data membesar (data beku).
- Jika ada sesi subagent: chip "X + N sub" dengan dot warna per sub.

- [ ] **Step 3: Commit**

```bash
git add src/voffice/static/index.html
git commit -m "feat: frontend mission control soft rooms"
```

---

### Task 10: README + smoke test final

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: semua yang sudah dibangun.
- Produces: README siap pembaca baru; verifikasi akhir semua test hijau + snapshot db asli sehat.

- [ ] **Step 1: Write README**

`README.md`:

```markdown
# voidlight-office

Dashboard lokal buat memantau agent yang jalan di ZCode. Analoginya pandangan
top-down sebuah kantor: setiap project adalah ruangan, setiap agent ZCode adalah
orang yang kerja di dalamnya. Buka di monitor kedua, dilirik dari jauh:
agent mana yang lagi kerja, lagi ngapain, udah jauh gimana.

## Install

Syarat: Python 3.12+, sekali saja setelah clone.

    python -m pip install -e ".[dev]"

## Pakai

    voffice run          # server di 127.0.0.1:8787 + buka browser; Ctrl+C untuk stop
    voffice snapshot     # print JSON snapshot sekali (debug tanpa browser)
    voffice test         # pytest

Flag `voffice run`: `--port N`, `--no-open`, `--db PATH` (override path db ZCode).
`voffice snapshot` juga punya `--db`.

Sumber data: db SQLite ZCode (`~/.zcode/cli/db/db.sqlite`), dibaca strict
read-only. Dashboard tidak menulis ke mana pun dan tidak menyimpan state sendiri.

## Config

Opsional: file `voffice.toml` di folder tempat `voffice` dijalankan. Tanpa file
ini semua default jalan. Contoh ada di root repo.

    [server]
    port = 8787
    poll_interval_seconds = 3

    [status]
    working_max_seconds = 90    # hijau (kerja)
    idle_max_seconds = 900      # kuning (idle); lebih tua = abu (quiet)
    agent_ttl_hours = 24        # sesi lebih tua dari ini tidak tampil

    [rooms]
    rename = { teraflow = "TF" }   # key = nama ruangan hasil derivasi
    hidden = ["zcode-workspace"]   # nama ruangan hasil derivasi

## Cara kerja

Collector thread baca db tiap 3 detik (WAL, read-only, aman selagi ZCode nulis),
bangun snapshot JSON via fungsi murni, server FastAPI menyajikannya di
`GET /api/snapshot`, frontend satu file HTML poll tiap 3 detik. Semua agregasi
di collector; frontend dumb. Fail soft: db hilang/schema berubah/server mati
hanya muncul banner, dashboard tidak crash.

## Test

    voffice test

Semua test pakai fixture db sintetis; tidak butuh db ZCode asli.
```

- [ ] **Step 2: Full test suite + smoke db asli**

Run:
```bash
python -m pytest tests/ -v
voffice snapshot --db "C:/Users/khayren/.zcode/cli/db/db.sqlite" > /tmp/snap.json && python -c "
import json
s = json.load(open('/tmp/snap.json'))
print('partial:', s['meta']['partial'], s['meta']['errors'])
print('rooms:', [r['name'] for r in s['rooms']])
print('usage:', s['usage'])
"
```
Expected: semua test PASS; snapshot asli: partial false, rooms sesuai project yang ada, usage terisi.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README cara pakai dan config"
```

---

## Self-Review (dijalankan penulis plan, hasil: lolos)

1. **Spec coverage:** pemetaan ruangan (sec 5) = Task 3+5; ring status + threshold (sec 5) = Task 3; "lagi ngapain" (sec 5) = Task 4; progress/budget (sec 5) = Task 4+5; sparkline = Task 4; activity feed = Task 5; strip usage global = Task 5; short_name = Task 5; JSON shape = Task 5 (+pin no. 10); CLI + flags (sec 6) = Task 1+8; struktur folder (sec 7) = semua task; config (sec 8) = Task 1; refresh & umur data (sec 9) = Task 6+9; interaksi slide-over + filter feed (sec 10) = Task 5 (data turns/tools/models) + Task 9; error handling fail soft (sec 11) = Task 6+9; testing (sec 12) = Task 2-8 + checklist manual Task 9; non-goals (sec 13) tidak menambah scope.
2. **Placeholder scan:** tidak ada TBD/TODO; semua step berisi kode atau command konkret.
3. **Type consistency:** `build_agent` menghasilkan field yang dikonsumsi `build_snapshot` dan frontend; `TOOL_STATUS_MAP`/`USAGE_STATUS_MAP` konsisten feed vs panel; `Collector.snapshot()` = holder protocol `create_app`; signature `load_snapshot(db_path, config, now_ms=None)` konsisten di Task 6 dan 8.
