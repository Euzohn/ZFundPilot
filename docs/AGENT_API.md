# ZFundPilot Agent 只读 API

本文档面向想让 AI Agent（Claude Desktop、Cursor、自建 MCP Server、脚本等）读取 ZFundPilot 组合数据的用户。

Agent 接口只读，**不提供任何交易、设置、导入导出或资金操作**。它使用独立于网页登录的 Agent token，按 scope 授权、默认拒绝、可随时撤销。

> English version: [AGENT_API_EN.md](./AGENT_API_EN.md)

---

## 1. 前置条件

- 实例已启用管理员密码认证（`AUTH_ENABLED=True`）。无密码模式下**不能签发、也不能使用** Agent token。
- 默认部署仅监听本机或受控反向代理；远程访问请使用 HTTPS。
- Agent token 只能放在 `Authorization` 请求头里，**不要**放进 URL、浏览器前端持久存储或模型提示词。

---

## 2. 签发与管理 token

在网页端 **设置 → 账户与安全 → Agent 访问令牌** 中签发。明文只显示一次，关闭页面后无法再次查看；服务端只保存 SHA-256 摘要。

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
| `scopes` | string[] | 否 | 默认 `portfolio:read` / `funds:read` / `health:read` 三个；新增的数据类 scope 需显式勾选；未知或写 scope 会被拒绝 |
| `expires_in_days` | int \| null | 否 | 1–3650 天，默认 90；传 `null` 表示不过期 |

---

## 3. Scope 一览

| Scope | 允许的工具 |
|---|---|
| `portfolio:read` | `portfolio-summary`、`positions`、`returns`、`portfolio-curve`、`benchmark`、`industry-exposure` |
| `funds:read` | `funds/{code}`、`funds/compare`、`search`、`screen`、`backtest/dca` |
| `health:read` | `data-status`、`portfolio-health`、`risk-report` |
| `transactions:read` | `transactions`、`transactions/{tx_id}` |
| `watchlist:read` | `watchlist` |
| `alerts:read` | `alerts` |
| `plans:read` | `auto-invest-plans` |

没有写 scope。调用未授权工具返回 **403**。

`capabilities` 只要求有效 token，不要求特定 scope；它只返回当前 token 已获授权的工具。

> 前三个 scope 是签发页面的默认勾选项；`transactions:read`、`watchlist:read`、`alerts:read`、`plans:read` 默认不勾选，需要读取对应数据时请显式勾选，避免存量流程静默扩权。

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
  "generated_at": "2026-10-27T21:30:00+08:00",
  "currency": "CNY",
  "data": { }
}
```

- `schema_version`：响应结构版本，当前为 `1`；新增字段不改版本，破坏性变更才递增。
- `tool`：工具名，与端点对应。
- `generated_at`：服务端生成时间（含时区）。
- `currency`：金额币种，当前固定 `CNY`。
- `data`：工具具体数据。

### 错误响应

使用标准 FastAPI 错误结构：

```json
{ "detail": "Agent token 缺少权限：funds:read" }
```

| 状态码 | 含义 |
|---|---|
| `400` | 参数不合法（如基金代码不是 6 位数字） |
| `401` | 缺少 token，或 token 无效 / 已过期 / 已撤销 |
| `403` | token 有效但缺少所需 scope；或实例未启用密码认证 |
| `404` | 工具或基金不存在（带有效 token 时） |
| `429` | 超过限流阈值，响应头含 `Retry-After` |

> `/api/agent/tools/*` 由独立的 Agent 鉴权中间件保护：即使访问一个不存在的工具路径，没有有效 token 也会先返回 `401`，不会暴露路由是否存在。

### 限流

每个 token、每个端点默认 **120 次/分钟**。路径参数按同一端点计（例如不同基金代码共用 `funds/{code}` 的额度），避免通过枚举代码绕过限流。较重端点使用更低限额：`search` 为 60 次/分钟，`screen`、`backtest/dca`、`benchmark`、`industry-exposure` 为 20 次/分钟；筛选无论是否补指标都共用同一个桶，切换参数不能绕过。超限返回 `429`，并按 `Retry-After` 秒数重试。限流与指标增强的并发上限都是**进程内**状态，多 worker 部署时各进程独立计数。

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

## 5. 工具列表

除 5.20 使用 `POST` 外，其余工具均为 `GET`。所有工具都只读，不接受交易、设置或导出操作。

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

`data` 公共字段：`scope`（`portfolio` / `fund`）、`valuation_basis`（固定 `latest_formal_nav`）、`as_of_date`、`as_of_date_semantics`。

组合级另有：

| 字段 | 说明 |
|---|---|
| `total_return` / `annualized_return` | 累计浮动收益率 / XIRR 年化（可能为 `null`） |
| `total_pnl` / `unrealized_pnl` / `realized_pnl` | 总 / 浮动 / 已实现盈亏 |
| `daily` / `week` / `month` / `year` | 各周期 `{pnl, return}` |
| `holding_count` | 当前持仓基金数 |

单基金级另有：

| 字段 | 说明 |
|---|---|
| `fund_code` / `fund_name` | 基金标识 |
| `market_value` / `total_cost` | 市值 / 持仓成本 |
| `unrealized_pnl` / `realized_pnl` / `total_pnl` | 盈亏 |
| `return_rate` / `annualized_return` | 累计收益率 / XIRR 年化 |
| `transaction_count` | 交易笔数 |
| `buy_amount` / `sell_amount` / `dividend_amount` | 累计买入 / 卖出 / 分红金额 |
| `channels` | 各渠道持仓：`channel`、`market_value`、`total_cost`、`unrealized_pnl`、`return_rate`、`annualized_return` |

> `annualized_return` 使用 XIRR（按实际现金流日期），分批发入时比简单收益率更可靠；数据不足时返回 `null`。

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

单笔交易详情，scope：`transactions:read`。字段与 5.8 的单项一致，另在 `data` 顶层附带 `valuation_basis`；id 不存在返回 `404`。

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

每条提醒只返回白名单字段：`id`、`alert_type`、`fund_code`、`fund_name`、`status`、`triggered_return`、`threshold`、`record_date`、`ex_date`、`pay_date`、`per_share`、`estimated_amount`、`held_shares`、`dividend_method`、`created_at`、`resolved_at`、`tx_id`。

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

在历史净值上模拟定投，可选一次性投入对照，scope：`funds:read`。这是**只读历史模拟**：不会写入正式净值表、交易、定投计划、自选或基金元数据，也不代表未来收益或配置建议。

请求体（JSON；未知字段、类型错误或约束不满足返回 `422`）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `fund_codes` | string[] | 必填 | 1–5 个 6 位代码；重复代码去重后逐基金独立模拟 |
| `start_date` / `end_date` | string | 必填 | 严格 `YYYY-MM-DD`；起日早于止日；止日不晚于中国时区今日 |
| `amount_per_period` | number | 必填 | 每只基金每期金额，有限正数，≤ 1,000,000 |
| `cadence` | string | `month` | `month` / `week` / `biweek` |
| `include_lumpsum` | bool | `true` | 每只基金增加一个等实际总投入的一次性投入对照 |
| `include_curve` | bool | `true` | 是否返回曲线；`false` 时曲线为空 |
| `include_periods` | bool | `false` | 是否返回逐期买入明细（响应体更大） |
| `max_points` | int | `365` | 曲线等距抽样上限，10–2000，保留首尾 |

区间最长 10 年；月/双周/周的计划期数最多分别约为 120/261/522。非法 JSON、缺少必填字段或未知字段返回 `422`；认证与 scope 语义与其他工具一致（`401`/`403`）。

`data` 字段：`ok`、`message`、`simulation_note`、`requested`、`fund_count`、`result_count`、`failed_count`、`results[]`。`failed_count` 按结果条数计（同一基金的 `dca` 与 `lumpsum` 各自计一条）。

每条结果包含：

- 基础：`fund_code`、`fund_name`、`strategy`（`dca`/`lumpsum`）、`status`（`ok`/`partial`/`failed`）、`code`、`message`。
- 数据：`data_source`（`database`/`remote`/`database+remote`/`none`）、`data_start`、`data_end`、`valuation_date`、`skipped_periods`、`fee_ok`。
- 指标：`cadence`、`amount_per_period`、`total_periods`、`invested_capital`、`total_fees`、`final_value`、`redemption_fee`、`net_final_value`、`total_return`、`annualized_return`、`max_drawdown`、`sharpe_ratio`。
- 明细：`curve`（按 `max_points` 抽样）、`curve_points`、`periods_detail`（仅在 `include_periods=true` 时非空）、`periods_detail_count`、`caveats`。
- `fee_ok=false` 表示费率表获取失败；即使 `fee_ok=true`，若申购或赎回档位缺失也会按 0 计并在 `caveats` 说明，不应解读为真实零费率。
- `status="failed"` 时 `code` 为 `insufficient_nav`（有效净值少于 2 个）或 `no_periods`（没有可执行的计划扣款日），不输出看似有效的零收益指标。
- `status="partial"` 且 `code="partial_coverage"` 表示部分计划期因净值未覆盖或与其他期落在同一净值日而跳过；`skipped_periods` 给出数量。

> 计划扣款日不早于请求起日。多个计划期落到同一净值日时只执行第一期，避免把多期投入堆到同一天。期末估值、赎回费持有天数与 XIRR 终值统一使用最后一个可用净值日（`valuation_date`），而不是请求止日。净值优先读取数据库，覆盖不足时通过外部接口在内存中补齐，不写库；`data_end` 可能早于 `end_date`。费率表按每只基金一次快照使用。结果未模拟分红、拆分与红利再投资；最大回撤与夏普基于市值曲线，定投现金流会影响可比性。单次请求最多 5 只基金，耗时受外部净值/费率抓取影响，建议先查 `data-status`，并遵守 20 次/分钟的限额。回测并发上限为 2（进程内），满额立即返回 `429`，不排队；多 worker 部署时各进程独立计数。

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

也可以用任意 HTTP 工具封装上述 20 个端点；仓库同时提供可选的 MCP 适配层（见本节末尾）。建议在 Agent 侧把 `data-status` 作为每次分析前的必查项，避免基于过期净值下结论。

---

### MCP 适配层（可选）

仓库内置一个 stdio MCP 桥接，把上述 20 个工具封装成 MCP 工具，供 Claude Desktop、Cursor 等客户端直接调用。它只是带 Agent token 的 HTTP 客户端，不访问数据库，鉴权、scope 与限流完全复用 HTTP 入口。

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

暴露的 MCP 工具：`get_portfolio_summary`、`get_data_status`、`list_positions`、`get_fund_detail`、`get_portfolio_health`、`get_returns`、`compare_funds`、`list_transactions`、`get_transaction`、`list_watchlist`、`list_alerts`、`list_auto_invest_plans`、`get_portfolio_curve`、`get_benchmark_comparison`、`get_risk_report`、`get_industry_exposure`、`search_funds`、`screen_funds`、`run_dca_backtest`、`get_agent_capabilities`。

- `ZFUNDPILOT_BASE_URL` 默认 `http://127.0.0.1:8000`；ZFundPilot 跑在 NAS/Docker 时改成实际地址，远程访问请用 HTTPS。
- `ZFUNDPILOT_TIMEOUT` 可选，默认 30 秒，范围 1–120。
- token 只从环境变量读取，不写入配置仓库或提示词；泄漏后立即在设置页撤销。

## 7. 安全与运维

- **独立凭证**：Agent token 与网页登录 token 不能互换。网页 token 调用工具返回 `401`；Agent token 不能调用网页管理接口。
- **默认拒绝**：工具路径由独立中间件先校验 token，再由 scope 依赖授权；管理端点也会自行校验网页 token。
- **仅存摘要**：数据库只保存 SHA-256 摘要和前 12 位前缀，明文只在签发时返回一次。
- **撤销**：设置页可随时撤销；撤销立即生效。建议为每个 Agent 单独签发，便于定位和回收。
- **审计**：签发、撤销、鉴权成功/失败、限流都会写审计日志，只记录 token 前缀，不记录明文或完整响应。
- **网络**：远程访问必须经 HTTPS 反向代理；不要把端口直接暴露到公网。token 泄漏时先撤销再重新签发。
- **范围**：只读 scope 覆盖组合、组合曲线、基准、风险、行业敞口、基金、数据状态、交易流水、自选、提醒与定投计划；写操作和导出接口不会开放给 Agent token。

---

## 8. 变更记录

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
