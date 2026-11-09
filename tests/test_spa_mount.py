"""回归测试：SPA 静态兜底挂载不得遮蔽 ``/api`` 路由。

背景：生产模式用 ``app.mount("/", StaticFiles(...))`` 兜底前端时，根路径挂载
会 FULL 匹配 ``/api`` 下的所有 GET 请求。对 POST-only 路由发 GET 会被静态兜底
返回 404（静态文件不存在），而不是 405；未知 ``/api`` 路径也会被静默吞掉。
``_SpaMount`` 让 ``/api`` 路径返回 ``Match.NONE`` 交回 FastAPI 路由来修复它。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse
from starlette.routing import Match

from zfundpilot.api import _SpaMount


async def _spa_app(scope, receive, send) -> None:
    await PlainTextResponse("spa")(scope, receive, send)


def _scope(path: str, method: str = "GET") -> dict:
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": [],
        "query_string": b"",
        "root_path": "",
    }


def test_api_paths_bypass_spa_mount():
    mount = _SpaMount("/", _spa_app)
    for path in ("/api", "/api/", "/api/agent/tools/backtest/dca", "/api/unknown"):
        assert mount.matches(_scope(path))[0] == Match.NONE, path


def test_non_api_paths_served_by_spa_mount():
    mount = _SpaMount("/", _spa_app)
    for path in ("/", "/index.html", "/assets/app.js", "/some/spa/route"):
        assert mount.matches(_scope(path))[0] == Match.FULL, path


def test_post_only_api_route_returns_405_with_spa_mount():
    app = FastAPI()

    @app.post("/api/foo")
    def post_foo() -> dict:
        return {"ok": True}

    app.routes.append(_SpaMount("/", _spa_app))
    client = TestClient(app)

    # GET 命中 POST-only 路由 → 405，而不是被 SPA 兜底成 404
    assert client.get("/api/foo").status_code == 405
    # 未知 /api 路径 → 404，且不返回 SPA 内容
    assert client.get("/api/missing").status_code == 404
    # 非 /api 路径交给 SPA 兜底
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.text == "spa"
