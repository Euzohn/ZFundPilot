"""持有人结构（机构/个人/内部持有比例）抓取与筛选增强测试。"""

from unittest.mock import MagicMock, patch

from zfundpilot import fetch_fund, fund_filter

_HOLDER_HTML = """var apidata={ content:"<table class='w782 comm cyrjg'><thead><tr>
<th class='first'>公告日期</th><th>机构持有比例</th><th>个人持有比例</th>
<th>内部持有比例</th><th class='last'>总份额（亿份）</th></tr></thead><tbody>
<tr><td>2025-12-31</td><td class='tor'>0.77%</td><td class='tor'>99.23%</td><td class='tor'>0.10%</td><td class='tor'>166.57</td></tr>
<tr><td>2026-06-30</td><td class='tor'>0.78%</td><td class='tor'>99.22%</td><td class='tor'>0.06%</td><td class='tor'>133.67</td></tr>
<tr><td>2024-12-31</td><td class='tor'>0.67%</td><td class='tor'>99.33%</td><td class='tor'>0.08%</td><td class='tor'>215.17</td></tr>
</tbody></table>"};
"""

_HOLDER = {
    "report_date": "2026-06-30",
    "institution_ratio": 0.78,
    "individual_ratio": 99.22,
    "internal_ratio": 0.06,
    "total_shares": 133.67,
}


def test_fetch_holder_structure_parses_latest_report():
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value=_HOLDER_HTML) as get,
    ):
        data = fetch_fund.fetch_holder_structure("005827")

    assert data == _HOLDER
    url = get.call_args.args[0]
    assert "type=cyrjg" in url and "code=005827" in url


def test_fetch_holder_structure_picks_max_date_when_unordered():
    shuffled = _HOLDER_HTML.replace("2026-06-30", "2026-07-01").replace(
        "2025-12-31", "2026-06-30"
    )
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value=shuffled),
    ):
        data = fetch_fund.fetch_holder_structure("005827")

    assert data is not None
    # 2026-07-01 那行数值仍是 0.78/99.22，但报告期应取最大日期
    assert data["report_date"] == "2026-07-01"


def test_fetch_holder_structure_empty_returns_none():
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value='var apidata={ content:""};'),
    ):
        assert fetch_fund.fetch_holder_structure("005827") is None


def test_fetch_holder_structure_failure_returns_none():
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", side_effect=OSError("boom")),
    ):
        assert fetch_fund.fetch_holder_structure("005827") is None


def test_fetch_holder_structure_cache_and_clear():
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value=_HOLDER_HTML) as get,
    ):
        fetch_fund.fetch_holder_structure("005827")
        fetch_fund.fetch_holder_structure("005827")
        assert get.call_count == 1

        fetch_fund.clear_holder_cache()
        fetch_fund.fetch_holder_structure("005827")
        assert get.call_count == 2


def test_fetch_holder_structure_caches_failure():
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", side_effect=OSError("boom")) as get,
    ):
        assert fetch_fund.fetch_holder_structure("005827") is None
        assert fetch_fund.fetch_holder_structure("005827") is None
        assert get.call_count == 1


def test_fetch_holder_structure_failure_cache_expires():
    with (
        patch.dict(fetch_fund._holder_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", side_effect=OSError("boom")) as get,
    ):
        assert fetch_fund.fetch_holder_structure("005827") is None
        fetch_fund._holder_cache["005827"]["ts"] -= fetch_fund._HOLDER_FAILURE_TTL + 1
        assert fetch_fund.fetch_holder_structure("005827") is None
        assert get.call_count == 2


def test_profile_includes_holder_structure():
    ping = 'var Data_fluctuationScale = {"series":[{"y":204.16}]};'
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value=ping),
        patch.object(fetch_fund, "fetch_holder_structure", return_value=_HOLDER),
        patch.object(fetch_fund, "fetch_risk_level", return_value=""),
        patch.object(fetch_fund, "fetch_fund_fee_rates") as fees,
    ):
        fees.return_value = MagicMock(ok=False)
        profile = fetch_fund.fetch_fund_profile("005827")

    assert profile.ok
    assert profile.institution_ratio == 0.78
    assert profile.individual_ratio == 99.22
    assert profile.internal_ratio == 0.06
    assert profile.holder_report_date == "2026-06-30"
    assert profile.to_dict()["institution_ratio"] == 0.78


def test_profile_ok_when_holder_structure_missing():
    ping = 'var Data_fluctuationScale = {"series":[{"y":204.16}]};'
    with (
        patch.dict(fetch_fund._profile_cache, {}, clear=True),
        patch.object(fetch_fund, "_http_get", return_value=ping),
        patch.object(fetch_fund, "fetch_holder_structure", return_value=None),
        patch.object(fetch_fund, "fetch_risk_level", return_value=""),
        patch.object(fetch_fund, "fetch_fund_fee_rates") as fees,
    ):
        fees.return_value = MagicMock(ok=False)
        profile = fetch_fund.fetch_fund_profile("005827")

    assert profile.ok
    assert profile.institution_ratio is None
    assert profile.holder_report_date == ""


def test_enrich_snapshot_includes_holder_structure():
    item = fund_filter.FundFilterItem(
        code="005827", name="易方达蓝筹精选", type="混合型", sector=""
    )
    with (
        patch.object(
            fund_filter._compare, "_get_cached_nav", return_value=MagicMock(empty=True)
        ),
        patch.object(
            fund_filter._compare,
            "_get_fund_archive",
            return_value={"scale": 204.16, "manager": "张坤", "inception": "2015-06-15"},
        ),
        patch.object(fund_filter, "fetch_holder_structure", return_value=_HOLDER),
    ):
        snapshot = fund_filter._enrich_snapshot(item)

    assert snapshot["institution_ratio"] == 0.78
    assert snapshot["individual_ratio"] == 99.22
    assert snapshot["internal_ratio"] == 0.06
    assert snapshot["holder_report_date"] == "2026-06-30"


def test_enrich_one_assigns_holder_fields():
    item = fund_filter.FundFilterItem(
        code="005827", name="易方达蓝筹精选", type="混合型", sector=""
    )
    snapshot = {
        "scale": 204.16,
        "manager": "张坤",
        "inception_date": "2015-06-15",
        "institution_ratio": 0.78,
        "individual_ratio": 99.22,
        "internal_ratio": 0.06,
        "holder_report_date": "2026-06-30",
        "returns": {},
        "risk": {},
    }
    with patch.object(fund_filter, "_enrich_snapshot", return_value=snapshot):
        fund_filter._enrich_one(item)

    assert item.institution_ratio == 0.78
    assert item.individual_ratio == 99.22
    assert item.internal_ratio == 0.06
    assert item.holder_report_date == "2026-06-30"


def test_enrich_one_keeps_none_when_holder_missing():
    item = fund_filter.FundFilterItem(
        code="005827", name="易方达蓝筹精选", type="混合型", sector=""
    )
    snapshot = {
        "scale": None,
        "manager": "",
        "inception_date": "",
        "institution_ratio": None,
        "individual_ratio": None,
        "internal_ratio": None,
        "holder_report_date": "",
        "returns": {},
        "risk": {},
    }
    with patch.object(fund_filter, "_enrich_snapshot", return_value=snapshot):
        fund_filter._enrich_one(item)

    assert item.institution_ratio is None
    assert item.holder_report_date == ""
