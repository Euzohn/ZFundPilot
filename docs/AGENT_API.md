# ZFundPilot Agent API（只读 + 受控提案）

本文档面向想让 AI Agent（Claude Desktop、Cursor、自建 MCP Server、脚本等）读取 ZFundPilot 组合数据、并在明确边界内提交受控操作的用户。

Agent 接口以只读为主，写能力默认关闭且分层授权：自选维护与数据刷新是低风险直接写入；账本变更默认只能提交**待审批提案**，必须由网页管理员确认后由服务端执行；提醒处理（确认/忽略）同样只能提交提案，只推进提醒状态机；管理员可为可信 Token 额外签发 `transactions:create`，允许在限额内直接记录用户已明确陈述的外部已完成单笔买入/卖出，预检异常时仍会降级为提案或拒绝。不提供设置、导入导出或资金划转，Agent token 也不能绕过网页审批直接写账本（除上述可信直记外）。Agent token 独立于网页登录，按 scope 授权、默认拒绝、可随时撤销。

> English version: [AGENT_API_EN.md](./AGENT_API_EN.md)

---

## 1. 前置条件

- 实例已启用管理员密码认证（`AUTH_ENABLED=True`）。无密码模式下**不能签发、也不能使用** Agent token。
- 默认部署仅监听本机或受控反向代理；远程访问请使用 HTTPS。
- Agent token 只能放在 `Authorization` 请求头里，**不要**放进 URL、浏览器前端持久存储或模型提示词。

---

## 2. 签发与管理 token

在网页端 **设置 → Agent 接入 → Agent 访问令牌** 中签发。明文只显示一次，关闭页面后无法再次查看；服务端只保存 SHA-256 摘要。

也可以直接调用管理 API（需要**网页登录 token**，不是 Agent token）：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/agent/tokens` | 列出 token 元数据（不含明文与摘要） |
| `POST` | `/api/agent/tokens` | 签发 token，明文仅在响应中返回一次 |
| `DELETE` | `/api/agent/tokens/{id}` | 撤销 token（幂等） |

签发示例：

```bash
# 1. 用管理员账号换取网页登录 token
WEB_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"你的密码"}' | jq -r .token)

# 2. 签发 Agent token（scope 可只选需要的）
curl -s -X POST http://localhost:8000/api/agent/tokens \
  -H "Authorization: Bearer $WEB_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "claude-desktop",
    "scopes": ["portfolio:read", "funds:read", "health:read"],
    "expires_in_days": 90
  }' | jq
```

响应中的 `token` 字段形如 `zfag_xxx`，即 Agent token 明文。`token_info` 只包含 `id`、名称、前缀、scope、时间等元数据。

下文示例统一假设已设置环境变量：

```bash
export ZFUNDPILOT_AGENT_TOKEN=zfag_xxx   # 换成你自己的 token
export ZFUNDPILOT_BASE_URL=http://localhost:8000
```

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 1–64 字符，用于区分调用方 |
| `scopes` | string[] | 否 | 默认 `portfolio:read` / `funds:read` / `health:read` 三个；新增的数据类或写 scope 需显式勾选；未知 scope 会被拒绝 |
| `expires_in_days` | int \| null | 否 | 1–3650 天，默认 90；传 `null` 表示不过期 |

---

## 3. Scope 一览

| Scope | 允许的工具 |
|---|---|
| `portfolio:read` | `portfolio-summary`、`positions`、`returns`、`portfolio-curve`、`benchmark`、`industry-exposure` |
| `funds:read` | `funds/{code}`、`funds/compare`、`search`、`screen`、`backtest/dca`、`refresh/{job_id}`（回测任务） |
| `health:read` | `data-status`、`portfolio-health`、`risk-report` |
| `transactions:read` | `transactions`、`transactions/{tx_id}` |
| `watchlist:read` | `watchlist` |
| `alerts:read` | `alerts` |
| `plans:read` | `auto-invest-plans` |
| `watchlist:write` | `watchlist`（新增/更新/删除自选，需同时开启服务端写开关） |
| `data:refresh` | `refresh`（启动任务化数据刷新，仅净值/元数据，需开启写开关）、`refresh/{job_id}`（查询刷新任务） |
| `transactions:propose` | `proposals`（创建/查看/取消自己的待审批**账本**提案，需开启写开关；执行权只属于网页管理员） |
| `plans:propose` | `proposals`（创建/查看/取消自己的待审批**定投计划**提案，需开启写开关；执行权只属于网页管理员；新计划默认停用） |
| `alerts:propose` | `proposals`（创建/查看/取消自己的待审批**提醒处理**提案，需开启写开关；只推进提醒状态，不写账本；执行权只属于网页管理员） |
| `transactions:create` | `POST /api/agent/tools/transactions`（可信单笔直记买入/卖出，需开启写开关；预检异常时按策略降级为提案或拒绝） |

写 scope 目前有 `watchlist:write`、`data:refresh`、`transactions:propose`、`plans:propose`、`alerts:propose` 与 `transactions:create`，均默认不勾选，且受服务端写开关约束（默认关闭）。写开关的日常开启/关闭由管理员在网页「设置 → Agent 接入 → Agent 写能力」完成（`GET/PUT /api/settings/agent-write`，开启需输入当前登录密码确认，状态持久化在数据库，多 worker 部署以数据库为权威值）；环境变量 `ZFUNDPILOT_AGENT_WRITE_ENABLED` 只在两种情况下生效：显式设为 `0`/`false`/`no`/`off` 是**紧急刹车**（强制关闭且设置页无法开启），设为 `1`/`true`/`yes`/`on` 仅作为数据库无记录时的首次启动默认值。调用未授权工具返回 **403**。前两者是低风险直接写入；`transactions:propose` 只允许提交账本提案，`plans:propose` 只允许提交定投计划提案，`alerts:propose` 只允许提交提醒处理提案，三者都**不能直接写账本或计划**；`transactions:create` 允许在限额内直接写入账本，是与提案**相互独立**的预授权——仅有 `transactions:create` 而无 `transactions:propose` 时预检异常直接拒绝（不会降级）。

`capabilities` 只要求有效 token，不要求特定 scope；它只返回当前 token 已获授权的工具，写工具会标注 `risk="write"`、提案工具标注 `risk="propose"`，并以 `enabled` 反映服务端写开关状态；每个工具另带契约元数据 `side_effect`（`read`/`additive`/`mutating`）、`idempotent`（同键同参重试是否安全）、`limits`（请求参数上限）、`error_codes`（稳定业务错误码，详见下方「统一能力表」）；顶层 `write_enabled` 为当前开关值，`write_locked` 为 `true` 时表示环境变量紧急刹车已锁死，设置页也无法开启。提案类工具（`create_operation_proposal`、`list_operation_proposals`、`get_operation_proposal`、`cancel_operation_proposal`）采用**多域授权**：持有 `transactions:propose`、`plans:propose` 或 `alerts:propose` 任一即可进入，但创建时按 `operation_type` 精确复核（账本类需 `transactions:propose`，计划类需 `plans:propose`，提醒类需 `alerts:propose`），跨域操作返回 **403**；`capabilities` 中任一 scope 命中即列出这些工具。

> 前三个 scope 是签发页面的默认勾选项；`transactions:read`、`watchlist:read`、`alerts:read`、`plans:read`、`watchlist:write`、`data:refresh`、`transactions:propose`、`plans:propose`、`alerts:propose`、`transactions:create` 默认不勾选，需要读取或写入对应数据时请显式勾选，避免存量流程静默扩权。

---

## 4. 通用约定

### 请求

```http
GET /api/agent/tools/portfolio-summary HTTP/1.1
Host: localhost:8000
Authorization: Bearer zfag_xxxxxxxx
```

### 统一响应包

所有工具成功时返回同一层信封，便于 Agent 稳定解析：

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

- `schema_version`：响应结构版本，当前为 `1`；新增字段不改版本，破坏性变更才递增。
- `tool`：工具名，与端点对应。
- `request_id`：本次请求 ID，与响应头 `X-Request-ID` 一致。
- `generated_at`：服务端生成时间（含时区）。
- `currency`：金额币种，当前固定 `CNY`。
- `data`：工具具体数据。

### 请求 ID

每个响应都带 `X-Request-ID` 头；Agent 工具成功响应体与所有错误响应体也含 `request_id`。客户端可传入
`X-Request-ID`（8–64 位 ASCII 字母、数字或 `._:-`）用于跨系统关联；非法值会被服务端替换。排障时请提供该 ID。
它只用于日志关联，**不是身份凭证**：服务端不会据此鉴权或信任任何调用方声明。

### 错误响应

错误响应保留 FastAPI 兼容的 `detail` 字段，同时新增稳定的 `error` 对象：

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

- `detail`：旧字段，形状保持不变（字符串 / 对象 / 校验错误列表），旧客户端可继续读取。
- `error.code`：稳定错误码，客户端应据此分支；`error.message` 只是中文兜底文案，不要匹配文案。
- `error.details`：可选，业务附加信息（如 `field`、`index`、`reason`）；参数校验错误时为精简的 `loc/type/msg` 列表。
- `error.retryable`：是否建议重试；`429`、`503` 为 `true`。
- `error.retry_after`：可选，建议重试秒数，与 `Retry-After` 响应头一致。

通用错误码：`bad_request`、`unauthorized`、`forbidden`、`not_found`、`method_not_allowed`、`conflict`、
`validation_error`、`rate_limited`、`internal_error`、`service_unavailable`。Agent 鉴权另有
`invalid_token`、`expired`、`revoked`、`auth_disabled`、`insufficient_scope`；业务错误码见各工具章节
（如 `write_disabled`、`target_changed`、`idempotency_conflict`）。

| 状态码 | 含义 | 典型 `error.code` |
|---|---|---|
| `400` | 参数不合法（如基金代码不是 6 位数字） | `bad_request` |
| `401` | 缺少 token，或 token 无效 / 已过期 / 已撤销 | `invalid_token` / `expired` / `revoked` |
| `403` | token 有效但缺少所需 scope、写能力总开关关闭；或实例未启用密码认证 | `insufficient_scope` / `write_disabled` / `auth_disabled` |
| `404` | 工具或基金不存在（带有效 token 时） | `not_found` |
| `409` | 自选版本冲突、对象已存在/不存在、基金未收录、提案非 `pending`/已过期，或幂等键冲突 | 业务错误码（如 `target_changed`） |
| `422` | 请求体/参数校验失败，或缺少合法的 `Idempotency-Key` | `validation_error` |
| `429` | 超过限流阈值 | `rate_limited`（`retryable=true`） |
| `503` | 数据库正忙（如备份/恢复持有写锁） | `database_busy`（`retryable=true`，按 `Retry-After` 重试） |

> `/api/agent/tools/*` 由独立的 Agent 鉴权中间件保护：即使访问一个不存在的工具路径，没有有效 token 也会先返回 `401`，不会暴露路由是否存在。

### 四类响应模型

成功响应共用上面的统一信封；`data` 的字段按调用性质分为四类。客户端应按下表解析，**不要假设所有成功响应都有同一组 `data` 字段**。

| 类别 | 代表工具 | `data` 关键字段 | 幂等 / 重试 |
|---|---|---|---|
| 查询 | `get_portfolio_summary`、`list_positions`、`get_data_status`、`precheck_*` | 业务字段；涉及金额时带 `valuation_basis`，涉及时间截面时带 `as_of_date`/`as_of_date_semantics`；分页工具带 `pagination{limit,offset,total,has_more}` | 只读，可直接重试（仍受限流） |
| 写入 | `add_watchlist_item`、`update_watchlist_item`、`remove_watchlist_item`、`start_data_refresh`、`record_transaction` | 必带 `ok`/`code`/`message`/`replayed`，再按工具追加字段（见下） | 必须带 `Idempotency-Key`；同键同参返回 `replayed=true` 且不重复写入 |
| 提案 | `create_operation_proposal`、`list_operation_proposals`、`get_operation_proposal`、`cancel_operation_proposal` | `proposal_id`/`operation_type`/`status`/`expires_at`/`summary`/`params`/`can_approve`/`can_cancel`/`execution_result` | 创建按幂等键去重；取消天然幂等；批准/拒绝只能走网页登录端点 |
| 作业 | `start_data_refresh`、`run_dca_backtest`、`get_job_status` | `job_id`/`job_type`/`status`/`progress{done,total,current,phase}`/`result`/`error`/`created_at`/`updated_at`/`expires_at`/`can_cancel` | 启动按幂等键去重；查询只读，可轮询 |

**查询类**

- 只有业务字段，没有 `ok`/`code`/`replayed`；成功与否由 HTTP 状态码决定。
- 金额口径统一为最新正式净值，`data.valuation_basis="latest_formal_nav"`；`as_of_date` 是各持仓正式净值日期的最大值，不代表所有基金都已更新。
- 分页工具（`list_transactions`/`list_watchlist`/`list_operation_proposals`/`list_alerts`/`search_funds`/`screen_funds`）返回 `pagination{limit,offset,total,has_more}`；`list_positions` 返回 `count`/`total`/`limit`，不带 `pagination` 块。

**写入类**

- `ok` 在 2xx 中恒为 `true`；失败一律是非 2xx 错误响应，不会出现 `ok=false` 的 2xx。
- `code` 是**成功码**（如 `created`/`updated`/`unchanged`/`removed`/`queued`/`recorded`/`downgraded`/`replayed`），与 `error.code` 分属两套命名空间，不要混用。
- `replayed` 表示本次是否命中幂等重放；重放不产生第二次写入。
- 自选写追加 `fund_code`/`changed`/`revision`/`before`/`after`。
- 任务启动（刷新/回测）追加 `job_id`/`status`/`fund_count`/`expires_at`，HTTP `202`。
- 直记追加 `execution_mode`、`transaction_id`（直记）或 `proposal_id`（降级）、`operation_id`/`receipt`/`daily_quota`/`verify_path`。
- **`execution_mode` 定稿为 `direct` / `proposal` 两个取值，没有 `rejected`。** 被拒绝的直记一律返回非 2xx 稳定错误码（如 `409 duplicate_candidate`、`429 daily_quota_exceeded`），客户端不得把错误响应当作「成功但被拒绝」。

**提案类**

- `status ∈ {pending,succeeded,failed,conflict,rejected,cancelled,expired}`；`pending` 之外均为终态。
- 批准成功为 `succeeded`（**不是** `approved`）；审批执行失败为 `failed`，执行期目标变更/并发冲突为 `conflict`，管理员拒绝为 `rejected`，超时为 `expired`，创建者取消为 `cancelled`。
- `execution_result` 仅终态有值，内容由 `operation_type` 决定；`can_approve`/`can_cancel` 仅在 `pending` 为 `true`。
- 批准/拒绝只能走网页登录端点 `POST /api/proposals/{id}/approve|reject`，Agent token 无法调用。

**作业类**

- `job_type` 当前为 `data_refresh`（数据刷新）或 `dca_backtest`（只读定投回测）；`status ∈ {queued,running,succeeded,failed,interrupted}`，后三者为终态。
- `result` 按 `job_type` 区分结构：`data_refresh` 为 `{ok,updated,failed,partial,errors[]}`；`dca_backtest` 为 §5.20 的结果结构（`ok`/`message`/`simulation_note`/`requested`/`fund_count`/`result_count`/`failed_count`/`results[]`）。`results[].status` 与任务 `status` 相互独立：单只基金失败不影响任务本身成功。新增任务类型必须复用同一响应包与同一查询端点，并在此处补充 `result` 结构。
- `get_job_status` 以 `data:refresh` 或 `funds:read` 任一 scope 进入，再按 `job_type` 精确复核（刷新→`data:refresh`，回测→`funds:read`，未知类型 `403`）；归属校验优先，他人任务一律 `404`。
- 服务重启会把遗留的 `queued`/`running` 标为 `interrupted`，不会误报成功。
- `can_cancel` 目前恒为 `false`（预留字段）。

### 契约版本与兼容策略

- `schema_version` 描述**响应信封**结构，当前为 `1`。新增字段、新增错误码、新增工具**不**递增；删除/重命名字段、改变字段类型或语义才递增，并同步 `CHANGELOG.md`。
- `error.code`、成功码 `code`、`execution_mode`、提案 `status`、作业 `status`/`job_type` 是稳定契约；`error.message`/`detail` 只是中文兜底文案，可能变化，**不要匹配文案**。
- 新增枚举值（新 `operation_type`、新 `job_type`、新提案状态）视为向后兼容；客户端必须对未知值安全降级（展示原始 code，禁止据此发起写操作）。
- 时间以服务端为准：`generated_at` 为响应生成时间，数据时间一律看 `data.as_of_date`/`updated_at`，不要依赖客户端时钟。
- 旧字段保留至少一个 minor 版本；删除或改名会先在 `CHANGELOG.md` 的 `Deprecated` 段标注。
- 文档与实现不一致时，以端点 OpenAPI 与 `get_agent_capabilities` 返回为准，并视为文档缺陷修复。

### 限流

每个 token、每个端点默认 **120 次/分钟**。路径参数按同一端点计（例如不同基金代码共用 `funds/{code}` 的额度），避免通过枚举代码绕过限流。较重端点使用更低限额：`search` 为 60 次/分钟，`screen`、`backtest/dca`、`benchmark`、`industry-exposure` 为 20 次/分钟；自选写端点（`POST`/`PATCH`/`DELETE watchlist`）为 30 次/分钟且与同路径的 `GET` 分开计数，`POST refresh` 为 10 次/分钟（联网抓取，避免高频触发），`POST /api/agent/tools/transactions`（可信单笔直记）为 10 次/分钟且与同路径的 `GET` 流水列表分开计数。筛选无论是否补指标都共用同一个桶，切换参数不能绕过。超限返回 `429`，并按 `Retry-After` 秒数重试。限流与指标增强的并发上限都是**进程内**状态，多 worker 部署时各进程独立计数。

### OpenAPI / Swagger

FastAPI 自动生成以下页面：

| 路径 | 内容 |
|---|---|
| `/openapi.json` | 机器可读的接口描述 |
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |

这些页面默认公开，**只描述接口结构**，不包含 token、持仓或其他业务数据；所有业务 `/api/*` 仍然需要认证。Agent 工具在 OpenAPI 中归入 `agent` 分组，管理端点归入 `agent-admin` 分组，并列出 401/403/429；带参数校验的工具另含 400，单基金详情与单笔交易另含 404。OpenAPI 声明了 `AgentBearer` 与 `WebLoginBearer` 两种 Bearer；Swagger 的 Authorize 一次只能发送一个 `Authorization` 头，调试时按需授权其一。如果部署环境不希望暴露接口清单，可在反向代理层屏蔽上述路径。

### 估值口径

持仓与基金详情中的金额基于**最新正式净值**，并在 `data.valuation_basis` 标注 `"latest_formal_nav"`。

- `as_of_date` 是各持仓正式净值日期的**最大值**，不代表所有基金都已更新。
- 接口**不返回**盘中实时估值，避免与正式净值混淆。数据完整性请调用 `data-status`。

---

### 统一能力表

下表汇总全部 Agent 工具的契约元数据（与 `get_agent_capabilities` 返回的 `side_effect`/`idempotent`/`limits`/`error_codes` 字段一致）。按副作用分组：**只读**（不改动任何状态，含只读模拟与 `precheck_*` 预检）、**追加**（只新增不覆盖既有数据，幂等键可安全重试）、**修改/删除**（可能覆盖或移除既有数据）。`risk` 与 `side_effect` 是两个正交维度：`risk` 描述授权层级（只读 / 直写 / 提案），`side_effect` 描述数据影响方式；例如 `precheck_*` 的 `risk=提案`（要求 `transactions:propose`）但 `side_effect=只读`（预检本身不写账本、不建提案）。`idempotent` 列表示同键同参重试是否安全（写类靠 `Idempotency-Key`，取消提案天然幂等）。

| 工具 | 方法 | HTTP 路径 | scope | 风险 | 副作用 | 需审批 | 限额 | 稳定错误码 |
|---|---|---|---|---|---|---|---|---|
| `compare_funds` | `GET` | `/api/agent/tools/funds/compare` | funds:read | 只读 | 只读 | 否 | codes 1-20 | validation_error, insufficient_scope, rate_limited |
| `get_agent_capabilities` | `GET` | `/api/agent/tools/capabilities` | — | 只读 | 只读 | 否 | — | — |
| `get_benchmark_comparison` | `GET` | `/api/agent/tools/benchmark` | portfolio:read | 只读 | 只读 | 否 | codes 1-20 | validation_error, insufficient_scope, rate_limited |
| `get_data_status` | `GET` | `/api/agent/tools/data-status` | health:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited |
| `get_fund_detail` | `GET` | `/api/agent/tools/funds/{code}` | funds:read | 只读 | 只读 | 否 | nav_limit 1-250 (default 30) | validation_error, insufficient_scope, rate_limited, not_found |
| `get_industry_exposure` | `GET` | `/api/agent/tools/industry-exposure` | portfolio:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited |
| `get_job_status` | `GET` | `/api/agent/tools/refresh/{job_id}` | data:refresh / funds:read（按 `job_type` 复核） | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited, not_found |
| `get_operation_proposal` | `GET` | `/api/agent/tools/proposals/{proposal_id}` | transactions/plans/alerts:propose 任一 | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited, not_found |
| `get_portfolio_curve` | `GET` | `/api/agent/tools/portfolio-curve` | portfolio:read | 只读 | 只读 | 否 | max_points 10-2000 (default 365) | validation_error, insufficient_scope, rate_limited |
| `get_portfolio_health` | `GET` | `/api/agent/tools/portfolio-health` | health:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited |
| `get_portfolio_summary` | `GET` | `/api/agent/tools/portfolio-summary` | portfolio:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited |
| `get_returns` | `GET` | `/api/agent/tools/returns` | portfolio:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited |
| `get_risk_report` | `GET` | `/api/agent/tools/risk-report` | health:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited |
| `get_transaction` | `GET` | `/api/agent/tools/transactions/{tx_id}` | transactions:read | 只读 | 只读 | 否 | — | validation_error, insufficient_scope, rate_limited, not_found |
| `list_alerts` | `GET` | `/api/agent/tools/alerts` | alerts:read | 只读 | 只读 | 否 | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `list_auto_invest_plans` | `GET` | `/api/agent/tools/auto-invest-plans` | plans:read | 只读 | 只读 | 否 | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `list_operation_proposals` | `GET` | `/api/agent/tools/proposals` | transactions/plans/alerts:propose 任一 | 只读 | 只读 | 否 | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `list_positions` | `GET` | `/api/agent/tools/positions` | portfolio:read | 只读 | 只读 | 否 | limit 1-500 (default 200) | validation_error, insufficient_scope, rate_limited |
| `list_transactions` | `GET` | `/api/agent/tools/transactions` | transactions:read | 只读 | 只读 | 否 | limit 1-200 (default 50); offset >=0 | validation_error, insufficient_scope, rate_limited |
| `list_watchlist` | `GET` | `/api/agent/tools/watchlist` | watchlist:read | 只读 | 只读 | 否 | limit 1-200 (default 50); offset >=0 | validation_error, insufficient_scope, rate_limited |
| `precheck_backfill` | `POST` | `/api/agent/tools/precheck/backfill` | transactions:propose | 提案 | 只读 | 否 | tx_ids 1-50 | validation_error, insufficient_scope, rate_limited |
| `precheck_reconciliation` | `POST` | `/api/agent/tools/precheck/reconciliation` | transactions:propose | 提案 | 只读 | 否 | holdings 1-100 | validation_error, insufficient_scope, rate_limited |
| `precheck_transactions` | `POST` | `/api/agent/tools/precheck/transactions` | transactions:propose | 提案 | 只读 | 否 | items 1-200; csv_text <=5MB | validation_error, insufficient_scope, rate_limited |
| `run_dca_backtest` | `POST` | `/api/agent/tools/backtest/dca` | funds:read | 只读 | 只读 | 否 | fund_codes 1-5; max_points 10-2000 (default 365); amount_per_period >0 and <=1000000; Idempotency-Key 16-128 | validation_error, insufficient_scope, rate_limited, not_found, idempotency_conflict, idempotency_expired, backtest_busy |
| `screen_funds` | `GET` | `/api/agent/tools/screen` | funds:read | 只读 | 只读 | 否 | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `search_funds` | `GET` | `/api/agent/tools/search` | funds:read | 只读 | 只读 | 否 | limit 1-200 (default 50) | validation_error, insufficient_scope, rate_limited |
| `add_watchlist_item` | `POST` | `/api/agent/tools/watchlist` | watchlist:write | 写 | 追加 | 否 | note <=500 chars; group_name <=50 chars | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, already_exists |
| `create_operation_proposal` | `POST` | `/api/agent/tools/proposals` | transactions/plans/alerts:propose 任一 | 提案 | 追加 | 需网页审批 | batch_import.items 1-50; backfill_transaction_navs.items 1-50 | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, target_changed, conflict, fee_unknown, pending_nav, no_buy_record |
| `record_transaction` | `POST` | `/api/agent/tools/transactions` | transactions:create | 写 | 追加 | 否 | — | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, fee_unknown, pending_nav, no_buy_record |
| `start_data_refresh` | `POST` | `/api/agent/tools/refresh` | data:refresh | 写 | 追加 | 否 | fund_codes 1-50 | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, already_running, busy |
| `cancel_operation_proposal` | `DELETE` | `/api/agent/tools/proposals/{proposal_id}` | transactions/plans/alerts:propose 任一 | 写 | 修改/删除 | 否 | — | not_found, conflict, insufficient_scope, rate_limited |
| `remove_watchlist_item` | `DELETE` | `/api/agent/tools/watchlist/{code}` | watchlist:write | 写 | 修改/删除 | 否 | — | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, target_changed |
| `update_watchlist_item` | `PATCH` | `/api/agent/tools/watchlist/{code}` | watchlist:write | 写 | 修改/删除 | 否 | note <=500 chars; group_name <=50 chars | validation_error, insufficient_scope, write_disabled, rate_limited, idempotency_conflict, idempotency_expired, not_found, target_changed |

> 稳定错误码列为该工具可能返回的**业务**错误码，不含通用鉴权/限流之外的未预期异常（统一 500 `internal_error`）；`validation_error`/`insufficient_scope`/`rate_limited` 为几乎所有工具共有，此处一并列出以便对照。`limits` 为请求参数的数值/条目上限，供 Agent 侧自适应分页与批量。

---

## 5. 工具列表

5.1–5.20 为只读或只读模拟工具（5.20 的回测使用 `POST` 创建任务后轮询）；5.21–5.23 为受控写能力，均默认关闭。任何工具都不接受设置、导入导出或资金划转操作，账本写入只能经由网页管理员批准提案。

### 5.1 `GET /api/agent/tools/portfolio-summary`

组合层面汇总，scope：`portfolio:read`。

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/portfolio-summary | jq
```

`data` 主要字段：

| 字段 | 说明 |
|---|---|
| `total_cost` | 当前持仓成本 |
| `total_value` | 当前市值（最新正式净值） |
| `unrealized_pnl` / `realized_pnl` / `total_pnl` | 浮动 / 已实现 / 总盈亏 |
| `total_return` | 浮动收益率 |
| `annualized_return` | XIRR 年化收益率，可能为 `null` |
| `total_buy` / `total_sell` / `total_dividend` | 累计买入 / 卖出 / 分红 |
| `holding_count` | 当前持仓基金数 |
| `max_single_weight` / `max_single_name` | 最大单只权重及名称 |
| `as_of_date` | 最新正式净值日期（见上方口径说明） |
| `daily_pnl` / `daily_return` | 今日收益额 / 收益率 |
| `week_*` / `month_*` / `year_*` | 本周 / 本月 / 今年收益额与收益率 |
| `data_status` | 数据状态摘要，见 5.2 |

### 5.2 `GET /api/agent/tools/data-status`

正式净值与 T+1 待确认交易摘要，scope：`health:read`。

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/data-status | jq
```

| 字段 | 说明 |
|---|---|
| `as_of_date` | 最新正式净值日期 |
| `as_of_date_semantics` | 对 `as_of_date` 含义的中文说明，避免被误读为全组合已更新 |
| `missing_nav_fund_count` | 有已确认份额但无任何正式净值的基金数（按代码去重） |
| `stale_nav_fund_count` | 超过容忍期未更新的基金数（与 missing 互斥；周末/节假日不误报） |
| `pending_t1_transaction_count` | T+1 待确认交易笔数（仅统计 `is_t1` 且净值为空的非分红交易） |

### 5.3 `GET /api/agent/tools/positions`

持仓列表，scope：`portfolio:read`。按（基金 × 渠道）区分，按市值降序。

查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `include_closed` | bool | `false` | 是否包含已清仓记录 |
| `limit` | int | `200` | 1–500，超出返回 422 |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/positions?limit=50" | jq
```

`data` 字段：

| 字段 | 说明 |
|---|---|
| `count` / `total` / `limit` | 本次返回数 / 总数 / 实际限制 |
| `include_closed` | 是否包含已清仓 |
| `valuation_basis` | 固定为 `latest_formal_nav` |
| `positions` | 持仓数组，见下表 |

单个持仓字段（`Position.to_dict()`）：

| 字段 | 说明 |
|---|---|
| `fund_code` / `fund_name` / `fund_type` / `sector` / `channel` | 基金与渠道信息 |
| `risk_level` / `tracking_index` | 风险等级与跟踪指数 |
| `held_shares` | 当前持有份额 |
| `total_cost` | 当前持仓成本 |
| `pending_buy_cost` | 待确认买入金额（不计入市值/盈亏） |
| `avg_cost_nav` | 持仓均价 |
| `latest_nav` / `latest_date` | 最新正式净值与日期 |
| `market_value` / `unrealized_pnl` / `realized_pnl` / `total_pnl` | 市值与盈亏 |
| `return_rate` / `annualized_return` | 浮动收益率 / XIRR 年化 |
| `weight` | 占组合市值比例 |
| `buy_count` / `sell_count` / `dividend_count` / `dividend_total` | 交易与分红统计 |
| `is_open` | 是否仍有持仓（含待确认） |

### 5.4 `GET /api/agent/tools/funds/{code}`

单基金详情，scope：`funds:read`。

路径参数：`code` 必须为 6 位数字，否则 `400`；基金不存在返回 `404`。

查询参数：`nav_limit`，默认 `30`，范围 1–250。

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/funds/005827?nav_limit=10" | jq
```

`data` 字段：

| 字段 | 说明 |
|---|---|
| `fund` | 基金基础信息（代码、名称、类型、板块、跟踪指数、分红方式、申购状态、限额、风险等级等） |
| `valuation_basis` | 固定为 `latest_formal_nav` |
| `latest_formal_nav` | `{date, nav, accumulated_nav, source}`；无正式净值时为 `null` |
| `annualized_return` | 该基金 XIRR 年化，可能为 `null` |
| `positions` | 该基金当前各渠道持仓（结构同 5.3） |
| `recent_nav` | 最近 `nav_limit` 条正式净值：`{date, nav, accumulated_nav}` |

> 此接口不返回盘中实时估值。若需要“今天大概涨跌”，请明确使用网页端的估值功能，并注意其非正式净值。

---

### 5.5 `GET /api/agent/tools/portfolio-health`

组合四维体检，scope：`health:read`。

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/portfolio-health | jq
```

`data` 字段：

| 字段 | 说明 |
|---|---|
| `overall_score` | 综合评分 0–100 |
| `overall_tier` | 等第：`excellent` / `good` / `fair` / `attention` / `danger` |
| `dimensions` | 四维评分：`allocation`（配置）/`risk`（风险）/`liquidity`（流动性）/`return`（收益），各含 `name`、`score`、`status`、`metrics` |
| `stable_weight` / `volatile_weight` | 稳定型（债券等）/ 波动型资产占比 |
| `risk_report` | 最大回撤、波动率、最大单只权重、HHI、股/债/QDII 占比与风险提示（`flags`） |
| `advice` | 结构建议，非交易指令 |
| `summary` | 组合汇总，结构同 5.1 |
| `valuation_basis` | 固定为 `latest_formal_nav` |
| `data_quality` | `as_of_date`、`as_of_date_semantics`、缺失/过期净值数、T+1 待确认数，以及 `caveats` 降级说明数组 |

> 先读 `data_quality.caveats` 再解读分数：缺净值或净值过期会拉低相关维度，T+1 待确认交易尚未计入市值。空组合的 `danger` 只表示暂无可诊断持仓，不代表真实风险。
>
> 体检会尝试获取 CPI 基线用于收益维度；网络不可用时自动降级为仅按年化收益率评分，接口仍会正常返回。

### 5.6 `GET /api/agent/tools/returns`

收益视图，scope：`portfolio:read`。默认组合级；传 `fund_code` 返回单基金级。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `fund_code` | str | 无 | 可选，6 位数字；格式非法返回 `400`，基金不存在返回 `404` |

```bash
# 组合级
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/returns | jq

# 单基金级
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/returns?fund_code=005827" | jq
```

`data` 公共字段：`scope`（`portfolio` / `fund`）、`valuation_basis`（固定 `latest_formal_nav`）、`return_basis`（固定 `open_positions_floating`）、`return_basis_note`、`realized_pnl_scope`（`all_history_including_closed`）、`total_pnl_scope`、`as_of_date`、`as_of_date_semantics`。

> **口径**：`total_return`/`return_rate` 只是**当前开仓**的浮动收益率（市值 ÷ 当前持仓成本 − 1），不是历史累计收益；已清仓基金的历史盈亏只体现在 `realized_pnl` 与 XIRR 中。`total_return` 不是“总收益 ÷ 总投入”，不能与累计买卖金额相除。完全清仓时当前成本为 0，`total_return`/`return_rate` 返回 `null`。

组合级另有：

| 字段 | 说明 |
|---|---|
| `total_return` / `annualized_return` | 当前开仓浮动收益率 / XIRR 年化（可能为 `null`） |
| `total_pnl` / `unrealized_pnl` / `realized_pnl` | 总 / 浮动 / 已实现盈亏；`realized_pnl` 含已清仓历史 |
| `total_cost` / `total_value` | 当前开仓成本 / 市值 |
| `daily` / `week` / `month` / `year` | 各周期 `{pnl, return}` |
| `holding_count` | 当前持仓基金数（按基金去重） |
| `open_position_count` / `closed_position_count` | 开仓 / 已清仓的（基金, 渠道）行数 |
| `data_quality` | 缺失/过期净值、T+1 待确认计数与 `caveats` |

单基金级另有：

| 字段 | 说明 |
|---|---|
| `fund_code` / `fund_name` | 基金标识 |
| `market_value` / `total_cost` | 当前开仓市值 / 持仓成本（已清仓渠道为 0） |
| `unrealized_pnl` / `realized_pnl` / `total_pnl` | 浮动 / 已实现 / 总盈亏；`realized_pnl` 含已清仓渠道 |
| `closed_realized_pnl` | 已清仓渠道贡献的已实现盈亏 |
| `return_rate` / `annualized_return` | 当前开仓浮动收益率 / 全历史 XIRR（可能为 `null`） |
| `transaction_count` | 交易笔数（含已清仓历史） |
| `buy_amount` / `sell_amount` / `dividend_amount` | 累计买入 / 卖出 / 分红金额；`dividend_amount` 含红利再投资金额 |
| `open_position_count` / `closed_position_count` | 开仓 / 已清仓渠道数 |
| `data_quality` | `missing_nav_channel_count`、`pending_t1_transaction_count`、`caveats` |
| `channels` | 全部渠道（含已清仓）：`channel`、`is_open`、`market_value`、`total_cost`、`unrealized_pnl`、`realized_pnl`、`return_rate`、`annualized_return`、`latest_date`、`nav_missing` |

> `annualized_return` 使用 XIRR（按实际现金流日期），分批发入时比简单收益率更可靠；数据不足时返回 `null`。现金分红计为流入，红利再投资按现金中性跳过（不重复计入收益）。有份额但缺少正式净值时，`return_rate` 与 `annualized_return` 返回 `null` 并给出 `caveats`，不会把缺失市值显示成 `-100%` 亏损。T+1 待确认买入的金额未计入市值与成本。

### 5.7 `GET /api/agent/tools/funds/compare`

多基金对比，scope：`funds:read`。一次最多 20 只。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `codes` | str[] | 必填 | 6 位基金代码，可重复传参：`?codes=005827&codes=000001`；为空或格式非法返回 `400`，不传返回 `422` |
| `include_nav_series` | bool | `false` | 是否返回归一化净值序列（体积较大） |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/funds/compare?codes=005827&codes=000001" | jq
```

`data` 字段：

| 字段 | 说明 |
|---|---|
| `ok` / `message` / `msg_code` | 整体是否成功及失败原因 |
| `count` | 返回基金数 |
| `funds` | 每只基金：`code`、`name`、`type`、`sector`、`scale`、`manager`、费率、`returns`、`risk`、`latest_nav`、`latest_date`、`ok`、`message` |
| `correlations` | 至少 2 只成功时的相关性矩阵；不足 2 只时为 `null` |
| `nav_series` | 仅 `include_nav_series=true` 时返回，按基金代码给出归一化净值序列 |
| `valuation_basis` | 固定为 `latest_formal_nav` |

> 对比会实时抓取外部数据，可能较慢；单只基金失败不影响其他基金，请先检查每项的 `ok`/`message`。该接口不返回盘中估值。

### 5.8 `GET /api/agent/tools/transactions`

交易流水列表，scope：`transactions:read`。按日期与 id 降序，仅读取已入库流水。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `fund_code` | str | 无 | 6 位基金代码，格式非法返回 `400` |
| `channel` | str | 无 | 按渠道精确匹配（区分空字符串） |
| `action` | str | 无 | `buy` / `sell` / `dividend` / `reinvest` |
| `date_from` | str | 无 | 起始日期（含），`YYYY-MM-DD` |
| `date_to` | str | 无 | 结束日期（含），`YYYY-MM-DD` |
| `conversion_id` | str | 无 | 基金转换关联 ID，用于取同一转换的两条腿 |
| `nav_status` | str | 无 | `confirmed` / `pending_t1` / `missing` |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | 从 0 开始 |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions?fund_code=005827&limit=20" | jq
```

`data` 字段：

| 字段 | 说明 |
|---|---|
| `count` / `total` | 本页条数 / 过滤后总条数 |
| `pagination` | `{limit, offset, total, has_more}`，`has_more` 为是否还有下一页 |
| `valuation_basis` | 固定为 `latest_formal_nav` |
| `transactions` | 流水数组，见下表 |

单笔流水字段：

| 字段 | 说明 |
|---|---|
| `id` / `fund_code` / `date` / `action` | 标识与基础字段 |
| `fund_name` | 基金名称，未入库时为 `null` |
| `amount` / `shares` / `nav` / `fee` | 成交金额 / 份额 / 净值 / 手续费 |
| `amount_semantics` | 金额口径：买入 `gross_paid`（含手续费）、卖出 `net_received`（扣手续费）、分红/再投资 `gross` |
| `channel` / `note` / `is_t1` | 渠道、备注、是否 T+1 |
| `nav_status` | `confirmed`（净值已回填）/ `pending_t1`（T+1 待确认）/ `missing`（缺净值且非 T+1） |
| `conversion_role` | 有 `conversion_id` 时：卖出腿 `out`、买入腿 `in`，否则为空串 |

> `pending_t1` 与 `missing` 的区分很重要：前者是正常等待确认，后者通常意味着数据缺失，建议结合 `data-status` 判断。

### 5.9 `GET /api/agent/tools/transactions/{tx_id}`

单笔交易详情，scope：`transactions:read`。字段与 5.8 的单项一致，另在 `data` 顶层附带 `valuation_basis` 与 `row_digest`（目标行内容 SHA-256，覆盖 `fund_code/action/date/amount/shares/nav/fee/channel/note/is_t1`，数值 `round(_,4)`；用于构造 `update_transaction`/`delete_transaction` 提案的 `expected_digest`；转换腿的 `row_digest` 也用于 `delete_conversion` 的 `expected_from_digest`/`expected_to_digest`）；id 不存在返回 `404`。

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/transactions/12 | jq
```

### 5.10 `GET /api/agent/tools/watchlist`

自选关注列表，scope：`watchlist:read`。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `group_name` | str | 无 | 按分组精确过滤；空串表示未分组 |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | 从 0 开始 |

`data` 字段：`count`、`total`、`pagination`（结构同 5.8）、`watchlist`。

每条自选字段：`fund_code`、`note`、`group_name`、`added_at`、`fund_name`、`fund_type`、`sector`、`tracking_index`（后四项来自基金库，未入库时为 `null`）。

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist?group_name=核心" | jq
```

### 5.11 `GET /api/agent/tools/alerts`

分红与止盈止损提醒，scope：`alerts:read`。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `type` | str | 无 | `dividend` / `take_profit` / `stop_loss` / `tp_sl`（后两者合称） |
| `status` | str | 无 | `pending` / `confirmed` / `ignored` |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | 从 0 开始 |

`data` 字段：`count`、`total`、`pagination`、`alerts`。

每条提醒只返回白名单字段：`id`、`alert_type`、`fund_code`、`fund_name`、`status`、`triggered_return`、`threshold`、`record_date`、`ex_date`、`pay_date`、`per_share`、`estimated_amount`、`held_shares`、`dividend_method`、`created_at`、`resolved_at`、`tx_id`，以及 `row_digest`（提醒业务字段 SHA-256，覆盖 `status/resolved_at/tx_id` 与分红/止盈止损业务字段，作为 `resolve_alert` 提案的 `expected_digest` 版本前置；`alert_type` 为 NULL 的旧行按 `dividend` 归一）。

> 这里的 `status` 是**业务处理状态**，不是「已读/未读」。ZFundPilot 目前没有提醒已读标记，接口不会虚构该语义。

### 5.12 `GET /api/agent/tools/auto-invest-plans`

定投计划列表，scope：`plans:read`。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | 无 | 按启用状态过滤 |
| `limit` | int | `50` | 1–200 |
| `offset` | int | `0` | 从 0 开始 |

`data` 字段：`count`、`total`、`pagination`、`plans`。

每个计划返回已持久化字段（基金代码、金额、周期、渠道、备注、`next_run`、`last_run`、`last_tx_id` 等），并补充：

| 字段 | 说明 |
|---|---|
| `fund_name` | 基金名称，未入库时 `null` |
| `enabled` | 统一为布尔值 |
| `row_digest` | 计划配置 SHA-256（覆盖 `fund_code/amount/cadence/day_of_week/day_of_month/channel/note/enabled`，`amount` 取 `round(_,4)`，`enabled` 归一为 0/1；**不含** `next_run/last_run/last_tx_id` 等调度器簿记字段，避免活跃计划每次执行后摘要失配）。作为 `update_plan`/`toggle_plan`/`delete_plan` 提案的 `expected_digest` 版本前置 |
| `status` | 派生状态：`paused`（已暂停）/ `due`（`next_run` 已到期）/ `active`（启用且未到期） |

> 跳过原因（例如余额不足、非交易日）**未按计划持久化**，因此不会返回 `skip_reason` 之类的推测字段。

### 5.13 `GET /api/agent/tools/capabilities`

能力发现，只要求有效 Agent token，不需要特定 scope。

`data` 字段：

| 字段 | 说明 |
|---|---|
| `server_version` | 服务端版本 |
| `schema_version` | 能力描述结构版本，当前为 `1` |
| `granted_scopes` | 当前 token 已获授权的 scope（排序） |
| `currency` | 固定 `CNY` |
| `tools` | 当前 token 可调用的工具数组：`name`、`method`、`path`、`scope`、`risk`（固定 `read`）、`requires_confirmation`（固定 `false`） |

```bash
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/capabilities | jq
```

> 建议 Agent 启动时先调用 `capabilities`，只使用返回列表中存在的工具，避免反复触发 403。

### 5.14 `GET /api/agent/tools/portfolio-curve`

组合每日市值、投入成本与累计收益率曲线，scope：`portfolio:read`。

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `start_date` / `end_date` | string | 无 | 可选，`YYYY-MM-DD`，含当日 |
| `max_points` | int | 365 | 10–2000；超出时等距抽样并保留首尾 |

`data` 字段：

| 字段 | 说明 |
|---|---|
| `as_of_date` | 各持仓正式净值日期的最大值 |
| `as_of_date_semantics` | 截至日期语义说明 |
| `valuation_basis` | 固定 `latest_formal_nav` |
| `max_points` | 本次请求的点数上限 |
| `points_count` | 实际返回点数 |
| `points[]` | `{date, total_value, invested_cost, total_return}` |

> 曲线用于可视化，不用于精确对账；待确认买入以占位市值计入，避免虚假亏损。日期格式非法或起止顺序颠倒返回 `400`。

### 5.15 `GET /api/agent/tools/benchmark`

基准指数/宏观水位与组合曲线对齐的累计收益率，scope：`portfolio:read`。

参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `codes` | string[] | 是 | 重复传参，最多 20 个，如 `?codes=000300&codes=CPI`；仅支持白名单 `000300`/`000001`/`399006`/`CPI`/`M2` |
| `start_date` / `end_date` | string | 否 | 可选，只截取返回区间 |

`data` 字段：`as_of_date`、`as_of_date_semantics`、`valuation_basis`、`codes`（请求值）、`code_names`（代码→名称）、`points_count`、`points[]`（`{date, <code>: 累计收益率}`）。

> 累计收益率基期为**组合曲线起点**，`start_date`/`end_date` 只截断响应，不改变基期。指数为日频、CPI/M2 为月度数据；失败或无数据的代码不出现在 `points`，不会填成 0。该工具可能较慢（联网拉取），不支持或为空的代码返回 `400`。

### 5.16 `GET /api/agent/tools/risk-report`

组合风险指标、结构占比与风险提示，scope：`health:read`。

`data` 字段：

| 字段 | 说明 |
|---|---|
| `as_of_date` / `as_of_date_semantics` / `valuation_basis` | 截至日期与净值口径 |
| `max_drawdown` / `volatility` | 最大回撤（负数）与年化波动率；数据不足为 `null` |
| `max_single_weight` / `max_single_name` | 最大单基金占比与名称 |
| `hhi` | 赫芬达尔集中度指数 |
| `equity_weight` / `bond_weight` / `qdii_weight` | 权益 / 债券 / QDII 占比（小数） |
| `flags[]` | `{level, code, params, title, detail}`；`code`+`params` 供客户端本地化，`title`/`detail` 为中文兼容文案 |
| `data_quality` | `{missing_nav_fund_count, stale_nav_fund_count, pending_t1_transaction_count, caveats[]}` |

> 数据缺口不隐藏；解读指标前先看 `data_quality.caveats`。

### 5.17 `GET /api/agent/tools/industry-exposure`

组合行业穿透敞口，scope：`portfolio:read`。

`data` 字段：`ok`、`message`、`as_of_date`、`as_of_date_semantics`、`valuation_basis`、`total_market_value`、`penetrated_market_value`、`unpenetrated_market_value`、`equity_total_market_value`、`equity_penetrated_market_value`、`funds_count`、`funds_with_data`、`quarter`、`items[]`、`funds_missing[]`、`data_quality`。

> 行业配置来自外部抓取（每基金一次请求，带缓存），**可能较慢**；失败基金进入 `funds_missing`（`reason` 为 `no_data`/`parse_error`/`fetch_error`/`empty_allocations`），不影响其他基金。无持仓时 `ok=false`、`message="无持仓"`。

### 5.18 `GET /api/agent/tools/search`

按名称或代码子串检索基金池，scope：`funds:read`。不补收益/风险指标，是快速查找路径。

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `keyword` | string | 必填 | 去首尾空白后 1–100 字符；空值返回 `400`，不传或 `keyword=` 返回 `422` |
| `limit` / `offset` | int | 50 / 0 | `limit` 1–200，`offset` ≥ 0 |

`data` 字段：`ok`、`code`、`message`、`count`、`total`、`pagination`、`funds[]`；每项为 `{code, name, type, sector}`。

> 匹配是字面子串，不支持正则或任意查询表达式；结果按基金代码升序。基金池缓存未命中时会联网刷新，文件缓存有效期为 24 小时。有效查询无匹配时 `ok=true` 且 `funds=[]`；基金池加载失败时仍返回 HTTP 200，但 `ok=false`、`code="universe_failed"`，调用方必须先检查 `ok`。类型与板块来自名称推断，仅用于候选检索。

### 5.19 `GET /api/agent/tools/screen`

按资产类型、板块与关键词筛选基金池，scope：`funds:read`。

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `types` | string[] | 无 | 重复传参；必须是服务端已知类型，最多 20 个 |
| `sectors` | string[] | 无 | 重复传参；必须是服务端已知板块（含自定义），最多 20 个 |
| `keyword` | string | 无 | 可选名称/代码子串，最多 100 字符 |
| `with_metrics` | bool | `false` | 是否为当前页前 30 项补收益/风险指标 |
| `limit` / `offset` | int | 50 / 0 | `limit` 1–200，`offset` ≥ 0 |

`data` 字段：`ok`、`code`、`message`、`count`、`total`、`pagination`、`with_metrics`、`metrics`、`funds[]`。

- `metrics`：`{requested, limit=30, attempted, succeeded, failed, timed_out, complete}`。
- 每只基金：`{code, name, type, sector, scale, manager, inception_date, returns, risk, metrics_status}`。
- `metrics_status`：`not_requested`（未请求）、`over_limit`（超出前 30 项）、`ok`（已补）、`unavailable`（失败或超时）；值为 `null` 表示未取到，不补零。

> `with_metrics=true` 会访问外部净值/档案接口，**可能较慢**，且只覆盖**当前页按代码升序的前 30 项**，不是全市场收益排名。增强并发上限为 2，满额立即返回 `429`（不排队）；超时只返回已完成项，未完成项标为 `unavailable`，后台任务结束后才释放并发额度。需要精确对比时用 `funds/compare`。未知类型/板块、超过 20 个过滤值或关键词超长返回 `400`。

### 5.20 `POST /api/agent/tools/backtest/dca`

启动一次**只读定投回测任务**，scope：`funds:read`。这是**只读历史模拟**：不会写入正式净值表、交易、定投计划、自选或基金元数据，也不代表未来收益或配置建议。

端点创建任务后立即返回 `202` 与 `job_id`；用 `GET /api/agent/tools/refresh/{job_id}` 轮询（该端点同时服务刷新与回测任务，按 `job_type` 精确复核 scope，见 §5.22）。回测在后台按基金逐个执行，`progress.done/total` 反映已完成的基金数，`progress.current` 为正在执行的基金代码。

必须带 `Idempotency-Key`（16–128 安全 ASCII）：同键同参返回原 `job_id`（`replayed=true`），同键异参或异操作返回 `409 idempotency_conflict`，过期返回 `409 idempotency_expired`。创建响应的 `data`：`ok`、`code`（`queued`/`replayed`）、`message`、`replayed`、`job_id`、`status`、`fund_count`、`expires_at`。

请求体（JSON；未知字段、类型错误或约束不满足返回 `422`）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `fund_codes` | string[] | 必填 | 列表最多 5 项；6 位代码，重复代码去重后逐基金独立模拟 |
| `start_date` / `end_date` | string | 必填 | 严格 `YYYY-MM-DD`；起日早于止日；止日不晚于中国时区今日 |
| `amount_per_period` | number | 必填 | 每只基金每期金额，有限正数，≤ 1,000,000 |
| `cadence` | string | `month` | `month` / `week` / `biweek` |
| `include_lumpsum` | bool | `true` | 每只基金增加一个等实际总投入的一次性投入对照 |
| `include_curve` | bool | `true` | 是否返回曲线；`false` 时曲线为空 |
| `include_periods` | bool | `false` | 是否返回逐期买入明细（响应体更大） |
| `max_points` | int | `365` | 曲线等距抽样上限，10–2000，保留首尾 |

区间最长 10 年；月/双周/周的计划期数最多分别约为 120/261/522。非法 JSON、缺少必填字段或未知字段返回 `422`；认证与 scope 语义与其他工具一致（`401`/`403`）。并发已满返回 `429 backtest_busy`（带 `Retry-After`），不排队；429 时未创建任务与幂等记录，可按 `Retry-After` 秒数用原键重试。审计记录 `dca_backtest_started/succeeded/failed/busy/rejected`，仅记计数与 token 前缀。

轮询到 `status="succeeded"` 后，`data.result` 字段：`ok`、`message`、`simulation_note`、`requested`、`fund_count`、`result_count`、`failed_count`、`results[]`。`failed_count` 按结果条数计（同一基金的 `dca` 与 `lumpsum` 各自计一条）；`ok` 仅在全部结果失败时为 `false`，部分失败仍为 `true`，由 `message` 与各结果的 `status` 说明。

每条结果包含：

- 基础：`fund_code`、`fund_name`、`strategy`（`dca`/`lumpsum`）、`status`（`ok`/`partial`/`failed`）、`code`、`message`。
- 数据：`data_source`（`database`/`remote`/`database+remote`/`none`）、`data_start`、`data_end`、`valuation_date`、`skipped_periods`、`fee_ok`。`data_start`/`data_end` 是实际可用净值区间；没有任何有效净值时为空字符串。
- 指标：`cadence`、`amount_per_period`、`total_periods`、`invested_capital`、`total_fees`、`final_value`、`redemption_fee`、`net_final_value`、`total_return`、`annualized_return`、`max_drawdown`、`sharpe_ratio`。
- 明细：`curve`（按 `max_points` 抽样）、`curve_points`、`periods_detail`（仅在 `include_periods=true` 时非空）、`periods_detail_count`、`caveats`。
- `fee_ok=false` 表示费率表获取失败；即使 `fee_ok=true`，若申购或赎回档位缺失也会按 0 计并在 `caveats` 说明，不应解读为真实零费率。
- `status="failed"` 时 `code` 为 `insufficient_nav`（有效净值少于 2 个）或 `no_periods`（没有可执行的计划扣款日），不输出看似有效的零收益指标。
- `status="partial"` 且 `code="partial_coverage"` 表示部分计划期因净值未覆盖或与其他期落在同一净值日而跳过；`skipped_periods` 给出数量。请求止日晚于最后一个可用净值日时，末期未被覆盖的计划期即属于此情形——回测仍按可用数据计算，`valuation_date`/`data_end` 反映实际覆盖范围。

> 计划扣款日不早于请求起日。多个计划期落到同一净值日时只执行第一期，避免把多期投入堆到同一天。期末估值、赎回费持有天数与 XIRR 终值统一使用最后一个可用净值日（`valuation_date`），而不是请求止日。净值优先读取数据库，覆盖不足时通过外部接口在内存中补齐，不写库；`data_end` 可能早于 `end_date`。费率表按每只基金一次快照使用。结果未模拟分红、拆分与红利再投资；最大回撤与夏普基于市值曲线，定投现金流会影响可比性。单次请求最多 5 只基金，耗时受外部净值/费率抓取影响，建议先查 `data-status`，并遵守 20 次/分钟的限额。回测并发上限为 2（进程内），满额在创建阶段立即返回 `429 backtest_busy`（`Retry-After: 60`），不排队；多 worker 部署时各进程独立计数。任务 `status="failed"` 表示执行期异常（`data.error` 给出原因），与单只基金 `results[].status="failed"` 不同——后者任务本身仍为 `succeeded`。

## 6. 最小接入示例

### Python

```python
import os
import httpx

BASE = os.getenv("ZFUNDPILOT_BASE_URL", "http://localhost:8000")
TOKEN = os.environ["ZFUNDPILOT_AGENT_TOKEN"]  # 不要写进代码或提示词

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

### Function Calling / MCP 工具定义（示意）

```json
{
  "name": "get_portfolio_summary",
  "description": "读取 ZFundPilot 组合市值、盈亏与数据截至日期。只读。",
  "parameters": { "type": "object", "properties": {}, "additionalProperties": false }
}
```

对应请求：

```http
GET /api/agent/tools/portfolio-summary
Authorization: Bearer zfag_xxx
```

也可以用任意 HTTP 工具封装上述端点；仓库同时提供可选的 MCP 适配层（见本节末尾）。建议在 Agent 侧把 `data-status` 作为每次分析前的必查项，避免基于过期净值下结论。

---

### 5.21 自选维护（写入，默认关闭）

三个写工具共用 `watchlist:write`，并受服务端写开关约束（默认关闭；关闭时即使 token 有 scope 也返回 `403 write_disabled`，开启方式见上文「写开关」说明）。它们只修改自选关系与备注/分组，**不创建交易、定投计划、净值或基金元数据**。

| MCP 工具 | HTTP | 说明 |
|---|---|---|
| `add_watchlist_item` | `POST /api/agent/tools/watchlist` | 新增；只接受已收录基金，已存在返回冲突，不覆盖原备注/分组 |
| `update_watchlist_item` | `PATCH /api/agent/tools/watchlist/{code}` | 按 `expected_revision` 更新备注/分组；只修改显式提供的字段，空字符串表示清空 |
| `remove_watchlist_item` | `DELETE /api/agent/tools/watchlist/{code}?expected_revision=N` | 按版本删除，保留可恢复前值 |

请求示例：

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f50" \
  -d '{"fund_code":"005827","note":"观察","group_name":"核心"}'
```

- 所有写请求必须带 `Idempotency-Key`（16–128 个安全 ASCII 字符）。同键同参数返回原结果并标记 `replayed=true`；同键不同参数或不同操作返回 `409 idempotency_conflict`；过期键返回 `409 idempotency_expired`。幂等记录保留 90 天；过期后再保留 30 天宽限供排障，之后由每日维护任务清理回收（超宽限的同键重试按新请求处理，请改用新的 `Idempotency-Key`）。
- `expected_revision` 来自 `list_watchlist` 返回的 `revision`。版本不符返回 `409 revision_conflict`，不会覆盖网页或其它调用方的更新。
- 新增已存在返回 `409 already_exists`；更新/删除不存在返回 `404 not_found`；基金未收录返回 `409 fund_not_registered`。
- 成功响应 `data` 含 `ok`、`code`、`message`、`changed`、`replayed`、`fund_code`、`revision`、`operation_id`、`audit_id`、`before`/`after`。
- 删除前值只供网页管理员通过 `POST /api/watchlist/{code}/restore` 恢复；恢复同样校验墓碑版本，不能覆盖删除后的重建或修改。
- 每个 token 的写端点为 30 次/分钟；写操作与业务结果审计在同一事务提交，鉴权成功不等于业务成功。

### 5.22 数据刷新（写入，默认关闭）

启动一次**仅净值/元数据**的刷新任务，scope：`data:refresh`，同样受服务端写开关约束（见上文「写开关」说明）。它**不**调用交易净值回填、**不**执行定投，也不会创建交易或计划——这是与网页 `POST /api/nav/update` 的关键区别。

| MCP 工具 | HTTP | 说明 |
|---|---|---|
| `start_data_refresh` | `POST /api/agent/tools/refresh` | 创建任务，返回 `202` + `job_id` |
| `get_job_status` | `GET /api/agent/tools/refresh/{job_id}` | 查询进度与结果，仅创建者 token 可读；同时服务刷新与回测任务 |

`get_job_status` 同时用于查询回测任务（`job_type="dca_backtest"`，见 §5.20）。端点以 `data:refresh` 或 `funds:read` 任一 scope 进入，再按任务类型精确复核：刷新任务需要 `data:refresh`，回测任务需要 `funds:read`，未知 `job_type` 一律 `403`；先按归属校验，他人任务仍返回 `404`。

```bash
# 启动（缺省刷新当前开仓持仓；也可显式传 fund_codes，最多 50 只）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f51" \
  -d '{}' | jq
# {"tool":"start_data_refresh","data":{"job_id":7,"status":"queued","fund_count":3,...}}

curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh/7" | jq
# {"tool":"get_job_status","data":{"job_type":"data_refresh","status":"succeeded","progress":{"done":3,"total":3,"phase":"risk_levels"},"result":{"ok":true,"updated":3,"failed":0,"partial":false,"errors":[]},"can_cancel":false}}
```

- 必须带 `Idempotency-Key`（16–128 安全 ASCII）；同键同参数重放返回原 `job_id`（`replayed=true`），同键异参数/过期返回 `409 idempotency_conflict` / `idempotency_expired`。
- 任务持久化在 `refresh_jobs` 表：`status ∈ {queued,running,succeeded,failed,interrupted}`，服务重启把遗留 `queued/running` 标记为 `interrupted`，不会误报成功。任务 7 天内可查询，记录额外保留 30 天后清理。
- 已有刷新在运行时返回 `409 refresh_busy`；若占用者是刷新任务，`detail.current_job_id` 给出任务 ID，可配合 `get_job_status` 轮询（网页手动刷新占用时该字段可能为 `null`）。不排队，避免陈旧任务。
- `can_cancel` 恒为 `false`：本期不支持取消，也不提供会误导的空取消接口。
- 任务间与网页 `/api/nav/update`、调度器共用互斥锁串行执行；进度（`done/total/current/phase`）写入任务记录，并镜像到共享运行状态供网页展示。
- 错误码：`write_disabled`、`validation_error`、`refresh_busy`、`not_found`、`idempotency_conflict`、`idempotency_expired`。审计记录 `data_refresh_started/succeeded/failed/busy/rejected`，仅记计数与 token 前缀。
- 单任务基金数上限 50，`POST refresh` 限流 10 次/分钟（`GET refresh/{job_id}` 走默认 120 次/分钟）。

### 5.23 账本、定投计划与提醒处理提案（写入需网页确认，默认关闭）

本组工具只能提交**待审批提案**，不会直接写账本或计划（可信直记见 §5.24）。提案工具采用**多域授权**：持有 `transactions:propose`、`plans:propose` 或 `alerts:propose` 任一即可调用 `list/get/cancel`，但 `create` 时按 `operation_type` 精确复核（账本类需 `transactions:propose`，计划类需 `plans:propose`，提醒类需 `alerts:propose`），跨域操作返回 **403**；`capabilities` 中任一 scope 命中即列出这些工具。同样受服务端写开关约束（见上文「写开关」说明）。开放十三种 `operation_type`：`add_transaction`（新增）、`update_transaction`（修改单笔，须带 `expected_digest` 行版本前置）、`delete_transaction`（删除单笔，须带 `expected_digest`）、`add_conversion`（基金转换，成对写入卖出腿+买入腿并共享 `conversion_id`）、`delete_conversion`（按 `conversion_id` 整对删除转换，须带两腿各自的 `expected_digest`）、`batch_import`（批量追加多条交易，单提案单次审批、事务内全部成功或全部回滚），以及 F5 定投计划维护四种：`create_plan`（创建计划，强制 `enabled=0`）、`update_plan`（部分字段 patch + 版本前置 `expected_digest`）、`toggle_plan`（显式 `enable` 布尔启停）、`delete_plan`（删除计划行，历史交易不动），以及 F6.1 提醒处理一种：`resolve_alert`（确认/忽略分红或止盈止损提醒，只推进提醒状态机，不写账本），以及 F6.2 交易回填一种：`backfill_transaction_navs`（为 `nav` 缺失的已存在交易补净值及连带份额/金额/手续费，须带 `expected_digest` 行版本前置，支持 1–50 条显式 `tx_ids` 批量、整批原子），以及 F6.3 定投手动执行一种：`execute_plan`（为一条已存在计划生成一笔买入流水并推进 `last_run`/`last_tx_id`，不重算 `next_run`、不触发调度器，须带计划 `row_digest` 版本前置）；批准、拒绝、取消后的执行与状态迁移均由服务端完成，执行路径不联网。修改/删除均整笔处理；转换腿仍不支持单腿编辑，整对删除使用 `delete_conversion`。`batch_import` 仅追加，永不清空，也不支持批内 update/delete/conversion 或 `dividend_alert_id`。**计划操作永不写 transactions 表，也不触发调度器执行**；新计划默认停用，启用必须另行提交 `toggle_plan` 提案。**回填只补 nav/shares/amount/fee 四字段、审批零联网，分红行不可回填。**

| MCP 工具 | HTTP | 说明 |
|---|---|---|
| `create_operation_proposal` | `POST /api/agent/tools/proposals` | 创建提案，返回 `201` + `proposal_id`；不写账本 |
| `list_operation_proposals` | `GET /api/agent/tools/proposals` | 仅列出当前 token 创建的提案 |
| `get_operation_proposal` | `GET /api/agent/tools/proposals/{proposal_id}` | 仅创建者可读，他人提案返回 `404` |
| `cancel_operation_proposal` | `DELETE /api/agent/tools/proposals/{proposal_id}` | 取消自己仍为 `pending` 的提案 |

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
      "channel": "支付宝"
    }
  }' | jq
# {"tool":"create_operation_proposal","data":{"proposal_id":1,"status":"pending","expires_at":"...","summary":{...}}}
```

修改单笔（先取 `row_digest`，再带 `expected_digest` 提交完整字段）：

```bash
# 1) 取目标行哈希
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  $ZFUNDPILOT_BASE_URL/api/agent/tools/transactions/12 | jq '.data.row_digest'

# 2) 提交修改提案（amount 1000→2000，其余字段原样回填）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: upd-1a2b3c4d-5e6f-7a8b-9c0d" \
  -d '{
    "operation_type": "update_transaction",
    "params": {
      "tx_id": 12,
      "expected_digest": "<上一步返回的 row_digest>",
      "fund_code": "005827", "action": "buy", "date": "2026-10-30",
      "amount": 2000, "fee": 1, "channel": "支付宝", "is_t1": false, "note": ""
    }
  }' | jq
# data.summary 含 tx_id / before / after / changed_fields（如 ["amount"]）
```

删除单笔（`reason` 可选）：

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: del-9f8e7d6c-5b4a-3c2d" \
  -d '{
    "operation_type": "delete_transaction",
    "params": {"tx_id": 12, "expected_digest": "<row_digest>", "reason": "误录"}
  }' | jq
# data.summary 含 tx_id / before / reason
```

基金转换（卖出转出基金 + 买入转入基金，审批时成对原子写入）：

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
      "channel": "支付宝"
    }
  }' | jq
# data.summary.conversion 含 from（sell）/ to（buy）两腿；审批回执含 from_id/to_id
```

整对删除转换（先按 `conversion_id` 找到两腿，再分别取 `row_digest`）：

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
      "expected_from_digest": "<卖出腿 row_digest>",
      "expected_to_digest": "<买入腿 row_digest>",
      "reason": "误录"
    }
  }' | jq
```

分红/再投资流水关联分红提醒（可选，审批时同事务确认提醒）：

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

批量追加（单提案、单次审批、整批原子写入）：

```bash
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: batch-0f6c2f9a-4b1e-4e2a" \
  -d '{
    "operation_type": "batch_import",
    "params": {
      "note": "10 月对账单补录",
      "transactions": [
        {"fund_code": "005827", "action": "buy", "date": "2026-10-08",
         "amount": 1000, "fee": 1, "channel": "支付宝"},
        {"fund_code": "005827", "action": "sell", "date": "2026-10-20",
         "shares": 50, "nav": 2.15, "fee": 0.5, "channel": "支付宝"}
      ]
    }
  }' | jq
```

定投计划维护（F5，scope `plans:propose`）。先取 `row_digest`，再带 `expected_digest` 提交：

```bash
# 1) 取目标计划的 row_digest（list_auto_invest_plans 每项均带）
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/auto-invest-plans" | jq '.data.plans[] | {id, row_digest}'

# 2a) 创建定投计划（默认停用，不会被执行）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-create-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "create_plan",
    "params": {
      "fund_code": "005827", "amount": 500, "cadence": "week",
      "day_of_week": 0, "channel": "支付宝", "note": "工资定投"
    }
  }' | jq
# data.summary 含 fund_code / amount / cadence / schedule / enabled=false / next_run / scheduler_hint

# 2b) 修改定投计划（部分 patch；显式 null 清除 day 字段）
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
# data.summary 含 plan_id / before / after / changed_fields（如 ["amount"]） / scheduler_hint

# 2c) 启停定投计划（显式 enable 布尔，动作语义）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: plan-toggle-1a2b3c4d-5e6f" \
  -d '{
    "operation_type": "toggle_plan",
    "params": {"plan_id": 3, "expected_digest": "<row_digest>", "enable": true}
  }' | jq
# data.summary 含 enabled_before / enabled_after / next_run / scheduler_hint

# 2d) 删除定投计划（只删计划行，历史交易不受影响）
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
# 2e) 处理提醒（确认/忽略；只推进提醒状态，不写账本）
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
# 2f) 手动执行定投计划（生成一笔买入流水并推进计划簿记；不触发调度器）
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
# data.summary 含 plan_id / fund_code / amount / trade_date / is_t1 / fee /
# fee_source / before / after / warnings
```

- `add_transaction` 的 `params` 只接受白名单字段：`fund_code`（6 位数字、需已在网页收录）、`action`（`buy`/`sell`/`dividend`/`reinvest`）、`date`（`YYYY-MM-DD`）、`amount`/`shares`/`nav`（买/卖至少两项可推导，卖出必须有份额，分红必须有金额）、`fee`、`channel`、`note`、`is_t1`，以及可选的 `dividend_alert_id`（仅 `dividend`/`reinvest`）。未知字段返回 `422 validation_error`。
- `batch_import` 的 `params` 为 `transactions`（1–50 条，每条字段集与 `add_transaction` 完全一致，但**必须**给 `fund_code`，不接受 `fund_name`）加可选 `note`。不支持 `dividend_alert_id`（返回 `422 batch_invalid_item`，`code=unsupported_in_batch`）；`clear_existing`/`fetch_meta` 会被忽略并在 `summary.warnings` 与 `params.ignored_fields` 中标注，永不执行清空或联网拉取。创建期硬拒绝结构错误、任一条目字段错误（`422 batch_invalid_item`，带 `index`/`issues`）、基金未收录（`409 fund_not_registered`，带 `index`/`fund_code`）、批内重复（`409 batch_internal_duplicate`，带 `index`/`other_index`）；与账本或待审提案（无论同主体还是他人）重复只写 warning；批量提案之间不互相判定重复（重复检测只比对单条 `add_transaction` 提案，属已知限制，请在提交前用 `precheck_transactions` 自查）。审批时先整体校验（基金仍在、参数仍合法、按「基金+渠道最终累计余额」批内累加后非负），全部通过才逐条 `insert`，任一条失败整批不写、提案标记 `conflict` 并在 `execution_result` 带 `index`/`executed_before_failure=0`。响应 `summary` 含 `count`/`actions`/`funds`/`date_range`/`amount_total`（买入金额与卖出净额合计，不是净投入）/`items`，成功执行结果含 `tx_ids`/`count`。
- `add_conversion` 的 `params`：`from_code`、`to_code`（均为 6 位数字、需已收录且不能相同）、`date`、`from_shares`（>0）、可选 `from_nav`/`from_fee`、可选 `to_amount`/`to_nav`/`to_fee`、`channel`、`note`、`is_t1`。非 T+1 须能推导转入腿金额/份额（未填 `to_amount` 时按卖出净到账推导）；T+1 可暂缺转入金额，审批不阻断，留待净值回填。审批在单事务内成对写入 `sell`/`buy` 两腿并共享新生成的 `conversion_id`，不联网抓净值；转出份额超过该渠道可用份额仅 warning，不阻断。响应 `summary.conversion` 含两腿明细。
- `delete_conversion` 的 `params` 为 `conversion_id` + `expected_from_digest` + `expected_to_digest`（两腿各自 `row_digest`，取自 `GET /api/agent/tools/transactions/{tx_id}`）+ 可选 `reason`。创建期要求该 `conversion_id` 恰好关联两条流水且分别为卖出/买入标准对，否则 `404 conversion_not_found` / `409 conversion_leg_mismatch`；任一腿哈希不匹配返回 `409 target_changed` 并附 `leg=from|to`。审批期复读两腿并同事务整对删除；删除买入腿若令转入基金后续卖出超份额则 `insufficient_shares_after_change`，删除卖出腿恒放行。
- `add_transaction` 的 `action=dividend`/`reinvest` 可携带 `dividend_alert_id`（正整数）：审批在同一事务内写入流水，并把对应提醒置为 `confirmed`、回填 `tx_id`。提醒不存在/已处理/类型不是 `dividend`/基金不一致，分别在审批期返回 `dividend_alert_not_found`、`dividend_alert_resolved`、`dividend_alert_type_mismatch`、`dividend_alert_fund_mismatch`（均为 `conflict`，不写流水）。
- `update_transaction` 的 `params` 须带 `tx_id`（目标交易 id）与 `expected_digest`（目标行内容哈希，取自 `GET /api/agent/tools/transactions/{tx_id}` 响应的 `row_digest`），再加与 `add_transaction` 相同的**完整字段集**（非部分更新，缺省字段按规则补默认）。哈希覆盖 `fund_code/action/date/amount/shares/nav/fee/channel/note/is_t1`（数值 `round(_,4)`，`None` 保留）。目标行内容已变（`409 target_changed`）或已删（`404 target_not_found`）时创建被拒；审批期再行复核，已变/已删则 `conflict`（`target_changed`/`target_deleted`），不覆盖。改 `fund_code`/`channel` 时双侧份额校验，改基金给出 warning。
- `delete_transaction` 的 `params` 为 `tx_id` + `expected_digest` + 可选 `reason`。审批期复核哈希，通过后删除目标行；删除买入若令后续卖出超份额则 `insufficient_shares_after_change`（不删），删除卖出恒放行。
- **转换腿**（`conversion_id` 非空）的单腿修改/删除一律 `409 conversion_leg_isolated`；整对删除请使用 `delete_conversion`，不要逐腿操作。
- `create_plan` 的 `params`（scope `plans:propose`）：`fund_code`（6 位数字、需已收录）、`amount`（>0）、`cadence`（`daily`/`week`/`biweek`/`month`）、`day_of_week`（0–6，0=周一；`week`/`biweek` 必填、其余禁填）、`day_of_month`（1–31；`month` 必填、其余禁填）、可选 `channel`/`note`。**硬拒** `enabled`/`next_run`/`last_run`/`last_tx_id`（`422 validation_error`，启停必须走独立 `toggle_plan`，调度器簿记由服务端维护）。新计划强制 `enabled=0`，审批写入后 `next_run` 按执行时点计算。重复检测只 warning：同配置既有计划、同摘要待审 `create_plan`。
- `update_plan` 的 `params`（scope `plans:propose`）：`plan_id` + `expected_digest`（取自 `list_auto_invest_plans` 的 `row_digest`）+ 任意 `create_plan` 配置字段子集（**部分 patch**；显式 `null` 表示清除 `day_of_week`/`day_of_month`）。合并后的完整配置必须通过 `_validate_plan_config`（交叉规则与网页一致：非对应频率的 day 字段必须为 `None`）。目标计划不存在 `404 target_not_found`（带 `plan_id`）；摘要失配 `409 target_changed`；合并校验失败 `422 validation_error`（事务回滚）。响应 `summary` 含 `before`/`after`/`changed_fields`/`scheduler_hint`。
- `toggle_plan` 的 `params`（scope `plans:propose`）：`plan_id` + `expected_digest` + `enable`（布尔，必填）。**不重算 `next_run`**（与网页启停一致）；启用而 `next_run` 已过期时 `summary.scheduler_hint` 提示调度器将尽快补投一期。同状态拒绝（`422 validation_error`，提示重新读取 `row_digest`）。目标缺失/失配错误码同 `update_plan`。摘要覆盖 `enabled`，故启停也算配置变更。
- `delete_plan` 的 `params`（scope `plans:propose`）：`plan_id` + `expected_digest`。审批期复核后只删计划行，历史交易与调度器簿记不动。响应 `summary` 含 `before`。
- `resolve_alert` 的 `params`（scope `alerts:propose`）：`alert_type`（`dividend`/`take_profit`/`stop_loss`）、`alert_id`、`expected_digest`（取自 `list_alerts` 的 `row_digest`）、`status`（仅 `confirmed`/`ignored`；**不支持回滚为 `pending`**，误处理请走网页更正），以及可选 `tx_id`（仅分红提醒且 `status=confirmed` 时可关联一条**已存在**的分红/再投资流水；不创建新流水）。创建期校验提醒存在、类型一致、当前为 `pending`、摘要匹配、关联流水存在且动作/基金一致且未被其他提醒占用；审批期在同一事务内复读并复核，成功后只更新提醒的 `status`/`resolved_at`/`tx_id` 并写审计，**不写 `transactions` 表**。`row_digest` 覆盖 `status/resolved_at/tx_id` 与业务字段，任何状态推进都会改变摘要。错误码：`404 target_not_found`；`409 not_pending`/`target_changed`/`tx_not_found`/`tx_mismatch`/`tx_already_linked`（创建期直接返回，审批期标记 `conflict` 并带 `target_deleted`/`target_changed`/`not_pending`/`alert_type_changed` 等 `reason`）。`summary` 含 `alert_id`/`alert_type`/`before_status`/`after_status`/`linked_tx_id` 与提醒业务字段。
- `backfill_transaction_navs` 的 `params`（scope `transactions:propose`）：`items`（1–50 条，每条为 `{tx_id, expected_digest, fee?}`；`tx_id` 为目标交易 id、`expected_digest` 取自 `GET /api/agent/tools/transactions/{tx_id}` 的 `row_digest`、可选 `fee` 仅当服务端无法算出费率时才需显式提供；批内 `tx_id` 去重）。**只做显式指定的行，不做「回填全部」**。仅补 `nav/shares/amount/fee` 四字段，不触碰 `date/action/fund_code/channel/note/is_t1`。分红行语义上不可回填（分红 `nav` 是每份分红金额而非基金净值），整批拒绝 `422 dividend_not_backfillable`；`nav IS NULL` 不满足返回 `409 nav_present`；缺摘要 `409 target_changed`、行不存在 `409 target_not_found`、本地无可用净值 `409 nav_unavailable`、费率/确认净值未知 `409 fee_unknown`（此时可显式给 `fee` 重提）。创建期**一次性预计算**每行 `nav`（按 T+1 规则取成交当日/次日净值，缺当天取之后首个净值日）与 `fee`（已有非零沿用 `existing`，否则按方向算 `fetched`：买入按金额、卖出按份额，与网页离线回填口径一致；Agent 显式提供记 `explicit`；卖出无买入记录 `no_buy_record` 也归入 `fee_unknown`，不静默填 0）并快照进 `summary_json`，**审批零联网、不重算漂移值**；预计算在写事务之外完成（费率抓取可能联网），写事务内只复读目标行做 digest 复核；任一行不可执行时整批拒绝、不创建悬空提案。审批在单事务内逐行复读（`nav IS NULL` + `digest` 匹配），全部通过才整批写快照值，任一行已回填/已改/已删 → 整批 `conflict`（`partially_updated`/`target_changed`/`target_deleted`/`proposal_corrupt`），无部分写入。`summary` 含 `count`/`funds`/`fee_sources`/`items`（逐行 `before`/`after` 仅覆盖回填四字段，`nav_date` 标注 T+1 采用的净值日；T+1 卖出回填 `nav` 取次日净值，赎回费仍按成交日净值计算，与网页既有口径一致）。
- `execute_plan` 的 `params`（scope `transactions:propose`）：`plan_id` + `expected_digest`（取自 `list_auto_invest_plans` 的 `row_digest`）+ 可选 `trade_date`（`YYYY-MM-DD`，缺省为创建当天上海时区，仅允许 `today-7` 至 `today`）+ 可选 `fee`（仅在服务端算不出申购费时需显式提供）。**金额/渠道/备注/`is_t1`/启停与调度器簿记字段（`enabled`/`next_run`/`last_run`/`last_tx_id`）一律硬拒（`422 validation_error`）**：金额、渠道、备注取自计划快照，`is_t1` 由「交易日是否为今天且创建时点 ≥15:00」判定。创建期在写事务外一次性判定可投性并抓取费率（显式 `fee` 则跳过抓取），费率未知（`fee_unknown`）时拒绝创建、不静默写 0；审批零联网，按快照写一笔 `buy`（`shares/nav` 仍为 `NULL`，待净值回填），并推进 `last_run = max(现有, trade_date)` 与 `last_tx_id`，**不重算 `next_run`、不触发调度器**。今天依赖 `last_run == trade_date` 防重；补记历史日期另有「同一 `plan_id + trade_date` 的已成功提案」查询兜底，避免 `last_run` 不回退导致重复写入。创建期错误码：`404 target_not_found`（计划不存在）、`409 target_changed`（摘要失配）、`already_executed`（当日已执行或历史日期已有成功提案）、`suspended`/`limit_exceeded`/`below_minimum`（严格阻断，detail 带 `reason`；与网页手动执行仅 warning 的口径不同）、`fee_unknown`；审批期同类问题标记 `conflict`（`target_deleted`/`target_changed`/`already_executed`/`purchasable_changed`/`proposal_corrupt`）。停用计划仍允许手动执行（`summary.warnings` 提示）；非交易日不硬阻断，仅 warning。`summary` 含 `plan_id`/`fund_code`/`amount`/`trade_date`/`is_t1`/`fee`/`fee_source`（`fetched`/`explicit`）/`channel`/`note`/`before`/`after`/`warnings`。
- 计划操作的审计事件与网页对齐：`auto_invest_plan_create`/`update`/`toggle`/`delete`，`detail` 带 `plan_id` + `proposal_id`（`toggle` 另带 `enabled`）。计划操作永不写 transactions 表、不触发调度器执行。手动执行定投（`execute_plan`）审批成功记 `auto_invest_execute`（与网页/调度器对齐），`detail` 带 `plan_id`/`fund_code`/`amount`/`tx_id`/`trade_date`/`is_t1`/`proposal_id`。提醒处理同样与网页对齐：分红记 `dividend_alert_update`、止盈止损记 `tp_sl_alert_update`，`detail` 带 `id`/`status`/`tx_id`/`proposal_id`。
- 必须带 `Idempotency-Key`（16–128 安全 ASCII）。同键同参数返回原提案（`200` + `replayed=true`）；同键异参数/跨操作返回 `409 idempotency_conflict`，过期键返回 `409 idempotency_expired`。`tx_id`+`expected_digest`+完整字段集视作 update 的完整参数参与重放比对。`plan_id`+`expected_digest` 视作 plan 类 update/toggle/delete 的完整参数参与重放比对；`alert_type`+`alert_id`+`expected_digest`+`status`+`tx_id` 视作 `resolve_alert` 的完整参数参与重放比对；`plan_id`+`expected_digest`+`trade_date`+`fee` 视作 `execute_plan` 的完整参数参与重放比对。
- 提案默认 7 天过期；过期后不可批准，也不能取消。每个 token 最多同时保留 20 个 `pending` 提案，超限返回 `409 too_many_pending`（`batch_import` 提案按 1 条计）。
- 基金尚未收录返回 `409 fund_not_registered`，避免审批路径联网补数据（`resolve_alert` 例外：历史提醒可能引用已移除的基金，不阻断处理）。计划类操作的目标计划不存在返回 `404 target_not_found`（带 `plan_id`），配置摘要失配返回 `409 target_changed`（带 `plan_id`）；审批期复核同样产出 `conflict`（`target_deleted`/`target_changed`），不覆盖他人改动。
- 状态机：`pending → succeeded / failed / conflict / rejected / cancelled / expired`。`failed` 表示创建者 token 失效或失去 scope；`conflict` 表示基金/参数/计划/提醒/定投执行目标在审批时已不合法（含目标被删/被改、提醒已处理、当日已执行、基金变为不可申购）。环境级阻断（`auth_disabled`、`write_disabled`）返回 `403` 且提案保持 `pending`，修复后可重试。
- 网页管理员在「待确认提案」页面批准后，服务端在同一 SQLite 事务内复核实例认证、写开关、创建者 token 与业务规则，写入账本/计划并记录 `proposal_approved` 与业务审计（账本类：`add_transaction`/`add_conversion`/`delete_conversion`，批量为每条 `add_transaction` 带 `batch_index`，分红关联另记 `dividend_alert_confirm`；计划类：`auto_invest_plan_create`/`update`/`toggle`/`delete`，均带 `plan_id`+`proposal_id`；提醒类：`dividend_alert_update`/`tp_sl_alert_update`，带 `id`/`status`/`tx_id`/`proposal_id`）；并发审批只有一个能成功，重复审批返回 `409 not_pending`。
- 网页审批端点仅接受网页登录身份：`GET /api/proposals/count`、`GET /api/proposals`、`GET /api/proposals/{id}`、`POST /api/proposals/{id}/approve`、`POST /api/proposals/{id}/reject`。Agent token 调用这些路径返回 `401`。
- 错误码：`write_disabled`、`validation_error`、`fund_not_registered`、`too_many_pending`、`not_pending`、`expired`、`not_found`、`target_changed`（目标行/转换腿哈希不匹配，`409`）、`target_not_found`（目标行不存在，`404`）、`conversion_leg_isolated`（转换腿单腿修改/删除被拒，`409`）、`conversion_not_found`（`conversion_id` 不存在或已非成对，`404`）、`conversion_leg_mismatch`（关联流水不是 sell/buy 标准对，`409`）、`batch_invalid_item`（批量：某条字段错误，`422`，带 `index`/`issues`）、`batch_internal_duplicate`（批量：批内重复，`409`，带 `index`/`other_index`）、`insufficient_shares_after_change`（审批执行期：修改/删除/批量令后续卖出超份额，`conflict`）、`fund_missing`（审批期基金已从账本移除）、`dividend_alert_not_found`/`dividend_alert_resolved`/`dividend_alert_type_mismatch`/`dividend_alert_fund_mismatch`（审批期分红提醒关联失败）、`not_pending`（提醒已处理，`409`）、`tx_not_found`/`tx_mismatch`/`tx_already_linked`（`resolve_alert` 关联流水失败，`409`）、`dividend_not_backfillable`（`backfill_transaction_navs`：分红行不可按净值回填，`422`）、`nav_present`（回填：已有净值，`409`）、`nav_unavailable`（回填：本地无可用净值，`409`）、`fee_unknown`（回填：费率/确认净值未知、卖出无买入记录或买入缺金额，且未显式给 `fee`，`409`）、`partially_updated`/`target_deleted`/`proposal_corrupt`（回填审批期整批冲突，`409`）、`already_executed`（`execute_plan`：该计划在目标交易日已执行或历史日期已有成功提案，`409`）、`suspended`/`limit_exceeded`/`below_minimum`（`execute_plan` 创建期基金不可申购，`409`，detail 带 `reason`）、`purchasable_changed`（`execute_plan` 审批期基金变为不可申购，`conflict`）、`proposal_corrupt`（提案快照缺失/与计划不一致，`conflict`）、`idempotency_conflict`、`idempotency_expired`。审计记录 `proposal_created`、`proposal_create_rejected`、`proposal_cancelled`、`proposal_expired`、`proposal_approved`、`proposal_rejected`、`proposal_failed`、`proposal_conflict`，只记 token 前缀与提案摘要（update/delete 摘要含 `tx_id`/`before`/`after`/`changed_fields`/`reason`；转换摘要含 `conversion`/`conversion_id`；批量摘要含 `count`/`actions`/`funds`/`date_range`/`amount_total`/`items`，审批成功逐条记 `add_transaction` 并带 `batch_index`；回填摘要含 `count`/`funds`/`fee_sources`/`items`，审批成功逐行记 `nav_backfill`（`detail` 带 `proposal_id`，与网页/调度器对齐）；提醒摘要含 `alert_id`/`alert_type`/`before_status`/`after_status`/`linked_tx_id`；定投执行摘要含 `plan_id`/`fund_code`/`amount`/`trade_date`/`is_t1`/`fee`/`fee_source`/`before`/`after`，审批成功记 `auto_invest_execute`（`detail` 带 `proposal_id`））。
- 提醒处理提案（`alerts:propose`，`resolve_alert`）不要求 `funds` 表收录该基金：历史提醒可能引用已从 `funds` 移除的代码，缺失时展示名回退为代码。执行**只推进提醒状态机**（`status`/`resolved_at`/`tx_id`），永不写 `transactions` 表；分红确认可携带已有分红/再投资流水 `tx_id` 做关联，不创建新流水。审计与网页对齐：分红 `dividend_alert_update`、止盈止损 `tp_sl_alert_update`，`detail` 带 `id`/`status`/`tx_id`/`proposal_id`。
- 创建/取消与自选写共用写总开关；提案不进入备份 ZIP，恢复备份时会清空未完成提案，避免旧提案指向已替换的数据。

### 5.24 可信单笔直记（写入，默认关闭）

仅用于用户**明确陈述已在外部平台完成**的单笔普通买入/卖出；不得凭截图、预测、建议推断交易。scope：`transactions:create`，同样受服务端写开关约束（见上文「写开关」说明）。预检异常时，Token 同时持有 `transactions:propose` 会降级为待审批提案，否则返回 409 稳定错误码；硬失败（未收录、日额度用尽）不降级。

| MCP 工具 | HTTP | 说明 |
|---|---|---|
| `record_transaction` | `POST /api/agent/tools/transactions` | 直记单笔 buy/sell；返回 `execution_mode` 区分直记与降级 |

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
    "channel": "支付宝"
  }' | jq
# {"tool":"record_transaction","data":{"execution_mode":"direct","transaction_id":12,"operation_id":3,"receipt":{...},"daily_quota":{"used":1,"count_limit":10,...},"verify_path":"/transactions"}}
```

- 请求体为扁平字段：`fund_code`、`action`（仅 `buy`/`sell`）、`date`（`YYYY-MM-DD`，不得晚于今天，否则 `422 future_date`）、`amount`/`shares`/`nav`、`fee`、`channel`、`note`、`is_t1`。未知字段按请求校验错误返回 `422`。
- 必须带 `Idempotency-Key`（16–128 安全 ASCII）。同键同参返回原结果（`200` + `replayed=true`）；同键异参返回 `409 idempotency_conflict`。**重放永不升级**：原结局为降级提案时，即使诱因消除，重放仍返回提案实时状态，不会再直写第二笔。
- 预检顺序：参数/日期 → 幂等重放 → 事务内复核 token/scope/写总闸 → 基金收录 → 每日额度 → 疑似重复 → 卖出份额 → 单笔金额上限。
- 错误码：`write_disabled`、`scope_revoked`、`validation_error`、`future_date`、`fund_not_registered`（409，不降级）、`daily_quota_exceeded`（429，含 `used`/`limit`/`reset_at`，不降级）、`duplicate_candidate`（账本重复含 `tx_id`；命中本人待审提案含 `proposal_id`，命中他人提案只报重复、不含 ID）、`insufficient_shares`（含 `available`/`requested`）、`amount_exceeds_cap`（含 `cap`/`amount`）、`idempotency_conflict`/`idempotency_expired`、`too_many_pending`（降级路径透传）。
- 降级产生的提案与 `create_operation_proposal` 完全等价，需在「待确认提案」页批准；同主体已存在同参 pending 提案时复用而非新建。
- 额度（可 env 覆盖）：单笔 `ZFUNDPILOT_AGENT_TX_MAX_AMOUNT`（默认 50 万）、每日笔数 `ZFUNDPILOT_AGENT_TX_DAILY_COUNT`（默认 10，含降级）、每日金额 `ZFUNDPILOT_AGENT_TX_DAILY_AMOUNT`（默认 100 万，仅直写累计）；路由限流 10 次/分钟。
- 直记写入的交易 `source="agent"`，流水页显示「Agent」徽标；网页/CSV/提案审批路径 `source` 为空。审计记录 `agent_direct_add`（直记成功）、`agent_direct_downgraded`（降级）、`agent_direct_rejected`（拒绝），并沿用业务 `add_transaction`（detail 含 `source`）。

### 5.25 CSV/截图预检与对账预检（只读，默认关闭）

**只读预检**：在提交交易提案前，先校验 CSV 或条目数组的基金收录、字段合法性与重复情况；或把截图持仓与账本持仓对账，生成差额建议交易。不写账本、不联网、不创建提案，仅返回结构化报告供调用方与用户确认后再走 `create_operation_proposal`。scope：`transactions:propose`，受写总闸约束（关闭时 `403 write_disabled`），路由限流 10 次/分钟。

| MCP 工具 | HTTP | 说明 |
|---|---|---|
| `precheck_transactions(payload)` | `POST /api/agent/tools/precheck/transactions` | 预检 CSV 文本或条目数组 |
| `precheck_reconciliation(payload)` | `POST /api/agent/tools/precheck/reconciliation` | 截图持仓对账，生成差额建议交易 |
| `precheck_backfill(payload)` | `POST /api/agent/tools/precheck/backfill` | 回填净值候选盘点，逐行返回 `row_digest` 与回填快照 |

```bash
# 条目预检
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/precheck/transactions" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":{"format":"items","items":[
    {"fund_code":"005827","action":"buy","date":"2026-10-30","amount":1000,"channel":"支付宝"}
  ]}}' | jq
# {"tool":"precheck_transactions","data":{"ok":true,"total":1,"valid":1,"invalid":0,
#  "duplicate":0,"items":[{"index":0,"status":"valid","proposal_ready":true,...}],"parse_errors":[]}}

# 持仓对账预检
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/precheck/reconciliation" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":{"holdings":[{"fund_code":"005827","shares":5932}],"channel":"支付宝"}}' | jq

# 回填净值候选盘点（省略 tx_ids 时盘点全部 nav IS NULL 非分红行）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/precheck/backfill" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tx_ids":[42]}' | jq
# {"tool":"precheck_backfill","data":{"total":1,"ready":1,"unavailable":0,"items":[
#  {"tx_id":42,"fund_code":"005827","action":"buy","date":"2026-10-30","nav_date":"2026-10-30",
#   "row_digest":"...","backfillable":true,"before":{"nav":null,...},"after":{"nav":1.5,...},"fee_source":"needs_fee","fee_pending":true}]}}
```

**交易预检**（`precheck_transactions`）：

- `input.format`：`"csv"`（需 `csv_text` 字符串，≤5 MB）或 `"items"`（数组，≤200 条）；可选 `channel_hint` 补全缺渠道的条目。
- 每条经「基金识别 → 字段校验 → 重复检测」三步：`fund_code` 查账本 `funds` 表校验收录（离线可用）；`fund_name` **也只查账本已收录基金**（精确 → 双向唯一子串匹配，覆盖 A/C 类后缀差异），不联网、不读基金池。返回 `status`：`valid`/`invalid`/`duplicate`，附 `fund_resolution`、`duplicate`、`issues`（`code` 含 `no_match`/`ambiguous_match`/`validation_error`/`invalid_params`/`missing_channel`/`missing_fee`）与 `proposal_ready` 标志。
- `duplicate.kind` 为 `ledger` 或 `pending_proposal`；`pending_proposal` 带 `own`（是否本人提案），仅 `own=true` 时返回 `proposal_id`，他人提案只参与重复判定、不泄漏 ID。
- 重复检测复用直记/提案的 `_duplicate_in_ledger`（同基金+渠道+日期+方向且金额或份额容差匹配）与 `_duplicate_pending_proposal`（待审批提案，跨主体保守判定）。
- 硬阻断仅：`date`/`action`/`fund_code`/`shares`(卖出)/`amount`(分红) 缺失或非法；`channel`/`fee` 缺失为 warning（条目仍 `valid`）。`missing_fee` 按「条目是否提供 `fee`」判断（items 路径）或「CSV 是否含 fee 列」判断（csv 路径），显式 `fee=0` 不告警。
- `parse_errors` 每条含 `line`（CSV 行号，无法定位时为 `null`）与 `message`。
- 请求级错误（`format` 非法、`items` 非数组、超 200 条、CSV 超 5 MB）返回 `422`，`detail.code` / `error.code` 为 `validation_error`/`too_many_items`/`csv_too_large`。

**对账预检**（`precheck_reconciliation`）：

- `input.holdings`：`[{fund_code 或 fund_name, shares, market_value?}]`，≤100 条；可选 `channel` 按渠道过滤（≤50 字符）。
- 先做基金识别 + `shares` 校验（非负有限数字），未收录或 shares 非法的条目进 `fund_resolution_errors`（含 `reason`：`fund_unresolved`/`invalid_shares`/`not_object`），不参与对账；被剔除的基金**不会**生成 `maybe_sold` 清仓建议。
- 合法条目复用 `analysis.reconcile_holdings` 生成差额表：`status` 为 `buy`/`sell`/`ok`/`new`/`maybe_sold`，附 `suggested_tx`（`nav` 取 `latest_nav` 估算，`note` 标注「请核实」）、`fund_resolution`（完整 shape）、`issues` 与 `proposal_ready` 标志。
- `maybe_sold`（系统有、输入无）一律 `proposal_ready=false`，并在 `issues` 附 `absent_from_input`；这只是疑似清仓提示，须用户确认后另行处理。`suggested_tx.date` 为 `null`，创建提案时须填当日日期。
- 调用方据报告确认后，用 `create_operation_proposal`（`add_transaction`）逐条提交建议交易，仍需网页审批。

**回填净值预检**（`precheck_backfill`）：

- `payload.tx_ids`：可选；省略时盘点全部 `nav IS NULL` 且非分红的行（按 `date`、`id` 升序，上限 50），给定 `tx_ids` 时按给定顺序逐行报告（≤50 条、批内去重，含不可回填原因）。
- 每行返回 `tx_id`/`fund_code`/`fund_name`/`action`/`date`/`is_t1`/`before`（`nav`/`shares`/`amount`/`fee`）与 `row_digest`（可直接作 `backfill_transaction_navs` 提案的 `expected_digest`）；可回填行另带 `nav_date`（T+1 用次日净值）、`after` 回填快照与 `fee_source`，`backfillable=true`。预检**完全不联网**：净值只查本地，缺失手续费的行标记 `fee_source="needs_fee"` + `fee_pending=true`（创建提案时再抓取，或由 Agent 显式给 `fee`），不会触发费率抓取。
- 不可回填行 `backfillable=false` 并带 `reason`：`dividend_not_backfillable`（分红 `nav` 是每份分红金额）、`nav_present`（已有净值）、`nav_unavailable`（本地无可用净值）、`fee_unknown`（买入缺金额等无法计算，可显式给 `fee` 后提案）。
- 顶层响应 `total`/`ready`/`unavailable`/`items`。**不写账本、不创建提案**，与交易/对账预检一致；受写总闸约束（关闭时 403）、限流 10 次/分钟。

两个预检成功时分别写审计 `agent_precheck_transactions`（token 前缀、`format`、条目计数）与 `agent_precheck_reconciliation`（token 前缀、`channel`、差额条目数）；回填预检写审计 `agent_precheck_backfill`（token 前缀、是否给定 `tx_ids`、`total`/`ready`/`unavailable` 计数）。三者均**不记录**条目金额或明细。

### MCP 适配层（可选）

仓库内置一个 stdio MCP 桥接，把上述工具封装成 MCP 工具，供 Claude Desktop、Cursor 等客户端直接调用。它只是带 Agent token 的 HTTP 客户端，不访问数据库，鉴权、scope 与限流完全复用 HTTP 入口。

```bash
# 在 ZFundPilot 源码目录安装可选依赖
pip install 'zfundpilot[agent]'

# 手动运行（正常由 MCP 客户端拉起）
export ZFUNDPILOT_BASE_URL=http://127.0.0.1:8000
export ZFUNDPILOT_AGENT_TOKEN=zfag_xxx
python -m zfundpilot.mcp_server
```

Claude Desktop 配置示例（`claude_desktop_config.json`）：

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

暴露的 MCP 工具：`get_portfolio_summary`、`get_data_status`、`list_positions`、`get_fund_detail`、`get_portfolio_health`、`get_returns`、`compare_funds`、`list_transactions`、`get_transaction`、`list_watchlist`、`list_alerts`、`list_auto_invest_plans`、`get_portfolio_curve`、`get_benchmark_comparison`、`get_risk_report`、`get_industry_exposure`、`search_funds`、`screen_funds`、`run_dca_backtest`、`get_agent_capabilities`、`add_watchlist_item`、`update_watchlist_item`、`remove_watchlist_item`、`start_data_refresh`、`get_job_status`、`create_operation_proposal`、`list_operation_proposals`、`get_operation_proposal`、`cancel_operation_proposal`、`record_transaction`。
写工具与任务化回测（`run_dca_backtest`）需要在客户端提供 `idempotency_key`，并映射到 HTTP 的 `Idempotency-Key`；MCP 客户端只负责传参，不能替代服务端鉴权、scope 与写开关。

每个 MCP 工具都带 `ToolAnnotations`（`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`），便于 MCP 客户端在 UI 上区分只读查询与写操作：

- **只读工具**（26 个：`get_portfolio_summary`、`get_data_status`、`list_positions`、`get_fund_detail`、`get_portfolio_health`、`get_returns`、`compare_funds`、`list_transactions`、`get_transaction`、`list_watchlist`、`get_job_status`、`precheck_*`、`list_operation_proposals`、`get_operation_proposal`、`list_alerts`、`list_auto_invest_plans`、`get_portfolio_curve`、`get_benchmark_comparison`、`get_risk_report`、`get_industry_exposure`、`search_funds`、`screen_funds`、`run_dca_backtest`、`get_agent_capabilities`）设 `readOnlyHint=True`。
- **追加型写**（`add_watchlist_item`、`start_data_refresh`、`create_operation_proposal`、`record_transaction`）设 `destructiveHint=False` + `idempotentHint=True`：只追加不覆盖，幂等键可安全重试。
- **修改/删除/取消型写**（`update_watchlist_item`、`remove_watchlist_item`、`cancel_operation_proposal`）设 `destructiveHint=True` + `idempotentHint=True`。

这些注解**仅是给客户端的提示**（`ToolAnnotations` 的所有字段按 MCP 规范都是 hint），不构成访问控制：实际安全仍由服务端的 scope 门控与 Agent 写开关独立校验，客户端 UI 不应（也不能）仅凭注解放行或拦截调用。

- `ZFUNDPILOT_BASE_URL` 默认 `http://127.0.0.1:8000`；ZFundPilot 跑在 NAS/Docker 时改成实际地址，远程访问请用 HTTPS。
- `ZFUNDPILOT_TIMEOUT` 可选，默认 30 秒，范围 1–120。
- token 只从环境变量读取，不写入配置仓库或提示词；泄漏后立即在设置页撤销。

## 7. 端到端示例（Agent 闭环）

> 本节示例全部走 `/api/agent/tools/*` HTTP 接口，MCP 工具与之一一对应（工具名见上文「统一能力表」）。示例省略 `Host` 与响应信封（`schema_version`/`tool`/`request_id`/`generated_at`/`currency`/`data`，见 §4）。`$ZFUNDPILOT_AGENT_TOKEN` 为 token 明文，只应来自环境变量，**不要**写入代码、URL 或提示词。
>
> 写示例假设管理员已为 token 勾选对应 scope **且**已开启「Agent 写能力」总开关；否则写端点返回 `403 write_disabled`。

### 7.1 只读分析：先确认数据状态，再下结论

```bash
# 1) 数据是否新鲜、是否有待确认净值的 T+1 交易
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/data-status" | jq '.data'
# {"as_of_date":"2026-11-13","as_of_date_semantics":"...",
#  "missing_nav_fund_count":0,"stale_nav_fund_count":1,
#  "pending_t1_transaction_count":2}

# 2) 组合汇总与持仓（金额基于最新正式净值）
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/portfolio-summary" | jq '.data'
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/positions?limit=20" | jq '.data.positions'
```

- `as_of_date` 是各持仓正式净值日期的**最大值**，不代表所有基金都已更新；`stale_nav_fund_count` / `missing_nav_fund_count` 非 0 时应在回答中显式提示。
- 待确认净值的 T+1 交易会造成成本/份额口径偏差，先说明再分析，不要给出确定性结论。

### 7.2 自选维护（低风险直写）

```bash
# 1) 读取当前自选与每项 revision
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist?limit=50" | jq '.data.watchlist'

# 2) 新增（必须带 Idempotency-Key）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f50" \
  -d '{"fund_code":"005827","note":"观察","group_name":"核心"}' | jq '.data'

# 3) 更新备注/分组（带 revision 前置，避免覆盖网页侧的修改）
curl -s -X PATCH "$ZFUNDPILOT_BASE_URL/api/agent/tools/watchlist/005827" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d" \
  -d '{"expected_revision":3,"note":"重点观察"}' | jq '.data'
```

- 同键同参重试返回原结果（`replayed=true`）；同键异参返回 `409 idempotency_conflict`。
- `expected_revision` 不匹配返回 `409 revision_conflict`：应**重新读取 revision 后再改**，不要盲目重试。
- 自选写入只影响自选关系与备注/分组，不写交易、净值或定投计划。

### 7.3 刷新与轮询（202 + job_id）

```bash
# 1) 启动（缺省刷新当前开仓持仓；也可显式传 fund_codes，最多 50 只）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f51" \
  -d '{}' | jq '.data'
# {"job_id":7,"status":"queued","fund_count":3,...}

# 2) 轮询（建议 1–2 秒一次，直到终态）
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/refresh/7" | jq '.data'
# {"job_type":"data_refresh","status":"succeeded","progress":{"done":3,"total":3},
#  "result":{"ok":true,"updated":3,"failed":0,"partial":false,"errors":[]},"can_cancel":false}
```

- 终态为 `succeeded` / `failed` / `interrupted`；服务重启会把遗留 `queued`/`running` 标为 `interrupted`，不会误报成功。
- 返回 `409 refresh_busy` 时，用 `detail.current_job_id` 轮询已有任务，不要换键重复创建（不排队）。
- 任务 7 天内可查询；刷新只更新净值/元数据，**不**回填交易净值、**不**执行定投。

### 7.4 已发生交易：提案 → 网页批准 → 核对

```bash
# 1) 提交提案（不写账本）
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f52" \
  -d '{"operation_type":"add_transaction","params":{
        "fund_code":"005827","action":"buy","date":"2026-11-10",
        "amount":1000,"fee":1,"channel":"支付宝"}}' | jq '.data'
# {"ok":true,"proposal_id":18,"status":"pending","expires_at":"2026-11-17T...","summary":{...}}

# 2) 管理员在网页「待确认提案」点批准（服务端同事务写入账本并审计）。
#    对应网页接口：POST /api/proposals/18/approve（需网页登录 token，不是 Agent token）。

# 3) Agent 侧核对提案结果与账本流水
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/proposals/18" | jq '.data | {status, execution_result}'
# {"status":"succeeded","execution_result":{"ok":true,"message":"..."}}

curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions?fund_code=005827&limit=5" | jq '.data.transactions[0]'
```

- 提案默认 7 天过期；已过期/已拒绝/已取消的提案不能再批准。
- 批准前 `list_transactions` 看不到这笔交易——**提案不是写入**。对用户应说「已提交，待网页确认」，不要宣称“已记录”。
- 修改/删除已存在流水需 `expected_digest`（先从 `GET transactions/{tx_id}` 的 `data.row_digest` 获取）；目标已被改动返回 `409 target_changed`，应重新读取后重建提案。

### 7.5 可信单笔直记 → 回执 → 更正

```bash
# 仅当用户明确说明「已在外部平台完成」且 token 具有 transactions:create
curl -s -X POST "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions" \
  -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: direct-0f6c2f9a-4b1e-4e2a-9d0e-7c1d2b3a4f52" \
  -d '{"fund_code":"005827","action":"buy","date":"2026-11-10",
       "amount":1000,"fee":1,"channel":"支付宝"}' | jq '.data'
# {"execution_mode":"direct","transaction_id":42,"receipt":{...},
#  "daily_quota":{"used":1,"count_limit":10,...},"verify_path":"/transactions"}

# 核对回执
curl -s -H "Authorization: Bearer $ZFUNDPILOT_AGENT_TOKEN" \
  "$ZFUNDPILOT_BASE_URL/api/agent/tools/transactions/42" | jq '.data'
```

- **边界（重要）**：直记是管理员对该 Token 的**预授权**，不是服务端验证了「本次对话中用户已确认」。模型自述、客户端弹窗、同一 Agent 再调用批准工具，都不构成独立的人类审批。不得凭截图、预测、建议或“看起来应该买过”推断交易。
- 先核对回执（金额/日期/渠道/净值状态），再向用户复述结果。
- 更正已直记的流水：取 `row_digest` → 提交 `update_transaction` 提案（需 `transactions:propose`）→ 网页批准。直记本身不支持修改/删除/转换/定投。

### 7.6 异常转审批（降级）与硬失败

| 命中情况 | 返回 | Agent 动作 |
|---|---|---|
| 疑似重复、卖出份额不足、单笔金额超限 | `200` + `data.execution_mode="proposal"` + `proposal_id`（需同时持有 `transactions:propose`） | 告知用户已转待审提案，等待网页批准 |
| 同上但只有 `transactions:create` | `409` + `duplicate_candidate` / `insufficient_shares` / `amount_exceeds_cap` | 不要换键重试直写；说明原因，必要时改走提案 |
| 待审提案数量超限 | `409 too_many_pending`（降级路径透传） | 先处理已有提案，再重试 |
| 基金未收录 | `409 fund_not_registered` | 不降级；让用户先在网页收录基金 |
| 当日额度用尽 | `429 daily_quota_exceeded`（含 `used`/`limit`/`reset_at`） | 不降级；告知额度与重置时间 |
| 请求体非法 | `422 validation_error` / `future_date` | 修正参数，不要原样重试 |

- **重放永不升级**：原结局是降级提案时，同键重放始终返回该提案的实时状态，即使诱因已消除也不会补写第二笔。
- 降级提案与 `create_operation_proposal` 完全等价；同主体同参的 pending 提案会被复用而不是新建。

### 7.7 权限、过期、撤销、冲突与重试

| 场景 | 状态码 / `error.code` | 建议动作 |
|---|---|---|
| 缺少 scope | `403 insufficient_scope` | 不重试；请管理员补 scope（需重新签发 token） |
| 写总闸关闭 | `403 write_disabled` | 不重试；请管理员在设置页开启 |
| 实例未启用密码认证 | `403 auth_disabled` | 不重试；请管理员先配置管理员密码 |
| token 无效 / 过期 / 已撤销 | `401 invalid_token` / `expired` / `revoked` | 立即停止，不要重试；请管理员重新签发 |
| 触发限流 | `429 rate_limited`（`retryable=true`） | 按 `Retry-After` 秒数重试 |
| 数据库忙 | `503 database_busy`（`retryable=true`） | 按 `Retry-After` 秒数重试 |
| 同键不同参数 | `409 idempotency_conflict` | 生成新的 `Idempotency-Key`；不要复用旧键 |
| 幂等键过期 | `409 idempotency_expired` | 用新键重新发起（先确认业务未执行） |
| 自选版本冲突 | `409 revision_conflict` | 重新读取 `revision` 后再改 |
| 提案目标已变更 | `409 target_changed` | 重新读取目标 `row_digest` 后重建提案 |
| 刷新已在运行 | `409 refresh_busy` | 轮询 `detail.current_job_id` |
| 回测并发已满 | `429 backtest_busy` | 未创建任务，按 `Retry-After` 秒数用原键重试 |
| token 在执行中被撤销 | `403 scope_revoked`（直记） | 停止并告知用户重新授权 |

重试总原则：

1. 只有 `retryable=true`（429/503）或**同一 `Idempotency-Key` 的确定性重放**才可重试；其余 4xx 先修正原因。
2. 写操作重试必须复用原 `Idempotency-Key`，否则可能产生第二笔写入。
3. 重试前先用 `GET .../proposals/{id}` 或 `GET .../refresh/{job_id}` 确认上一次结果。
4. 错误响应含 `request_id`，反馈问题时请附带（见 §4）。

> **已知限制**：服务端错误消息（`error.message` / `detail`）目前为中文。英文界面客户端应按 `error.code` 分支展示本地化文案，**不要**匹配或直出 `message`。

---

## 8. 安全与运维

- **独立凭证**：Agent token 与网页登录 token 不能互换。网页 token 调用工具返回 `401`；Agent token 不能调用网页管理接口。
- **默认拒绝**：工具路径由独立中间件先校验 token，再由 scope 依赖授权；管理端点也会自行校验网页 token。
- **仅存摘要**：数据库只保存 SHA-256 摘要和前 12 位前缀，明文只在签发时返回一次。
- **撤销**：设置页可随时撤销；撤销立即生效。建议为每个 Agent 单独签发，便于定位和回收。
- **审计**：签发、撤销、鉴权成功/失败、限流都会写审计日志，只记录 token 前缀，不记录明文或完整响应。
- **网络**：远程访问必须经 HTTPS 反向代理；不要把端口直接暴露到公网。token 泄漏时先撤销再重新签发。
- **范围**：只读 scope 覆盖组合、组合曲线、基准、风险、行业敞口、基金、数据状态、交易流水、自选、提醒与定投计划；写 scope 仅开放自选维护、任务化数据刷新、账本提案、定投计划提案、提醒处理提案与可信单笔直记。账本/定投计划/提醒处理/回填/手动执行提案必须经网页管理员确认；可信直记需显式签发 `transactions:create`，仅在单笔/每日额度内直接写入普通买入/卖出，预检异常时降级为提案或拒绝，不能修改/删除/转换/定投；`transactions:propose` 另含两个只读预检工具（CSV/条目交易预检与持仓对账预检），受写总闸约束、不写账本，仅返回报告供确认后再提交提案。设置、导入导出与资金划转接口不会开放给 Agent token。

---

## 9. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-27 | 首批 4 个只读工具上线：`portfolio-summary`、`data-status`、`positions`、`funds/{code}` |
| 2026-10-27 | 新增 `portfolio-health`：四维体检、风险提示、结构建议与 `data_quality` 降级说明 |
| 2026-10-27 | 新增 `returns`：组合级/单基金级收益分解与 XIRR |
| 2026-10-27 | 新增 `funds/compare`：最多 20 只基金的收益、风险、费率与相关性对比 |
| 2026-10-27 | 新增 4 个数据类只读 scope 与 6 个工具：`transactions`、`transactions/{tx_id}`、`watchlist`、`alerts`、`auto-invest-plans`、`capabilities`；新 scope 默认不勾选 |
| 2026-10-28 | 新增 4 个组合级只读工具：`portfolio-curve`、`benchmark`、`risk-report`、`industry-exposure`，复用 `portfolio:read`/`health:read`，不新增 scope |
| 2026-10-28 | 新增 2 个基金检索工具：`search`（关键词检索）、`screen`（类型/板块/关键词筛选，可选限量指标），复用 `funds:read`；引入按路由覆盖的限流 |
| 2026-10-28 | 新增只读定投回测工具 `backtest/dca`（`POST`，复用 `funds:read`）：数据准备与计算解耦，不写正式净值表；统一估值日与 XIRR 终值日，显式标注数据不足、部分覆盖与费率未知 |
| 2026-10-30 | 新增 `transactions:propose` scope 与 4 个账本提案工具：Agent 只能提交待审批提案，管理员在网页批准后由服务端同事务写入账本并审计；首期仅开放 `add_transaction`，提案默认 7 天过期、幂等创建、按 token 隔离 |
| 2026-10-30 | D：新增任务化数据刷新（`data:refresh` scope，默认关闭）：`POST refresh` 返回 `202` + `job_id`，`GET refresh/{job_id}` 轮询进度与结果；仅更新净值/元数据，不回填交易净值、不执行定投；与网页/调度器共用互斥锁，占用时返回 `409 refresh_busy`；幂等创建，重启把遗留任务标为 `interrupted` |
| 2026-10-31 | 新增 `transactions:create` scope 与 `record_transaction` 工具（F0 可信单笔直记）：限额内直接写入 buy/sell，预检异常降级为提案或稳定报错；新增 `transactions.source` 列与 3 个审计标签，备份兼容旧 v2 列变体 |
| 2026-10-31 | F1：`create_operation_proposal` 新增 `update_transaction`/`delete_transaction` 两种 operation_type，携带 `expected_digest`（行内容 SHA-256）作目标行版本前置；转换腿单腿修改/删除被拒，份额连带在执行期阻断；`GET transactions/{tx_id}` 新增 `row_digest` 字段 |
| 2026-10-31 | F2：新增 `add_conversion`/`delete_conversion` 提案（转换双腿原子写入；按 `conversion_id` 整对删除并校验两腿 `expected_digest`），`add_transaction` 支持可选 `dividend_alert_id` 原子关联分红提醒；均复用 `transactions:propose`，新增对应错误码与审计标签 |
| 2026-11-01 | F3：新增 `precheck_transactions`/`precheck_reconciliation` 两个只读预检工具（复用 `transactions:propose`，受写总闸约束、限流 10 次/分钟）：交易预检支持 CSV 文本或条目数组，逐条做基金识别（查账本 `funds` 表）、字段校验与重复检测；对账预检先做基金识别 + `shares` 校验，合法条目复用 `reconcile_holdings` 生成差额与建议交易。均不写账本、不联网、不创建提案 |
| 2026-11-01 | F3 加固：`fund_name` 改为只查账本已收录基金（离线、与提案收录要求一致）；命中他人待审提案只判重复不返回 `proposal_id`（新增 `own`）；对账 `maybe_sold` 不再标记可提案并附 `absent_from_input`，被剔除条目不再生成清仓建议；`channel` 增加 50 字符上限；CSV `parse_errors` 补行号；预检成功写审计（仅计数/格式/渠道） |
| 2026-11-02 | F4：新增 `batch_import` operation_type（复用 `transactions:propose`），单提案最多 50 条追加交易、单次审批、单事务原子写入；创建期逐条校验并硬拒绝字段错误/未收录/批内重复，与账本或待审提案重复仅 warning；审批期先整体校验（基金仍在、参数合法、按渠道最终累计余额批内累加后非负）再写入，任一条失败整批回滚并标记 `conflict`；不支持 `dividend_alert_id`，`clear_existing`/`fetch_meta` 忽略并 warning |
| 2026-11-02 | F5：新增 `plans:propose` scope 与四种定投计划维护 operation_type（`create_plan`/`update_plan`/`toggle_plan`/`delete_plan`），与 `transactions:propose` 域对称、独立签发；提案工具（`create`/`list`/`get`/`cancel`）改为双域授权（任一 scope 进入、按 `operation_type` 精确复核、`capabilities` 任一命中即列出）。计划操作永不写 transactions 表、不触发调度器执行；新计划强制停用，启停必须走独立 `toggle_plan`；`update`/`toggle`/`delete` 用 `expected_digest`（计划配置摘要，覆盖 `fund_code/amount/cadence/day_of_week/day_of_month/channel/note/enabled`，排除 `next_run`/`last_run`/`last_tx_id`）做版本前置，目标缺失 `404 target_not_found`、失配 `409 target_changed`。`list_auto_invest_plans` 每项新增 `row_digest` 字段。审计事件与网页对齐（`auto_invest_plan_create/update/toggle/delete`，带 `plan_id`+`proposal_id`） |
| 2026-11-04 | F6.1：新增 `alerts:propose` scope 与 `resolve_alert` operation_type，把 `pending` 提醒推进为 `confirmed`/`ignored`（不支持回滚到 `pending`）；分红可携带已有分红/再投资流水的 `tx_id` 关联，不创建流水。`list_alerts` 每项新增 `row_digest`（覆盖 `status/resolved_at/tx_id` 与业务字段）作 `expected_digest` 版本前置。提案工具改为多域授权（`transactions:propose`/`plans:propose`/`alerts:propose` 任一进入、按 `operation_type` 精确复核、`capabilities` 任一命中即列出）。执行只更新提醒状态并在同一事务写审计（`dividend_alert_update`/`tp_sl_alert_update`，带 `proposal_id`），不写 `transactions` 表 |
| 2026-11-05 | F6.2：新增 `backfill_transaction_navs` operation_type（复用 `transactions:propose`），为 `nav` 缺失的已存在交易补净值及连带份额/金额/手续费，支持 1–50 条显式 `tx_ids` 批量（不做「回填全部」）、逐行 `expected_digest` 版本前置、整批原子。创建期一次性预计算 nav/fee 快照并固化进 `summary_json`（预计算在写事务之外，费率缺失时可能联网一次；审批零联网），分红行 `422 dividend_not_backfillable`、已有净值 `409 nav_present`、无可用净值 `409 nav_unavailable`、费率未知/卖出无买入记录 `409 fee_unknown`（可显式给 `fee`）；审批单事务逐行复读，任一行已回填/已改/已删 → 整批 `conflict`、无部分写入，成功逐行记 `nav_backfill`（带 `proposal_id`）。新增只读工具 `precheck_backfill`（`POST /api/agent/tools/precheck/backfill`，受写总闸与 10 次/分钟限流约束，逐行返回 `row_digest` 与回填快照） |
| 2026-11-07 | F6.3：新增 `execute_plan` operation_type（复用 `transactions:propose`），为一条已存在的定投计划手动生成一笔买入流水并推进 `last_run`/`last_tx_id`；不重算 `next_run`、不触发调度器，网页/调度器既有行为不变。须带计划 `row_digest` 版本前置；金额/渠道/备注/`is_t1`/启停与簿记字段一律硬拒。创建期在写事务外判定可投性并抓取费率（显式 `fee` 跳过；费率未知 `409 fee_unknown`，不静默写 0），`trade_date` 缺省今天、仅允许最近 7 天补记；审批零联网，按快照写 `buy`（`shares/nav` 待回填）。今天靠 `last_run == trade_date` 防重，历史日期另查同一计划+交易日的已成功提案；停用计划仍可手动执行（warning），非交易日仅 warning。审批成功记 `auto_invest_execute`（带 `proposal_id`） |
| 2026-11-14 | R5：回测任务化——`backtest/dca` 由同步 `200` 改为 **`202` + `job_id`**（破坏性变更，客户端需改为轮询 `get_job_status`），复用 `refresh_jobs`（新增 `job_type="dca_backtest"`）与幂等记录，必带 `Idempotency-Key`；后台按基金逐个执行推进进度（`done` 为已完成数、`current` 为正在执行的基金），并发满返回 `429 backtest_busy`（`Retry-After: 60`，未建任务可用原键重试）；`get_job_status` 以 `data:refresh`/`funds:read` 任一进入并按 `job_type` 精确复核；MCP `run_dca_backtest` 新增必填 `idempotency_key`。网页同步回测端点不变 |
