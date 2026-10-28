"""ZFundPilot MCP 适配层（stdio）。

把 ZFundPilot 的只读 Agent API 封装成 MCP 工具，供 Claude Desktop、Cursor
等 MCP 客户端直接调用。适配层不含任何业务逻辑，也不直接访问数据库：它只是
带 ``Authorization: Bearer <Agent token>`` 的 HTTP 客户端，因此与网页/HTTP
入口共用同一套 token 校验、scope 与限流，不另开鉴权后门。

安装（可选依赖）::

    pip install 'zfundpilot[agent]'

运行::

    ZFUNDPILOT_BASE_URL=http://127.0.0.1:8000 \
    ZFUNDPILOT_AGENT_TOKEN=zfag_xxx \
    python -m zfundpilot.mcp_server
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from . import config
from .models import ACTIONS

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0

_NAV_STATUSES = frozenset({"confirmed", "pending_t1", "missing"})
_ALERT_TYPES = frozenset({"dividend", "take_profit", "stop_loss", "tp_sl"})
_ALERT_STATUSES = frozenset({"pending", "confirmed", "ignored"})
_BENCHMARK_CODES = frozenset(
    {**config.BENCHMARK_INDICES, **config.MACRO_INDICES})


def _validate_date(value: str | None, field: str) -> str | None:
    """校验可选的 YYYY-MM-DD 日期，非法时抛 ToolError。"""
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ToolError(f"{field} must be YYYY-MM-DD.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ToolError(f"{field} is not a valid date.") from exc
    return value


mcp = FastMCP(
    "zfundpilot",
    instructions=(
        "Read-only portfolio analysis from ZFundPilot. "
        "Call get_data_status before drawing conclusions from NAV-based data, "
        "and get_agent_capabilities to discover tools granted to this token."
    ),
)


def _base_url() -> str:
    return os.environ.get("ZFUNDPILOT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _token() -> str:
    token = os.environ.get("ZFUNDPILOT_AGENT_TOKEN", "").strip()
    if not token:
        raise ToolError(
            "Missing ZFUNDPILOT_AGENT_TOKEN. Issue an Agent token in ZFundPilot "
            "Settings > Account & Security, then set the environment variable."
        )
    return token


def _timeout() -> float:
    raw = os.environ.get("ZFUNDPILOT_TIMEOUT", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT
    except ValueError:
        value = DEFAULT_TIMEOUT
    return max(1.0, min(value, MAX_TIMEOUT))


def _make_client() -> httpx.AsyncClient:
    """构造带 Agent token 的 HTTP 客户端；测试中可替换。"""
    return httpx.AsyncClient(
        base_url=_base_url(),
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=_timeout(),
    )


async def _request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with _make_client() as client:
            response = await client.get(path, params=params)
    except httpx.HTTPError as exc:
        raise ToolError(
            f"Cannot reach ZFundPilot at {_base_url()}: {exc}"
        ) from exc

    if response.status_code == 401:
        raise ToolError(
            "Agent token is invalid, expired, or revoked. "
            "Issue a new token in ZFundPilot Settings."
        )
    if response.status_code == 403:
        raise ToolError(
            "Agent token lacks the required scope, or admin authentication is disabled."
        )
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "60")
        raise ToolError(
            f"Rate limited by ZFundPilot. Retry after {retry_after} seconds."
        )
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("detail", detail))
        except ValueError:
            pass
        raise ToolError(f"ZFundPilot API error ({response.status_code}): {detail}")

    try:
        return response.json()
    except ValueError as exc:
        raise ToolError("ZFundPilot returned a non-JSON response.") from exc


@mcp.tool()
async def get_portfolio_summary() -> dict[str, Any]:
    """Read portfolio market value, cost, P&L, annualized return, and data-as-of date.

    Amounts use the latest formal NAV; the response includes a data_status summary.
    """
    return await _request("/api/agent/tools/portfolio-summary")


@mcp.tool()
async def get_data_status() -> dict[str, Any]:
    """Check formal NAV freshness and pending T+1 transactions before analysis."""
    return await _request("/api/agent/tools/data-status")


@mcp.tool()
async def list_positions(
    include_closed: bool = False,
    limit: Annotated[int, Field(ge=1, le=500)] = 200,
) -> dict[str, Any]:
    """List current holdings by fund and channel, sorted by market value descending.

    Args:
        include_closed: Include fully closed positions.
        limit: Maximum number of positions to return (1-500).
    """
    return await _request("/api/agent/tools/positions", {
        "include_closed": include_closed,
        "limit": limit,
    })


@mcp.tool()
async def get_fund_detail(
    code: str,
    nav_limit: Annotated[int, Field(ge=1, le=250)] = 30,
) -> dict[str, Any]:
    """Read one fund's metadata, latest formal NAV, annualized return, and recent NAV.

    Args:
        code: Six-digit fund code, e.g. "005827".
        nav_limit: Number of recent formal NAV points (1-250).
    """
    if not re.fullmatch(r"\d{6}", code or ""):
        raise ToolError("Fund code must be exactly 6 digits.")
    return await _request(f"/api/agent/tools/funds/{code}", {"nav_limit": nav_limit})


@mcp.tool()
async def get_portfolio_health() -> dict[str, Any]:
    """Read the four-dimension health score, risk flags, and structural advice.

    Check data_quality.caveats before interpreting scores, since missing or stale
    NAV data can lower related dimensions.
    """
    return await _request("/api/agent/tools/portfolio-health")


@mcp.tool()
async def get_returns(fund_code: str | None = None) -> dict[str, Any]:
    """Read portfolio or single-fund return breakdown.

    Returns cumulative return, XIRR annualized return, and daily/week/month/year P&L.

    Args:
        fund_code: Optional six-digit fund code; omit for portfolio-level returns.
    """
    params: dict[str, Any] = {}
    if fund_code:
        if not re.fullmatch(r"\d{6}", fund_code):
            raise ToolError("Fund code must be exactly 6 digits.")
        params["fund_code"] = fund_code
    return await _request("/api/agent/tools/returns", params)


@mcp.tool()
async def compare_funds(
    codes: Annotated[list[str], Field(min_length=1, max_length=20)],
    include_nav_series: bool = False,
) -> dict[str, Any]:
    """Compare up to 20 funds on returns, risk, fees, and correlation.

    Args:
        codes: Six-digit fund codes, e.g. ["005827", "000001"].
        include_nav_series: Include normalized NAV series (larger response).
    """
    cleaned = [c.strip() for c in codes if c and c.strip()]
    if not cleaned:
        raise ToolError("At least one fund code is required.")
    if any(not re.fullmatch(r"\d{6}", c) for c in cleaned):
        raise ToolError("Fund codes must be exactly 6 digits.")
    return await _request("/api/agent/tools/funds/compare", {
        "codes": cleaned,
        "include_nav_series": include_nav_series,
    })


@mcp.tool()
async def list_transactions(
    fund_code: str | None = None,
    channel: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    conversion_id: str | None = None,
    nav_status: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List recorded transactions (newest first) with filters and pagination.

    Amounts: buys include fees, sells are net of fees, dividends are gross.

    Args:
        fund_code: Optional six-digit fund code.
        channel: Optional exact purchase channel.
        action: Optional buy/sell/dividend/reinvest.
        date_from: Optional inclusive start date (YYYY-MM-DD).
        date_to: Optional inclusive end date (YYYY-MM-DD).
        conversion_id: Optional conversion link id to fetch both legs.
        nav_status: Optional confirmed/pending_t1/missing.
        limit: Page size (1-200).
        offset: Page offset.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if fund_code:
        if not re.fullmatch(r"\d{6}", fund_code):
            raise ToolError("Fund code must be exactly 6 digits.")
        params["fund_code"] = fund_code
    if channel is not None:
        params["channel"] = channel
    if action:
        if action not in ACTIONS:
            raise ToolError(f"Action must be one of: {', '.join(ACTIONS)}.")
        params["action"] = action
    for field, value in (("date_from", date_from), ("date_to", date_to)):
        if value:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ToolError(f"{field} must be YYYY-MM-DD.")
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise ToolError(f"{field} is not a valid date.") from exc
            params[field] = value
    if conversion_id:
        params["conversion_id"] = conversion_id
    if nav_status:
        if nav_status not in _NAV_STATUSES:
            raise ToolError(
                "nav_status must be confirmed, pending_t1, or missing.")
        params["nav_status"] = nav_status
    if date_from and date_to and date_from > date_to:
        raise ToolError("date_from must not be later than date_to.")
    return await _request("/api/agent/tools/transactions", params)


@mcp.tool()
async def get_transaction(
    tx_id: Annotated[int, Field(ge=1)],
) -> dict[str, Any]:
    """Read one transaction by id, including derived NAV and conversion fields.

    Args:
        tx_id: Transaction id.
    """
    return await _request(f"/api/agent/tools/transactions/{tx_id}")


@mcp.tool()
async def list_watchlist(
    group_name: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List watchlist funds, optionally filtered by group.

    Args:
        group_name: Optional watchlist group name.
        limit: Page size (1-200).
        offset: Page offset.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if group_name is not None:
        params["group_name"] = group_name
    return await _request("/api/agent/tools/watchlist", params)


@mcp.tool()
async def list_alerts(
    type: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List dividend and take-profit/stop-loss alerts.

    status is a business processing state (pending/confirmed/ignored), not read/unread.

    Args:
        type: Optional dividend/take_profit/stop_loss/tp_sl.
        status: Optional pending/confirmed/ignored.
        limit: Page size (1-200).
        offset: Page offset.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if type:
        if type not in _ALERT_TYPES:
            raise ToolError(
                "type must be dividend, take_profit, stop_loss, or tp_sl.")
        params["type"] = type
    if status:
        if status not in _ALERT_STATUSES:
            raise ToolError("status must be pending, confirmed, or ignored.")
        params["status"] = status
    return await _request("/api/agent/tools/alerts", params)


@mcp.tool()
async def list_auto_invest_plans(
    enabled: bool | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List auto-invest plans with derived status (active/paused/due).

    Skip reasons are not persisted per plan, so they are not reported.

    Args:
        enabled: Optional enabled-state filter.
        limit: Page size (1-200).
        offset: Page offset.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if enabled is not None:
        params["enabled"] = enabled
    return await _request("/api/agent/tools/auto-invest-plans", params)


@mcp.tool()
async def get_portfolio_curve(
    start_date: str | None = None,
    end_date: str | None = None,
    max_points: Annotated[int, Field(ge=10, le=2000)] = 365,
) -> dict[str, Any]:
    """Read the daily portfolio value, invested cost, and cumulative return curve.

    The curve is for visualization, not exact reconciliation.

    Args:
        start_date: Optional inclusive start date (YYYY-MM-DD).
        end_date: Optional inclusive end date (YYYY-MM-DD).
        max_points: Maximum points; larger series are evenly sampled (10-2000).
    """
    params: dict[str, Any] = {"max_points": max_points}
    s = _validate_date(start_date, "start_date")
    e = _validate_date(end_date, "end_date")
    if s and e and s > e:
        raise ToolError("start_date must not be later than end_date.")
    if s:
        params["start_date"] = s
    if e:
        params["end_date"] = e
    return await _request("/api/agent/tools/portfolio-curve", params)


@mcp.tool()
async def get_benchmark_comparison(
    codes: Annotated[list[str], Field(min_length=1, max_length=20)],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Compare the portfolio curve with benchmark indices and macro levels.

    Supported codes: 000300, 000001, 399006 (indices) and CPI, M2 (macro).
    Cumulative returns are based on the portfolio curve start; date filters only
    trim the response. Failed codes do not appear in points.

    Args:
        codes: Benchmark codes, e.g. ["000300", "CPI"].
        start_date: Optional inclusive start date (YYYY-MM-DD).
        end_date: Optional inclusive end date (YYYY-MM-DD).
    """
    cleaned = list(dict.fromkeys(
        c.strip() for c in codes if c and c.strip()))
    if not cleaned:
        raise ToolError("At least one benchmark code is required.")
    invalid = [c for c in cleaned if c not in _BENCHMARK_CODES]
    if invalid:
        raise ToolError(f"Unsupported benchmark codes: {', '.join(invalid)}.")
    params: dict[str, Any] = {"codes": cleaned}
    s = _validate_date(start_date, "start_date")
    e = _validate_date(end_date, "end_date")
    if s and e and s > e:
        raise ToolError("start_date must not be later than end_date.")
    if s:
        params["start_date"] = s
    if e:
        params["end_date"] = e
    return await _request("/api/agent/tools/benchmark", params)


@mcp.tool()
async def get_risk_report() -> dict[str, Any]:
    """Read drawdown, volatility, concentration, structure weights, and risk flags.

    Check data_quality.caveats before interpreting metrics; missing or stale NAV
    data can distort them.
    """
    return await _request("/api/agent/tools/risk-report")


@mcp.tool()
async def get_industry_exposure() -> dict[str, Any]:
    """Read portfolio industry exposure by looking through fund allocations.

    May be slow because it fetches external allocation data. Funds without data
    appear in funds_missing with a reason and do not affect other funds.
    """
    return await _request("/api/agent/tools/industry-exposure")


@mcp.tool()
async def get_agent_capabilities() -> dict[str, Any]:
    """List read-only tools granted to the current Agent token."""
    return await _request("/api/agent/tools/capabilities")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
