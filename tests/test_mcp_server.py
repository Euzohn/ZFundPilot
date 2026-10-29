"""MCP 适配层测试：使用 httpx MockTransport，不访问网络。"""

from __future__ import annotations

import asyncio
import json
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
        "search_funds",
        "screen_funds",
        "run_dca_backtest",
        "get_agent_capabilities",
        "add_watchlist_item",
        "update_watchlist_item",
        "remove_watchlist_item",
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


def test_search_funds_passes_keyword_and_paging(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"funds": []}})

    mock_api(handler)
    _run(mcp_server.search_funds("易方达", limit=10, offset=20))

    assert seen["path"] == "/api/agent/tools/search"
    assert seen["params"] == {"keyword": "易方达", "limit": "10", "offset": "20"}


def test_search_funds_validation_without_network():
    with pytest.raises(ToolError, match="must not be empty"):
        _run(mcp_server.search_funds("   "))
    with pytest.raises(ToolError, match="at most 100"):
        _run(mcp_server.search_funds("基" * 101))


def test_screen_funds_passes_filters_and_metrics(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["types"] = request.url.params.get_list("types")
        seen["sectors"] = request.url.params.get_list("sectors")
        return httpx.Response(200, json={"data": {"funds": []}})

    mock_api(handler)
    _run(mcp_server.screen_funds(
        types=["混合型", "混合型", "债券型"], sectors=["科技"],
        keyword="  易方达  ", with_metrics=True, limit=20, offset=0))

    assert seen["path"] == "/api/agent/tools/screen"
    assert seen["types"] == ["混合型", "债券型"]
    assert seen["sectors"] == ["科技"]
    assert seen["params"]["keyword"] == "易方达"
    assert seen["params"]["with_metrics"] == "true"
    assert seen["params"]["limit"] == "20"


def test_screen_funds_validation_without_network():
    with pytest.raises(ToolError, match="at most 20"):
        _run(mcp_server.screen_funds(types=[f"类型{i}" for i in range(21)]))
    with pytest.raises(ToolError, match="at most 100"):
        _run(mcp_server.screen_funds(keyword="基" * 101))


def test_run_dca_backtest_posts_json(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"ok": True}})

    mock_api(handler)
    _run(mcp_server.run_dca_backtest(
        ["000001", " 000001 ", "110011"],
        "2024-01-01", "2024-03-31", 1000.0,
        cadence="week", include_lumpsum=False,
        include_curve=False, include_periods=True, max_points=20))

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent/tools/backtest/dca"
    assert seen["body"] == {
        "fund_codes": ["000001", "110011"],
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "amount_per_period": 1000.0,
        "cadence": "week",
        "include_lumpsum": False,
        "include_curve": False,
        "include_periods": True,
        "max_points": 20,
    }


def test_run_dca_backtest_validation_without_network():
    base = {
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "amount_per_period": 1000.0,
    }
    with pytest.raises(ToolError, match="at least one"):
        _run(mcp_server.run_dca_backtest([], **base))
    with pytest.raises(ToolError, match="at most 5"):
        _run(mcp_server.run_dca_backtest(
            [f"00000{i}" for i in range(6)], **base))
    with pytest.raises(ToolError, match="at most 5"):
        _run(mcp_server.run_dca_backtest(["000001"] * 6, **base))
    with pytest.raises(ToolError, match="six-digit"):
        _run(mcp_server.run_dca_backtest(["12345"], **base))
    with pytest.raises(ToolError, match="must contain strings"):
        _run(mcp_server.run_dca_backtest([123456], **base))
    with pytest.raises(ToolError, match="earlier than end_date"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], start_date="2024-03-31", end_date="2024-01-01",
            amount_per_period=1000.0))
    with pytest.raises(ToolError, match="later than today"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], start_date="2024-01-01", end_date="2999-01-01",
            amount_per_period=1000.0))
    with pytest.raises(ToolError, match="must not exceed 10 years"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], start_date="2014-01-01", end_date="2024-01-02",
            amount_per_period=1000.0))
    with pytest.raises(ToolError, match="positive"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], **{**base, "amount_per_period": 0}))
    with pytest.raises(ToolError, match="1,000,000"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], **{**base, "amount_per_period": 1_000_001}))
    with pytest.raises(ToolError, match="cadence"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], **base, cadence="daily"))
    with pytest.raises(ToolError, match="max_points"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], **base, max_points=9))
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        _run(mcp_server.run_dca_backtest(
            ["000001"], **{**base, "start_date": "2024/01/01"}))


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


KEY = "test-key-aaaaaaaaaaaa"


def test_add_watchlist_item_maps_header_and_body(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("Idempotency-Key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"tool": "add_watchlist_item",
                                         "data": {"ok": True}})

    mock_api(handler)
    _run(mcp_server.add_watchlist_item(
        "005827", KEY, note="\u89c2\u5bdf", group_name="\u6838\u5fc3"))

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent/tools/watchlist"
    assert seen["key"] == KEY
    assert seen["body"] == {"fund_code": "005827", "note": "\u89c2\u5bdf",
                            "group_name": "\u6838\u5fc3"}


def test_update_watchlist_item_only_sends_provided_fields(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"tool": "update_watchlist_item",
                                         "data": {"ok": True}})

    mock_api(handler)
    _run(mcp_server.update_watchlist_item(
        "005827", 3, KEY, note="\u65b0\u5907\u6ce8"))

    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/agent/tools/watchlist/005827"
    assert seen["body"] == {"expected_revision": 3, "note": "\u65b0\u5907\u6ce8"}


def test_remove_watchlist_item_uses_query_and_header(mock_api):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["revision"] = request.url.params.get("expected_revision")
        seen["key"] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, json={"tool": "remove_watchlist_item",
                                         "data": {"ok": True}})

    mock_api(handler)
    _run(mcp_server.remove_watchlist_item("005827", 2, KEY))

    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/agent/tools/watchlist/005827"
    assert seen["revision"] == "2"
    assert seen["key"] == KEY


def test_write_tools_validate_input_before_http(mock_api):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("HTTP must not be called")

    mock_api(handler)
    with pytest.raises(ToolError):
        _run(mcp_server.add_watchlist_item("12345", KEY))
    with pytest.raises(ToolError):
        _run(mcp_server.add_watchlist_item("005827", "short"))
    with pytest.raises(ToolError):
        _run(mcp_server.remove_watchlist_item("005827", 0, KEY))
