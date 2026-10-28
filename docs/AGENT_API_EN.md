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

The examples below assume these environment variables are set:

```bash
export ZFUNDPILOT_AGENT_TOKEN=zfag_xxx   # your own token
export ZFUNDPILOT_BASE_URL=http://localhost:8000
```

Request body:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | 1–64 characters, identifies the caller |
| `scopes` | string[] | No | Defaults to `portfolio:read`, `funds:read`, and `health:read`; the data scopes added later must be selected explicitly; unknown or write scopes are rejected |
| `expires_in_days` | int \| null | No | 1–3650 days, default 90; `null` means no expiry |

---

## 3. Scopes

| Scope | Allowed tools |
|---|---|
| `portfolio:read` | `portfolio-summary`, `positions`, `returns`, `portfolio-curve`, `benchmark`, `industry-exposure` |
| `funds:read` | `funds/{code}`, `funds/compare`, `search`, `screen`, `backtest/dca` |
| `health:read` | `data-status`, `portfolio-health`, `risk-report` |
| `transactions:read` | `transactions`, `transactions/{tx_id}` |
| `watchlist:read` | `watchlist` |
| `alerts:read` | `alerts` |
| `plans:read` | `auto-invest-plans` |

There are no write scopes. Calling a tool without the required scope returns **403**.

`capabilities` only requires a valid token, not a specific scope; it returns only the tools granted to that token.

> The first three scopes are checked by default on the issuance panel. `transactions:read`, `watchlist:read`, `alerts:read`, and `plans:read` are unchecked by default: opt in explicitly when an agent needs that data, so existing tokens are never silently broadened.

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

**120 requests per minute** per token per endpoint by default. Path parameters count as the same endpoint (for example, different fund codes share the `funds/{code}` budget), so enumerating codes cannot bypass the limit. Heavier endpoints use lower limits: `search` is 60/min, and `screen`, `backtest/dca`, `benchmark`, and `industry-exposure` are 20/min; screening shares one bucket whether or not metrics are requested, so switching parameters cannot bypass it. Exceeding a limit returns `429`; retry after the `Retry-After` seconds. Rate-limit and metric-enrichment concurrency are **in-process** state; multiple workers count independently.

### OpenAPI / Swagger

FastAPI generates:

| Path | Content |
|---|---|
| `/openapi.json` | Machine-readable API description |
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |

These pages are public by default and **only describe the API structure**; they contain no tokens, holdings, or other business data. All business `/api/*` endpoints still require authentication. Agent tools are grouped under `agent` and management endpoints under `agent-admin`, with documented 401/403/429 responses; tools with parameter validation also document 400, and fund/transaction detail document 404. The schema declares two Bearer schemes, `AgentBearer` and `WebLoginBearer`; Swagger UI can send only one `Authorization` header at a time, so authorize the one you need. If your deployment should not expose the endpoint list, block these paths at the reverse proxy.

### Valuation basis

Amounts are based on the **latest formal NAV** and marked with `data.valuation_basis = "latest_formal_nav"`.

- `as_of_date` is the maximum formal NAV date among holdings; it does **not** mean every fund is up to date.
- The API does **not** return intraday estimates, to avoid mixing them with formal NAV. Use `data-status` to check completeness.

---

## 5. Tools

All tools are read-only. Except for 5.20, which uses `POST`, every tool uses `GET`; none accepts trading, settings, or export operations.

### 5.1 `GET /api/agent/tools/portfolio-summary`

Portfolio-level summary. Scope: `portfolio:read`.

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/portfolio-summary | jq
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
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/data-status | jq
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
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/positions?limit=50" | jq
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
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/funds/005827?nav_limit=10" | jq
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

### 5.5 `GET /api/agent/tools/portfolio-health`

Four-dimension portfolio health check. Scope: `health:read`.

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/portfolio-health | jq
```

`data` fields:

| Field | Description |
|---|---|
| `overall_score` | Overall score 0–100 |
| `overall_tier` | Tier: `excellent` / `good` / `fair` / `attention` / `danger` |
| `dimensions` | Four dimensions: `allocation`, `risk`, `liquidity`, `return`; each has `name`, `score`, `status`, `metrics` |
| `stable_weight` / `volatile_weight` | Stable (bonds etc.) / volatile asset weight |
| `risk_report` | Max drawdown, volatility, largest single weight, HHI, equity/bond/QDII weights, and risk `flags` |
| `advice` | Structural suggestions, not trading instructions |
| `summary` | Portfolio summary, same shape as 5.1 |
| `valuation_basis` | Always `latest_formal_nav` |
| `data_quality` | `as_of_date`, `as_of_date_semantics`, missing/stale NAV counts, pending T+1 count, and a `caveats` array |

> Read `data_quality.caveats` before interpreting scores: missing or stale NAV can lower related dimensions, and pending T+1 transactions are not yet included in market value. A `danger` tier on an empty portfolio only means there is nothing to diagnose, not real risk.
>
> The health check tries to fetch a CPI baseline for the return dimension; if the network is unavailable it degrades to scoring on annualized return only and still returns normally.

### 5.6 `GET /api/agent/tools/returns`

Return breakdown. Scope: `portfolio:read`. Portfolio-level by default; pass `fund_code` for a single fund.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `fund_code` | str | none | Optional six-digit code; malformed returns `400`, unknown fund returns `404` |

```bash
# Portfolio-level
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/returns | jq

# Single fund
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/returns?fund_code=005827" | jq
```

Common `data` fields: `scope` (`portfolio` / `fund`), `valuation_basis` (always `latest_formal_nav`), `as_of_date`, and `as_of_date_semantics`.

Portfolio-level additionally has:

| Field | Description |
|---|---|
| `total_return` / `annualized_return` | Cumulative return / XIRR annualized (may be `null`) |
| `total_pnl` / `unrealized_pnl` / `realized_pnl` | Total / unrealized / realized P&L |
| `daily` / `week` / `month` / `year` | Period `{pnl, return}` |
| `holding_count` | Number of funds currently held |

Single-fund additionally has:

| Field | Description |
|---|---|
| `fund_code` / `fund_name` | Fund identity |
| `market_value` / `total_cost` | Market value / holding cost |
| `unrealized_pnl` / `realized_pnl` / `total_pnl` | P&L |
| `return_rate` / `annualized_return` | Cumulative return / XIRR annualized |
| `transaction_count` | Number of transactions |
| `buy_amount` / `sell_amount` / `dividend_amount` | Cumulative buy / sell / dividend amounts |
| `channels` | Per-channel holdings: `channel`, `market_value`, `total_cost`, `unrealized_pnl`, `return_rate`, `annualized_return` |

> `annualized_return` uses XIRR on actual cash-flow dates, which is more reliable than a simple return for staged purchases; it returns `null` when there is not enough data.

### 5.7 `GET /api/agent/tools/funds/compare`

Multi-fund comparison. Scope: `funds:read`. Up to 20 funds per request.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `codes` | str[] | required | Six-digit fund codes, repeated: `?codes=005827&codes=000001`; empty or malformed returns `400`, omitted returns `422` |
| `include_nav_series` | bool | `false` | Include normalized NAV series (larger response) |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/funds/compare?codes=005827&codes=000001" | jq
```

`data` fields:

| Field | Description |
|---|---|
| `ok` / `message` / `msg_code` | Overall success flag and failure reason |
| `count` | Number of funds returned |
| `funds` | Per fund: `code`, `name`, `type`, `sector`, `scale`, `manager`, fees, `returns`, `risk`, `latest_nav`, `latest_date`, `ok`, `message` |
| `correlations` | Correlation matrix when at least two funds succeed; `null` otherwise |
| `nav_series` | Only when `include_nav_series=true`; normalized NAV series per fund code |
| `valuation_basis` | Always `latest_formal_nav` |

> Comparison fetches external data and may be slow; one failed fund does not affect the others, so check each item's `ok`/`message`. Intraday estimates are not returned.

### 5.8 `GET /api/agent/tools/transactions`

Transaction list. Scope: `transactions:read`. Sorted by date and id descending; only stored transactions are read.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `fund_code` | str | none | Six-digit fund code; malformed returns `400` |
| `channel` | str | none | Exact channel match (empty string included) |
| `action` | str | none | `buy` / `sell` / `dividend` / `reinvest` |
| `date_from` | str | none | Inclusive start date, `YYYY-MM-DD` |
| `date_to` | str | none | Inclusive end date, `YYYY-MM-DD` |
| `conversion_id` | str | none | Conversion link id, to fetch both legs |
| `nav_status` | str | none | `confirmed` / `pending_t1` / `missing` |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | Zero-based |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions?fund_code=005827&limit=20" | jq
```

`data` fields:

| Field | Description |
|---|---|
| `count` / `total` | Items on this page / matched total |
| `pagination` | `{limit, offset, total, has_more}` |
| `valuation_basis` | Always `latest_formal_nav` |
| `transactions` | Transaction array, see below |

Per transaction:

| Field | Description |
|---|---|
| `id` / `fund_code` / `date` / `action` | Identity and basic fields |
| `fund_name` | Fund name, `null` when the fund is not stored |
| `amount` / `shares` / `nav` / `fee` | Amount / shares / NAV / fee |
| `amount_semantics` | `gross_paid` for buys (fees included), `net_received` for sells (fees deducted), `gross` for dividends/reinvestments |
| `channel` / `note` / `is_t1` | Channel, note, T+1 flag |
| `nav_status` | `confirmed` (NAV backfilled) / `pending_t1` (awaiting confirmation) / `missing` (no NAV and not T+1) |
| `conversion_role` | With `conversion_id`: `out` for the sell leg, `in` for the buy leg; otherwise empty |

> The `pending_t1` vs `missing` distinction matters: the former is normal waiting, the latter usually means missing data. Cross-check with `data-status`.

### 5.9 `GET /api/agent/tools/transactions/{tx_id}`

Single transaction detail. Scope: `transactions:read`. Fields match one item from 5.8, plus a top-level `data.valuation_basis`; an unknown id returns `404`.

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/transactions/12 | jq
```

### 5.10 `GET /api/agent/tools/watchlist`

Watchlist. Scope: `watchlist:read`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `group_name` | str | none | Exact group filter; empty string means ungrouped |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | Zero-based |

`data` fields: `count`, `total`, `pagination` (same shape as 5.8), `watchlist`.

Each item: `fund_code`, `note`, `group_name`, `added_at`, `fund_name`, `fund_type`, `sector`, `tracking_index` (the last four come from the fund table and are `null` when unknown).

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist?group_name=core" | jq
```

### 5.11 `GET /api/agent/tools/alerts`

Dividend and take-profit/stop-loss alerts. Scope: `alerts:read`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `type` | str | none | `dividend` / `take_profit` / `stop_loss` / `tp_sl` (both TP and SL) |
| `status` | str | none | `pending` / `confirmed` / `ignored` |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | Zero-based |

`data` fields: `count`, `total`, `pagination`, `alerts`.

Only whitelisted fields are returned: `id`, `alert_type`, `fund_code`, `fund_name`, `status`, `triggered_return`, `threshold`, `record_date`, `ex_date`, `pay_date`, `per_share`, `estimated_amount`, `held_shares`, `dividend_method`, `created_at`, `resolved_at`, `tx_id`.

> `status` is the **business processing state**, not read/unread. ZFundPilot has no read flag for alerts, and the API does not invent one.

### 5.12 `GET /api/agent/tools/auto-invest-plans`

Auto-invest plans. Scope: `plans:read`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | none | Filter by enabled state |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | Zero-based |

`data` fields: `count`, `total`, `pagination`, `plans`.

Each plan returns stored fields (fund code, amount, cadence, channel, note, `next_run`, `last_run`, `last_tx_id`, etc.) plus:

| Field | Description |
|---|---|
| `fund_name` | Fund name, `null` when unknown |
| `enabled` | Normalized boolean |
| `status` | Derived: `paused` (disabled) / `due` (`next_run` reached) / `active` (enabled and not due) |

> Skip reasons (e.g. insufficient balance, non-trading day) are **not persisted per plan**, so no speculative `skip_reason` field is returned.

### 5.13 `GET /api/agent/tools/capabilities`

Capability discovery. Requires only a valid Agent token, not a specific scope.

`data` fields:

| Field | Description |
|---|---|
| `server_version` | Server version |
| `schema_version` | Capability schema version, currently `1` |
| `granted_scopes` | Scopes granted to this token (sorted) |
| `currency` | Always `CNY` |
| `tools` | Callable tools: `name`, `method`, `path`, `scope`, `risk` (always `read`), `requires_confirmation` (always `false`) |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/capabilities | jq
```

> Agents should call `capabilities` at startup and use only the returned tools, avoiding repeated 403s.

### 5.14 `GET /api/agent/tools/portfolio-curve`

Daily portfolio value, invested cost, and cumulative return curve. Scope: `portfolio:read`.

Parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `start_date` / `end_date` | string | none | Optional `YYYY-MM-DD`, inclusive |
| `max_points` | int | 365 | 10–2000; larger series are evenly sampled keeping the first and last point |

`data` fields:

| Field | Description |
|---|---|
| `as_of_date` | Max formal NAV date across holdings |
| `as_of_date_semantics` | Explanation of the as-of date |
| `valuation_basis` | Always `latest_formal_nav` |
| `max_points` | Requested point cap |
| `points_count` | Number of returned points |
| `points[]` | `{date, total_value, invested_cost, total_return}` |

> The curve is for visualization, not exact reconciliation. Pending buys use a placeholder value to avoid fake losses. Invalid dates or reversed ranges return `400`.

### 5.15 `GET /api/agent/tools/benchmark`

Benchmark index / macro level cumulative returns aligned to the portfolio curve. Scope: `portfolio:read`.

Parameters:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `codes` | string[] | yes | Repeated query params, up to 20, e.g. `?codes=000300&codes=CPI`; whitelist `000300`/`000001`/`399006`/`CPI`/`M2` |
| `start_date` / `end_date` | string | no | Optional, trim the returned range only |

`data` fields: `as_of_date`, `as_of_date_semantics`, `valuation_basis`, `codes` (requested), `code_names` (code→name), `points_count`, `points[]` (`{date, <code>: cumulative_return}`).

> Cumulative returns use the **portfolio curve start** as the baseline; date filters only trim the response and do not move the baseline. Indices are daily while CPI/M2 are monthly. Failed or missing codes do not appear in `points` and are never filled with 0. This tool may be slow (network fetch); unsupported or empty codes return `400`.

### 5.16 `GET /api/agent/tools/risk-report`

Portfolio risk metrics, structure weights, and risk flags. Scope: `health:read`.

`data` fields:

| Field | Description |
|---|---|
| `as_of_date` / `as_of_date_semantics` / `valuation_basis` | As-of date and NAV basis |
| `max_drawdown` / `volatility` | Max drawdown (negative) and annualized volatility; `null` when data is insufficient |
| `max_single_weight` / `max_single_name` | Largest single-fund weight and name |
| `hhi` | Herfindahl concentration index |
| `equity_weight` / `bond_weight` / `qdii_weight` | Equity / bond / QDII weights (fractions) |
| `flags[]` | `{level, code, params, title, detail}`; `code`+`params` are for client i18n, `title`/`detail` keep Chinese fallback text |
| `data_quality` | `{missing_nav_fund_count, stale_nav_fund_count, pending_t1_transaction_count, caveats[]}` |

> Data gaps are not hidden; read `data_quality.caveats` before interpreting metrics.

### 5.17 `GET /api/agent/tools/industry-exposure`

Portfolio industry exposure by looking through fund allocations. Scope: `portfolio:read`.

`data` fields: `ok`, `message`, `as_of_date`, `as_of_date_semantics`, `valuation_basis`, `total_market_value`, `penetrated_market_value`, `unpenetrated_market_value`, `equity_total_market_value`, `equity_penetrated_market_value`, `funds_count`, `funds_with_data`, `quarter`, `items[]`, `funds_missing[]`, `data_quality`.

> Allocation data is fetched externally (one request per fund, cached) and **may be slow**. Funds without data appear in `funds_missing` (`reason`: `no_data`/`parse_error`/`fetch_error`/`empty_allocations`) without affecting others. With no holdings, `ok=false` and `message="无持仓"`.

### 5.18 `GET /api/agent/tools/search`

Search the fund universe by name or code substring. Scope: `funds:read`. Metrics are not enriched, so this is the fast lookup path.

Parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `keyword` | string | required | 1–100 characters after trimming; blank returns `400`; missing or `keyword=` returns `422` |
| `limit` / `offset` | int | 50 / 0 | `limit` 1–200, `offset` ≥ 0 |

`data` fields: `ok`, `code`, `message`, `count`, `total`, `pagination`, `funds[]`; each item is `{code, name, type, sector}`.

> Matching is literal substring only; regex and arbitrary query expressions are not accepted. Results are sorted by fund code ascending. The universe cache is refreshed over the network when missing and is valid for 24 hours. A valid query with no matches returns `ok=true` and `funds=[]`. If the universe fails to load, HTTP stays 200 but `ok=false` and `code="universe_failed"`, so callers must check `ok` first. Type and sector are inferred from names and are for candidate lookup only.

### 5.19 `GET /api/agent/tools/screen`

Screen the fund universe by asset type, sector, and keyword. Scope: `funds:read`.

Parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `types` | string[] | none | Repeated params; must be known server-side types, at most 20 |
| `sectors` | string[] | none | Repeated params; must be known sectors (including custom), at most 20 |
| `keyword` | string | none | Optional name/code substring, at most 100 characters |
| `with_metrics` | bool | `false` | Enrich the first 30 funds of the current page with return/risk metrics |
| `limit` / `offset` | int | 50 / 0 | `limit` 1–200, `offset` ≥ 0 |

`data` fields: `ok`, `code`, `message`, `count`, `total`, `pagination`, `with_metrics`, `metrics`, `funds[]`.

- `metrics`: `{requested, limit=30, attempted, succeeded, failed, timed_out, complete}`.
- Each fund: `{code, name, type, sector, scale, manager, inception_date, returns, risk, metrics_status}`.
- `metrics_status`: `not_requested`, `over_limit` (beyond the first 30), `ok`, or `unavailable` (failed or timed out). `null` means missing, never zero-filled.

> `with_metrics=true` calls external NAV/archive services and **may be slow**. It only covers the **first 30 funds of the current page in ascending code order**, not a market-wide return ranking. Enrichment concurrency is capped at 2; when full it returns `429` immediately instead of queueing. A timeout returns only completed items and marks the rest `unavailable`; the concurrency slot is released only after background work finishes. Use `funds/compare` for precise comparison. Unknown types/sectors, more than 20 filter values, or an over-long keyword return `400`.

### 5.20 `POST /api/agent/tools/backtest/dca`

Simulate a historical DCA plan, optionally with a lump-sum comparison. Scope: `funds:read`. This is a **read-only historical simulation**: it does not write the formal NAV table, transactions, auto-invest plans, watchlist, or fund metadata, and it is neither a forecast nor allocation advice.

JSON body (unknown fields, type errors, or constraint violations return `422`):

| Field | Type | Default | Description |
|---|---|---|---|
| `fund_codes` | string[] | required | 1–5 six-digit codes; duplicates are removed and each fund is simulated independently |
| `start_date` / `end_date` | string | required | Strict `YYYY-MM-DD`; start before end; end not after today in China time |
| `amount_per_period` | number | required | Amount per fund per period; finite and positive, ≤ 1,000,000 |
| `cadence` | string | `month` | `month`, `week`, or `biweek` |
| `include_lumpsum` | bool | `true` | Add a lump-sum comparison per fund using the actual total invested |
| `include_curve` | bool | `true` | Return the value curve; when false the curve is empty |
| `include_periods` | bool | `false` | Return per-period purchase details (larger response) |
| `max_points` | int | `365` | Curve sampling cap, 10–2000, first/last preserved |

The range is limited to 10 years; monthly/biweekly/weekly plans produce at most roughly 120/261/522 periods. Invalid JSON, missing required fields, or unknown fields return `422`; authentication and scope semantics match the other tools (`401`/`403`).

`data` fields: `ok`, `message`, `simulation_note`, `requested`, `fund_count`, `result_count`, `failed_count`, `results[]`. `failed_count` counts result rows (a fund's `dca` and `lumpsum` rows count separately).

Each result contains:

- Basics: `fund_code`, `fund_name`, `strategy` (`dca`/`lumpsum`), `status` (`ok`/`partial`/`failed`), `code`, `message`.
- Data: `data_source` (`database`/`remote`/`database+remote`/`none`), `data_start`, `data_end`, `valuation_date`, `skipped_periods`, `fee_ok`.
- Metrics: `cadence`, `amount_per_period`, `total_periods`, `invested_capital`, `total_fees`, `final_value`, `redemption_fee`, `net_final_value`, `total_return`, `annualized_return`, `max_drawdown`, `sharpe_ratio`.
- Details: `curve` (sampled to `max_points`), `curve_points`, `periods_detail` (non-empty only with `include_periods=true`), `periods_detail_count`, `caveats`.
- `fee_ok=false` means the fee table could not be fetched; even when `fee_ok=true`, a missing purchase or redemption tier is counted as 0 and explained in `caveats`, which must not be read as a true zero-fee fund.
- `status="failed"` uses `code="insufficient_nav"` (fewer than 2 valid NAV points) or `no_periods` (no executable planned date), and does not output apparently valid zero-return metrics.
- `status="partial"` with `code="partial_coverage"` means some planned periods were skipped because NAV data did not cover them or because multiple periods mapped to the same NAV date; `skipped_periods` gives the count.

> Planned dates never precede the requested start. When multiple plans map to the same NAV date, only the first executes so that periods are not stacked onto one day. The closing valuation, redemption holding-period calculation, and XIRR terminal cash flow all use the last available NAV date (`valuation_date`), not the requested end date. NAV data is read from the database first and fetched in memory only when coverage is insufficient; nothing is written, and `data_end` may be earlier than `end_date`. Each fund's fee table is used as a single snapshot. Dividends, splits, and reinvestment are not simulated; max drawdown and Sharpe use the market-value curve, so DCA cash flows affect comparability. A request is capped at 5 funds, may be slowed by external NAV/fee fetches, should be preceded by `data-status`, and is limited to 20 requests per minute. Backtest concurrency is capped at 2 in-process; when full it returns `429` immediately instead of queueing, and multiple workers count independently.

## 6. Minimal integration

### Python

```python
import os
import httpx

BASE = os.getenv("ZFUNDPILOT_BASE_URL", "http://localhost:8000")
TOKEN = os.environ["ZFUNDPILOT_AGENT_TOKEN"]  # never hardcode or put in prompts

client = httpx.Client(
    base_url=BASE,
    headers={"Authorization": f"Bearer {TOKEN}"},
    timeout=30,
)

def call(tool: str, **params):
    response = client.get(f"/api/agent/tools/{tool}", params=params)
    response.raise_for_status()
    return response.json()

summary = call("portfolio-summary")["data"]
positions = call("positions", limit=20)["data"]["positions"]
returns = call("returns")["data"]
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

You can also wrap these twenty endpoints with any HTTP tool; an optional MCP adapter is provided at the end of this section. Agents should call `data-status` before analysis to avoid drawing conclusions from stale NAV data.

---

### MCP adapter (optional)

A stdio MCP bridge is bundled to expose the twenty tools above to Claude Desktop, Cursor, and other MCP clients. It is only an HTTP client carrying an Agent token: it does not touch the database, and authentication, scopes, and rate limiting are identical to the HTTP entry point.

```bash
# Install the optional extra from the ZFundPilot source tree
pip install 'zfundpilot[agent]'

# Run manually (normally launched by the MCP client)
export ZFUNDPILOT_BASE_URL=http://127.0.0.1:8000
export ZFUNDPILOT_AGENT_TOKEN=zfag_xxx
python -m zfundpilot.mcp_server
```

Claude Desktop example (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "zfundpilot": {
      "command": "python",
      "args": ["-m", "zfundpilot.mcp_server"],
      "env": {
        "ZFUNDPILOT_BASE_URL": "http://127.0.0.1:8000",
        "ZFUNDPILOT_AGENT_TOKEN": "zfag_xxx"
      }
    }
  }
}
```

Exposed MCP tools: `get_portfolio_summary`, `get_data_status`, `list_positions`, `get_fund_detail`, `get_portfolio_health`, `get_returns`, `compare_funds`, `list_transactions`, `get_transaction`, `list_watchlist`, `list_alerts`, `list_auto_invest_plans`, `get_portfolio_curve`, `get_benchmark_comparison`, `get_risk_report`, `get_industry_exposure`, `search_funds`, `screen_funds`, `run_dca_backtest`, `get_agent_capabilities`.

- `ZFUNDPILOT_BASE_URL` defaults to `http://127.0.0.1:8000`; use the real NAS/Docker address for remote instances and HTTPS for remote access.
- `ZFUNDPILOT_TIMEOUT` is optional, default 30 seconds (range 1–120).
- The token is read only from the environment; never commit it or paste it into prompts. Revoke it in Settings if leaked.

## 7. Security and operations

- **Separate credentials**: Agent and web tokens are not interchangeable. A web token calling a tool gets `401`; an Agent token cannot call web management endpoints.
- **Default deny**: Tool paths are checked by the Agent middleware first, then authorized by scope dependencies. Management endpoints also verify the web token themselves.
- **Digest only**: The database stores only the SHA-256 digest and a 12-character prefix. Plaintext is returned once at issuance.
- **Revocation**: Revoke from Settings at any time; it takes effect immediately. Issue one token per agent for easier tracing and cleanup.
- **Audit**: Issuance, revocation, auth success/failure, and rate limiting are audited. Only token prefixes are recorded — never plaintext or full responses.
- **Network**: Remote access must go through an HTTPS reverse proxy; do not expose the port directly. Revoke and reissue if a token leaks.
- **Scope**: Read scopes now cover portfolio, portfolio curve, benchmark, risk, industry exposure, funds, data status, transactions, watchlist, alerts, and auto-invest plans. Write and export endpoints are not available to Agent tokens.

---

## 8. Changelog

| Date | Change |
|---|---|
| 2026-10-27 | First four read-only tools: `portfolio-summary`, `data-status`, `positions`, `funds/{code}` |
| 2026-10-27 | Added `portfolio-health`: four-dimension health check, risk flags, structural advice, and `data_quality` caveats |
| 2026-10-27 | Added `returns`: portfolio/single-fund return breakdown and XIRR |
| 2026-10-27 | Added `funds/compare`: compare up to 20 funds on returns, risk, fees, and correlation |
| 2026-10-27 | Added four data read scopes and six tools: `transactions`, `transactions/{tx_id}`, `watchlist`, `alerts`, `auto-invest-plans`, `capabilities`; new scopes are unchecked by default |
| 2026-10-28 | Added four portfolio-level read tools: `portfolio-curve`, `benchmark`, `risk-report`, `industry-exposure`, reusing `portfolio:read`/`health:read` without new scopes |
| 2026-10-28 | Added two fund lookup tools: `search` (keyword lookup) and `screen` (type/sector/keyword screening with optional capped metrics), reusing `funds:read`; added per-route rate limits |
| 2026-10-28 | Added the read-only DCA backtest tool `backtest/dca` (`POST`, reusing `funds:read`): separated data preparation from calculation, never writes formal NAV data; unified valuation/XIRR terminal dates and explicitly flags insufficient data, partial coverage, and unknown fees |
