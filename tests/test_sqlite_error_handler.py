"""SQLite 异常映射测试：持锁超时返回可重试的 503，而不是 500。"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from zfundpilot.api import app

TEST_PATH = "/api/__test_sqlite_error"


@pytest.fixture
def error_route():
    """注册一个临时路由，按测试注入的异常类型抛出。"""
    holder: dict[str, Exception] = {}

    def _boom() -> None:
        raise holder["exc"]

    app.add_api_route(TEST_PATH, _boom, methods=["GET"])
    # 本地存在 frontend/dist 时，SPA 的 StaticFiles 挂载会优先吞掉未知路径；
    # 把测试路由移到最前，确保验证到的是异常处理器而不是静态文件 404。
    route = app.router.routes.pop()
    app.router.routes.insert(0, route)
    try:
        yield holder
    finally:
        app.router.routes = [
            item for item in app.router.routes
            if getattr(item, "path", None) != TEST_PATH
        ]


@pytest.mark.parametrize("message", ["database is locked", "database is busy"])
def test_locked_busy_maps_to_503(error_route, message):
    error_route["exc"] = sqlite3.OperationalError(message)

    response = TestClient(app).get(TEST_PATH)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    detail = response.json()["detail"]
    assert detail["code"] == "database_busy"
    assert "稍后重试" in detail["message"]


def test_other_operational_error_maps_to_500(error_route):
    error_route["exc"] = sqlite3.OperationalError("no such table: nope")

    response = TestClient(app).get(TEST_PATH)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "database_error"
