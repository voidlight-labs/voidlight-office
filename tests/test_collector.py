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
