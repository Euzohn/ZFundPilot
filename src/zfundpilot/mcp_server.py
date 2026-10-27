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
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0

mcp = FastMCP(
    "zfundpilot",
    instructions=(
        "Read-only portfolio analysis from ZFundPilot. "
        "Call get_data_status before drawing conclusions from NAV-based data."
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
