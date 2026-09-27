import json
from datetime import datetime

from conftest import sess, tool, turn
from voffice.intelligence import build_intelligence, intelligence_report

NOW = 1_790_373_040_121
MID = NOW - 7 * 3_600_000
HOME = "C:\\Users\\khayren"


def local_midnight(now_ms):
    return int(datetime.fromtimestamp(now_ms / 1000)
               .replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def test_build_intelligence_ranks_sessions_and_attaches_identity():
    session_rows = [
        {"session_id": "sess_b", "title": "Tugas B", "directory": "C:/w/voidlight",
         "total": 900, "input_tokens": 300, "output_tokens": 100,
         "cache_creation": 200, "cache_read": 300, "turns": 1},
        {"session_id": "sess_a", "title": "Tugas A", "directory": "C:/w/teraflow",
         "total": 600, "input_tokens": 100, "output_tokens": 50,
         "cache_creation": 150, "cache_read": 200, "turns": 2},
    ]
    turns = [
        turn(session_id="sess_a", turn_id="t1", started_at=NOW, computed_total_tokens=500,
             input_tokens=100, output_tokens=50, cache_creation_input_tokens=150,
             cache_read_input_tokens=200, tool_call_count=2),
        turn(session_id="sess_b", turn_id="t2", started_at=NOW, computed_total_tokens=900,
             input_tokens=300, output_tokens=100, cache_creation_input_tokens=200,
             cache_read_input_tokens=300, tool_call_count=1),
        turn(session_id="sess_a", turn_id="t3", started_at=NOW, computed_total_tokens=100),
    ]
    tools = [
        tool(session_id="sess_a", turn_id="t1", tool_name="Bash"),
        tool(session_id="sess_a", turn_id="t1", tool_name="Edit"),
        tool(session_id="sess_b", turn_id="t2", tool_name="Bash"),
    ]
    turn_tokens = [("sess_a", "t1", 500, 2), ("sess_b", "t2", 900, 1),
                   ("sess_a", "t3", 100, 0)]
    report = build_intelligence(session_rows, turns, tools, turn_tokens,
                                scope="all", home=HOME, limit=10)
    assert report["scope"] == "all"
    names = [r["name"] for r in report["sessions"]]
    assert names[0] == agent_name_of("sess_b")
    assert names[1] == agent_name_of("sess_a")
    top = report["sessions"][0]
    assert top["total"] == 900
    assert top["input"] == 300
    assert top["output"] == 100
    assert top["cache_creation"] == 200
    assert top["cache_read"] == 300
    assert top["turns"] == 1
    assert top["room"] == "voidlight"
    assert top["title"] == "Tugas B"
    assert top["share"] == 100
    # turn ranking teratas
    assert report["turns"][0]["total"] == 900
    assert report["turns"][0]["tool_calls"] == 1
    # estimasi token tool: turn 500 / 2 tool = 250 per call
    tool_rank = {r["tool"]: r for r in report["tools"]}
    assert tool_rank["Bash"]["est_tokens"] == 900 + 250
    assert tool_rank["Bash"]["calls"] == 2
    assert tool_rank["Edit"]["est_tokens"] == 250


def agent_name_of(session_id):
    from voffice.collector import agent_name_for_session
    return agent_name_for_session(session_id)


def test_build_intelligence_respects_limit():
    session_rows = [
        {"session_id": f"sess_{i}", "title": None, "directory": "C:/w/proj",
         "total": (i + 1) * 100, "input_tokens": 0, "output_tokens": 0,
         "cache_creation": 0, "cache_read": 0, "turns": 1}
        for i in range(15)
    ]
    turns = [turn(session_id=f"sess_{i}", turn_id=f"t{i}", started_at=NOW,
                  computed_total_tokens=(i + 1) * 100) for i in range(15)]
    report = build_intelligence(session_rows, turns, [], [], scope="all", home=HOME, limit=10)
    assert len(report["sessions"]) == 10
    assert len(report["turns"]) == 10
    assert report["sessions"][0]["total"] == 1500


def test_build_intelligence_empty():
    report = build_intelligence([], [], [], [], scope="all", home=HOME)
    assert report["sessions"] == []
    assert report["turns"] == []
    assert report["tools"] == []
    assert report["partial"] is False


def test_intelligence_report_from_fixture_db(make_db):
    mid = local_midnight(NOW)
    path = make_db(
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=NOW)],
        turns=[
            turn(session_id="sess_a", turn_id="t1", started_at=mid + 1000,
                 computed_total_tokens=700, input_tokens=100, output_tokens=100,
                 cache_creation_input_tokens=200, cache_read_input_tokens=300),
            turn(session_id="sess_a", turn_id="t2", started_at=mid - 999_000,
                 computed_total_tokens=9_000),
        ],
        tools=[tool(session_id="sess_a", turn_id="t1", tool_name="Bash",
                    started_at=mid + 1000, output_bytes=1000, stdout_bytes=800,
                    stderr_bytes=20)],
    )
    all_report = intelligence_report(path, scope="all", now_ms=NOW)
    assert all_report["partial"] is False
    assert all_report["sessions"][0]["total"] == 9700

    today_report = intelligence_report(path, scope="today", now_ms=NOW)
    assert today_report["sessions"][0]["total"] == 700
    assert today_report["scope"] == "today"
    tool_row = today_report["tools"][0]
    assert tool_row["tool"] == "Bash"
    assert tool_row["calls"] == 1
    assert tool_row["output_bytes"] == 1820
    assert tool_row["est_tokens"] == 700


def test_intelligence_report_fail_soft(make_db):
    path = make_db(drop_tables=("turn_usage",))
    report = intelligence_report(path, scope="all", now_ms=NOW)
    assert report["partial"] is True
    assert report["errors"]
    assert report["sessions"] == []


def test_intelligence_report_missing_db(tmp_path):
    report = intelligence_report(tmp_path / "nope.sqlite", scope="all", now_ms=NOW)
    assert report["partial"] is True
    assert any("db tidak ditemukan" in e for e in report["errors"])
