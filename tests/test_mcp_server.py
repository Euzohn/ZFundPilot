"""MCP 适配层测试：使用 httpx MockTransport，不访问网络。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from zfundpilot import mcp_server


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ZFUNDPILOT_BASE_URL", "http://zfund.test")
    monkeypatch.setenv("ZFUNDPILOT_AGENT_TOKEN", "zfag_test")


@pytest.fixture
def mock_api(monkeypatch):
    """替换 HTTP 客户端，返回一个安装函数。"""
    def install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        def factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://zfund.test",
            )

        monkeypatch.setattr(mcp_server, "_make_client", factory)

    return install


def test_tools_registered():
    tools = _run(mcp_server.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "get_portfolio_summary",
        "get_data_status",
        "list_positions",
        "get_fund_detail",
        "get_portfolio_health",
    }


def test_summary_sends_bearer_token(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={
            "tool": "get_portfolio_summary",
            "data": {"total_value": 123.0},
        })

    mock_api(handler)
    result = _run(mcp_server.get_portfolio_summary())

    assert seen == {"path": "/api/agent/tools/portfolio-summary"}
    assert result["data"]["total_value"] == 123.0


def test_client_sends_bearer_token():
    async def check() -> str | None:
        client = mcp_server._make_client()
        try:
            return client.headers.get("authorization")
        finally:
            await client.aclose()

    assert _run(check()) == "Bearer zfag_test"


def test_positions_passes_query_params(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"positions": []}})

    mock_api(handler)
    _run(mcp_server.list_positions(include_closed=True, limit=5))

    assert seen["params"] == {"include_closed": "true", "limit": "5"}


def test_scope_error_becomes_tool_error(mock_api):
    mock_api(lambda request: httpx.Response(
        403, json={"detail": "Agent token 缺少权限：health:read"}))

    with pytest.raises(ToolError, match="scope"):
        _run(mcp_server.get_data_status())


def test_api_error_detail_is_preserved(mock_api):
    mock_api(lambda request: httpx.Response(
        404, json={"detail": "未找到基金 000000"}))

    with pytest.raises(ToolError, match="未找到基金 000000"):
        _run(mcp_server.get_fund_detail("000000"))


def test_fund_code_validation_without_network():
    with pytest.raises(ToolError, match="6 digits"):
        _run(mcp_server.get_fund_detail("abc"))


def test_missing_token(monkeypatch):
    monkeypatch.delenv("ZFUNDPILOT_AGENT_TOKEN", raising=False)
    with pytest.raises(ToolError, match="ZFUNDPILOT_AGENT_TOKEN"):
        _run(mcp_server.get_portfolio_summary())
