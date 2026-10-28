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
        "get_returns",
        "compare_funds",
        "list_transactions",
        "get_transaction",
        "list_watchlist",
        "list_alerts",
        "list_auto_invest_plans",
        "get_portfolio_curve",
        "get_benchmark_comparison",
        "get_risk_report",
        "get_industry_exposure",
        "get_agent_capabilities",
    }


def test_summary_requests_expected_path(mock_api):
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


def test_returns_passes_fund_code(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"scope": "fund"}})

    mock_api(handler)
    result = _run(mcp_server.get_returns("005827"))

    assert seen["path"] == "/api/agent/tools/returns"
    assert seen["params"] == {"fund_code": "005827"}
    assert result["data"]["scope"] == "fund"


def test_returns_omits_fund_code_for_portfolio(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"scope": "portfolio"}})

    mock_api(handler)
    _run(mcp_server.get_returns())

    assert seen["params"] == {}


def test_compare_funds_passes_repeated_codes(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["codes"] = request.url.params.get_list("codes")
        return httpx.Response(200, json={"data": {"count": 2}})

    mock_api(handler)
    _run(mcp_server.compare_funds(["005827", "000001"]))

    assert seen["path"] == "/api/agent/tools/funds/compare"
    assert seen["codes"] == ["005827", "000001"]


def test_compare_funds_validation_without_network():
    with pytest.raises(ToolError, match="6 digits"):
        _run(mcp_server.compare_funds(["abc"]))
    with pytest.raises(ToolError, match="At least one"):
        _run(mcp_server.compare_funds([""]))


def test_list_transactions_passes_filters(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"total": 1}})

    mock_api(handler)
    result = _run(mcp_server.list_transactions(
        fund_code="005827", action="buy", date_from="2026-01-01",
        date_to="2026-12-31", nav_status="confirmed", channel="支付宝",
        conversion_id="conv-1", limit=10, offset=20,
    ))

    assert seen["path"] == "/api/agent/tools/transactions"
    assert seen["params"] == {
        "fund_code": "005827",
        "action": "buy",
        "date_from": "2026-01-01",
        "date_to": "2026-12-31",
        "nav_status": "confirmed",
        "channel": "支付宝",
        "conversion_id": "conv-1",
        "limit": "10",
        "offset": "20",
    }
    assert result["data"]["total"] == 1


def test_list_transactions_omits_empty_filters(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {}})

    mock_api(handler)
    _run(mcp_server.list_transactions())

    assert seen["params"] == {"limit": "50", "offset": "0"}


def test_list_transactions_validation_without_network():
    with pytest.raises(ToolError, match="6 digits"):
        _run(mcp_server.list_transactions(fund_code="abc"))
    with pytest.raises(ToolError, match="Action"):
        _run(mcp_server.list_transactions(action="trade"))
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        _run(mcp_server.list_transactions(date_from="2026/01/01"))
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        _run(mcp_server.list_transactions(date_from="2026-1-01"))
    with pytest.raises(ToolError, match="valid date"):
        _run(mcp_server.list_transactions(date_to="2026-02-30"))
    with pytest.raises(ToolError, match="nav_status"):
        _run(mcp_server.list_transactions(nav_status="ok"))
    with pytest.raises(ToolError, match="date_from"):
        _run(mcp_server.list_transactions(
            date_from="2026-12-01", date_to="2026-01-01"))


def test_get_transaction_uses_id_path(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"id": 7}})

    mock_api(handler)
    result = _run(mcp_server.get_transaction(7))

    assert seen["path"] == "/api/agent/tools/transactions/7"
    assert result["data"]["id"] == 7


def test_list_watchlist_filters_by_group(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"total": 1}})

    mock_api(handler)
    _run(mcp_server.list_watchlist(group_name="核心", limit=5))

    assert seen["path"] == "/api/agent/tools/watchlist"
    assert seen["params"] == {
        "group_name": "核心", "limit": "5", "offset": "0"}


def test_list_alerts_passes_type_and_status(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"total": 0}})

    mock_api(handler)
    _run(mcp_server.list_alerts(type="dividend", status="pending"))

    assert seen["path"] == "/api/agent/tools/alerts"
    assert seen["params"] == {
        "type": "dividend", "status": "pending",
        "limit": "50", "offset": "0"}


def test_list_alerts_validation_without_network():
    with pytest.raises(ToolError, match="type"):
        _run(mcp_server.list_alerts(type="unknown"))
    with pytest.raises(ToolError, match="status"):
        _run(mcp_server.list_alerts(status="done"))


def test_list_auto_invest_plans_passes_enabled(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"total": 0}})

    mock_api(handler)
    _run(mcp_server.list_auto_invest_plans(enabled=False, limit=10))

    assert seen["path"] == "/api/agent/tools/auto-invest-plans"
    assert seen["params"] == {
        "enabled": "false", "limit": "10", "offset": "0"}


def test_portfolio_curve_passes_dates_and_limit(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"points": []}})

    mock_api(handler)
    _run(mcp_server.get_portfolio_curve(
        start_date="2026-01-01", end_date="2026-01-31", max_points=100))

    assert seen["path"] == "/api/agent/tools/portfolio-curve"
    assert seen["params"] == {
        "max_points": "100",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    }


def test_portfolio_curve_validation_without_network():
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        _run(mcp_server.get_portfolio_curve(start_date="2026-1-01"))
    with pytest.raises(ToolError, match="not a valid date"):
        _run(mcp_server.get_portfolio_curve(end_date="2026-02-30"))
    with pytest.raises(ToolError, match="later than"):
        _run(mcp_server.get_portfolio_curve(
            start_date="2026-02-01", end_date="2026-01-01"))


def test_benchmark_comparison_passes_codes_and_dates(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["codes"] = request.url.params.get_list("codes")
        return httpx.Response(200, json={"data": {"points": []}})

    mock_api(handler)
    _run(mcp_server.get_benchmark_comparison(
        ["000300", "CPI"], start_date="2026-01-01"))

    assert seen["path"] == "/api/agent/tools/benchmark"
    assert seen["codes"] == ["000300", "CPI"]
    assert seen["params"]["start_date"] == "2026-01-01"


def test_benchmark_comparison_validation_without_network():
    with pytest.raises(ToolError, match="At least one"):
        _run(mcp_server.get_benchmark_comparison([""]))
    with pytest.raises(ToolError, match="Unsupported"):
        _run(mcp_server.get_benchmark_comparison(["BAD"]))
    with pytest.raises(ToolError, match="not a valid date"):
        _run(mcp_server.get_benchmark_comparison(
            ["000300"], end_date="2026-02-30"))


def test_risk_report_requests_expected_path(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"max_drawdown": None}})

    mock_api(handler)
    result = _run(mcp_server.get_risk_report())

    assert seen["path"] == "/api/agent/tools/risk-report"
    assert result["data"]["max_drawdown"] is None


def test_industry_exposure_requests_expected_path(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"ok": False}})

    mock_api(handler)
    result = _run(mcp_server.get_industry_exposure())

    assert seen["path"] == "/api/agent/tools/industry-exposure"
    assert result["data"]["ok"] is False


def test_capabilities_requests_expected_path(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"schema_version": 1}})

    mock_api(handler)
    result = _run(mcp_server.get_agent_capabilities())

    assert seen["path"] == "/api/agent/tools/capabilities"
    assert result["data"]["schema_version"] == 1


def test_missing_token(monkeypatch):
    monkeypatch.delenv("ZFUNDPILOT_AGENT_TOKEN", raising=False)
    with pytest.raises(ToolError, match="ZFUNDPILOT_AGENT_TOKEN"):
        _run(mcp_server.get_portfolio_summary())
