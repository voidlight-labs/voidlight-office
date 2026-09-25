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
