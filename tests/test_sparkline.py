"""sparkline 模块与 /api/funds/sparklines 端点测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db, sparkline
from zfundpilot.models import NavPoint


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    db.upsert_nav_batch([
        NavPoint("005827", "2026-11-10", 2.0),
        NavPoint("005827", "2026-11-11", 2.1),
        NavPoint("005827", "2026-11-12", 2.2),
    ])
    yield


# ---------------------------------------------------------------------------
# parse_codes
# ---------------------------------------------------------------------------
class TestParseCodes:
    def test_dedupe_and_trim(self):
        assert sparkline.parse_codes(" 005827 ,110011,005827,") == ["005827", "110011"]

    def test_empty(self):
        assert sparkline.parse_codes("") == []
        assert sparkline.parse_codes(" , ,") == []

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="格式错误"):
            sparkline.parse_codes("00582")
        with pytest.raises(ValueError, match="格式错误"):
            sparkline.parse_codes("abcdef")

    def test_max_codes(self):
        codes = ",".join(f"{i:06d}" for i in range(sparkline.MAX_CODES))
        assert len(sparkline.parse_codes(codes)) == sparkline.MAX_CODES
        too_many = ",".join(f"{i:06d}" for i in range(sparkline.MAX_CODES + 1))
        with pytest.raises(ValueError, match="最多"):
            sparkline.parse_codes(too_many)


# ---------------------------------------------------------------------------
# build_sparkline(s)
# ---------------------------------------------------------------------------
class TestBuildSparkline:
    def test_normalized(self, temp_db):
        s = sparkline.build_sparkline("005827")
        assert s.points == [1.0, 1.05, 1.1]
        assert s.start == "2026-11-10"
        assert s.end == "2026-11-12"

    def test_missing_fund_empty(self, temp_db):
        s = sparkline.build_sparkline("999999")
        assert s.points == []
        assert s.start == "" and s.end == ""

    def test_single_point_empty(self, temp_db, monkeypatch):
        monkeypatch.setattr(
            db, "get_nav_history_tail",
            lambda code, limit: [dict(date="2026-11-12", nav=2.2)])
        assert sparkline.build_sparkline("005827").points == []

    def test_skips_invalid_nav(self, temp_db, monkeypatch):
        """非法/非正净值跳过，不影响归一化基准。"""
        rows = [
            dict(date="2026-11-09", nav=None),
            dict(date="2026-11-10", nav=2.0),
            dict(date="2026-11-11", nav=-1.0),
            dict(date="2026-11-12", nav=2.2),
        ]
        monkeypatch.setattr(db, "get_nav_history_tail", lambda code, limit: rows)
        s = sparkline.build_sparkline("005827")
        assert s.points == [1.0, 1.1]
        assert s.start == "2026-11-10"

    def test_tail_limit(self, temp_db):
        """只取最近 limit 条（date ASC）。"""
        db.upsert_nav_batch([
            NavPoint("110011", f"2026-01-{d:02d}", 1.0 + d / 100) for d in range(1, 11)
        ])
        s = sparkline.build_sparkline("110011", limit=3)
        assert s.start == "2026-01-08"
        assert s.end == "2026-01-10"
        assert len(s.points) == 3
        assert s.points[0] == 1.0

    def test_batch_degrades_on_error(self, temp_db, monkeypatch):
        def fake_build(code, limit):
            if code == "005827":
                raise RuntimeError("db busy")
            return sparkline.Sparkline(code=code, points=[1.0, 1.2], start="a", end="b")

        monkeypatch.setattr(sparkline, "build_sparkline", fake_build)
        result = sparkline.build_sparklines(["005827", "110011"])
        assert result[0].points == []
        assert result[1].points == [1.0, 1.2]


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------
class TestSparklinesEndpoint:
    @pytest.fixture
    def client(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        return TestClient(api.app)

    def test_ok(self, client):
        r = client.get("/api/funds/sparklines?codes=005827,999999")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert len(body["sparklines"]) == 2
        assert body["sparklines"][0]["points"] == [1.0, 1.05, 1.1]
        assert body["sparklines"][1]["points"] == []

    def test_route_not_shadowed_by_fund_code(self, client):
        """sparklines 路由必须先于 /api/funds/{code} 注册。"""
        r = client.get("/api/funds/sparklines?codes=005827")
        assert r.status_code == 200
        assert "sparklines" in r.json()

    def test_invalid_code_400(self, client):
        assert client.get("/api/funds/sparklines?codes=bad").status_code == 400

    def test_too_many_400(self, client):
        codes = ",".join(f"{i:06d}" for i in range(sparkline.MAX_CODES + 1))
        assert client.get(f"/api/funds/sparklines?codes={codes}").status_code == 400

    def test_empty_codes(self, client):
        r = client.get("/api/funds/sparklines")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "sparklines": []}

    def test_requires_auth_when_enabled(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
        client = TestClient(api.app)
        assert client.get("/api/funds/sparklines?codes=005827").status_code == 401
