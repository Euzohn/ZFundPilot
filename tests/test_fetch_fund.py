"""fetch_fund 新增功能测试：同类排名走势、基金档案。"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zfundpilot import fetch_fund
from zfundpilot.models import (
    FundProfile,
    FundRankingResult,
    IndustryAllocationResult,
    NavPoint,
    Transaction,
)


def _fake_akshare(df):
    """构造假的 akshare 模块，使其 fund_open_fund_info_em 返回指定 df。"""
    fake = ModuleType("akshare")
    fake.fund_open_fund_info_em = MagicMock(return_value=df)
    return fake


def _rank_df() -> pd.DataFrame:
    """构造同类排名百分比 DataFrame（与 AkShare 返回列名一致）。"""
    return pd.DataFrame(
        {
            "报告日期": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "同类型排名-每日近3月收益排名百分比": [12.5, 8.3, 15.7],
        }
    )


def test_fetch_fund_ranking_success():
    fake = _fake_akshare(_rank_df())
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._ranking_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_ranking("005827")
    assert result.ok
    assert result.code == "ok"
    assert len(result.points) == 3
    assert result.points[0].date == "2024-01-02"
    assert result.points[0].percentile == 12.5
    assert result.points[-1].percentile == 15.7


def test_fetch_fund_ranking_empty():
    fake = _fake_akshare(pd.DataFrame())
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._ranking_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_ranking("005827")
    assert not result.ok
    assert result.code == "no_data"
    assert result.points == []


def test_fetch_fund_ranking_skips_invalid_percentile():
    df = pd.DataFrame(
        {
            "报告日期": ["2024-01-02", "2024-01-03"],
            "同类型排名-每日近3月收益排名百分比": [0.0, "--"],
        }
    )
    fake = _fake_akshare(df)
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._ranking_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_ranking("005827")
    assert result.ok
    assert result.points == []


def test_fetch_fund_ranking_fetch_error():
    fake = _fake_akshare(None)
    fake.fund_open_fund_info_em.side_effect = RuntimeError("boom")
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._ranking_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_ranking("005827")
    assert not result.ok
    assert result.code == "fetch_error"
    assert result.points == []


def test_fetch_fund_ranking_uses_cache():
    fake = _fake_akshare(_rank_df())
    cached = FundRankingResult(fund_code="005827", ok=True, message="成功", code="ok", points=[])
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(
            fetch_fund._ranking_cache,
            {"005827": {"ts": fetch_fund.time.time(), "data": cached}},
            clear=True,
        ),
    ):
        result = fetch_fund.fetch_fund_ranking("005827")
    fake.fund_open_fund_info_em.assert_not_called()
    assert result.ok
    assert result.points == []


def test_parse_work_days():
    assert fetch_fund._parse_work_days("13年又310天") == 13 * 365 + 310
    assert fetch_fund._parse_work_days("7年又311天") == 7 * 365 + 311
    assert fetch_fund._parse_work_days("3年") == 3 * 365
    assert fetch_fund._parse_work_days("") is None
    assert fetch_fund._parse_work_days(None) is None
    assert fetch_fund._parse_work_days("abc") is None


_PINGZHONGDATA_SAMPLE = """\
Data_currentFundManager = [{"name":"张坤","workTime":"13年又310天","profit":{"series":[{"data":[{"y":50.94}]}]}}] ;/*申购赎回*/
var Data_buySedemption = {};

var Data_fluctuationScale = {"categories":["2026-03-31","2026-06-30"],"series":[{"y":267.93},{"y":204.16}]};
"""

_FUND_DETAIL_HTML_SAMPLE = (
    '<td>类型：<a href="http://fund.eastmoney.com/HH_jzzzl.html">混合型-灵活</a>'
    "&nbsp;&nbsp;|&nbsp;&nbsp;中高风险</td>"
)


def _mock_http_get(url, timeout=15):
    if "pingzhongdata" in url:
        return _PINGZHONGDATA_SAMPLE
    if "fund.eastmoney.com" in url and url.endswith(".html"):
        return _FUND_DETAIL_HTML_SAMPLE
    return ""


def test_fetch_fund_profile_success():
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", side_effect=_mock_http_get),
        patch.object(fetch_fund, "fetch_fund_fee_rates") as f,
    ):
        f.return_value = MagicMock(
            ok=True, management_fee=0.015, custodian_fee=0.0025, sales_fee=None
        )
        profile = fetch_fund.fetch_fund_profile("005827")
    assert profile.ok
    assert profile.code == "ok"
    assert profile.manager == "张坤"
    assert profile.manager_career_days == 13 * 365 + 310
    assert profile.scale == 204.16
    assert profile.tenure_return == 50.94
    assert profile.management_fee == 0.015
    assert profile.custodian_fee == 0.0025
    assert profile.sales_fee is None
    assert profile.risk_level == "中高风险"


def test_fetch_fund_profile_no_manager():
    def _empty_pingzhong(url, timeout=15):
        if "pingzhongdata" in url:
            return "var nothing = 1;"
        return _FUND_DETAIL_HTML_SAMPLE
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", side_effect=_empty_pingzhong),
        patch.object(fetch_fund, "fetch_fund_fee_rates") as f,
    ):
        f.return_value = MagicMock(
            ok=True, management_fee=0.015, custodian_fee=0.0025, sales_fee=None
        )
        profile = fetch_fund.fetch_fund_profile("005827")
    assert profile.manager == ""
    assert profile.scale is None
    # 有费率仍算成功
    assert profile.ok
    assert profile.management_fee == 0.015
    assert profile.risk_level == "中高风险"


def test_fetch_fund_profile_all_empty_fails():
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value="var nothing = 1;"),
        patch.object(fetch_fund, "fetch_fund_fee_rates") as f,
    ):
        f.return_value = MagicMock(ok=True, management_fee=None, custodian_fee=None, sales_fee=None)
        profile = fetch_fund.fetch_fund_profile("005827")
    assert not profile.ok
    assert profile.code in ("no_data", "fetch_error")
    assert profile.risk_level == ""


def test_fund_profile_to_dict():
    p = FundProfile(
        fund_code="005827",
        ok=True,
        message="成功",
        code="ok",
        manager="张坤",
        manager_career_days=5055,
        scale=204.16,
        tenure_return=50.94,
        management_fee=0.015,
    )
    d = p.to_dict()
    assert d["manager"] == "张坤"
    assert d["scale"] == 204.16
    assert d["tenure_return"] == 50.94


def test_clear_caches():
    fetch_fund._ranking_cache["x"] = {"ts": 1, "data": None}
    fetch_fund._profile_cache["y"] = {"ts": 1, "data": None}
    fetch_fund.clear_ranking_cache()
    fetch_fund.clear_profile_cache()
    assert fetch_fund._ranking_cache == {}
    assert fetch_fund._profile_cache == {}


# ---------------------------------------------------------------------------
# 风险等级（轻量抓取 + 批量写回）
# ---------------------------------------------------------------------------
def test_fetch_risk_level_success():
    with patch.object(fetch_fund, "_http_get", return_value=_FUND_DETAIL_HTML_SAMPLE):
        assert fetch_fund.fetch_risk_level("005827") == "中高风险"


def test_fetch_risk_level_no_match():
    with patch.object(fetch_fund, "_http_get", return_value="<html>no risk</html>"):
        assert fetch_fund.fetch_risk_level("005827") == ""


def test_fetch_risk_level_http_error():
    with patch.object(fetch_fund, "_http_get", side_effect=RuntimeError("boom")):
        assert fetch_fund.fetch_risk_level("005827") == ""


def test_refresh_risk_levels_writes_back():
    updates: list[tuple[str, str]] = []

    def _record(code, level):
        updates.append((code, level))

    def _fake_fetch(code):
        return {"005827": "中高风险", "000001": ""}.get(code, "")

    with (
        patch.object(fetch_fund, "fetch_risk_level", side_effect=_fake_fetch),
        patch.object(fetch_fund.db, "update_fund_risk_level", _record),
    ):
        n = fetch_fund.refresh_risk_levels(["005827", "000001"])
    assert n == 1  # 空值不写回
    assert updates == [("005827", "中高风险")]


def test_refresh_risk_levels_concurrent_many():
    """并发刷新应处理全部代码（含空值不写回）；DB 写入主线程串行。"""
    codes = [f"00000{i}" for i in range(8)]
    levels = {codes[0]: "低风险", codes[3]: "中高风险", codes[7]: "高风险"}
    updates: list[tuple[str, str]] = []

    def _record(code, level):
        updates.append((code, level))

    def _fake_fetch(code):
        return levels.get(code, "")

    with (
        patch.object(fetch_fund, "fetch_risk_level", side_effect=_fake_fetch),
        patch.object(fetch_fund.db, "update_fund_risk_level", _record),
    ):
        n = fetch_fund.refresh_risk_levels(codes)
    assert n == 3
    assert set(updates) == {("000000", "低风险"), ("000003", "中高风险"), ("000007", "高风险")}


# ---------------------------------------------------------------------------
# 行业配置（基金穿透数据源）
# ---------------------------------------------------------------------------

def _fake_akshare_industry(df):
    """构造假的 akshare 模块，使其 fund_portfolio_industry_allocation_em 返回 df。"""
    fake = ModuleType("akshare")
    fake.fund_portfolio_industry_allocation_em = MagicMock(return_value=df)
    return fake


def _industry_df() -> pd.DataFrame:
    """构造行业配置 DataFrame（与 AkShare 返回列名一致）。"""
    return pd.DataFrame(
        {
            "序号": [1, 2, 3],
            "行业类别": ["制造业", "金融业", "采矿业"],
            "占净值比例": [69.53, 1.17, 1.17],
            "市值": [189787.96, 3195.41, 3194.76],
            "截止时间": ["2023-09-30", "2023-09-30", "2023-09-30"],
        }
    )


def test_fetch_fund_industry_allocation_success():
    fake = _fake_akshare_industry(_industry_df())
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._industry_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_industry_allocation("000001")
    assert result.ok
    assert result.code == "ok"
    assert len(result.allocations) == 3
    assert result.allocations[0].industry == "制造业"
    assert result.allocations[0].weight == pytest.approx(0.6953)
    assert result.allocations[0].market_value == pytest.approx(189787.96)
    assert result.quarter == "2023-09-30"
    assert result.stock_ratio == pytest.approx(0.7187)


def test_fetch_fund_industry_allocation_latest_quarter():
    df = pd.DataFrame(
        {
            "行业类别": ["制造业", "金融业", "制造业", "采矿业"],
            "占净值比例": [69.53, 1.17, 65.89, 1.93],
            "市值": [189787.96, 3195.41, 193354.96, 11490.74],
            "截止时间": ["2023-09-30", "2023-09-30", "2023-03-31", "2023-03-31"],
        }
    )
    fake = _fake_akshare_industry(df)
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._industry_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_industry_allocation("000001")
    assert result.ok
    assert result.quarter == "2023-09-30"
    assert len(result.allocations) == 2
    assert {a.industry for a in result.allocations} == {"制造业", "金融业"}


def test_fetch_fund_industry_allocation_empty():
    fake = _fake_akshare_industry(pd.DataFrame())
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._industry_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_industry_allocation("000001")
    assert not result.ok
    assert result.code == "no_data"
    assert result.allocations == []


def test_fetch_fund_industry_allocation_year_fallback():
    fake = _fake_akshare_industry(pd.DataFrame())
    fake.fund_portfolio_industry_allocation_em.side_effect = [
        pd.DataFrame(),  # 当年无数据
        _industry_df(),  # 上一年有数据
    ]
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._industry_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_industry_allocation("000001")
    assert result.ok
    assert result.quarter == "2023-09-30"
    assert fake.fund_portfolio_industry_allocation_em.call_count == 2


def test_fetch_fund_industry_allocation_fetch_error():
    fake = _fake_akshare_industry(None)
    fake.fund_portfolio_industry_allocation_em.side_effect = RuntimeError("boom")
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(fetch_fund._industry_cache, {}, clear=True),
    ):
        result = fetch_fund.fetch_fund_industry_allocation("000001")
    assert not result.ok
    assert result.allocations == []


def test_fetch_fund_industry_allocation_uses_cache():
    fake = _fake_akshare_industry(_industry_df())
    cached = IndustryAllocationResult(
        fund_code="000001", ok=True, message="成功", code="ok", allocations=[]
    )
    with (
        patch.dict(sys.modules, {"akshare": fake}),
        patch.dict(
            fetch_fund._industry_cache,
            {"000001": {"ts": fetch_fund.time.time(), "data": cached}},
            clear=True,
        ),
    ):
        result = fetch_fund.fetch_fund_industry_allocation("000001")
    fake.fund_portfolio_industry_allocation_em.assert_not_called()
    assert result.ok
    assert result.allocations == []


class TestCleanIndustryName:
    """_clean_industry_name: 去掉前导数字/空白（数据源有时把序号拼到行业名前）。"""

    def test_strips_leading_number(self):
        assert fetch_fund._clean_industry_name("45信息技术") == "信息技术"

    def test_strips_leading_number_with_spaces(self):
        assert fetch_fund._clean_industry_name("12 制造业") == "制造业"

    def test_normal_name_unchanged(self):
        assert fetch_fund._clean_industry_name("非必需消费品") == "非必需消费品"

    def test_empty_string(self):
        assert fetch_fund._clean_industry_name("") == ""

    def test_pipeline_integration(self):
        """DataFrame 含脏值时，清洗后返回正确行业名。"""
        df = pd.DataFrame(
            {
                "行业类别": ["45制造业", "非必需消费品", "11金融"],
                "占净值比例": [80.0, 10.0, 5.0],
                "市值": [1000, 500, 200],
                "截止时间": ["2026-06-30"] * 3,
            }
        )
        fake = _fake_akshare_industry(df)
        with (
            patch.dict(sys.modules, {"akshare": fake}),
            patch.dict(fetch_fund._industry_cache, {}, clear=True),
        ):
            result = fetch_fund.fetch_fund_industry_allocation("000001")
        assert result.ok
        assert result.allocations[0].industry == "制造业"
        assert result.allocations[1].industry == "非必需消费品"
        assert result.allocations[2].industry == "金融"


# ---------------------------------------------------------------------------
# 申购状态（限购/暂停申购）
# ---------------------------------------------------------------------------
def _purchase_df() -> pd.DataFrame:
    """构造申购状态 DataFrame（与 AkShare fund_purchase_em 列名一致）。"""
    return pd.DataFrame(
        {
            "基金代码": ["160213", "000001"],
            "申购状态": ["暂停申购", "限大额"],
            "日累计限定金额": [100.0, float("nan")],
            "购买起点": [10.0, 100.0],
        }
    )


def _fake_akshare_purchase(df):
    fake = ModuleType("akshare")
    fake.fund_purchase_em = MagicMock(return_value=df)
    return fake


@pytest.fixture
def purchase_cache():
    """重置申购状态缓存，避免跨测试污染。"""
    fetch_fund._purchase_cache.clear()
    fetch_fund._purchase_cache_ts = 0.0
    yield
    fetch_fund._purchase_cache.clear()
    fetch_fund._purchase_cache_ts = 0.0


class TestFetchPurchaseStatus:
    def test_filters_requested_codes(self, purchase_cache):
        fake = _fake_akshare_purchase(_purchase_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            result = fetch_fund.fetch_purchase_status(
                ["160213", "000001", "999999"]
            )
        assert set(result) == {"160213", "000001"}
        assert result["160213"]["status"] == "暂停申购"
        assert result["160213"]["daily_limit"] == 100.0
        assert result["000001"]["daily_limit"] == 0.0  # NaN -> 0
        assert result["000001"]["min_purchase"] == 100.0

    def test_empty_codes(self, purchase_cache):
        fake = _fake_akshare_purchase(_purchase_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            assert fetch_fund.fetch_purchase_status([]) == {}

    def test_cache_hit_no_refetch(self, purchase_cache):
        fake = _fake_akshare_purchase(_purchase_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            fetch_fund.fetch_purchase_status(["000001"])
            fetch_fund.fetch_purchase_status(["000001"])
        assert fake.fund_purchase_em.call_count == 1

    def test_network_failure_returns_stale(self, purchase_cache):
        fake = _fake_akshare_purchase(_purchase_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            first = fetch_fund.fetch_purchase_status(["000001"])
        assert "000001" in first
        # 过期 + 网络失败 → 返回过期缓存（stale-if-error）
        fetch_fund._purchase_cache_ts = 0.0
        failing = ModuleType("akshare")
        failing.fund_purchase_em = MagicMock(side_effect=RuntimeError("boom"))
        with patch.dict(sys.modules, {"akshare": failing}):
            stale = fetch_fund.fetch_purchase_status(["000001"])
        assert "000001" in stale

    def test_write_back_to_db(self, purchase_cache):
        fake = _fake_akshare_purchase(_purchase_df())
        updates: list[tuple] = []

        def _record(code, status, daily_limit, min_purchase):
            updates.append((code, status, daily_limit, min_purchase))

        with (
            patch.dict(sys.modules, {"akshare": fake}),
            patch.object(fetch_fund.db, "update_fund_purchase_status", _record),
        ):
            n = fetch_fund.refresh_purchase_status(["160213", "000001"])
        assert n == 2
        assert ("160213", "暂停申购", 100.0, 10.0) in updates


# ---------------------------------------------------------------------------
# A 股交易日历
# ---------------------------------------------------------------------------
def _calendar_df():
    """构造交易日历 DataFrame（date 对象 + 字符串混合）。"""
    return pd.DataFrame(
        {"trade_date": [pd.Timestamp("2026-09-30"), "2026-10-08", "2026-10-09"]}
    )


def _fake_akshare_calendar(df):
    fake = ModuleType("akshare")
    fake.tool_trade_date_hist_sina = MagicMock(return_value=df)
    return fake


@pytest.fixture
def trade_cal_cache():
    """重置交易日历缓存，避免跨测试污染。"""
    fetch_fund._trade_cal_cache.clear()
    fetch_fund._trade_cal_cache_ts = 0.0
    yield
    fetch_fund._trade_cal_cache.clear()
    fetch_fund._trade_cal_cache_ts = 0.0


class TestFetchTradeCalendar:
    def test_parses_dates(self, trade_cal_cache):
        fake = _fake_akshare_calendar(_calendar_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            result = fetch_fund.fetch_trade_calendar()
        assert result == {"2026-09-30", "2026-10-08", "2026-10-09"}

    def test_cache_hit_no_refetch(self, trade_cal_cache):
        fake = _fake_akshare_calendar(_calendar_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            fetch_fund.fetch_trade_calendar()
            fetch_fund.fetch_trade_calendar()
        assert fake.tool_trade_date_hist_sina.call_count == 1

    def test_network_failure_returns_stale(self, trade_cal_cache):
        fake = _fake_akshare_calendar(_calendar_df())
        with patch.dict(sys.modules, {"akshare": fake}):
            first = fetch_fund.fetch_trade_calendar()
        assert "2026-10-08" in first
        fetch_fund._trade_cal_cache_ts = 0.0  # 强制过期
        failing = ModuleType("akshare")
        failing.tool_trade_date_hist_sina = MagicMock(side_effect=RuntimeError("boom"))
        with patch.dict(sys.modules, {"akshare": failing}):
            stale = fetch_fund.fetch_trade_calendar()
        assert "2026-10-08" in stale

    def test_refresh_persists(self, trade_cal_cache):
        fake = _fake_akshare_calendar(_calendar_df())
        saved: list[list[str]] = []
        with (
            patch.dict(sys.modules, {"akshare": fake}),
            patch.object(fetch_fund.db, "upsert_trade_calendar",
                         lambda dates: saved.append(dates) or len(dates)),
        ):
            n = fetch_fund.refresh_trade_calendar()
        assert n == 3
        assert saved == [["2026-09-30", "2026-10-08", "2026-10-09"]]


# ---------------------------------------------------------------------------
# 赎回费 FIFO（回放历史 sell/reinvest）+ update_fund_nav 容错
# ---------------------------------------------------------------------------
import sqlite3  # noqa: E402

from zfundpilot import config, db  # noqa: E402


@pytest.fixture
def fee_db(tmp_path, monkeypatch):
    """临时数据库 + 固定赎回费率档（不联网）。"""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    rates = fetch_fund.FeeRates(
        fund_code="001", ok=True, message="成功", code="ok",
        redemption=[
            fetch_fund.RedemptionTier(min_days=0, max_days=6, rate=0.015),
            fetch_fund.RedemptionTier(min_days=7, max_days=29, rate=0.0075),
            fetch_fund.RedemptionTier(min_days=30, max_days=364, rate=0.005),
            fetch_fund.RedemptionTier(min_days=365, max_days=None, rate=0.0),
        ],
    )
    monkeypatch.setattr(fetch_fund, "fetch_fund_fee_rates", lambda code: rates)


def _add_tx(action: str, date: str, shares: float) -> int:
    """写入一笔 001 基金流水（nav=1.0，normalize 自动补金额）。"""
    return db.add_transaction(Transaction(
        fund_code="001", action=action, date=date, shares=shares, nav=1.0))


def _add_nav(date: str, nav: float = 2.0) -> None:
    db.upsert_nav_batch([NavPoint(fund_code="001", date=date, nav=nav)])


def test_redemption_fee_fifo_consumes_prior_sells(fee_db):
    """买A→买B→卖(耗A)→再卖：第二次卖出应从 B 批起算持有期。"""
    _add_tx("buy", "2026-01-05", 100)   # A 批
    _add_tx("buy", "2026-06-01", 100)   # B 批
    _add_tx("sell", "2026-06-15", 100)  # 消耗 A 批（已入库，回填场景）
    _add_nav("2026-06-15")
    _add_nav("2026-06-20")

    # 6/15 卖出本身（已在库中）不能被重复消耗：仍从 A 批起算 161 天 → 0.5%
    first = fetch_fund.calc_redemption_fee("001", "2026-06-15", 100)
    assert first.code == "redemption_rate"
    assert first.lots[0]["buy_date"] == "2026-01-05"
    assert first.fee == pytest.approx(1.0)  # 100 × 2.0 × 0.005

    # 6/20 再卖应从 B 批起算 19 天 → 0.75%（旧实现误从 A 批 166 天 → 0.5%）
    second = fetch_fund.calc_redemption_fee("001", "2026-06-20", 100)
    assert second.code == "redemption_rate"
    assert len(second.lots) == 1
    assert second.lots[0]["buy_date"] == "2026-06-01"
    assert second.lots[0]["days_held"] == 19
    assert second.lots[0]["rate"] == pytest.approx(0.0075)
    assert second.fee == pytest.approx(1.5)  # 100 × 2.0 × 0.0075


def test_redemption_fee_fifo_partial_lot_consumption(fee_db):
    """此前卖出跨批次消耗后，再卖只匹配剩余份额。"""
    _add_tx("buy", "2026-01-05", 100)
    _add_tx("buy", "2026-06-01", 100)
    _add_tx("sell", "2026-06-15", 150)  # 耗尽 A + B 的 50 份
    _add_nav("2026-06-20")

    res = fetch_fund.calc_redemption_fee("001", "2026-06-20", 50)
    assert res.code == "redemption_rate"
    assert len(res.lots) == 1
    assert res.lots[0]["buy_date"] == "2026-06-01"
    assert res.lots[0]["buy_shares"] == pytest.approx(50)  # B 批剩余份额
    assert res.lots[0]["used_shares"] == pytest.approx(50)
    assert res.fee == pytest.approx(0.75)  # 50 × 2.0 × 0.0075


def test_redemption_fee_reinvest_lot(fee_db):
    """reinvest 份额作为新批次，持有期自再投资日起算。"""
    _add_tx("buy", "2026-01-05", 100)
    _add_tx("sell", "2026-02-01", 100)     # 耗尽买入批次
    _add_tx("reinvest", "2026-06-01", 50)  # 红利再投资
    _add_nav("2026-06-10")

    res = fetch_fund.calc_redemption_fee("001", "2026-06-10", 50)
    assert res.code == "redemption_rate"
    assert len(res.lots) == 1
    assert res.lots[0]["buy_date"] == "2026-06-01"
    assert res.lots[0]["days_held"] == 9
    # 旧实现忽略 reinvest 份额、误按 A 批 156 天计 0.5%（0.5 元）
    assert res.fee == pytest.approx(0.75)  # 50 × 2.0 × 0.0075


def test_redemption_fee_fifo_buy_then_reinvest(fee_db):
    """卖出跨 buy+reinvest 批次时按各自持有期分档计费。"""
    _add_tx("buy", "2026-01-05", 100)
    _add_tx("reinvest", "2026-06-01", 50)
    _add_nav("2026-06-10")

    res = fetch_fund.calc_redemption_fee("001", "2026-06-10", 120)
    assert res.code == "redemption_rate"
    assert len(res.lots) == 2
    assert res.lots[0]["buy_date"] == "2026-01-05"
    assert res.lots[0]["used_shares"] == pytest.approx(100)
    assert res.lots[0]["rate"] == pytest.approx(0.005)   # 156 天
    assert res.lots[1]["buy_date"] == "2026-06-01"
    assert res.lots[1]["used_shares"] == pytest.approx(20)
    assert res.lots[1]["rate"] == pytest.approx(0.0075)  # 9 天
    assert res.fee == pytest.approx(1.3)  # 100×2×0.005 + 20×2×0.0075


def test_redemption_fee_oversell_uses_lowest_tier(fee_db):
    """超出剩余买入总量的份额按最后一档计费（保留旧兜底口径）。"""
    _add_tx("buy", "2026-01-05", 100)
    _add_nav("2026-06-20")

    res = fetch_fund.calc_redemption_fee("001", "2026-06-20", 150)
    assert res.code == "redemption_rate"
    assert len(res.lots) == 2
    assert res.lots[0]["used_shares"] == pytest.approx(100)
    assert res.lots[1]["buy_date"] == ""
    assert res.lots[1]["used_shares"] == pytest.approx(50)
    assert res.lots[1]["rate"] == 0.0  # 最后一档（>=365 天）0 费率
    assert res.fee == pytest.approx(1.0)


def test_redemption_fee_no_buy_record(fee_db):
    """无买入/再投资记录（含只有卖出）→ no_buy_record。"""
    _add_nav("2026-06-20")
    res = fetch_fund.calc_redemption_fee("001", "2026-06-20", 100)
    assert res.code == "no_buy_record"

    _add_tx("sell", "2026-01-05", 100)
    res = fetch_fund.calc_redemption_fee("001", "2026-06-20", 100)
    assert res.code == "no_buy_record"


def test_redemption_fee_ignores_future_flows(fee_db):
    """晚于卖出日的买入/卖出不影响本次批次匹配与持有期。"""
    _add_tx("buy", "2026-01-05", 100)
    _add_tx("buy", "2026-07-01", 100)    # 未来买入
    _add_tx("sell", "2026-09-01", 100)   # 未来卖出
    _add_nav("2026-06-20")

    res = fetch_fund.calc_redemption_fee("001", "2026-06-20", 100)
    assert res.code == "redemption_rate"
    assert len(res.lots) == 1
    assert res.lots[0]["buy_date"] == "2026-01-05"
    assert res.lots[0]["days_held"] == 166
    assert res.fee == pytest.approx(1.0)


def test_redemption_fee_short_held_tier(fee_db):
    """持有 <7 天适用惩罚性费率档。"""
    _add_tx("buy", "2026-06-01", 100)
    _add_nav("2026-06-05")

    res = fetch_fund.calc_redemption_fee("001", "2026-06-05", 100)
    assert res.lots[0]["days_held"] == 4
    assert res.fee == pytest.approx(3.0)  # 100 × 2.0 × 0.015


def test_redemption_fee_pending_nav(fee_db):
    """卖出日及之后无净值 → pending_nav（T+1 待确认）。"""
    _add_tx("buy", "2026-06-01", 100)
    res = fetch_fund.calc_redemption_fee("001", "2026-06-05", 100)
    assert res.code == "pending_nav"


def test_update_fund_nav_success(monkeypatch):
    points = [NavPoint(fund_code="001", date="2026-06-19", nav=1.9),
              NavPoint(fund_code="001", date="2026-06-20", nav=2.0)]
    monkeypatch.setattr(fetch_fund, "fetch_nav_history", lambda code: points)
    monkeypatch.setattr(fetch_fund.db, "upsert_nav_batch", lambda pts: len(pts))

    res = fetch_fund.update_fund_nav("001")
    assert res.ok and res.code == "ok"
    assert res.written == 2
    assert res.latest_date == "2026-06-20"
    assert res.latest_nav == 2.0


def test_update_fund_nav_fetch_error_no_throw(monkeypatch):
    monkeypatch.setattr(fetch_fund, "fetch_nav_history",
                        MagicMock(side_effect=RuntimeError("网络错误")))
    res = fetch_fund.update_fund_nav("001")
    assert not res.ok
    assert res.code == "fetch_error"


def test_update_fund_nav_db_error_no_throw(monkeypatch):
    """DB 写失败返回 ok=False/db_error，不抛异常（契约：不抛异常）。"""
    points = [NavPoint(fund_code="001", date="2026-06-20", nav=2.0)]
    monkeypatch.setattr(fetch_fund, "fetch_nav_history", lambda code: points)
    monkeypatch.setattr(fetch_fund.db, "upsert_nav_batch",
                        MagicMock(side_effect=sqlite3.OperationalError("database is locked")))

    res = fetch_fund.update_fund_nav("001")
    assert not res.ok
    assert res.code == "db_error"
    assert "database is locked" in res.message


def test_update_all_holdings_nav_continues_after_db_error(monkeypatch):
    """单只基金 DB 失败不中断批量循环，逐只返回 FetchResult。"""
    monkeypatch.setattr(
        fetch_fund, "fetch_nav_history",
        lambda code: [NavPoint(fund_code=code, date="2026-06-20", nav=2.0)])

    def _upsert(pts):
        if pts[0].fund_code == "001":
            raise sqlite3.OperationalError("disk full")
        return len(pts)

    monkeypatch.setattr(fetch_fund.db, "upsert_nav_batch", _upsert)
    monkeypatch.setattr(fetch_fund.time, "sleep", lambda s: None)

    results = fetch_fund.update_all_holdings_nav(codes=["001", "002"])
    assert len(results) == 2
    assert not results[0].ok and results[0].code == "db_error"
    assert results[1].ok and results[1].written == 1
