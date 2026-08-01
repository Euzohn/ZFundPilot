"""fetch_fund 新增功能测试：同类排名走势、基金档案。"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd

from zfundpilot import fetch_fund
from zfundpilot.models import FundProfile, FundRankingResult


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


def test_fetch_fund_profile_success():
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value=_PINGZHONGDATA_SAMPLE),
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


def test_fetch_fund_profile_no_manager():
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value="var nothing = 1;"),
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
