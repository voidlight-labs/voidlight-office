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
