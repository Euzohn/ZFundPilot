# ZFundPilot Agent API (read-only + controlled proposals)

This document is for users who want AI agents (Claude Desktop, Cursor, custom MCP servers, scripts, etc.) to read portfolio data from ZFundPilot and submit controlled operations within explicit boundaries.

The Agent API is read-only by default. Write access is off by default and layered: watchlist maintenance and data refresh are low-risk direct writes; ledger changes are proposal-only by default (a web administrator must approve them before the server executes them); administrators may additionally grant a trusted token the `transactions:create` scope, which lets it directly record a single buy/sell the user explicitly says already happened externally, within limits and with downgrade-to-proposal on precheck anomalies. Settings, import/export, and fund-moving operations are not exposed, and an Agent token can never bypass web approval to write the ledger except for that trusted direct-write path. Agent tokens are independent of web login tokens, scoped, default-deny, and revocable.

> 中文版本：[AGENT_API.md](./AGENT_API.md)

---

## 1. Prerequisites

- Admin password authentication must be enabled (`AUTH_ENABLED=True`). When no password is configured, Agent tokens can be neither issued nor used.
- The default deployment listens on localhost or behind a controlled reverse proxy. Use HTTPS for remote access.
- Send the token only in the `Authorization` header. **Never** put it in URLs, browser persistent storage, or model prompts.

---

## 2. Issuing and managing tokens

In the web UI, go to **Settings → Agent Access → Agent Access Tokens**. The plaintext is shown only once; only its SHA-256 digest is stored server-side.

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
| `funds:read` | `funds/{code}`, `funds/compare`, `search`, `screen`, `backtest/dca`, `refresh/{job_id}` (backtest jobs) |
| `health:read` | `data-status`, `portfolio-health`, `risk-report` |
| `transactions:read` | `transactions`, `transactions/{tx_id}` |
| `watchlist:read` | `watchlist` |
| `alerts:read` | `alerts` |
| `plans:read` | `auto-invest-plans` |
| `watchlist:write` | `watchlist` (add/update/remove; requires the server write switch) |
| `data:refresh` | `refresh` (start a task-based data refresh; NAV/metadata only; requires the server write switch), `refresh/{job_id}` (query refresh jobs) |
| `transactions:propose` | `proposals` (create/list/cancel your pending **ledger** proposals; requires the server write switch; execution belongs to the web administrator) |
| `plans:propose` | `proposals` (create/list/cancel your pending **auto-invest plan** proposals; requires the server write switch; execution belongs to the web administrator; new plans start disabled) |
| `alerts:propose` | `proposals` (create/list/cancel your pending **alert resolution** proposals; requires the server write switch; only advances the alert state, never writes the ledger; execution belongs to the web administrator) |
| `transactions:create` | `POST /api/agent/tools/transactions` (trusted single buy/sell direct write; requires the server write switch; downgrades to a proposal or rejects on precheck anomalies) |

The write scopes are `watchlist:write`, `data:refresh`, `transactions:propose`, `plans:propose`, `alerts:propose`, and `transactions:create`, all unchecked by default and gated by the server write switch (off by default). The switch is managed day-to-day by the administrator on the web Settings page ("Agent Access → Agent write capability", `GET/PUT /api/settings/agent-write`); enabling it requires the current login password, and the state persists in the database and is authoritative across multiple workers. The `ZFUNDPILOT_AGENT_WRITE_ENABLED` environment variable only matters in two cases: explicitly set to `0`/`false`/`no`/`off` it is an **emergency brake** (forced off, and the Settings page cannot enable it); set to `1`/`true`/`yes`/`on` it only serves as the first-start default when the database has no record. Calling a tool without the required scope returns **403**. The first two are low-risk direct writes; `transactions:propose` only submits ledger proposals, `plans:propose` only submits auto-invest plan proposals, and `alerts:propose` only submits alert-resolution proposals — none can write the ledger or plans directly; `transactions:create` is an independent pre-authorization that writes the ledger directly within limits — a token with only `transactions:create` (no `transactions:propose`) is rejected on precheck anomalies rather than downgraded.

`capabilities` only requires a valid token, not a specific scope; it returns only the tools granted to that token, marking write tools with `risk="write"`, proposal tools with `risk="propose"`, and `enabled` reflecting the server write switch; each tool also carries contract metadata `side_effect` (`read`/`additive`/`mutating`), `idempotent` (whether retrying with the same key and parameters is safe), `limits` (request-parameter caps), and `error_codes` (stable business error codes — see the "Unified capability table" below); the top-level `write_enabled` is the current switch value, and `write_locked: true` means the environment-variable emergency brake has locked the switch so the Settings page cannot enable it either. Proposal tools (`create_operation_proposal`, `list_operation_proposals`, `get_operation_proposal`, `cancel_operation_proposal`) use **multi-domain authorization**: holding `transactions:propose`, `plans:propose`, or `alerts:propose` lets you enter, but on `create` the scope is re-checked per `operation_type` (ledger ops need `transactions:propose`, plan ops need `plans:propose`, alert ops need `alerts:propose`), and a cross-domain op returns **403**; in `capabilities`, hitting any of these scopes lists these tools.

> The first three scopes are checked by default on the issuance panel. `transactions:read`, `watchlist:read`, `alerts:read`, `plans:read`, `watchlist:write`, `data:refresh`, `transactions:propose`, `plans:propose`, `alerts:propose`, and `transactions:create` are unchecked by default: opt in explicitly when needed, so existing tokens are never silently broadened.

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
  "request_id": "0f5c2d9a8b7e4c1fa2b3c4d5e6f70819",
  "generated_at": "2026-10-27T21:30:00+08:00",
  "currency": "CNY",
  "data": { }
}
```

- `schema_version`: response schema version, currently `1`. Additive fields do not bump it; only breaking changes do.
- `tool`: tool name matching the endpoint.
- `request_id`: ID of this request, matching the `X-Request-ID` header.
- `generated_at`: server-side timestamp with timezone.
- `currency`: amount currency, currently always `CNY`.
- `data`: tool-specific payload.

### Request ID

Every response carries an `X-Request-ID` header; successful tool envelopes and all error bodies also include
`request_id`. Clients may send `X-Request-ID` (8–64 ASCII letters, digits, or `._:-`) for cross-system correlation;
invalid values are replaced by the server. Include this ID when reporting issues. It is for log correlation only and
is **not an identity credential**; the server never authorizes requests or trusts claims based on it.

### Errors

Error responses keep the FastAPI-compatible `detail` field and add a stable `error` object:

```json
{
  "detail": "Agent token 缺少权限：funds:read",
  "error": {
    "code": "insufficient_scope",
    "message": "Agent token 缺少权限：funds:read",
    "request_id": "0f5c2d9a8b7e4c1fa2b3c4d5e6f70819",
    "retryable": false
  },
  "request_id": "0f5c2d9a8b7e4c1fa2b3c4d5e6f70819"
}
```

- `detail`: legacy field, unchanged in shape (string / object / validation list), so old clients keep working.
- `error.code`: stable code; branch on it. `error.message` is a Chinese fallback only — do not match text.
- `error.details`: optional business context (e.g. `field`, `index`, `reason`); for validation errors it is a compact `loc/type/msg` list.
- `error.retryable`: whether a retry is recommended; `true` for `429` and `503`.
- `error.retry_after`: optional suggested delay in seconds, matching the `Retry-After` header.

Generic codes: `bad_request`, `unauthorized`, `forbidden`, `not_found`, `method_not_allowed`, `conflict`,
`validation_error`, `rate_limited`, `internal_error`, `service_unavailable`. Agent auth adds `invalid_token`,
`expired`, `revoked`, `auth_disabled`, `insufficient_scope`; business codes are listed per tool
(e.g. `write_disabled`, `target_changed`, `idempotency_conflict`).

| Status | Meaning | Typical `error.code` |
|---|---|---|
| `400` | Invalid parameter (e.g. fund code is not 6 digits) | `bad_request` |
| `401` | Missing, invalid, expired, or revoked token | `invalid_token` / `expired` / `revoked` |
| `403` | Valid token but missing required scope, write switch off, or password auth not enabled | `insufficient_scope` / `write_disabled` / `auth_disabled` |
| `404` | Unknown tool or fund (only with a valid token) | `not_found` |
| `409` | Watchlist revision conflict, missing/existing object, unregistered fund, non-pending/expired proposal, or idempotency conflict | business code (e.g. `target_changed`) |
| `422` | Invalid body/parameters, or missing a valid `Idempotency-Key` | `validation_error` |
| `429` | Rate limit exceeded | `rate_limited` (`retryable=true`) |
| `503` | Database busy (e.g. backup/restore holds the write lock) | `database_busy` (`retryable=true`, retry after `Retry-After`) |

> `/api/agent/tools/*` is protected by a dedicated Agent auth middleware. Even a nonexistent tool path returns `401` without a valid token, so route existence is not leaked.

### Four response classes

Successful responses share the envelope above; the fields inside `data` fall into four classes depending on what the call does. Parse by class — **do not assume every success response has the same set of `data` fields**.

| Class | Representative tools | Key `data` fields | Idempotency / retry |
|---|---|---|---|
| Query | `get_portfolio_summary`, `list_positions`, `get_data_status`, `precheck_*` | Business fields; `valuation_basis` when amounts are involved; `as_of_date`/`as_of_date_semantics` for time snapshots; `pagination{limit,offset,total,has_more}` for lists | Read-only; safe to retry (still rate-limited) |
| Write | `add_watchlist_item`, `update_watchlist_item`, `remove_watchlist_item`, `start_data_refresh`, `record_transaction` | Always `ok`/`code`/`message`/`replayed`, plus tool-specific fields (below) | Requires `Idempotency-Key`; same key + same params returns `replayed=true` without a second write |
| Proposal | `create_operation_proposal`, `list_operation_proposals`, `get_operation_proposal`, `cancel_operation_proposal` | `proposal_id`/`operation_type`/`status`/`expires_at`/`summary`/`params`/`can_approve`/`can_cancel`/`execution_result` | Creation deduped by idempotency key; cancel is naturally idempotent; approval/rejection only via web login endpoints |
| Job | `start_data_refresh`, `run_dca_backtest`, `get_job_status` | `job_id`/`job_type`/`status`/`progress{done,total,current,phase}`/`result`/`error`/`created_at`/`updated_at`/`expires_at`/`can_cancel` | Start deduped by idempotency key; status is read-only and pollable |

**Query**

- Business fields only — no `ok`/`code`/`replayed`; success is determined by the HTTP status.
- Amounts use the latest formal NAV with `data.valuation_basis="latest_formal_nav"`; `as_of_date` is the maximum formal-NAV date across holdings and does not mean every fund was updated.
- Paginated tools (`list_transactions`/`list_watchlist`/`list_operation_proposals`/`list_alerts`/`search_funds`/`screen_funds`) return `pagination{limit,offset,total,has_more}`; `list_positions` returns `count`/`total`/`limit` without a `pagination` block.

**Write**

- `ok` is always `true` on 2xx; failures are non-2xx error responses, never a 2xx with `ok=false`.
- `code` is a **success code** (`created`/`updated`/`unchanged`/`removed`/`queued`/`recorded`/`downgraded`/`replayed`), a separate namespace from `error.code` — do not mix them.
- `replayed` means the call hit an idempotent replay; a replay never writes twice.
- Watchlist writes add `fund_code`/`changed`/`revision`/`before`/`after`.
- Job start (refresh/backtest) adds `job_id`/`status`/`fund_count`/`expires_at` and responds `202`.
- Direct record adds `execution_mode`, `transaction_id` (direct) or `proposal_id` (downgraded), `operation_id`/`receipt`/`daily_quota`/`verify_path`.
- **`execution_mode` is finalized as `direct` / `proposal`; there is no `rejected`.** A rejected direct record always returns a non-2xx stable error code (e.g. `409 duplicate_candidate`, `429 daily_quota_exceeded`); clients must not treat an error response as "succeeded but rejected".

**Proposal**

- `status ∈ {pending,succeeded,failed,conflict,rejected,cancelled,expired}`; everything except `pending` is terminal.
- Successful approval is `succeeded` (**not** `approved`); execution failure is `failed`, target changes/concurrent conflicts during execution are `conflict`, an administrator rejection is `rejected`, timeout is `expired`, creator cancellation is `cancelled`.
- `execution_result` is present only in terminal states and depends on `operation_type`; `can_approve`/`can_cancel` are `true` only while `pending`.
- Approval/rejection is only available via web login endpoints `POST /api/proposals/{id}/approve|reject`; Agent tokens cannot call them.

**Job**

- `job_type` is currently `data_refresh` (data refresh) or `dca_backtest` (read-only DCA backtest); `status ∈ {queued,running,succeeded,failed,interrupted}`, the last three being terminal.
- `result` depends on `job_type`: `data_refresh` is `{ok,updated,failed,partial,errors[]}`; `dca_backtest` is the result structure from §5.20 (`ok`/`message`/`simulation_note`/`requested`/`fund_count`/`result_count`/`failed_count`/`results[]`). `results[].status` and the task `status` are independent: a single fund failing does not make the task fail. New job types must reuse the same envelope and the same status endpoint, and must document their `result` shape here.
- `get_job_status` is entered with either `data:refresh` or `funds:read`, then re-checked by `job_type` (refresh→`data:refresh`, backtest→`funds:read`, unknown type→`403`); ownership is checked first, so another token's job always returns `404`.
- On restart, leftover `queued`/`running` jobs are marked `interrupted` — never falsely reported as succeeded.
- `can_cancel` is currently always `false` (reserved field).

### Contract versioning and compatibility

- `schema_version` describes the **response envelope**, currently `1`. Adding fields, error codes, or tools does **not** bump it; removing/renaming fields or changing types/semantics does, together with a `CHANGELOG.md` entry.
- `error.code`, success `code`, `execution_mode`, proposal `status`, and job `status`/`job_type` are stable contract values; `error.message`/`detail` are Chinese fallback text that may change — **do not match on text**.
- New enum values (a new `operation_type`, `job_type`, or proposal status) are backward-compatible; clients must degrade safely on unknown values (display the raw code, and never launch a write based on it).
- Times are server-authoritative: `generated_at` is the response time; data timestamps are always `data.as_of_date`/`updated_at` — never rely on the client clock.
- Old fields are kept for at least one minor version; removal or renaming is first marked in the `Deprecated` section of `CHANGELOG.md`.
- When docs and implementation disagree, the endpoint OpenAPI and `get_agent_capabilities` output win, and the discrepancy is treated as a documentation defect.

### Rate limiting

**120 requests per minute** per token per endpoint by default. Path parameters count as the same endpoint (for example, different fund codes share the `funds/{code}` budget), so enumerating codes cannot bypass the limit. Heavier endpoints use lower limits: `search` is 60/min; `screen`, `backtest/dca`, `benchmark`, and `industry-exposure` are 20/min; watchlist writes (`POST`/`PATCH`/`DELETE`) are 30/min and count separately from `GET` on the same path; `POST refresh` is 10/min (network-fetching, so avoid high-frequency triggers); `POST /api/agent/tools/transactions` (trusted single direct write) is 10/min and counts separately from the `GET` ledger list on the same path. Screening shares one bucket whether or not metrics are requested, so switching parameters cannot bypass it. Exceeding a limit returns `429`; retry after the `Retry-After` seconds. Rate-limit and metric-enrichment concurrency are **in-process** state; multiple workers count independently.

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

### Unified capability table

The table below summarizes the contract metadata for all Agent tools (matching the `side_effect`/`idempotent`/`limits`/`error_codes` fields returned by `get_agent_capabilities`). Rows are grouped by side effect: **Read** (changes no state, including read-only simulation and `precheck_*` pre-checks), **Additive** (only appends, never overwrites existing data; safe to retry with an idempotency key), and **Modify/Delete** (may overwrite or remove existing data). `risk` and `side_effect` are orthogonal: `risk` describes the authorization tier (read / direct write / propose), while `side_effect` describes how data is affected. For example `precheck_*` has `risk=Propose` (requires `transactions:propose`) but `side_effect=Read` (the pre-check itself writes no ledger and creates no proposal). The `idempotent` column indicates whether retrying with the same key and parameters is safe (writes rely on `Idempotency-Key`; cancelling a proposal is inherently idempotent).

| Tool | Method | HTTP path | Scope | Risk | Side effect | Web approval | Limits | Stable error codes |
|---|---|---|---|---|---|---|---|---|
| `compare_funds` | `GET` | `/api/agent/tools/funds/compare` | funds:read | Read | Read | No | codes 1-20 | validation_error, insufficient_scope, rate_limited |
| `get_agent_capabilities` | `GET` | `/api/agent/tools/capabilities` | — | Read | Read | No | — | — |
| `get_benchmark_comparison` | `GET` | `/api/agent/tools/benchmark` | portfolio:read | Read | Read | No | codes 1-20 | validation_error, insufficient_scope, rate_limited |
| `get_data_status` | `GET` | `/api/agent/tools/data-status` | health:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited |
| `get_fund_detail` | `GET` | `/api/agent/tools/funds/{code}` | funds:read | Read | Read | No | nav_limit 1-250 (default 30) | validation_error, insufficient_scope, rate_limited, not_found |
| `get_industry_exposure` | `GET` | `/api/agent/tools/industry-exposure` | portfolio:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited |
| `get_job_status` | `GET` | `/api/agent/tools/refresh/{job_id}` | data:refresh / funds:read (checked by `job_type`) | Read | Read | No | — | validation_error, insufficient_scope, rate_limited, not_found |
| `get_operation_proposal` | `GET` | `/api/agent/tools/proposals/{proposal_id}` | any of transactions/plans/alerts:propose | Read | Read | No | — | validation_error, insufficient_scope, rate_limited, not_found |
| `get_portfolio_curve` | `GET` | `/api/agent/tools/portfolio-curve` | portfolio:read | Read | Read | No | max_points 10-2000 (default 365) | validation_error, insufficient_scope, rate_limited |
| `get_portfolio_health` | `GET` | `/api/agent/tools/portfolio-health` | health:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited |
| `get_portfolio_summary` | `GET` | `/api/agent/tools/portfolio-summary` | portfolio:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited |
| `get_returns` | `GET` | `/api/agent/tools/returns` | portfolio:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited |
| `get_risk_report` | `GET` | `/api/agent/tools/risk-report` | health:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited |
| `get_transaction` | `GET` | `/api/agent/tools/transactions/{tx_id}` | transactions:read | Read | Read | No | — | validation_error, insufficient_scope, rate_limited, not_found |
| `list_alerts` | `GET` | `/api/agent/tools/alerts` | alerts:read | Read | Read | No | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `list_auto_invest_plans` | `GET` | `/api/agent/tools/auto-invest-plans` | plans:read | Read | Read | No | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `list_operation_proposals` | `GET` | `/api/agent/tools/proposals` | any of transactions/plans/alerts:propose | Read | Read | No | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `list_positions` | `GET` | `/api/agent/tools/positions` | portfolio:read | Read | Read | No | limit 1-500 (default 200) | validation_error, insufficient_scope, rate_limited |
| `list_transactions` | `GET` | `/api/agent/tools/transactions` | transactions:read | Read | Read | No | limit 1-200 (default 50); offset >=0 | validation_error, insufficient_scope, rate_limited |
| `list_watchlist` | `GET` | `/api/agent/tools/watchlist` | watchlist:read | Read | Read | No | limit 1-200 (default 50); offset >=0 | validation_error, insufficient_scope, rate_limited |
| `precheck_backfill` | `POST` | `/api/agent/tools/precheck/backfill` | transactions:propose | Propose | Read | No | tx_ids 1-50 | validation_error, insufficient_scope, rate_limited |
| `precheck_reconciliation` | `POST` | `/api/agent/tools/precheck/reconciliation` | transactions:propose | Propose | Read | No | holdings 1-100 | validation_error, insufficient_scope, rate_limited |
| `precheck_transactions` | `POST` | `/api/agent/tools/precheck/transactions` | transactions:propose | Propose | Read | No | items 1-200; csv_text <=5MB | validation_error, insufficient_scope, rate_limited |
| `run_dca_backtest` | `POST` | `/api/agent/tools/backtest/dca` | funds:read | Read | Read | No | fund_codes 1-5; max_points 10-2000 (default 365); amount_per_period >0 and <=1000000; Idempotency-Key 16-128 | validation_error, insufficient_scope, rate_limited, not_found, idempotency_conflict, idempotency_expired, backtest_busy |
| `screen_funds` | `GET` | `/api/agent/tools/screen` | funds:read | Read | Read | No | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `search_funds` | `GET` | `/api/agent/tools/search` | funds:read | Read | Read | No | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `add_watchlist_item` | `POST` | `/api/agent/tools/watchlist` | watchlist:write | Write | Additive | No | note <=500 chars; group_name <=50 chars | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, already_exists |
| `create_operation_proposal` | `POST` | `/api/agent/tools/proposals` | any of transactions/plans/alerts:propose | Propose | Additive | Web approval | batch_import.items 1-50; backfill_transaction_navs.items 1-50 | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, target_changed, conflict, fee_unknown, pending_nav, no_buy_record |
| `record_transaction` | `POST` | `/api/agent/tools/transactions` | transactions:create | Write | Additive | No | — | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, fee_unknown, pending_nav, no_buy_record |
| `start_data_refresh` | `POST` | `/api/agent/tools/refresh` | data:refresh | Write | Additive | No | fund_codes 1-50 | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, already_running, busy |
| `cancel_operation_proposal` | `DELETE` | `/api/agent/tools/proposals/{proposal_id}` | any of transactions/plans/alerts:propose | Write | Modify/Delete | No | — | not_found, conflict, insufficient_scope, rate_limited |
| `remove_watchlist_item` | `DELETE` | `/api/agent/tools/watchlist/{code}` | watchlist:write | Write | Modify/Delete | No | — | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, target_changed |
| `update_watchlist_item` | `PATCH` | `/api/agent/tools/watchlist/{code}` | watchlist:write | Write | Modify/Delete | No | note <=500 chars; group_name <=50 chars | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, target_changed |

> The stable error codes column lists the **business** error codes each tool may return; it excludes unexpected exceptions (always 500 `internal_error`) beyond the common auth/rate-limit codes. `validation_error`/`insufficient_scope`/`rate_limited` are shared by nearly all tools and are listed here for reference. `limits` are the numeric/item caps on request parameters, so an Agent can adapt its paging and batching.

---

## 5. Tools

Sections 5.1–5.20 are read-only or read-only simulations (5.20 creates a backtest job via `POST` and then polls); 5.21–5.23 are controlled writes, all off by default. No tool accepts settings, import/export, or fund-moving operations, and ledger writes happen only after a web administrator approves a proposal.

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

Single transaction detail. Scope: `transactions:read`. Fields match one item from 5.8, plus top-level `data.valuation_basis` and `data.row_digest` (the target row's content SHA-256 covering `fund_code/action/date/amount/shares/nav/fee/channel/note/is_t1`, numbers `round(_,4)`; use it as `expected_digest` when building `update_transaction`/`delete_transaction` proposals; for a conversion leg, the same row digest is used as `expected_from_digest`/`expected_to_digest` in a `delete_conversion` proposal); an unknown id returns `404`.

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

Only whitelisted fields are returned: `id`, `alert_type`, `fund_code`, `fund_name`, `status`, `triggered_return`, `threshold`, `record_date`, `ex_date`, `pay_date`, `per_share`, `estimated_amount`, `held_shares`, `dividend_method`, `created_at`, `resolved_at`, `tx_id`, plus `row_digest` (SHA-256 over the alert's business fields including `status/resolved_at/tx_id`, used as `expected_digest` for `resolve_alert`; legacy rows with a NULL `alert_type` are normalized to `dividend`).

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
| `row_digest` | SHA-256 of the plan config (covers `fund_code/amount/cadence/day_of_week/day_of_month/channel/note/enabled`; `amount` rounded to 4 dp; `enabled` normalized to 0/1; **excludes** `next_run`/`last_run`/`last_tx_id` scheduler bookkeeping so an active plan's digest stays stable across runs). Use it as `expected_digest` in `update_plan`/`toggle_plan`/`delete_plan` proposals |
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

Start a **read-only DCA backtest job**. Scope: `funds:read`. This is a **read-only historical simulation**: it does not write the formal NAV table, transactions, auto-invest plans, watchlist, or fund metadata, and it is neither a forecast nor allocation advice.

The endpoint creates the job and immediately returns `202` with a `job_id`; poll `GET /api/agent/tools/refresh/{job_id}` (the same endpoint serves refresh and backtest jobs and re-checks scope by `job_type`, see §5.22). The backtest runs in the background fund by fund, so `progress.done/total` reflects completed funds and `progress.current` is the fund code being processed.

An `Idempotency-Key` is required (16–128 safe ASCII chars): the same key and parameters replay the original `job_id` (`replayed=true`); the same key with different parameters or a different operation returns `409 idempotency_conflict`, and expired keys return `409 idempotency_expired`. Creation response `data`: `ok`, `code` (`queued`/`replayed`), `message`, `replayed`, `job_id`, `status`, `fund_count`, `expires_at`.

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

The range is limited to 10 years; monthly/biweekly/weekly plans produce at most roughly 120/261/522 periods. Invalid JSON, missing required fields, or unknown fields return `422`; authentication and scope semantics match the other tools (`401`/`403`). When concurrency is full the creation returns `429 backtest_busy` with `Retry-After` instead of queueing; a 429 creates no job or idempotency record, so retrying with the same key after the indicated delay is safe. Audits `dca_backtest_started/succeeded/failed/busy/rejected` record only counts and the token prefix.

Once polling reaches `status="succeeded"`, `data.result` contains: `ok`, `message`, `simulation_note`, `requested`, `fund_count`, `result_count`, `failed_count`, `results[]`. `failed_count` counts result rows (a fund's `dca` and `lumpsum` rows count separately); `ok` is `false` only when every result failed. Partial failures keep `ok=true`; use `message` and each result's `status` for details.

Each result contains:

- Basics: `fund_code`, `fund_name`, `strategy` (`dca`/`lumpsum`), `status` (`ok`/`partial`/`failed`), `code`, `message`.
- Data: `data_source` (`database`/`remote`/`database+remote`/`none`), `data_start`, `data_end`, `valuation_date`, `skipped_periods`, `fee_ok`. `data_start`/`data_end` are the actual available NAV range and are empty strings when no valid NAV exists.
- Metrics: `cadence`, `amount_per_period`, `total_periods`, `invested_capital`, `total_fees`, `final_value`, `redemption_fee`, `net_final_value`, `total_return`, `annualized_return`, `max_drawdown`, `sharpe_ratio`.
- Details: `curve` (sampled to `max_points`), `curve_points`, `periods_detail` (non-empty only with `include_periods=true`), `periods_detail_count`, `caveats`.
- `fee_ok=false` means the fee table could not be fetched; even when `fee_ok=true`, a missing purchase or redemption tier is counted as 0 and explained in `caveats`, which must not be read as a true zero-fee fund.
- `status="failed"` uses `code="insufficient_nav"` (fewer than 2 valid NAV points) or `no_periods` (no executable planned date), and does not output apparently valid zero-return metrics.
- `status="partial"` with `code="partial_coverage"` means some planned periods were skipped because NAV data did not cover them or because multiple periods mapped to the same NAV date; `skipped_periods` gives the count. When the requested end is later than the last available NAV date, the trailing uncovered periods fall into this case — the backtest still runs on the available data, and `valuation_date`/`data_end` reflect the actual coverage.

> Planned dates never precede the requested start. When multiple plans map to the same NAV date, only the first executes so that periods are not stacked onto one day. The closing valuation, redemption holding-period calculation, and XIRR terminal cash flow all use the last available NAV date (`valuation_date`), not the requested end date. NAV data is read from the database first and fetched in memory only when coverage is insufficient; nothing is written, and `data_end` may be earlier than `end_date`. Each fund's fee table is used as a single snapshot. Dividends, splits, and reinvestment are not simulated; max drawdown and Sharpe use the market-value curve, so DCA cash flows affect comparability. A request is capped at 5 funds, may be slowed by external NAV/fee fetches, should be preceded by `data-status`, and is limited to 20 requests per minute. Backtest concurrency is capped at 2 in-process; when full, creation immediately returns `429 backtest_busy` (`Retry-After: 60`) instead of queueing, and multiple workers count independently. A task `status="failed"` means an execution-time exception (`data.error` explains it), which is different from a per-fund `results[].status="failed"` — in the latter case the task itself still ends as `succeeded`.

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

- Every write request must send `Idempotency-Key` (16–128 safe ASCII characters). Same key and parameters replay the original result with `replayed=true`; same key with different parameters or a different operation returns `409 idempotency_conflict`; expired keys return `409 idempotency_expired`. Records are kept for 90 days, plus a 30-day grace window for troubleshooting; after that a daily maintenance job reclaims them (a retry with the same over-grace key is treated as a new request — use a new `Idempotency-Key`).
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
| `get_job_status` | `GET /api/agent/tools/refresh/{job_id}` | Query progress/result; only the creating token can read; serves both refresh and backtest jobs |

`get_job_status` also queries backtest jobs (`job_type="dca_backtest"`, see §5.20). The endpoint is entered with either `data:refresh` or `funds:read`, then re-checks by job type: refresh jobs need `data:refresh`, backtest jobs need `funds:read`, and an unknown `job_type` always returns `403`; ownership is checked first, so another token's job still returns `404`.

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

### 5.23 Ledger, auto-invest plan, and alert-resolution proposals (write, requires web approval; off by default)

This group only submits **pending proposals** and never writes the ledger or plans directly (for trusted direct write, see §5.24). Proposal tools use **multi-domain authorization**: holding `transactions:propose`, `plans:propose`, or `alerts:propose` lets you call `list/get/cancel`, but on `create` the scope is re-checked per `operation_type` (ledger ops need `transactions:propose`, plan ops need `plans:propose`, alert ops need `alerts:propose`), and a cross-domain op returns **403**; in `capabilities`, hitting any of these scopes lists these tools. Also gated by the server write switch (see the write-switch notes above). Thirteen `operation_type` values are supported: `add_transaction` (new), `update_transaction` (modify a single row, must carry `expected_digest` row-version precondition), `delete_transaction` (delete a single row, must carry `expected_digest`), `add_conversion` (fund conversion; writes a sell leg and a buy leg sharing one `conversion_id`), `delete_conversion` (delete a whole conversion pair by `conversion_id`, carrying both legs' `expected_digest`), `batch_import` (append multiple transactions under one proposal, one approval, all-or-nothing in one transaction), plus four F5 auto-invest plan maintenance ops: `create_plan` (create a plan, forced `enabled=0`), `update_plan` (partial-field patch with `expected_digest` version precondition), `toggle_plan` (explicit `enable` boolean), and `delete_plan` (delete the plan row; history untouched), one F6.1 alert-resolution op: `resolve_alert` (confirm/ignore a dividend or TP/SL alert; advances only the alert state machine and never writes the ledger), one F6.2 backfill op: `backfill_transaction_navs` (fill the missing NAV — and the derived shares/amount/fee — of existing transactions whose `nav` is NULL; must carry a per-row `expected_digest` row-version precondition; supports an explicit batch of 1–50 `tx_ids`, written atomically), and one F6.3 manual-execution op: `execute_plan` (insert one buy transaction for an existing plan and advance its `last_run`/`last_tx_id`; never recomputes `next_run` or triggers the scheduler; requires the plan's `row_digest`). Approval, rejection, execution, and state transitions happen server-side on the web, and the execution path performs no network access. Updates and deletes operate on the whole row; conversion legs still cannot be edited in isolation — use `delete_conversion` for whole-pair removal. `batch_import` only appends, never clears, and does not support in-batch update/delete/conversion or `dividend_alert_id`. **Plan operations never write the `transactions` table and never trigger the scheduler**; new plans start disabled, and enabling requires a separate `toggle_plan` proposal. **Backfill writes only the `nav/shares/amount/fee` four fields with zero network access at approval; dividend rows cannot be backfilled.**

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

Modify a single row (fetch `row_digest` first, then submit the full field set with `expected_digest`):

```bash
# 1) Fetch the target row digest
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/transactions/12 | jq '.data.row_digest'

# 2) Submit an update proposal (amount 1000->2000; other fields echoed in full)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: upd-1a2b3c4d-5e6f-7a8b-9c0d" \
  -d '{
    "operation_type": "update_transaction",
    "params": {
      "tx_id": 12,
      "expected_digest": "<row_digest from step 1>",
      "fund_code": "005827", "action": "buy", "date": "2026-10-30",
      "amount": 2000, "fee": 1, "channel": "Alipay", "is_t1": false, "note": ""
    }
  }' | jq
# data.summary includes tx_id / before / after / changed_fields (e.g. ["amount"])
```

Delete a single row (`reason` is optional):

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: del-9f8e7d6c-5b4a-3c2d" \
  -d '{
    "operation_type": "delete_transaction",
    "params": {"tx_id": 12, "expected_digest": "<row_digest>", "reason": "recorded by mistake"}
  }' | jq
# data.summary includes tx_id / before / reason
```

Fund conversion (sell the from fund + buy the to fund; written atomically as a pair on approval):

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: conv-0f6c2f9a-4b1e-4e2a" \
  -d '{
    "operation_type": "add_conversion",
    "params": {
      "from_code": "005827",
      "to_code": "110011",
      "date": "2026-10-30",
      "from_shares": 100,
      "from_nav": 2.1,
      "from_fee": 0.5,
      "to_nav": 3.2,
      "channel": "Alipay"
    }
  }' | jq
# data.summary.conversion contains from (sell) / to (buy); approval receipt contains from_id/to_id
```

Delete a whole conversion pair (find both legs by `conversion_id`, then take each `row_digest`):

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions?conversion_id=<conversion_id>" | jq

curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: delconv-1a2b3c4d-5e6f-7a8b" \
  -d '{
    "operation_type": "delete_conversion",
    "params": {
      "conversion_id": "<conversion_id>",
      "expected_from_digest": "<sell-leg row_digest>",
      "expected_to_digest": "<buy-leg row_digest>",
      "reason": "recorded by mistake"
    }
  }' | jq
```

Link a dividend/reinvest transaction to a dividend alert (optional; confirmed atomically at approval):

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: div-0f6c2f9a-4b1e-4e2a" \
  -d '{
    "operation_type": "add_transaction",
    "params": {
      "fund_code": "005827",
      "action": "dividend",
      "date": "2026-10-30",
      "amount": 120,
      "dividend_alert_id": 7
    }
  }' | jq
```

Batch append (single proposal, single approval, atomic write):

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: batch-0f6c2f9a-4b1e-4e2a" \
  -d '{
    "operation_type": "batch_import",
    "params": {
      "note": "October statement backfill",
      "transactions": [
        {"fund_code": "005827", "action": "buy", "date": "2026-10-08",
         "amount": 1000, "fee": 1, "channel": "Alipay"},
        {"fund_code": "005827", "action": "sell", "date": "2026-10-20",
         "shares": 50, "nav": 2.15, "fee": 0.5, "channel": "Alipay"}
      ]
    }
  }' | jq
```

Auto-invest plan maintenance (F5, scope `plans:propose`). Fetch `row_digest` first, then submit with `expected_digest`:

```bash
# 1) Fetch the target plan's row_digest (list_auto_invest_plans carries it per item)
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/auto-invest-plans" | jq '.data.plans[] | {id, row_digest}'

# 2a) Create an auto-invest plan (starts disabled, never executed by the scheduler)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-create-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "create_plan",
    "params": {
      "fund_code": "005827", "amount": 500, "cadence": "week",
      "day_of_week": 0, "channel": "Alipay", "note": "payday DCA"
    }
  }' | jq
# data.summary has fund_code / amount / cadence / schedule / enabled=false / next_run / scheduler_hint

# 2b) Update a plan (partial patch; explicit null clears a day field)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-upd-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "update_plan",
    "params": {
      "plan_id": 3, "expected_digest": "<row_digest>",
      "amount": 800
    }
  }' | jq
# data.summary has plan_id / before / after / changed_fields (e.g. ["amount"]) / scheduler_hint

# 2c) Toggle a plan (explicit enable boolean, action semantics)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-toggle-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "toggle_plan",
    "params": {"plan_id": 3, "expected_digest": "<row_digest>", "enable": true}
  }' | jq
# data.summary has enabled_before / enabled_after / next_run / scheduler_hint

# 2d) Delete a plan (only the plan row; historical transactions are kept)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-del-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "delete_plan",
    "params": {"plan_id": 3, "expected_digest": "<row_digest>"}
  }' | jq
```

```bash
# 2e) Resolve an alert (confirm/ignore; advances only the alert state)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: alert-confirm-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "resolve_alert",
    "params": {
      "alert_type": "dividend",
      "alert_id": 12,
      "expected_digest": "<row_digest>",
      "status": "confirmed",
      "tx_id": 345
    }
  }' | jq
```

```bash
# 2f) Manually execute an auto-invest plan (insert one buy and advance the plan bookkeeping)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-exec-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "execute_plan",
    "params": {
      "plan_id": 3,
      "expected_digest": "<row_digest>",
      "trade_date": "2026-11-07",
      "fee": 1.5
    }
  }' | jq
# data.summary carries plan_id / fund_code / amount / trade_date / is_t1 /
# fee / fee_source / before / after / warnings
```

- `add_transaction` `params` accept only the whitelist: `fund_code` (six digits, must already be registered), `action` (`buy`/`sell`/`dividend`/`reinvest`), `date` (`YYYY-MM-DD`), `amount`/`shares`/`nav` (buy/sell need enough fields to derive the rest; sell requires shares; dividend requires an amount), `fee`, `channel`, `note`, `is_t1`, and optional `dividend_alert_id` (only for `dividend`/`reinvest`). Unknown fields return `422 validation_error`.
- `batch_import` `params` are `transactions` (1–50 items, each with exactly the `add_transaction` field set, but `fund_code` is **required** and `fund_name` is not accepted) plus an optional `note`. `dividend_alert_id` is not supported (`422 batch_invalid_item`, `code=unsupported_in_batch`); `clear_existing`/`fetch_meta` are ignored and surfaced in `summary.warnings` and `params.ignored_fields`, never clearing data or fetching over the network. Creation hard-rejects structural errors, any bad item (`422 batch_invalid_item` with `index`/`issues`), unregistered funds (`409 fund_not_registered` with `index`/`fund_code`), and in-batch duplicates (`409 batch_internal_duplicate` with `index`/`other_index`); duplicates against the ledger or pending proposals (own or another principal's) are warnings only; batch proposals are not cross-checked against other *batch* pending proposals (duplicate detection compares single `add_transaction` proposals only — a known limitation, so run `precheck_transactions` before submitting). Approval validates the whole batch first (funds still present, params still valid, running per `fund+channel` final balance non-negative) and only then inserts every row; any failure writes nothing, marks the proposal `conflict`, and returns `index`/`executed_before_failure=0` in `execution_result`. The `summary` carries `count`/`actions`/`funds`/`date_range`/`amount_total` (buy amounts plus sell net proceeds, not net invested)/`items`, and a successful execution result carries `tx_ids`/`count`.
- `add_conversion` `params`: `from_code`, `to_code` (both six digits, registered, and different), `date`, `from_shares` (>0), optional `from_nav`/`from_fee`, optional `to_amount`/`to_nav`/`to_fee`, `channel`, `note`, `is_t1`. For non-T+1, the to-leg amount/shares must be derivable (when `to_amount` is omitted it is derived from the sell-leg net proceeds); for T+1 the to-leg amount may be deferred and approval will not block it. Approval writes both `sell`/`buy` legs atomically with a newly generated shared `conversion_id` and never fetches NAVs; if the from-leg shares exceed available shares in that channel it is a warning only, not a block. `summary.conversion` contains both legs.
- `delete_conversion` `params` are `conversion_id` + `expected_from_digest` + `expected_to_digest` (each leg's `row_digest` from `GET /api/agent/tools/transactions/{tx_id}`) + optional `reason`. At creation the `conversion_id` must link exactly two rows that are a standard sell/buy pair, otherwise `404 conversion_not_found` / `409 conversion_leg_mismatch`; a digest mismatch returns `409 target_changed` with `leg=from|to`. Approval re-reads both legs and deletes the pair in the same transaction; deleting the buy leg returns `insufficient_shares_after_change` if it would leave later sells over-shares, while removing the sell leg is always allowed.
- `add_transaction` with `action=dividend`/`reinvest` may carry `dividend_alert_id` (positive integer): approval writes the transaction and marks the matching alert `confirmed`, backfilling `tx_id`, in one transaction. A missing/resolved/non-dividend alert or a fund mismatch returns `dividend_alert_not_found`, `dividend_alert_resolved`, `dividend_alert_type_mismatch`, or `dividend_alert_fund_mismatch` at approval (all `conflict`, no transaction written).
- `update_transaction` `params` require `tx_id` (target transaction id) and `expected_digest` (the target row's content hash, taken from `GET /api/agent/tools/transactions/{tx_id}` as `row_digest`), plus the **full field set** identical to `add_transaction` (not a partial patch; omitted fields take defaults). The hash covers `fund_code/action/date/amount/shares/nav/fee/channel/note/is_t1` (numbers `round(_,4)`, `None` preserved). If the target changed (`409 target_changed`) or was deleted (`404 target_not_found`) the proposal is rejected at creation; it is re-checked at approval and, if changed/deleted, resolves to `conflict` (`target_changed`/`target_deleted`) without overwriting. Changing `fund_code`/`channel` validates shares on both sides; changing the fund adds a warning.
- `delete_transaction` `params` are `tx_id` + `expected_digest` + optional `reason`. At approval the hash is re-checked and the row deleted; deleting a buy that would leave later sells over-shares returns `insufficient_shares_after_change` (not deleted), while deleting a sell is always allowed.
- **Conversion legs** (`conversion_id` set) cannot be updated/deleted in isolation: `409 conversion_leg_isolated`. Use `delete_conversion` to remove the whole pair rather than operating on individual legs.
- `create_plan` `params` (scope `plans:propose`): `fund_code` (six digits, must be registered), `amount` (>0), `cadence` (`daily`/`week`/`biweek`/`month`), `day_of_week` (0–6, 0=Monday; required for `week`/`biweek`, forbidden otherwise), `day_of_month` (1–31; required for `month`, forbidden otherwise), optional `channel`/`note`. **Hard-rejects** `enabled`/`next_run`/`last_run`/`last_tx_id` (`422 validation_error`; toggling must use a separate `toggle_plan`, and scheduler bookkeeping is server-owned). New plans are forced to `enabled=0`; on approval `next_run` is computed at execution time. Duplicate detection is warning-only: an existing plan with the same config, or a pending `create_plan` with the same digest.
- `update_plan` `params` (scope `plans:propose`): `plan_id` + `expected_digest` (the plan's `row_digest` from `list_auto_invest_plans`) + any subset of the `create_plan` config fields (**partial patch**; explicit `null` clears `day_of_week`/`day_of_month`). The merged full config must pass `_validate_plan_config` (cross rules match the web UI: the day field for a non-matching cadence must be `None`). Target missing → `404 target_not_found` (with `plan_id`); digest mismatch → `409 target_changed`; merge-validation failure → `422 validation_error` (transaction rolls back). The `summary` carries `before`/`after`/`changed_fields`/`scheduler_hint`.
- `toggle_plan` `params` (scope `plans:propose`): `plan_id` + `expected_digest` + `enable` (boolean, required). **Does not recompute `next_run`** (matches the web toggle); when enabling a plan whose `next_run` is overdue, `summary.scheduler_hint` notes the scheduler will catch up one run soon. Same-state toggle is rejected (`422 validation_error`, advising a fresh `row_digest`). Target missing/mismatch errors match `update_plan`. The digest covers `enabled`, so toggling counts as a config change.
- `delete_plan` `params` (scope `plans:propose`): `plan_id` + `expected_digest`. Approval re-checks the digest and deletes only the plan row; historical transactions and scheduler bookkeeping are untouched. The `summary` carries `before`.
- `resolve_alert` `params` (scope `alerts:propose`): `alert_type` (`dividend`/`take_profit`/`stop_loss`), `alert_id`, `expected_digest` (the alert's `row_digest` from `list_alerts`), `status` (only `confirmed`/`ignored`; **no rollback to `pending`** — correct a mistake on the web UI), and an optional `tx_id` (only for a dividend alert with `status=confirmed`, linking one **existing** dividend/reinvestment transaction; no new transaction is created). At creation the service verifies the alert exists, the type matches, it is still `pending`, the digest matches, and any linked tx exists with the right action/fund and is not already linked to another alert. At approval the same checks are re-run in one transaction and, on success, only the alert's `status`/`resolved_at`/`tx_id` are updated — **the `transactions` table is never written**. Any state change alters `row_digest`. Error codes: `404 target_not_found`; `409 not_pending`/`target_changed`/`tx_not_found`/`tx_mismatch`/`tx_already_linked` (returned directly at creation; marked `conflict` at approval with `reason` `target_deleted`/`target_changed`/`not_pending`/`alert_type_changed`). The `summary` carries `alert_id`/`alert_type`/`before_status`/`after_status`/`linked_tx_id` plus the alert's business fields.
- `backfill_transaction_navs` `params` (scope `transactions:propose`): `items` (1–50 entries, each `{tx_id, expected_digest, fee?}`; `tx_id` is the target transaction id, `expected_digest` comes from `GET /api/agent/tools/transactions/{tx_id}` `row_digest`, and the optional `fee` is required only when the server cannot compute the fee; `tx_id` is unique within the batch). **Only explicitly named rows are processed — there is no "backfill everything".** Only the `nav/shares/amount/fee` four fields are written; `date/action/fund_code/channel/note/is_t1` are never touched. A dividend row cannot be backfilled by NAV (its `nav` is the per-share payout), so the whole batch is rejected with `422 dividend_not_backfillable`; a row whose `nav` is already set returns `409 nav_present`; a stale `expected_digest` returns `409 target_changed`; a missing row `409 target_not_found`; no usable NAV in the local NAV table `409 nav_unavailable`; an unknown fee/confirmation NAV, a sell with no buy record, or a buy missing its amount `409 fee_unknown` (retry with an explicit `fee`). At creation each row's `nav` (per the T+1 rule: same-day NAV, or next-day for T+1; falls back to the first later NAV date) and `fee` (reuse a non-zero fee `existing`; otherwise compute `fetched` — buy by amount, sell by shares, matching the web offline backfill; a sell with no buy record falls into `fee_unknown` instead of silently writing 0; an Agent-supplied `fee` is `explicit`) are precomputed **at creation, outside the write transaction** (NAV is local; a missing fee may fetch fee rates once) and snapshotted into `summary_json`, so **approval never touches the network or recomputes drifting values**; the write transaction only re-reads target rows for digest verification, and if any row cannot be executed the whole batch is rejected and no dangling proposal is created. At approval each row is re-read in one transaction (`nav IS NULL` + digest match); only if all pass are the snapshot values written as a batch — any row already backfilled/changed/deleted marks the whole proposal `conflict` (`partially_updated`/`target_changed`/`target_deleted`/`proposal_corrupt`) with no partial write. The `summary` carries `count`/`funds`/`fee_sources`/`items` (each row's `before`/`after` cover only the four backfilled fields; `nav_date` marks the NAV date used, including T+1; for a T+1 sell the backfilled `nav` uses the next-day NAV while the redemption fee is still computed from the trade-date NAV, matching the existing web behavior).
- `execute_plan` `params` (scope `transactions:propose`): `plan_id` + `expected_digest` (the plan's `row_digest` from `list_auto_invest_plans`) + an optional `trade_date` (`YYYY-MM-DD`; defaults to today in Asia/Shanghai; only `today-7` through `today` are allowed) + an optional `fee` (required only when the server cannot compute the purchase fee). **Amount/channel/note/`is_t1`/enablement and scheduler bookkeeping fields (`enabled`/`next_run`/`last_run`/`last_tx_id`) are hard-rejected (`422 validation_error`)**: amount, channel, and note come from the plan snapshot, and `is_t1` is derived from whether the trade date is today and the proposal was created at or after 15:00. At creation purchasability is checked once outside the write transaction and the fee is fetched (skipped when `fee` is explicit); an unknown fee (`fee_unknown`) rejects creation rather than silently writing 0. Approval is zero-network: it inserts one `buy` from the snapshot (`shares/nav` stay `NULL` pending NAV backfill) and advances `last_run = max(existing, trade_date)` plus `last_tx_id`, **without recomputing `next_run` or triggering the scheduler**. Same-day duplicates are caught by `last_run == trade_date`; backdated dates additionally check for an already-succeeded proposal with the same `plan_id + trade_date`, because `last_run` never moves backwards. Creation error codes: `404 target_not_found` (plan missing), `409 target_changed` (digest mismatch), `already_executed` (already run that day or a succeeded backdated proposal exists), `suspended`/`limit_exceeded`/`below_minimum` (strict blocks with `reason`; unlike the web manual execution, which only warns), and `fee_unknown`; at approval the same problems become `conflict` (`target_deleted`/`target_changed`/`already_executed`/`purchasable_changed`/`proposal_corrupt`). A disabled plan can still be executed manually (with a warning); non-trading days are warnings only. The `summary` carries `plan_id`/`fund_code`/`amount`/`trade_date`/`is_t1`/`fee`/`fee_source` (`fetched`/`explicit`)/`channel`/`note`/`before`/`after`/`warnings`.
- Plan-op audit events align with the web UI: `auto_invest_plan_create`/`update`/`toggle`/`delete`, with `plan_id` + `proposal_id` in `detail` (`toggle` also carries `enabled`). Plan ops never write the `transactions` table and never trigger the scheduler. Manual plan execution (`execute_plan`) records `auto_invest_execute` on success (aligned with the web/scheduler) with `plan_id`/`fund_code`/`amount`/`tx_id`/`trade_date`/`is_t1`/`proposal_id` in `detail`. Alert resolution also aligns with the web UI: `dividend_alert_update` for dividends, `tp_sl_alert_update` for TP/SL, with `id`/`status`/`tx_id`/`proposal_id` in `detail`.
- Must send `Idempotency-Key` (16–128 safe ASCII chars). Same key and parameters replay the original proposal (`200` + `replayed=true`); same key with different parameters/operation returns `409 idempotency_conflict`; expired keys return `409 idempotency_expired`. For updates, `tx_id` + `expected_digest` + the full field set count as the complete parameter set for replay comparison. For plan update/toggle/delete, `plan_id` + `expected_digest` count as the complete parameter set for replay comparison; for `resolve_alert`, `alert_type` + `alert_id` + `expected_digest` + `status` + `tx_id` do; for `execute_plan`, `plan_id` + `expected_digest` + `trade_date` + `fee` do.
- Proposals expire after 7 days and can then no longer be approved or cancelled. Each token may keep at most 20 `pending` proposals; beyond that returns `409 too_many_pending` (a `batch_import` proposal counts as one).
- A fund that is not yet registered returns `409 fund_not_registered`, so the approval path never fetches data over the network (`resolve_alert` is an exception: a historical alert may reference a fund removed from `funds`, so it is not blocked). For plan ops, a missing target plan returns `404 target_not_found` (with `plan_id`) and a digest mismatch returns `409 target_changed` (with `plan_id`); approval-time re-checks likewise resolve to `conflict` (`target_deleted`/`target_changed`) without overwriting others' changes.
- State machine: `pending → succeeded / failed / conflict / rejected / cancelled / expired`. `failed` means the creator token was revoked, expired, or lost the scope; `conflict` means the fund/parameters/plan/alert/execution target became invalid at approval time (including target deleted/changed, the alert already resolved, the plan already run that day, or the fund becoming unpurchasable). Environment-level blocks (`auth_disabled`, `write_disabled`) return `403` and leave the proposal `pending` so it can be retried after the fix.
- After a web administrator approves, the server re-checks instance authentication, the write switch, the creator token, and business rules in the same SQLite transaction, writes the ledger/plan (or updates the alert state), and records `proposal_approved` plus the business audit (ledger: `add_transaction`/`add_conversion`/`delete_conversion`, batches record one `add_transaction` per row with `batch_index`, dividend linking also records `dividend_alert_confirm`; plan: `auto_invest_plan_create`/`update`/`toggle`/`delete`, each carrying `plan_id`+`proposal_id`; manual execution: `auto_invest_execute` with `plan_id`/`fund_code`/`amount`/`tx_id`/`trade_date`/`is_t1`/`proposal_id`; alert: `dividend_alert_update`/`tp_sl_alert_update`, each carrying `id`/`status`/`tx_id`/`proposal_id`). Concurrent approvals succeed only once; a repeat returns `409 not_pending`.
- Web approval endpoints accept web login identities only: `GET /api/proposals/count`, `GET /api/proposals`, `GET /api/proposals/{id}`, `POST /api/proposals/{id}/approve`, `POST /api/proposals/{id}/reject`. An Agent token calling these returns `401`.
- Error codes: `write_disabled`, `validation_error`, `fund_not_registered`, `too_many_pending`, `not_pending`, `expired`, `not_found`, `target_changed` (target row/leg hash mismatch, `409`), `target_not_found` (target row missing, `404`), `conversion_leg_isolated` (single-leg edit/delete of a conversion leg, `409`), `conversion_not_found` (`conversion_id` missing or no longer a pair, `404`), `conversion_leg_mismatch` (linked rows are not a sell/buy pair, `409`), `batch_invalid_item` (batch: one item has bad fields, `422`, with `index`/`issues`), `batch_internal_duplicate` (batch: duplicate rows inside the batch, `409`, with `index`/`other_index`), `insufficient_shares_after_change` (at approval: update/delete/batch would leave later sells over-shares, `conflict`), `fund_missing` (fund removed before approval), `dividend_alert_not_found`/`dividend_alert_resolved`/`dividend_alert_type_mismatch`/`dividend_alert_fund_mismatch` (dividend-alert linking failed at approval), `tx_not_found`/`tx_mismatch`/`tx_already_linked` (`resolve_alert` tx linking failed, `409`), `dividend_not_backfillable` (`backfill_transaction_navs`: dividend row cannot be backfilled by NAV, `422`), `nav_present` (backfill: NAV already set, `409`), `nav_unavailable` (backfill: no usable NAV locally, `409`), `fee_unknown` (backfill: fee/confirmation NAV unknown and no explicit `fee`, `409`), `partially_updated`/`target_deleted`/`proposal_corrupt` (backfill whole-batch conflict at approval, `409`), `already_executed` (`execute_plan`: the plan already ran on the target trade date or a succeeded backdated proposal exists, `409`), `suspended`/`limit_exceeded`/`below_minimum` (`execute_plan` creation: the fund is not purchasable, `409`, with `reason`), `purchasable_changed` (`execute_plan` approval: the fund became unpurchasable, `conflict`), `proposal_corrupt` (proposal snapshot missing or inconsistent with the plan, `conflict`), `idempotency_conflict`, `idempotency_expired`. Audits `proposal_created`, `proposal_create_rejected`, `proposal_cancelled`, `proposal_expired`, `proposal_approved`, `proposal_rejected`, `proposal_failed`, and `proposal_conflict` record only the token prefix and proposal summary (update/delete summaries include `tx_id`/`before`/`after`/`changed_fields`/`reason`; conversion summaries include `conversion`/`conversion_id`; batch summaries include `count`/`actions`/`funds`/`date_range`/`amount_total`/`items`; backfill summaries include `count`/`funds`/`fee_sources`/`items`, and on success each row is audited as `nav_backfill` with `proposal_id`, aligned with the web/scheduler; alert summaries include `alert_id`/`alert_type`/`before_status`/`after_status`/`linked_tx_id`; execute_plan summaries include `plan_id`/`fund_code`/`amount`/`trade_date`/`is_t1`/`fee`/`fee_source`/`before`/`after`, and on success `auto_invest_execute` is audited with `proposal_id`).
- Alert-resolution proposals (`alerts:propose`, `resolve_alert`) do not require the fund to be present in the `funds` table: a historical alert may reference a removed code, and a missing name falls back to the code. Execution **only advances the alert state machine** (`status`/`resolved_at`/`tx_id`) and never writes the `transactions` table; confirming a dividend may carry an existing dividend/reinvest tx_id for linking without creating one. Audits align with the web UI: `dividend_alert_update` for dividends, `tp_sl_alert_update` for TP/SL, each with `id`/`status`/`tx_id`/`proposal_id` in `detail`.
- Creation/cancellation share the global write switch with watchlist writes. Proposals are not included in backup archives; restoring a backup clears stale proposals so they cannot point at replaced ledger data.

### 5.24 Trusted single direct write (write, off by default)

Use this only when the user **explicitly states a single ordinary buy/sell already completed on an external platform**; never infer a trade from a screenshot, a forecast, or a recommendation. Scope: `transactions:create`, also gated by the server write switch (see the write-switch notes above). On precheck anomalies the service downgrades to a pending proposal if the token also holds `transactions:propose`, otherwise it returns a 409 stable error code; hard failures (unregistered fund, exhausted daily quota) never downgrade.

| MCP tool | HTTP | Description |
|---|---|---|
| `record_transaction` | `POST /api/agent/tools/transactions` | Direct-write a single buy/sell; the response `execution_mode` distinguishes direct write from downgrade |

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: direct-0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f52" \
  -d '{
    "fund_code": "005827",
    "action": "buy",
    "date": "2026-10-30",
    "amount": 1000,
    "fee": 1,
    "channel": "Alipay"
  }' | jq
# {"tool":"record_transaction","data":{"execution_mode":"direct","transaction_id":12,"operation_id":3,"receipt":{...},"daily_quota":{"used":1,"count_limit":10,...},"verify_path":"/transactions"}}
```

- The request body is flat: `fund_code`, `action` (only `buy`/`sell`), `date` (`YYYY-MM-DD`, must not be later than today, else `422 future_date`), `amount`/`shares`/`nav`, `fee`, `channel`, `note`, `is_t1`. Unknown fields return `422` as a request-validation error.
- Must send `Idempotency-Key` (16–128 safe ASCII chars). Same key and parameters replay the original result (`200` + `replayed=true`); same key with different parameters returns `409 idempotency_conflict`. **Replay never upgrades**: if the original outcome was a downgraded proposal, replay returns the proposal's live status even after the trigger has cleared, and never writes a second direct transaction.
- Precheck order: parameters/date → idempotency replay → in-transaction recheck of token/scope/write switch → fund registration → daily quota → suspected duplicate → sell shares → single-amount cap.
- Error codes: `write_disabled`, `scope_revoked`, `validation_error`, `future_date`, `fund_not_registered` (409, no downgrade), `daily_quota_exceeded` (429, includes `used`/`limit`/`reset_at`, no downgrade), `duplicate_candidate` (ledger duplicate includes `tx_id`; a hit on your own pending proposal includes `proposal_id`, while another principal's proposal only reports the duplicate without its ID), `insufficient_shares` (includes `available`/`requested`), `amount_exceeds_cap` (includes `cap`/`amount`), `idempotency_conflict`/`idempotency_expired`, `too_many_pending` (forwarded from the downgrade path).
- A downgrade proposal is fully equivalent to one from `create_operation_proposal` and is approved on the "Pending proposals" page; when a same-principal same-params pending proposal already exists it is reused rather than recreated.
- Quotas (env-overridable): single `ZFUNDPILOT_AGENT_TX_MAX_AMOUNT` (default 500000), daily count `ZFUNDPILOT_AGENT_TX_DAILY_COUNT` (default 10, includes downgrades), daily amount `ZFUNDPILOT_AGENT_TX_DAILY_AMOUNT` (default 1000000, direct writes only); route rate limit 10/min.
- Transactions written by direct write carry `source="agent"` and show an "Agent" badge on the ledger page; the web/CSV/proposal-approval paths leave `source` empty. Audits record `agent_direct_add` (direct success), `agent_direct_downgraded` (downgrade), `agent_direct_rejected` (reject), plus the business `add_transaction` (detail includes `source`).

### 5.25 CSV / screenshot precheck & reconciliation (read-only, off by default)

**Read-only precheck**: before submitting transaction proposals, validate a CSV or items array for fund registration, field validity, and duplicates; or reconcile screenshot holdings against the ledger to produce suggested adjustment transactions. It does not write the ledger, call the network, or create proposals — it only returns a structured report for the caller and user to confirm before using `create_operation_proposal`. Scope: `transactions:propose`, gated by the write switch (`403 write_disabled` when off), route rate limit 10/min.

| MCP tool | HTTP | Description |
|---|---|---|
| `precheck_transactions(payload)` | `POST /api/agent/tools/precheck/transactions` | Pre-check CSV text or an items array |
| `precheck_reconciliation(payload)` | `POST /api/agent/tools/precheck/reconciliation` | Reconcile screenshot holdings; produce diff suggestions |
| `precheck_backfill(payload)` | `POST /api/agent/tools/precheck/backfill` | Inventory NAV-backfill candidates; returns per-row `row_digest` and backfill snapshot |

```bash
# Items precheck
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/precheck/transactions" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":{"format":"items","items":[
    {"fund_code":"005827","action":"buy","date":"2026-10-30","amount":1000,"channel":"Alipay"}
  ]}}' | jq
# {"tool":"precheck_transactions","data":{"ok":true,"total":1,"valid":1,"invalid":0,
#  "duplicate":0,"items":[{"index":0,"status":"valid","proposal_ready":true,...}],"parse_errors":[]}}

# Holdings reconciliation precheck
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/precheck/reconciliation" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":{"holdings":[{"fund_code":"005827","shares":5932}],"channel":"Alipay"}}' | jq

# NAV-backfill candidate inventory (omit tx_ids to list all nav-NULL non-dividend rows)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/precheck/backfill" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tx_ids":[42]}' | jq
# {"tool":"precheck_backfill","data":{"total":1,"ready":1,"unavailable":0,"items":[
#  {"tx_id":42,"fund_code":"005827","action":"buy","date":"2026-10-30","nav_date":"2026-10-30",
#   "row_digest":"...","backfillable":true,"before":{"nav":null,...},"after":{"nav":1.5,...},"fee_source":"needs_fee","fee_pending":true}]}}
```

**Transaction precheck** (`precheck_transactions`):

- `input.format`: `"csv"` (requires `csv_text` string, ≤5 MB) or `"items"` (array, ≤200); optional `channel_hint` fills missing channels.
- Each item goes through fund resolution → field validation → duplicate detection. `fund_code` is checked against the ledger `funds` table (works offline); `fund_name` **also resolves only against registered ledger funds** (exact → unique bidirectional substring match, covering A/C share-class suffixes) and never touches the network or the fund universe. Returns `status`: `valid`/`invalid`/`duplicate`, with `fund_resolution`, `duplicate`, `issues` (`code` includes `no_match`/`ambiguous_match`/`validation_error`/`invalid_params`/`missing_channel`/`missing_fee`), and a `proposal_ready` flag.
- `duplicate.kind` is `ledger` or `pending_proposal`; pending-proposal hits include `own` (whether the proposal belongs to this token), and `proposal_id` is returned only when `own=true`. Other principals' proposals still count as duplicates but never leak their ID.
- Duplicate detection reuses the direct-write/proposal `_duplicate_in_ledger` (same fund + channel + date + direction with amount or shares tolerance match) and `_duplicate_pending_proposal` (pending proposals, conservatively across principals).
- Hard blocks only: missing/invalid `date`/`action`/`fund_code`/`shares`(sell)/`amount`(dividend); missing `channel`/`fee` are warnings (item stays `valid`). `missing_fee` is based on whether the original item supplied `fee` (items path) or whether the CSV has a fee column (csv path); an explicit `fee=0` does not warn.
- Each `parse_errors` entry includes `line` (CSV line number, `null` when not locatable) and `message`.
- Request-level errors (`format` invalid, `items` not an array, over 200 items, CSV over 5 MB) return `422` with `detail.code` / `error.code` of `validation_error`/`too_many_items`/`csv_too_large`.

**Reconciliation precheck** (`precheck_reconciliation`):

- `input.holdings`: `[{fund_code or fund_name, shares, market_value?}]`, ≤100; optional `channel` filters by channel (≤50 characters).
- Fund resolution + `shares` validation (non-negative finite number) run first; unregistered or invalid-shares items go to `fund_resolution_errors` (with `reason`: `fund_unresolved`/`invalid_shares`/`not_object`) and are skipped. Excluded funds **never** produce a `maybe_sold` sell-everything suggestion.
- Valid items reuse `analysis.reconcile_holdings` to produce a diff table: `status` is `buy`/`sell`/`ok`/`new`/`maybe_sold`, with `suggested_tx` (`nav` uses `latest_nav` estimate, `note` flagged "please verify"), a full `fund_resolution` shape, `issues`, and a `proposal_ready` flag.
- `maybe_sold` (held in the ledger but absent from the input) is always `proposal_ready=false` with an `absent_from_input` issue: it is only a suspected full sale and must be confirmed by the user. `suggested_tx.date` is `null`; fill in the current date when creating a proposal.
- After confirming the report, the caller submits suggested transactions one by one via `create_operation_proposal` (`add_transaction`); web approval still required.

**NAV-backfill precheck** (`precheck_backfill`):

- `payload.tx_ids`: optional; when omitted, inventories all `nav IS NULL` non-dividend rows (ordered by `date`, `id`, capped at 50); when given, reports each row in the provided order (≤50, no duplicates, including not-backfillable reasons).
- Each row returns `tx_id`/`fund_code`/`fund_name`/`action`/`date`/`is_t1`/`before` (`nav`/`shares`/`amount`/`fee`) and `row_digest` (usable directly as the `backfill_transaction_navs` proposal's `expected_digest`); backfillable rows also carry `nav_date` (next-day NAV for T+1), the `after` backfill snapshot, and `fee_source`, with `backfillable=true`. The precheck is **fully offline**: NAV is read only from the local table, and a row with a missing fee is marked `fee_source="needs_fee"` + `fee_pending=true` (the fee is fetched at proposal creation, or the Agent may pass an explicit `fee`), so no fee rates are ever fetched here.
- Non-backfillable rows set `backfillable=false` with a `reason`: `dividend_not_backfillable` (a dividend's `nav` is the per-share payout), `nav_present` (NAV already set), `nav_unavailable` (no usable NAV locally), `fee_unknown` (e.g. a buy without amount; may retry with an explicit `fee`).
- Top-level response `total`/`ready`/`unavailable`/`items`. **Writes no ledger and creates no proposal**, consistent with the transaction/reconciliation prechecks; gated by the write switch (403 when off), rate-limited 10/min.

On success the two prechecks audit `agent_precheck_transactions` (token prefix, `format`, item counts) and `agent_precheck_reconciliation` (token prefix, `channel`, diff item count); the backfill precheck audits `agent_precheck_backfill` (token prefix, whether `tx_ids` was given, `total`/`ready`/`unavailable` counts). Item amounts and details are **never** recorded.

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

Exposed MCP tools: `get_portfolio_summary`, `get_data_status`, `list_positions`, `get_fund_detail`, `get_portfolio_health`, `get_returns`, `compare_funds`, `list_transactions`, `get_transaction`, `list_watchlist`, `list_alerts`, `list_auto_invest_plans`, `get_portfolio_curve`, `get_benchmark_comparison`, `get_risk_report`, `get_industry_exposure`, `search_funds`, `screen_funds`, `run_dca_backtest`, `get_agent_capabilities`, `add_watchlist_item`, `update_watchlist_item`, `remove_watchlist_item`, `start_data_refresh`, `get_job_status`, `create_operation_proposal`, `list_operation_proposals`, `get_operation_proposal`, `cancel_operation_proposal`, `record_transaction`.
Write tools and the task-based backtest (`run_dca_backtest`) require an `idempotency_key` argument, mapped to the HTTP `Idempotency-Key` header. The MCP client only passes parameters; server-side auth, scope, and the write switch remain authoritative.

Every MCP tool carries `ToolAnnotations` (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`) so MCP clients can distinguish read queries from writes in their UI:

- **Read-only tools** (26: `get_portfolio_summary`, `get_data_status`, `list_positions`, `get_fund_detail`, `get_portfolio_health`, `get_returns`, `compare_funds`, `list_transactions`, `get_transaction`, `list_watchlist`, `get_job_status`, `precheck_*`, `list_operation_proposals`, `get_operation_proposal`, `list_alerts`, `list_auto_invest_plans`, `get_portfolio_curve`, `get_benchmark_comparison`, `get_risk_report`, `get_industry_exposure`, `search_funds`, `screen_funds`, `run_dca_backtest`, `get_agent_capabilities`) set `readOnlyHint=True`.
- **Additive writes** (`add_watchlist_item`, `start_data_refresh`, `create_operation_proposal`, `record_transaction`) set `destructiveHint=False` + `idempotentHint=True`: they only append and are safe to retry with an idempotency key.
- **Modify/delete/cancel writes** (`update_watchlist_item`, `remove_watchlist_item`, `cancel_operation_proposal`) set `destructiveHint=True` + `idempotentHint=True`.

These annotations are **hints to the client only** (every `ToolAnnotations` field is a hint per the MCP spec); they are not access control. Actual security is enforced independently by server-side scope gating and the Agent write switch, and a client UI must not (and cannot) gate calls on the annotations alone.

- `ZFUNDPILOT_BASE_URL` defaults to `http://127.0.0.1:8000`; use the real NAS/Docker address for remote instances and HTTPS for remote access.
- `ZFUNDPILOT_TIMEOUT` is optional, default 30 seconds (range 1–120).
- The token is read only from the environment; never commit it or paste it into prompts. Revoke it in Settings if leaked.

## 7. End-to-end examples (agent loop)

> Every example below uses the `/api/agent/tools/*` HTTP endpoints; MCP tools map one-to-one to them (tool names are listed in the unified capability table above). Examples omit `Host` and the response envelope (`schema_version`/`tool`/`request_id`/`generated_at`/`currency`/`data`; see §4). `$ZFUNDPILOT_AGENT_TOKEN` is the token plaintext and must come from an environment variable only — **never** put it in code, URLs, or prompts.
>
> Write examples assume the administrator has granted the token the matching scope **and** enabled the Agent write switch; otherwise write endpoints return `403 write_disabled`.

### 7.1 Read-only analysis: check data status before drawing conclusions

```bash
# 1) Is the data fresh? Are there T+1 transactions awaiting NAV?
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/data-status" | jq '.data'
# {"as_of_date":"2026-11-13","as_of_date_semantics":"...",
#  "missing_nav_fund_count":0,"stale_nav_fund_count":1,
#  "pending_t1_transaction_count":2}

# 2) Portfolio summary and positions (amounts use the latest formal NAV)
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/portfolio-summary" | jq '.data'
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/positions?limit=20" | jq '.data.positions'
```

- `as_of_date` is the **maximum** formal-NAV date across holdings; it does not mean every fund was updated. If `stale_nav_fund_count` / `missing_nav_fund_count` is non-zero, say so explicitly in the answer.
- T+1 transactions awaiting NAV skew cost/share figures; disclose that before analyzing rather than giving a definitive conclusion.

### 7.2 Watchlist maintenance (low-risk direct write)

```bash
# 1) Read the current watchlist and each item's revision
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist?limit=50" | jq '.data.watchlist'

# 2) Add an item (Idempotency-Key is required)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f50" \
  -d '{"fund_code":"005827","note":"watch","group_name":"core"}' | jq '.data'

# 3) Update note/group (revision precondition prevents overwriting web edits)
curl -s -X PATCH "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist/005827" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d" \
  -d '{"expected_revision":3,"note":"priority watch"}' | jq '.data'
```

- Retrying with the same key and parameters returns the original result (`replayed=true`); same key with different parameters returns `409 idempotency_conflict`.
- A mismatched `expected_revision` returns `409 revision_conflict`: **re-read the revision and retry**, do not blindly retry.
- Watchlist writes only touch the watchlist relation and note/group; they never write transactions, NAV, or plans.

### 7.3 Refresh and polling (202 + job_id)

```bash
# 1) Start (defaults to current open holdings; fund_codes may be passed explicitly, max 50)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f51" \
  -d '{}' | jq '.data'
# {"job_id":7,"status":"queued","fund_count":3,...}

# 2) Poll (every 1–2 seconds until a terminal state)
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh/7" | jq '.data'
# {"job_type":"data_refresh","status":"succeeded","progress":{"done":3,"total":3},
#  "result":{"ok":true,"updated":3,"failed":0,"partial":false,"errors":[]},"can_cancel":false}
```

- Terminal states are `succeeded` / `failed` / `interrupted`; on restart, leftover `queued`/`running` jobs are marked `interrupted` rather than falsely reported as succeeded.
- On `409 refresh_busy`, poll the existing job via `detail.current_job_id` instead of creating another one with a different key (no queueing).
- Jobs are queryable for 7 days; refresh only updates NAV/metadata and **never** backfills transaction NAV or runs auto-invest plans.

### 7.4 Already-happened transaction: proposal → web approval → verify

```bash
# 1) Create a proposal (writes nothing to the ledger)
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f52" \
  -d '{"operation_type":"add_transaction","params":{
        "fund_code":"005827","action":"buy","date":"2026-11-10",
        "amount":1000,"fee":1,"channel":"Alipay"}}' | jq '.data'
# {"ok":true,"proposal_id":18,"status":"pending","expires_at":"2026-11-17T...","summary":{...}}

# 2) The administrator approves it in Settings → Pending proposals
#    (server writes the ledger and audit in one transaction).
#    Web endpoint: POST /api/proposals/18/approve (requires a web login token, not an Agent token).

# 3) The agent verifies the proposal result and the ledger row
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals/18" | jq '.data | {status, execution_result}'
# {"status":"succeeded","execution_result":{"ok":true,"message":"..."}}

curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions?fund_code=005827&limit=5" | jq '.data.transactions[0]'
```

- Proposals expire after 7 days by default; expired/rejected/cancelled proposals can no longer be approved.
- Before approval, `list_transactions` does not show the trade — **a proposal is not a write**. Tell the user "submitted, awaiting web approval", never "recorded".
- Updating/deleting an existing row requires `expected_digest` (get it from `GET transactions/{tx_id}` → `data.row_digest`); if the target changed, the API returns `409 target_changed`, so re-read and rebuild the proposal.

### 7.5 Trusted single direct write → receipt → correction

```bash
# Only when the user explicitly says it already happened externally
# and the token has transactions:create
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: direct-0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f52" \
  -d '{"fund_code":"005827","action":"buy","date":"2026-11-10",
       "amount":1000,"fee":1,"channel":"Alipay"}' | jq '.data'
# {"execution_mode":"direct","transaction_id":42,"receipt":{...},
#  "daily_quota":{"used":1,"count_limit":10,...},"verify_path":"/transactions"}

# Verify the receipt
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions/42" | jq '.data'
```

- **Boundary (important)**: direct write is a **pre-authorization** the administrator granted to this token; it is *not* the server verifying that the user confirmed in this conversation. A model's own claim, a client-side dialog, or the same agent calling an approval tool do not constitute independent human approval. Never infer a trade from a screenshot, forecast, recommendation, or "it probably happened".
- Verify the receipt (amount/date/channel/NAV status) before restating the result to the user.
- To correct a directly written row: take `row_digest` → submit an `update_transaction` proposal (needs `transactions:propose`) → web approval. Direct write itself cannot update/delete/convert or touch plans.

### 7.6 Exceptions downgraded to proposals — and hard failures

| Trigger | Response | Agent action |
|---|---|---|
| Suspected duplicate, insufficient shares, amount over cap | `200` + `data.execution_mode="proposal"` + `proposal_id` (requires `transactions:propose` too) | Tell the user it became a pending proposal and awaits web approval |
| Same, but the token only has `transactions:create` | `409` + `duplicate_candidate` / `insufficient_shares` / `amount_exceeds_cap` | Do not retry the direct write with a new key; explain and suggest the proposal path |
| Too many pending proposals | `409 too_many_pending` (passed through from the downgrade path) | Resolve existing proposals first, then retry |
| Fund not registered | `409 fund_not_registered` | No downgrade; ask the user to add the fund in the web UI first |
| Daily quota exhausted | `429 daily_quota_exceeded` (includes `used`/`limit`/`reset_at`) | No downgrade; report the quota and reset time |
| Invalid request body | `422 validation_error` / `future_date` | Fix the parameters; do not retry unchanged |

- **Replays never escalate**: if the original outcome was a downgraded proposal, a same-key replay always returns that proposal's live status and will not write a second entry even after the trigger clears.
- Downgraded proposals are fully equivalent to `create_operation_proposal`; a same-principal, same-parameter pending proposal is reused rather than duplicated.

### 7.7 Permissions, expiry, revocation, conflicts, and retries

| Scenario | Status / `error.code` | Suggested action |
|---|---|---|
| Missing scope | `403 insufficient_scope` | Do not retry; ask the administrator to grant the scope (re-issue the token) |
| Write switch off | `403 write_disabled` | Do not retry; ask the administrator to enable it in Settings |
| Instance has no admin password | `403 auth_disabled` | Do not retry; ask the administrator to configure an admin password |
| Token invalid / expired / revoked | `401 invalid_token` / `expired` / `revoked` | Stop immediately; ask the administrator to re-issue |
| Rate limited | `429 rate_limited` (`retryable=true`) | Retry after `Retry-After` seconds |
| Database busy | `503 database_busy` (`retryable=true`) | Retry after `Retry-After` seconds |
| Same key, different parameters | `409 idempotency_conflict` | Generate a new `Idempotency-Key`; do not reuse the old one |
| Idempotency key expired | `409 idempotency_expired` | Retry with a new key after confirming nothing was executed |
| Watchlist revision conflict | `409 revision_conflict` | Re-read `revision`, then retry |
| Proposal target changed | `409 target_changed` | Re-read the target `row_digest`, then rebuild the proposal |
| Refresh already running | `409 refresh_busy` | Poll `detail.current_job_id` |
| Backtest concurrency full | `429 backtest_busy` | No job was created; retry with the same key after `Retry-After` seconds |
| Token revoked mid-execution | `403 scope_revoked` (direct write) | Stop and ask the user to re-authorize |

Retry principles:

1. Only `retryable=true` (429/503) or a **deterministic replay with the same `Idempotency-Key`** is safe to retry; fix the cause first for any other 4xx.
2. Write retries must reuse the original `Idempotency-Key`; otherwise a second write may occur.
3. Before retrying, confirm the previous outcome via `GET .../proposals/{id}` or `GET .../refresh/{job_id}`.
4. Error responses include `request_id`; include it when reporting an issue (see §4).

> **Known limitation**: server error messages (`error.message` / `detail`) are currently in Chinese. English-UI clients should branch on `error.code` and render their own localized text — do **not** match or surface `message`.

---

## 8. Security and operations

- **Separate credentials**: Agent and web tokens are not interchangeable. A web token calling a tool gets `401`; an Agent token cannot call web management endpoints.
- **Default deny**: Tool paths are checked by the Agent middleware first, then authorized by scope dependencies. Management endpoints also verify the web token themselves.
- **Digest only**: The database stores only the SHA-256 digest and a 12-character prefix. Plaintext is returned once at issuance.
- **Revocation**: Revoke from Settings at any time; it takes effect immediately. Issue one token per agent for easier tracing and cleanup.
- **Audit**: Issuance, revocation, auth success/failure, and rate limiting are audited. Only token prefixes are recorded — never plaintext or full responses.
- **Network**: Remote access must go through an HTTPS reverse proxy; do not expose the port directly. Revoke and reissue if a token leaks.
- **Scope**: Read scopes cover portfolio, portfolio curve, benchmark, risk, industry exposure, funds, data status, transactions, watchlist, alerts, and auto-invest plans. Write scopes are limited to watchlist maintenance, task-based data refresh, ledger proposals, auto-invest plan proposals, alert-resolution proposals, and trusted single-transaction direct write. Ledger/plan/alert/backfill/manual-execution proposals require web administrator approval; trusted direct write requires an explicitly issued `transactions:create` and only records ordinary buys/sells directly within per-transaction/daily limits, downgrading to a proposal or rejecting on precheck anomalies, and cannot update/delete/convert or touch auto-invest. `transactions:propose` also includes two read-only precheck tools (CSV/items transaction precheck and holdings reconciliation precheck), gated by the write switch, that never write the ledger and only return a report for confirmation before submitting a proposal. Settings/import/export/fund-moving endpoints are never available to Agent tokens.

---

## 9. Changelog

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
| 2026-10-30 | D: adds task-based data refresh (`data:refresh` scope, off by default): `POST refresh` returns `202` + `job_id`, `GET refresh/{job_id}` polls progress and results; NAV/metadata only — no transaction NAV backfill, no auto-invest execution; shares the nav-update mutex with the web UI/scheduler and returns `409 refresh_busy` when occupied; idempotent creation, restart marks leftover jobs `interrupted` |
| 2026-10-31 | Added the `transactions:create` scope and the `record_transaction` tool (F0 trusted single direct write): within quotas it writes a single buy/sell directly and downgrades to a proposal or rejects on precheck anomalies. Added the `transactions.source` column and three audit labels; backups remain compatible with the legacy v2 column variant |
| 2026-10-31 | F1: `create_operation_proposal` adds `update_transaction`/`delete_transaction` operation types carrying `expected_digest` (row content SHA-256) as a row-version precondition; single-leg edits/deletes of conversion legs are rejected and share cascades block at execution time; `GET transactions/{tx_id}` adds `row_digest` |
| 2026-10-31 | F2: adds `add_conversion`/`delete_conversion` proposals (atomic two-leg conversion writes; whole-pair deletion by `conversion_id` with both legs' `expected_digest`) and optional `dividend_alert_id` atomic linking on `add_transaction`; all reuse `transactions:propose`, with new error codes and audit labels |
| 2026-11-01 | F3: adds `precheck_transactions`/`precheck_reconciliation` read-only precheck tools (reusing `transactions:propose`, gated by the write switch, 10/min): transaction precheck accepts CSV text or an items array and runs per-item fund resolution (against the ledger `funds` table), field validation, and duplicate detection; reconciliation precheck runs fund resolution + `shares` validation then reuses `reconcile_holdings` to produce diffs and suggested transactions. Neither writes the ledger, calls the network, or creates proposals |
| 2026-11-01 | F3 hardening: `fund_name` now resolves only against registered ledger funds (offline, consistent with proposal registration checks); hits on another principal's pending proposal report a duplicate without `proposal_id` (new `own` flag); reconciliation `maybe_sold` is no longer proposal-ready and carries `absent_from_input`, and excluded items no longer produce sell-everything suggestions; `channel` gains a 50-character limit; CSV `parse_errors` include line numbers; successful prechecks write audits (counts/format/channel only) |
| 2026-11-02 | F4: adds the `batch_import` operation type (reusing `transactions:propose`): up to 50 appended transactions per proposal, one approval, one atomic transaction. Creation validates every item and hard-rejects bad fields/unregistered funds/in-batch duplicates, while duplicates against the ledger or pending proposals are warnings only. Approval validates the whole batch first (funds still present, params valid, per `fund+channel` running final balance non-negative) and then writes; any failure writes nothing, marks the proposal `conflict`, and reports `index`. `dividend_alert_id` is unsupported; `clear_existing`/`fetch_meta` are ignored with warnings |
| 2026-11-02 | F5: adds the `plans:propose` scope and four auto-invest plan maintenance operation types (`create_plan`/`update_plan`/`toggle_plan`/`delete_plan`), symmetric with `transactions:propose` and issued independently. Proposal tools (`create`/`list`/`get`/`cancel`) switch to dual-domain authorization (either scope enters; `create` re-checks per `operation_type`; `capabilities` lists them on either hit). Plan ops never write the `transactions` table and never trigger the scheduler; new plans start disabled and enabling requires a separate `toggle_plan`. `update`/`toggle`/`delete` use `expected_digest` (a plan-config digest covering `fund_code/amount/cadence/day_of_week/day_of_month/channel/note/enabled`, excluding `next_run`/`last_run`/`last_tx_id`) as a version precondition; missing target → `404 target_not_found`, mismatch → `409 target_changed`. `list_auto_invest_plans` now carries a `row_digest` field per item. Audit events align with the web UI (`auto_invest_plan_create/update/toggle/delete`, carrying `plan_id`+`proposal_id`) |
| 2026-11-04 | F6.1: adds the `alerts:propose` scope and the `resolve_alert` operation type, advancing a `pending` alert to `confirmed`/`ignored` (no rollback to `pending`). Dividend alerts may link one existing dividend/reinvestment transaction via `tx_id`; no new transactions are created. `list_alerts` now carries a per-item `row_digest` (covering `status/resolved_at/tx_id` and business fields) used as the `expected_digest` version precondition. Proposal tools switch to multi-domain authorization (`transactions:propose`/`plans:propose`/`alerts:propose` — any scope enters, `create` re-checks per `operation_type`, `capabilities` lists them on any hit). Execution updates only the alert state and writes an aligned audit event (`dividend_alert_update`/`tp_sl_alert_update`, carrying `proposal_id`) in the same transaction; the `transactions` table is never written |
| 2026-11-05 | F6.2: adds the `backfill_transaction_navs` operation type (reusing `transactions:propose`), filling the missing NAV — and derived shares/amount/fee — of existing transactions whose `nav` is NULL. Supports an explicit batch of 1–50 `tx_ids` (no "backfill everything"), a per-row `expected_digest` version precondition, and all-or-nothing approval. NAV/fee snapshots are precomputed once at creation and fixed into `summary_json` (precomputation runs outside the write transaction; a missing fee may fetch rates once; approval is zero-network); dividend rows are rejected with `422 dividend_not_backfillable`, an already-set NAV with `409 nav_present`, no usable NAV with `409 nav_unavailable`, and an unknown fee / a sell with no buy record with `409 fee_unknown` (retry with an explicit `fee`). Approval re-reads every row in one transaction; any row already backfilled/changed/deleted marks the whole proposal `conflict` with no partial write, and on success each row is audited as `nav_backfill` (with `proposal_id`). Adds the read-only `precheck_backfill` tool (`POST /api/agent/tools/precheck/backfill`, gated by the write switch, 10/min) returning per-row `row_digest` and backfill snapshots |
| 2026-11-07 | F6.3: adds the `execute_plan` operation type (reusing `transactions:propose`) to manually execute an existing auto-invest plan: one buy transaction is inserted and the plan's `last_run`/`last_tx_id` advanced; `next_run` is not recomputed and the scheduler is not triggered, leaving web/scheduler behavior unchanged. Requires the plan's `row_digest`; amount/channel/note/`is_t1`/enablement and bookkeeping fields are hard-rejected. Creation checks purchasability outside the write transaction and fetches the fee (skipped when `fee` is explicit; an unknown fee returns `409 fee_unknown` instead of writing 0); `trade_date` defaults to today and allows at most a 7-day backfill. Approval is zero-network and writes `buy` from the snapshot (`shares/nav` pending backfill). Same-day duplicates are blocked by `last_run == trade_date`; backdated dates additionally check for an already-succeeded proposal with the same `plan_id + trade_date`. Disabled plans remain manually executable (warning) and non-trading days are warnings only. On success `auto_invest_execute` is audited with `proposal_id` |
| 2026-11-14 | R5: task-based backtesting — `backtest/dca` changes from synchronous `200` to **`202` + `job_id`** (breaking change; clients must poll `get_job_status`), reusing `refresh_jobs` (new `job_type="dca_backtest"`) and idempotency records, with a required `Idempotency-Key`; runs fund by fund in the background (`done` = completed count, `current` = fund being processed), returns `429 backtest_busy` when concurrency is full (`Retry-After: 60`; no job is created, so the same key can be retried); `get_job_status` is entered with either `data:refresh`/`funds:read` and re-checked by `job_type`; MCP `run_dca_backtest` gains a required `idempotency_key`. The synchronous web backtest endpoint is unchanged |
