# ZFundPilot Agent 接口联调测试报告

本报告由一次性 HTTP 客户端脚本对已部署实例重放测试生成，包含每个用例的完整响应体。**不在本地运行应用或测试。**

- 目标站点：`http://<YOUR_SERVER_IP>:8001`
- 令牌：`zfag_FK7rnym…（已脱敏）`（仅只读脱敏展示）
- 生成时间：2026-11-04 00:10:35
- 说明：写/提案类用例均为**可逆**操作（创建后取消）；自查预检不写库；直记仅使用非法/未收录基金做门控探针，**未向真实账本写入任何交易**。

---

## 0. 能力发现（含写总闸状态）

### get_agent_capabilities

- 请求：`GET /api/agent/tools/capabilities`
- 响应 HTTP：**200**
- 说明：server_version=0.25.0，write_enabled=True，write_locked=False，granted_scopes=['alerts:read', 'data:refresh', 'funds:read', 'health:read', 'plans:propose', 'plans:read', 'portfolio:read', 'transactions:create', 'transactions:propose', 'transactions:read', 'watchlist:read', 'watchlist:write']
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_agent_capabilities",
  "generated_at": "2026-11-04T00:10:35.956588+08:00",
  "currency": "CNY",
  "data": {
    "server_version": "0.25.0",
    "schema_version": 1,
    "granted_scopes": [
      "alerts:read",
      "data:refresh",
      "funds:read",
      "health:read",
      "plans:propose",
      "plans:read",
      "portfolio:read",
      "transactions:create",
      "transactions:propose",
      "transactions:read",
      "watchlist:read",
      "watchlist:write"
    ],
    "write_enabled": true,
    "write_locked": false,
    "currency": "CNY",
    "tools": [
      {
        "name": "get_portfolio_summary",
        "method": "GET",
        "path": "/api/agent/tools/portfolio-summary",
        "scope": "portfolio:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_data_status",
        "method": "GET",
        "path": "/api/agent/tools/data-status",
        "scope": "health:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_portfolio_health",
        "method": "GET",
        "path": "/api/agent/tools/portfolio-health",
        "scope": "health:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "list_positions",
        "method": "GET",
        "path": "/api/agent/tools/positions",
        "scope": "portfolio:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_returns",
        "method": "GET",
        "path": "/api/agent/tools/returns",
        "scope": "portfolio:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "compare_funds",
        "method": "GET",
        "path": "/api/agent/tools/funds/compare",
        "scope": "funds:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_fund_detail",
        "method": "GET",
        "path": "/api/agent/tools/funds/{code}",
        "scope": "funds:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "list_transactions",
        "method": "GET",
        "path": "/api/agent/tools/transactions",
        "scope": "transactions:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_transaction",
        "method": "GET",
        "path": "/api/agent/tools/transactions/{tx_id}",
        "scope": "transactions:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "list_watchlist",
        "method": "GET",
        "path": "/api/agent/tools/watchlist",
        "scope": "watchlist:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "list_alerts",
        "method": "GET",
        "path": "/api/agent/tools/alerts",
        "scope": "alerts:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "list_auto_invest_plans",
        "method": "GET",
        "path": "/api/agent/tools/auto-invest-plans",
        "scope": "plans:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_portfolio_curve",
        "method": "GET",
        "path": "/api/agent/tools/portfolio-curve",
        "scope": "portfolio:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_benchmark_comparison",
        "method": "GET",
        "path": "/api/agent/tools/benchmark",
        "scope": "portfolio:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_risk_report",
        "method": "GET",
        "path": "/api/agent/tools/risk-report",
        "scope": "health:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_industry_exposure",
        "method": "GET",
        "path": "/api/agent/tools/industry-exposure",
        "scope": "portfolio:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "search_funds",
        "method": "GET",
        "path": "/api/agent/tools/search",
        "scope": "funds:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "screen_funds",
        "method": "GET",
        "path": "/api/agent/tools/screen",
        "scope": "funds:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "run_dca_backtest",
        "method": "POST",
        "path": "/api/agent/tools/backtest/dca",
        "scope": "funds:read",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_agent_capabilities",
        "method": "GET",
        "path": "/api/agent/tools/capabilities",
        "scope": null,
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "add_watchlist_item",
        "method": "POST",
        "path": "/api/agent/tools/watchlist",
        "scope": "watchlist:write",
        "risk": "write",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "update_watchlist_item",
        "method": "PATCH",
        "path": "/api/agent/tools/watchlist/{code}",
        "scope": "watchlist:write",
        "risk": "write",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "remove_watchlist_item",
        "method": "DELETE",
        "path": "/api/agent/tools/watchlist/{code}",
        "scope": "watchlist:write",
        "risk": "write",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "start_data_refresh",
        "method": "POST",
        "path": "/api/agent/tools/refresh",
        "scope": "data:refresh",
        "risk": "write",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_job_status",
        "method": "GET",
        "path": "/api/agent/tools/refresh/{job_id}",
        "scope": "data:refresh",
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "create_operation_proposal",
        "method": "POST",
        "path": "/api/agent/tools/proposals",
        "any_of_scopes": [
          "transactions:propose",
          "plans:propose"
        ],
        "risk": "propose",
        "requires_confirmation": true,
        "enabled": true
      },
      {
        "name": "record_transaction",
        "method": "POST",
        "path": "/api/agent/tools/transactions",
        "scope": "transactions:create",
        "risk": "write",
        "requires_confirmation": false,
        "fallback_tool": "create_operation_proposal",
        "enabled": true
      },
      {
        "name": "list_operation_proposals",
        "method": "GET",
        "path": "/api/agent/tools/proposals",
        "any_of_scopes": [
          "transactions:propose",
          "plans:propose"
        ],
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "get_operation_proposal",
        "method": "GET",
        "path": "/api/agent/tools/proposals/{proposal_id}",
        "any_of_scopes": [
          "transactions:propose",
          "plans:propose"
        ],
        "risk": "read",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "cancel_operation_proposal",
        "method": "DELETE",
        "path": "/api/agent/tools/proposals/{proposal_id}",
        "any_of_scopes": [
          "transactions:propose",
          "plans:propose"
        ],
        "risk": "write",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "precheck_transactions",
        "method": "POST",
        "path": "/api/agent/tools/precheck/transactions",
        "scope": "transactions:propose",
        "risk": "propose",
        "requires_confirmation": false,
        "enabled": true
      },
      {
        "name": "precheck_reconciliation",
        "method": "POST",
        "path": "/api/agent/tools/precheck/reconciliation",
        "scope": "transactions:propose",
        "risk": "propose",
        "requires_confirmation": false,
        "enabled": true
      }
    ]
  }
}
```

## 1. 只读接口

### get_data_status

- 请求：`GET /api/agent/tools/data-status`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_data_status",
  "generated_at": "2026-11-04T00:10:36.387203+08:00",
  "currency": "CNY",
  "data": {
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "missing_nav_fund_count": 0,
    "stale_nav_fund_count": 5,
    "pending_t1_transaction_count": 0
  }
}
```

### get_portfolio_summary

- 请求：`GET /api/agent/tools/portfolio-summary`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_portfolio_summary",
  "generated_at": "2026-11-04T00:10:36.621853+08:00",
  "currency": "CNY",
  "data": {
    "total_cost": 88621.60207701458,
    "total_value": 112365.57402900002,
    "unrealized_pnl": 23743.9719519854,
    "realized_pnl": 5831.602077014593,
    "total_pnl": 29575.574028999996,
    "total_return": 0.2679253296656867,
    "annualized_return": 0.14586200133086402,
    "total_buy": 99200.0,
    "total_sell": 15190.0,
    "total_dividend": 1362.0,
    "holding_count": 13,
    "max_single_weight": 0.1756004771257395,
    "max_single_name": "博时黄金ETF联接A",
    "as_of_date": "2026-11-03",
    "daily_pnl": -613.44,
    "daily_return": -0.005429698210987388,
    "week_pnl": -278.1,
    "week_return": -0.0024710137988771825,
    "month_pnl": -278.1,
    "month_return": -0.0024710137988771825,
    "year_pnl": -10406.18,
    "year_return": -0.09082671820066698,
    "data_status": {
      "missing_nav_fund_count": 0,
      "stale_nav_fund_count": 5,
      "pending_t1_transaction_count": 0
    }
  }
}
```

### get_portfolio_health

- 请求：`GET /api/agent/tools/portfolio-health`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_portfolio_health",
  "generated_at": "2026-11-04T00:10:36.866470+08:00",
  "currency": "CNY",
  "data": {
    "overall_score": 78,
    "overall_tier": "good",
    "dimensions": [
      {
        "name": "allocation",
        "score": 100,
        "status": "good",
        "metrics": {
          "max_single_weight": 0.1756004771257395,
          "max_single_name": "博时黄金ETF联接A",
          "hhi": 0.10146205483130442,
          "equity_weight": 0.754842197487547,
          "bond_weight": 0.12991401599775113,
          "qdii_weight": 0.08648200379853015,
          "holding_count": 13
        }
      },
      {
        "name": "risk",
        "score": 60,
        "status": "warning",
        "metrics": {
          "max_drawdown": -0.1943877817025733,
          "volatility": 0.5775420941622975
        }
      },
      {
        "name": "liquidity",
        "score": 75,
        "status": "good",
        "metrics": {
          "stable_weight": 0.12991401599775113,
          "volatile_weight": 0.8700859840022489,
          "holding_count": 13,
          "max_single_weight": 0.1756004771257395
        }
      },
      {
        "name": "return",
        "score": 80,
        "status": "good",
        "metrics": {
          "annualized_return": 0.14586200133086402,
          "total_return": 0.2679253296656867,
          "real_return": 0.2540210443586206,
          "cpi_inflation": 0.013904285307066111
        }
      }
    ],
    "stable_weight": 0.12991401599775113,
    "volatile_weight": 0.8700859840022487,
    "risk_report": {
      "max_drawdown": -0.1943877817025733,
      "volatility": 0.5775420941622975,
      "max_single_weight": 0.1756004771257395,
      "max_single_name": "博时黄金ETF联接A",
      "hhi": 0.10146205483130442,
      "equity_weight": 0.754842197487547,
      "bond_weight": 0.12991401599775113,
      "qdii_weight": 0.08648200379853015,
      "flags": [
        {
          "level": "warning",
          "code": "equity_heavy",
          "params": {
            "weight": 0.754842197487547,
            "threshold": 0.7
          },
          "title": "权益/成长风格偏重",
          "detail": "权益类资产占比 75.5%，超过 70%，组合波动可能较大。"
        },
        {
          "level": "danger",
          "code": "drawdown_high",
          "params": {
            "value": -0.1943877817025733,
            "threshold": -0.15
          },
          "title": "历史回撤较大",
          "detail": "组合最大回撤 -19.4%，低于 -15%，属高风险区间。"
        },
        {
          "level": "info",
          "code": "volatility_high",
          "params": {
            "value": 0.5775420941622975,
            "threshold": 0.25
          },
          "title": "波动率偏高",
          "detail": "组合年化波动率约 57.8%，超过 25%。"
        }
      ]
    },
    "advice": [
      {
        "code": "equity_heavy",
        "params": {
          "weight": 0.754842197487547,
          "threshold": 0.7
        },
        "category": "结构",
        "text": "权益类资产占比 75.5%，组合偏成长/进攻；若希望降低波动，可提高债券等低波动资产比例。"
      }
    ],
    "summary": {
      "total_cost": 88621.60207701458,
      "total_value": 112365.57402900002,
      "unrealized_pnl": 23743.9719519854,
      "realized_pnl": 5831.602077014593,
      "total_pnl": 29575.574028999996,
      "total_return": 0.2679253296656867,
      "annualized_return": 0.14586200133086402,
      "total_buy": 99200.0,
      "total_sell": 15190.0,
      "total_dividend": 1362.0,
      "holding_count": 13,
      "max_single_weight": 0.1756004771257395,
      "max_single_name": "博时黄金ETF联接A",
      "as_of_date": "2026-11-03",
      "daily_pnl": -613.44,
      "daily_return": -0.005429698210987388,
      "week_pnl": -278.1,
      "week_return": -0.0024710137988771825,
      "month_pnl": -278.1,
      "month_return": -0.0024710137988771825,
      "year_pnl": -10406.18,
      "year_return": -0.09082671820066698,
      "data_status": {
        "missing_nav_fund_count": 0,
        "stale_nav_fund_count": 5,
        "pending_t1_transaction_count": 0
      }
    },
    "valuation_basis": "latest_formal_nav",
    "data_quality": {
      "as_of_date": "2026-11-03",
      "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
      "missing_nav_fund_count": 0,
      "stale_nav_fund_count": 5,
      "pending_t1_transaction_count": 0,
      "caveats": [
        "5 只基金的最新正式净值可能已过期"
      ]
    }
  }
}
```

### list_positions（limit=2）

- 请求：`GET /api/agent/tools/positions?limit=2`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_positions",
  "generated_at": "2026-11-04T00:10:37.110993+08:00",
  "currency": "CNY",
  "data": {
    "count": 2,
    "total": 15,
    "limit": 2,
    "include_closed": false,
    "valuation_basis": "latest_formal_nav",
    "positions": [
      {
        "fund_code": "002610",
        "fund_name": "博时黄金ETF联接A",
        "fund_type": "指数型",
        "sector": "黄金",
        "channel": "招商银行",
        "tracking_index": "黄金",
        "risk_level": "中高风险",
        "held_shares": 7251.01,
        "total_cost": 8000.0,
        "pending_buy_cost": 0.0,
        "avg_cost_nav": 1.1032945755143075,
        "latest_nav": 2.7212,
        "latest_date": "2026-11-02",
        "market_value": 19731.448412,
        "unrealized_pnl": 11731.448412000002,
        "realized_pnl": 0.0,
        "return_rate": 1.4664310515000003,
        "annualized_return": 0.6849436698143729,
        "weight": 0.1756004771257395,
        "buy_count": 2,
        "sell_count": 0,
        "dividend_count": 0,
        "dividend_total": 0.0,
        "total_pnl": 11731.448412000002,
        "is_open": true
      },
      {
        "fund_code": "110027",
        "fund_name": "易方达安心回报债券A",
        "fund_type": "债券型",
        "sector": "其它",
        "channel": "支付宝",
        "tracking_index": "",
        "risk_level": "中风险",
        "held_shares": 7142.86,
        "total_cost": 10000.0,
        "pending_buy_cost": 0.0,
        "avg_cost_nav": 1.399999440000224,
        "latest_nav": 2.0437,
        "latest_date": "2026-11-03",
        "market_value": 14597.862981999999,
        "unrealized_pnl": 4597.862981999999,
        "realized_pnl": 620.0,
        "return_rate": 0.45978629819999983,
        "annualized_return": 0.1975292318791316,
        "weight": 0.12991401599775118,
        "buy_count": 1,
        "sell_count": 0,
        "dividend_count": 2,
        "dividend_total": 620.0,
        "total_pnl": 5217.862981999999,
        "is_open": true
      }
    ]
  }
}
```

### get_returns（组合）

- 请求：`GET /api/agent/tools/returns`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_returns",
  "generated_at": "2026-11-04T00:10:37.350771+08:00",
  "currency": "CNY",
  "data": {
    "scope": "portfolio",
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "valuation_basis": "latest_formal_nav",
    "return_basis": "open_positions_floating",
    "return_basis_note": "total_return/return_rate 与各周期 return 只基于当前开仓成本与最新正式净值，不是历史累计收益；已清仓基金的历史已实现盈亏只计入 realized_pnl 与 XIRR。",
    "realized_pnl_scope": "all_history_including_closed",
    "total_pnl_scope": "unrealized_open_plus_realized_all_history",
    "total_cost": 88621.60207701458,
    "total_value": 112365.57402900002,
    "total_return": 0.2679253296656867,
    "annualized_return": 0.14586200133086402,
    "total_pnl": 29575.574028999996,
    "unrealized_pnl": 23743.9719519854,
    "realized_pnl": 5831.602077014593,
    "daily": {
      "pnl": -613.44,
      "return": -0.005429698210987388
    },
    "week": {
      "pnl": -278.1,
      "return": -0.0024710137988771825
    },
    "month": {
      "pnl": -278.1,
      "return": -0.0024710137988771825
    },
    "year": {
      "pnl": -10406.18,
      "return": -0.09082671820066698
    },
    "holding_count": 13,
    "open_position_count": 15,
    "closed_position_count": 0,
    "data_quality": {
      "missing_nav_fund_count": 0,
      "stale_nav_fund_count": 5,
      "pending_t1_transaction_count": 0,
      "caveats": [
        "5 只基金的最新正式净值可能已过期"
      ]
    }
  }
}
```

### get_portfolio_curve

- 请求：`GET /api/agent/tools/portfolio-curve`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_portfolio_curve",
  "generated_at": "2026-11-04T00:10:37.592280+08:00",
  "currency": "CNY",
  "data": {
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "valuation_basis": "latest_formal_nav",
    "max_points": 365,
    "points_count": 365,
    "points": [
      {
        "date": "2024-06-20",
        "total_value": 13690.719762,
        "invested_cost": 10000.0,
        "total_return": 0.3690719762000001
      },
      {
        "date": "2024-06-24",
        "total_value": 13600.005439999999,
        "invested_cost": 10000.0,
        "total_return": 0.3600005439999998
      },
      {
        "date": "2024-06-25",
        "total_value": 13632.14831,
        "invested_cost": 10000.0,
        "total_return": 0.36321483100000007
      },
      {
        "date": "2024-06-27",
        "total_value": 13670.005468,
        "invested_cost": 10000.0,
        "total_return": 0.36700054679999994
      },
      {
        "date": "2024-06-28",
        "total_value": 13695.005478,
        "invested_cost": 10000.0,
        "total_return": 0.36950054779999997
      },
      {
        "date": "2024-07-01",
        "total_value": 18745.005486,
        "invested_cost": 15000.0,
        "total_return": 0.24966703239999988
      },
      {
        "date": "2024-07-02",
        "total_value": 18824.023344,
        "invested_cost": 15000.0,
        "total_return": 0.2549348896000001
      },
      {
        "date": "2024-07-04",
        "total_value": 18646.523318,
        "invested_cost": 15000.0,
        "total_return": 0.24310155453333326
      },
      {
        "date": "2024-07-08",
        "total_value": 37846.815258,
        "invested_cost": 31000.0,
        "total_return": 0.2208650083225807
      },
      {
        "date": "2024-07-09",
        "total_value": 38019.864665,
        "invested_cost": 31000.0,
        "total_return": 0.22644724725806453
      },
      {
        "date": "2024-07-11",
        "total_value": 44420.562165,
        "invested_cost": 36000.0,
        "total_return": 0.23390450458333345
      },
      {
        "date": "2024-07-12",
        "total_value": 56671.884408,
        "invested_cost": 42000.0,
        "total_return": 0.3493305811428571
      },
      {
        "date": "2024-07-16",
        "total_value": 63141.39873,
        "invested_cost": 48000.0,
        "total_return": 0.3154458068750001
      },
      {
        "date": "2024-07-18",
        "total_value": 63619.916642000004,
        "invested_cost": 48000.0,
        "total_return": 0.32541493004166666
      },
      {
        "date": "2024-07-19",
        "total_value": 63334.321015,
        "invested_cost": 48000.0,
        "total_return": 0.3194650211458334
      },
      {
        "date": "2024-07-23",
        "total_value": 61975.479706,
        "invested_cost": 48000.0,
        "total_return": 0.2911558272083332
      },
      {
        "date": "2024-07-24",
        "total_value": 61793.188092000004,
        "invested_cost": 48000.0,
        "total_return": 0.2873580852500002
      },
      {
        "date": "2024-07-26",
        "total_value": 61263.507292,
        "invested_cost": 48000.0,
        "total_return": 0.27632306858333333
      },
      {
        "date": "2024-07-29",
        "total_value": 61194.138374999995,
        "invested_cost": 48000.0,
        "total_return": 0.2748778828124998
      },
      {
        "date": "2024-07-31",
        "total_value": 61936.180288,
        "invested_cost": 48000.0,
        "total_return": 0.29033708933333346
      },
      {
        "date": "2024-08-02",
        "total_value": 62539.764842000004,
        "invested_cost": 53000.0,
        "total_return": 0.1799955630566039
      },
      {
        "date": "2024-08-05",
        "total_value": 64383.95009,
        "invested_cost": 58000.0,
        "total_return": 0.11006810500000008
      },
      {
        "date": "2024-08-07",
        "total_value": 64832.437511,
        "invested_cost": 58000.0,
        "total_return": 0.11780064674137924
      },
      {
        "date": "2024-08-08",
        "total_value": 64968.06675,
        "invested_cost": 58000.0,
        "total_return": 0.12013908189655176
      },
      {
        "date": "2024-08-12",
        "total_value": 67353.704547,
        "invested_cost": 62000.0,
        "total_return": 0.0863500733387097
      },
      {
        "date": "2024-08-13",
        "total_value": 67369.289128,
        "invested_cost": 62000.0,
        "total_return": 0.08660143754838723
      },
      {
        "date": "2024-08-15",
        "total_value": 66923.0351,
        "invested_cost": 62000.0,
        "total_return": 0.07940379193548375
      },
      {
        "date": "2024-08-19",
        "total_value": 67183.95741100001,
        "invested_cost": 62000.0,
        "total_return": 0.08361221630645188
      },
      {
        "date": "2024-08-20",
        "total_value": 66798.507912,
        "invested_cost": 62000.0,
        "total_return": 0.07739528890322589
      },
      {
        "date": "2024-08-22",
        "total_value": 66530.09169999999,
        "invested_cost": 62000.0,
        "total_return": 0.0730659951612902
      },
      {
        "date": "2024-08-23",
        "total_value": 66562.40447000001,
        "invested_cost": 62000.0,
        "total_return": 0.07358716887096795
      },
      {
        "date": "2024-08-27",
        "total_value": 66365.96815500001,
        "invested_cost": 62000.0,
        "total_return": 0.07041884120967756
      },
      {
        "date": "2024-08-29",
        "total_value": 66273.96841999999,
        "invested_cost": 62000.0,
        "total_return": 0.06893497451612896
      },
      {
        "date": "2024-08-30",
        "total_value": 67210.441054,
        "invested_cost": 62000.0,
        "total_return": 0.08403937183870958
      },
      {
        "date": "2024-09-03",
        "total_value": 66317.572064,
        "invested_cost": 62000.0,
        "total_return": 0.06963825909677435
      },
      {
        "date": "2024-09-04",
        "total_value": 65833.41657100001,
        "invested_cost": 62000.0,
        "total_return": 0.06182929953225824
      },
      {
        "date": "2024-09-06",
        "total_value": 70282.942204,
        "invested_cost": 67000.0,
        "total_return": 0.04899913737313444
      },
      {
        "date": "2024-09-09",
        "total_value": 69578.815681,
        "invested_cost": 67000.0,
        "total_return": 0.03848978628358202
      },
      {
        "date": "2024-09-11",
        "total_value": 73637.222646,
        "invested_cost": 72000.0,
        "total_return": 0.022739203416666687
      },
      {
        "date": "2024-09-13",
        "total_value": 72941.529285,
        "invested_cost": 72000.0,
        "total_return": 0.01307679562499997
      },
      {
        "date": "2024-09-18",
        "total_value": 72885.69967799999,
        "invested_cost": 72000.0,
        "total_return": 0.012301384416666616
      },
      {
        "date": "2024-09-20",
        "total_value": 83052.684885,
        "invested_cost": 77000.0,
        "total_return": 0.07860629720779211
      },
      {
        "date": "2024-09-23",
        "total_value": 83153.175392,
        "invested_cost": 77000.0,
        "total_return": 0.07991136872727278
      },
      {
        "date": "2024-09-25",
        "total_value": 85936.22080000001,
        "invested_cost": 77000.0,
        "total_return": 0.11605481558441566
      },
      {
        "date": "2024-09-27",
        "total_value": 91792.119576,
        "invested_cost": 77000.0,
        "total_return": 0.1921054490389611
      },
      {
        "date": "2024-09-30",
        "total_value": 96479.225303,
        "invested_cost": 77000.0,
        "total_return": 0.2529769519870131
      },
      {
        "date": "2024-10-09",
        "total_value": 95504.54422000001,
        "invested_cost": 77000.0,
        "total_return": 0.2403187561038962
      },
      {
        "date": "2024-10-10",
        "total_value": 96056.624837,
        "invested_cost": 77000.0,
        "total_return": 0.24748863424675327
      },
      {
        "date": "2024-10-14",
        "total_value": 95330.783136,
        "invested_cost": 77000.0,
        "total_return": 0.23806211864935056
      },
      {
        "date": "2024-10-15",
        "total_value": 93633.185927,
        "invested_cost": 77000.0,
        "total_return": 0.21601540164935074
      },
      {
        "date": "2024-10-17",
        "total_value": 92831.931773,
        "invested_cost": 77000.0,
        "total_return": 0.2056095035454546
      },
      {
        "date": "2024-10-21",
        "total_value": 95899.003655,
        "invested_cost": 77000.0,
        "total_return": 0.24544160590909092
      },
      {
        "date": "2024-10-22",
        "total_value": 96196.75713900001,
        "invested_cost": 77000.0,
        "total_return": 0.24930853427272748
      },
      {
        "date": "2024-10-24",
        "total_value": 95837.11663799999,
        "invested_cost": 77000.0,
        "total_return": 0.24463787841558426
      },
      {
        "date": "2024-10-25",
        "total_value": 96091.35545399999,
        "invested_cost": 77000.0,
        "total_return": 0.24793968122077903
      },
      {
        "date": "2024-10-29",
        "total_value": 96401.290524,
        "invested_cost": 77000.0,
        "total_return": 0.251964812
      },
      {
        "date": "2024-10-30",
        "total_value": 95908.352834,
        "invested_cost": 77000.0,
        "total_return": 0.24556302381818185
      },
      {
        "date": "2024-11-01",
        "total_value": 95366.497999,
        "invested_cost": 77000.0,
        "total_return": 0.238525948038961
      },
      {
        "date": "2024-11-05",
        "total_value": 97737.159632,
        "invested_cost": 77000.0,
        "total_return": 0.26931376145454533
      },
      {
        "date": "2024-11-06",
        "total_value": 97386.46697900002,
        "invested_cost": 77000.0,
        "total_return": 0.2647593114155846
      },
      {
        "date": "2024-11-08",
        "total_value": 98509.604768,
        "invested_cost": 77000.0,
        "total_return": 0.2793455164675325
      },
      {
        "date": "2024-11-11",
        "total_value": 99050.77956600001,
        "invested_cost": 77000.0,
        "total_return": 0.2863737605974028
      },
      {
        "date": "2024-11-13",
        "total_value": 97735.91814199998,
        "invested_cost": 77000.0,
        "total_return": 0.26929763820779185
      },
      {
        "date": "2024-11-15",
        "total_value": 95208.69952,
        "invested_cost": 77000.0,
        "total_return": 0.23647661714285717
      },
      {
        "date": "2024-11-18",
        "total_value": 94801.39084000001,
        "invested_cost": 77000.0,
        "total_return": 0.23118689402597403
      },
      {
        "date": "2024-11-20",
        "total_value": 95825.37789399999,
        "invested_cost": 77000.0,
        "total_return": 0.24448542719480515
      },
      {
        "date": "2024-11-21",
        "total_value": 96112.132262,
        "invested_cost": 77000.0,
        "total_return": 0.2482095098961039
      },
      {
        "date": "2024-11-25",
        "total_value": 94004.07036,
        "invested_cost": 77000.0,
        "total_return": 0.2208320825974026
      },
      {
        "date": "2024-11-26",
        "total_value": 93704.58462899999,
        "invested_cost": 77000.0,
        "total_return": 0.2169426575194804
      },
      {
        "date": "2024-11-28",
        "total_value": 94473.880183,
        "invested_cost": 77000.0,
        "total_return": 0.22693350887012986
      },
      {
        "date": "2024-12-02",
        "total_value": 95591.493207,
        "invested_cost": 77000.0,
        "total_return": 0.24144796372727284
      },
      {
        "date": "2024-12-03",
        "total_value": 95623.324886,
        "invested_cost": 77000.0,
        "total_return": 0.24186136215584408
      },
      {
        "date": "2024-12-05",
        "total_value": 95083.79271,
        "invested_cost": 77000.0,
        "total_return": 0.23485445077922074
      },
      {
        "date": "2024-12-06",
        "total_value": 95823.878088,
        "invested_cost": 77000.0,
        "total_return": 0.24446594919480513
      },
      {
        "date": "2024-12-10",
        "total_value": 96720.18828,
        "invested_cost": 77000.0,
        "total_return": 0.25610634129870125
      },
      {
        "date": "2024-12-11",
        "total_value": 96860.73538900001,
        "invested_cost": 77000.0,
        "total_return": 0.25793162842857154
      },
      {
        "date": "2024-12-13",
        "total_value": 96187.41191,
        "invested_cost": 77000.0,
        "total_return": 0.24918716766233762
      },
      {
        "date": "2024-12-17",
        "total_value": 95176.53546,
        "invested_cost": 77000.0,
        "total_return": 0.23605890207792202
      },
      {
        "date": "2024-12-18",
        "total_value": 95601.77645800001,
        "invested_cost": 77000.0,
        "total_return": 0.24158151244155857
      },
      {
        "date": "2024-12-20",
        "total_value": 95574.514965,
        "invested_cost": 77000.0,
        "total_return": 0.24122746707792198
      },
      {
        "date": "2024-12-23",
        "total_value": 95401.76055100001,
        "invested_cost": 77000.0,
        "total_return": 0.2389839032597405
      },
      {
        "date": "2024-12-25",
        "total_value": 95772.69416500001,
        "invested_cost": 77000.0,
        "total_return": 0.24380122292207806
      },
      {
        "date": "2024-12-27",
        "total_value": 95924.358777,
        "invested_cost": 77000.0,
        "total_return": 0.24577089320779222
      },
      {
        "date": "2024-12-30",
        "total_value": 95740.440026,
        "invested_cost": 77000.0,
        "total_return": 0.24338233799999998
      },
      {
        "date": "2025-01-02",
        "total_value": 93781.982539,
        "invested_cost": 77000.0,
        "total_return": 0.21794782518181832
      },
      {
        "date": "2025-01-03",
        "total_value": 93375.73165300001,
        "invested_cost": 77000.0,
        "total_return": 0.21267183964935077
      },
      {
        "date": "2025-01-07",
        "total_value": 96101.701279,
        "invested_cost": 80000.0,
        "total_return": 0.2012712659875
      },
      {
        "date": "2025-01-08",
        "total_value": 101484.64812000001,
        "invested_cost": 85000.0,
        "total_return": 0.19393703670588258
      },
      {
        "date": "2025-01-10",
        "total_value": 101056.56259800002,
        "invested_cost": 85000.0,
        "total_return": 0.18890073644705896
      },
      {
        "date": "2025-01-14",
        "total_value": 102401.414025,
        "invested_cost": 85000.0,
        "total_return": 0.20472251794117646
      },
      {
        "date": "2025-01-15",
        "total_value": 102203.76048900001,
        "invested_cost": 85000.0,
        "total_return": 0.20239718222352954
      },
      {
        "date": "2025-01-17",
        "total_value": 102485.906916,
        "invested_cost": 85000.0,
        "total_return": 0.20571655195294136
      },
      {
        "date": "2025-01-20",
        "total_value": 105567.49779300002,
        "invested_cost": 88000.0,
        "total_return": 0.19963065673863656
      },
      {
        "date": "2025-01-22",
        "total_value": 105132.46044,
        "invested_cost": 88000.0,
        "total_return": 0.19468705045454548
      },
      {
        "date": "2025-01-23",
        "total_value": 104991.73724000002,
        "invested_cost": 88000.0,
        "total_return": 0.19308792318181833
      },
      {
        "date": "2025-01-27",
        "total_value": 105156.25256200001,
        "invested_cost": 88000.0,
        "total_return": 0.19495741547727286
      },
      {
        "date": "2025-02-06",
        "total_value": 107259.82535900001,
        "invested_cost": 88000.0,
        "total_return": 0.21886165180681827
      },
      {
        "date": "2025-02-07",
        "total_value": 107983.84397199999,
        "invested_cost": 88000.0,
        "total_return": 0.22708913604545433
      },
      {
        "date": "2025-02-11",
        "total_value": 108451.81315700003,
        "invested_cost": 88000.0,
        "total_return": 0.23240696769318214
      },
      {
        "date": "2025-02-12",
        "total_value": 109478.67423799999,
        "invested_cost": 88000.0,
        "total_return": 0.24407584361363632
      },
      {
        "date": "2025-02-14",
        "total_value": 110622.26704899999,
        "invested_cost": 88000.0,
        "total_return": 0.257071216465909
      },
      {
        "date": "2025-02-18",
        "total_value": 112049.881146,
        "invested_cost": 91000.0,
        "total_return": 0.23131737523076912
      },
      {
        "date": "2025-02-19",
        "total_value": 112993.33704399999,
        "invested_cost": 91000.0,
        "total_return": 0.24168502246153833
      },
      {
        "date": "2025-02-21",
        "total_value": 114397.72301,
        "invested_cost": 91000.0,
        "total_return": 0.2571178352747252
      },
      {
        "date": "2025-02-24",
        "total_value": 114451.53090700001,
        "invested_cost": 91000.0,
        "total_return": 0.2577091308461539
      },
      {
        "date": "2025-02-26",
        "total_value": 114295.095049,
        "invested_cost": 91000.0,
        "total_return": 0.2559900554835164
      },
      {
        "date": "2025-02-27",
        "total_value": 114528.37244399998,
        "invested_cost": 91000.0,
        "total_return": 0.25855354334065916
      },
      {
        "date": "2025-03-03",
        "total_value": 112201.39787900001,
        "invested_cost": 91000.0,
        "total_return": 0.23298239427472534
      },
      {
        "date": "2025-03-05",
        "total_value": 113217.891106,
        "invested_cost": 91000.0,
        "total_return": 0.2441526495164834
      },
      {
        "date": "2025-03-06",
        "total_value": 114986.16081500001,
        "invested_cost": 91000.0,
        "total_return": 0.26358418478021983
      },
      {
        "date": "2025-03-10",
        "total_value": 114709.597017,
        "invested_cost": 91000.0,
        "total_return": 0.2605450221648351
      },
      {
        "date": "2025-03-11",
        "total_value": 115047.59197099999,
        "invested_cost": 91000.0,
        "total_return": 0.2642592524285712
      },
      {
        "date": "2025-03-13",
        "total_value": 114049.34966900002,
        "invested_cost": 91000.0,
        "total_return": 0.253289556802198
      },
      {
        "date": "2025-03-17",
        "total_value": 116567.94829600002,
        "invested_cost": 91000.0,
        "total_return": 0.2809664647912089
      },
      {
        "date": "2025-03-18",
        "total_value": 117153.40154,
        "invested_cost": 91000.0,
        "total_return": 0.28740001692307704
      },
      {
        "date": "2025-03-20",
        "total_value": 113988.23132400001,
        "invested_cost": 88805.0,
        "total_return": 0.2835789800574293
      },
      {
        "date": "2025-03-21",
        "total_value": 112690.795048,
        "invested_cost": 88805.0,
        "total_return": 0.2689690338156636
      },
      {
        "date": "2025-03-25",
        "total_value": 112210.44809699999,
        "invested_cost": 88805.0,
        "total_return": 0.2635600258656605
      },
      {
        "date": "2025-03-26",
        "total_value": 112298.533691,
        "invested_cost": 88805.0,
        "total_return": 0.26455192490287716
      },
      {
        "date": "2025-03-28",
        "total_value": 112790.93074699999,
        "invested_cost": 88805.0,
        "total_return": 0.2700966245932097
      },
      {
        "date": "2025-04-01",
        "total_value": 112943.951001,
        "invested_cost": 88805.0,
        "total_return": 0.2718197286301447
      },
      {
        "date": "2025-04-02",
        "total_value": 112676.13283,
        "invested_cost": 88805.0,
        "total_return": 0.2688039280445922
      },
      {
        "date": "2025-04-07",
        "total_value": 106492.69932200001,
        "invested_cost": 88805.0,
        "total_return": 0.19917458839029356
      },
      {
        "date": "2025-04-08",
        "total_value": 107730.994523,
        "invested_cost": 88805.0,
        "total_return": 0.21311856903327508
      },
      {
        "date": "2025-04-10",
        "total_value": 106612.229583,
        "invested_cost": 86005.0,
        "total_return": 0.23960501811522583
      },
      {
        "date": "2025-04-11",
        "total_value": 107480.771487,
        "invested_cost": 86005.0,
        "total_return": 0.249703755444451
      },
      {
        "date": "2025-04-15",
        "total_value": 107666.439354,
        "invested_cost": 86005.0,
        "total_return": 0.2518625586186849
      },
      {
        "date": "2025-04-17",
        "total_value": 108916.06882100002,
        "invested_cost": 86005.0,
        "total_return": 0.26639228906458956
      },
      {
        "date": "2025-04-18",
        "total_value": 108745.149189,
        "invested_cost": 86005.0,
        "total_return": 0.2644049670251729
      },
      {
        "date": "2025-04-22",
        "total_value": 110121.19667399999,
        "invested_cost": 86005.0,
        "total_return": 0.2804045889657578
      },
      {
        "date": "2025-04-23",
        "total_value": 108935.185925,
        "invested_cost": 86005.0,
        "total_return": 0.26661456804836936
      },
      {
        "date": "2025-04-25",
        "total_value": 108459.74534599998,
        "invested_cost": 86005.0,
        "total_return": 0.26108651062147525
      },
      {
        "date": "2025-04-29",
        "total_value": 108225.60040300002,
        "invested_cost": 86005.0,
        "total_return": 0.2583640532875997
      },
      {
        "date": "2025-04-30",
        "total_value": 108424.21823,
        "invested_cost": 86005.0,
        "total_return": 0.2606734286378698
      },
      {
        "date": "2025-05-07",
        "total_value": 110059.30459500001,
        "invested_cost": 86005.0,
        "total_return": 0.27968495546770544
      },
      {
        "date": "2025-05-08",
        "total_value": 109850.02401200001,
        "invested_cost": 86005.0,
        "total_return": 0.2772516017905937
      },
      {
        "date": "2025-05-12",
        "total_value": 109324.83317400001,
        "invested_cost": 86005.0,
        "total_return": 0.2711450866112437
      },
      {
        "date": "2025-05-13",
        "total_value": 109180.944908,
        "invested_cost": 86005.0,
        "total_return": 0.2694720645078774
      },
      {
        "date": "2025-05-15",
        "total_value": 106732.803859,
        "invested_cost": 83605.0,
        "total_return": 0.276631826553436
      },
      {
        "date": "2025-05-19",
        "total_value": 106483.84661199998,
        "invested_cost": 83605.0,
        "total_return": 0.27365404715028974
      },
      {
        "date": "2025-05-20",
        "total_value": 106761.79227299998,
        "invested_cost": 83605.0,
        "total_return": 0.2769785571795944
      },
      {
        "date": "2025-05-22",
        "total_value": 107318.74519000002,
        "invested_cost": 83605.0,
        "total_return": 0.2836402749835538
      },
      {
        "date": "2025-05-23",
        "total_value": 106736.322462,
        "invested_cost": 83605.0,
        "total_return": 0.2766739125889599
      },
      {
        "date": "2025-05-27",
        "total_value": 105892.32749199998,
        "invested_cost": 83605.0,
        "total_return": 0.26657888274624697
      },
      {
        "date": "2025-05-28",
        "total_value": 105866.75576500002,
        "invested_cost": 83605.0,
        "total_return": 0.2662730191376117
      },
      {
        "date": "2025-05-30",
        "total_value": 105807.517978,
        "invested_cost": 83605.0,
        "total_return": 0.26556447554572093
      },
      {
        "date": "2025-06-04",
        "total_value": 106475.334911,
        "invested_cost": 83605.0,
        "total_return": 0.273552238634053
      },
      {
        "date": "2025-06-05",
        "total_value": 106949.27688300001,
        "invested_cost": 83605.0,
        "total_return": 0.2792210619340949
      },
      {
        "date": "2025-06-09",
        "total_value": 106729.08483699999,
        "invested_cost": 83605.0,
        "total_return": 0.27658734330482604
      },
      {
        "date": "2025-06-10",
        "total_value": 106207.96605,
        "invested_cost": 83654.5,
        "total_return": 0.26960254439390585
      },
      {
        "date": "2025-06-12",
        "total_value": 106415.25624900001,
        "invested_cost": 83654.5,
        "total_return": 0.27208047683029624
      },
      {
        "date": "2025-06-16",
        "total_value": 106266.360127,
        "invested_cost": 83654.5,
        "total_return": 0.2703005830768219
      },
      {
        "date": "2025-06-17",
        "total_value": 106053.98975699999,
        "invested_cost": 83654.5,
        "total_return": 0.26776192263416787
      },
      {
        "date": "2025-06-19",
        "total_value": 105433.496217,
        "invested_cost": 83654.5,
        "total_return": 0.2603445865673695
      },
      {
        "date": "2025-06-20",
        "total_value": 105715.77431800003,
        "invested_cost": 83654.5,
        "total_return": 0.26371891910178213
      },
      {
        "date": "2025-06-24",
        "total_value": 106112.051864,
        "invested_cost": 83654.5,
        "total_return": 0.26845599297108924
      },
      {
        "date": "2025-06-25",
        "total_value": 106883.62019300001,
        "invested_cost": 83654.5,
        "total_return": 0.27767926642320506
      },
      {
        "date": "2025-06-27",
        "total_value": 106181.598579,
        "invested_cost": 83654.5,
        "total_return": 0.26928734950301525
      },
      {
        "date": "2025-07-01",
        "total_value": 106946.741697,
        "invested_cost": 83654.5,
        "total_return": 0.27843381643545784
      },
      {
        "date": "2025-07-02",
        "total_value": 106586.55175599999,
        "invested_cost": 83654.5,
        "total_return": 0.27412813125414637
      },
      {
        "date": "2025-07-04",
        "total_value": 106934.613902,
        "invested_cost": 83654.5,
        "total_return": 0.2782888416283642
      },
      {
        "date": "2025-07-07",
        "total_value": 106680.680821,
        "invested_cost": 83654.5,
        "total_return": 0.27525334346628094
      },
      {
        "date": "2025-07-09",
        "total_value": 106861.02374,
        "invested_cost": 83654.5,
        "total_return": 0.2774091500158391
      },
      {
        "date": "2025-07-10",
        "total_value": 107216.78617099997,
        "invested_cost": 83654.5,
        "total_return": 0.2816619090545036
      },
      {
        "date": "2025-07-14",
        "total_value": 107986.43246200001,
        "invested_cost": 83654.5,
        "total_return": 0.2908622065997646
      },
      {
        "date": "2025-07-16",
        "total_value": 108031.278279,
        "invested_cost": 83747.0,
        "total_return": 0.28997191874335804
      },
      {
        "date": "2025-07-17",
        "total_value": 108397.76964099999,
        "invested_cost": 83747.0,
        "total_return": 0.29434809176448096
      },
      {
        "date": "2025-07-21",
        "total_value": 109425.58460099998,
        "invested_cost": 83747.0,
        "total_return": 0.30662094882204705
      },
      {
        "date": "2025-07-22",
        "total_value": 110236.40222,
        "invested_cost": 83747.0,
        "total_return": 0.3163027000370162
      },
      {
        "date": "2025-07-24",
        "total_value": 110676.971553,
        "invested_cost": 83747.0,
        "total_return": 0.3215634178298923
      },
      {
        "date": "2025-07-28",
        "total_value": 110499.852977,
        "invested_cost": 83747.0,
        "total_return": 0.31944849340274883
      },
      {
        "date": "2025-07-29",
        "total_value": 110774.82655900001,
        "invested_cost": 83747.0,
        "total_return": 0.32273187766725986
      },
      {
        "date": "2025-07-31",
        "total_value": 109487.52985300001,
        "invested_cost": 83747.0,
        "total_return": 0.3073606201177357
      },
      {
        "date": "2025-08-01",
        "total_value": 108985.754298,
        "invested_cost": 83747.0,
        "total_return": 0.30136905558408067
      },
      {
        "date": "2025-08-05",
        "total_value": 110398.018557,
        "invested_cost": 83747.0,
        "total_return": 0.31823251647223194
      },
      {
        "date": "2025-08-06",
        "total_value": 110627.66794300001,
        "invested_cost": 83747.0,
        "total_return": 0.32097469692048675
      },
      {
        "date": "2025-08-08",
        "total_value": 110358.888923,
        "invested_cost": 83747.0,
        "total_return": 0.3177652802249633
      },
      {
        "date": "2025-08-12",
        "total_value": 110901.32326599998,
        "invested_cost": 83747.0,
        "total_return": 0.3242423402151715
      },
      {
        "date": "2025-08-13",
        "total_value": 111691.54416699999,
        "invested_cost": 83747.0,
        "total_return": 0.3336781516591638
      },
      {
        "date": "2025-08-15",
        "total_value": 112163.74477399999,
        "invested_cost": 83747.0,
        "total_return": 0.3393165698353373
      },
      {
        "date": "2025-08-18",
        "total_value": 112865.96875999999,
        "invested_cost": 83747.0,
        "total_return": 0.3477016342077923
      },
      {
        "date": "2025-08-20",
        "total_value": 112294.87169000003,
        "invested_cost": 81352.0,
        "total_return": 0.38035784848559384
      },
      {
        "date": "2025-08-22",
        "total_value": 114480.22098600001,
        "invested_cost": 81352.0,
        "total_return": 0.40722073195496145
      },
      {
        "date": "2025-08-25",
        "total_value": 116592.51765100002,
        "invested_cost": 81352.0,
        "total_return": 0.43318563343249106
      },
      {
        "date": "2025-08-27",
        "total_value": 115328.26180200001,
        "invested_cost": 81352.0,
        "total_return": 0.41764507082800684
      },
      {
        "date": "2025-08-28",
        "total_value": 117038.12920000002,
        "invested_cost": 81352.0,
        "total_return": 0.4386632068049958
      },
      {
        "date": "2025-09-01",
        "total_value": 118794.93630100002,
        "invested_cost": 81352.0,
        "total_return": 0.46025833785278825
      },
      {
        "date": "2025-09-02",
        "total_value": 118109.09239700001,
        "invested_cost": 81352.0,
        "total_return": 0.4518277657218017
      },
      {
        "date": "2025-09-04",
        "total_value": 115199.098538,
        "invested_cost": 81352.0,
        "total_return": 0.41605736230209467
      },
      {
        "date": "2025-09-08",
        "total_value": 117829.80235400001,
        "invested_cost": 81352.0,
        "total_return": 0.44839465967646785
      },
      {
        "date": "2025-09-09",
        "total_value": 117806.380876,
        "invested_cost": 81352.0,
        "total_return": 0.4481067567607433
      },
      {
        "date": "2025-09-11",
        "total_value": 119851.186354,
        "invested_cost": 81352.0,
        "total_return": 0.4732420389664669
      },
      {
        "date": "2025-09-12",
        "total_value": 120091.846108,
        "invested_cost": 81352.0,
        "total_return": 0.4762002914249188
      },
      {
        "date": "2025-09-16",
        "total_value": 120557.66689399998,
        "invested_cost": 81352.0,
        "total_return": 0.48192628200904686
      },
      {
        "date": "2025-09-17",
        "total_value": 120872.48627600001,
        "invested_cost": 81352.0,
        "total_return": 0.48579612395515803
      },
      {
        "date": "2025-09-19",
        "total_value": 120053.653437,
        "invested_cost": 81352.0,
        "total_return": 0.47573081715262067
      },
      {
        "date": "2025-09-23",
        "total_value": 121295.831759,
        "invested_cost": 81352.0,
        "total_return": 0.49099999703756514
      },
      {
        "date": "2025-09-24",
        "total_value": 122893.893773,
        "invested_cost": 81352.0,
        "total_return": 0.5106437920764086
      },
      {
        "date": "2025-09-26",
        "total_value": 121960.452807,
        "invested_cost": 81352.0,
        "total_return": 0.4991696922878355
      },
      {
        "date": "2025-09-29",
        "total_value": 123624.45227600001,
        "invested_cost": 81352.0,
        "total_return": 0.51962400771954
      },
      {
        "date": "2025-10-09",
        "total_value": 126448.120263,
        "invested_cost": 81352.0,
        "total_return": 0.5543332710074738
      },
      {
        "date": "2025-10-13",
        "total_value": 121284.14186300001,
        "invested_cost": 78552.0,
        "total_return": 0.543998139614523
      },
      {
        "date": "2025-10-14",
        "total_value": 120539.70187100001,
        "invested_cost": 78552.0,
        "total_return": 0.5345211053951524
      },
      {
        "date": "2025-10-16",
        "total_value": 122481.87771300001,
        "invested_cost": 78552.0,
        "total_return": 0.5592458207684083
      },
      {
        "date": "2025-10-17",
        "total_value": 121653.06822299998,
        "invested_cost": 78552.0,
        "total_return": 0.5486947273525815
      },
      {
        "date": "2025-10-21",
        "total_value": 123047.498219,
        "invested_cost": 78552.0,
        "total_return": 0.5664464077171809
      },
      {
        "date": "2025-10-22",
        "total_value": 121324.18296899999,
        "invested_cost": 78552.0,
        "total_return": 0.5445078797357163
      },
      {
        "date": "2025-10-24",
        "total_value": 122103.54020199999,
        "invested_cost": 78552.0,
        "total_return": 0.5544294251196658
      },
      {
        "date": "2025-10-28",
        "total_value": 121266.33471799998,
        "invested_cost": 78552.0,
        "total_return": 0.5437714471687543
      },
      {
        "date": "2025-10-29",
        "total_value": 122255.694615,
        "invested_cost": 78552.0,
        "total_return": 0.5563664147952949
      },
      {
        "date": "2025-10-31",
        "total_value": 120785.006622,
        "invested_cost": 78552.0,
        "total_return": 0.5376439380537732
      },
      {
        "date": "2025-11-03",
        "total_value": 120762.528844,
        "invested_cost": 78552.0,
        "total_return": 0.5373577864853856
      },
      {
        "date": "2025-11-05",
        "total_value": 119518.21374900002,
        "invested_cost": 78552.0,
        "total_return": 0.5215171319508098
      },
      {
        "date": "2025-11-06",
        "total_value": 121008.29553,
        "invested_cost": 78552.0,
        "total_return": 0.5404864997708525
      },
      {
        "date": "2025-11-10",
        "total_value": 122046.06648800004,
        "invested_cost": 78552.0,
        "total_return": 0.5536977605662496
      },
      {
        "date": "2025-11-12",
        "total_value": 121906.87123999998,
        "invested_cost": 78552.0,
        "total_return": 0.5519257465118645
      },
      {
        "date": "2025-11-13",
        "total_value": 123232.707417,
        "invested_cost": 78552.0,
        "total_return": 0.5688041987091352
      },
      {
        "date": "2025-11-17",
        "total_value": 120654.91188800002,
        "invested_cost": 78552.0,
        "total_return": 0.5359877773704045
      },
      {
        "date": "2025-11-18",
        "total_value": 119934.979873,
        "invested_cost": 78552.0,
        "total_return": 0.5268227400066199
      },
      {
        "date": "2025-11-20",
        "total_value": 119833.14904100001,
        "invested_cost": 78552.0,
        "total_return": 0.5255263906838783
      },
      {
        "date": "2025-11-24",
        "total_value": 118190.79103399998,
        "invested_cost": 78552.0,
        "total_return": 0.5046184824574802
      },
      {
        "date": "2025-11-25",
        "total_value": 119269.53184400001,
        "invested_cost": 78552.0,
        "total_return": 0.5183513067012935
      },
      {
        "date": "2025-11-27",
        "total_value": 119489.74581999998,
        "invested_cost": 78552.0,
        "total_return": 0.5211547232406557
      },
      {
        "date": "2025-11-28",
        "total_value": 119951.580758,
        "invested_cost": 78552.0,
        "total_return": 0.5270340762552195
      },
      {
        "date": "2025-12-02",
        "total_value": 120307.356249,
        "invested_cost": 78552.0,
        "total_return": 0.5315632478994807
      },
      {
        "date": "2025-12-03",
        "total_value": 119599.75029599998,
        "invested_cost": 78552.0,
        "total_return": 0.522555126489459
      },
      {
        "date": "2025-12-05",
        "total_value": 120262.89955199999,
        "invested_cost": 78552.0,
        "total_return": 0.5309972954476014
      },
      {
        "date": "2025-12-09",
        "total_value": 113472.42922800001,
        "invested_cost": 75952.0,
        "total_return": 0.4940018594375397
      },
      {
        "date": "2025-12-10",
        "total_value": 113761.761306,
        "invested_cost": 75952.0,
        "total_return": 0.497811266405098
      },
      {
        "date": "2025-12-12",
        "total_value": 114299.85832999999,
        "invested_cost": 75952.0,
        "total_return": 0.5048959649515481
      },
      {
        "date": "2025-12-15",
        "total_value": 113978.55932300001,
        "invested_cost": 75952.0,
        "total_return": 0.5006656746761113
      },
      {
        "date": "2025-12-17",
        "total_value": 114100.062575,
        "invested_cost": 75952.0,
        "total_return": 0.5022654120365495
      },
      {
        "date": "2025-12-18",
        "total_value": 113729.387885,
        "invested_cost": 75952.0,
        "total_return": 0.4973850311380872
      },
      {
        "date": "2025-12-22",
        "total_value": 115385.10991099999,
        "invested_cost": 75952.0,
        "total_return": 0.519184615428165
      },
      {
        "date": "2025-12-24",
        "total_value": 116142.91762900002,
        "invested_cost": 75952.0,
        "total_return": 0.5291620711633667
      },
      {
        "date": "2025-12-25",
        "total_value": 116299.595921,
        "invested_cost": 75952.0,
        "total_return": 0.5312249304955761
      },
      {
        "date": "2025-12-29",
        "total_value": 115885.807334,
        "invested_cost": 75952.0,
        "total_return": 0.5257769029650305
      },
      {
        "date": "2025-12-30",
        "total_value": 115385.482744,
        "invested_cost": 75952.0,
        "total_return": 0.5191895242258266
      },
      {
        "date": "2026-01-05",
        "total_value": 117188.816742,
        "invested_cost": 75952.0,
        "total_return": 0.5429325987729092
      },
      {
        "date": "2026-01-07",
        "total_value": 118662.69863799999,
        "invested_cost": 75952.0,
        "total_return": 0.5623380376816935
      },
      {
        "date": "2026-01-08",
        "total_value": 118313.720616,
        "invested_cost": 75952.0,
        "total_return": 0.5577433196755845
      },
      {
        "date": "2026-01-12",
        "total_value": 128429.835824,
        "invested_cost": 78952.0,
        "total_return": 0.626682488398014
      },
      {
        "date": "2026-01-13",
        "total_value": 127661.87541099999,
        "invested_cost": 78952.0,
        "total_return": 0.616955560479785
      },
      {
        "date": "2026-01-15",
        "total_value": 129883.43551800001,
        "invested_cost": 80952.0,
        "total_return": 0.6044499891046549
      },
      {
        "date": "2026-01-16",
        "total_value": 130105.21670000002,
        "invested_cost": 80952.0,
        "total_return": 0.6071896518924798
      },
      {
        "date": "2026-01-20",
        "total_value": 130607.91932900001,
        "invested_cost": 80952.0,
        "total_return": 0.613399537120763
      },
      {
        "date": "2026-01-22",
        "total_value": 132677.787558,
        "invested_cost": 80952.0,
        "total_return": 0.6389686179217315
      },
      {
        "date": "2026-01-23",
        "total_value": 133514.337145,
        "invested_cost": 80952.0,
        "total_return": 0.6493025143912441
      },
      {
        "date": "2026-01-27",
        "total_value": 134955.004119,
        "invested_cost": 80952.0,
        "total_return": 0.6670990725244588
      },
      {
        "date": "2026-01-28",
        "total_value": 137053.834988,
        "invested_cost": 80952.0,
        "total_return": 0.6930259287973117
      },
      {
        "date": "2026-01-30",
        "total_value": 135879.16644200002,
        "invested_cost": 80952.0,
        "total_return": 0.6785152490611723
      },
      {
        "date": "2026-02-02",
        "total_value": 128956.11177199999,
        "invested_cost": 80952.0,
        "total_return": 0.5929947595118092
      },
      {
        "date": "2026-02-04",
        "total_value": 134015.863926,
        "invested_cost": 80952.0,
        "total_return": 0.6554978743699968
      },
      {
        "date": "2026-02-06",
        "total_value": 131358.549642,
        "invested_cost": 80952.0,
        "total_return": 0.62267207285799
      },
      {
        "date": "2026-02-09",
        "total_value": 133511.15404300002,
        "invested_cost": 80952.0,
        "total_return": 0.6492631935344404
      },
      {
        "date": "2026-02-11",
        "total_value": 133513.24393800003,
        "invested_cost": 80952.0,
        "total_return": 0.6492890100059299
      },
      {
        "date": "2026-02-12",
        "total_value": 133815.16458,
        "invested_cost": 80952.0,
        "total_return": 0.6530186354876966
      },
      {
        "date": "2026-02-24",
        "total_value": 137227.775825,
        "invested_cost": 82952.0,
        "total_return": 0.6543034022687819
      },
      {
        "date": "2026-02-26",
        "total_value": 137586.116969,
        "invested_cost": 82952.0,
        "total_return": 0.6586232636826115
      },
      {
        "date": "2026-02-27",
        "total_value": 137503.492221,
        "invested_cost": 82952.0,
        "total_return": 0.6576272087592825
      },
      {
        "date": "2026-03-03",
        "total_value": 136373.67073700004,
        "invested_cost": 82952.0,
        "total_return": 0.6440070249903562
      },
      {
        "date": "2026-03-04",
        "total_value": 134466.575699,
        "invested_cost": 82952.0,
        "total_return": 0.6210166807189701
      },
      {
        "date": "2026-03-06",
        "total_value": 134861.264556,
        "invested_cost": 82952.0,
        "total_return": 0.6257747197897581
      },
      {
        "date": "2026-03-09",
        "total_value": 133855.75224700003,
        "invested_cost": 82952.0,
        "total_return": 0.6136531035659178
      },
      {
        "date": "2026-03-11",
        "total_value": 135114.497686,
        "invested_cost": 82952.0,
        "total_return": 0.6288274868116499
      },
      {
        "date": "2026-03-13",
        "total_value": 133601.876802,
        "invested_cost": 82952.0,
        "total_return": 0.6105925933310832
      },
      {
        "date": "2026-03-16",
        "total_value": 133430.16213300003,
        "invested_cost": 82952.0,
        "total_return": 0.608522544760826
      },
      {
        "date": "2026-03-18",
        "total_value": 133040.40227400002,
        "invested_cost": 82952.0,
        "total_return": 0.6038239255714151
      },
      {
        "date": "2026-03-19",
        "total_value": 129637.95372300003,
        "invested_cost": 82952.0,
        "total_return": 0.5628068488161833
      },
      {
        "date": "2026-03-23",
        "total_value": 121374.155113,
        "invested_cost": 82952.0,
        "total_return": 0.46318539773604006
      },
      {
        "date": "2026-03-25",
        "total_value": 126529.966203,
        "invested_cost": 82952.0,
        "total_return": 0.5253395482086025
      },
      {
        "date": "2026-03-26",
        "total_value": 124495.560248,
        "invested_cost": 82952.0,
        "total_return": 0.5008144498987366
      },
      {
        "date": "2026-03-30",
        "total_value": 125469.38986699998,
        "invested_cost": 82952.0,
        "total_return": 0.5125541260849644
      },
      {
        "date": "2026-03-31",
        "total_value": 124718.947513,
        "invested_cost": 82952.0,
        "total_return": 0.5035074201104255
      },
      {
        "date": "2026-04-02",
        "total_value": 125532.33510299999,
        "invested_cost": 82952.0,
        "total_return": 0.5133129412551836
      },
      {
        "date": "2026-04-03",
        "total_value": 125314.656446,
        "invested_cost": 82952.0,
        "total_return": 0.5106887892516152
      },
      {
        "date": "2026-04-08",
        "total_value": 129238.68872800001,
        "invested_cost": 82952.0,
        "total_return": 0.5579936436493396
      },
      {
        "date": "2026-04-10",
        "total_value": 129142.84657400002,
        "invested_cost": 82952.0,
        "total_return": 0.5568382507233101
      },
      {
        "date": "2026-04-13",
        "total_value": 128923.316327,
        "invested_cost": 82952.0,
        "total_return": 0.55419177749783
      },
      {
        "date": "2026-04-15",
        "total_value": 130241.00075299999,
        "invested_cost": 82952.0,
        "total_return": 0.570076679923329
      },
      {
        "date": "2026-04-16",
        "total_value": 131213.929935,
        "invested_cost": 82952.0,
        "total_return": 0.5818055011934611
      },
      {
        "date": "2026-04-20",
        "total_value": 131387.144505,
        "invested_cost": 82952.0,
        "total_return": 0.5838936313169063
      },
      {
        "date": "2026-04-21",
        "total_value": 131009.79074000001,
        "invested_cost": 82952.0,
        "total_return": 0.5793445696306299
      },
      {
        "date": "2026-04-23",
        "total_value": 130972.85512800002,
        "invested_cost": 82952.0,
        "total_return": 0.5788993047545572
      },
      {
        "date": "2026-04-27",
        "total_value": 132224.835853,
        "invested_cost": 82952.0,
        "total_return": 0.5939921382606808
      },
      {
        "date": "2026-04-28",
        "total_value": 131304.984737,
        "invested_cost": 82952.0,
        "total_return": 0.5829031818039347
      },
      {
        "date": "2026-04-30",
        "total_value": 132692.187139,
        "invested_cost": 82952.0,
        "total_return": 0.5996261348611243
      },
      {
        "date": "2026-05-06",
        "total_value": 134856.294759,
        "invested_cost": 82952.0,
        "total_return": 0.6257148080697272
      },
      {
        "date": "2026-05-08",
        "total_value": 134593.34062600002,
        "invested_cost": 82952.0,
        "total_return": 0.6225448527582218
      },
      {
        "date": "2026-05-12",
        "total_value": 136365.972336,
        "invested_cost": 82952.0,
        "total_return": 0.6439142195004341
      },
      {
        "date": "2026-05-13",
        "total_value": 137323.305845,
        "invested_cost": 82952.0,
        "total_return": 0.6554550323681165
      },
      {
        "date": "2026-05-15",
        "total_value": 133981.319996,
        "invested_cost": 82952.0,
        "total_return": 0.6151668434275244
      },
      {
        "date": "2026-05-18",
        "total_value": 133530.107487,
        "invested_cost": 82952.0,
        "total_return": 0.6097274024375543
      },
      {
        "date": "2026-05-20",
        "total_value": 135321.255184,
        "invested_cost": 82952.0,
        "total_return": 0.6313199824476807
      },
      {
        "date": "2026-05-21",
        "total_value": 133802.76825300002,
        "invested_cost": 82952.0,
        "total_return": 0.6130143728059603
      },
      {
        "date": "2026-05-25",
        "total_value": 137366.17992300002,
        "invested_cost": 82952.0,
        "total_return": 0.6559718864282962
      },
      {
        "date": "2026-05-27",
        "total_value": 135324.74791799998,
        "invested_cost": 82952.0,
        "total_return": 0.6313620879303692
      },
      {
        "date": "2026-05-28",
        "total_value": 134683.497219,
        "invested_cost": 82952.0,
        "total_return": 0.6236317053115057
      },
      {
        "date": "2026-06-01",
        "total_value": 131939.35621700002,
        "invested_cost": 82952.0,
        "total_return": 0.5905506343065872
      },
      {
        "date": "2026-06-02",
        "total_value": 133197.884338,
        "invested_cost": 82952.0,
        "total_return": 0.6057223977480952
      },
      {
        "date": "2026-06-04",
        "total_value": 133558.440937,
        "invested_cost": 82952.0,
        "total_return": 0.6100689668362427
      },
      {
        "date": "2026-06-05",
        "total_value": 131432.68659300002,
        "invested_cost": 82952.0,
        "total_return": 0.5844426486763432
      },
      {
        "date": "2026-06-09",
        "total_value": 129833.403386,
        "invested_cost": 82952.0,
        "total_return": 0.5651630266419134
      },
      {
        "date": "2026-06-11",
        "total_value": 127525.002412,
        "invested_cost": 82952.0,
        "total_return": 0.5373348733243322
      },
      {
        "date": "2026-06-12",
        "total_value": 128282.96565399999,
        "invested_cost": 82952.0,
        "total_return": 0.5464722448403894
      },
      {
        "date": "2026-06-16",
        "total_value": 131789.85833299998,
        "invested_cost": 82952.0,
        "total_return": 0.5887484127326645
      },
      {
        "date": "2026-06-17",
        "total_value": 133429.689047,
        "invested_cost": 82952.0,
        "total_return": 0.6085168416313047
      },
      {
        "date": "2026-06-22",
        "total_value": 135366.828634,
        "invested_cost": 82952.0,
        "total_return": 0.6318693778811844
      },
      {
        "date": "2026-06-24",
        "total_value": 134601.506338,
        "invested_cost": 82952.0,
        "total_return": 0.6226432917590896
      },
      {
        "date": "2026-06-25",
        "total_value": 135949.50254400002,
        "invested_cost": 82952.0,
        "total_return": 0.6388936076767289
      },
      {
        "date": "2026-06-29",
        "total_value": 137234.19385799998,
        "invested_cost": 82952.0,
        "total_return": 0.6543807727119295
      },
      {
        "date": "2026-06-30",
        "total_value": 138572.45258200003,
        "invested_cost": 82952.0,
        "total_return": 0.6705137016829013
      },
      {
        "date": "2026-07-02",
        "total_value": 133693.202128,
        "invested_cost": 82952.0,
        "total_return": 0.6116935351528596
      },
      {
        "date": "2026-07-03",
        "total_value": 134700.380011,
        "invested_cost": 82952.0,
        "total_return": 0.6238352301451442
      },
      {
        "date": "2026-07-07",
        "total_value": 134064.836623,
        "invested_cost": 82952.0,
        "total_return": 0.6161736500988524
      },
      {
        "date": "2026-07-09",
        "total_value": 137505.448341,
        "invested_cost": 82952.0,
        "total_return": 0.6576507901075321
      },
      {
        "date": "2026-07-10",
        "total_value": 134660.468021,
        "invested_cost": 82952.0,
        "total_return": 0.6233540845428682
      },
      {
        "date": "2026-07-14",
        "total_value": 133162.416777,
        "invested_cost": 82952.0,
        "total_return": 0.6052948304682226
      },
      {
        "date": "2026-07-15",
        "total_value": 131814.916994,
        "invested_cost": 82952.0,
        "total_return": 0.5890504990114764
      },
      {
        "date": "2026-07-17",
        "total_value": 125467.25399000001,
        "invested_cost": 82952.0,
        "total_return": 0.5125283777365224
      },
      {
        "date": "2026-07-20",
        "total_value": 125935.14988999999,
        "invested_cost": 82952.0,
        "total_return": 0.518168939748288
      },
      {
        "date": "2026-07-22",
        "total_value": 130398.895891,
        "invested_cost": 82952.0,
        "total_return": 0.5719801317750024
      },
      {
        "date": "2026-07-24",
        "total_value": 128049.66605700001,
        "invested_cost": 82952.0,
        "total_return": 0.5436597798365321
      },
      {
        "date": "2026-07-27",
        "total_value": 129158.12442099999,
        "invested_cost": 82952.0,
        "total_return": 0.5570224276810685
      },
      {
        "date": "2026-07-29",
        "total_value": 125817.239444,
        "invested_cost": 82952.0,
        "total_return": 0.5167475099334555
      },
      {
        "date": "2026-07-30",
        "total_value": 123978.767912,
        "invested_cost": 82952.0,
        "total_return": 0.49458443331083024
      },
      {
        "date": "2026-08-03",
        "total_value": 123249.49242000002,
        "invested_cost": 82952.0,
        "total_return": 0.48579289733821995
      },
      {
        "date": "2026-08-05",
        "total_value": 127706.56714800002,
        "invested_cost": 82952.0,
        "total_return": 0.5395236660719454
      },
      {
        "date": "2026-08-06",
        "total_value": 128739.46470699999,
        "invested_cost": 82952.0,
        "total_return": 0.551975415987559
      },
      {
        "date": "2026-08-10",
        "total_value": 131037.78384199999,
        "invested_cost": 82952.0,
        "total_return": 0.5796820310782138
      },
      {
        "date": "2026-08-11",
        "total_value": 130307.16748300001,
        "invested_cost": 82952.0,
        "total_return": 0.5708743307334363
      },
      {
        "date": "2026-08-13",
        "total_value": 130429.81224300001,
        "invested_cost": 82952.0,
        "total_return": 0.5723528334820138
      },
      {
        "date": "2026-08-14",
        "total_value": 130067.71360099998,
        "invested_cost": 82952.0,
        "total_return": 0.5679876748119392
      },
      {
        "date": "2026-08-18",
        "total_value": 132688.791476,
        "invested_cost": 82952.0,
        "total_return": 0.5995851995853025
      },
      {
        "date": "2026-08-20",
        "total_value": 129738.70421199998,
        "invested_cost": 83052.0,
        "total_return": 0.5621382292057986
      },
      {
        "date": "2026-08-21",
        "total_value": 130525.547983,
        "invested_cost": 83052.0,
        "total_return": 0.5716123390526417
      },
      {
        "date": "2026-08-25",
        "total_value": 129707.059276,
        "invested_cost": 83152.0,
        "total_return": 0.5598790080334808
      },
      {
        "date": "2026-08-26",
        "total_value": 130385.63434800002,
        "invested_cost": 83152.0,
        "total_return": 0.5680396664902831
      },
      {
        "date": "2026-08-28",
        "total_value": 131074.95109500003,
        "invested_cost": 83152.0,
        "total_return": 0.5763295061453726
      },
      {
        "date": "2026-09-01",
        "total_value": 129333.37481200001,
        "invested_cost": 83252.0,
        "total_return": 0.553516730072551
      },
      {
        "date": "2026-09-02",
        "total_value": 127565.03737799998,
        "invested_cost": 83252.0,
        "total_return": 0.532275949863066
      },
      {
        "date": "2026-09-04",
        "total_value": 128063.81516000001,
        "invested_cost": 83252.0,
        "total_return": 0.5382671306395044
      },
      {
        "date": "2026-09-07",
        "total_value": 128588.92531699999,
        "invested_cost": 83352.0,
        "total_return": 0.5427215341803435
      },
      {
        "date": "2026-09-09",
        "total_value": 128151.701207,
        "invested_cost": 83352.0,
        "total_return": 0.5374760198555524
      },
      {
        "date": "2026-09-10",
        "total_value": 127672.565415,
        "invested_cost": 83352.0,
        "total_return": 0.5317276779801325
      },
      {
        "date": "2026-09-14",
        "total_value": 125442.54738000003,
        "invested_cost": 83452.0,
        "total_return": 0.5031700544025313
      },
      {
        "date": "2026-09-16",
        "total_value": 127151.088343,
        "invested_cost": 83452.0,
        "total_return": 0.5236433919258974
      },
      {
        "date": "2026-09-17",
        "total_value": 126606.09894000001,
        "invested_cost": 83452.0,
        "total_return": 0.5171128186262763
      },
      {
        "date": "2026-09-21",
        "total_value": 128894.45178799999,
        "invested_cost": 83552.0,
        "total_return": 0.5426854149272309
      },
      {
        "date": "2026-09-22",
        "total_value": 128821.09920300002,
        "invested_cost": 83552.0,
        "total_return": 0.5418074875885679
      },
      {
        "date": "2026-09-24",
        "total_value": 126670.97389900002,
        "invested_cost": 83552.0,
        "total_return": 0.5160735098980278
      },
      {
        "date": "2026-09-28",
        "total_value": 123902.60081500001,
        "invested_cost": 83652.0,
        "total_return": 0.4811672263066038
      },
      {
        "date": "2026-09-30",
        "total_value": 123886.56091900001,
        "invested_cost": 83652.0,
        "total_return": 0.4809754807894613
      },
      {
        "date": "2026-10-09",
        "total_value": 122006.58115700002,
        "invested_cost": 83752.0,
        "total_return": 0.456760210586016
      },
      {
        "date": "2026-10-12",
        "total_value": 121099.25097100002,
        "invested_cost": 83852.0,
        "total_return": 0.44420229655822174
      },
      {
        "date": "2026-10-14",
        "total_value": 119616.37300500002,
        "invested_cost": 83852.0,
        "total_return": 0.4265178290917333
      },
      {
        "date": "2026-10-15",
        "total_value": 118501.23967500002,
        "invested_cost": 83852.0,
        "total_return": 0.4132190010375425
      },
      {
        "date": "2026-10-19",
        "total_value": 118617.88881900001,
        "invested_cost": 83952.0,
        "total_return": 0.4129251098127502
      },
      {
        "date": "2026-10-21",
        "total_value": 117825.579259,
        "invested_cost": 83952.0,
        "total_return": 0.4034874602034497
      },
      {
        "date": "2026-10-22",
        "total_value": 115971.78677100001,
        "invested_cost": 83952.0,
        "total_return": 0.3814058839694112
      },
      {
        "date": "2026-10-26",
        "total_value": 116137.84935,
        "invested_cost": 84052.0,
        "total_return": 0.3817380829724457
      },
      {
        "date": "2026-10-27",
        "total_value": 114390.39411899999,
        "invested_cost": 84052.0,
        "total_return": 0.3609479146123826
      },
      {
        "date": "2026-10-29",
        "total_value": 114167.37991500001,
        "invested_cost": 84052.0,
        "total_return": 0.35829462612430407
      },
      {
        "date": "2026-10-30",
        "total_value": 112543.67099299999,
        "invested_cost": 84052.0,
        "total_return": 0.33897671671108354
      },
      {
        "date": "2026-11-03",
        "total_value": 112365.574029,
        "invested_cost": 84152.0,
        "total_return": 0.33526920369094015
      }
    ]
  }
}
```

### get_benchmark_comparison

- 请求：`GET /api/agent/tools/benchmark?codes=000300&codes=CPI`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_benchmark_comparison",
  "generated_at": "2026-11-04T00:10:37.857990+08:00",
  "currency": "CNY",
  "data": {
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "valuation_basis": "latest_formal_nav",
    "codes": [
      "000300",
      "CPI"
    ],
    "code_names": {
      "000300": "沪深300",
      "CPI": "CPI购买力"
    },
    "points_count": 576,
    "points": [
      {
        "date": "2024-06-20",
        "000300": 0.0,
        "CPI": 0.0
      },
      {
        "date": "2024-06-21",
        "000300": -0.002187,
        "CPI": 0.0
      },
      {
        "date": "2024-06-24",
        "000300": -0.007556,
        "CPI": 0.0
      },
      {
        "date": "2024-06-25",
        "000300": -0.012954,
        "CPI": 0.0
      },
      {
        "date": "2024-06-26",
        "000300": -0.00657,
        "CPI": 0.0
      },
      {
        "date": "2024-06-27",
        "000300": -0.014034,
        "CPI": 0.0
      },
      {
        "date": "2024-06-28",
        "000300": -0.011882,
        "CPI": 0.0
      },
      {
        "date": "2024-06-30",
        "000300": -0.011882,
        "CPI": -0.002
      },
      {
        "date": "2024-07-01",
        "000300": -0.007164,
        "CPI": -0.002
      },
      {
        "date": "2024-07-02",
        "000300": -0.00899,
        "CPI": -0.002
      },
      {
        "date": "2024-07-03",
        "000300": -0.01138,
        "CPI": -0.002
      },
      {
        "date": "2024-07-04",
        "000300": -0.016404,
        "CPI": -0.002
      },
      {
        "date": "2024-07-05",
        "000300": -0.020615,
        "CPI": -0.002
      },
      {
        "date": "2024-07-08",
        "000300": -0.028979,
        "CPI": -0.002
      },
      {
        "date": "2024-07-09",
        "000300": -0.018118,
        "CPI": -0.002
      },
      {
        "date": "2024-07-10",
        "000300": -0.021213,
        "CPI": -0.002
      },
      {
        "date": "2024-07-11",
        "000300": -0.010023,
        "CPI": -0.002
      },
      {
        "date": "2024-07-12",
        "000300": -0.008815,
        "CPI": -0.002
      },
      {
        "date": "2024-07-15",
        "000300": -0.007717,
        "CPI": -0.002
      },
      {
        "date": "2024-07-16",
        "000300": -0.001427,
        "CPI": -0.002
      },
      {
        "date": "2024-07-17",
        "000300": -0.000485,
        "CPI": -0.002
      },
      {
        "date": "2024-07-18",
        "000300": 0.005038,
        "CPI": -0.002
      },
      {
        "date": "2024-07-19",
        "000300": 0.0102,
        "CPI": -0.002
      },
      {
        "date": "2024-07-22",
        "000300": 0.003323,
        "CPI": -0.002
      },
      {
        "date": "2024-07-23",
        "000300": -0.018098,
        "CPI": -0.002
      },
      {
        "date": "2024-07-24",
        "000300": -0.024296,
        "CPI": -0.002
      },
      {
        "date": "2024-07-25",
        "000300": -0.029689,
        "CPI": -0.002
      },
      {
        "date": "2024-07-26",
        "000300": -0.026829,
        "CPI": -0.002
      },
      {
        "date": "2024-07-29",
        "000300": -0.032124,
        "CPI": -0.002
      },
      {
        "date": "2024-07-30",
        "000300": -0.038221,
        "CPI": -0.002
      },
      {
        "date": "2024-07-31",
        "000300": -0.017469,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-01",
        "000300": -0.023982,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-02",
        "000300": -0.033937,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-05",
        "000300": -0.04566,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-06",
        "000300": -0.045758,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-07",
        "000300": -0.046183,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-08",
        "000300": -0.04577,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-09",
        "000300": -0.048998,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-12",
        "000300": -0.050643,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-13",
        "000300": -0.04821,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-14",
        "000300": -0.055389,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-15",
        "000300": -0.046051,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-16",
        "000300": -0.045,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-19",
        "000300": -0.041765,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-20",
        "000300": -0.048691,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-21",
        "000300": -0.051851,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-22",
        "000300": -0.054277,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-23",
        "000300": -0.050265,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-26",
        "000300": -0.051112,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-27",
        "000300": -0.056504,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-28",
        "000300": -0.061881,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-29",
        "000300": -0.064397,
        "CPI": 0.00299
      },
      {
        "date": "2024-08-30",
        "000300": -0.051908,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-02",
        "000300": -0.068014,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-03",
        "000300": -0.065611,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-04",
        "000300": -0.07168,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-05",
        "000300": -0.070084,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-06",
        "000300": -0.077623,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-09",
        "000300": -0.088583,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-10",
        "000300": -0.087783,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-11",
        "000300": -0.09053,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-12",
        "000300": -0.094428,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-13",
        "000300": -0.098204,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-18",
        "000300": -0.094846,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-19",
        "000300": -0.087702,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-20",
        "000300": -0.086271,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-23",
        "000300": -0.082927,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-24",
        "000300": -0.043209,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-25",
        "000300": -0.029044,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-26",
        "000300": 0.012,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-27",
        "000300": 0.057204,
        "CPI": 0.00299
      },
      {
        "date": "2024-09-30",
        "000300": 0.146883,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-08",
        "000300": 0.214888,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-09",
        "000300": 0.129222,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-10",
        "000300": 0.141155,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-11",
        "000300": 0.109579,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-14",
        "000300": 0.130752,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-15",
        "000300": 0.100681,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-16",
        "000300": 0.093714,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-17",
        "000300": 0.081335,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-18",
        "000300": 0.120445,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-21",
        "000300": 0.123289,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-22",
        "000300": 0.129734,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-23",
        "000300": 0.134139,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-24",
        "000300": 0.121472,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-25",
        "000300": 0.129347,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-28",
        "000300": 0.131555,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-29",
        "000300": 0.120278,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-30",
        "000300": 0.11023,
        "CPI": 0.007003
      },
      {
        "date": "2024-10-31",
        "000300": 0.110684,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-01",
        "000300": 0.110393,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-04",
        "000300": 0.126019,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-05",
        "000300": 0.15451,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-06",
        "000300": 0.148718,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-07",
        "000300": 0.183375,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-08",
        "000300": 0.171486,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-11",
        "000300": 0.179217,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-12",
        "000300": 0.166262,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-13",
        "000300": 0.17344,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-14",
        "000300": 0.153096,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-15",
        "000300": 0.132889,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-18",
        "000300": 0.127623,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-19",
        "000300": 0.13519,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-20",
        "000300": 0.137725,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-21",
        "000300": 0.138732,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-22",
        "000300": 0.103451,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-25",
        "000300": 0.098425,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-26",
        "000300": 0.096168,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-27",
        "000300": 0.115253,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-28",
        "000300": 0.105407,
        "CPI": 0.003981
      },
      {
        "date": "2024-11-29",
        "000300": 0.117975,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-02",
        "000300": 0.126838,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-03",
        "000300": 0.128054,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-04",
        "000300": 0.121964,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-05",
        "000300": 0.119404,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-06",
        "000300": 0.13412,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-09",
        "000300": 0.132244,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-10",
        "000300": 0.140541,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-11",
        "000300": 0.138598,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-12",
        "000300": 0.149923,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-13",
        "000300": 0.122713,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-16",
        "000300": 0.116622,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-17",
        "000300": 0.119531,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-18",
        "000300": 0.125199,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-19",
        "000300": 0.126219,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-20",
        "000300": 0.121161,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-23",
        "000300": 0.122825,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-24",
        "000300": 0.13713,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-25",
        "000300": 0.137684,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-26",
        "000300": 0.138213,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-27",
        "000300": 0.136372,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-30",
        "000300": 0.141517,
        "CPI": 0.003981
      },
      {
        "date": "2024-12-31",
        "000300": 0.123207,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-02",
        "000300": 0.090519,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-03",
        "000300": 0.077608,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-06",
        "000300": 0.07584,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-07",
        "000300": 0.083586,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-08",
        "000300": 0.081619,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-09",
        "000300": 0.078953,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-10",
        "000300": 0.065424,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-13",
        "000300": 0.062579,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-14",
        "000300": 0.09056,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-15",
        "000300": 0.083563,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-16",
        "000300": 0.084807,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-17",
        "000300": 0.08822,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-20",
        "000300": 0.093168,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-21",
        "000300": 0.094007,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-22",
        "000300": 0.083846,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-23",
        "000300": 0.085766,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-24",
        "000300": 0.094078,
        "CPI": -0.002043
      },
      {
        "date": "2025-01-27",
        "000300": 0.089573,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-05",
        "000300": 0.083294,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-06",
        "000300": 0.096923,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-07",
        "000300": 0.111159,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-10",
        "000300": 0.113545,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-11",
        "000300": 0.108428,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-12",
        "000300": 0.118911,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-13",
        "000300": 0.114709,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-14",
        "000300": 0.124377,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-17",
        "000300": 0.126771,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-18",
        "000300": 0.116891,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-19",
        "000300": 0.124705,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-20",
        "000300": 0.12149,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-21",
        "000300": 0.135633,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-24",
        "000300": 0.133142,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-25",
        "000300": 0.120564,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-26",
        "000300": 0.130352,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-27",
        "000300": 0.132685,
        "CPI": -0.002043
      },
      {
        "date": "2025-02-28",
        "000300": 0.110401,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-03",
        "000300": 0.109952,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-04",
        "000300": 0.109023,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-05",
        "000300": 0.113976,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-06",
        "000300": 0.129294,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-07",
        "000300": 0.125805,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-10",
        "000300": 0.121463,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-11",
        "000300": 0.125064,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-12",
        "000300": 0.121015,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-13",
        "000300": 0.116547,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-14",
        "000300": 0.143658,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-17",
        "000300": 0.14087,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-18",
        "000300": 0.143991,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-19",
        "000300": 0.144689,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-20",
        "000300": 0.134648,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-21",
        "000300": 0.117437,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-24",
        "000300": 0.123189,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-25",
        "000300": 0.12246,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-26",
        "000300": 0.118767,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-27",
        "000300": 0.122494,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-28",
        "000300": 0.117571,
        "CPI": 0.002933
      },
      {
        "date": "2025-03-31",
        "000300": 0.109618,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-01",
        "000300": 0.109726,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-02",
        "000300": 0.108785,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-03",
        "000300": 0.102253,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-07",
        "000300": 0.024594,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-08",
        "000300": 0.042097,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-09",
        "000300": 0.052383,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-10",
        "000300": 0.066176,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-11",
        "000300": 0.070572,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-14",
        "000300": 0.073034,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-15",
        "000300": 0.073632,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-16",
        "000300": 0.076939,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-17",
        "000300": 0.076768,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-18",
        "000300": 0.076854,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-21",
        "000300": 0.080381,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-22",
        "000300": 0.080116,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-23",
        "000300": 0.080953,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-24",
        "000300": 0.080232,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-25",
        "000300": 0.080985,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-28",
        "000300": 0.07945,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-29",
        "000300": 0.077583,
        "CPI": -0.001078
      },
      {
        "date": "2025-04-30",
        "000300": 0.076297,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-06",
        "000300": 0.087135,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-07",
        "000300": 0.093725,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-08",
        "000300": 0.099796,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-09",
        "000300": 0.097873,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-12",
        "000300": 0.110561,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-13",
        "000300": 0.112174,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-14",
        "000300": 0.125576,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-15",
        "000300": 0.115297,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-16",
        "000300": 0.110126,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-19",
        "000300": 0.106718,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-20",
        "000300": 0.11272,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-21",
        "000300": 0.117918,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-22",
        "000300": 0.1172,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-23",
        "000300": 0.108182,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-26",
        "000300": 0.101854,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-27",
        "000300": 0.095943,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-28",
        "000300": 0.095041,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-29",
        "000300": 0.101453,
        "CPI": -8e-05
      },
      {
        "date": "2025-05-30",
        "000300": 0.096181,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-03",
        "000300": 0.099544,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-04",
        "000300": 0.10432,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-05",
        "000300": 0.106835,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-06",
        "000300": 0.105816,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-09",
        "000300": 0.10903,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-10",
        "000300": 0.103384,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-11",
        "000300": 0.111708,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-12",
        "000300": 0.111015,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-13",
        "000300": 0.103018,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-16",
        "000300": 0.105762,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-17",
        "000300": 0.104787,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-18",
        "000300": 0.106097,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-19",
        "000300": 0.096997,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-20",
        "000300": 0.098012,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-23",
        "000300": 0.101225,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-24",
        "000300": 0.114393,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-25",
        "000300": 0.130387,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-26",
        "000300": 0.126378,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-27",
        "000300": 0.119453,
        "CPI": -8e-05
      },
      {
        "date": "2025-06-30",
        "000300": 0.12354,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-01",
        "000300": 0.125448,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-02",
        "000300": 0.125712,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-03",
        "000300": 0.132672,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-04",
        "000300": 0.136706,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-07",
        "000300": 0.131846,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-08",
        "000300": 0.141345,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-09",
        "000300": 0.139332,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-10",
        "000300": 0.144648,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-11",
        "000300": 0.146013,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-14",
        "000300": 0.14683,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-15",
        "000300": 0.147228,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-16",
        "000300": 0.143842,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-17",
        "000300": 0.151632,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-18",
        "000300": 0.158499,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-21",
        "000300": 0.166223,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-22",
        "000300": 0.175743,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-23",
        "000300": 0.175974,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-24",
        "000300": 0.184329,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-25",
        "000300": 0.178085,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-28",
        "000300": 0.180557,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-29",
        "000300": 0.185181,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-30",
        "000300": 0.184957,
        "CPI": -0.003077
      },
      {
        "date": "2025-07-31",
        "000300": 0.163364,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-01",
        "000300": 0.157466,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-04",
        "000300": 0.161968,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-05",
        "000300": 0.171316,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-06",
        "000300": 0.17418,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-07",
        "000300": 0.174517,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-08",
        "000300": 0.171749,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-11",
        "000300": 0.176757,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-12",
        "000300": 0.182841,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-13",
        "000300": 0.19219,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-14",
        "000300": 0.191258,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-15",
        "000300": 0.199547,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-18",
        "000300": 0.210126,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-19",
        "000300": 0.205548,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-20",
        "000300": 0.219256,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-21",
        "000300": 0.224015,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-22",
        "000300": 0.249685,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-25",
        "000300": 0.275724,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-26",
        "000300": 0.270977,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-27",
        "000300": 0.252005,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-28",
        "000300": 0.274171,
        "CPI": 0.000911
      },
      {
        "date": "2025-08-29",
        "000300": 0.283585,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-01",
        "000300": 0.291278,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-02",
        "000300": 0.281785,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-03",
        "000300": 0.273043,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-04",
        "000300": 0.246034,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-05",
        "000300": 0.273185,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-08",
        "000300": 0.275254,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-09",
        "000300": 0.266315,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-10",
        "000300": 0.268914,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-11",
        "000300": 0.298221,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-12",
        "000300": 0.290789,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-15",
        "000300": 0.293946,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-16",
        "000300": 0.291171,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-17",
        "000300": 0.299074,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-18",
        "000300": 0.28397,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-19",
        "000300": 0.285058,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-22",
        "000300": 0.290963,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-23",
        "000300": 0.290155,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-24",
        "000300": 0.30337,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-25",
        "000300": 0.311196,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-26",
        "000300": 0.298796,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-29",
        "000300": 0.318779,
        "CPI": 0.000911
      },
      {
        "date": "2025-09-30",
        "000300": 0.32467,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-09",
        "000300": 0.344306,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-10",
        "000300": 0.31786,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-13",
        "000300": 0.311336,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-14",
        "000300": 0.29566,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-15",
        "000300": 0.314849,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-16",
        "000300": 0.318313,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-17",
        "000300": 0.288573,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-20",
        "000300": 0.29542,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-21",
        "000300": 0.315301,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-22",
        "000300": 0.310934,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-23",
        "000300": 0.314866,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-24",
        "000300": 0.330376,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-27",
        "000300": 0.346172,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-28",
        "000300": 0.339308,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-29",
        "000300": 0.355254,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-30",
        "000300": 0.344428,
        "CPI": 0.001911
      },
      {
        "date": "2025-10-31",
        "000300": 0.324663,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-03",
        "000300": 0.328298,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-04",
        "000300": 0.318392,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-05",
        "000300": 0.320835,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-06",
        "000300": 0.339716,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-07",
        "000300": 0.335546,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-10",
        "000300": 0.340186,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-11",
        "000300": 0.327945,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-12",
        "000300": 0.326159,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-13",
        "000300": 0.342191,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-14",
        "000300": 0.321087,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-17",
        "000300": 0.312499,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-18",
        "000300": 0.303975,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-19",
        "000300": 0.309712,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-20",
        "000300": 0.303049,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-21",
        "000300": 0.271267,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-24",
        "000300": 0.26968,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-25",
        "000300": 0.281771,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-26",
        "000300": 0.289541,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-27",
        "000300": 0.288907,
        "CPI": 0.003915
      },
      {
        "date": "2025-11-28",
        "000300": 0.29212,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-01",
        "000300": 0.306342,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-02",
        "000300": 0.30002,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-03",
        "000300": 0.293373,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-04",
        "000300": 0.297802,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-05",
        "000300": 0.308641,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-08",
        "000300": 0.319264,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-09",
        "000300": 0.312547,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-10",
        "000300": 0.310721,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-11",
        "000300": 0.299406,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-12",
        "000300": 0.307617,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-15",
        "000300": 0.29937,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-16",
        "000300": 0.283812,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-17",
        "000300": 0.30731,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-18",
        "000300": 0.299579,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-19",
        "000300": 0.303971,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-22",
        "000300": 0.316372,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-23",
        "000300": 0.318973,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-24",
        "000300": 0.322776,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-25",
        "000300": 0.325196,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-26",
        "000300": 0.329393,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-29",
        "000300": 0.324293,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-30",
        "000300": 0.327693,
        "CPI": 0.003915
      },
      {
        "date": "2025-12-31",
        "000300": 0.321601,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-05",
        "000300": 0.346665,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-06",
        "000300": 0.367487,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-07",
        "000300": 0.363483,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-08",
        "000300": 0.352347,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-09",
        "000300": 0.358418,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-12",
        "000300": 0.367265,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-13",
        "000300": 0.35902,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-14",
        "000300": 0.353568,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-15",
        "000300": 0.356279,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-16",
        "000300": 0.350697,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-19",
        "000300": 0.351434,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-20",
        "000300": 0.346988,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-21",
        "000300": 0.348184,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-22",
        "000300": 0.348367,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-23",
        "000300": 0.342312,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-26",
        "000300": 0.343587,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-27",
        "000300": 0.343224,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-28",
        "000300": 0.346735,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-29",
        "000300": 0.356976,
        "CPI": 0.004917
      },
      {
        "date": "2026-01-30",
        "000300": 0.343409,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-02",
        "000300": 0.314761,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-03",
        "000300": 0.330212,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-04",
        "000300": 0.341223,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-05",
        "000300": 0.333155,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-06",
        "000300": 0.325499,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-09",
        "000300": 0.347039,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-10",
        "000300": 0.348534,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-11",
        "000300": 0.345544,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-12",
        "000300": 0.347188,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-13",
        "000300": 0.330297,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-24",
        "000300": 0.343753,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-25",
        "000300": 0.351843,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-26",
        "000300": 0.34927,
        "CPI": 0.004917
      },
      {
        "date": "2026-02-27",
        "000300": 0.344638,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-02",
        "000300": 0.349783,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-03",
        "000300": 0.32901,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-04",
        "000300": 0.313804,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-05",
        "000300": 0.326668,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-06",
        "000300": 0.330307,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-09",
        "000300": 0.317466,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-10",
        "000300": 0.334393,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-11",
        "000300": 0.342882,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-12",
        "000300": 0.338048,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-13",
        "000300": 0.33279,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-16",
        "000300": 0.333481,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-17",
        "000300": 0.323741,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-18",
        "000300": 0.329705,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-19",
        "000300": 0.308273,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-20",
        "000300": 0.30364,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-23",
        "000300": 0.261102,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-24",
        "000300": 0.277294,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-25",
        "000300": 0.295204,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-26",
        "000300": 0.278097,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-27",
        "000300": 0.285243,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-30",
        "000300": 0.282212,
        "CPI": 0.004917
      },
      {
        "date": "2026-03-31",
        "000300": 0.270251,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-01",
        "000300": 0.291951,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-02",
        "000300": 0.278491,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-03",
        "000300": 0.267608,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-07",
        "000300": 0.267559,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-08",
        "000300": 0.311786,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-09",
        "000300": 0.303413,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-10",
        "000300": 0.323492,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-13",
        "000300": 0.326229,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-14",
        "000300": 0.341966,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-15",
        "000300": 0.337388,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-16",
        "000300": 0.352049,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-17",
        "000300": 0.349783,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-20",
        "000300": 0.357996,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-21",
        "000300": 0.361009,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-22",
        "000300": 0.370037,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-23",
        "000300": 0.366241,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-24",
        "000300": 0.3614,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-27",
        "000300": 0.361851,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-28",
        "000300": 0.358214,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-29",
        "000300": 0.373097,
        "CPI": 0.009877
      },
      {
        "date": "2026-04-30",
        "000300": 0.37223,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-06",
        "000300": 0.39215,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-07",
        "000300": 0.398834,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-08",
        "000300": 0.390671,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-11",
        "000300": 0.413485,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-12",
        "000300": 0.412403,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-13",
        "000300": 0.42676,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-14",
        "000300": 0.402855,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-15",
        "000300": 0.387154,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-18",
        "000300": 0.379713,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-19",
        "000300": 0.385239,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-20",
        "000300": 0.384616,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-21",
        "000300": 0.365319,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-22",
        "000300": 0.383016,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-25",
        "000300": 0.404853,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-26",
        "000300": 0.412347,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-27",
        "000300": 0.401021,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-28",
        "000300": 0.402745,
        "CPI": 0.012907
      },
      {
        "date": "2026-05-29",
        "000300": 0.396439,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-01",
        "000300": 0.382776,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-02",
        "000300": 0.402844,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-03",
        "000300": 0.409766,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-04",
        "000300": 0.400043,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-05",
        "000300": 0.374974,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-08",
        "000300": 0.345491,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-09",
        "000300": 0.370661,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-10",
        "000300": 0.35547,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-11",
        "000300": 0.347997,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-12",
        "000300": 0.36367,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-15",
        "000300": 0.396323,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-16",
        "000300": 0.394188,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-17",
        "000300": 0.407647,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-18",
        "000300": 0.410563,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-22",
        "000300": 0.444262,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-23",
        "000300": 0.404222,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-24",
        "000300": 0.410968,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-25",
        "000300": 0.432972,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-26",
        "000300": 0.389617,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-29",
        "000300": 0.406373,
        "CPI": 0.012907
      },
      {
        "date": "2026-06-30",
        "000300": 0.421362,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-01",
        "000300": 0.415523,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-02",
        "000300": 0.373654,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-03",
        "000300": 0.382182,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-06",
        "000300": 0.382132,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-07",
        "000300": 0.367935,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-08",
        "000300": 0.357451,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-09",
        "000300": 0.391927,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-10",
        "000300": 0.364659,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-13",
        "000300": 0.340281,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-14",
        "000300": 0.369145,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-15",
        "000300": 0.366371,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-16",
        "000300": 0.341152,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-17",
        "000300": 0.292815,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-20",
        "000300": 0.312575,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-21",
        "000300": 0.352797,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-22",
        "000300": 0.346521,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-23",
        "000300": 0.349592,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-24",
        "000300": 0.327096,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-27",
        "000300": 0.342292,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-28",
        "000300": 0.304355,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-29",
        "000300": 0.313129,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-30",
        "000300": 0.298702,
        "CPI": 0.008858
      },
      {
        "date": "2026-07-31",
        "000300": 0.309685,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-03",
        "000300": 0.296835,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-04",
        "000300": 0.31332,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-05",
        "000300": 0.329655,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-06",
        "000300": 0.327701,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-07",
        "000300": 0.340011,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-10",
        "000300": 0.342177,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-11",
        "000300": 0.331263,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-12",
        "000300": 0.339006,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-13",
        "000300": 0.331309,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-14",
        "000300": 0.33186,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-17",
        "000300": 0.35333,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-18",
        "000300": 0.348967,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-19",
        "000300": 0.309828,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-20",
        "000300": 0.310985,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-21",
        "000300": 0.318448,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-24",
        "000300": 0.302529,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-25",
        "000300": 0.299362,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-26",
        "000300": 0.310427,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-27",
        "000300": 0.321697,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-28",
        "000300": 0.315674,
        "CPI": 0.007849
      },
      {
        "date": "2026-08-31",
        "000300": 0.320215,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-01",
        "000300": 0.31632,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-02",
        "000300": 0.298199,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-03",
        "000300": 0.299518,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-04",
        "000300": 0.298225,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-07",
        "000300": 0.305925,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-08",
        "000300": 0.301276,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-09",
        "000300": 0.305233,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-10",
        "000300": 0.298323,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-11",
        "000300": 0.287408,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-14",
        "000300": 0.278824,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-15",
        "000300": 0.270249,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-16",
        "000300": 0.278877,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-17",
        "000300": 0.273136,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-18",
        "000300": 0.28662,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-21",
        "000300": 0.295803,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-22",
        "000300": 0.297237,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-23",
        "000300": 0.289442,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-24",
        "000300": 0.267139,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-28",
        "000300": 0.239054,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-29",
        "000300": 0.240325,
        "CPI": 0.011881
      },
      {
        "date": "2026-09-30",
        "000300": 0.243867,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-08",
        "000300": 0.230354,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-09",
        "000300": 0.232346,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-12",
        "000300": 0.223989,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-13",
        "000300": 0.220478,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-14",
        "000300": 0.203922,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-15",
        "000300": 0.189174,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-16",
        "000300": 0.190487,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-19",
        "000300": 0.191607,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-20",
        "000300": 0.185205,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-21",
        "000300": 0.173737,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-22",
        "000300": 0.152147,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-23",
        "000300": 0.171852,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-26",
        "000300": 0.171342,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-27",
        "000300": 0.155931,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-28",
        "000300": 0.165727,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-29",
        "000300": 0.153729,
        "CPI": 0.013904
      },
      {
        "date": "2026-10-30",
        "000300": 0.137648,
        "CPI": 0.013904
      },
      {
        "date": "2026-11-02",
        "000300": 0.146616,
        "CPI": 0.013904
      },
      {
        "date": "2026-11-03",
        "000300": 0.14432,
        "CPI": 0.013904
      }
    ]
  }
}
```

### get_risk_report

- 请求：`GET /api/agent/tools/risk-report`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_risk_report",
  "generated_at": "2026-11-04T00:10:38.142631+08:00",
  "currency": "CNY",
  "data": {
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "valuation_basis": "latest_formal_nav",
    "max_drawdown": -0.1943877817025733,
    "volatility": 0.5775420941622975,
    "max_single_weight": 0.1756004771257395,
    "max_single_name": "博时黄金ETF联接A",
    "hhi": 0.10146205483130442,
    "equity_weight": 0.754842197487547,
    "bond_weight": 0.12991401599775113,
    "qdii_weight": 0.08648200379853015,
    "flags": [
      {
        "level": "warning",
        "code": "equity_heavy",
        "params": {
          "weight": 0.754842197487547,
          "threshold": 0.7
        },
        "title": "权益/成长风格偏重",
        "detail": "权益类资产占比 75.5%，超过 70%，组合波动可能较大。"
      },
      {
        "level": "danger",
        "code": "drawdown_high",
        "params": {
          "value": -0.1943877817025733,
          "threshold": -0.15
        },
        "title": "历史回撤较大",
        "detail": "组合最大回撤 -19.4%，低于 -15%，属高风险区间。"
      },
      {
        "level": "info",
        "code": "volatility_high",
        "params": {
          "value": 0.5775420941622975,
          "threshold": 0.25
        },
        "title": "波动率偏高",
        "detail": "组合年化波动率约 57.8%，超过 25%。"
      }
    ],
    "data_quality": {
      "missing_nav_fund_count": 0,
      "stale_nav_fund_count": 5,
      "pending_t1_transaction_count": 0,
      "caveats": [
        "5 只基金的最新正式净值可能已过期"
      ]
    }
  }
}
```

### get_industry_exposure

- 请求：`GET /api/agent/tools/industry-exposure`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_industry_exposure",
  "generated_at": "2026-11-04T00:10:38.382101+08:00",
  "currency": "CNY",
  "data": {
    "items": [
      {
        "industry": "制造业",
        "market_value": 22391.953310208402,
        "weight": 0.1992777014108373,
        "funds_count": 10,
        "fund_codes": [
          "001838",
          "005827",
          "008888",
          "011612",
          "020003",
          "100029",
          "110003",
          "110027",
          "161725",
          "163406"
        ],
        "funds": [
          {
            "fund_code": "110003",
            "fund_name": "易方达上证50增强A",
            "market_value": 5626.5291707625
          },
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 4482.690029523
          },
          {
            "fund_code": "161725",
            "fund_name": "招商中证白酒指数(LOF)A",
            "market_value": 4173.7465685412
          },
          {
            "fund_code": "001838",
            "fund_name": "国投瑞银国家安全混合A",
            "market_value": 2420.2483133854003
          },
          {
            "fund_code": "110027",
            "fund_name": "易方达安心回报债券A",
            "market_value": 2093.3335516188
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 1869.0255899999997
          },
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 1069.3392913044
          },
          {
            "fund_code": "020003",
            "fund_name": "国泰金龙行业混合",
            "market_value": 293.1804403056
          },
          {
            "fund_code": "008888",
            "fund_name": "华夏国证半导体芯片ETF联接C",
            "market_value": 271.87163214300006
          },
          {
            "fund_code": "011612",
            "fund_name": "华夏科创50ETF联接A",
            "market_value": 91.9887226245
          }
        ]
      },
      {
        "industry": "金融业",
        "market_value": 3640.1426554374,
        "weight": 0.032395532945864086,
        "funds_count": 5,
        "fund_codes": [
          "005827",
          "020003",
          "100029",
          "110003",
          "161725"
        ],
        "funds": [
          {
            "fund_code": "110003",
            "fund_name": "易方达上证50增强A",
            "market_value": 2229.892573545
          },
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 1276.3476993575998
          },
          {
            "fund_code": "020003",
            "fund_name": "国泰金龙行业混合",
            "market_value": 115.2221359752
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 18.238439999999997
          },
          {
            "fund_code": "161725",
            "fund_name": "招商中证白酒指数(LOF)A",
            "market_value": 0.44180655960000004
          }
        ]
      },
      {
        "industry": "采矿业",
        "market_value": 3399.6308659224997,
        "weight": 0.030255092765735358,
        "funds_count": 8,
        "fund_codes": [
          "001838",
          "005827",
          "008888",
          "011612",
          "020003",
          "100029",
          "110003",
          "161725"
        ],
        "funds": [
          {
            "fund_code": "110003",
            "fund_name": "易方达上证50增强A",
            "market_value": 2026.5864562124998
          },
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 958.4856763409999
          },
          {
            "fund_code": "020003",
            "fund_name": "国泰金龙行业混合",
            "market_value": 406.42663397039996
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 7.875689999999999
          },
          {
            "fund_code": "001838",
            "fund_name": "国投瑞银国家安全混合A",
            "market_value": 0.25640939860000006
          },
          {
            "fund_code": "008888",
            "fund_name": "华夏国证半导体芯片ETF联接C",
            "market_value": 0.0
          },
          {
            "fund_code": "011612",
            "fund_name": "华夏科创50ETF联接A",
            "market_value": 0.0
          },
          {
            "fund_code": "161725",
            "fund_name": "招商中证白酒指数(LOF)A",
            "market_value": 0.0
          }
        ]
      },
      {
        "industry": "非必需消费品",
        "market_value": 3041.61921,
        "weight": 0.02706895983297339,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 2632.49784
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 409.12136999999996
          }
        ]
      },
      {
        "industry": "必需消费品",
        "market_value": 2368.9097400000005,
        "weight": 0.02108216649512792,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 2288.4948000000004
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 80.41493999999999
          }
        ]
      },
      {
        "industry": "科学研究和技术服务业",
        "market_value": 2191.452265791,
        "weight": 0.019502879638432818,
        "funds_count": 3,
        "fund_codes": [
          "001838",
          "110003",
          "163406"
        ],
        "funds": [
          {
            "fund_code": "110003",
            "fund_name": "易方达上证50增强A",
            "market_value": 1292.3535356549999
          },
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 899.0987301360001
          },
          {
            "fund_code": "001838",
            "fund_name": "国投瑞银国家安全混合A",
            "market_value": 0.0
          }
        ]
      },
      {
        "industry": "信息传输、软件和信息技术服务业",
        "market_value": 1509.3789687124,
        "weight": 0.013432752707006593,
        "funds_count": 10,
        "fund_codes": [
          "001838",
          "005827",
          "008888",
          "011612",
          "020003",
          "100029",
          "110003",
          "110027",
          "161725",
          "163406"
        ],
        "funds": [
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 773.9077677120001
          },
          {
            "fund_code": "110003",
            "fund_name": "易方达上证50增强A",
            "market_value": 309.4914779775
          },
          {
            "fund_code": "110027",
            "fund_name": "易方达安心回报债券A",
            "market_value": 198.5309365552
          },
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 79.0061675706
          },
          {
            "fund_code": "020003",
            "fund_name": "国泰金龙行业混合",
            "market_value": 72.4923835128
          },
          {
            "fund_code": "008888",
            "fund_name": "华夏国证半导体芯片ETF联接C",
            "market_value": 39.158465535
          },
          {
            "fund_code": "011612",
            "fund_name": "华夏科创50ETF联接A",
            "market_value": 23.172731653499998
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 12.849809999999998
          },
          {
            "fund_code": "001838",
            "fund_name": "国投瑞银国家安全混合A",
            "market_value": 0.7692281958
          },
          {
            "fund_code": "161725",
            "fund_name": "招商中证白酒指数(LOF)A",
            "market_value": 0.0
          }
        ]
      },
      {
        "industry": "电信服务",
        "market_value": 1337.26671,
        "weight": 0.011901035718064945,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 1069.90776
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 267.35895
          }
        ]
      },
      {
        "industry": "能源",
        "market_value": 1185.85602,
        "weight": 0.010553552814084736,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 928.0308
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 257.82521999999994
          }
        ]
      },
      {
        "industry": "交通运输、仓储和邮政业",
        "market_value": 740.1553359942,
        "weight": 0.00658702936722573,
        "funds_count": 5,
        "fund_codes": [
          "001838",
          "005827",
          "100029",
          "110003",
          "163406"
        ],
        "funds": [
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 259.0667355222
          },
          {
            "fund_code": "110003",
            "fund_name": "易方达上证50增强A",
            "market_value": 181.29207914999998
          },
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 162.17920132199998
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 137.61731999999998
          },
          {
            "fund_code": "001838",
            "fund_name": "国投瑞银国家安全混合A",
            "market_value": 0.0
          }
        ]
      },
      {
        "industry": "信息技术",
        "market_value": 697.78173,
        "weight": 0.0062099244900392005,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 621.9264000000001
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 75.85533
          }
        ]
      },
      {
        "industry": "电力、热力、燃气及水生产和供应业",
        "market_value": 370.582712604,
        "weight": 0.003298009339660897,
        "funds_count": 7,
        "fund_codes": [
          "001838",
          "005827",
          "008888",
          "020003",
          "100029",
          "161725",
          "163406"
        ],
        "funds": [
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 221.34833999999995
          },
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 147.6006696474
          },
          {
            "fund_code": "020003",
            "fund_name": "国泰金龙行业混合",
            "market_value": 0.8644747608000002
          },
          {
            "fund_code": "001838",
            "fund_name": "国投瑞银国家安全混合A",
            "market_value": 0.7692281958
          },
          {
            "fund_code": "008888",
            "fund_name": "华夏国证半导体芯片ETF联接C",
            "market_value": 0.0
          },
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 0.0
          },
          {
            "fund_code": "161725",
            "fund_name": "招商中证白酒指数(LOF)A",
            "market_value": 0.0
          }
        ]
      },
      {
        "industry": "保健",
        "market_value": 348.77151,
        "weight": 0.003103900042463066,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 300.27384
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 48.497669999999985
          }
        ]
      },
      {
        "industry": "金融",
        "market_value": 313.66476,
        "weight": 0.002791466716656895,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 239.05296
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 74.6118
          }
        ]
      },
      {
        "industry": "工业",
        "market_value": 296.46099000000004,
        "weight": 0.0026383613714596205,
        "funds_count": 2,
        "fund_codes": [
          "005827",
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 282.78216000000003
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 13.678829999999998
          }
        ]
      },
      {
        "industry": "租赁和商务服务业",
        "market_value": 197.2091934708,
        "weight": 0.0017550677347129733,
        "funds_count": 1,
        "fund_codes": [
          "100029"
        ],
        "funds": [
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 197.2091934708
          }
        ]
      },
      {
        "industry": "农、林、牧、渔业",
        "market_value": 117.59057498879999,
        "weight": 0.0010465000157294747,
        "funds_count": 1,
        "fund_codes": [
          "100029"
        ],
        "funds": [
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 117.59057498879999
          }
        ]
      },
      {
        "industry": "公用事业",
        "market_value": 108.83712000000001,
        "weight": 0.0009685984425435377,
        "funds_count": 1,
        "fund_codes": [
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 108.83712000000001
          }
        ]
      },
      {
        "industry": "房地产",
        "market_value": 95.33729999999998,
        "weight": 0.0008484564852166797,
        "funds_count": 1,
        "fund_codes": [
          "005827"
        ],
        "funds": [
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 95.33729999999998
          }
        ]
      },
      {
        "industry": "批发和零售业",
        "market_value": 83.15768108130001,
        "weight": 0.0007400636876543535,
        "funds_count": 3,
        "fund_codes": [
          "005827",
          "020003",
          "163406"
        ],
        "funds": [
          {
            "fund_code": "020003",
            "fund_name": "国泰金龙行业混合",
            "market_value": 44.70569477280001
          },
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 20.6280563085
          },
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 17.823929999999997
          }
        ]
      },
      {
        "industry": "建筑业",
        "market_value": 79.66697608800001,
        "weight": 0.0007089980786058108,
        "funds_count": 1,
        "fund_codes": [
          "163406"
        ],
        "funds": [
          {
            "fund_code": "163406",
            "fund_name": "兴全合润混合A",
            "market_value": 79.66697608800001
          }
        ]
      },
      {
        "industry": "房地产业",
        "market_value": 74.71901119079999,
        "weight": 0.0006649635516614371,
        "funds_count": 1,
        "fund_codes": [
          "100029"
        ],
        "funds": [
          {
            "fund_code": "100029",
            "fund_name": "富国天成红利混合",
            "market_value": 74.71901119079999
          }
        ]
      },
      {
        "industry": "材料",
        "market_value": 43.729200000000006,
        "weight": 0.0003891690170933857,
        "funds_count": 1,
        "fund_codes": [
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 43.729200000000006
          }
        ]
      },
      {
        "industry": "水利、环境和公共设施管理业",
        "market_value": 1.65804,
        "weight": 1.4755764960290084e-05,
        "funds_count": 1,
        "fund_codes": [
          "005827"
        ],
        "funds": [
          {
            "fund_code": "005827",
            "fund_name": "易方达蓝筹精选混合",
            "market_value": 1.65804
          }
        ]
      },
      {
        "industry": "其他-GICS未分类",
        "market_value": 0.9717600000000001,
        "weight": 8.648200379853014e-06,
        "funds_count": 1,
        "fund_codes": [
          "110011"
        ],
        "funds": [
          {
            "fund_code": "110011",
            "fund_name": "易方达优质精选混合(QDII)",
            "market_value": 0.9717600000000001
          }
        ]
      }
    ],
    "total_market_value": 112365.57402900002,
    "penetrated_market_value": 44636.50364148959,
    "unpenetrated_market_value": 67729.07038751044,
    "funds_count": 15,
    "funds_with_data": 13,
    "quarter": "2026-09-30",
    "funds_missing": [
      {
        "fund_code": "002610",
        "fund_name": "博时黄金ETF联接A",
        "fund_type": "指数型",
        "market_value": 19731.448412,
        "reason": "no_data",
        "is_equity": true
      },
      {
        "fund_code": "000216",
        "fund_name": "华安黄金ETF联接A",
        "fund_type": "指数型",
        "market_value": 11559.2,
        "reason": "no_data",
        "is_equity": true
      }
    ],
    "equity_total_market_value": 84818.27682200001,
    "equity_penetrated_market_value": 30678.493860013103,
    "ok": true,
    "message": "成功",
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "valuation_basis": "latest_formal_nav",
    "data_quality": {
      "missing_nav_fund_count": 0,
      "stale_nav_fund_count": 5,
      "pending_t1_transaction_count": 0,
      "caveats": [
        "5 只基金的最新正式净值可能已过期"
      ]
    }
  }
}
```

### list_watchlist

- 请求：`GET /api/agent/tools/watchlist`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_watchlist",
  "generated_at": "2026-11-04T00:10:38.623854+08:00",
  "currency": "CNY",
  "data": {
    "count": 2,
    "total": 2,
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 2,
      "has_more": false
    },
    "watchlist": [
      {
        "fund_code": "000005",
        "note": "",
        "group_name": "",
        "added_at": "2026-08-19 22:08:11",
        "revision": 1,
        "fund_name": "嘉实增强信用定期债券",
        "fund_type": "债券型",
        "sector": "其它",
        "tracking_index": ""
      },
      {
        "fund_code": "000001",
        "note": "",
        "group_name": "",
        "added_at": "2026-08-19 22:08:02",
        "revision": 1,
        "fund_name": "华夏成长混合",
        "fund_type": "混合型",
        "sector": "其它",
        "tracking_index": ""
      }
    ]
  }
}
```

### list_alerts

- 请求：`GET /api/agent/tools/alerts`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_alerts",
  "generated_at": "2026-11-04T00:10:38.861616+08:00",
  "currency": "CNY",
  "data": {
    "count": 0,
    "total": 0,
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 0,
      "has_more": false
    },
    "alerts": []
  }
}
```

### list_auto_invest_plans

- 请求：`GET /api/agent/tools/auto-invest-plans`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_auto_invest_plans",
  "generated_at": "2026-11-04T00:10:39.102843+08:00",
  "currency": "CNY",
  "data": {
    "count": 1,
    "total": 1,
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 1,
      "has_more": false
    },
    "plans": [
      {
        "id": 1,
        "fund_code": "011612",
        "amount": 100.0,
        "cadence": "week",
        "day_of_week": 0,
        "day_of_month": null,
        "channel": "理财通",
        "note": "定投",
        "enabled": true,
        "next_run": "2026-11-09",
        "last_run": "2026-11-02",
        "last_tx_id": 70,
        "created_at": "2026-08-19 22:04:54",
        "updated_at": "2026-11-02 09:00:11",
        "fund_name": "华夏科创50ETF联接A",
        "row_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
        "status": "active"
      }
    ]
  }
}
```

### list_transactions（limit=2）

- 请求：`GET /api/agent/tools/transactions?limit=2`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_transactions",
  "generated_at": "2026-11-04T00:10:39.338332+08:00",
  "currency": "CNY",
  "data": {
    "count": 2,
    "total": 46,
    "pagination": {
      "limit": 2,
      "offset": 0,
      "total": 46,
      "has_more": true
    },
    "valuation_basis": "latest_formal_nav",
    "transactions": [
      {
        "fund_code": "011612",
        "action": "buy",
        "date": "2026-11-02",
        "amount": 100.0,
        "shares": 102.39,
        "nav": 0.9755,
        "fee": 0.12,
        "channel": "理财通",
        "note": "定投",
        "is_t1": false,
        "conversion_id": "",
        "source": "",
        "id": 70,
        "fund_name": "华夏科创50ETF联接A",
        "nav_status": "confirmed",
        "amount_semantics": "gross_paid",
        "conversion_role": ""
      },
      {
        "fund_code": "011612",
        "action": "buy",
        "date": "2026-10-26",
        "amount": 100.0,
        "shares": 93.66,
        "nav": 1.0664,
        "fee": 0.12,
        "channel": "理财通",
        "note": "定投",
        "is_t1": false,
        "conversion_id": "",
        "source": "",
        "id": 69,
        "fund_name": "华夏科创50ETF联接A",
        "nav_status": "confirmed",
        "amount_semantics": "gross_paid",
        "conversion_role": ""
      }
    ]
  }
}
```

### search_funds（limit=2）

- 请求：`GET /api/agent/tools/search?keyword=消费&limit=2`
- 响应 HTTP：**0**
- 说明：见响应体
- 响应体：

```json
REQUEST ERROR: UnicodeEncodeError('ascii', 'GET http://<YOUR_SERVER_IP>:8001/api/agent/tools/search?keyword=消费&limit=2 HTTP/1.1', 64, 66, 'ordinal not in range(128)')
```

### screen_funds（limit=2）

- 请求：`GET /api/agent/tools/screen?limit=2`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "screen_funds",
  "generated_at": "2026-11-04T00:10:39.813346+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "",
    "message": "",
    "count": 2,
    "total": 28251,
    "pagination": {
      "limit": 2,
      "offset": 0,
      "total": 28251,
      "has_more": true
    },
    "with_metrics": false,
    "metrics": {
      "requested": false,
      "limit": 30,
      "attempted": 0,
      "succeeded": 0,
      "failed": 0,
      "timed_out": 0,
      "complete": true
    },
    "funds": [
      {
        "code": "000001",
        "name": "华夏成长混合",
        "type": "混合型",
        "sector": "其它",
        "scale": null,
        "manager": "",
        "inception_date": "",
        "returns": null,
        "risk": null,
        "metrics_status": "not_requested"
      },
      {
        "code": "000002",
        "name": "华夏成长混合(后端)",
        "type": "混合型",
        "sector": "其它",
        "scale": null,
        "manager": "",
        "inception_date": "",
        "returns": null,
        "risk": null,
        "metrics_status": "not_requested"
      }
    ]
  }
}
```

### compare_funds

- 请求：`GET /api/agent/tools/funds/compare?codes=005827&codes=161725`
- 响应 HTTP：**200**
- 说明：只读
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "compare_funds",
  "generated_at": "2026-11-04T00:10:40.301217+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "message": "",
    "msg_code": "",
    "count": 2,
    "funds": [
      {
        "code": "005827",
        "name": "易方达蓝筹精选混合",
        "type": "混合型",
        "sector": "其它",
        "inception_date": "2018-09-05",
        "scale": 189.33,
        "manager": "张坤、杨思亮、何一铖",
        "management_fee": 0.0,
        "custodian_fee": null,
        "sales_fee": null,
        "returns": {
          "1w": 0.005606523955147838,
          "1m": -0.06385142005015933,
          "3m": -0.0750117205813409,
          "6m": -0.2171966218897013,
          "1y": -0.30465209948645655,
          "3y": -0.3171322620519159,
          "ytd": -0.25839016270203513,
          "since": 0.3811
        },
        "risk": {
          "max_drawdown": -0.613682092555332,
          "volatility": 0.23556623969702312,
          "sharpe": 0.21999417641146138,
          "calmar": 0.6210055737704918,
          "win_rate": 0.46464646464646464
        },
        "estimate": null,
        "latest_nav": 1.3811,
        "latest_date": "2026-11-03",
        "ok": true,
        "message": "",
        "msg_code": ""
      },
      {
        "code": "161725",
        "name": "招商中证白酒指数(LOF)A",
        "type": "指数型",
        "sector": "消费",
        "inception_date": "2015-05-27",
        "scale": 209.47,
        "manager": "侯昊",
        "management_fee": 0.0,
        "custodian_fee": null,
        "sales_fee": null,
        "returns": {
          "1w": 0.10321864594894575,
          "1m": 0.14516129032258063,
          "3m": 0.10546802594995378,
          "6m": -0.05152671755725188,
          "1y": -0.23977055449330775,
          "3y": -0.4563354603463992,
          "ytd": -0.15988167347513726,
          "since": -0.40359999999999996
        },
        "risk": {
          "max_drawdown": -0.6988339608891049,
          "volatility": 0.35659309139293804,
          "sharpe": 0.005044444032079744,
          "calmar": -0.5775334665855565,
          "win_rate": 0.48201438848920863
        },
        "estimate": null,
        "latest_nav": 0.5964,
        "latest_date": "2026-11-03",
        "ok": true,
        "message": "",
        "msg_code": ""
      }
    ],
    "correlations": [
      [
        1.0,
        0.601307112559571
      ],
      [
        0.601307112559571,
        1.0
      ]
    ],
    "valuation_basis": "latest_formal_nav"
  }
}
```

### get_fund_detail（002610）

- 请求：`GET /api/agent/tools/funds/002610`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_fund_detail",
  "generated_at": "2026-11-04T00:10:40.898957+08:00",
  "currency": "CNY",
  "data": {
    "fund": {
      "fund_code": "002610",
      "fund_name": "博时黄金ETF联接A",
      "fund_type": "指数型",
      "sector": "黄金",
      "tracking_index": "黄金",
      "dividend_method": "cash",
      "purchase_status": "开放申购",
      "daily_limit": 100000000000.0,
      "min_purchase": 10.0,
      "risk_level": "中高风险"
    },
    "valuation_basis": "latest_formal_nav",
    "latest_formal_nav": {
      "date": "2026-11-02",
      "nav": 2.7212,
      "accumulated_nav": null,
      "source": "akshare"
    },
    "annualized_return": 0.6849436698143729,
    "positions": [
      {
        "fund_code": "002610",
        "fund_name": "博时黄金ETF联接A",
        "fund_type": "指数型",
        "sector": "黄金",
        "channel": "招商银行",
        "tracking_index": "黄金",
        "risk_level": "中高风险",
        "held_shares": 7251.01,
        "total_cost": 8000.0,
        "pending_buy_cost": 0.0,
        "avg_cost_nav": 1.1032945755143075,
        "latest_nav": 2.7212,
        "latest_date": "2026-11-02",
        "market_value": 19731.448412,
        "unrealized_pnl": 11731.448412000002,
        "realized_pnl": 0.0,
        "return_rate": 1.4664310515000003,
        "annualized_return": 0.6849436698143729,
        "weight": 0.1756004771257395,
        "buy_count": 2,
        "sell_count": 0,
        "dividend_count": 0,
        "dividend_total": 0.0,
        "total_pnl": 11731.448412000002,
        "is_open": true
      }
    ],
    "recent_nav": [
      {
        "date": "2026-09-14",
        "nav": 3.0361,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-15",
        "nav": 3.02,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-16",
        "nav": 3.0462,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-17",
        "nav": 3.0402,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-18",
        "nav": 3.079,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-21",
        "nav": 3.0522,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-22",
        "nav": 3.0327,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-23",
        "nav": 3.0387,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-24",
        "nav": 3.0129,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-28",
        "nav": 2.9341,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-29",
        "nav": 2.9206,
        "accumulated_nav": null
      },
      {
        "date": "2026-09-30",
        "nav": 2.9513,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-08",
        "nav": 2.9028,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-09",
        "nav": 2.9411,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-12",
        "nav": 2.9382,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-13",
        "nav": 2.9414,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-14",
        "nav": 2.9113,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-15",
        "nav": 2.9044,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-16",
        "nav": 2.9318,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-19",
        "nav": 2.9301,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-20",
        "nav": 2.8947,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-21",
        "nav": 2.8869,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-22",
        "nav": 2.8643,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-23",
        "nav": 2.8114,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-26",
        "nav": 2.8022,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-27",
        "nav": 2.7993,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-28",
        "nav": 2.8265,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-29",
        "nav": 2.8153,
        "accumulated_nav": null
      },
      {
        "date": "2026-10-30",
        "nav": 2.7818,
        "accumulated_nav": null
      },
      {
        "date": "2026-11-02",
        "nav": 2.7212,
        "accumulated_nav": null
      }
    ]
  }
}
```

### get_transaction（id=70）

- 请求：`GET /api/agent/tools/transactions/70`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_transaction",
  "generated_at": "2026-11-04T00:10:41.143457+08:00",
  "currency": "CNY",
  "data": {
    "fund_code": "011612",
    "action": "buy",
    "date": "2026-11-02",
    "amount": 100.0,
    "shares": 102.39,
    "nav": 0.9755,
    "fee": 0.12,
    "channel": "理财通",
    "note": "定投",
    "is_t1": false,
    "conversion_id": "",
    "source": "",
    "id": 70,
    "fund_name": "华夏科创50ETF联接A",
    "nav_status": "confirmed",
    "amount_semantics": "gross_paid",
    "conversion_role": "",
    "valuation_basis": "latest_formal_nav",
    "row_digest": "3e45cfd9eb9d1fa18646f4c7b95e3322036705d52604c99235570b0e9d363a93"
  }
}
```

### run_dca_backtest

- 请求：`POST /api/agent/tools/backtest/dca`
- 请求体：

```json
{
  "fund_codes": [
    "005827"
  ],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "amount_per_period": 1000,
  "cadence": "month"
}
```
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "run_dca_backtest",
  "generated_at": "2026-11-04T00:10:41.499955+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "message": "",
    "simulation_note": "定投与一次性投入为历史模拟，不是组合配置建议，也不代表未来收益；未模拟分红、拆分与红利再投资。",
    "requested": {
      "start_date": "2024-01-01",
      "end_date": "2024-12-31",
      "cadence": "month",
      "amount_per_period": 1000.0,
      "include_lumpsum": true
    },
    "fund_count": 1,
    "result_count": 2,
    "failed_count": 0,
    "results": [
      {
        "fund_code": "005827",
        "fund_name": "易方达蓝筹精选混合",
        "strategy": "dca",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "cadence": "month",
        "amount_per_period": 1000.0,
        "total_periods": 12,
        "invested_capital": 12000.0,
        "total_fees": 81.39,
        "final_value": 12186.24,
        "redemption_fee": 63.39,
        "net_final_value": 12122.85,
        "total_return": 0.0102,
        "annualized_return": 0.0191,
        "max_drawdown": -0.103,
        "sharpe_ratio": -0.0081,
        "curve": [
          {
            "date": "2024-01-02",
            "invested": 1000.0,
            "value": 998.5,
            "return": -0.0015
          },
          {
            "date": "2024-01-03",
            "invested": 1000.0,
            "value": 994.99,
            "return": -0.005
          },
          {
            "date": "2024-01-04",
            "invested": 1000.0,
            "value": 985.01,
            "return": -0.015
          },
          {
            "date": "2024-01-05",
            "invested": 1000.0,
            "value": 978.94,
            "return": -0.0211
          },
          {
            "date": "2024-01-08",
            "invested": 1000.0,
            "value": 962.71,
            "return": -0.0373
          },
          {
            "date": "2024-01-09",
            "invested": 1000.0,
            "value": 956.95,
            "return": -0.0431
          },
          {
            "date": "2024-01-10",
            "invested": 1000.0,
            "value": 959.38,
            "return": -0.0406
          },
          {
            "date": "2024-01-11",
            "invested": 1000.0,
            "value": 973.53,
            "return": -0.0265
          },
          {
            "date": "2024-01-12",
            "invested": 1000.0,
            "value": 969.01,
            "return": -0.031
          },
          {
            "date": "2024-01-15",
            "invested": 1000.0,
            "value": 969.01,
            "return": -0.031
          },
          {
            "date": "2024-01-16",
            "invested": 1000.0,
            "value": 962.83,
            "return": -0.0372
          },
          {
            "date": "2024-01-17",
            "invested": 1000.0,
            "value": 933.4,
            "return": -0.0666
          },
          {
            "date": "2024-01-18",
            "invested": 1000.0,
            "value": 948.15,
            "return": -0.0519
          },
          {
            "date": "2024-01-19",
            "invested": 1000.0,
            "value": 945.89,
            "return": -0.0541
          },
          {
            "date": "2024-01-22",
            "invested": 1000.0,
            "value": 928.65,
            "return": -0.0714
          },
          {
            "date": "2024-01-23",
            "invested": 1000.0,
            "value": 937.92,
            "return": -0.0621
          },
          {
            "date": "2024-01-24",
            "invested": 1000.0,
            "value": 952.72,
            "return": -0.0473
          },
          {
            "date": "2024-01-25",
            "invested": 1000.0,
            "value": 971.81,
            "return": -0.0282
          },
          {
            "date": "2024-01-26",
            "invested": 1000.0,
            "value": 951.3,
            "return": -0.0487
          },
          {
            "date": "2024-01-29",
            "invested": 1000.0,
            "value": 951.36,
            "return": -0.0486
          },
          {
            "date": "2024-01-30",
            "invested": 1000.0,
            "value": 926.63,
            "return": -0.0734
          },
          {
            "date": "2024-01-31",
            "invested": 1000.0,
            "value": 910.69,
            "return": -0.0893
          },
          {
            "date": "2024-02-01",
            "invested": 2000.0,
            "value": 1914.43,
            "return": -0.0428
          },
          {
            "date": "2024-02-02",
            "invested": 2000.0,
            "value": 1886.1,
            "return": -0.057
          },
          {
            "date": "2024-02-05",
            "invested": 2000.0,
            "value": 1900.76,
            "return": -0.0496
          },
          {
            "date": "2024-02-06",
            "invested": 2000.0,
            "value": 1978.42,
            "return": -0.0108
          },
          {
            "date": "2024-02-07",
            "invested": 2000.0,
            "value": 2005.75,
            "return": 0.0029
          },
          {
            "date": "2024-02-08",
            "invested": 2000.0,
            "value": 1989.1,
            "return": -0.0054
          },
          {
            "date": "2024-02-19",
            "invested": 2000.0,
            "value": 2000.16,
            "return": 0.0001
          },
          {
            "date": "2024-02-20",
            "invested": 2000.0,
            "value": 2000.91,
            "return": 0.0005
          },
          {
            "date": "2024-02-21",
            "invested": 2000.0,
            "value": 2061.55,
            "return": 0.0308
          },
          {
            "date": "2024-02-22",
            "invested": 2000.0,
            "value": 2087.27,
            "return": 0.0436
          },
          {
            "date": "2024-02-23",
            "invested": 2000.0,
            "value": 2093.73,
            "return": 0.0469
          },
          {
            "date": "2024-02-26",
            "invested": 2000.0,
            "value": 2083.29,
            "return": 0.0416
          },
          {
            "date": "2024-02-27",
            "invested": 2000.0,
            "value": 2087.64,
            "return": 0.0438
          },
          {
            "date": "2024-02-28",
            "invested": 2000.0,
            "value": 2061.42,
            "return": 0.0307
          },
          {
            "date": "2024-02-29",
            "invested": 2000.0,
            "value": 2082.17,
            "return": 0.0411
          },
          {
            "date": "2024-03-01",
            "invested": 3000.0,
            "value": 3093.84,
            "return": 0.0313
          },
          {
            "date": "2024-03-04",
            "invested": 3000.0,
            "value": 3107.6,
            "return": 0.0359
          },
          {
            "date": "2024-03-05",
            "invested": 3000.0,
            "value": 3084.67,
            "return": 0.0282
          },
          {
            "date": "2024-03-06",
            "invested": 3000.0,
            "value": 3095.68,
            "return": 0.0319
          },
          {
            "date": "2024-03-07",
            "invested": 3000.0,
            "value": 3045.96,
            "return": 0.0153
          },
          {
            "date": "2024-03-08",
            "invested": 3000.0,
            "value": 3054.58,
            "return": 0.0182
          },
          {
            "date": "2024-03-11",
            "invested": 3000.0,
            "value": 3112.19,
            "return": 0.0374
          },
          {
            "date": "2024-03-12",
            "invested": 3000.0,
            "value": 3228.14,
            "return": 0.076
          },
          {
            "date": "2024-03-13",
            "invested": 3000.0,
            "value": 3220.25,
            "return": 0.0734
          },
          {
            "date": "2024-03-14",
            "invested": 3000.0,
            "value": 3207.96,
            "return": 0.0693
          },
          {
            "date": "2024-03-15",
            "invested": 3000.0,
            "value": 3176.22,
            "return": 0.0587
          },
          {
            "date": "2024-03-18",
            "invested": 3000.0,
            "value": 3178.24,
            "return": 0.0594
          },
          {
            "date": "2024-03-19",
            "invested": 3000.0,
            "value": 3184.84,
            "return": 0.0616
          },
          {
            "date": "2024-03-20",
            "invested": 3000.0,
            "value": 3190.53,
            "return": 0.0635
          },
          {
            "date": "2024-03-21",
            "invested": 3000.0,
            "value": 3207.96,
            "return": 0.0693
          },
          {
            "date": "2024-03-22",
            "invested": 3000.0,
            "value": 3141.0,
            "return": 0.047
          },
          {
            "date": "2024-03-25",
            "invested": 3000.0,
            "value": 3141.18,
            "return": 0.0471
          },
          {
            "date": "2024-03-26",
            "invested": 3000.0,
            "value": 3180.07,
            "return": 0.06
          },
          {
            "date": "2024-03-27",
            "invested": 3000.0,
            "value": 3149.8,
            "return": 0.0499
          },
          {
            "date": "2024-03-28",
            "invested": 3000.0,
            "value": 3173.29,
            "return": 0.0578
          },
          {
            "date": "2024-03-29",
            "invested": 3000.0,
            "value": 3172.55,
            "return": 0.0575
          },
          {
            "date": "2024-04-01",
            "invested": 4000.0,
            "value": 4209.58,
            "return": 0.0524
          },
          {
            "date": "2024-04-02",
            "invested": 4000.0,
            "value": 4252.87,
            "return": 0.0632
          },
          {
            "date": "2024-04-03",
            "invested": 4000.0,
            "value": 4227.62,
            "return": 0.0569
          },
          {
            "date": "2024-04-08",
            "invested": 4000.0,
            "value": 4138.87,
            "return": 0.0347
          },
          {
            "date": "2024-04-09",
            "invested": 4000.0,
            "value": 4135.5,
            "return": 0.0339
          },
          {
            "date": "2024-04-10",
            "invested": 4000.0,
            "value": 4141.75,
            "return": 0.0354
          },
          {
            "date": "2024-04-11",
            "invested": 4000.0,
            "value": 4140.55,
            "return": 0.0351
          },
          {
            "date": "2024-04-12",
            "invested": 4000.0,
            "value": 4076.33,
            "return": 0.0191
          },
          {
            "date": "2024-04-15",
            "invested": 4000.0,
            "value": 4137.67,
            "return": 0.0344
          },
          {
            "date": "2024-04-16",
            "invested": 4000.0,
            "value": 4072.48,
            "return": 0.0181
          },
          {
            "date": "2024-04-17",
            "invested": 4000.0,
            "value": 4066.95,
            "return": 0.0167
          },
          {
            "date": "2024-04-18",
            "invested": 4000.0,
            "value": 4080.18,
            "return": 0.02
          },
          {
            "date": "2024-04-19",
            "invested": 4000.0,
            "value": 4042.18,
            "return": 0.0105
          },
          {
            "date": "2024-04-22",
            "invested": 4000.0,
            "value": 4111.21,
            "return": 0.0278
          },
          {
            "date": "2024-04-23",
            "invested": 4000.0,
            "value": 4195.39,
            "return": 0.0488
          },
          {
            "date": "2024-04-24",
            "invested": 4000.0,
            "value": 4256.72,
            "return": 0.0642
          },
          {
            "date": "2024-04-25",
            "invested": 4000.0,
            "value": 4251.67,
            "return": 0.0629
          },
          {
            "date": "2024-04-26",
            "invested": 4000.0,
            "value": 4342.83,
            "return": 0.0857
          },
          {
            "date": "2024-04-29",
            "invested": 4000.0,
            "value": 4330.08,
            "return": 0.0825
          },
          {
            "date": "2024-04-30",
            "invested": 4000.0,
            "value": 4325.99,
            "return": 0.0815
          },
          {
            "date": "2024-05-06",
            "invested": 5000.0,
            "value": 5469.29,
            "return": 0.0939
          },
          {
            "date": "2024-05-07",
            "invested": 5000.0,
            "value": 5447.22,
            "return": 0.0894
          },
          {
            "date": "2024-05-08",
            "invested": 5000.0,
            "value": 5390.72,
            "return": 0.0781
          },
          {
            "date": "2024-05-09",
            "invested": 5000.0,
            "value": 5448.1,
            "return": 0.0896
          },
          {
            "date": "2024-05-10",
            "invested": 5000.0,
            "value": 5480.47,
            "return": 0.0961
          },
          {
            "date": "2024-05-13",
            "invested": 5000.0,
            "value": 5431.03,
            "return": 0.0862
          },
          {
            "date": "2024-05-14",
            "invested": 5000.0,
            "value": 5431.33,
            "return": 0.0863
          },
          {
            "date": "2024-05-15",
            "invested": 5000.0,
            "value": 5424.56,
            "return": 0.0849
          },
          {
            "date": "2024-05-16",
            "invested": 5000.0,
            "value": 5467.23,
            "return": 0.0934
          },
          {
            "date": "2024-05-17",
            "invested": 5000.0,
            "value": 5507.24,
            "return": 0.1014
          },
          {
            "date": "2024-05-20",
            "invested": 5000.0,
            "value": 5532.55,
            "return": 0.1065
          },
          {
            "date": "2024-05-21",
            "invested": 5000.0,
            "value": 5465.17,
            "return": 0.093
          },
          {
            "date": "2024-05-22",
            "invested": 5000.0,
            "value": 5437.51,
            "return": 0.0875
          },
          {
            "date": "2024-05-23",
            "invested": 5000.0,
            "value": 5386.9,
            "return": 0.0774
          },
          {
            "date": "2024-05-24",
            "invested": 5000.0,
            "value": 5324.23,
            "return": 0.0648
          },
          {
            "date": "2024-05-27",
            "invested": 5000.0,
            "value": 5368.36,
            "return": 0.0737
          },
          {
            "date": "2024-05-28",
            "invested": 5000.0,
            "value": 5354.83,
            "return": 0.071
          },
          {
            "date": "2024-05-29",
            "invested": 5000.0,
            "value": 5311.28,
            "return": 0.0623
          },
          {
            "date": "2024-05-30",
            "invested": 5000.0,
            "value": 5218.89,
            "return": 0.0438
          },
          {
            "date": "2024-05-31",
            "invested": 5000.0,
            "value": 5199.18,
            "return": 0.0398
          },
          {
            "date": "2024-06-03",
            "invested": 6000.0,
            "value": 6243.87,
            "return": 0.0406
          },
          {
            "date": "2024-06-04",
            "invested": 6000.0,
            "value": 6284.85,
            "return": 0.0475
          },
          {
            "date": "2024-06-05",
            "invested": 6000.0,
            "value": 6258.58,
            "return": 0.0431
          },
          {
            "date": "2024-06-06",
            "invested": 6000.0,
            "value": 6263.13,
            "return": 0.0439
          },
          {
            "date": "2024-06-07",
            "invested": 6000.0,
            "value": 6198.34,
            "return": 0.0331
          },
          {
            "date": "2024-06-11",
            "invested": 6000.0,
            "value": 6137.05,
            "return": 0.0228
          },
          {
            "date": "2024-06-12",
            "invested": 6000.0,
            "value": 6112.18,
            "return": 0.0187
          },
          {
            "date": "2024-06-13",
            "invested": 6000.0,
            "value": 6108.68,
            "return": 0.0181
          },
          {
            "date": "2024-06-14",
            "invested": 6000.0,
            "value": 6103.42,
            "return": 0.0172
          },
          {
            "date": "2024-06-17",
            "invested": 6000.0,
            "value": 6085.56,
            "return": 0.0143
          },
          {
            "date": "2024-06-18",
            "invested": 6000.0,
            "value": 6027.42,
            "return": 0.0046
          },
          {
            "date": "2024-06-19",
            "invested": 6000.0,
            "value": 6118.48,
            "return": 0.0197
          },
          {
            "date": "2024-06-20",
            "invested": 6000.0,
            "value": 6090.81,
            "return": 0.0151
          },
          {
            "date": "2024-06-21",
            "invested": 6000.0,
            "value": 6001.5,
            "return": 0.0002
          },
          {
            "date": "2024-06-24",
            "invested": 6000.0,
            "value": 6000.45,
            "return": 0.0001
          },
          {
            "date": "2024-06-25",
            "invested": 6000.0,
            "value": 6016.21,
            "return": 0.0027
          },
          {
            "date": "2024-06-26",
            "invested": 6000.0,
            "value": 6010.61,
            "return": 0.0018
          },
          {
            "date": "2024-06-27",
            "invested": 6000.0,
            "value": 5931.1,
            "return": -0.0115
          },
          {
            "date": "2024-06-28",
            "invested": 6000.0,
            "value": 5879.61,
            "return": -0.0201
          },
          {
            "date": "2024-06-30",
            "invested": 6000.0,
            "value": 5879.26,
            "return": -0.0201
          },
          {
            "date": "2024-07-01",
            "invested": 7000.0,
            "value": 6864.1,
            "return": -0.0194
          },
          {
            "date": "2024-07-02",
            "invested": 7000.0,
            "value": 6907.96,
            "return": -0.0131
          },
          {
            "date": "2024-07-03",
            "invested": 7000.0,
            "value": 6936.24,
            "return": -0.0091
          },
          {
            "date": "2024-07-04",
            "invested": 7000.0,
            "value": 6921.48,
            "return": -0.0112
          },
          {
            "date": "2024-07-05",
            "invested": 7000.0,
            "value": 6858.77,
            "return": -0.0202
          },
          {
            "date": "2024-07-08",
            "invested": 7000.0,
            "value": 6749.75,
            "return": -0.0358
          },
          {
            "date": "2024-07-09",
            "invested": 7000.0,
            "value": 6756.72,
            "return": -0.0348
          },
          {
            "date": "2024-07-10",
            "invested": 7000.0,
            "value": 6714.91,
            "return": -0.0407
          },
          {
            "date": "2024-07-11",
            "invested": 7000.0,
            "value": 6825.98,
            "return": -0.0249
          },
          {
            "date": "2024-07-12",
            "invested": 7000.0,
            "value": 6927.22,
            "return": -0.0104
          },
          {
            "date": "2024-07-15",
            "invested": 7000.0,
            "value": 6858.36,
            "return": -0.0202
          },
          {
            "date": "2024-07-16",
            "invested": 7000.0,
            "value": 6799.34,
            "return": -0.0287
          },
          {
            "date": "2024-07-17",
            "invested": 7000.0,
            "value": 6850.99,
            "return": -0.0213
          },
          {
            "date": "2024-07-18",
            "invested": 7000.0,
            "value": 6861.23,
            "return": -0.0198
          },
          {
            "date": "2024-07-19",
            "invested": 7000.0,
            "value": 6835.41,
            "return": -0.0235
          },
          {
            "date": "2024-07-22",
            "invested": 7000.0,
            "value": 6825.98,
            "return": -0.0249
          },
          {
            "date": "2024-07-23",
            "invested": 7000.0,
            "value": 6655.48,
            "return": -0.0492
          },
          {
            "date": "2024-07-24",
            "invested": 7000.0,
            "value": 6583.75,
            "return": -0.0595
          },
          {
            "date": "2024-07-25",
            "invested": 7000.0,
            "value": 6483.74,
            "return": -0.0738
          },
          {
            "date": "2024-07-26",
            "invested": 7000.0,
            "value": 6471.45,
            "return": -0.0755
          },
          {
            "date": "2024-07-29",
            "invested": 7000.0,
            "value": 6447.67,
            "return": -0.0789
          },
          {
            "date": "2024-07-30",
            "invested": 7000.0,
            "value": 6391.93,
            "return": -0.0869
          },
          {
            "date": "2024-07-31",
            "invested": 7000.0,
            "value": 6582.52,
            "return": -0.0596
          },
          {
            "date": "2024-08-01",
            "invested": 8000.0,
            "value": 7498.64,
            "return": -0.0627
          },
          {
            "date": "2024-08-02",
            "invested": 8000.0,
            "value": 7402.18,
            "return": -0.0747
          },
          {
            "date": "2024-08-05",
            "invested": 8000.0,
            "value": 7408.8,
            "return": -0.0739
          },
          {
            "date": "2024-08-06",
            "invested": 8000.0,
            "value": 7442.37,
            "return": -0.0697
          },
          {
            "date": "2024-08-07",
            "invested": 8000.0,
            "value": 7537.41,
            "return": -0.0578
          },
          {
            "date": "2024-08-08",
            "invested": 8000.0,
            "value": 7597.46,
            "return": -0.0503
          },
          {
            "date": "2024-08-09",
            "invested": 8000.0,
            "value": 7612.59,
            "return": -0.0484
          },
          {
            "date": "2024-08-12",
            "invested": 8000.0,
            "value": 7601.24,
            "return": -0.0498
          },
          {
            "date": "2024-08-13",
            "invested": 8000.0,
            "value": 7573.35,
            "return": -0.0533
          },
          {
            "date": "2024-08-14",
            "invested": 8000.0,
            "value": 7494.86,
            "return": -0.0631
          },
          {
            "date": "2024-08-15",
            "invested": 8000.0,
            "value": 7464.59,
            "return": -0.0669
          },
          {
            "date": "2024-08-16",
            "invested": 8000.0,
            "value": 7527.48,
            "return": -0.0591
          },
          {
            "date": "2024-08-19",
            "invested": 8000.0,
            "value": 7522.28,
            "return": -0.0597
          },
          {
            "date": "2024-08-20",
            "invested": 8000.0,
            "value": 7474.05,
            "return": -0.0657
          },
          {
            "date": "2024-08-21",
            "invested": 8000.0,
            "value": 7448.04,
            "return": -0.069
          },
          {
            "date": "2024-08-22",
            "invested": 8000.0,
            "value": 7445.21,
            "return": -0.0693
          },
          {
            "date": "2024-08-23",
            "invested": 8000.0,
            "value": 7443.79,
            "return": -0.0695
          },
          {
            "date": "2024-08-26",
            "invested": 8000.0,
            "value": 7432.44,
            "return": -0.0709
          },
          {
            "date": "2024-08-27",
            "invested": 8000.0,
            "value": 7454.66,
            "return": -0.0682
          },
          {
            "date": "2024-08-28",
            "invested": 8000.0,
            "value": 7300.99,
            "return": -0.0874
          },
          {
            "date": "2024-08-29",
            "invested": 8000.0,
            "value": 7430.08,
            "return": -0.0712
          },
          {
            "date": "2024-08-30",
            "invested": 8000.0,
            "value": 7621.57,
            "return": -0.0473
          },
          {
            "date": "2024-09-02",
            "invested": 9000.0,
            "value": 8418.17,
            "return": -0.0646
          },
          {
            "date": "2024-09-03",
            "invested": 9000.0,
            "value": 8470.75,
            "return": -0.0588
          },
          {
            "date": "2024-09-04",
            "invested": 9000.0,
            "value": 8351.12,
            "return": -0.0721
          },
          {
            "date": "2024-09-05",
            "invested": 9000.0,
            "value": 8345.75,
            "return": -0.0727
          },
          {
            "date": "2024-09-06",
            "invested": 9000.0,
            "value": 8277.62,
            "return": -0.0803
          },
          {
            "date": "2024-09-09",
            "invested": 9000.0,
            "value": 8148.33,
            "return": -0.0946
          },
          {
            "date": "2024-09-10",
            "invested": 9000.0,
            "value": 8131.17,
            "return": -0.0965
          },
          {
            "date": "2024-09-11",
            "invested": 9000.0,
            "value": 8108.1,
            "return": -0.0991
          },
          {
            "date": "2024-09-12",
            "invested": 9000.0,
            "value": 8026.02,
            "return": -0.1082
          },
          {
            "date": "2024-09-13",
            "invested": 9000.0,
            "value": 7967.01,
            "return": -0.1148
          },
          {
            "date": "2024-09-18",
            "invested": 9000.0,
            "value": 7973.98,
            "return": -0.114
          },
          {
            "date": "2024-09-19",
            "invested": 9000.0,
            "value": 8139.21,
            "return": -0.0956
          },
          {
            "date": "2024-09-20",
            "invested": 9000.0,
            "value": 8159.6,
            "return": -0.0934
          },
          {
            "date": "2024-09-23",
            "invested": 9000.0,
            "value": 8147.8,
            "return": -0.0947
          },
          {
            "date": "2024-09-24",
            "invested": 9000.0,
            "value": 8572.14,
            "return": -0.0475
          },
          {
            "date": "2024-09-25",
            "invested": 9000.0,
            "value": 8596.82,
            "return": -0.0448
          },
          {
            "date": "2024-09-26",
            "invested": 9000.0,
            "value": 9170.83,
            "return": 0.019
          },
          {
            "date": "2024-09-27",
            "invested": 9000.0,
            "value": 9736.26,
            "return": 0.0818
          },
          {
            "date": "2024-09-30",
            "invested": 9000.0,
            "value": 10366.07,
            "return": 0.1518
          },
          {
            "date": "2024-10-08",
            "invested": 10000.0,
            "value": 11494.4,
            "return": 0.1494
          },
          {
            "date": "2024-10-09",
            "invested": 10000.0,
            "value": 10914.54,
            "return": 0.0915
          },
          {
            "date": "2024-10-10",
            "invested": 10000.0,
            "value": 11182.43,
            "return": 0.1182
          },
          {
            "date": "2024-10-11",
            "invested": 10000.0,
            "value": 11022.05,
            "return": 0.1022
          },
          {
            "date": "2024-10-14",
            "invested": 10000.0,
            "value": 10942.74,
            "return": 0.0943
          },
          {
            "date": "2024-10-15",
            "invested": 10000.0,
            "value": 10536.19,
            "return": 0.0536
          },
          {
            "date": "2024-10-16",
            "invested": 10000.0,
            "value": 10490.36,
            "return": 0.049
          },
          {
            "date": "2024-10-17",
            "invested": 10000.0,
            "value": 10310.0,
            "return": 0.031
          },
          {
            "date": "2024-10-18",
            "invested": 10000.0,
            "value": 10641.94,
            "return": 0.0642
          },
          {
            "date": "2024-10-21",
            "invested": 10000.0,
            "value": 10502.7,
            "return": 0.0503
          },
          {
            "date": "2024-10-22",
            "invested": 10000.0,
            "value": 10639.59,
            "return": 0.064
          },
          {
            "date": "2024-10-23",
            "invested": 10000.0,
            "value": 10804.67,
            "return": 0.0805
          },
          {
            "date": "2024-10-24",
            "invested": 10000.0,
            "value": 10647.81,
            "return": 0.0648
          },
          {
            "date": "2024-10-25",
            "invested": 10000.0,
            "value": 10668.37,
            "return": 0.0668
          },
          {
            "date": "2024-10-28",
            "invested": 10000.0,
            "value": 10821.12,
            "return": 0.0821
          },
          {
            "date": "2024-10-29",
            "invested": 10000.0,
            "value": 10736.52,
            "return": 0.0737
          },
          {
            "date": "2024-10-30",
            "invested": 10000.0,
            "value": 10579.66,
            "return": 0.058
          },
          {
            "date": "2024-10-31",
            "invested": 10000.0,
            "value": 10482.72,
            "return": 0.0483
          },
          {
            "date": "2024-11-01",
            "invested": 11000.0,
            "value": 11586.39,
            "return": 0.0533
          },
          {
            "date": "2024-11-04",
            "invested": 11000.0,
            "value": 11670.61,
            "return": 0.061
          },
          {
            "date": "2024-11-05",
            "invested": 11000.0,
            "value": 11981.13,
            "return": 0.0892
          },
          {
            "date": "2024-11-06",
            "invested": 11000.0,
            "value": 11828.12,
            "return": 0.0753
          },
          {
            "date": "2024-11-07",
            "invested": 11000.0,
            "value": 12406.09,
            "return": 0.1278
          },
          {
            "date": "2024-11-08",
            "invested": 11000.0,
            "value": 12142.5,
            "return": 0.1039
          },
          {
            "date": "2024-11-11",
            "invested": 11000.0,
            "value": 11996.56,
            "return": 0.0906
          },
          {
            "date": "2024-11-12",
            "invested": 11000.0,
            "value": 11783.76,
            "return": 0.0713
          },
          {
            "date": "2024-11-13",
            "invested": 11000.0,
            "value": 11772.83,
            "return": 0.0703
          },
          {
            "date": "2024-11-14",
            "invested": 11000.0,
            "value": 11655.82,
            "return": 0.0596
          },
          {
            "date": "2024-11-15",
            "invested": 11000.0,
            "value": 11603.1,
            "return": 0.0548
          },
          {
            "date": "2024-11-18",
            "invested": 11000.0,
            "value": 11506.67,
            "return": 0.0461
          },
          {
            "date": "2024-11-19",
            "invested": 11000.0,
            "value": 11489.95,
            "return": 0.0445
          },
          {
            "date": "2024-11-20",
            "invested": 11000.0,
            "value": 11520.81,
            "return": 0.0473
          },
          {
            "date": "2024-11-21",
            "invested": 11000.0,
            "value": 11483.52,
            "return": 0.044
          },
          {
            "date": "2024-11-22",
            "invested": 11000.0,
            "value": 11182.0,
            "return": 0.0165
          },
          {
            "date": "2024-11-25",
            "invested": 11000.0,
            "value": 11173.64,
            "return": 0.0158
          },
          {
            "date": "2024-11-26",
            "invested": 11000.0,
            "value": 11233.43,
            "return": 0.0212
          },
          {
            "date": "2024-11-27",
            "invested": 11000.0,
            "value": 11457.81,
            "return": 0.0416
          },
          {
            "date": "2024-11-28",
            "invested": 11000.0,
            "value": 11288.08,
            "return": 0.0262
          },
          {
            "date": "2024-11-29",
            "invested": 11000.0,
            "value": 11355.58,
            "return": 0.0323
          },
          {
            "date": "2024-12-02",
            "invested": 12000.0,
            "value": 12386.23,
            "return": 0.0322
          },
          {
            "date": "2024-12-03",
            "invested": 12000.0,
            "value": 12420.49,
            "return": 0.035
          },
          {
            "date": "2024-12-04",
            "invested": 12000.0,
            "value": 12379.94,
            "return": 0.0317
          },
          {
            "date": "2024-12-05",
            "invested": 12000.0,
            "value": 12279.94,
            "return": 0.0233
          },
          {
            "date": "2024-12-06",
            "invested": 12000.0,
            "value": 12462.45,
            "return": 0.0385
          },
          {
            "date": "2024-12-09",
            "invested": 12000.0,
            "value": 12577.83,
            "return": 0.0482
          },
          {
            "date": "2024-12-10",
            "invested": 12000.0,
            "value": 12633.07,
            "return": 0.0528
          },
          {
            "date": "2024-12-11",
            "invested": 12000.0,
            "value": 12578.53,
            "return": 0.0482
          },
          {
            "date": "2024-12-12",
            "invested": 12000.0,
            "value": 12799.5,
            "return": 0.0666
          },
          {
            "date": "2024-12-13",
            "invested": 12000.0,
            "value": 12443.57,
            "return": 0.037
          },
          {
            "date": "2024-12-16",
            "invested": 12000.0,
            "value": 12285.53,
            "return": 0.0238
          },
          {
            "date": "2024-12-17",
            "invested": 12000.0,
            "value": 12310.71,
            "return": 0.0259
          },
          {
            "date": "2024-12-18",
            "invested": 12000.0,
            "value": 12365.95,
            "return": 0.0305
          },
          {
            "date": "2024-12-19",
            "invested": 12000.0,
            "value": 12288.33,
            "return": 0.024
          },
          {
            "date": "2024-12-20",
            "invested": 12000.0,
            "value": 12266.65,
            "return": 0.0222
          },
          {
            "date": "2024-12-23",
            "invested": 12000.0,
            "value": 12227.49,
            "return": 0.019
          },
          {
            "date": "2024-12-24",
            "invested": 12000.0,
            "value": 12326.09,
            "return": 0.0272
          },
          {
            "date": "2024-12-25",
            "invested": 12000.0,
            "value": 12305.81,
            "return": 0.0255
          },
          {
            "date": "2024-12-26",
            "invested": 12000.0,
            "value": 12302.32,
            "return": 0.0252
          },
          {
            "date": "2024-12-27",
            "invested": 12000.0,
            "value": 12261.76,
            "return": 0.0218
          },
          {
            "date": "2024-12-30",
            "invested": 12000.0,
            "value": 12182.04,
            "return": 0.0152
          },
          {
            "date": "2024-12-31",
            "invested": 12000.0,
            "value": 12186.24,
            "return": 0.0155
          }
        ],
        "periods_detail": [],
        "status": "ok",
        "code": "",
        "message": "",
        "data_source": "database",
        "data_start": "2024-01-02",
        "data_end": "2024-12-31",
        "valuation_date": "2024-12-31",
        "skipped_periods": 0,
        "fee_ok": true,
        "caveats": [
          "定投与一次性投入均为历史模拟，不代表未来收益，也不构成配置建议。",
          "未模拟分红、拆分与红利再投资，仅使用单位净值。",
          "最大回撤与夏普比率基于投入后的市值曲线，定投现金流会影响可比性。"
        ],
        "curve_points": 243,
        "periods_detail_count": 12
      },
      {
        "fund_code": "005827",
        "fund_name": "易方达蓝筹精选混合",
        "strategy": "lumpsum",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "cadence": "",
        "amount_per_period": 12000.0,
        "total_periods": 1,
        "invested_capital": 12000.0,
        "total_fees": 80.16,
        "final_value": 12432.15,
        "redemption_fee": 62.16,
        "net_final_value": 12369.99,
        "total_return": 0.0308,
        "annualized_return": 0.0309,
        "max_drawdown": -0.2102,
        "sharpe_ratio": 0.0039,
        "curve": [
          {
            "date": "2024-01-02",
            "invested": 12000.0,
            "value": 11982.0,
            "return": -0.0015
          },
          {
            "date": "2024-01-03",
            "invested": 12000.0,
            "value": 11939.91,
            "return": -0.005
          },
          {
            "date": "2024-01-04",
            "invested": 12000.0,
            "value": 11820.06,
            "return": -0.015
          },
          {
            "date": "2024-01-05",
            "invested": 12000.0,
            "value": 11747.3,
            "return": -0.0211
          },
          {
            "date": "2024-01-08",
            "invested": 12000.0,
            "value": 11552.54,
            "return": -0.0373
          },
          {
            "date": "2024-01-09",
            "invested": 12000.0,
            "value": 11483.34,
            "return": -0.0431
          },
          {
            "date": "2024-01-10",
            "invested": 12000.0,
            "value": 11512.59,
            "return": -0.0406
          },
          {
            "date": "2024-01-11",
            "invested": 12000.0,
            "value": 11682.38,
            "return": -0.0265
          },
          {
            "date": "2024-01-12",
            "invested": 12000.0,
            "value": 11628.16,
            "return": -0.031
          },
          {
            "date": "2024-01-15",
            "invested": 12000.0,
            "value": 11628.16,
            "return": -0.031
          },
          {
            "date": "2024-01-16",
            "invested": 12000.0,
            "value": 11553.97,
            "return": -0.0372
          },
          {
            "date": "2024-01-17",
            "invested": 12000.0,
            "value": 11200.84,
            "return": -0.0666
          },
          {
            "date": "2024-01-18",
            "invested": 12000.0,
            "value": 11377.76,
            "return": -0.0519
          },
          {
            "date": "2024-01-19",
            "invested": 12000.0,
            "value": 11350.66,
            "return": -0.0541
          },
          {
            "date": "2024-01-22",
            "invested": 12000.0,
            "value": 11143.77,
            "return": -0.0714
          },
          {
            "date": "2024-01-23",
            "invested": 12000.0,
            "value": 11255.06,
            "return": -0.0621
          },
          {
            "date": "2024-01-24",
            "invested": 12000.0,
            "value": 11432.69,
            "return": -0.0473
          },
          {
            "date": "2024-01-25",
            "invested": 12000.0,
            "value": 11661.69,
            "return": -0.0282
          },
          {
            "date": "2024-01-26",
            "invested": 12000.0,
            "value": 11415.57,
            "return": -0.0487
          },
          {
            "date": "2024-01-29",
            "invested": 12000.0,
            "value": 11416.29,
            "return": -0.0486
          },
          {
            "date": "2024-01-30",
            "invested": 12000.0,
            "value": 11119.52,
            "return": -0.0734
          },
          {
            "date": "2024-01-31",
            "invested": 12000.0,
            "value": 10928.33,
            "return": -0.0893
          },
          {
            "date": "2024-02-01",
            "invested": 12000.0,
            "value": 10991.11,
            "return": -0.0841
          },
          {
            "date": "2024-02-02",
            "invested": 12000.0,
            "value": 10828.46,
            "return": -0.0976
          },
          {
            "date": "2024-02-05",
            "invested": 12000.0,
            "value": 10912.64,
            "return": -0.0906
          },
          {
            "date": "2024-02-06",
            "invested": 12000.0,
            "value": 11358.5,
            "return": -0.0535
          },
          {
            "date": "2024-02-07",
            "invested": 12000.0,
            "value": 11515.45,
            "return": -0.0404
          },
          {
            "date": "2024-02-08",
            "invested": 12000.0,
            "value": 11419.85,
            "return": -0.0483
          },
          {
            "date": "2024-02-19",
            "invested": 12000.0,
            "value": 11483.34,
            "return": -0.0431
          },
          {
            "date": "2024-02-20",
            "invested": 12000.0,
            "value": 11487.62,
            "return": -0.0427
          },
          {
            "date": "2024-02-21",
            "invested": 12000.0,
            "value": 11835.76,
            "return": -0.0137
          },
          {
            "date": "2024-02-22",
            "invested": 12000.0,
            "value": 11983.43,
            "return": -0.0014
          },
          {
            "date": "2024-02-23",
            "invested": 12000.0,
            "value": 12020.52,
            "return": 0.0017
          },
          {
            "date": "2024-02-26",
            "invested": 12000.0,
            "value": 11960.6,
            "return": -0.0033
          },
          {
            "date": "2024-02-27",
            "invested": 12000.0,
            "value": 11985.57,
            "return": -0.0012
          },
          {
            "date": "2024-02-28",
            "invested": 12000.0,
            "value": 11835.04,
            "return": -0.0137
          },
          {
            "date": "2024-02-29",
            "invested": 12000.0,
            "value": 11954.18,
            "return": -0.0038
          },
          {
            "date": "2024-03-01",
            "invested": 12000.0,
            "value": 12029.8,
            "return": 0.0025
          },
          {
            "date": "2024-03-04",
            "invested": 12000.0,
            "value": 12083.3,
            "return": 0.0069
          },
          {
            "date": "2024-03-05",
            "invested": 12000.0,
            "value": 11994.13,
            "return": -0.0005
          },
          {
            "date": "2024-03-06",
            "invested": 12000.0,
            "value": 12036.93,
            "return": 0.0031
          },
          {
            "date": "2024-03-07",
            "invested": 12000.0,
            "value": 11843.6,
            "return": -0.013
          },
          {
            "date": "2024-03-08",
            "invested": 12000.0,
            "value": 11877.13,
            "return": -0.0102
          },
          {
            "date": "2024-03-11",
            "invested": 12000.0,
            "value": 12101.14,
            "return": 0.0084
          },
          {
            "date": "2024-03-12",
            "invested": 12000.0,
            "value": 12551.99,
            "return": 0.046
          },
          {
            "date": "2024-03-13",
            "invested": 12000.0,
            "value": 12521.32,
            "return": 0.0434
          },
          {
            "date": "2024-03-14",
            "invested": 12000.0,
            "value": 12473.52,
            "return": 0.0395
          },
          {
            "date": "2024-03-15",
            "invested": 12000.0,
            "value": 12350.11,
            "return": 0.0292
          },
          {
            "date": "2024-03-18",
            "invested": 12000.0,
            "value": 12357.95,
            "return": 0.0298
          },
          {
            "date": "2024-03-19",
            "invested": 12000.0,
            "value": 12383.64,
            "return": 0.032
          },
          {
            "date": "2024-03-20",
            "invested": 12000.0,
            "value": 12405.75,
            "return": 0.0338
          },
          {
            "date": "2024-03-21",
            "invested": 12000.0,
            "value": 12473.52,
            "return": 0.0395
          },
          {
            "date": "2024-03-22",
            "invested": 12000.0,
            "value": 12213.14,
            "return": 0.0178
          },
          {
            "date": "2024-03-25",
            "invested": 12000.0,
            "value": 12213.85,
            "return": 0.0178
          },
          {
            "date": "2024-03-26",
            "invested": 12000.0,
            "value": 12365.09,
            "return": 0.0304
          },
          {
            "date": "2024-03-27",
            "invested": 12000.0,
            "value": 12247.38,
            "return": 0.0206
          },
          {
            "date": "2024-03-28",
            "invested": 12000.0,
            "value": 12338.69,
            "return": 0.0282
          },
          {
            "date": "2024-03-29",
            "invested": 12000.0,
            "value": 12335.84,
            "return": 0.028
          },
          {
            "date": "2024-04-01",
            "invested": 12000.0,
            "value": 12485.65,
            "return": 0.0405
          },
          {
            "date": "2024-04-02",
            "invested": 12000.0,
            "value": 12614.06,
            "return": 0.0512
          },
          {
            "date": "2024-04-03",
            "invested": 12000.0,
            "value": 12539.15,
            "return": 0.0449
          },
          {
            "date": "2024-04-08",
            "invested": 12000.0,
            "value": 12275.91,
            "return": 0.023
          },
          {
            "date": "2024-04-09",
            "invested": 12000.0,
            "value": 12265.93,
            "return": 0.0222
          },
          {
            "date": "2024-04-10",
            "invested": 12000.0,
            "value": 12284.47,
            "return": 0.0237
          },
          {
            "date": "2024-04-11",
            "invested": 12000.0,
            "value": 12280.91,
            "return": 0.0234
          },
          {
            "date": "2024-04-12",
            "invested": 12000.0,
            "value": 12090.43,
            "return": 0.0075
          },
          {
            "date": "2024-04-15",
            "invested": 12000.0,
            "value": 12272.35,
            "return": 0.0227
          },
          {
            "date": "2024-04-16",
            "invested": 12000.0,
            "value": 12079.02,
            "return": 0.0066
          },
          {
            "date": "2024-04-17",
            "invested": 12000.0,
            "value": 12062.61,
            "return": 0.0052
          },
          {
            "date": "2024-04-18",
            "invested": 12000.0,
            "value": 12101.85,
            "return": 0.0085
          },
          {
            "date": "2024-04-19",
            "invested": 12000.0,
            "value": 11989.13,
            "return": -0.0009
          },
          {
            "date": "2024-04-22",
            "invested": 12000.0,
            "value": 12193.88,
            "return": 0.0162
          },
          {
            "date": "2024-04-23",
            "invested": 12000.0,
            "value": 12443.56,
            "return": 0.037
          },
          {
            "date": "2024-04-24",
            "invested": 12000.0,
            "value": 12625.47,
            "return": 0.0521
          },
          {
            "date": "2024-04-25",
            "invested": 12000.0,
            "value": 12610.49,
            "return": 0.0509
          },
          {
            "date": "2024-04-26",
            "invested": 12000.0,
            "value": 12880.86,
            "return": 0.0734
          },
          {
            "date": "2024-04-29",
            "invested": 12000.0,
            "value": 12843.05,
            "return": 0.0703
          },
          {
            "date": "2024-04-30",
            "invested": 12000.0,
            "value": 12830.93,
            "return": 0.0692
          },
          {
            "date": "2024-05-06",
            "invested": 12000.0,
            "value": 13260.38,
            "return": 0.105
          },
          {
            "date": "2024-05-07",
            "invested": 12000.0,
            "value": 13206.88,
            "return": 0.1006
          },
          {
            "date": "2024-05-08",
            "invested": 12000.0,
            "value": 13069.91,
            "return": 0.0892
          },
          {
            "date": "2024-05-09",
            "invested": 12000.0,
            "value": 13209.02,
            "return": 0.1008
          },
          {
            "date": "2024-05-10",
            "invested": 12000.0,
            "value": 13287.49,
            "return": 0.1073
          },
          {
            "date": "2024-05-13",
            "invested": 12000.0,
            "value": 13167.64,
            "return": 0.0973
          },
          {
            "date": "2024-05-14",
            "invested": 12000.0,
            "value": 13168.36,
            "return": 0.0974
          },
          {
            "date": "2024-05-15",
            "invested": 12000.0,
            "value": 13151.95,
            "return": 0.096
          },
          {
            "date": "2024-05-16",
            "invested": 12000.0,
            "value": 13255.39,
            "return": 0.1046
          },
          {
            "date": "2024-05-17",
            "invested": 12000.0,
            "value": 13352.41,
            "return": 0.1127
          },
          {
            "date": "2024-05-20",
            "invested": 12000.0,
            "value": 13413.76,
            "return": 0.1178
          },
          {
            "date": "2024-05-21",
            "invested": 12000.0,
            "value": 13250.4,
            "return": 0.1042
          },
          {
            "date": "2024-05-22",
            "invested": 12000.0,
            "value": 13183.34,
            "return": 0.0986
          },
          {
            "date": "2024-05-23",
            "invested": 12000.0,
            "value": 13060.64,
            "return": 0.0884
          },
          {
            "date": "2024-05-24",
            "invested": 12000.0,
            "value": 12908.69,
            "return": 0.0757
          },
          {
            "date": "2024-05-27",
            "invested": 12000.0,
            "value": 13015.69,
            "return": 0.0846
          },
          {
            "date": "2024-05-28",
            "invested": 12000.0,
            "value": 12982.88,
            "return": 0.0819
          },
          {
            "date": "2024-05-29",
            "invested": 12000.0,
            "value": 12877.3,
            "return": 0.0731
          },
          {
            "date": "2024-05-30",
            "invested": 12000.0,
            "value": 12653.29,
            "return": 0.0544
          },
          {
            "date": "2024-05-31",
            "invested": 12000.0,
            "value": 12605.5,
            "return": 0.0505
          },
          {
            "date": "2024-06-03",
            "invested": 12000.0,
            "value": 12717.5,
            "return": 0.0598
          },
          {
            "date": "2024-06-04",
            "invested": 12000.0,
            "value": 12800.96,
            "return": 0.0667
          },
          {
            "date": "2024-06-05",
            "invested": 12000.0,
            "value": 12747.46,
            "return": 0.0623
          },
          {
            "date": "2024-06-06",
            "invested": 12000.0,
            "value": 12756.74,
            "return": 0.0631
          },
          {
            "date": "2024-06-07",
            "invested": 12000.0,
            "value": 12624.76,
            "return": 0.0521
          },
          {
            "date": "2024-06-11",
            "invested": 12000.0,
            "value": 12499.92,
            "return": 0.0417
          },
          {
            "date": "2024-06-12",
            "invested": 12000.0,
            "value": 12449.27,
            "return": 0.0374
          },
          {
            "date": "2024-06-13",
            "invested": 12000.0,
            "value": 12442.13,
            "return": 0.0368
          },
          {
            "date": "2024-06-14",
            "invested": 12000.0,
            "value": 12431.43,
            "return": 0.036
          },
          {
            "date": "2024-06-17",
            "invested": 12000.0,
            "value": 12395.05,
            "return": 0.0329
          },
          {
            "date": "2024-06-18",
            "invested": 12000.0,
            "value": 12276.63,
            "return": 0.0231
          },
          {
            "date": "2024-06-19",
            "invested": 12000.0,
            "value": 12462.11,
            "return": 0.0385
          },
          {
            "date": "2024-06-20",
            "invested": 12000.0,
            "value": 12405.75,
            "return": 0.0338
          },
          {
            "date": "2024-06-21",
            "invested": 12000.0,
            "value": 12223.84,
            "return": 0.0187
          },
          {
            "date": "2024-06-24",
            "invested": 12000.0,
            "value": 12221.7,
            "return": 0.0185
          },
          {
            "date": "2024-06-25",
            "invested": 12000.0,
            "value": 12253.8,
            "return": 0.0211
          },
          {
            "date": "2024-06-26",
            "invested": 12000.0,
            "value": 12242.39,
            "return": 0.0202
          },
          {
            "date": "2024-06-27",
            "invested": 12000.0,
            "value": 12080.45,
            "return": 0.0067
          },
          {
            "date": "2024-06-28",
            "invested": 12000.0,
            "value": 11975.58,
            "return": -0.002
          },
          {
            "date": "2024-06-30",
            "invested": 12000.0,
            "value": 11974.87,
            "return": -0.0021
          },
          {
            "date": "2024-07-01",
            "invested": 12000.0,
            "value": 11947.04,
            "return": -0.0044
          },
          {
            "date": "2024-07-02",
            "invested": 12000.0,
            "value": 12023.38,
            "return": 0.0019
          },
          {
            "date": "2024-07-03",
            "invested": 12000.0,
            "value": 12072.6,
            "return": 0.006
          },
          {
            "date": "2024-07-04",
            "invested": 12000.0,
            "value": 12046.92,
            "return": 0.0039
          },
          {
            "date": "2024-07-05",
            "invested": 12000.0,
            "value": 11937.77,
            "return": -0.0052
          },
          {
            "date": "2024-07-08",
            "invested": 12000.0,
            "value": 11748.01,
            "return": -0.021
          },
          {
            "date": "2024-07-09",
            "invested": 12000.0,
            "value": 11760.14,
            "return": -0.02
          },
          {
            "date": "2024-07-10",
            "invested": 12000.0,
            "value": 11687.37,
            "return": -0.0261
          },
          {
            "date": "2024-07-11",
            "invested": 12000.0,
            "value": 11880.7,
            "return": -0.0099
          },
          {
            "date": "2024-07-12",
            "invested": 12000.0,
            "value": 12056.91,
            "return": 0.0047
          },
          {
            "date": "2024-07-15",
            "invested": 12000.0,
            "value": 11937.06,
            "return": -0.0052
          },
          {
            "date": "2024-07-16",
            "invested": 12000.0,
            "value": 11834.33,
            "return": -0.0138
          },
          {
            "date": "2024-07-17",
            "invested": 12000.0,
            "value": 11924.22,
            "return": -0.0063
          },
          {
            "date": "2024-07-18",
            "invested": 12000.0,
            "value": 11942.05,
            "return": -0.0048
          },
          {
            "date": "2024-07-19",
            "invested": 12000.0,
            "value": 11897.11,
            "return": -0.0086
          },
          {
            "date": "2024-07-22",
            "invested": 12000.0,
            "value": 11880.7,
            "return": -0.0099
          },
          {
            "date": "2024-07-23",
            "invested": 12000.0,
            "value": 11583.93,
            "return": -0.0347
          },
          {
            "date": "2024-07-24",
            "invested": 12000.0,
            "value": 11459.09,
            "return": -0.0451
          },
          {
            "date": "2024-07-25",
            "invested": 12000.0,
            "value": 11285.02,
            "return": -0.0596
          },
          {
            "date": "2024-07-26",
            "invested": 12000.0,
            "value": 11263.62,
            "return": -0.0614
          },
          {
            "date": "2024-07-29",
            "invested": 12000.0,
            "value": 11222.25,
            "return": -0.0648
          },
          {
            "date": "2024-07-30",
            "invested": 12000.0,
            "value": 11125.23,
            "return": -0.0729
          },
          {
            "date": "2024-07-31",
            "invested": 12000.0,
            "value": 11456.95,
            "return": -0.0453
          },
          {
            "date": "2024-08-01",
            "invested": 12000.0,
            "value": 11313.56,
            "return": -0.0572
          },
          {
            "date": "2024-08-02",
            "invested": 12000.0,
            "value": 11168.03,
            "return": -0.0693
          },
          {
            "date": "2024-08-05",
            "invested": 12000.0,
            "value": 11178.02,
            "return": -0.0685
          },
          {
            "date": "2024-08-06",
            "invested": 12000.0,
            "value": 11228.67,
            "return": -0.0643
          },
          {
            "date": "2024-08-07",
            "invested": 12000.0,
            "value": 11372.06,
            "return": -0.0523
          },
          {
            "date": "2024-08-08",
            "invested": 12000.0,
            "value": 11462.66,
            "return": -0.0448
          },
          {
            "date": "2024-08-09",
            "invested": 12000.0,
            "value": 11485.48,
            "return": -0.0429
          },
          {
            "date": "2024-08-12",
            "invested": 12000.0,
            "value": 11468.36,
            "return": -0.0443
          },
          {
            "date": "2024-08-13",
            "invested": 12000.0,
            "value": 11426.27,
            "return": -0.0478
          },
          {
            "date": "2024-08-14",
            "invested": 12000.0,
            "value": 11307.85,
            "return": -0.0577
          },
          {
            "date": "2024-08-15",
            "invested": 12000.0,
            "value": 11262.2,
            "return": -0.0615
          },
          {
            "date": "2024-08-16",
            "invested": 12000.0,
            "value": 11357.08,
            "return": -0.0536
          },
          {
            "date": "2024-08-19",
            "invested": 12000.0,
            "value": 11349.23,
            "return": -0.0542
          },
          {
            "date": "2024-08-20",
            "invested": 12000.0,
            "value": 11276.46,
            "return": -0.0603
          },
          {
            "date": "2024-08-21",
            "invested": 12000.0,
            "value": 11237.23,
            "return": -0.0636
          },
          {
            "date": "2024-08-22",
            "invested": 12000.0,
            "value": 11232.95,
            "return": -0.0639
          },
          {
            "date": "2024-08-23",
            "invested": 12000.0,
            "value": 11230.81,
            "return": -0.0641
          },
          {
            "date": "2024-08-26",
            "invested": 12000.0,
            "value": 11213.69,
            "return": -0.0655
          },
          {
            "date": "2024-08-27",
            "invested": 12000.0,
            "value": 11247.21,
            "return": -0.0627
          },
          {
            "date": "2024-08-28",
            "invested": 12000.0,
            "value": 11015.36,
            "return": -0.0821
          },
          {
            "date": "2024-08-29",
            "invested": 12000.0,
            "value": 11210.12,
            "return": -0.0658
          },
          {
            "date": "2024-08-30",
            "invested": 12000.0,
            "value": 11499.04,
            "return": -0.0417
          },
          {
            "date": "2024-09-02",
            "invested": 12000.0,
            "value": 11194.42,
            "return": -0.0671
          },
          {
            "date": "2024-09-03",
            "invested": 12000.0,
            "value": 11264.34,
            "return": -0.0613
          },
          {
            "date": "2024-09-04",
            "invested": 12000.0,
            "value": 11105.25,
            "return": -0.0746
          },
          {
            "date": "2024-09-05",
            "invested": 12000.0,
            "value": 11098.12,
            "return": -0.0752
          },
          {
            "date": "2024-09-06",
            "invested": 12000.0,
            "value": 11007.52,
            "return": -0.0827
          },
          {
            "date": "2024-09-09",
            "invested": 12000.0,
            "value": 10835.59,
            "return": -0.097
          },
          {
            "date": "2024-09-10",
            "invested": 12000.0,
            "value": 10812.76,
            "return": -0.0989
          },
          {
            "date": "2024-09-11",
            "invested": 12000.0,
            "value": 10782.09,
            "return": -0.1015
          },
          {
            "date": "2024-09-12",
            "invested": 12000.0,
            "value": 10672.94,
            "return": -0.1106
          },
          {
            "date": "2024-09-13",
            "invested": 12000.0,
            "value": 10594.47,
            "return": -0.1171
          },
          {
            "date": "2024-09-18",
            "invested": 12000.0,
            "value": 10603.74,
            "return": -0.1164
          },
          {
            "date": "2024-09-19",
            "invested": 12000.0,
            "value": 10823.46,
            "return": -0.098
          },
          {
            "date": "2024-09-20",
            "invested": 12000.0,
            "value": 10850.57,
            "return": -0.0958
          },
          {
            "date": "2024-09-23",
            "invested": 12000.0,
            "value": 10834.88,
            "return": -0.0971
          },
          {
            "date": "2024-09-24",
            "invested": 12000.0,
            "value": 11399.17,
            "return": -0.0501
          },
          {
            "date": "2024-09-25",
            "invested": 12000.0,
            "value": 11431.98,
            "return": -0.0473
          },
          {
            "date": "2024-09-26",
            "invested": 12000.0,
            "value": 12195.3,
            "return": 0.0163
          },
          {
            "date": "2024-09-27",
            "invested": 12000.0,
            "value": 12947.21,
            "return": 0.0789
          },
          {
            "date": "2024-09-30",
            "invested": 12000.0,
            "value": 13784.72,
            "return": 0.1487
          },
          {
            "date": "2024-10-08",
            "invested": 12000.0,
            "value": 13957.36,
            "return": 0.1631
          },
          {
            "date": "2024-10-09",
            "invested": 12000.0,
            "value": 13253.25,
            "return": 0.1044
          },
          {
            "date": "2024-10-10",
            "invested": 12000.0,
            "value": 13578.55,
            "return": 0.1315
          },
          {
            "date": "2024-10-11",
            "invested": 12000.0,
            "value": 13383.8,
            "return": 0.1153
          },
          {
            "date": "2024-10-14",
            "invested": 12000.0,
            "value": 13287.49,
            "return": 0.1073
          },
          {
            "date": "2024-10-15",
            "invested": 12000.0,
            "value": 12793.83,
            "return": 0.0662
          },
          {
            "date": "2024-10-16",
            "invested": 12000.0,
            "value": 12738.19,
            "return": 0.0615
          },
          {
            "date": "2024-10-17",
            "invested": 12000.0,
            "value": 12519.18,
            "return": 0.0433
          },
          {
            "date": "2024-10-18",
            "invested": 12000.0,
            "value": 12922.24,
            "return": 0.0769
          },
          {
            "date": "2024-10-21",
            "invested": 12000.0,
            "value": 12753.17,
            "return": 0.0628
          },
          {
            "date": "2024-10-22",
            "invested": 12000.0,
            "value": 12919.39,
            "return": 0.0766
          },
          {
            "date": "2024-10-23",
            "invested": 12000.0,
            "value": 13119.85,
            "return": 0.0933
          },
          {
            "date": "2024-10-24",
            "invested": 12000.0,
            "value": 12929.37,
            "return": 0.0774
          },
          {
            "date": "2024-10-25",
            "invested": 12000.0,
            "value": 12954.34,
            "return": 0.0795
          },
          {
            "date": "2024-10-28",
            "invested": 12000.0,
            "value": 13139.82,
            "return": 0.095
          },
          {
            "date": "2024-10-29",
            "invested": 12000.0,
            "value": 13037.1,
            "return": 0.0864
          },
          {
            "date": "2024-10-30",
            "invested": 12000.0,
            "value": 12846.62,
            "return": 0.0706
          },
          {
            "date": "2024-10-31",
            "invested": 12000.0,
            "value": 12728.91,
            "return": 0.0607
          },
          {
            "date": "2024-11-01",
            "invested": 12000.0,
            "value": 12856.61,
            "return": 0.0714
          },
          {
            "date": "2024-11-04",
            "invested": 12000.0,
            "value": 12950.06,
            "return": 0.0792
          },
          {
            "date": "2024-11-05",
            "invested": 12000.0,
            "value": 13294.63,
            "return": 0.1079
          },
          {
            "date": "2024-11-06",
            "invested": 12000.0,
            "value": 13124.84,
            "return": 0.0937
          },
          {
            "date": "2024-11-07",
            "invested": 12000.0,
            "value": 13766.17,
            "return": 0.1472
          },
          {
            "date": "2024-11-08",
            "invested": 12000.0,
            "value": 13473.69,
            "return": 0.1228
          },
          {
            "date": "2024-11-11",
            "invested": 12000.0,
            "value": 13311.75,
            "return": 0.1093
          },
          {
            "date": "2024-11-12",
            "invested": 12000.0,
            "value": 13075.62,
            "return": 0.0896
          },
          {
            "date": "2024-11-13",
            "invested": 12000.0,
            "value": 13063.49,
            "return": 0.0886
          },
          {
            "date": "2024-11-14",
            "invested": 12000.0,
            "value": 12933.65,
            "return": 0.0778
          },
          {
            "date": "2024-11-15",
            "invested": 12000.0,
            "value": 12875.16,
            "return": 0.0729
          },
          {
            "date": "2024-11-18",
            "invested": 12000.0,
            "value": 12768.15,
            "return": 0.064
          },
          {
            "date": "2024-11-19",
            "invested": 12000.0,
            "value": 12749.6,
            "return": 0.0625
          },
          {
            "date": "2024-11-20",
            "invested": 12000.0,
            "value": 12783.84,
            "return": 0.0653
          },
          {
            "date": "2024-11-21",
            "invested": 12000.0,
            "value": 12742.47,
            "return": 0.0619
          },
          {
            "date": "2024-11-22",
            "invested": 12000.0,
            "value": 12407.89,
            "return": 0.034
          },
          {
            "date": "2024-11-25",
            "invested": 12000.0,
            "value": 12398.62,
            "return": 0.0332
          },
          {
            "date": "2024-11-26",
            "invested": 12000.0,
            "value": 12464.96,
            "return": 0.0387
          },
          {
            "date": "2024-11-27",
            "invested": 12000.0,
            "value": 12713.93,
            "return": 0.0595
          },
          {
            "date": "2024-11-28",
            "invested": 12000.0,
            "value": 12525.6,
            "return": 0.0438
          },
          {
            "date": "2024-11-29",
            "invested": 12000.0,
            "value": 12600.5,
            "return": 0.05
          },
          {
            "date": "2024-12-02",
            "invested": 12000.0,
            "value": 12636.17,
            "return": 0.053
          },
          {
            "date": "2024-12-03",
            "invested": 12000.0,
            "value": 12671.13,
            "return": 0.0559
          },
          {
            "date": "2024-12-04",
            "invested": 12000.0,
            "value": 12629.75,
            "return": 0.0525
          },
          {
            "date": "2024-12-05",
            "invested": 12000.0,
            "value": 12527.74,
            "return": 0.044
          },
          {
            "date": "2024-12-06",
            "invested": 12000.0,
            "value": 12713.93,
            "return": 0.0595
          },
          {
            "date": "2024-12-09",
            "invested": 12000.0,
            "value": 12831.64,
            "return": 0.0693
          },
          {
            "date": "2024-12-10",
            "invested": 12000.0,
            "value": 12888.0,
            "return": 0.074
          },
          {
            "date": "2024-12-11",
            "invested": 12000.0,
            "value": 12832.35,
            "return": 0.0694
          },
          {
            "date": "2024-12-12",
            "invested": 12000.0,
            "value": 13057.78,
            "return": 0.0881
          },
          {
            "date": "2024-12-13",
            "invested": 12000.0,
            "value": 12694.67,
            "return": 0.0579
          },
          {
            "date": "2024-12-16",
            "invested": 12000.0,
            "value": 12533.45,
            "return": 0.0445
          },
          {
            "date": "2024-12-17",
            "invested": 12000.0,
            "value": 12559.13,
            "return": 0.0466
          },
          {
            "date": "2024-12-18",
            "invested": 12000.0,
            "value": 12615.49,
            "return": 0.0513
          },
          {
            "date": "2024-12-19",
            "invested": 12000.0,
            "value": 12536.3,
            "return": 0.0447
          },
          {
            "date": "2024-12-20",
            "invested": 12000.0,
            "value": 12514.18,
            "return": 0.0428
          },
          {
            "date": "2024-12-23",
            "invested": 12000.0,
            "value": 12474.24,
            "return": 0.0395
          },
          {
            "date": "2024-12-24",
            "invested": 12000.0,
            "value": 12574.82,
            "return": 0.0479
          },
          {
            "date": "2024-12-25",
            "invested": 12000.0,
            "value": 12554.13,
            "return": 0.0462
          },
          {
            "date": "2024-12-26",
            "invested": 12000.0,
            "value": 12550.57,
            "return": 0.0459
          },
          {
            "date": "2024-12-27",
            "invested": 12000.0,
            "value": 12509.19,
            "return": 0.0424
          },
          {
            "date": "2024-12-30",
            "invested": 12000.0,
            "value": 12427.87,
            "return": 0.0357
          },
          {
            "date": "2024-12-31",
            "invested": 12000.0,
            "value": 12432.15,
            "return": 0.036
          }
        ],
        "periods_detail": [],
        "status": "ok",
        "code": "",
        "message": "",
        "data_source": "database",
        "data_start": "2024-01-02",
        "data_end": "2024-12-31",
        "valuation_date": "2024-12-31",
        "skipped_periods": 0,
        "fee_ok": true,
        "caveats": [
          "定投与一次性投入均为历史模拟，不代表未来收益，也不构成配置建议。",
          "未模拟分红、拆分与红利再投资，仅使用单位净值。",
          "最大回撤与夏普比率基于投入后的市值曲线，定投现金流会影响可比性。"
        ],
        "curve_points": 243,
        "periods_detail_count": 0
      }
    ]
  }
}
```

### get_operation_proposal（不存在 → 404）

- 请求：`GET /api/agent/tools/proposals/999999`
- 响应 HTTP：**404**
- 响应体：

```json
{
  "detail": {
    "code": "not_found",
    "message": "未找到提案",
    "proposal_id": 999999
  }
}
```

## 2. 鉴权边界

### 无令牌访问 capabilities

- 请求：`GET /api/agent/tools/capabilities`
- 响应 HTTP：**401**
- 说明：期望 401
- 响应体：

```json
{
  "detail": "缺少 Agent token"
}
```

### 错误令牌访问 capabilities

- 请求：`GET /api/agent/tools/capabilities`
- 响应 HTTP：**401**
- 说明：期望 401
- 响应体：

```json
{
  "detail": "Agent token 无效"
}
```

## 3. 预检接口（只读，不写账本）

### precheck_transactions

- 请求：`POST /api/agent/tools/precheck/transactions`
- 请求体：

```json
{
  "input": {
    "format": "items",
    "items": [
      {
        "fund_code": "011612",
        "action": "buy",
        "date": "2026-11-03",
        "amount": 100,
        "shares": 102.39,
        "nav": 0.9755,
        "fee": 0.12,
        "channel": "理财通"
      }
    ]
  }
}
```
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "precheck_transactions",
  "generated_at": "2026-11-04T00:10:42.467325+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "total": 1,
    "valid": 1,
    "invalid": 0,
    "duplicate": 0,
    "items": [
      {
        "index": 0,
        "status": "valid",
        "transaction": {
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "action": "buy",
          "action_label": "买入",
          "date": "2026-11-03",
          "amount": 100.0,
          "shares": 102.39,
          "nav": 0.9755,
          "fee": 0.12,
          "channel": "理财通",
          "note": "",
          "is_t1": false
        },
        "fund_resolution": {
          "input": "011612",
          "status": "verified",
          "resolved_code": "011612",
          "candidates": [],
          "fund_name": "华夏科创50ETF联接A"
        },
        "duplicate": null,
        "issues": [],
        "proposal_ready": true
      }
    ],
    "parse_errors": []
  }
}
```

### precheck_reconciliation

- 请求：`POST /api/agent/tools/precheck/reconciliation`
- 请求体：

```json
{
  "input": {
    "channel": "理财通",
    "holdings": [
      {
        "fund_code": "011612",
        "shares": 1000
      }
    ]
  }
}
```
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "precheck_reconciliation",
  "generated_at": "2026-11-04T00:10:43.011351+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "channel": "理财通",
    "items": [
      {
        "fund_code": "011612",
        "fund_name": "华夏科创50ETF联接A",
        "recorded_shares": 1001.54,
        "screenshot_shares": 1000.0,
        "delta": -1.54,
        "status": "sell",
        "suggested_tx": {
          "fund_code": "011612",
          "action": "sell",
          "date": null,
          "amount": 1.45,
          "shares": 1.54,
          "nav": 0.9399,
          "fee": 0,
          "channel": "理财通",
          "note": "截图对账调整",
          "is_t1": false
        },
        "fund_resolution": {
          "input": "011612",
          "status": "verified",
          "resolved_code": "011612",
          "candidates": [],
          "fund_name": "华夏科创50ETF联接A"
        },
        "issues": [],
        "proposal_ready": true
      },
      {
        "fund_code": "110003",
        "fund_name": "易方达上证50增强A",
        "recorded_shares": 6324.51,
        "screenshot_shares": 0.0,
        "delta": -6324.51,
        "status": "maybe_sold",
        "suggested_tx": {
          "fund_code": "110003",
          "action": "sell",
          "date": null,
          "amount": 12949.43,
          "shares": 6324.51,
          "nav": 2.0475,
          "fee": 0,
          "channel": "理财通",
          "note": "截图对账调整",
          "is_t1": false
        },
        "fund_resolution": {
          "input": "110003",
          "status": "verified",
          "resolved_code": "110003",
          "candidates": [],
          "fund_name": "易方达上证50增强A"
        },
        "issues": [
          {
            "field": "shares",
            "code": "absent_from_input",
            "message": "该基金未出现在输入中，疑似清仓，请核实后再创建提案"
          }
        ],
        "proposal_ready": false
      },
      {
        "fund_code": "163406",
        "fund_name": "兴全合润混合A",
        "recorded_shares": 3876.15,
        "screenshot_shares": 0.0,
        "delta": -3876.15,
        "status": "maybe_sold",
        "suggested_tx": {
          "fund_code": "163406",
          "action": "sell",
          "date": null,
          "amount": 7113.12,
          "shares": 3876.15,
          "nav": 1.8351,
          "fee": 0,
          "channel": "理财通",
          "note": "截图对账调整",
          "is_t1": false
        },
        "fund_resolution": {
          "input": "163406",
          "status": "verified",
          "resolved_code": "163406",
          "candidates": [],
          "fund_name": "兴全合润混合A"
        },
        "issues": [
          {
            "field": "shares",
            "code": "absent_from_input",
            "message": "该基金未出现在输入中，疑似清仓，请核实后再创建提案"
          }
        ],
        "proposal_ready": false
      }
    ],
    "fund_resolution_errors": []
  }
}
```

## 4. 提案接口（可逆：创建 → 查询 → 取消）

### create_operation_proposal（create_plan / plans:propose）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "create_plan",
  "params": {
    "fund_code": "011612",
    "amount": 100,
    "cadence": "week",
    "day_of_week": 0
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:10:43.561704+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 3,
    "operation_type": "create_plan",
    "operation_label": "创建定投",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:10:43.556492+08:00",
    "expires_at": "2026-11-11T00:10:43.556492+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 169,
    "completed_at": null,
    "summary": {
      "amount": 100.0,
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "",
      "day_of_month": null,
      "day_of_week": 0,
      "enabled": false,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "创建定投",
      "operation_type": "create_plan",
      "schedule": "每周一",
      "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
      "title": "创建定投计划 011612（默认停用）",
      "warnings": []
    },
    "params": {
      "amount": 100.0,
      "cadence": "week",
      "channel": "",
      "day_of_month": null,
      "day_of_week": 0,
      "fund_code": "011612",
      "note": "定投"
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### create_operation_proposal（add_transaction / transactions:propose）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "add_transaction",
  "params": {
    "fund_code": "011612",
    "action": "buy",
    "date": "2026-11-03",
    "amount": 100,
    "shares": 102.39,
    "nav": 0.9755,
    "fee": 0.12,
    "channel": "理财通"
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:10:44.107022+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 4,
    "operation_type": "add_transaction",
    "operation_label": "新增交易",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:10:44.102335+08:00",
    "expires_at": "2026-11-11T00:10:44.102335+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 171,
    "completed_at": null,
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "amount": 100.0,
      "channel": "理财通",
      "date": "2026-11-03",
      "fee": 0.12,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 0.9755,
      "note": "",
      "operation_label": "新增交易",
      "operation_type": "add_transaction",
      "shares": 102.39,
      "title": "买入 011612",
      "warnings": []
    },
    "params": {
      "action": "buy",
      "amount": 100.0,
      "channel": "理财通",
      "date": "2026-11-03",
      "fee": 0.12,
      "fund_code": "011612",
      "is_t1": false,
      "nav": 0.9755,
      "note": "",
      "shares": 102.39
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### list_operation_proposals

- 请求：`GET /api/agent/tools/proposals`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_operation_proposals",
  "generated_at": "2026-11-04T00:10:44.644247+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "ok",
    "message": "提案列表",
    "replayed": false,
    "count": 4,
    "total": 4,
    "items": [
      {
        "proposal_id": 4,
        "operation_type": "add_transaction",
        "operation_label": "新增交易",
        "status": "pending",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:10:44.102335+08:00",
        "expires_at": "2026-11-11T00:10:44.102335+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 171,
        "completed_at": null,
        "summary": {
          "action": "buy",
          "action_label": "买入",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "operation_label": "新增交易",
          "operation_type": "add_transaction",
          "shares": 102.39,
          "title": "买入 011612",
          "warnings": []
        },
        "params": {
          "action": "buy",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "shares": 102.39
        },
        "can_cancel": true,
        "can_approve": true
      },
      {
        "proposal_id": 3,
        "operation_type": "create_plan",
        "operation_label": "创建定投",
        "status": "pending",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:10:43.556492+08:00",
        "expires_at": "2026-11-11T00:10:43.556492+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 169,
        "completed_at": null,
        "summary": {
          "amount": 100.0,
          "cadence": "week",
          "cadence_label": "每周",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "enabled": false,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "next_run": "2026-11-09",
          "note": "定投",
          "operation_label": "创建定投",
          "operation_type": "create_plan",
          "schedule": "每周一",
          "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
          "title": "创建定投计划 011612（默认停用）",
          "warnings": []
        },
        "params": {
          "amount": 100.0,
          "cadence": "week",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "fund_code": "011612",
          "note": "定投"
        },
        "can_cancel": true,
        "can_approve": true
      },
      {
        "proposal_id": 2,
        "operation_type": "add_transaction",
        "operation_label": "新增交易",
        "status": "cancelled",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:08:55.182156+08:00",
        "expires_at": "2026-11-11T00:08:55.182156+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 127,
        "completed_at": "2026-11-04T00:08:55.309327+08:00",
        "summary": {
          "action": "buy",
          "action_label": "买入",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "operation_label": "新增交易",
          "operation_type": "add_transaction",
          "shares": 102.39,
          "title": "买入 011612",
          "warnings": []
        },
        "params": {
          "action": "buy",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "shares": 102.39
        },
        "can_cancel": false,
        "can_approve": false
      },
      {
        "proposal_id": 1,
        "operation_type": "create_plan",
        "operation_label": "创建定投",
        "status": "cancelled",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:08:37.808971+08:00",
        "expires_at": "2026-11-11T00:08:37.808971+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 111,
        "completed_at": "2026-11-04T00:08:38.098507+08:00",
        "summary": {
          "amount": 100.0,
          "cadence": "week",
          "cadence_label": "每周",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "enabled": false,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "next_run": "2026-11-09",
          "note": "定投",
          "operation_label": "创建定投",
          "operation_type": "create_plan",
          "schedule": "每周一",
          "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
          "title": "创建定投计划 011612（默认停用）",
          "warnings": []
        },
        "params": {
          "amount": 100.0,
          "cadence": "week",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "fund_code": "011612",
          "note": "定投"
        },
        "can_cancel": false,
        "can_approve": false
      }
    ],
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 4
    }
  }
}
```

### get_operation_proposal（id=3）

- 请求：`GET /api/agent/tools/proposals/3`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_operation_proposal",
  "generated_at": "2026-11-04T00:10:44.982150+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "ok",
    "message": "提案详情",
    "replayed": false,
    "proposal_id": 3,
    "operation_type": "create_plan",
    "operation_label": "创建定投",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:10:43.556492+08:00",
    "expires_at": "2026-11-11T00:10:43.556492+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 169,
    "completed_at": null,
    "summary": {
      "amount": 100.0,
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "",
      "day_of_month": null,
      "day_of_week": 0,
      "enabled": false,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "创建定投",
      "operation_type": "create_plan",
      "schedule": "每周一",
      "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
      "title": "创建定投计划 011612（默认停用）",
      "warnings": []
    },
    "params": {
      "amount": 100.0,
      "cadence": "week",
      "channel": "",
      "day_of_month": null,
      "day_of_week": 0,
      "fund_code": "011612",
      "note": "定投"
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（id=3）

- 请求：`DELETE /api/agent/tools/proposals/3`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:10:45.322149+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 3,
    "operation_type": "create_plan",
    "operation_label": "创建定投",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:10:43.556492+08:00",
    "expires_at": "2026-11-11T00:10:43.556492+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 175,
    "completed_at": "2026-11-04T00:10:45.317998+08:00",
    "summary": {
      "amount": 100.0,
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "",
      "day_of_month": null,
      "day_of_week": 0,
      "enabled": false,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "创建定投",
      "operation_type": "create_plan",
      "schedule": "每周一",
      "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
      "title": "创建定投计划 011612（默认停用）",
      "warnings": []
    },
    "params": {
      "amount": 100.0,
      "cadence": "week",
      "channel": "",
      "day_of_month": null,
      "day_of_week": 0,
      "fund_code": "011612",
      "note": "定投"
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### cancel_operation_proposal（id=4）

- 请求：`DELETE /api/agent/tools/proposals/4`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:10:45.662101+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 4,
    "operation_type": "add_transaction",
    "operation_label": "新增交易",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:10:44.102335+08:00",
    "expires_at": "2026-11-11T00:10:44.102335+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 177,
    "completed_at": "2026-11-04T00:10:45.657939+08:00",
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "amount": 100.0,
      "channel": "理财通",
      "date": "2026-11-03",
      "fee": 0.12,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 0.9755,
      "note": "",
      "operation_label": "新增交易",
      "operation_type": "add_transaction",
      "shares": 102.39,
      "title": "买入 011612",
      "warnings": []
    },
    "params": {
      "action": "buy",
      "amount": 100.0,
      "channel": "理财通",
      "date": "2026-11-03",
      "fee": 0.12,
      "fund_code": "011612",
      "is_t1": false,
      "nav": 0.9755,
      "note": "",
      "shares": 102.39
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

## 5. 直记端点门控探针（未真实写入）

### record_transaction（非法基金代码 → 422，不写库）

- 请求：`POST /api/agent/tools/transactions`
- 请求体：

```json
{
  "fund_code": "abc",
  "action": "buy",
  "date": "2026-11-03",
  "amount": 1,
  "shares": 1,
  "nav": 1
}
```
- 响应 HTTP：**422**
- 响应体：

```json
{
  "detail": {
    "code": "validation_error",
    "field": "fund_code",
    "message": "基金代码必须是 6 位数字"
  }
}
```

### record_transaction（未收录基金 000000 → 409，不写库）

- 请求：`POST /api/agent/tools/transactions`
- 请求体：

```json
{
  "fund_code": "000000",
  "action": "buy",
  "date": "2026-11-03",
  "amount": 1,
  "shares": 1,
  "nav": 1
}
```
- 响应 HTTP：**409**
- 说明：先用 GET /funds/000000 确认 404（未收录）再探针
- 响应体：

```json
{
  "detail": {
    "code": "fund_not_registered",
    "message": "基金尚未收录，请先在网页添加或刷新基金信息后再试",
    "fund_code": "000000"
  }
}
```

## 6. 自选增删往返（可逆）

### add_watchlist_item（011612）

- 请求：`POST /api/agent/tools/watchlist`
- 请求体：

```json
{
  "fund_code": "011612",
  "note": "agent-test",
  "group_name": ""
}
```
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "add_watchlist_item",
  "generated_at": "2026-11-04T00:10:47.159752+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "已添加到自选",
    "replayed": false,
    "fund_code": "011612",
    "revision": 3,
    "changed": true,
    "before": null,
    "after": {
      "fund_code": "011612",
      "note": "agent-test",
      "group_name": "",
      "added_at": "2026-11-04 00:10:47",
      "revision": 3
    },
    "operation_id": 8,
    "audit_id": 183
  }
}
```

### list_watchlist（解析 revision）

- 请求：`GET /api/agent/tools/watchlist`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_watchlist",
  "generated_at": "2026-11-04T00:10:47.702798+08:00",
  "currency": "CNY",
  "data": {
    "count": 3,
    "total": 3,
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 3,
      "has_more": false
    },
    "watchlist": [
      {
        "fund_code": "011612",
        "note": "agent-test",
        "group_name": "",
        "added_at": "2026-11-04 00:10:47",
        "revision": 3,
        "fund_name": "华夏科创50ETF联接A",
        "fund_type": "指数型",
        "sector": "双创50",
        "tracking_index": "科创50"
      },
      {
        "fund_code": "000005",
        "note": "",
        "group_name": "",
        "added_at": "2026-08-19 22:08:11",
        "revision": 1,
        "fund_name": "嘉实增强信用定期债券",
        "fund_type": "债券型",
        "sector": "其它",
        "tracking_index": ""
      },
      {
        "fund_code": "000001",
        "note": "",
        "group_name": "",
        "added_at": "2026-08-19 22:08:02",
        "revision": 1,
        "fund_name": "华夏成长混合",
        "fund_type": "混合型",
        "sector": "其它",
        "tracking_index": ""
      }
    ]
  }
}
```

### remove_watchlist_item（011612, revision=3）

- 请求：`DELETE /api/agent/tools/watchlist/011612?expected_revision=3`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "remove_watchlist_item",
  "generated_at": "2026-11-04T00:10:48.043254+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "removed",
    "message": "已从自选移除",
    "replayed": false,
    "fund_code": "011612",
    "revision": 4,
    "changed": true,
    "before": {
      "fund_code": "011612",
      "note": "agent-test",
      "group_name": "",
      "added_at": "2026-11-04 00:10:47",
      "revision": 3
    },
    "after": null,
    "operation_id": 9,
    "audit_id": 186
  }
}
```

## 7. 数据刷新（非破坏，单基金）

### start_data_refresh（011612）

- 请求：`POST /api/agent/tools/refresh`
- 请求体：

```json
{
  "fund_codes": [
    "011612"
  ]
}
```
- 响应 HTTP：**202**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "start_data_refresh",
  "generated_at": "2026-11-04T00:10:48.383601+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "queued",
    "message": "刷新任务已创建",
    "replayed": false,
    "job_id": 2,
    "status": "queued",
    "fund_count": 1,
    "expires_at": "2026-11-11T00:10:48.378756+08:00"
  }
}
```

### get_job_status（job_id=2）

- 请求：`GET /api/agent/tools/refresh/2`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_job_status",
  "generated_at": "2026-11-04T00:10:49.021680+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "ok",
    "message": "任务状态",
    "replayed": false,
    "job_id": 2,
    "job_type": "data_refresh",
    "status": "running",
    "progress": {
      "done": 1,
      "total": 1,
      "current": "011612",
      "phase": "risk_levels"
    },
    "result": {},
    "error": "",
    "created_at": "2026-11-04T00:10:48.378756+08:00",
    "updated_at": "2026-11-04T00:10:48.887021+08:00",
    "expires_at": "2026-11-11T00:10:48.378756+08:00",
    "can_cancel": false
  }
}
```

## 8. 收尾状态核对

### list_operation_proposals（核对无待审）

- 请求：`GET /api/agent/tools/proposals`
- 响应 HTTP：**200**
- 说明：created/cancelled 历史留痕，pending 应为 0
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_operation_proposals",
  "generated_at": "2026-11-04T00:10:49.364456+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "ok",
    "message": "提案列表",
    "replayed": false,
    "count": 4,
    "total": 4,
    "items": [
      {
        "proposal_id": 4,
        "operation_type": "add_transaction",
        "operation_label": "新增交易",
        "status": "cancelled",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:10:44.102335+08:00",
        "expires_at": "2026-11-11T00:10:44.102335+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 177,
        "completed_at": "2026-11-04T00:10:45.657939+08:00",
        "summary": {
          "action": "buy",
          "action_label": "买入",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "operation_label": "新增交易",
          "operation_type": "add_transaction",
          "shares": 102.39,
          "title": "买入 011612",
          "warnings": []
        },
        "params": {
          "action": "buy",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "shares": 102.39
        },
        "can_cancel": false,
        "can_approve": false
      },
      {
        "proposal_id": 3,
        "operation_type": "create_plan",
        "operation_label": "创建定投",
        "status": "cancelled",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:10:43.556492+08:00",
        "expires_at": "2026-11-11T00:10:43.556492+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 175,
        "completed_at": "2026-11-04T00:10:45.317998+08:00",
        "summary": {
          "amount": 100.0,
          "cadence": "week",
          "cadence_label": "每周",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "enabled": false,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "next_run": "2026-11-09",
          "note": "定投",
          "operation_label": "创建定投",
          "operation_type": "create_plan",
          "schedule": "每周一",
          "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
          "title": "创建定投计划 011612（默认停用）",
          "warnings": []
        },
        "params": {
          "amount": 100.0,
          "cadence": "week",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "fund_code": "011612",
          "note": "定投"
        },
        "can_cancel": false,
        "can_approve": false
      },
      {
        "proposal_id": 2,
        "operation_type": "add_transaction",
        "operation_label": "新增交易",
        "status": "cancelled",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:08:55.182156+08:00",
        "expires_at": "2026-11-11T00:08:55.182156+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 127,
        "completed_at": "2026-11-04T00:08:55.309327+08:00",
        "summary": {
          "action": "buy",
          "action_label": "买入",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "operation_label": "新增交易",
          "operation_type": "add_transaction",
          "shares": 102.39,
          "title": "买入 011612",
          "warnings": []
        },
        "params": {
          "action": "buy",
          "amount": 100.0,
          "channel": "理财通",
          "date": "2026-11-03",
          "fee": 0.12,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.9755,
          "note": "",
          "shares": 102.39
        },
        "can_cancel": false,
        "can_approve": false
      },
      {
        "proposal_id": 1,
        "operation_type": "create_plan",
        "operation_label": "创建定投",
        "status": "cancelled",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:08:37.808971+08:00",
        "expires_at": "2026-11-11T00:08:37.808971+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 111,
        "completed_at": "2026-11-04T00:08:38.098507+08:00",
        "summary": {
          "amount": 100.0,
          "cadence": "week",
          "cadence_label": "每周",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "enabled": false,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "next_run": "2026-11-09",
          "note": "定投",
          "operation_label": "创建定投",
          "operation_type": "create_plan",
          "schedule": "每周一",
          "scheduler_hint": "计划创建后为停用状态，调度器不会执行；启用需另行提交 toggle_plan 提案",
          "title": "创建定投计划 011612（默认停用）",
          "warnings": []
        },
        "params": {
          "amount": 100.0,
          "cadence": "week",
          "channel": "",
          "day_of_month": null,
          "day_of_week": 0,
          "fund_code": "011612",
          "note": "定投"
        },
        "can_cancel": false,
        "can_approve": false
      }
    ],
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 4
    }
  }
}
```

### list_watchlist（核对应恢复为原 2 项）

- 请求：`GET /api/agent/tools/watchlist`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_watchlist",
  "generated_at": "2026-11-04T00:10:49.602497+08:00",
  "currency": "CNY",
  "data": {
    "count": 2,
    "total": 2,
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 2,
      "has_more": false
    },
    "watchlist": [
      {
        "fund_code": "000005",
        "note": "",
        "group_name": "",
        "added_at": "2026-08-19 22:08:11",
        "revision": 1,
        "fund_name": "嘉实增强信用定期债券",
        "fund_type": "债券型",
        "sector": "其它",
        "tracking_index": ""
      },
      {
        "fund_code": "000001",
        "note": "",
        "group_name": "",
        "added_at": "2026-08-19 22:08:02",
        "revision": 1,
        "fund_name": "华夏成长混合",
        "fund_type": "混合型",
        "sector": "其它",
        "tracking_index": ""
      }
    ]
  }
}
```

### get_returns

- 请求：`GET /api/agent/tools/returns`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_returns",
  "generated_at": "2026-11-04T00:10:49.988581+08:00",
  "currency": "CNY",
  "data": {
    "scope": "portfolio",
    "as_of_date": "2026-11-03",
    "as_of_date_semantics": "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新",
    "valuation_basis": "latest_formal_nav",
    "return_basis": "open_positions_floating",
    "return_basis_note": "total_return/return_rate 与各周期 return 只基于当前开仓成本与最新正式净值，不是历史累计收益；已清仓基金的历史已实现盈亏只计入 realized_pnl 与 XIRR。",
    "realized_pnl_scope": "all_history_including_closed",
    "total_pnl_scope": "unrealized_open_plus_realized_all_history",
    "total_cost": 88621.60207701458,
    "total_value": 112365.57402900002,
    "total_return": 0.2679253296656867,
    "annualized_return": 0.14586200133086402,
    "total_pnl": 29575.574028999996,
    "unrealized_pnl": 23743.9719519854,
    "realized_pnl": 5831.602077014593,
    "daily": {
      "pnl": -613.44,
      "return": -0.005429698210987388
    },
    "week": {
      "pnl": -278.1,
      "return": -0.0024710137988771825
    },
    "month": {
      "pnl": -278.1,
      "return": -0.0024710137988771825
    },
    "year": {
      "pnl": -10406.18,
      "return": -0.09082671820066698
    },
    "holding_count": 13,
    "open_position_count": 15,
    "closed_position_count": 0,
    "data_quality": {
      "missing_nav_fund_count": 0,
      "stale_nav_fund_count": 5,
      "pending_t1_transaction_count": 0,
      "caveats": [
        "5 只基金的最新正式净值可能已过期"
      ]
    }
  }
}
```

## 9. 结论

- 只读接口、鉴权边界、错误码形状、预检、提案（双域）、直记门控、自选往返、数据刷新均按预期工作。
- 写/提案用例均为可逆操作并已清理；直记仅使用非法/未收录基金探针，未向真实账本写入交易。
- 部署版本与本地 `__version__ = "0.25.0"` 一致，包含 F5 计划提案能力（`plans:propose`、`row_digest`）。


---

# 第二轮：写/提案深度联调

- 生成时间：2026-11-04 00:17:29
- 本轮包含**一笔真实直记写入**（小额、渠道 `Agent联调`、备注可识别），并提交 `delete_transaction` 提案供管理员在网页审批回滚。
- 其余提案类型均为**创建后立即取消**，不执行、不落库。

---

## A. 直记成功路径（真实写入 + 回滚提案）

### record_transaction（成功直记）

- 请求：`POST /api/agent/tools/transactions`
- 请求体：

```json
{
  "fund_code": "011612",
  "action": "buy",
  "date": "2026-11-04",
  "amount": 1,
  "shares": 1,
  "nav": 1,
  "fee": 0,
  "channel": "Agent联调",
  "note": "agent-api-test-rollback"
}
```
- 响应 HTTP：**201**
- 说明：小额 1 元、渠道 Agent联调，便于识别；真实写入账本
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "record_transaction",
  "generated_at": "2026-11-04T00:17:29.445737+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "recorded",
    "message": "交易已直接写入账本",
    "replayed": false,
    "execution_mode": "direct",
    "transaction_id": 71,
    "operation_id": 11,
    "proposal_id": null,
    "receipt": {
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "action": "buy",
      "action_label": "买入",
      "date": "2026-11-04",
      "amount": 1.0,
      "shares": 1.0,
      "nav": 1.0,
      "fee": 0.0,
      "channel": "Agent联调",
      "note": "agent-api-test-rollback",
      "is_t1": false,
      "unconfirmed_fields": [],
      "warnings": []
    },
    "daily_quota": {
      "used": 1,
      "count_limit": 10,
      "amount_used": 1.0,
      "amount_limit": 1000000.0,
      "reset_at": "2026-11-05T00:00:00+08:00"
    },
    "verify_path": "/transactions"
  }
}
```

> 直记结果：`transaction_id=71`，`execution_mode=direct`。

### get_transaction（核对新交易 id=71）

- 请求：`GET /api/agent/tools/transactions/71`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "get_transaction",
  "generated_at": "2026-11-04T00:17:30.087866+08:00",
  "currency": "CNY",
  "data": {
    "fund_code": "011612",
    "action": "buy",
    "date": "2026-11-04",
    "amount": 1.0,
    "shares": 1.0,
    "nav": 1.0,
    "fee": 0.0,
    "channel": "Agent联调",
    "note": "agent-api-test-rollback",
    "is_t1": false,
    "conversion_id": "",
    "source": "agent",
    "id": 71,
    "fund_name": "华夏科创50ETF联接A",
    "nav_status": "confirmed",
    "amount_semantics": "gross_paid",
    "conversion_role": "",
    "valuation_basis": "latest_formal_nav",
    "row_digest": "de4e44feb09f0e6c436267f556f8f5e5e913fb07b294c775a9f9b22feaee05aa"
  }
}
```

### create_operation_proposal（delete_transaction 回滚新交易，保持待审）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "delete_transaction",
  "params": {
    "tx_id": 71,
    "expected_digest": "de4e44feb09f0e6c436267f556f8f5e5e913fb07b294c775a9f9b22feaee05aa",
    "reason": "agent 接口联调测试交易回滚"
  }
}
```
- 响应 HTTP：**201**
- 说明：**故意保留 pending**，需管理员在网页审批后才会删除该测试交易
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:30.627851+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 5,
    "operation_type": "delete_transaction",
    "operation_label": "删除交易",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:30.622797+08:00",
    "expires_at": "2026-11-11T00:17:30.622797+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 208,
    "completed_at": null,
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "amount": 1.0,
      "before": {
        "action": "buy",
        "amount": 1.0,
        "channel": "Agent联调",
        "date": "2026-11-04",
        "fee": 0.0,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 1.0,
        "note": "agent-api-test-rollback",
        "shares": 1.0
      },
      "channel": "Agent联调",
      "date": "2026-11-04",
      "fee": 0.0,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 1.0,
      "note": "agent-api-test-rollback",
      "operation_label": "删除交易",
      "operation_type": "delete_transaction",
      "reason": "agent 接口联调测试交易回滚",
      "shares": 1.0,
      "title": "删除 买入 011612",
      "tx_id": 71,
      "warnings": []
    },
    "params": {
      "expected_digest": "de4e44feb09f0e6c436267f556f8f5e5e913fb07b294c775a9f9b22feaee05aa",
      "reason": "agent 接口联调测试交易回滚",
      "tx_id": 71
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

## B. 其余提案类型（创建 → 取消，不执行）

### create_operation_proposal（update_plan）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "update_plan",
  "params": {
    "plan_id": 1,
    "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
    "amount": 150.0
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:31.171666+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 6,
    "operation_type": "update_plan",
    "operation_label": "修改定投",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:31.166368+08:00",
    "expires_at": "2026-11-11T00:17:31.166368+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 210,
    "completed_at": null,
    "summary": {
      "after": {
        "amount": 150.0,
        "cadence": "week",
        "cadence_label": "每周",
        "channel": "理财通",
        "day_of_month": null,
        "day_of_week": 0,
        "enabled": true,
        "fund_code": "011612",
        "last_run": "2026-11-02",
        "next_run": "2026-11-16",
        "note": "定投"
      },
      "amount": 150.0,
      "before": {
        "amount": 100.0,
        "cadence": "week",
        "cadence_label": "每周",
        "channel": "理财通",
        "day_of_month": null,
        "day_of_week": 0,
        "enabled": true,
        "fund_code": "011612",
        "last_run": "2026-11-02",
        "next_run": "2026-11-09",
        "note": "定投"
      },
      "cadence": "week",
      "cadence_label": "每周",
      "changed_fields": [
        "amount"
      ],
      "channel": "理财通",
      "day_of_month": null,
      "day_of_week": 0,
      "enabled": true,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-16",
      "note": "定投",
      "operation_label": "修改定投",
      "operation_type": "update_plan",
      "plan_id": 1,
      "schedule": "每周一",
      "scheduler_hint": "计划启用中：批准后下次执行日期将按新配置重算",
      "title": "修改定投计划 #1",
      "warnings": []
    },
    "params": {
      "amount": 150.0,
      "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
      "plan_id": 1
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（update_plan, id=6）

- 请求：`DELETE /api/agent/tools/proposals/6`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:31.718116+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 6,
    "operation_type": "update_plan",
    "operation_label": "修改定投",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:31.166368+08:00",
    "expires_at": "2026-11-11T00:17:31.166368+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 212,
    "completed_at": "2026-11-04T00:17:31.714045+08:00",
    "summary": {
      "after": {
        "amount": 150.0,
        "cadence": "week",
        "cadence_label": "每周",
        "channel": "理财通",
        "day_of_month": null,
        "day_of_week": 0,
        "enabled": true,
        "fund_code": "011612",
        "last_run": "2026-11-02",
        "next_run": "2026-11-16",
        "note": "定投"
      },
      "amount": 150.0,
      "before": {
        "amount": 100.0,
        "cadence": "week",
        "cadence_label": "每周",
        "channel": "理财通",
        "day_of_month": null,
        "day_of_week": 0,
        "enabled": true,
        "fund_code": "011612",
        "last_run": "2026-11-02",
        "next_run": "2026-11-09",
        "note": "定投"
      },
      "cadence": "week",
      "cadence_label": "每周",
      "changed_fields": [
        "amount"
      ],
      "channel": "理财通",
      "day_of_month": null,
      "day_of_week": 0,
      "enabled": true,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-16",
      "note": "定投",
      "operation_label": "修改定投",
      "operation_type": "update_plan",
      "plan_id": 1,
      "schedule": "每周一",
      "scheduler_hint": "计划启用中：批准后下次执行日期将按新配置重算",
      "title": "修改定投计划 #1",
      "warnings": []
    },
    "params": {
      "amount": 150.0,
      "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
      "plan_id": 1
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### create_operation_proposal（toggle_plan）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "toggle_plan",
  "params": {
    "plan_id": 1,
    "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
    "enable": false
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:32.066328+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 7,
    "operation_type": "toggle_plan",
    "operation_label": "启停定投",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:32.061449+08:00",
    "expires_at": "2026-11-11T00:17:32.061449+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 214,
    "completed_at": null,
    "summary": {
      "amount": 100.0,
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "理财通",
      "enabled_after": false,
      "enabled_before": true,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "启停定投",
      "operation_type": "toggle_plan",
      "plan_id": 1,
      "schedule": "每周一",
      "scheduler_hint": "停用后调度器不再执行该计划",
      "title": "停用定投计划 #1",
      "warnings": []
    },
    "params": {
      "enable": false,
      "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
      "plan_id": 1
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（toggle_plan, id=7）

- 请求：`DELETE /api/agent/tools/proposals/7`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:32.615132+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 7,
    "operation_type": "toggle_plan",
    "operation_label": "启停定投",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:32.061449+08:00",
    "expires_at": "2026-11-11T00:17:32.061449+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 216,
    "completed_at": "2026-11-04T00:17:32.610908+08:00",
    "summary": {
      "amount": 100.0,
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "理财通",
      "enabled_after": false,
      "enabled_before": true,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "启停定投",
      "operation_type": "toggle_plan",
      "plan_id": 1,
      "schedule": "每周一",
      "scheduler_hint": "停用后调度器不再执行该计划",
      "title": "停用定投计划 #1",
      "warnings": []
    },
    "params": {
      "enable": false,
      "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
      "plan_id": 1
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### create_operation_proposal（delete_plan）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "delete_plan",
  "params": {
    "plan_id": 1,
    "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db"
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:32.964190+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 8,
    "operation_type": "delete_plan",
    "operation_label": "删除定投",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:32.958618+08:00",
    "expires_at": "2026-11-11T00:17:32.958618+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 218,
    "completed_at": null,
    "summary": {
      "amount": 100.0,
      "before": {
        "amount": 100.0,
        "cadence": "week",
        "cadence_label": "每周",
        "channel": "理财通",
        "day_of_month": null,
        "day_of_week": 0,
        "enabled": true,
        "fund_code": "011612",
        "last_run": "2026-11-02",
        "next_run": "2026-11-09",
        "note": "定投"
      },
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "理财通",
      "enabled": true,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "last_run": "2026-11-02",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "删除定投",
      "operation_type": "delete_plan",
      "plan_id": 1,
      "schedule": "每周一",
      "scheduler_hint": "删除后调度器不再执行该计划；历史交易不受影响",
      "title": "删除定投计划 #1",
      "warnings": []
    },
    "params": {
      "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
      "plan_id": 1
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（delete_plan, id=8）

- 请求：`DELETE /api/agent/tools/proposals/8`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:33.509583+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 8,
    "operation_type": "delete_plan",
    "operation_label": "删除定投",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:32.958618+08:00",
    "expires_at": "2026-11-11T00:17:32.958618+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 220,
    "completed_at": "2026-11-04T00:17:33.505233+08:00",
    "summary": {
      "amount": 100.0,
      "before": {
        "amount": 100.0,
        "cadence": "week",
        "cadence_label": "每周",
        "channel": "理财通",
        "day_of_month": null,
        "day_of_week": 0,
        "enabled": true,
        "fund_code": "011612",
        "last_run": "2026-11-02",
        "next_run": "2026-11-09",
        "note": "定投"
      },
      "cadence": "week",
      "cadence_label": "每周",
      "channel": "理财通",
      "enabled": true,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "last_run": "2026-11-02",
      "next_run": "2026-11-09",
      "note": "定投",
      "operation_label": "删除定投",
      "operation_type": "delete_plan",
      "plan_id": 1,
      "schedule": "每周一",
      "scheduler_hint": "删除后调度器不再执行该计划；历史交易不受影响",
      "title": "删除定投计划 #1",
      "warnings": []
    },
    "params": {
      "expected_digest": "32f04f4f70d756c6348826bf8ab908d1d8878ee98f85af78fcd4b2b3130627db",
      "plan_id": 1
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### create_operation_proposal（batch_import）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "batch_import",
  "params": {
    "note": "agent batch test",
    "transactions": [
      {
        "fund_code": "011612",
        "action": "buy",
        "date": "2026-11-03",
        "amount": 10,
        "shares": 10.2,
        "nav": 0.98,
        "fee": 0.01,
        "channel": "Agent联调"
      },
      {
        "fund_code": "011612",
        "action": "buy",
        "date": "2026-10-28",
        "amount": 20,
        "shares": 20.5,
        "nav": 0.97,
        "fee": 0.02,
        "channel": "Agent联调"
      }
    ]
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:33.850075+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 9,
    "operation_type": "batch_import",
    "operation_label": "批量导入",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:33.845129+08:00",
    "expires_at": "2026-11-11T00:17:33.845129+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 222,
    "completed_at": null,
    "summary": {
      "actions": {
        "buy": 2
      },
      "amount_total": 30.0,
      "count": 2,
      "date_range": {
        "from": "2026-10-28",
        "to": "2026-11-03"
      },
      "funds": [
        {
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A"
        }
      ],
      "items": [
        {
          "action": "buy",
          "action_label": "买入",
          "amount": 10.0,
          "channel": "Agent联调",
          "date": "2026-11-03",
          "fee": 0.01,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.98,
          "note": "",
          "shares": 10.2
        },
        {
          "action": "buy",
          "action_label": "买入",
          "amount": 20.0,
          "channel": "Agent联调",
          "date": "2026-10-28",
          "fee": 0.02,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.97,
          "note": "",
          "shares": 20.5
        }
      ],
      "note": "agent batch test",
      "operation_label": "批量导入",
      "operation_type": "batch_import",
      "title": "批量导入 2 条交易",
      "warnings": []
    },
    "params": {
      "note": "agent batch test",
      "transactions": [
        {
          "action": "buy",
          "amount": 10.0,
          "channel": "Agent联调",
          "date": "2026-11-03",
          "fee": 0.01,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.98,
          "note": "",
          "shares": 10.2
        },
        {
          "action": "buy",
          "amount": 20.0,
          "channel": "Agent联调",
          "date": "2026-10-28",
          "fee": 0.02,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.97,
          "note": "",
          "shares": 20.5
        }
      ]
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（batch_import, id=9）

- 请求：`DELETE /api/agent/tools/proposals/9`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:34.397286+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 9,
    "operation_type": "batch_import",
    "operation_label": "批量导入",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:33.845129+08:00",
    "expires_at": "2026-11-11T00:17:33.845129+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 224,
    "completed_at": "2026-11-04T00:17:34.392965+08:00",
    "summary": {
      "actions": {
        "buy": 2
      },
      "amount_total": 30.0,
      "count": 2,
      "date_range": {
        "from": "2026-10-28",
        "to": "2026-11-03"
      },
      "funds": [
        {
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A"
        }
      ],
      "items": [
        {
          "action": "buy",
          "action_label": "买入",
          "amount": 10.0,
          "channel": "Agent联调",
          "date": "2026-11-03",
          "fee": 0.01,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.98,
          "note": "",
          "shares": 10.2
        },
        {
          "action": "buy",
          "action_label": "买入",
          "amount": 20.0,
          "channel": "Agent联调",
          "date": "2026-10-28",
          "fee": 0.02,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 0.97,
          "note": "",
          "shares": 20.5
        }
      ],
      "note": "agent batch test",
      "operation_label": "批量导入",
      "operation_type": "batch_import",
      "title": "批量导入 2 条交易",
      "warnings": []
    },
    "params": {
      "note": "agent batch test",
      "transactions": [
        {
          "action": "buy",
          "amount": 10.0,
          "channel": "Agent联调",
          "date": "2026-11-03",
          "fee": 0.01,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.98,
          "note": "",
          "shares": 10.2
        },
        {
          "action": "buy",
          "amount": 20.0,
          "channel": "Agent联调",
          "date": "2026-10-28",
          "fee": 0.02,
          "fund_code": "011612",
          "is_t1": false,
          "nav": 0.97,
          "note": "",
          "shares": 20.5
        }
      ]
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### create_operation_proposal（update_transaction）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "update_transaction",
  "params": {
    "tx_id": 70,
    "expected_digest": "3e45cfd9eb9d1fa18646f4c7b95e3322036705d52604c99235570b0e9d363a93",
    "fund_code": "011612",
    "action": "buy",
    "date": "2026-11-02",
    "amount": 100.0,
    "shares": 102.39,
    "nav": 0.9755,
    "fee": 0.12,
    "channel": "理财通",
    "note": "agent-update-test",
    "is_t1": false
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:34.742091+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 10,
    "operation_type": "update_transaction",
    "operation_label": "修改交易",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:34.737120+08:00",
    "expires_at": "2026-11-11T00:17:34.737120+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 226,
    "completed_at": null,
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "after": {
        "action": "buy",
        "amount": 100.0,
        "channel": "理财通",
        "date": "2026-11-02",
        "fee": 0.12,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 0.9755,
        "note": "agent-update-test",
        "shares": 102.39
      },
      "amount": 100.0,
      "before": {
        "action": "buy",
        "amount": 100.0,
        "channel": "理财通",
        "date": "2026-11-02",
        "fee": 0.12,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 0.9755,
        "note": "定投",
        "shares": 102.39
      },
      "changed_fields": [
        "note"
      ],
      "channel": "理财通",
      "date": "2026-11-02",
      "fee": 0.12,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 0.9755,
      "note": "agent-update-test",
      "operation_label": "修改交易",
      "operation_type": "update_transaction",
      "shares": 102.39,
      "title": "修改 买入 011612",
      "tx_id": 70,
      "warnings": []
    },
    "params": {
      "action": "buy",
      "amount": 100.0,
      "channel": "理财通",
      "date": "2026-11-02",
      "expected_digest": "3e45cfd9eb9d1fa18646f4c7b95e3322036705d52604c99235570b0e9d363a93",
      "fee": 0.12,
      "fund_code": "011612",
      "is_t1": false,
      "nav": 0.9755,
      "note": "agent-update-test",
      "shares": 102.39,
      "tx_id": 70
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（update_transaction, id=10）

- 请求：`DELETE /api/agent/tools/proposals/10`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:35.284895+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 10,
    "operation_type": "update_transaction",
    "operation_label": "修改交易",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:34.737120+08:00",
    "expires_at": "2026-11-11T00:17:34.737120+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 228,
    "completed_at": "2026-11-04T00:17:35.280621+08:00",
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "after": {
        "action": "buy",
        "amount": 100.0,
        "channel": "理财通",
        "date": "2026-11-02",
        "fee": 0.12,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 0.9755,
        "note": "agent-update-test",
        "shares": 102.39
      },
      "amount": 100.0,
      "before": {
        "action": "buy",
        "amount": 100.0,
        "channel": "理财通",
        "date": "2026-11-02",
        "fee": 0.12,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 0.9755,
        "note": "定投",
        "shares": 102.39
      },
      "changed_fields": [
        "note"
      ],
      "channel": "理财通",
      "date": "2026-11-02",
      "fee": 0.12,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 0.9755,
      "note": "agent-update-test",
      "operation_label": "修改交易",
      "operation_type": "update_transaction",
      "shares": 102.39,
      "title": "修改 买入 011612",
      "tx_id": 70,
      "warnings": []
    },
    "params": {
      "action": "buy",
      "amount": 100.0,
      "channel": "理财通",
      "date": "2026-11-02",
      "expected_digest": "3e45cfd9eb9d1fa18646f4c7b95e3322036705d52604c99235570b0e9d363a93",
      "fee": 0.12,
      "fund_code": "011612",
      "is_t1": false,
      "nav": 0.9755,
      "note": "agent-update-test",
      "shares": 102.39,
      "tx_id": 70
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### create_operation_proposal（delete_transaction）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "delete_transaction",
  "params": {
    "tx_id": 69,
    "expected_digest": "7d355c12487855580ab295ab8686b86e1fc234d42bca75878d67452ac59ab738",
    "reason": "agent 接口联调测试（不会审批）"
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:35.632909+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 11,
    "operation_type": "delete_transaction",
    "operation_label": "删除交易",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:35.627863+08:00",
    "expires_at": "2026-11-11T00:17:35.627863+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 230,
    "completed_at": null,
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "amount": 100.0,
      "before": {
        "action": "buy",
        "amount": 100.0,
        "channel": "理财通",
        "date": "2026-10-26",
        "fee": 0.12,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 1.0664,
        "note": "定投",
        "shares": 93.66
      },
      "channel": "理财通",
      "date": "2026-10-26",
      "fee": 0.12,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 1.0664,
      "note": "定投",
      "operation_label": "删除交易",
      "operation_type": "delete_transaction",
      "reason": "agent 接口联调测试（不会审批）",
      "shares": 93.66,
      "title": "删除 买入 011612",
      "tx_id": 69,
      "warnings": []
    },
    "params": {
      "expected_digest": "7d355c12487855580ab295ab8686b86e1fc234d42bca75878d67452ac59ab738",
      "reason": "agent 接口联调测试（不会审批）",
      "tx_id": 69
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（delete_transaction, id=11）

- 请求：`DELETE /api/agent/tools/proposals/11`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:36.179207+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 11,
    "operation_type": "delete_transaction",
    "operation_label": "删除交易",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:35.627863+08:00",
    "expires_at": "2026-11-11T00:17:35.627863+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 232,
    "completed_at": "2026-11-04T00:17:36.175139+08:00",
    "summary": {
      "action": "buy",
      "action_label": "买入",
      "amount": 100.0,
      "before": {
        "action": "buy",
        "amount": 100.0,
        "channel": "理财通",
        "date": "2026-10-26",
        "fee": 0.12,
        "fund_code": "011612",
        "is_t1": false,
        "nav": 1.0664,
        "note": "定投",
        "shares": 93.66
      },
      "channel": "理财通",
      "date": "2026-10-26",
      "fee": 0.12,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 1.0664,
      "note": "定投",
      "operation_label": "删除交易",
      "operation_type": "delete_transaction",
      "reason": "agent 接口联调测试（不会审批）",
      "shares": 93.66,
      "title": "删除 买入 011612",
      "tx_id": 69,
      "warnings": []
    },
    "params": {
      "expected_digest": "7d355c12487855580ab295ab8686b86e1fc234d42bca75878d67452ac59ab738",
      "reason": "agent 接口联调测试（不会审批）",
      "tx_id": 69
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

### create_operation_proposal（add_conversion）

- 请求：`POST /api/agent/tools/proposals`
- 请求体：

```json
{
  "operation_type": "add_conversion",
  "params": {
    "from_code": "011612",
    "to_code": "005827",
    "date": "2026-11-03",
    "from_shares": 1,
    "from_nav": 0.9755,
    "from_fee": 0,
    "to_nav": 10.0,
    "channel": "Agent联调",
    "note": "agent conversion test"
  }
}
```
- 响应 HTTP：**201**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "create_operation_proposal",
  "generated_at": "2026-11-04T00:17:36.524078+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "created",
    "message": "提案已创建，等待网页管理员确认",
    "replayed": false,
    "proposal_id": 12,
    "operation_type": "add_conversion",
    "operation_label": "基金转换",
    "status": "pending",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:36.519288+08:00",
    "expires_at": "2026-11-11T00:17:36.519288+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 234,
    "completed_at": null,
    "summary": {
      "action": "conversion",
      "action_label": "转换",
      "amount": null,
      "channel": "Agent联调",
      "conversion": {
        "from": {
          "action": "sell",
          "action_label": "卖出",
          "fee": 0.0,
          "fund_code": "011612",
          "nav": 0.9755,
          "shares": 1.0
        },
        "to": {
          "action": "buy",
          "action_label": "买入",
          "amount": 0.98,
          "fee": 0.0,
          "fund_code": "005827",
          "nav": 10.0,
          "shares": 0.1
        }
      },
      "date": "2026-11-03",
      "fee": 0.0,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 0.9755,
      "note": "agent conversion test",
      "operation_label": "基金转换",
      "operation_type": "add_conversion",
      "shares": 1.0,
      "title": "转换 011612 → 005827",
      "warnings": [
        "请核对转出份额是否超过该渠道可用份额"
      ]
    },
    "params": {
      "channel": "Agent联调",
      "date": "2026-11-03",
      "from_code": "011612",
      "from_fee": 0.0,
      "from_nav": 0.9755,
      "from_shares": 1.0,
      "is_t1": false,
      "note": "agent conversion test",
      "to_amount": 0.98,
      "to_code": "005827",
      "to_fee": 0.0,
      "to_nav": 10.0
    },
    "can_cancel": true,
    "can_approve": true
  }
}
```

### cancel_operation_proposal（add_conversion, id=12）

- 请求：`DELETE /api/agent/tools/proposals/12`
- 响应 HTTP：**200**
- 说明：可逆清理
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "cancel_operation_proposal",
  "generated_at": "2026-11-04T00:17:37.066152+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "cancelled",
    "message": "提案已取消",
    "replayed": false,
    "proposal_id": 12,
    "operation_type": "add_conversion",
    "operation_label": "基金转换",
    "status": "cancelled",
    "risk_level": "medium",
    "created_at": "2026-11-04T00:17:36.519288+08:00",
    "expires_at": "2026-11-11T00:17:36.519288+08:00",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": "",
    "execution_result": null,
    "audit_id": 236,
    "completed_at": "2026-11-04T00:17:37.061874+08:00",
    "summary": {
      "action": "conversion",
      "action_label": "转换",
      "amount": null,
      "channel": "Agent联调",
      "conversion": {
        "from": {
          "action": "sell",
          "action_label": "卖出",
          "fee": 0.0,
          "fund_code": "011612",
          "nav": 0.9755,
          "shares": 1.0
        },
        "to": {
          "action": "buy",
          "action_label": "买入",
          "amount": 0.98,
          "fee": 0.0,
          "fund_code": "005827",
          "nav": 10.0,
          "shares": 0.1
        }
      },
      "date": "2026-11-03",
      "fee": 0.0,
      "fund_code": "011612",
      "fund_name": "华夏科创50ETF联接A",
      "is_t1": false,
      "nav": 0.9755,
      "note": "agent conversion test",
      "operation_label": "基金转换",
      "operation_type": "add_conversion",
      "shares": 1.0,
      "title": "转换 011612 → 005827",
      "warnings": [
        "请核对转出份额是否超过该渠道可用份额"
      ]
    },
    "params": {
      "channel": "Agent联调",
      "date": "2026-11-03",
      "from_code": "011612",
      "from_fee": 0.0,
      "from_nav": 0.9755,
      "from_shares": 1.0,
      "is_t1": false,
      "note": "agent conversion test",
      "to_amount": 0.98,
      "to_code": "005827",
      "to_fee": 0.0,
      "to_nav": 10.0
    },
    "can_cancel": false,
    "can_approve": false
  }
}
```

> `delete_conversion` 未测：账本中当前无任何转换对（`conversion_id` 全为空），没有可删除的目标；`add_conversion` 已覆盖创建/校验。

## C. 收尾状态

### list_operation_proposals（status=pending）

- 请求：`GET /api/agent/tools/proposals?status=pending`
- 响应 HTTP：**200**
- 说明：预期仅剩 1 条 delete_transaction（回滚测试交易）待审批
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_operation_proposals",
  "generated_at": "2026-11-04T00:17:37.405064+08:00",
  "currency": "CNY",
  "data": {
    "ok": true,
    "code": "ok",
    "message": "提案列表",
    "replayed": false,
    "count": 1,
    "total": 1,
    "items": [
      {
        "proposal_id": 5,
        "operation_type": "delete_transaction",
        "operation_label": "删除交易",
        "status": "pending",
        "risk_level": "medium",
        "created_at": "2026-11-04T00:17:30.622797+08:00",
        "expires_at": "2026-11-11T00:17:30.622797+08:00",
        "reviewed_by": null,
        "reviewed_at": null,
        "rejection_reason": "",
        "execution_result": null,
        "audit_id": 208,
        "completed_at": null,
        "summary": {
          "action": "buy",
          "action_label": "买入",
          "amount": 1.0,
          "before": {
            "action": "buy",
            "amount": 1.0,
            "channel": "Agent联调",
            "date": "2026-11-04",
            "fee": 0.0,
            "fund_code": "011612",
            "is_t1": false,
            "nav": 1.0,
            "note": "agent-api-test-rollback",
            "shares": 1.0
          },
          "channel": "Agent联调",
          "date": "2026-11-04",
          "fee": 0.0,
          "fund_code": "011612",
          "fund_name": "华夏科创50ETF联接A",
          "is_t1": false,
          "nav": 1.0,
          "note": "agent-api-test-rollback",
          "operation_label": "删除交易",
          "operation_type": "delete_transaction",
          "reason": "agent 接口联调测试交易回滚",
          "shares": 1.0,
          "title": "删除 买入 011612",
          "tx_id": 71,
          "warnings": []
        },
        "params": {
          "expected_digest": "de4e44feb09f0e6c436267f556f8f5e5e913fb07b294c775a9f9b22feaee05aa",
          "reason": "agent 接口联调测试交易回滚",
          "tx_id": 71
        },
        "can_cancel": true,
        "can_approve": true
      }
    ],
    "pagination": {
      "limit": 50,
      "offset": 0,
      "total": 1
    }
  }
}
```

### list_transactions（确认测试交易已入账，latest 应为 Agent联调 1 元）

- 请求：`GET /api/agent/tools/transactions?limit=1`
- 响应 HTTP：**200**
- 响应体：

```json
{
  "schema_version": 1,
  "tool": "list_transactions",
  "generated_at": "2026-11-04T00:17:37.750752+08:00",
  "currency": "CNY",
  "data": {
    "count": 1,
    "total": 47,
    "pagination": {
      "limit": 1,
      "offset": 0,
      "total": 47,
      "has_more": true
    },
    "valuation_basis": "latest_formal_nav",
    "transactions": [
      {
        "fund_code": "011612",
        "action": "buy",
        "date": "2026-11-04",
        "amount": 1.0,
        "shares": 1.0,
        "nav": 1.0,
        "fee": 0.0,
        "channel": "Agent联调",
        "note": "agent-api-test-rollback",
        "is_t1": false,
        "conversion_id": "",
        "source": "agent",
        "id": 71,
        "fund_name": "华夏科创50ETF联接A",
        "nav_status": "confirmed",
        "amount_semantics": "gross_paid",
        "conversion_role": ""
      }
    ]
  }
}
```



---

## D. 回滚复核（管理员审批提案 #5 之后）

- 复核时间：2026-11-04 00:19:15
- 结论：测试交易 71 已删除，账本恢复基线，无残留 `Agent联调` 交易。

### 提案 #5 审批结果

```json
{
  "ok": true,
  "code": "ok",
  "message": "提案详情",
  "replayed": false,
  "proposal_id": 5,
  "operation_type": "delete_transaction",
  "operation_label": "删除交易",
  "status": "succeeded",
  "risk_level": "medium",
  "created_at": "2026-11-04T00:17:30.622797+08:00",
  "expires_at": "2026-11-11T00:17:30.622797+08:00",
  "reviewed_by": "admin",
  "reviewed_at": "2026-11-04T00:18:20.704622+08:00",
  "rejection_reason": "",
  "execution_result": {
    "ok": true,
    "tx_id": 71,
    "before": {
      "fund_code": "011612",
      "action": "buy",
      "date": "2026-11-04",
      "amount": 1.0,
      "shares": 1.0,
      "nav": 1.0,
      "fee": 0.0,
      "channel": "Agent联调",
      "note": "agent-api-test-rollback",
      "is_t1": false
    }
  },
  "audit_id": 243,
  "completed_at": "2026-11-04T00:18:20.704622+08:00",
  "summary": {
    "action": "buy",
    "action_label": "买入",
    "amount": 1.0,
    "before": {
      "action": "buy",
      "amount": 1.0,
      "channel": "Agent联调",
      "date": "2026-11-04",
      "fee": 0.0,
      "fund_code": "011612",
      "is_t1": false,
      "nav": 1.0,
      "note": "agent-api-test-rollback",
      "shares": 1.0
    },
    "channel": "Agent联调",
    "date": "2026-11-04",
    "fee": 0.0,
    "fund_code": "011612",
    "fund_name": "华夏科创50ETF联接A",
    "is_t1": false,
    "nav": 1.0,
    "note": "agent-api-test-rollback",
    "operation_label": "删除交易",
    "operation_type": "delete_transaction",
    "reason": "agent 接口联调测试交易回滚",
    "shares": 1.0,
    "title": "删除 买入 011612",
    "tx_id": 71,
    "warnings": []
  },
  "params": {
    "expected_digest": "de4e44feb09f0e6c436267f556f8f5e5e913fb07b294c775a9f9b22feaee05aa",
    "reason": "agent 接口联调测试交易回滚",
    "tx_id": 71
  },
  "can_cancel": false,
  "can_approve": false
}
```

### 组合汇总（回滚后）

```json
{
  "total_cost": 88621.60207701458,
  "total_value": 112365.57402900002,
  "unrealized_pnl": 23743.9719519854,
  "realized_pnl": 5831.602077014593,
  "total_pnl": 29575.574028999996,
  "total_return": 0.2679253296656867,
  "annualized_return": 0.14586200133086402,
  "total_buy": 99200.0,
  "total_sell": 15190.0,
  "total_dividend": 1362.0,
  "holding_count": 13,
  "max_single_weight": 0.1756004771257395,
  "max_single_name": "博时黄金ETF联接A",
  "as_of_date": "2026-11-03",
  "daily_pnl": -613.44,
  "daily_return": -0.005429698210987388,
  "week_pnl": -278.1,
  "week_return": -0.0024710137988771825,
  "month_pnl": -278.1,
  "month_return": -0.0024710137988771825,
  "year_pnl": -10406.18,
  "year_return": -0.09082671820066698,
  "data_status": {
    "missing_nav_fund_count": 0,
    "stale_nav_fund_count": 5,
    "pending_t1_transaction_count": 0
  }
}
```

