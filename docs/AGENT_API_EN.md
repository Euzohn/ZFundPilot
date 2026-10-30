# ZFundPilot Agent API (read-only + controlled proposals)

This document is for users who want AI agents (Claude Desktop, Cursor, custom MCP servers, scripts, etc.) to read portfolio data from ZFundPilot and submit controlled operations within explicit boundaries.

The Agent API is read-only by default. Write access is off by default and layered: watchlist maintenance and data refresh are low-risk direct writes; ledger changes can only be submitted as **pending proposals**, which a web administrator must approve before the server executes them. Settings, import/export, and fund-moving operations are not exposed, and an Agent token can never bypass web approval to write the ledger. Agent tokens are independent of web login tokens, scoped, default-deny, and revocable.

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
| `scopes` | string[] | No | Defaults to `portfolio:read`, `funds:read`, and `health:read`; data and write scopes added later must be selected explicitly; unknown scopes are rejected |
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
| `watchlist:write` | `watchlist` (add/update/remove; requires the server write switch) |
| `data:refresh` | `refresh` (start/query task-based data refresh; NAV/metadata only; requires the server write switch) |
| `transactions:propose` | `proposals` (create/list/cancel your pending ledger proposals; requires the server write switch; execution belongs to the web administrator) |

The write scopes are `watchlist:write`, `data:refresh`, and `transactions:propose`, all unchecked by default and gated by the server write switch (off by default). The switch is managed day-to-day by the administrator on the web Settings page ("Account & Security → Agent write capability", `GET/PUT /api/settings/agent-write`); enabling it requires the current login password, and the state persists in the database. The `ZFUNDPILOT_AGENT_WRITE_ENABLED` environment variable only matters in two cases: explicitly set to `0`/`false`/`no`/`off` it is an **emergency brake** (forced off, and the Settings page cannot enable it); set to `1`/`true`/`yes`/`on` it only serves as the first-start default when the database has no record. Calling a tool without the required scope returns **403**. The first two are low-risk direct writes; `transactions:propose` only submits proposals and **cannot write the ledger directly**.

`capabilities` only requires a valid token, not a specific scope; it returns only the tools granted to that token, marking write tools with `risk="write"`, proposal tools with `risk="propose"`, and `enabled` reflecting the server write switch; the top-level `write_enabled` is the current switch value, and `write_locked: true` means the environment-variable emergency brake has locked the switch so the Settings page cannot enable it either.

> The first three scopes are checked by default on the issuance panel. `transactions:read`, `watchlist:read`, `alerts:read`, `plans:read`, `watchlist:write`, `data:refresh`, and `transactions:propose` are unchecked by default: opt in explicitly when needed, so existing tokens are never silently broadened.

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
| `403` | Valid token but missing required scope, write switch off, or password auth not enabled |
| `404` | Unknown tool or fund (only with a valid token) |
| `409` | Watchlist revision conflict, missing/existing object, unregistered fund, non-pending/expired proposal, or idempotency conflict |
| `422` | Invalid body/parameters, or missing a valid `Idempotency-Key` |
| `429` | Rate limit exceeded; see `Retry-After` |

> `/api/agent/tools/*` is protected by a dedicated Agent auth middleware. Even a nonexistent tool path returns `401` without a valid token, so route existence is not leaked.

### Rate limiting

**120 requests per minute** per token per endpoint by default. Path parameters count as the same endpoint (for example, different fund codes share the `funds/{code}` budget), so enumerating codes cannot bypass the limit. Heavier endpoints use lower limits: `search` is 60/min; `screen`, `backtest/dca`, `benchmark`, and `industry-exposure` are 20/min; watchlist writes (`POST`/`PATCH`/`DELETE`) are 30/min and count separately from `GET` on the same path; `POST refresh` is 10/min (network-fetching, so avoid high-frequency triggers). Screening shares one bucket whether or not metrics are requested, so switching parameters cannot bypass it. Exceeding a limit returns `429`; retry after the `Retry-After` seconds. Rate-limit and metric-enrichment concurrency are **in-process** state; multiple workers count independently.

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

Sections 5.1–5.20 are read-only or read-only simulations (5.20 uses `POST`); 5.21–5.23 are controlled writes, all off by default. No tool accepts settings, import/export, or fund-moving operations, and ledger writes happen only after a web administrator approves a proposal.

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

Common `data` fields: `scope` (`portfolio` / `fund`), `valuation_basis` (always `latest_formal_nav`), `return_basis` (always `open_positions_floating`), `return_basis_note`, `realized_pnl_scope` (`all_history_including_closed`), `total_pnl_scope`, `as_of_date`, and `as_of_date_semantics`.

> **Semantics**: `total_return`/`return_rate` is the **current open-position** floating return (market value ÷ current holding cost − 1), not a historical cumulative return. P&L from fully closed funds appears only in `realized_pnl` and XIRR. Do not divide `total_return` by cumulative buy/sell amounts. When everything is closed, current cost is zero and `total_return`/`return_rate` is `null`.

Portfolio-level additionally has:

| Field | Description |
|---|---|
| `total_return` / `annualized_return` | Current open-position floating return / XIRR annualized (may be `null`) |
| `total_pnl` / `unrealized_pnl` / `realized_pnl` | Total / unrealized / realized P&L; `realized_pnl` includes closed history |
| `total_cost` / `total_value` | Current open-position cost / market value |
| `daily` / `week` / `month` / `year` | Period `{pnl, return}` |
| `holding_count` | Number of funds currently held (deduplicated by fund) |
| `open_position_count` / `closed_position_count` | Open / closed (fund, channel) rows |
| `data_quality` | Missing/stale NAV and pending T+1 counts plus `caveats` |

Single-fund additionally has:

| Field | Description |
|---|---|
| `fund_code` / `fund_name` | Fund identity |
| `market_value` / `total_cost` | Current open market value / holding cost (closed channels contribute zero) |
| `unrealized_pnl` / `realized_pnl` / `total_pnl` | Unrealized / realized / total P&L; `realized_pnl` includes closed channels |
| `closed_realized_pnl` | Realized P&L contributed by closed channels |
| `return_rate` / `annualized_return` | Current open-position floating return / all-history XIRR (may be `null`) |
| `transaction_count` | Transaction count, including closed history |
| `buy_amount` / `sell_amount` / `dividend_amount` | Cumulative buy / sell / dividend amounts; `dividend_amount` includes reinvested dividends |
| `open_position_count` / `closed_position_count` | Open / closed channel count |
| `data_quality` | `missing_nav_channel_count`, `pending_t1_transaction_count`, `caveats` |
| `channels` | All channels, including closed: `channel`, `is_open`, `market_value`, `total_cost`, `unrealized_pnl`, `realized_pnl`, `return_rate`, `annualized_return`, `latest_date`, `nav_missing` |

> `annualized_return` uses XIRR on actual cash-flow dates, which is more reliable than a simple return for staged purchases; it returns `null` when there is not enough data. Cash dividends are inflows; reinvested dividends are skipped as cash-neutral so they are not double-counted. If a held channel has no formal NAV, `return_rate` and `annualized_return` return `null` with `caveats`, instead of reporting a fake `-100%` loss. Pending T+1 buys are excluded from market value and cost.

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
| `fund_codes` | string[] | required | At most 5 list items; six-digit codes, duplicates are removed and each fund is simulated independently |
| `start_date` / `end_date` | string | required | Strict `YYYY-MM-DD`; start before end; end not after today in China time |
| `amount_per_period` | number | required | Amount per fund per period; finite and positive, ≤ 1,000,000 |
| `cadence` | string | `month` | `month`, `week`, or `biweek` |
| `include_lumpsum` | bool | `true` | Add a lump-sum comparison per fund using the actual total invested |
| `include_curve` | bool | `true` | Return the value curve; when false the curve is empty |
| `include_periods` | bool | `false` | Return per-period purchase details (larger response) |
| `max_points` | int | `365` | Curve sampling cap, 10–2000, first/last preserved |

The range is limited to 10 years; monthly/biweekly/weekly plans produce at most roughly 120/261/522 periods. Invalid JSON, missing required fields, or unknown fields return `422`; authentication and scope semantics match the other tools (`401`/`403`).

`data` fields: `ok`, `message`, `simulation_note`, `requested`, `fund_count`, `result_count`, `failed_count`, `results[]`. `failed_count` counts result rows (a fund's `dca` and `lumpsum` rows count separately); `ok` is `false` only when every result failed. Partial failures keep `ok=true`; use `message` and each result's `status` for details.

Each result contains:

- Basics: `fund_code`, `fund_name`, `strategy` (`dca`/`lumpsum`), `status` (`ok`/`partial`/`failed`), `code`, `message`.
- Data: `data_source` (`database`/`remote`/`database+remote`/`none`), `data_start`, `data_end`, `valuation_date`, `skipped_periods`, `fee_ok`. `data_start`/`data_end` are the actual available NAV range and are empty strings when no valid NAV exists.
- Metrics: `cadence`, `amount_per_period`, `total_periods`, `invested_capital`, `total_fees`, `final_value`, `redemption_fee`, `net_final_value`, `total_return`, `annualized_return`, `max_drawdown`, `sharpe_ratio`.
- Details: `curve` (sampled to `max_points`), `curve_points`, `periods_detail` (non-empty only with `include_periods=true`), `periods_detail_count`, `caveats`.
- `fee_ok=false` means the fee table could not be fetched; even when `fee_ok=true`, a missing purchase or redemption tier is counted as 0 and explained in `caveats`, which must not be read as a true zero-fee fund.
- `status="failed"` uses `code="insufficient_nav"` (fewer than 2 valid NAV points) or `no_periods` (no executable planned date), and does not output apparently valid zero-return metrics.
- `status="partial"` with `code="partial_coverage"` means some planned periods were skipped because NAV data did not cover them or because multiple periods mapped to the same NAV date; `skipped_periods` gives the count. When the requested end is later than the last available NAV date, the trailing uncovered periods fall into this case — the backtest still runs on the available data, and `valuation_date`/`data_end` reflect the actual coverage.

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

### 5.21 Watchlist maintenance (write, disabled by default)

The three write tools share `watchlist:write` and are also gated by the server write switch (off by default; when off, even a token with the scope gets `403 write_disabled` — see the write-switch notes above). They only change watchlist membership, notes, and groups — **never transactions, auto-invest plans, NAV data, or fund metadata**.

| MCP tool | HTTP | Behavior |
|---|---|---|
| `add_watchlist_item` | `POST /api/agent/tools/watchlist` | Add; only registered funds; conflicts instead of overwriting notes/groups |
| `update_watchlist_item` | `PATCH /api/agent/tools/watchlist/{code}` | Update with `expected_revision`; only explicitly provided fields change; an empty string clears a field |
| `remove_watchlist_item` | `DELETE /api/agent/tools/watchlist/{code}?expected_revision=N` | Delete by revision, keeping a recoverable previous value |

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f50" \
  -d '{"fund_code":"005827","note":"watch","group_name":"core"}'
```

- Every write request must send `Idempotency-Key` (16–128 safe ASCII characters). Same key and parameters replay the original result with `replayed=true`; same key with different parameters or a different operation returns `409 idempotency_conflict`; expired keys return `409 idempotency_expired`. Records are kept for 90 days.
- `expected_revision` comes from `list_watchlist`. A mismatch returns `409 revision_conflict` and never overwrites concurrent web or agent changes.
- Adding an existing item returns `409 already_exists`; updating/removing a missing item returns `404 not_found`; an unregistered fund returns `409 fund_not_registered`.
- Successful `data` includes `ok`, `code`, `message`, `changed`, `replayed`, `fund_code`, `revision`, `operation_id`, `audit_id`, and `before`/`after`.
- Deleted values are recoverable only by the web administrator via `POST /api/watchlist/{code}/restore`, which also checks the tombstone revision and cannot overwrite a later rebuild or edit.
- Watchlist writes are limited to 30 requests/minute per token. The business result audit is committed in the same transaction as the write; a successful auth audit does not mean the business operation succeeded.

### 5.22 Data refresh (write, disabled by default)

Start a **NAV/metadata-only** refresh job. Scope: `data:refresh`, also gated by the server write switch (see the write-switch notes above). It does **not** backfill transaction NAVs, does **not** execute auto-invest plans, and never creates transactions or plans — the key difference from the web `POST /api/nav/update`.

| MCP tool | HTTP | Behavior |
|---|---|---|
| `start_data_refresh` | `POST /api/agent/tools/refresh` | Create a job; returns `202` + `job_id` |
| `get_job_status` | `GET /api/agent/tools/refresh/{job_id}` | Query progress/result; only the creating token can read |

```bash
# Start (default: current open holdings; or pass fund_codes, max 50)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f51" \
  -d '{}' | jq

curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh/7" | jq
```

- Must send `Idempotency-Key` (16–128 safe ASCII chars). Same key and parameters replay the original `job_id` (`replayed=true`); same key with different parameters returns `409 idempotency_conflict`; expired keys return `409 idempotency_expired`.
- Jobs persist in `refresh_jobs`: `status ∈ {queued,running,succeeded,failed,interrupted}`; a restart marks leftover `queued/running` as `interrupted`, never falsely reporting success. Jobs are queryable for 7 days; records are kept another 30 days before cleanup.
- If a refresh is already running, return `409 refresh_busy`; when a refresh job holds the lock, `detail.current_job_id` gives its ID for polling with `get_job_status` (it may be `null` when a manual web refresh is running). No queueing, avoiding stale jobs.
- `can_cancel` is always `false`: cancellation is not supported in this phase, and no misleading empty cancel API is provided.
- Jobs share the nav-update mutex with the web `/api/nav/update` and the scheduler, running serially. Progress (`done/total/current/phase`) is written to the job row and mirrored to the shared run state for the web UI.
- Error codes: `write_disabled`, `validation_error`, `refresh_busy`, `not_found`, `idempotency_conflict`, `idempotency_expired`. Audits `data_refresh_started/succeeded/failed/busy/rejected` record only counts and the token prefix.
- Max 50 funds per job; `POST refresh` is limited to 10 requests/minute (`GET refresh/{job_id}` uses the default 120/min).

### 5.23 Ledger proposals (write, requires web approval; off by default)

Agents can only submit **pending proposals**; they never write the ledger directly. Scope: `transactions:propose`, also gated by the server write switch (see the write-switch notes above). This phase supports only `operation_type="add_transaction"`. Approval, rejection, execution, and state transitions happen server-side on the web, and the execution path performs no network access.

| MCP tool | HTTP | Description |
|---|---|---|
| `create_operation_proposal` | `POST /api/agent/tools/proposals` | Create a proposal; returns `201` + `proposal_id`; does not write the ledger |
| `list_operation_proposals` | `GET /api/agent/tools/proposals` | List only proposals created by the current token |
| `get_operation_proposal` | `GET /api/agent/tools/proposals/{proposal_id}` | Readable only by the creator; others get `404` |
| `cancel_operation_proposal` | `DELETE /api/agent/tools/proposals/{proposal_id}` | Cancel your own proposal while it is still `pending` |

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f52" \
  -d '{
    "operation_type": "add_transaction",
    "params": {
      "fund_code": "005827",
      "action": "buy",
      "date": "2026-10-30",
      "amount": 1000,
      "fee": 1,
      "channel": "Alipay"
    }
  }' | jq
# {"tool":"create_operation_proposal","data":{"proposal_id":1,"status":"pending","expires_at":"...","summary":{...}}}
```

- `params` accepts only the `add_transaction` whitelist: `fund_code` (six digits, must already be registered), `action` (`buy`/`sell`/`dividend`/`reinvest`), `date` (`YYYY-MM-DD`), `amount`/`shares`/`nav` (buy/sell need enough fields to derive the rest; sell requires shares; dividend requires an amount), `fee`, `channel`, `note`, `is_t1`. Unknown fields return `422 validation_error`.
- Must send `Idempotency-Key` (16–128 safe ASCII chars). Same key and parameters replay the original proposal (`200` + `replayed=true`); same key with different parameters/operation returns `409 idempotency_conflict`; expired keys return `409 idempotency_expired`.
- Proposals expire after 7 days and can then no longer be approved or cancelled. Each token may keep at most 20 `pending` proposals; beyond that returns `409 too_many_pending`.
- A fund that is not yet registered returns `409 fund_not_registered`, so the approval path never fetches data over the network.
- State machine: `pending → succeeded / failed / conflict / rejected / cancelled / expired`. `failed` means the creator token was revoked, expired, or lost the scope; `conflict` means the fund/parameters became invalid at approval time. Environment-level blocks (`auth_disabled`, `write_disabled`) return `403` and leave the proposal `pending` so it can be retried after the fix.
- After a web administrator approves, the server re-checks instance authentication, the write switch, the creator token, and business rules in the same SQLite transaction, writes the transaction, and records both `proposal_approved` and `add_transaction` audits. Concurrent approvals succeed only once; a repeat returns `409 not_pending`.
- Web approval endpoints accept web login identities only: `GET /api/proposals/count`, `GET /api/proposals`, `GET /api/proposals/{id}`, `POST /api/proposals/{id}/approve`, `POST /api/proposals/{id}/reject`. An Agent token calling these returns `401`.
- Error codes: `write_disabled`, `validation_error`, `fund_not_registered`, `too_many_pending`, `not_pending`, `expired`, `not_found`, `idempotency_conflict`, `idempotency_expired`. Audits `proposal_created`, `proposal_create_rejected`, `proposal_cancelled`, `proposal_expired`, `proposal_approved`, `proposal_rejected`, `proposal_failed`, and `proposal_conflict` record only the token prefix and proposal summary.
- Creation/cancellation share the global write switch with watchlist writes. Proposals are not included in backup archives; restoring a backup clears stale proposals so they cannot point at replaced ledger data.

### MCP adapter (optional)

A stdio MCP bridge is bundled to expose the tools above to Claude Desktop, Cursor, and other MCP clients. It is only an HTTP client carrying an Agent token: it does not touch the database, and authentication, scopes, and rate limiting are identical to the HTTP entry point.

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

Exposed MCP tools: `get_portfolio_summary`, `get_data_status`, `list_positions`, `get_fund_detail`, `get_portfolio_health`, `get_returns`, `compare_funds`, `list_transactions`, `get_transaction`, `list_watchlist`, `list_alerts`, `list_auto_invest_plans`, `get_portfolio_curve`, `get_benchmark_comparison`, `get_risk_report`, `get_industry_exposure`, `search_funds`, `screen_funds`, `run_dca_backtest`, `get_agent_capabilities`, `add_watchlist_item`, `update_watchlist_item`, `remove_watchlist_item`, `start_data_refresh`, `get_job_status`, `create_operation_proposal`, `list_operation_proposals`, `get_operation_proposal`, `cancel_operation_proposal`.
Write tools require an `idempotency_key` argument, mapped to the HTTP `Idempotency-Key` header. The MCP client only passes parameters; server-side auth, scope, and the write switch remain authoritative.

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
- **Scope**: Read scopes cover portfolio, portfolio curve, benchmark, risk, industry exposure, funds, data status, transactions, watchlist, alerts, and auto-invest plans. Write scopes are limited to watchlist maintenance, task-based data refresh, and ledger proposals. Proposals require web administrator approval; Agent tokens cannot write the ledger directly, and settings/import/export/fund-moving endpoints are never available to them.

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
| 2026-10-30 | Added the `transactions:propose` scope and four ledger proposal tools: agents can only submit pending proposals; after web administrator approval the server writes the ledger and audits in one transaction. This phase supports only `add_transaction`; proposals expire after 7 days, are idempotent, and are isolated per token |
