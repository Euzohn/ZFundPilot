# ZFundPilot Agent Read-only API

This document is for users who want AI agents (Claude Desktop, Cursor, custom MCP servers, scripts, etc.) to read portfolio data from ZFundPilot.

The Agent API is strictly read-only. It **does not expose trading, settings, import/export, or any fund-moving operations**. It uses Agent tokens that are independent of web login tokens, scoped, default-deny, and revocable.

> 中文版本：[AGENT_API.md](./AGENT_API.md)

---

## 1. Prerequisites

- Admin password authentication must be enabled (`AUTH_ENABLED=True`). When no password is configured, Agent tokens can be neither issued nor used.
- The default deployment listens on localhost or behind a controlled reverse proxy. Use HTTPS for remote access.
- Send the token only in the `Authorization` header. **Never** put it in URLs, browser persistent storage, or model prompts.

---

## 2. Issuing and managing tokens

In the web UI, go to **Settings → Account & Security → Agent Access Tokens**. The plaintext is shown only once; only its SHA-256 digest is stored server-side.

You can also call the management API directly (these require a **web login token**, not an Agent token):

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/agent/tokens` | List token metadata (no plaintext or digest) |
| `POST` | `/api/agent/tokens` | Issue a token; plaintext returned once |
| `DELETE` | `/api/agent/tokens/{id}` | Revoke a token (idempotent) |

Example:

```bash
# 1. Obtain a web login token
WEB_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}' | jq -r .token)

# 2. Issue an Agent token
curl -s -X POST http://localhost:8000/api/agent/tokens \
  -H "Authorization: Bearer $WEB_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "claude-desktop",
    "scopes": ["portfolio:read", "funds:read", "health:read"],
    "expires_in_days": 90
  }' | jq
```

The `token` field in the response (format `zfag_xxx`) is the plaintext Agent token. `token_info` contains only metadata: `id`, name, prefix, scopes, and timestamps.

Request body:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | 1–64 characters, identifies the caller |
| `scopes` | string[] | No | Defaults to all three read scopes; unknown or write scopes are rejected |
| `expires_in_days` | int \| null | No | 1–3650 days, default 90; `null` means no expiry |

---

## 3. Scopes

| Scope | Allowed tools |
|---|---|
| `portfolio:read` | `portfolio-summary`, `positions` |
| `funds:read` | `funds/{code}` |
| `health:read` | `data-status` |

There are no write scopes. Calling a tool without the required scope returns **403**.

---

## 4. Conventions

### Request

```http
GET /api/agent/tools/portfolio-summary HTTP/1.1
Host: localhost:8000
Authorization: Bearer zfag_xxxxxxxx
```

### Response envelope

Every successful tool call returns the same envelope:

```json
{
  "schema_version": 1,
  "tool": "get_portfolio_summary",
  "generated_at": "2026-10-27T21:30:00+08:00",
  "currency": "CNY",
  "data": { }
}
```

- `schema_version`: response schema version, currently `1`. Additive fields do not bump it; only breaking changes do.
- `tool`: tool name matching the endpoint.
- `generated_at`: server-side timestamp with timezone.
- `currency`: amount currency, currently always `CNY`.
- `data`: tool-specific payload.

### Errors

Standard FastAPI error shape:

```json
{ "detail": "Agent token 缺少权限：funds:read" }
```

| Status | Meaning |
|---|---|
| `400` | Invalid parameter (e.g. fund code is not 6 digits) |
| `401` | Missing, invalid, expired, or revoked token |
| `403` | Valid token but missing required scope, or password auth not enabled |
| `404` | Unknown tool or fund (only with a valid token) |
| `429` | Rate limit exceeded; see `Retry-After` |

> `/api/agent/tools/*` is protected by a dedicated Agent auth middleware. Even a nonexistent tool path returns `401` without a valid token, so route existence is not leaked.

### Rate limiting

**120 requests per minute** per token per endpoint. Exceeding it returns `429`; retry after the `Retry-After` seconds.

### Valuation basis

Amounts are based on the **latest formal NAV** and marked with `data.valuation_basis = "latest_formal_nav"`.

- `as_of_date` is the maximum formal NAV date among holdings; it does **not** mean every fund is up to date.
- The API does **not** return intraday estimates, to avoid mixing them with formal NAV. Use `data-status` to check completeness.

---

## 5. Tools

### 5.1 `GET /api/agent/tools/portfolio-summary`

Portfolio-level summary. Scope: `portfolio:read`.

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  http://localhost:8000/api/agent/tools/portfolio-summary | jq
```

Key `data` fields:

| Field | Description |
|---|---|
| `total_cost` | Current holding cost |
| `total_value` | Market value at latest formal NAV |
| `unrealized_pnl` / `realized_pnl` / `total_pnl` | Unrealized / realized / total P&L |
| `total_return` | Unrealized return rate |
| `annualized_return` | XIRR annualized return, may be `null` |
| `total_buy` / `total_sell` / `total_dividend` | Cumulative buy / sell / dividend |
| `holding_count` | Number of funds currently held |
| `max_single_weight` / `max_single_name` | Largest single-fund weight and name |
| `as_of_date` | Latest formal NAV date (see valuation note) |
| `daily_pnl` / `daily_return` | Today's P&L amount / rate |
| `week_*` / `month_*` / `year_*` | Week / month / year P&L and return |
| `data_status` | Data status summary, see 5.2 |

### 5.2 `GET /api/agent/tools/data-status`

Formal NAV and T+1 pending-transaction summary. Scope: `health:read`.

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  http://localhost:8000/api/agent/tools/data-status | jq
```

| Field | Description |
|---|---|
| `as_of_date` | Latest formal NAV date |
| `as_of_date_semantics` | Chinese note explaining that `as_of_date` is the maximum date, not a whole-portfolio update |
| `missing_nav_fund_count` | Funds with confirmed shares but no formal NAV (deduplicated by code) |
| `stale_nav_fund_count` | Funds whose latest NAV is older than the tolerance window (exclusive with missing; weekends/holidays do not trigger false positives) |
| `pending_t1_transaction_count` | T+1 transactions awaiting NAV confirmation (non-dividend, `is_t1` with empty NAV) |

### 5.3 `GET /api/agent/tools/positions`

Holdings list. Scope: `portfolio:read`. Split by fund × channel, sorted by market value descending.

Query parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_closed` | bool | `false` | Include fully closed positions |
| `limit` | int | `200` | 1–500; out-of-range returns 422 |

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  "http://localhost:8000/api/agent/tools/positions?limit=50" | jq
```

`data` fields:

| Field | Description |
|---|---|
| `count` / `total` / `limit` | Returned count / total / applied limit |
| `include_closed` | Whether closed positions are included |
| `valuation_basis` | Always `latest_formal_nav` |
| `positions` | Position array, see below |

Each position (`Position.to_dict()`):

| Field | Description |
|---|---|
| `fund_code` / `fund_name` / `fund_type` / `sector` / `channel` | Fund and channel info |
| `risk_level` / `tracking_index` | Risk level and tracking index |
| `held_shares` | Current shares |
| `total_cost` | Current holding cost |
| `pending_buy_cost` | Pending buy amount (excluded from market value/P&L) |
| `avg_cost_nav` | Average cost NAV |
| `latest_nav` / `latest_date` | Latest formal NAV and date |
| `market_value` / `unrealized_pnl` / `realized_pnl` / `total_pnl` | Market value and P&L |
| `return_rate` / `annualized_return` | Unrealized return / XIRR annualized |
| `weight` | Weight in portfolio market value |
| `buy_count` / `sell_count` / `dividend_count` / `dividend_total` | Transaction and dividend stats |
| `is_open` | Whether still held (including pending) |

### 5.4 `GET /api/agent/tools/funds/{code}`

Single fund detail. Scope: `funds:read`.

Path parameter `code` must be 6 digits (otherwise `400`); unknown fund returns `404`.

Query parameter `nav_limit` defaults to `30` (range 1–250).

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  "http://localhost:8000/api/agent/tools/funds/005827?nav_limit=10" | jq
```

`data` fields:

| Field | Description |
|---|---|
| `fund` | Fund metadata (code, name, type, sector, tracking index, dividend method, purchase status, limits, risk level, etc.) |
| `valuation_basis` | Always `latest_formal_nav` |
| `latest_formal_nav` | `{date, nav, accumulated_nav, source}`, or `null` |
| `annualized_return` | Fund XIRR annualized, may be `null` |
| `positions` | Current holdings of this fund across channels (same shape as 5.3) |
| `recent_nav` | Recent `nav_limit` formal NAV points: `{date, nav, accumulated_nav}` |

> This endpoint does not return intraday estimates. If you need an approximate intraday move, use the web UI estimate feature and treat it as non-formal.

---

## 6. Minimal integration

### Python

```python
import os
import requests

BASE = os.getenv("ZFUND_BASE_URL", "http://localhost:8000")
TOKEN = os.environ["ZFUND_AGENT_TOKEN"]  # never hardcode or put in prompts

def call(tool: str, **params):
    r = requests.get(
        f"{BASE}/api/agent/tools/{tool}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

summary = call("portfolio-summary")["data"]
positions = call("positions", limit=20)["data"]["positions"]
```

### Function calling / MCP tool definition (illustrative)

```json
{
  "name": "get_portfolio_summary",
  "description": "Read ZFundPilot portfolio value, P&L, and data-as-of date. Read-only.",
  "parameters": { "type": "object", "properties": {}, "additionalProperties": false }
}
```

Maps to:

```http
GET /api/agent/tools/portfolio-summary
Authorization: Bearer zfag_xxx
```

An MCP adapter is not bundled yet; wrap these four endpoints with any HTTP tool. Agents should call `data-status` before analysis to avoid drawing conclusions from stale NAV data.

---

## 7. Security and operations

- **Separate credentials**: Agent and web tokens are not interchangeable. A web token calling a tool gets `401`; an Agent token cannot call web management endpoints.
- **Default deny**: Tool paths are checked by the Agent middleware first, then authorized by scope dependencies. Management endpoints also verify the web token themselves.
- **Digest only**: The database stores only the SHA-256 digest and a 12-character prefix. Plaintext is returned once at issuance.
- **Revocation**: Revoke from Settings at any time; it takes effect immediately. Issue one token per agent for easier tracing and cleanup.
- **Audit**: Issuance, revocation, auth success/failure, and rate limiting are audited. Only token prefixes are recorded — never plaintext or full responses.
- **Network**: Remote access must go through an HTTPS reverse proxy; do not expose the port directly. Revoke and reissue if a token leaks.
- **Scope**: The initial read scopes cover portfolio, funds, and data status only. Write and export endpoints are not available to Agent tokens.

---

## 8. Changelog

| Date | Change |
|---|---|
| 2026-10-27 | First four read-only tools: `portfolio-summary`, `data-status`, `positions`, `funds/{code}` |
