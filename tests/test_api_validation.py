"""API 输入验证回归测试。

验证 Pydantic field_validator / Query 约束 / allow_inf_nan=False 对所有
输入模型的防护：格式、枚举、非负、NaN/inf、查询参数边界。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from zfundpilot.api import (
    AIConfigUpdate,
    AutoInvestPlanCreate,
    ChatMessage,
    ChatRequest,
    DcaBacktestRequest,
    FilterRequest,
    ReconcileItem,
    TpSlConfigUpdate,
    TransactionCreate,
    VisionConfigUpdate,
    app,
)

client = TestClient(app)

# ---------------------------------------------------------------------------
# TransactionCreate
# ---------------------------------------------------------------------------

class TestTransactionCreate:
    def test_valid_buy(self):
        tx = TransactionCreate(
            fund_code="005827", action="buy", date="2026-01-15",
            amount=1000, shares=None, nav=None,
        )
        assert tx.fund_code == "005827"

    def test_valid_sell(self):
        tx = TransactionCreate(
            fund_code="005827", action="sell", date="2026-01-15",
            shares=100, nav=1.5,
        )
        assert tx.action == "sell"

    def test_fund_code_too_short(self):
        with pytest.raises(ValidationError, match="6 位数字"):
            TransactionCreate(fund_code="001", action="buy", date="2026-01-15", amount=100)

    def test_fund_code_letters(self):
        with pytest.raises(ValidationError, match="6 位数字"):
            TransactionCreate(fund_code="abcdef", action="buy", date="2026-01-15", amount=100)

    def test_fund_code_too_long(self):
        with pytest.raises(ValidationError, match="6 位数字"):
            TransactionCreate(fund_code="0058270", action="buy", date="2026-01-15", amount=100)

    def test_fund_code_nan_inf(self):
        with pytest.raises(ValidationError):
            TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=float("nan"))

    def test_action_invalid(self):
        with pytest.raises(ValidationError, match="action 仅支持"):
            TransactionCreate(fund_code="005827", action="hold", date="2026-01-15", amount=100)

    def test_date_bad_format(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            TransactionCreate(fund_code="005827", action="buy", date="01/15/2026", amount=100)

    def test_date_nonexistent(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            TransactionCreate(fund_code="005827", action="buy", date="2026-02-30", amount=100)

    def test_amount_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=-100)

    def test_shares_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TransactionCreate(fund_code="005827", action="sell", date="2026-01-15", shares=-10, nav=1.5)

    def test_nav_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=100, nav=-1.5)

    def test_fee_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=100, fee=-5)

    def test_zero_amount_accepted(self):
        tx = TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=0)
        assert tx.amount == 0

    def test_inf_amount_rejected(self):
        with pytest.raises(ValidationError):
            TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=float("inf"))

    def test_neg_inf_amount_rejected(self):
        with pytest.raises(ValidationError):
            TransactionCreate(fund_code="005827", action="buy", date="2026-01-15", amount=float("-inf"))


# ---------------------------------------------------------------------------
# AutoInvestPlanCreate
# ---------------------------------------------------------------------------

class TestAutoInvestPlanCreate:
    def test_valid_weekly(self):
        p = AutoInvestPlanCreate(fund_code="005827", amount=1000, cadence="week", day_of_week=0)
        assert p.amount == 1000

    def test_amount_zero(self):
        with pytest.raises(ValidationError, match="必须大于 0"):
            AutoInvestPlanCreate(fund_code="005827", amount=0, cadence="week", day_of_week=0)

    def test_amount_negative(self):
        with pytest.raises(ValidationError, match="必须大于 0"):
            AutoInvestPlanCreate(fund_code="005827", amount=-500, cadence="week", day_of_week=0)

    def test_fund_code_invalid(self):
        with pytest.raises(ValidationError, match="6 位数字"):
            AutoInvestPlanCreate(fund_code="abc", amount=1000, cadence="month", day_of_month=15)

    def test_cadence_invalid(self):
        with pytest.raises(ValidationError, match="频率仅支持"):
            AutoInvestPlanCreate(fund_code="005827", amount=1000, cadence="year", day_of_month=15)


# ---------------------------------------------------------------------------
# ReconcileItem
# ---------------------------------------------------------------------------

class TestReconcileItem:
    def test_valid(self):
        r = ReconcileItem(fund_code="005827", shares=100, market_value=1500)
        assert r.fund_code == "005827"

    def test_fund_code_bad(self):
        with pytest.raises(ValidationError, match="6 位数字"):
            ReconcileItem(fund_code="abc", shares=100)

    def test_shares_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            ReconcileItem(fund_code="005827", shares=-10)

    def test_market_value_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            ReconcileItem(fund_code="005827", market_value=-1000)


# ---------------------------------------------------------------------------
# TpSlConfigUpdate
# ---------------------------------------------------------------------------

class TestTpSlConfigUpdate:
    def test_valid(self):
        t = TpSlConfigUpdate(take_profit=0.15, stop_loss=0.05)
        assert t.take_profit == 0.15

    def test_take_profit_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TpSlConfigUpdate(take_profit=-0.1)

    def test_stop_loss_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TpSlConfigUpdate(stop_loss=-0.05)

    def test_reset_ratio_negative(self):
        with pytest.raises(ValidationError, match="不能为负数"):
            TpSlConfigUpdate(reset_ratio=-1)

    def test_nan_rejected(self):
        with pytest.raises(ValidationError):
            TpSlConfigUpdate(take_profit=float("nan"))

    def test_inf_rejected(self):
        with pytest.raises(ValidationError):
            TpSlConfigUpdate(stop_loss=float("inf"))


# ---------------------------------------------------------------------------
# DcaBacktestRequest
# ---------------------------------------------------------------------------

class TestDcaBacktestRequest:
    def test_valid(self):
        r = DcaBacktestRequest(
            fund_codes=["005827"], start_date="2024-01-01", end_date="2024-12-31",
            amount_per_period=1000,
        )
        assert r.amount_per_period == 1000

    def test_amount_zero(self):
        with pytest.raises(ValidationError, match="必须大于 0"):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=0,
            )

    def test_amount_negative(self):
        with pytest.raises(ValidationError, match="必须大于 0"):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=-500,
            )

    def test_cadence_invalid(self):
        with pytest.raises(ValidationError, match="频率仅支持"):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=1000, cadence="year",
            )

    def test_fund_code_invalid(self):
        with pytest.raises(ValidationError, match="6 位数字"):
            DcaBacktestRequest(
                fund_codes=["abc"], start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=1000,
            )

    def test_empty_fund_codes(self):
        with pytest.raises(ValidationError, match="至少选择一只"):
            DcaBacktestRequest(
                fund_codes=[], start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=1000,
            )

    def test_too_many_funds(self):
        with pytest.raises(ValidationError, match="最多选择 20"):
            DcaBacktestRequest(
                fund_codes=[f"{i:06d}" for i in range(21)],
                start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=1000,
            )

    def test_date_format_bad(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="01-01-2024", end_date="2024-12-31",
                amount_per_period=1000,
            )

    def test_date_order_bad(self):
        with pytest.raises(ValidationError, match="起始日期必须早于"):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="2024-12-31", end_date="2024-01-01",
                amount_per_period=1000,
            )

    def test_date_order_equal(self):
        with pytest.raises(ValidationError, match="起始日期必须早于"):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="2024-06-15", end_date="2024-06-15",
                amount_per_period=1000,
            )

    def test_nan_amount_rejected(self):
        with pytest.raises(ValidationError):
            DcaBacktestRequest(
                fund_codes=["005827"], start_date="2024-01-01", end_date="2024-12-31",
                amount_per_period=float("nan"),
            )


# ---------------------------------------------------------------------------
# ChatMessage / ChatRequest
# ---------------------------------------------------------------------------

class TestChatRequest:
    def test_valid(self):
        r = ChatRequest(messages=[
            ChatMessage(role="user", content="你好"),
        ])
        assert len(r.messages) == 1

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[ChatMessage(role="admin", content="hi")])

    def test_content_too_long(self):
        with pytest.raises(ValidationError, match="20000"):
            ChatRequest(messages=[ChatMessage(role="user", content="x" * 20001)])

    def test_too_many_messages(self):
        with pytest.raises(ValidationError, match="50 条"):
            ChatRequest(messages=[
                ChatMessage(role="user", content="hi") for _ in range(51)
            ])

    def test_total_content_too_long(self):
        msgs = [
            ChatMessage(role="user", content="x" * 17000),
            ChatMessage(role="assistant", content="y" * 17000),
            ChatMessage(role="user", content="z" * 17000),
            ChatMessage(role="assistant", content="w" * 17000),
            ChatMessage(role="user", content="v" * 17000),
            ChatMessage(role="assistant", content="u" * 17000),
        ]
        with pytest.raises(ValidationError, match="100000"):
            ChatRequest(messages=msgs)

    def test_nan_in_content_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[ChatMessage(role="user", content=float("nan"))])

    def test_inf_in_content_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[ChatMessage(role="user", content=float("inf"))])


# ---------------------------------------------------------------------------
# FilterRequest
# ---------------------------------------------------------------------------

class TestFilterRequest:
    def test_valid(self):
        f = FilterRequest(limit=50, offset=0)
        assert f.limit == 50

    def test_limit_zero(self):
        with pytest.raises(ValidationError):
            FilterRequest(limit=0)

    def test_limit_negative(self):
        with pytest.raises(ValidationError):
            FilterRequest(limit=-1)

    def test_limit_too_large(self):
        with pytest.raises(ValidationError):
            FilterRequest(limit=501)

    def test_offset_negative(self):
        with pytest.raises(ValidationError):
            FilterRequest(offset=-1)


# ---------------------------------------------------------------------------
# GET 端点 Query 约束
# ---------------------------------------------------------------------------

class TestQueryConstraints:
    def test_ai_usage_daily_days_negative(self):
        resp = client.get("/api/ai/usage/daily?days=-1")
        assert resp.status_code == 422

    def test_ai_usage_daily_days_zero(self):
        resp = client.get("/api/ai/usage/daily?days=0")
        assert resp.status_code == 422

    def test_ai_usage_daily_days_over_365(self):
        resp = client.get("/api/ai/usage/daily?days=366")
        assert resp.status_code == 422

    def test_audit_logs_limit_negative(self):
        resp = client.get("/api/audit?limit=-1")
        assert resp.status_code == 422

    def test_audit_logs_limit_zero(self):
        resp = client.get("/api/audit?limit=0")
        assert resp.status_code == 422

    def test_audit_logs_limit_over_1000(self):
        resp = client.get("/api/audit?limit=1001")
        assert resp.status_code == 422

    def test_transactions_bad_fund_code(self):
        resp = client.get("/api/transactions?fund_code=abc")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# SSRF base_url 验证
# ---------------------------------------------------------------------------


class TestSSRFValidation:
    def test_valid_https_url(self):
        m = AIConfigUpdate(base_url="https://api.openai.com/v1", model="gpt-4")
        assert m.base_url == "https://api.openai.com/v1"

    def test_valid_http_localhost(self):
        m = AIConfigUpdate(base_url="http://localhost:11434", model="llama3")
        assert m.base_url == "http://localhost:11434"

    def test_valid_private_ip(self):
        m = AIConfigUpdate(base_url="http://192.168.1.100:8080", model="model")
        assert m.base_url == "http://192.168.1.100:8080"

    def test_reject_link_local_ipv4(self):
        with pytest.raises(ValidationError, match="link-local"):
            AIConfigUpdate(base_url="http://169.254.169.254/metadata", model="m")

    def test_reject_link_local_ipv6(self):
        with pytest.raises(ValidationError, match="link-local"):
            AIConfigUpdate(base_url="http://[fe80::1]/", model="m")

    def test_reject_internal_tld(self):
        with pytest.raises(ValidationError, match="internal"):
            AIConfigUpdate(base_url="http://metadata.internal/", model="m")

    def test_reject_localhost_tld(self):
        with pytest.raises(ValidationError, match="localhost"):
            AIConfigUpdate(base_url="http://app.localhost/", model="m")

    def test_reject_non_http_scheme(self):
        with pytest.raises(ValidationError, match="http 或 https"):
            AIConfigUpdate(base_url="ftp://example.com", model="m")

    def test_vision_reject_link_local(self):
        with pytest.raises(ValidationError, match="link-local"):
            VisionConfigUpdate(base_url="http://169.254.169.254/", model="m")
