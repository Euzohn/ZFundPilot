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

import math
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
        "Portfolio analysis and controlled tools for ZFundPilot. "
        "Call get_data_status before drawing conclusions from NAV-based data, "
        "and get_agent_capabilities to discover tools granted to this token. "
        "Watchlist writes and data refresh are direct low-risk writes. "
        "Ledger changes are proposal-only: create_operation_proposal never "
        "writes the ledger; an administrator must approve it in the web UI."
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


async def _send(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """发送请求并统一错误语义；仅由固定工具函数调用。"""
    try:
        async with _make_client() as client:
            response = await client.request(
                method, path, params=params, json=json_body,
                headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(
            f"Cannot reach ZFundPilot at {_base_url()}: {exc}"
        ) from exc

    if response.status_code >= 400:
        detail: object = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail", detail)
        except ValueError:
            pass
        if isinstance(detail, dict):
            code = detail.get("code")
            message = detail.get("message") or code or ""
            detail_text = f"{code}: {message}" if code else str(message)
        else:
            detail_text = str(detail)

        if response.status_code == 401:
            raise ToolError(
                "Agent token is invalid, expired, or revoked. "
                "Issue a new token in ZFundPilot Settings."
            )
        if response.status_code == 403:
            raise ToolError(
                "Agent token lacks the required scope, admin authentication "
                "is disabled, or the Agent write switch is off. "
                f"Server detail: {detail_text}"
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise ToolError(
                f"Rate limited by ZFundPilot. Retry after {retry_after} seconds."
            )
        raise ToolError(
            f"ZFundPilot API error ({response.status_code}): {detail_text}")

    try:
        return response.json()
    except ValueError as exc:
        raise ToolError("ZFundPilot returned a non-JSON response.") from exc


async def _request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET 请求（保持既有工具的参数行为）。"""
    return await _send("GET", path, params=params)


async def _post(path: str, body: dict[str, Any],
                headers: dict[str, str] | None = None) -> dict[str, Any]:
    """POST 请求；路径由工具函数写死，不接受调用方传入。"""
    return await _send("POST", path, json_body=body, headers=headers)


async def _delete(path: str, params: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> dict[str, Any]:
    """DELETE 请求；路径与参数由工具函数按契约构造。"""
    return await _send("DELETE", path, params=params, headers=headers)


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

def _validate_write_key(value: str) -> str:
    """校验幂等键，尽早给出可读错误；服务端仍会再次校验。"""
    if not (16 <= len(value or "") <= 128):
        raise ToolError("idempotency_key must be 16-128 characters.")
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
        raise ToolError("idempotency_key contains unsupported characters.")
    return value


@mcp.tool()
async def add_watchlist_item(
    fund_code: str,
    idempotency_key: str,
    note: str = "",
    group_name: str = "",
) -> dict[str, Any]:
    """Add a fund to the watchlist. This is a write operation.

    The fund must already be registered in ZFundPilot; this tool never creates
    transactions, plans, or fund metadata.

    Args:
        fund_code: Six-digit fund code, e.g. "005827".
        idempotency_key: Unique retry key (16-128 chars); reuse it only for the
            exact same request.
        note: Optional note (max 500 chars).
        group_name: Optional watchlist group (max 50 chars).
    """
    if not re.fullmatch(r"\d{6}", fund_code or ""):
        raise ToolError("fund_code must be exactly 6 digits.")
    _validate_write_key(idempotency_key)
    return await _send(
        "POST", "/api/agent/tools/watchlist",
        json_body={"fund_code": fund_code, "note": note,
                   "group_name": group_name},
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool()
async def update_watchlist_item(
    fund_code: str,
    expected_revision: int,
    idempotency_key: str,
    note: str | None = None,
    group_name: str | None = None,
) -> dict[str, Any]:
    """Update a watchlist note or group. This is a write operation.

    Read list_watchlist first to get the item's current revision. Omitted
    fields are left unchanged; an empty string clears the field.

    Args:
        fund_code: Six-digit fund code.
        expected_revision: Revision returned by list_watchlist.
        idempotency_key: Unique retry key (16-128 chars).
        note: New note; omit to keep the current value.
        group_name: New group; omit to keep the current value.
    """
    if not re.fullmatch(r"\d{6}", fund_code or ""):
        raise ToolError("fund_code must be exactly 6 digits.")
    _validate_write_key(idempotency_key)
    if expected_revision < 1:
        raise ToolError("expected_revision must be a positive integer.")
    body: dict[str, Any] = {"expected_revision": expected_revision}
    if note is not None:
        body["note"] = note
    if group_name is not None:
        body["group_name"] = group_name
    return await _send(
        "PATCH", f"/api/agent/tools/watchlist/{fund_code}",
        json_body=body,
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool()
async def remove_watchlist_item(
    fund_code: str,
    expected_revision: int,
    idempotency_key: str,
) -> dict[str, Any]:
    """Remove a fund from the watchlist. This is a write operation.

    Deletion keeps a recoverable previous value for the web administrator.

    Args:
        fund_code: Six-digit fund code.
        expected_revision: Revision returned by list_watchlist.
        idempotency_key: Unique retry key (16-128 chars).
    """
    if not re.fullmatch(r"\d{6}", fund_code or ""):
        raise ToolError("fund_code must be exactly 6 digits.")
    _validate_write_key(idempotency_key)
    if expected_revision < 1:
        raise ToolError("expected_revision must be a positive integer.")
    return await _delete(
        f"/api/agent/tools/watchlist/{fund_code}",
        params={"expected_revision": expected_revision},
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool()
async def start_data_refresh(
    idempotency_key: str,
    fund_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Start a NAV/metadata refresh job. This is a write operation.

    Only NAV history and fund metadata are refreshed. It never backfills
    transaction NAVs and never executes auto-invest plans. Poll with
    get_job_status using the returned job_id.

    Args:
        idempotency_key: Unique retry key (16-128 chars); same key+params
            returns the same job_id.
        fund_codes: Up to 50 six-digit codes; omit to refresh current open
            holdings.
    """
    _validate_write_key(idempotency_key)
    if fund_codes is not None:
        if not isinstance(fund_codes, list) or not fund_codes:
            raise ToolError("fund_codes must be a non-empty list.")
        if len(fund_codes) > 50:
            raise ToolError("fund_codes must have at most 50 entries.")
        for code in fund_codes:
            if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
                raise ToolError("fund_codes must be six-digit codes.")
    return await _post(
        "/api/agent/tools/refresh",
        {"fund_codes": fund_codes},
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool()
async def get_job_status(job_id: int) -> dict[str, Any]:
    """Get the status of a data refresh job started with start_data_refresh.

    Args:
        job_id: The job_id returned by start_data_refresh.
    """
    if not isinstance(job_id, int) or job_id <= 0:
        raise ToolError("job_id must be a positive integer.")
    return await _request(f"/api/agent/tools/refresh/{job_id}")


@mcp.tool()
async def create_operation_proposal(
    operation_type: str,
    params: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    """Create a ledger proposal for a human to approve in the web UI.

    This does NOT write the ledger. It only creates a pending proposal; the
    administrator must approve it on the Proposals page in the ZFundPilot web
    UI (top-level sidebar entry, not under Settings), and the server then
    executes it. Currently only operation_type="add_transaction" is supported.

    Args:
        operation_type: Currently only "add_transaction".
        params: For add_transaction: fund_code, action (buy/sell/dividend/
            reinvest), date (YYYY-MM-DD), fee, channel, note, is_t1, and the
            amount/shares/nav combination required by the action: buy and
            reinvest need amount or shares; sell needs shares; dividend needs
            amount. nav may be omitted while awaiting T+1 confirmation.
        idempotency_key: Unique retry key (16-128 chars); same key+params
            returns the same proposal.
    """
    _validate_write_key(idempotency_key)
    if operation_type != "add_transaction":
        raise ToolError('operation_type must be "add_transaction".')
    if not isinstance(params, dict):
        raise ToolError("params must be an object.")
    return await _post(
        "/api/agent/tools/proposals",
        {"operation_type": operation_type, "params": params},
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool()
async def list_operation_proposals(
    status: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List proposals created by the current token (newest first).

    Args:
        status: Optional pending/succeeded/failed/conflict/rejected/
            cancelled/expired.
        limit: Page size (1-200).
        offset: Page offset.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    return await _request("/api/agent/tools/proposals", params)


@mcp.tool()
async def get_operation_proposal(proposal_id: int) -> dict[str, Any]:
    """Get one proposal created by the current token.

    Args:
        proposal_id: Proposal id returned by create_operation_proposal.
    """
    if not isinstance(proposal_id, int) or proposal_id <= 0:
        raise ToolError("proposal_id must be a positive integer.")
    return await _request(f"/api/agent/tools/proposals/{proposal_id}")


@mcp.tool()
async def cancel_operation_proposal(proposal_id: int) -> dict[str, Any]:
    """Cancel one of your pending proposals. Approved/rejected ones cannot cancel.

    This operation is inherently idempotent (a second cancel returns a
    conflict), so no idempotency key is required.

    Args:
        proposal_id: Proposal id returned by create_operation_proposal.
    """
    if not isinstance(proposal_id, int) or proposal_id <= 0:
        raise ToolError("proposal_id must be a positive integer.")
    return await _delete(f"/api/agent/tools/proposals/{proposal_id}")


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
async def search_funds(
    keyword: str,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """Search the fund universe by name or six-digit code substring.

    Returns basic metadata only and does not enrich metrics, so this is the fast
    lookup path. An empty result is a successful query, not an error.

    Args:
        keyword: Name or code substring, 1-100 characters after trimming.
        limit: Page size (1-200).
        offset: Page offset.
    """
    value = keyword.strip()
    if not value:
        raise ToolError("keyword must not be empty.")
    if len(value) > 100:
        raise ToolError("keyword must be at most 100 characters.")
    return await _request("/api/agent/tools/search", {
        "keyword": value, "limit": limit, "offset": offset})


@mcp.tool()
async def screen_funds(
    types: Annotated[list[str] | None, Field(max_length=20)] = None,
    sectors: Annotated[list[str] | None, Field(max_length=20)] = None,
    keyword: str | None = None,
    with_metrics: bool = False,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """Screen the fund universe by asset type, sector, and code/name substring.

    When with_metrics is true, only the first 30 funds of the current page (in
    ascending code order) are enriched; this can be slow and is concurrency
    limited. Missing metrics are reported as unavailable, never as zero.

    Args:
        types: Optional asset types, e.g. ["混合型", "指数型"].
        sectors: Optional sectors, e.g. ["科技"].
        keyword: Optional name or code substring, at most 100 characters.
        with_metrics: Enrich up to 30 funds with return and risk metrics.
        limit: Page size (1-200).
        offset: Page offset.
    """
    params: dict[str, Any] = {"with_metrics": with_metrics,
                              "limit": limit, "offset": offset}
    for field, values in (("types", types), ("sectors", sectors)):
        if values:
            cleaned = list(dict.fromkeys(
                v.strip() for v in values if v and v.strip()))
            if len(cleaned) > 20:
                raise ToolError(f"{field} supports at most 20 values.")
            if cleaned:
                params[field] = cleaned
    if keyword is not None and keyword.strip():
        value = keyword.strip()
        if len(value) > 100:
            raise ToolError("keyword must be at most 100 characters.")
        params["keyword"] = value
    return await _request("/api/agent/tools/screen", params)


@mcp.tool()
async def run_dca_backtest(
    fund_codes: Annotated[list[str], Field(min_length=1, max_length=5)],
    start_date: str,
    end_date: str,
    amount_per_period: float,
    cadence: str = "month",
    include_lumpsum: bool = True,
    include_curve: bool = True,
    include_periods: bool = False,
    max_points: Annotated[int, Field(ge=10, le=2000)] = 365,
) -> dict[str, Any]:
    """Simulate a historical DCA plan, optionally with a lump-sum comparison.

    Read-only: it never writes NAV data, transactions, plans, or fund metadata.
    Results are historical simulations, not forecasts or allocation advice.
    Per-fund status/code/message explain insufficient NAV or partial coverage;
    unknown fee tables are flagged instead of being reported as zero cost.

    Args:
        fund_codes: 1-5 six-digit fund codes; duplicates are removed.
        start_date: Inclusive start date (YYYY-MM-DD), before end_date.
        end_date: Inclusive end date (YYYY-MM-DD), not after today in China time.
        amount_per_period: Amount per fund per period, > 0 and <= 1,000,000.
        cadence: "month", "week", or "biweek".
        include_lumpsum: Add a lump-sum comparison per fund.
        include_curve: Return the sampled portfolio value curve.
        include_periods: Return per-period purchase details (larger response).
        max_points: Maximum curve points (10-2000, first/last preserved).
    """
    if len(fund_codes) > 5:
        raise ToolError("fund_codes supports at most 5 items.")
    cleaned: list[str] = []
    for raw in fund_codes:
        if not isinstance(raw, str):
            raise ToolError("fund_codes must contain strings.")
        code = raw.strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ToolError(f"fund_codes must contain six-digit codes, got: {raw!r}.")
        if code not in cleaned:
            cleaned.append(code)
    if not cleaned:
        raise ToolError("fund_codes must contain at least one code.")

    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if start is None or end is None:
        raise ToolError("start_date and end_date are required.")
    if start >= end:
        raise ToolError("start_date must be earlier than end_date.")

    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end, "%Y-%m-%d").date()
    today = datetime.now(config.TIMEZONE).date()
    if end_dt > today:
        raise ToolError("end_date must not be later than today in China time.")
    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    if months > 120 or (months == 120 and end_dt.day > start_dt.day):
        raise ToolError("The backtest range must not exceed 10 years.")

    if isinstance(amount_per_period, bool) or not isinstance(
            amount_per_period, (int, float)):
        raise ToolError("amount_per_period must be a number.")
    if not math.isfinite(amount_per_period) or amount_per_period <= 0:
        raise ToolError("amount_per_period must be a finite positive number.")
    if amount_per_period > 1_000_000:
        raise ToolError("amount_per_period must not exceed 1,000,000.")
    if cadence not in ("month", "week", "biweek"):
        raise ToolError("cadence must be 'month', 'week', or 'biweek'.")
    if isinstance(max_points, bool) or not isinstance(max_points, int):
        raise ToolError("max_points must be an integer.")
    if not 10 <= max_points <= 2000:
        raise ToolError("max_points must be between 10 and 2000.")

    return await _post("/api/agent/tools/backtest/dca", {
        "fund_codes": cleaned,
        "start_date": start,
        "end_date": end,
        "amount_per_period": amount_per_period,
        "cadence": cadence,
        "include_lumpsum": include_lumpsum,
        "include_curve": include_curve,
        "include_periods": include_periods,
        "max_points": max_points,
    })


@mcp.tool()
async def get_agent_capabilities() -> dict[str, Any]:
    """List read-only tools granted to the current Agent token."""
    return await _request("/api/agent/tools/capabilities")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
