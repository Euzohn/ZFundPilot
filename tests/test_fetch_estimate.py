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
            estimates = [est]
            _index_fallback(estimates, merged)
        assert estimates[0].ok
        assert estimates[0].gsz == 2.03
        assert estimates[0].gszzl == 1.5
        assert estimates[0].code == "index_estimate"

    def test_no_cache_mutation(self):
        """缓存污染修复验证：_index_fallback 不得原地改写缓存共享对象。

        传入的 FundEstimate 对象是 30s 批量缓存的引用，调用后原始对象字段
        必须保持不变；兜底结果应写入新对象并放回 list。
        """
        est = _make_est(dwjz=2.0, jzrq="2026-01-05")
        merged = {"001": {"tracking_index": "沪深300", "latest_date": None}}
        with (
            patch("zfundpilot.api.fetch_estimate.fetch_index_quotes",
                  return_value={"沪深300": 1.5}),
            patch("zfundpilot.api.db.get_latest_nav",
                  return_value={"nav": 2.0, "date": "2026-01-05"}),
        ):
            from zfundpilot.api import _index_fallback
            estimates = [est]
            _index_fallback(estimates, merged)
        assert not est.ok
        assert est.dwjz == 2.0
        assert est.jzrq == "2026-01-05"
        assert est.gsz == 0.0
        assert est.gszzl == 0.0
        assert est.code == ""
        assert estimates[0] is not est

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


# ---------------------------------------------------------------------------
# get_estimates DB-override 缓存污染回归
# ---------------------------------------------------------------------------
class TestGetEstimatesCacheMutation:
    """get_estimates 的 DB-override 分支不得改写缓存共享对象。"""

    def _position(self, fund_code, latest_date):
        from types import SimpleNamespace
        return SimpleNamespace(
            fund_code=fund_code,
            fund_name="测试基金",
            is_open=True,
            held_shares=100.0,
            latest_date=latest_date,
            tracking_index="",
        )

    def test_db_override_no_cache_mutation(self):
        """当日净值已入库时 DB-override 改写为新对象，原缓存对象不变。"""
        from zfundpilot import config

        today = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
        est = FundEstimate(
            fund_code="001", fund_name="测试基金", ok=True,
            dwjz=1.0, gsz=1.1, gszzl=10.0, gztime="2026-01-05 15:00",
        )
        positions = [self._position("001", today)]
        with (
            patch("zfundpilot.api.analysis.calculate_positions", return_value=positions),
            patch("zfundpilot.api.fetch_estimate.fetch_estimates", return_value=[est]),
            patch("zfundpilot.api.db.get_latest_nav",
                  return_value={"nav": 1.2, "date": today}),
            patch("zfundpilot.api.db.get_prev_nav",
                  return_value={"nav": 1.0, "date": "2026-01-05"}),
        ):
            from zfundpilot.api import get_estimates
            resp = get_estimates()

        # 缓存共享对象未被原地改写
        assert est.ok is True
        assert est.dwjz == 1.0
        assert est.gsz == 1.1
        assert est.gszzl == 10.0
        # 响应使用 DB override 后的数据
        f = resp["funds"][0]
        assert f["ok"] is False
        assert f["gsz"] == 1.2
        assert f["dwjz"] == 1.0
        assert f["gszzl"] == 20.0


# ---------------------------------------------------------------------------
# fetch_index_history：DB 持久化 + 离线 fallback
# ---------------------------------------------------------------------------
class TestIndexHistoryDB:
    """index_history 表 CRUD + fetch_index_history 三级缓存测试。"""

    def _setup_db(self, tmp_path):
        import os

        import zfundpilot.db as db_module
        from zfundpilot import config

        db_path = os.path.join(str(tmp_path), "test.db")
        original = config.DB_PATH
        config.DB_PATH = db_path
        db_module.init_db()
        return db_module, original

    def _teardown(self, original):
        from zfundpilot import config
        config.DB_PATH = original
        # 清空内存缓存
        from zfundpilot.fetch_estimate import clear_index_hist_cache
        clear_index_hist_cache()

    def test_upsert_and_get_index_history(self, tmp_path):
        """upsert_index_history + get_index_history 基本读写。"""
        db, original = self._setup_db(tmp_path)
        try:
            db.upsert_index_history("000300", [
                ("2026-01-01", 3800.0),
                ("2026-01-02", 3850.0),
                ("2026-01-03", 3900.0),
            ])
            rows = db.get_index_history("000300", "2026-01-02", "2026-01-03")
            assert len(rows) == 2
            assert rows[0]["date"] == "2026-01-02"
            assert float(rows[0]["close"]) == 3850.0
            assert rows[1]["date"] == "2026-01-03"
        finally:
            self._teardown(original)

    def test_upsert_is_idempotent(self, tmp_path):
        """重复 upsert 不报错，close 被更新。"""
        db, original = self._setup_db(tmp_path)
        try:
            db.upsert_index_history("000300", [("2026-01-01", 3800.0)])
            db.upsert_index_history("000300", [("2026-01-01", 3801.0)])
            rows = db.get_index_history("000300")
            assert len(rows) == 1
            assert float(rows[0]["close"]) == 3801.0
        finally:
            self._teardown(original)

    def test_get_index_latest_date(self, tmp_path):
        """get_index_latest_date 返回最新日期。"""
        db, original = self._setup_db(tmp_path)
        try:
            assert db.get_index_latest_date("000300") is None
            db.upsert_index_history("000300", [
                ("2026-01-01", 3800.0),
                ("2026-01-03", 3900.0),
            ])
            assert db.get_index_latest_date("000300") == "2026-01-03"
        finally:
            self._teardown(original)

    def test_fetch_index_history_persists_to_db(self, tmp_path):
        """fetch_index_history 成功拉取后持久化到 DB。"""
        db, original = self._setup_db(tmp_path)
        try:
            # 模拟 AkShare 返回数据
            import pandas as pd
            mock_df = pd.DataFrame({
                "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
                "close": [3800.0, 3850.0, 3900.0],
            })
            with patch("zfundpilot.fetch_estimate.ak.stock_zh_index_daily",
                       return_value=mock_df):
                from zfundpilot.fetch_estimate import fetch_index_history
                result = fetch_index_history("000300", "2026-01-01", "2026-01-03")
            assert len(result) == 3
            assert result[0] == {"date": "2026-01-01", "close": 3800.0}
            # 验证 DB 已持久化
            rows = db.get_index_history("000300")
            assert len(rows) == 3
            assert db.get_index_latest_date("000300") == "2026-01-03"
        finally:
            self._teardown(original)

    def test_fetch_index_history_offline_fallback(self, tmp_path):
        """离线场景：AkShare 失败时从 DB 返回缓存数据。"""
        db, original = self._setup_db(tmp_path)
        try:
            # 先写入 DB 数据
            db.upsert_index_history("000300", [
                ("2026-01-01", 3800.0),
                ("2026-01-02", 3850.0),
            ])
            # 模拟今天日期 = 2026-01-03（DB 最新 01-02 < today → need_fetch=True）
            # AkShare 失败 → fallback DB
            with (
                patch("zfundpilot.fetch_estimate.ak.stock_zh_index_daily",
                      side_effect=Exception("network error")),
                patch("zfundpilot.fetch_estimate.datetime") as mock_dt,
            ):
                from datetime import datetime as real_dt
                mock_dt.now.return_value = real_dt(2026, 1, 3)
                from zfundpilot.fetch_estimate import fetch_index_history
                result = fetch_index_history("000300", "2026-01-01", "2026-01-02")
            # 离线 fallback：返回 DB 缓存数据
            assert len(result) == 2
            assert result[0]["date"] == "2026-01-01"
            assert result[0]["close"] == 3800.0
        finally:
            self._teardown(original)

    def test_fetch_index_history_db_hit_no_fetch(self, tmp_path):
        """DB 已有最新数据时不再在线拉取。"""
        db, original = self._setup_db(tmp_path)
        try:
            from datetime import datetime as real_dt
            # DB 最新日期 = today → need_fetch=False → 不调 AkShare
            today_str = real_dt.now().strftime("%Y-%m-%d")
            db.upsert_index_history("000300", [
                ("2026-01-01", 3800.0),
                (today_str, 3900.0),
            ])
            with patch("zfundpilot.fetch_estimate.ak.stock_zh_index_daily") as mock_ak:
                from zfundpilot.fetch_estimate import fetch_index_history
                result = fetch_index_history("000300", "2026-01-01", today_str)
                mock_ak.assert_not_called()
            assert len(result) == 2
        finally:
            self._teardown(original)
