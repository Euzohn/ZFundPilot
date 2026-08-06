"""fetch_estimate 模块测试：安全转换、关键词匹配、指数行情、指数估值兜底。"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from zfundpilot.fetch_estimate import (
    FundEstimate,
    _match_keyword,
    _safe_float,
    _safe_pct,
    estimate_from_index,
    fetch_index_quotes,
)

_TZ = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------------------
# _safe_float / _safe_pct
# ---------------------------------------------------------------------------
class TestSafeFloat:
    def test_normal(self):
        assert _safe_float("1.23") == 1.23

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_empty(self):
        assert _safe_float("") == 0.0

    def test_dash(self):
        assert _safe_float("--") == 0.0

    def test_nan(self):
        assert _safe_float(float("nan")) == 0.0

    def test_invalid(self):
        assert _safe_float("abc") == 0.0

    def test_int_input(self):
        assert _safe_float(5) == 5.0


class TestSafePct:
    def test_with_percent(self):
        assert _safe_pct("0.98%") == 0.98

    def test_without_percent(self):
        assert _safe_pct("0.98") == 0.98

    def test_none(self):
        assert _safe_pct(None) == 0.0

    def test_dash(self):
        assert _safe_pct("--") == 0.0

    def test_zero(self):
        assert _safe_pct("0.00%") == 0.0


# ---------------------------------------------------------------------------
# _match_keyword
# ---------------------------------------------------------------------------
class TestMatchKeyword:
    def test_exact_match(self):
        assert _match_keyword("沪深300", {"沪深300": 1.5}) == 1.5

    def test_contain_in_name(self):
        assert _match_keyword("沪深300", {"沪深300指数": 1.5}) == 1.5

    def test_name_in_keyword(self):
        assert _match_keyword("沪深300指数", {"沪深300": 1.5}) == 1.5

    def test_not_found(self):
        assert _match_keyword("日经225", {"沪深300": 1.5}) is None

    def test_substring_prefix_only(self):
        """仅前缀子串能匹配（contain 双向都不命中）。"""
        assert _match_keyword("半导体材料设备", {"半导体指数": 2.0}) == 2.0

    def test_empty_map(self):
        assert _match_keyword("沪深300", {}) is None


# ---------------------------------------------------------------------------
# fetch_index_quotes
# ---------------------------------------------------------------------------
class TestFetchIndexQuotes:
    def test_empty_keywords(self):
        assert fetch_index_quotes([]) == {}

    def test_all_from_index_cache(self):
        with (
            patch(
                "zfundpilot.fetch_estimate._get_index_spot_cached",
                return_value={"沪深300": 1.5, "中证500": -0.8},
            ),
            patch("zfundpilot.fetch_estimate._get_etf_spot_cached") as mock_etf,
        ):
            result = fetch_index_quotes(["沪深300", "中证500"])
        assert result == {"沪深300": 1.5, "中证500": -0.8}
        mock_etf.assert_not_called()

    def test_etf_fallback(self):
        with (
            patch(
                "zfundpilot.fetch_estimate._get_index_spot_cached",
                return_value={"沪深300": 1.5},
            ),
            patch(
                "zfundpilot.fetch_estimate._get_etf_spot_cached",
                return_value={"半导体ETF": 2.0},
            ),
        ):
            result = fetch_index_quotes(["沪深300", "半导体"])
        assert result == {"沪深300": 1.5, "半导体": 2.0}

    def test_unmatched_omitted(self):
        with (
            patch(
                "zfundpilot.fetch_estimate._get_index_spot_cached",
                return_value={"沪深300": 1.5},
            ),
            patch(
                "zfundpilot.fetch_estimate._get_etf_spot_cached",
                return_value={},
            ),
        ):
            result = fetch_index_quotes(["沪深300", "日经225"])
        assert result == {"沪深300": 1.5}


# ---------------------------------------------------------------------------
# estimate_from_index
# ---------------------------------------------------------------------------
class TestEstimateFromIndex:
    def test_valid(self):
        with patch(
            "zfundpilot.fetch_estimate.fetch_index_quotes",
            return_value={"沪深300": 1.5},
        ):
            est = estimate_from_index("001", "测试基金", "沪深300", 2.0, "2026-01-05")
        assert est.ok
        assert est.fund_code == "001"
        assert est.dwjz == 2.0
        assert est.gsz == 2.03  # 2.0 * (1 + 1.5/100)
        assert est.gszzl == 1.5
        assert est.code == "index_estimate"

    def test_no_quote(self):
        with patch(
            "zfundpilot.fetch_estimate.fetch_index_quotes",
            return_value={},
        ):
            est = estimate_from_index("001", "测试基金", "沪深300", 2.0, "2026-01-05")
        assert not est.ok
        assert est.code == "no_index_quote"

    def test_no_nav(self):
        with patch(
            "zfundpilot.fetch_estimate.fetch_index_quotes",
            return_value={"沪深300": 1.5},
        ):
            est = estimate_from_index("001", "测试基金", "沪深300", 0.0, "2026-01-05")
        assert not est.ok
        assert est.code == "no_index_quote"


# ---------------------------------------------------------------------------
# _index_fallback（api.py）
# ---------------------------------------------------------------------------
def _make_est(fund_code="001", ok=False, dwjz=0.0, gsz=0.0, gszzl=0.0,
              jzrq="", code="", message="") -> FundEstimate:
    return FundEstimate(
        fund_code=fund_code, ok=ok, dwjz=dwjz, gsz=gsz, gszzl=gszzl,
        jzrq=jzrq, code=code, message=message,
    )


class TestIndexFallback:
    def _run(self, estimates, merged, quotes=None, latest_nav=None):
        from zfundpilot.api import _index_fallback

        with (
            patch("zfundpilot.api.fetch_estimate.fetch_index_quotes",
                  return_value=quotes or {}),
            patch("zfundpilot.api.db.get_latest_nav", return_value=latest_nav),
        ):
            _index_fallback(estimates, merged)
        return estimates

    def test_skips_ok(self):
        est = _make_est(ok=True, dwjz=1.0)
        merged = {"001": {"tracking_index": "沪深300", "latest_date": None}}
        with patch("zfundpilot.api.fetch_estimate.fetch_index_quotes") as mock_q:
            from zfundpilot.api import _index_fallback
            _index_fallback([est], merged)
        mock_q.assert_not_called()
        assert est.ok

    def test_skips_no_tracking_index(self):
        est = _make_est()
        merged = {"001": {"tracking_index": "", "latest_date": None}}
        with patch("zfundpilot.api.fetch_estimate.fetch_index_quotes") as mock_q:
            from zfundpilot.api import _index_fallback
            _index_fallback([est], merged)
        mock_q.assert_not_called()

    def test_applies_when_dwjz_gt_zero(self):
        """est.ok=False, dwjz>0 且 tracking_index 存在 → 应执行兜底（bug fix 验证）。"""
        est = _make_est(dwjz=2.0, jzrq="2026-01-05")
        merged = {"001": {"tracking_index": "沪深300", "latest_date": None}}
        with (
            patch("zfundpilot.api.fetch_estimate.fetch_index_quotes",
                  return_value={"沪深300": 1.5}),
            patch("zfundpilot.api.db.get_latest_nav",
                  return_value={"nav": 2.0, "date": "2026-01-05"}),
        ):
            from zfundpilot.api import _index_fallback
            _index_fallback([est], merged)
        assert est.ok
        assert est.gsz == 2.03
        assert est.gszzl == 1.5
        assert est.code == "index_estimate"

    def test_skips_db_override(self):
        """当日净值已入库（latest_date == today）→ 跳过。"""
        today = datetime.now(_TZ).strftime("%Y-%m-%d")
        est = _make_est()
        merged = {"001": {"tracking_index": "沪深300", "latest_date": today}}
        with patch("zfundpilot.api.fetch_estimate.fetch_index_quotes") as mock_q:
            from zfundpilot.api import _index_fallback
            _index_fallback([est], merged)
        mock_q.assert_not_called()

    def test_skips_no_nav(self):
        """无 latest_nav → 跳过。"""
        est = _make_est(dwjz=2.0)
        merged = {"001": {"tracking_index": "沪深300", "latest_date": None}}
        with (
            patch("zfundpilot.api.fetch_estimate.fetch_index_quotes",
                  return_value={"沪深300": 1.5}),
            patch("zfundpilot.api.db.get_latest_nav", return_value=None),
        ):
            from zfundpilot.api import _index_fallback
            _index_fallback([est], merged)
        assert not est.ok

    def test_skips_quote_not_found(self):
        """指数行情未匹配 → 跳过。"""
        est = _make_est(dwjz=2.0)
        merged = {"001": {"tracking_index": "沪深300", "latest_date": None}}
        with (
            patch("zfundpilot.api.fetch_estimate.fetch_index_quotes",
                  return_value={}),
            patch("zfundpilot.api.db.get_latest_nav",
                  return_value={"nav": 2.0, "date": "2026-01-05"}),
        ):
            from zfundpilot.api import _index_fallback
            _index_fallback([est], merged)
        assert not est.ok
