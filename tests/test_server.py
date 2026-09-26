from pathlib import Path

from fastapi.testclient import TestClient

from conftest import msg, part_row, sess, turn
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


def test_content_endpoints(make_db):
    db = make_db(
        turns=[turn(session_id="sess_a", turn_id="t1", user_message_id="msg_u1")],
        messages=[msg(id="msg_u1", session_id="sess_a", role="user")],
        parts=[
            part_row(id="p1", message_id="msg_u1", data={"type": "text", "text": "hai"},
                     sequence=0),
            part_row(id="p2", data={
                "type": "tool", "callID": "call_1", "tool": "Bash",
                "state": {"status": "completed", "input": {"command": "ls"}, "output": "ok"},
            }),
        ],
    )
    app = create_app(FakeHolder(None), Path("/tmp"), db_path=str(db))
    client = TestClient(app)
    res = client.get("/api/content/tool/call_1")
    assert res.status_code == 200
    assert res.json()["kind"] == "tool"
    assert res.json()["output"]["content"] == "ok"

    res = client.get("/api/content/turn/t1")
    assert res.status_code == 200
    assert res.json()["kind"] == "turn"
    assert res.json()["entries"][0]["content"] == "hai"

    assert client.get("/api/content/tool/missing").status_code == 404
    assert client.get("/api/content/turn/missing").status_code == 404


def test_content_endpoints_without_db(tmp_path):
    app = create_app(FakeHolder(None), tmp_path, db_path=None)
    client = TestClient(app)
    assert client.get("/api/content/tool/x").status_code == 404
    assert client.get("/api/content/turn/x").status_code == 404
    assert client.get("/api/intelligence").status_code == 404


def test_intelligence_endpoint(make_db):
    from datetime import datetime

    now = 1_790_373_040_121
    mid = int(datetime.fromtimestamp(now / 1000)
              .replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    db = make_db(
        sessions=[sess("sess_a", directory="C:/w/teraflow", created=now)],
        turns=[
            turn(session_id="sess_a", turn_id="t1", started_at=mid + 1000,
                 computed_total_tokens=700),
            turn(session_id="sess_a", turn_id="t2", started_at=mid - 999_000,
                 computed_total_tokens=9_000),
        ],
    )
    app = create_app(FakeHolder(None), Path("/tmp"), db_path=str(db))
    client = TestClient(app)

    all_res = client.get("/api/intelligence?scope=all")
    assert all_res.status_code == 200
    body = all_res.json()
    assert body["sessions"][0]["total"] == 9700
    assert body["turns"][0]["total"] == 9000

    today_res = client.get("/api/intelligence?scope=today")
    assert today_res.json()["sessions"][0]["total"] == 700

    bogus = client.get("/api/intelligence?scope=hazard")
    assert bogus.json()["scope"] == "all"
