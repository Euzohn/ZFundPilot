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
from mcp.types import ToolAnnotations
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


# MCP tool annotations：仅作客户端提示（ToolAnnotations 所有字段均为 hint），
# 实际安全仍由服务端 scope 与写开关独立校验，不依赖这些注解。
_ANNOT_READ_ONLY = ToolAnnotations(readOnlyHint=True)
# additive 写：只追加不覆盖，幂等键可安全重试。
_ANNOT_ADDITIVE_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True,
)
# 修改/删除/取消类写：可能覆盖或移除既有数据，幂等键可安全重试。
_ANNOT_MUTATING_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=True,
)


mcp = FastMCP(
    "zfundpilot",
    instructions=(
        "Portfolio analysis and controlled tools for ZFundPilot. "
        "Call get_data_status before drawing conclusions from NAV-based data, "
        "and get_agent_capabilities to discover tools granted to this token. "
        "Watchlist writes and data refresh are direct low-risk writes. "
        "run_dca_backtest starts a read-only simulation job (202 + job_id); "
        "poll get_job_status for both refresh and backtest jobs — data.job_type "
        "tells them apart and determines the result shape. "
        "Ledger changes are proposal-only by default: create_operation_proposal "
        "never writes the ledger; an administrator must approve it in the web UI. "
        "Auto-invest plan maintenance (create_plan/update_plan/toggle_plan/"
        "delete_plan) goes through the same proposal tool and requires the "
        "plans:propose scope; new plans are always created disabled. "
        "Alert resolution (resolve_alert) also goes through the same tool and "
        "requires alerts:propose; it only advances the alert state and never "
        "writes the transactions table. "
        "Manual plan execution (execute_plan) uses the same proposal path and "
        "requires transactions:propose; approval inserts one buy transaction "
        "and advances the plan's bookkeeping without recomputing next_run or "
        "triggering the scheduler. "
        "record_transaction is a separately authorized direct-write path for a "
        "single buy/sell the user explicitly says already happened elsewhere; it "
        "requires transactions:create and may still be downgraded to a proposal "
        "(check execution_mode in the response)."
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
        request_id = response.headers.get("X-Request-ID", "")
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                detail = error if isinstance(error, dict) else payload.get(
                    "detail", detail)
                request_id = request_id or str(payload.get("request_id") or "")
        except ValueError:
            pass
        if isinstance(detail, dict):
            code = detail.get("code")
            message = detail.get("message") or code or ""
            detail_text = f"{code}: {message}" if code else str(message)
        else:
            detail_text = str(detail)
        trace = f" (request_id: {request_id})" if request_id else ""

        if response.status_code == 401:
            raise ToolError(
                "Agent token is invalid, expired, or revoked. "
                "Issue a new token in ZFundPilot Settings."
            )
        if response.status_code == 403:
            raise ToolError(
                "Agent token lacks the required scope, admin authentication "
                "is disabled, or the Agent write switch is off. "
                f"Server detail: {detail_text}{trace}"
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise ToolError(
                f"Rate limited by ZFundPilot. Retry after {retry_after} seconds."
            )
        raise ToolError(
            f"ZFundPilot API error ({response.status_code}): "
            f"{detail_text}{trace}"
        )

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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_portfolio_summary() -> dict[str, Any]:
    """Read portfolio market value, cost, P&L, annualized return, and data-as-of date.

    Amounts use the latest formal NAV; the response includes a data_status summary.
    """
    return await _request("/api/agent/tools/portfolio-summary")


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_data_status() -> dict[str, Any]:
    """Check formal NAV freshness and pending T+1 transactions before analysis."""
    return await _request("/api/agent/tools/data-status")


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_portfolio_health() -> dict[str, Any]:
    """Read the four-dimension health score, risk flags, and structural advice.

    Check data_quality.caveats before interpreting scores, since missing or stale
    NAV data can lower related dimensions.
    """
    return await _request("/api/agent/tools/portfolio-health")


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_transaction(
    tx_id: Annotated[int, Field(ge=1)],
) -> dict[str, Any]:
    """Read one transaction by id, including derived NAV and conversion fields.

    The response includes data.row_digest: pass it as expected_digest when
    creating an update_transaction or delete_transaction proposal for this row.
    For a conversion leg, row_digest is also used as expected_from_digest /
    expected_to_digest when creating a delete_conversion proposal for the pair.

    Args:
        tx_id: Transaction id.
    """
    return await _request(f"/api/agent/tools/transactions/{tx_id}")


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_ADDITIVE_WRITE)
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


@mcp.tool(annotations=_ANNOT_MUTATING_WRITE)
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


@mcp.tool(annotations=_ANNOT_MUTATING_WRITE)
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


@mcp.tool(annotations=_ANNOT_ADDITIVE_WRITE)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_job_status(job_id: int) -> dict[str, Any]:
    """Get the status of a job started by start_data_refresh or run_dca_backtest.

    ``data.job_type`` is ``data_refresh`` or ``dca_backtest`` and determines the
    shape of ``data.result``; ``data.status`` is queued/running and then
    succeeded/failed/interrupted. Requires ``data:refresh`` for refresh jobs or
    ``funds:read`` for backtest jobs.

    Args:
        job_id: The job_id returned by start_data_refresh or run_dca_backtest.
    """
    if not isinstance(job_id, int) or job_id <= 0:
        raise ToolError("job_id must be a positive integer.")
    return await _request(f"/api/agent/tools/refresh/{job_id}")


@mcp.tool(annotations=_ANNOT_ADDITIVE_WRITE)
async def create_operation_proposal(
    operation_type: str,
    params: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    """Create a ledger/plan/alert proposal for a human to approve in the web UI.

    This does NOT write the ledger. It only creates a pending proposal; the
    administrator must approve it on the Proposals page in the ZFundPilot web
    UI (top-level sidebar entry, not under Settings), and the server then
    executes it.

    Supported operation types:
      - "add_transaction": add a transaction (buy/sell/dividend/reinvest).
        Dividend/reinvest may optionally carry dividend_alert_id to atomically
        mark the matching pending dividend alert as confirmed.
      - "update_transaction": modify one existing transaction. Requires the
        target tx_id and its current row_digest (from get_transaction); the
        server rejects the approval with a conflict if the row changed in the
        meantime. Conversion legs cannot be modified individually.
      - "delete_transaction": delete one existing transaction. Requires tx_id
        and row_digest; conversion legs cannot be deleted individually.
      - "add_conversion": record a fund conversion as two linked legs (sell the
        from fund, buy the to fund) sharing one conversion_id. Written
        atomically on approval. Never fetches NAVs.
      - "delete_conversion": delete a whole conversion pair (both legs) at
        once. Requires conversion_id plus both legs' row_digest; use
        delete_transaction for non-conversion rows.
      - "batch_import": append several transactions in one proposal. All items
        are validated first and written atomically on approval: either every
        row is inserted or none. Use this instead of many add_transaction
        proposals when importing a batch of already-happened trades.
      - "create_plan": create an auto-invest (DCA) plan. New plans are always
        created disabled; the scheduler never runs them until an admin
        approves a separate toggle_plan proposal. Plan operations never write
        transactions.
      - "update_plan": modify plan config fields (partial patch). Requires
        plan_id and its current row_digest (from list_auto_invest_plans).
        Explicit null clears day_of_week/day_of_month; the merged config is
        re-validated as a whole.
      - "toggle_plan": enable or disable a plan. Requires plan_id,
        row_digest, and an explicit enable boolean. next_run is not
        recomputed (same behavior as the web UI toggle); enabling a plan
        whose next_run is overdue lets the scheduler catch up one run soon.
      - "delete_plan": delete a plan. Requires plan_id and row_digest.
        Historical transactions are kept.
      - "resolve_alert": advance a pending dividend or take-profit/stop-loss
        alert to confirmed or ignored. Requires the alert's alert_type,
        alert_id, expected_digest (the row_digest from list_alerts), and
        status (confirmed/ignored; no rollback to pending). A dividend alert
        confirmed with status=confirmed may optionally carry tx_id to link one
        existing dividend/reinvestment transaction; no new transaction is
        created. This operation only advances the alert state and never
        writes the transactions table.
      - "backfill_transaction_navs": fill in the missing NAV (and the derived
        shares/amount/fee) of one or more existing transactions whose nav is
        still NULL. Requires items (1-50), each with tx_id, expected_digest
        (the row_digest from get_transaction), and an optional fee (required
        only when the server cannot compute it at creation; a sell with no buy
        record also requires an explicit fee). Only explicit tx_ids are
        accepted — there is no "backfill everything". Dividend rows are
        rejected (a dividend's nav is the per-share payout, not a fund NAV).
        All NAVs/fees are snapshotted at creation outside the write
        transaction; approval never touches the network. The whole batch is
        written atomically on approval, or rejected if any row was filled or
        changed in the meantime.
      - "execute_plan": manually execute one existing auto-invest (DCA) plan.
        Requires plan_id and its current row_digest (from
        list_auto_invest_plans), an optional trade_date (defaults to today;
        only the last 7 days are allowed), and an optional fee (required only
        when the server cannot compute the purchase fee at creation). Approval
        inserts one buy transaction (amount/channel/note from the plan, NAV and
        shares still unset, T+1 flag fixed at creation) and advances the plan's
        last_run/last_tx_id without recomputing next_run or triggering the
        scheduler. Purchasability is checked strictly at creation and approval;
        fee/NAV are snapshotted at creation, so approval never touches the
        network. Repeated execution for the same plan and trade_date is
        rejected.

    Args:
        operation_type: "add_transaction", "update_transaction",
            "delete_transaction", "add_conversion", "delete_conversion",
            "batch_import", "create_plan", "update_plan", "toggle_plan",
            "delete_plan", "resolve_alert", "backfill_transaction_navs", or
            "execute_plan".
        params: For add_transaction: fund_code, action (buy/sell/dividend/
            reinvest), date (YYYY-MM-DD), fee, channel, note, is_t1, optional
            dividend_alert_id (dividend/reinvest only), and the
            amount/shares/nav combination required by the action: buy and
            reinvest need amount or shares; sell needs shares; dividend needs
            amount. nav may be omitted while awaiting T+1 confirmation.
            For update_transaction: tx_id, expected_digest (the row_digest from
            get_transaction), plus the full post-change field set (fund_code,
            action, date, amount, shares, nav, fee, channel, note, is_t1) —
            partial updates are not supported.
            For delete_transaction: tx_id, expected_digest, and an optional
            reason (max 500 chars).
            For add_conversion: from_code, to_code (both registered, different),
            date, from_shares, optional from_nav/from_fee, optional
            to_amount/to_nav/to_fee, channel, note, is_t1. Non-T+1 requires a
            derivable to-leg amount or shares; T+1 may defer it.
            For delete_conversion: conversion_id, expected_from_digest,
            expected_to_digest (both row_digest values, e.g. from
            list_transactions?conversion_id=... then get_transaction), and an
            optional reason.
            For batch_import: transactions (1-50 items), each with fund_code
            (required, no fund_name), action, date, the amount/shares/nav
            combination required by the action, and optional fee/channel/note/
            is_t1; plus an optional overall note. Never clears existing rows.
            For create_plan: fund_code, amount (>0), cadence (daily/week/
            biweek/month), day_of_week (0-6, 0=Monday; required for week/
            biweek, forbidden otherwise), day_of_month (1-31; required for
            month, forbidden otherwise), optional channel/note. enabled,
            next_run, last_run and last_tx_id are rejected.
            For update_plan: plan_id, expected_digest (the row_digest from
            list_auto_invest_plans), plus any subset of the create_plan
            config fields to change.
            For toggle_plan: plan_id, expected_digest, enable (bool).
            For delete_plan: plan_id, expected_digest.
            For resolve_alert: alert_type (dividend/take_profit/stop_loss),
            alert_id, expected_digest (the row_digest from list_alerts),
            status (confirmed/ignored; no rollback to pending), and an
            optional tx_id (dividend + confirmed only; links one existing
            dividend/reinvestment transaction, does not create one).
            For backfill_transaction_navs: items (1-50), each with tx_id,
            expected_digest (the row_digest from get_transaction), and an
            optional fee (required only when the server cannot compute the
            fee offline; omit otherwise).
            For execute_plan: plan_id, expected_digest (the row_digest from
            list_auto_invest_plans), an optional trade_date (YYYY-MM-DD;
            defaults to today, only the last 7 days are allowed), and an
            optional fee (required only when the purchase fee cannot be
            computed at creation). amount/is_t1/channel/note and scheduler
            bookkeeping fields are rejected.
        idempotency_key: Unique retry key (16-128 chars); same key+params
            returns the same proposal.
    """
    _validate_write_key(idempotency_key)
    if operation_type not in (
            "add_transaction", "update_transaction", "delete_transaction",
            "add_conversion", "delete_conversion", "batch_import",
            "create_plan", "update_plan", "toggle_plan", "delete_plan",
            "resolve_alert", "backfill_transaction_navs", "execute_plan"):
        raise ToolError(
            'operation_type must be "add_transaction", "update_transaction", '
            '"delete_transaction", "add_conversion", "delete_conversion", '
            '"batch_import", "create_plan", "update_plan", "toggle_plan", '
            '"delete_plan", "resolve_alert", "backfill_transaction_navs", or '
            '"execute_plan".')
    if not isinstance(params, dict):
        raise ToolError("params must be an object.")
    return await _post(
        "/api/agent/tools/proposals",
        {"operation_type": operation_type, "params": params},
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool(annotations=_ANNOT_ADDITIVE_WRITE)
async def record_transaction(
    fund_code: str,
    action: str,
    date: str,
    idempotency_key: str,
    amount: float | None = None,
    shares: float | None = None,
    nav: float | None = None,
    fee: float = 0.0,
    channel: str = "",
    note: str = "",
    is_t1: bool = False,
) -> dict[str, Any]:
    """Directly record ONE buy/sell the user says already happened externally.

    Use this only when the user explicitly states that a buy or sell has already
    been completed on an external platform. Never infer a transaction from a
    screenshot, forecast, recommendation, or portfolio suggestion; use
    create_operation_proposal for reconciliation-style input instead.

    Requires the transactions:create scope. Prechecks may downgrade the request
    to a pending proposal (for example suspected duplicate, insufficient shares,
    or amount over the direct-write cap). Always inspect
    data.execution_mode: "direct" means the ledger was written; "proposal" means
    nothing was written and an administrator must approve it in the web UI.

    The receipt's data.receipt.unconfirmed_fields lists fields awaiting T+1/NAV
    backfill. Do not present an estimated NAV as the confirmed execution NAV.

    Args:
        fund_code: Six-digit fund code.
        action: "buy" or "sell" (direct write supports only these two).
        date: Trade date YYYY-MM-DD; must not be in the future.
        idempotency_key: Unique retry key (16-128 chars); retries with the same
            key and params never create a second transaction or upgrade a
            downgraded proposal to a direct write.
        amount: Buy amount including fee, or sell proceeds. For buy, provide
            amount or shares; for sell, shares is required.
        shares: Confirmed shares, if known.
        nav: Confirmed execution NAV; omit while awaiting T+1 confirmation.
        fee: Fee amount (default 0).
        channel: Purchase channel, e.g. "支付宝"; keep it consistent with
            existing ledger rows for share and duplicate checks.
        note: Optional note.
        is_t1: True when the trade awaits T+1 confirmation.
    """
    _validate_write_key(idempotency_key)
    if action not in ("buy", "sell"):
        raise ToolError('action must be "buy" or "sell" for direct write.')
    _validate_date(date, "date")
    if not re.fullmatch(r"\d{6}", fund_code):
        raise ToolError("fund_code must be a six-digit code.")
    if amount is None and shares is None:
        raise ToolError("Provide amount or shares.")
    body = {
        "fund_code": fund_code,
        "action": action,
        "date": date,
        "amount": amount,
        "shares": shares,
        "nav": nav,
        "fee": fee,
        "channel": channel,
        "note": note,
        "is_t1": is_t1,
    }
    return await _post(
        "/api/agent/tools/transactions", body,
        headers={"Idempotency-Key": idempotency_key},
    )


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def precheck_transactions(payload: dict[str, Any]) -> dict[str, Any]:
    """Pre-check transactions before proposing them. Read-only, never writes.

    Validates CSV text or an items array: resolves funds (against the ledger's
    registered funds), checks field validity, and detects duplicates against
    both the ledger and pending proposals. Returns a structured report per item
    with status valid/invalid/duplicate and a proposal_ready flag.

    This does NOT write the ledger and does NOT create a proposal. Use it to
    preview what create_operation_proposal would accept or reject, so the user
    can fix issues first.

    Args:
        payload: The precheck input. Must contain "format" ("csv" or "items").
            - csv: {"format": "csv", "csv_text": str, "channel_hint"?: str}
            - items: {"format": "items", "items": [{fund_code or fund_name,
              action, date, amount?, shares?, nav?, fee?, channel?, note?,
              is_t1?}], "channel_hint"?: str}
            At most 200 items. CSV text at most 5 MB.
    """
    if not isinstance(payload, dict):
        raise ToolError("payload must be an object.")
    return await _post(
        "/api/agent/tools/precheck/transactions", {"input": payload})


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def precheck_reconciliation(payload: dict[str, Any]) -> dict[str, Any]:
    """Pre-check a holdings reconciliation against the ledger. Read-only.

    Compares screenshot-parsed holdings against recorded positions by channel,
    computes share differences, and suggests adjustment transactions (buy/sell)
    with estimated NAV. Returns a diff table with a proposal_ready flag per
    item. Funds not registered in the ledger are reported in
    fund_resolution_errors and skipped. "maybe_sold" entries (held in the
    ledger but absent from the input) are hints only: proposal_ready is false
    and the user must confirm before any sell proposal.

    This does NOT write the ledger and does NOT create a proposal. Use
    create_operation_proposal to submit the suggested transactions after the
    user confirms them.

    Args:
        payload: {"holdings": [{fund_code or fund_name, shares, market_value?}],
          "channel"?: str}. At most 100 holdings. shares must be a
          non-negative finite number.
    """
    if not isinstance(payload, dict):
        raise ToolError("payload must be an object.")
    return await _post(
        "/api/agent/tools/precheck/reconciliation", {"input": payload})


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def precheck_backfill(payload: dict[str, Any]) -> dict[str, Any]:
    """Pre-check which transactions can have their NAV backfilled. Read-only.

    Lists transactions whose nav is still NULL and reports, per row, whether
    a fund NAV is available in the local NAV table, whether the fee must be
    fetched or supplied at proposal creation, and the NAV date that would be
    used (T+1 transactions use the next trading day's NAV). This pre-check is
    fully offline: a row with a missing fee is marked fee_source="needs_fee"
    (fee_pending=true) instead of fetching fee rates. Each row includes its
    row_digest, so you can build a backfill_transaction_navs proposal directly
    from the output.

    Dividend rows are reported as not backfillable: a dividend's nav is the
    per-share payout, not a fund NAV.

    This does NOT write the ledger and does NOT create a proposal. Requires the
    transactions:propose scope.

    Args:
        payload: {"tx_ids"?: [int, ...]}. Omit tx_ids to list all nav-NULL
          non-dividend rows (capped at 50); pass tx_ids to check specific rows
          (at most 50, no duplicates). Read-only either way.
    """
    if not isinstance(payload, dict):
        raise ToolError("payload must be an object.")
    return await _post("/api/agent/tools/precheck/backfill", payload)


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_operation_proposal(proposal_id: int) -> dict[str, Any]:
    """Get one proposal created by the current token.

    Args:
        proposal_id: Proposal id returned by create_operation_proposal.
    """
    if not isinstance(proposal_id, int) or proposal_id <= 0:
        raise ToolError("proposal_id must be a positive integer.")
    return await _request(f"/api/agent/tools/proposals/{proposal_id}")


@mcp.tool(annotations=_ANNOT_MUTATING_WRITE)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def list_alerts(
    type: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List dividend and take-profit/stop-loss alerts.

    status is a business processing state (pending/confirmed/ignored), not read/unread.

    Each alert includes row_digest: use it as the expected_digest for
    resolve_alert proposals (it covers the alert's business fields plus
    status/resolved_at/tx_id, so any state change alters it).

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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def list_auto_invest_plans(
    enabled: bool | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List auto-invest plans with derived status (active/paused/due).

    Each plan carries a row_digest: the config fingerprint required as
    expected_digest by update_plan/toggle_plan/delete_plan proposals
    (create_operation_proposal). Re-read it before proposing if the plan
    may have changed.

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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_risk_report() -> dict[str, Any]:
    """Read drawdown, volatility, concentration, structure weights, and risk flags.

    Check data_quality.caveats before interpreting metrics; missing or stale NAV
    data can distort them.
    """
    return await _request("/api/agent/tools/risk-report")


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_industry_exposure() -> dict[str, Any]:
    """Read portfolio industry exposure by looking through fund allocations.

    May be slow because it fetches external allocation data. Funds without data
    appear in funds_missing with a reason and do not affect other funds.
    """
    return await _request("/api/agent/tools/industry-exposure")


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
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


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def run_dca_backtest(
    fund_codes: Annotated[list[str], Field(min_length=1, max_length=5)],
    start_date: str,
    end_date: str,
    amount_per_period: float,
    idempotency_key: str,
    cadence: str = "month",
    include_lumpsum: bool = True,
    include_curve: bool = True,
    include_periods: bool = False,
    max_points: Annotated[int, Field(ge=10, le=2000)] = 365,
) -> dict[str, Any]:
    """Start a historical DCA simulation job; poll ``get_job_status`` for results.

    Read-only: it never writes NAV data, transactions, plans, or fund metadata.
    The call returns HTTP 202 with a ``job_id``; pass that job_id to
    ``get_job_status`` until ``status`` is ``succeeded``/``failed``/
    ``interrupted``. Same key + same params returns the same job_id.
    Results are historical simulations, not forecasts or allocation advice.
    Per-fund status/code/message explain insufficient NAV or partial coverage;
    unknown fee tables are flagged instead of being reported as zero cost.

    Args:
        fund_codes: 1-5 six-digit fund codes; duplicates are removed.
        start_date: Inclusive start date (YYYY-MM-DD), before end_date.
        end_date: Inclusive end date (YYYY-MM-DD), not after today in China time.
        amount_per_period: Amount per fund per period, > 0 and <= 1,000,000.
        idempotency_key: Unique retry key (16-128 chars); same key+params
            returns the same job_id.
        cadence: "month", "week", or "biweek".
        include_lumpsum: Add a lump-sum comparison per fund.
        include_curve: Return the sampled portfolio value curve.
        include_periods: Return per-period purchase details (larger response).
        max_points: Maximum curve points (10-2000, first/last preserved).
    """
    _validate_write_key(idempotency_key)
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
    }, headers={"Idempotency-Key": idempotency_key})


@mcp.tool(annotations=_ANNOT_READ_ONLY)
async def get_agent_capabilities() -> dict[str, Any]:
    """List read-only tools granted to the current Agent token."""
    return await _request("/api/agent/tools/capabilities")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
