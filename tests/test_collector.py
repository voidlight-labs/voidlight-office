import sqlite3
import time

import pytest

from conftest import model, sess, target, tool, turn
from voffice.collector import (
    AGENT_NAME_POOL,
    Collector,
    agent_name_for_session,
    build_agent,
    build_snapshot,
    compute_activity_ts,
    current_tool_line,
    derive_role,
    derive_status,
    format_duration,
    is_last_turn_errored,
    load_snapshot,
    room_name_for_directory,
)

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
    agent = build_agent(sess(), [], [], tools, [], now_ms=NOW, status_cfg=STATUS_CFG)
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
        targets=[target(session_id="parent", objective="migrasi auth", time_updated=NOW - 10)],
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
    name_a, name_b = agent_name_for_session("sess_a"), agent_name_for_session("sess_b")
    assert [(r["room"], r["agent"], r["tool"], r["status"]) for r in feed] == [
        ("teraflow", name_a, "Read", "running"),
        ("voidlight", name_b, "Edit", "error"),
        ("teraflow", name_a, "Bash", "ok"),
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


def test_agent_name_deterministic_per_session():
    assert agent_name_for_session("sess_a") == agent_name_for_session("sess_a")
    assert agent_name_for_session("sess_a") in AGENT_NAME_POOL


def test_agent_name_uniqueness_falls_to_next_pool_entry():
    pool = ["Alpha", "Beta", "Gamma"]
    used: set = set()
    first = agent_name_for_session("sess_a", pool, used)
    used.add(first)
    second = agent_name_for_session("sess_b", pool, used)
    used.add(second)
    third = agent_name_for_session("sess_c", pool, used)
    assert len({first, second, third}) == 3
    assert {first, second, third} <= set(pool)


def test_snapshot_assigns_unique_names_to_all_agents():
    s = snap(
        sessions=[
            sess("parent", directory="C:/w/teraflow", created=NOW - 1000, updated=NOW),
            sess("sub1", directory="C:/w/teraflow", parent_id="parent", created=NOW, updated=NOW),
            sess("other", directory="C:/w/voidlight", created=NOW, updated=NOW),
        ],
    )
    names = []
    for r in s["rooms"]:
        for a in r["agents"]:
            names.append(a["name"])
            for sub in a["subagents"]:
                names.append(sub["name"])
    assert len(names) == 3
    assert len(set(names)) == 3
    assert set(names) <= set(AGENT_NAME_POOL)


def test_derive_role_from_latest_model_usage():
    models = [
        model(started_at=1000, agent="zcode-general-purpose"),
        model(started_at=2000, agent="zcode-Explore"),
    ]
    assert derive_role(models) == "Explore"
    assert derive_role([model(started_at=1000, agent="zcode-agent")]) == "agent"
    assert derive_role([model(started_at=1000, agent=None), model(started_at=2000)]) is None
    assert derive_role([]) is None


def test_snapshot_role_and_sub_roles_summary():
    s = snap(
        sessions=[
            sess("parent", directory="C:/w/teraflow", created=NOW - 1000, updated=NOW),
            sess("sub1", directory="C:/w/teraflow", parent_id="parent", created=NOW, updated=NOW),
            sess("sub2", directory="C:/w/teraflow", parent_id="parent", created=NOW, updated=NOW),
        ],
        models=[
            model(session_id="parent", agent="zcode-agent", started_at=NOW - 1000),
            model(session_id="sub1", agent="zcode-Explore", started_at=NOW - 1000),
            model(session_id="sub2", agent="zcode-judge", started_at=NOW - 1000),
        ],
    )
    parent = s["rooms"][0]["agents"][0]
    assert parent["role"] == "agent"
    assert parent["subagents"][0]["role"] == "Explore"
    assert parent["subagents"][1]["role"] == "judge"
    assert parent["sub_roles"] == {"Explore": 1, "judge": 1}


def test_snapshot_no_role_when_model_usage_empty():
    s = snap(sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW, updated=NOW)])
    agent = s["rooms"][0]["agents"][0]
    assert agent["role"] is None
    assert agent["sub_roles"] == {}


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
