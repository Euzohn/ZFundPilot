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

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 1–64 字符，用于区分调用方 |
| `scopes` | string[] | 否 | 默认全部三个只读 scope；未知或写 scope 会被拒绝 |
| `expires_in_days` | int \| null | 否 | 1–3650 天，默认 90；传 `null` 表示不过期 |

---

## 3. Scope 一览

| Scope | 允许的工具 |
|---|---|
| `portfolio:read` | `portfolio-summary`、`positions` |
| `funds:read` | `funds/{code}` |
| `health:read` | `data-status`、`portfolio-health` |

没有写 scope。调用未授权工具返回 **403**。

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

每个 token、每个端点 **120 次/分钟**。超限返回 `429`，并按 `Retry-After` 秒数重试。

### 估值口径

持仓与基金详情中的金额基于**最新正式净值**，并在 `data.valuation_basis` 标注 `"latest_formal_nav"`。

- `as_of_date` 是各持仓正式净值日期的**最大值**，不代表所有基金都已更新。
- 接口**不返回**盘中实时估值，避免与正式净值混淆。数据完整性请调用 `data-status`。

---

## 5. 工具列表

### 5.1 `GET /api/agent/tools/portfolio-summary`

组合层面汇总，scope：`portfolio:read`。

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  http://localhost:8000/api/agent/tools/portfolio-summary | jq
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
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  http://localhost:8000/api/agent/tools/data-status | jq
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
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  "http://localhost:8000/api/agent/tools/positions?limit=50" | jq
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
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  "http://localhost:8000/api/agent/tools/funds/005827?nav_limit=10" | jq
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
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  http://localhost:8000/api/agent/tools/portfolio-health | jq
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

## 6. 最小接入示例

### Python

```python
import os
import requests

BASE = os.getenv("ZFUND_BASE_URL", "http://localhost:8000")
TOKEN = os.environ["ZFUND_AGENT_TOKEN"]  # 不要写进代码或提示词

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

也可以用任意 HTTP 工具封装上述 5 个端点；仓库同时提供可选的 MCP 适配层（见本节末尾）。建议在 Agent 侧把 `data-status` 作为每次分析前的必查项，避免基于过期净值下结论。

---

### MCP 适配层（可选）

仓库内置一个 stdio MCP 桥接，把上述 5 个工具封装成 MCP 工具，供 Claude Desktop、Cursor 等客户端直接调用。它只是带 Agent token 的 HTTP 客户端，不访问数据库，鉴权、scope 与限流完全复用 HTTP 入口。

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

暴露的 MCP 工具：`get_portfolio_summary`、`get_data_status`、`list_positions`、`get_fund_detail`、`get_portfolio_health`。

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
- **范围**：首期只读 scope 仅覆盖组合、基金、数据状态；写操作和导出接口不会开放给 Agent token。

---

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-27 | 首批 4 个只读工具上线：`portfolio-summary`、`data-status`、`positions`、`funds/{code}` |
| 2026-10-27 | 新增 `portfolio-health`：四维体检、风险提示、结构建议与 `data_quality` 降级说明 |
