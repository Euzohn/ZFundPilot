"""fetch_macro 模块测试：中文月份解析、CPI 链乘、M2 存量、三级缓存、API 端点。"""

import os
from unittest.mock import patch

import pandas as pd

from zfundpilot.fetch_macro import (
    _build_cpi_level,
    _macro_is_fresh,
    _parse_cn_month,
    _safe_float,
    fetch_macro_history,
)


# ---------------------------------------------------------------------------
# _parse_cn_month
# ---------------------------------------------------------------------------
class TestParseCnMonth:
    def test_normal(self):
        assert _parse_cn_month("2026年07月份") == "2026-07-31"

    def test_february_leap(self):
        assert _parse_cn_month("2024年02月份") == "2024-02-29"

    def test_february_non_leap(self):
        assert _parse_cn_month("2023年02月份") == "2023-02-28"

    def test_single_digit_month(self):
        assert _parse_cn_month("2026年01月份") == "2026-01-31"

    def test_invalid_month(self):
        assert _parse_cn_month("2026年13月份") is None

    def test_garbage(self):
        assert _parse_cn_month("not a date") is None

    def test_empty(self):
        assert _parse_cn_month("") is None


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------
class TestSafeFloat:
    def test_normal(self):
        assert _safe_float("1.5") == 1.5

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_nan(self):
        assert _safe_float(float("nan")) == 0.0

    def test_invalid(self):
        assert _safe_float("abc") == 0.0


# ---------------------------------------------------------------------------
# _build_cpi_level
# ---------------------------------------------------------------------------
class TestBuildCpiLevel:
    def test_chains_mom(self):
        """环比链乘：1.0% → 0.5% → 累计 (1.01*1.005-1)。"""
        df = pd.DataFrame({
            "月份": ["2024年01月份", "2024年02月份"],
            "全国-环比增长": [1.0, 0.5],
        })
        result = _build_cpi_level(df)
        assert len(result) == 2
        assert result[0]["date"] == "2024-01-31"
        assert result[0]["close"] == 101.0  # 100 * 1.01
        assert result[1]["close"] == 101.505  # 101 * 1.005

    def test_zero_mom_no_change(self):
        df = pd.DataFrame({
            "月份": ["2024年01月份", "2024年02月份"],
            "全国-环比增长": [0.0, 0.0],
        })
        result = _build_cpi_level(df)
        assert result[0]["close"] == 100.0
        assert result[1]["close"] == 100.0

    def test_ignores_bad_rows(self):
        df = pd.DataFrame({
            "月份": ["2024年01月份", "bad"],
            "全国-环比增长": [1.0, "x"],
        })
        result = _build_cpi_level(df)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _macro_is_fresh
# ---------------------------------------------------------------------------
class TestMacroIsFresh:
    def test_recent(self):
        assert _macro_is_fresh("2026-08-31")

    def test_stale(self):
        assert not _macro_is_fresh("2026-01-31")

    def test_invalid(self):
        assert not _macro_is_fresh("garbage")


# ---------------------------------------------------------------------------
# fetch_macro_history：三级缓存 + 排序 + 离线 fallback
# ---------------------------------------------------------------------------
def _setup_db(tmp_path):
    import zfundpilot.db as db_module
    from zfundpilot import config

    db_path = os.path.join(str(tmp_path), "test.db")
    original = config.DB_PATH
    config.DB_PATH = db_path
    db_module.init_db()
    return db_module, original


def _teardown(original):
    from zfundpilot import config
    config.DB_PATH = original
    from zfundpilot.fetch_macro import clear_macro_cache
    clear_macro_cache()


def _cpi_df():
    """模拟 AkShare CPI 返回（降序，最新在前，与真实数据一致）。"""
    return pd.DataFrame({
        "月份": ["2024年03月份", "2024年02月份", "2024年01月份"],
        "全国-环比增长": [0.3, 0.2, 0.1],
    })


def _m2_df():
    """模拟 AkShare M2 返回（降序）。"""
    return pd.DataFrame({
        "月份": ["2024年03月份", "2024年02月份", "2024年01月份"],
        "货币和准货币(M2)-数量(亿元)": [300000.0, 295000.0, 290000.0],
    })


class TestFetchMacroHistory:
    def test_fetch_cpi_ascending_and_persist(self, tmp_path):
        """CPI 在线拉取 → 升序返回 + 持久化到 DB。"""
        db, original = _setup_db(tmp_path)
        try:
            with patch("zfundpilot.fetch_macro.ak.macro_china_cpi",
                       return_value=_cpi_df()):
                result = fetch_macro_history("CPI", "2024-01-01", "2024-12-31")
            assert [r["date"] for r in result] == [
                "2024-01-31", "2024-02-29", "2024-03-31",
            ]
            # 升序链乘：100×1.001×1.002×1.003
            assert result[0]["close"] == 100.1
            assert result[1]["close"] == 100.3002
            assert result[2]["close"] == 100.6011
            # 持久化 + source="macro"
            rows = db.get_index_history("CPI")
            assert len(rows) == 3
            assert rows[0]["source"] == "macro"
        finally:
            _teardown(original)

    def test_fetch_m2_ascending_and_persist(self, tmp_path):
        """M2 在线拉取 → 升序返回 + 持久化。"""
        db, original = _setup_db(tmp_path)
        try:
            with patch("zfundpilot.fetch_macro.ak.macro_china_money_supply",
                       return_value=_m2_df()):
                result = fetch_macro_history("M2", "2024-01-01", "2024-12-31")
            assert [r["date"] for r in result] == [
                "2024-01-31", "2024-02-29", "2024-03-31",
            ]
            assert result[0]["close"] == 290000.0
            assert result[2]["close"] == 300000.0
            assert db.get_index_latest_date("M2") == "2024-03-31"
        finally:
            _teardown(original)

    def test_unknown_code(self, tmp_path):
        db, original = _setup_db(tmp_path)
        try:
            assert fetch_macro_history("FOO", "2024-01-01", "2024-12-31") == []
        finally:
            _teardown(original)

    def test_db_hit_no_fetch(self, tmp_path):
        """DB 数据新鲜时不再在线拉取。"""
        db, original = _setup_db(tmp_path)
        try:
            db.upsert_index_history("CPI", [
                ("2024-01-31", 100.0), ("2024-02-29", 100.2),
            ], source="macro")
            with (
                patch("zfundpilot.fetch_macro._macro_is_fresh", return_value=True),
                patch("zfundpilot.fetch_macro.ak.macro_china_cpi") as mock_ak,
            ):
                result = fetch_macro_history("CPI", "2024-01-01", "2024-03-01")
                mock_ak.assert_not_called()
            assert len(result) == 2
        finally:
            _teardown(original)

    def test_offline_fallback(self, tmp_path):
        """在线失败 → 从 DB 返回缓存（离线容灾）。"""
        db, original = _setup_db(tmp_path)
        try:
            db.upsert_index_history("CPI", [
                ("2024-01-31", 100.0),
            ], source="macro")
            with patch("zfundpilot.fetch_macro.ak.macro_china_cpi",
                       side_effect=Exception("network error")):
                result = fetch_macro_history("CPI", "2024-01-01", "2024-03-01")
            assert len(result) == 1
            assert result[0]["close"] == 100.0
        finally:
            _teardown(original)

    def test_date_range_filter(self, tmp_path):
        """按日期区间过滤。"""
        db, original = _setup_db(tmp_path)
        try:
            with patch("zfundpilot.fetch_macro.ak.macro_china_cpi",
                       return_value=_cpi_df()):
                result = fetch_macro_history("CPI", "2024-02-01", "2024-02-29")
            assert len(result) == 1
            assert result[0]["date"] == "2024-02-29"
        finally:
            _teardown(original)


# ---------------------------------------------------------------------------
# API 端点：/api/portfolio/benchmark 支持 CPI/M2
# ---------------------------------------------------------------------------
class TestBenchmarkEndpointMacro:
    def _curve(self):
        return pd.DataFrame({
            "date": ["2024-02-01", "2024-02-29", "2024-03-01"],
            "total_value": [100000.0, 101000.0, 102000.0],
            "invested_cost": [100000.0, 100000.0, 100000.0],
            "total_return": [0.0, 0.01, 0.02],
        })

    def test_cpi_and_m2_lines(self):
        """CPI/M2 与组合曲线日期对齐，累计收益率正确。"""
        from zfundpilot.api import get_portfolio_benchmark

        baselines = {
            "CPI": ([
                {"date": "2024-01-31", "close": 100.0},
                {"date": "2024-02-29", "close": 101.0},
            ], 100.0),
            "M2": ([
                {"date": "2024-01-31", "close": 100.0},
                {"date": "2024-02-29", "close": 110.0},
            ], 100.0),
        }

        with (
            patch("zfundpilot.api.analysis.build_portfolio_curve",
                  return_value=self._curve()),
            patch("zfundpilot.api.fetch_macro.fetch_macro_baseline",
                  side_effect=lambda code, s, e: baselines.get(code)),
        ):
            result = get_portfolio_benchmark("CPI,M2")

        assert len(result) == 3
        # 2024-02-01：基期点（1-31）在区间外 → ffill 0
        assert result[0]["CPI"] == 0.0
        # 2024-02-29：CPI 101/100-1 = 1%
        assert result[1]["CPI"] == 0.01
        # 2024-03-01：ffill 1%
        assert result[2]["CPI"] == 0.01
        # M2 110/100-1 = 10%
        assert result[1]["M2"] == 0.1
        assert result[2]["M2"] == 0.1
        # date 键保留
        assert result[0]["date"] == "2024-02-01"

    def test_macro_code_filtered_by_whitelist(self):
        """未知代码被白名单过滤。"""
        from zfundpilot.api import get_portfolio_benchmark

        with (
            patch("zfundpilot.api.analysis.build_portfolio_curve",
                  return_value=self._curve()),
            patch("zfundpilot.api.fetch_estimate.fetch_index_history",
                  return_value=[]),
        ):
            result = get_portfolio_benchmark("FOO,000300")
        # FOO 被白名单过滤；000300 无数据 → 跳过 → 空
        assert result == []

    def test_empty_indices(self):
        from zfundpilot.api import get_portfolio_benchmark
        assert get_portfolio_benchmark("") == []

    def test_empty_curve(self):
        """组合曲线为空时返回空。"""
        from zfundpilot.api import get_portfolio_benchmark

        empty = pd.DataFrame(columns=["date", "total_value", "invested_cost", "total_return"])
        with patch("zfundpilot.api.analysis.build_portfolio_curve",
                   return_value=empty):
            result = get_portfolio_benchmark("CPI")
        assert result == []

    def test_macro_no_data_in_range_skipped(self):
        """区间内无宏观数据（新组合）→ 该代码被跳过，返回空。"""
        from zfundpilot.api import get_portfolio_benchmark

        with (
            patch("zfundpilot.api.analysis.build_portfolio_curve",
                  return_value=self._curve()),
            patch("zfundpilot.api.fetch_macro.fetch_macro_baseline",
                  return_value=None),
        ):
            result = get_portfolio_benchmark("CPI")
        assert result == []

    def test_macro_baseline_used_as_reference(self):
        """水位线以基期（建仓前最后月末）为基准，建仓日为 0。"""
        from zfundpilot.api import get_portfolio_benchmark

        # 建仓日 2024-03-15，基期应为 2024-02-29（≤ 建仓日的最后月末）
        baseline_res = ([
            {"date": "2024-01-31", "close": 100.0},
            {"date": "2024-02-29", "close": 100.5},   # 基期
            {"date": "2024-03-31", "close": 101.5},
        ], 100.5)  # fetch_macro_baseline 应选 2024-02-29 作基期

        with (
            patch("zfundpilot.api.analysis.build_portfolio_curve",
                  return_value=pd.DataFrame({
                      "date": ["2024-03-15", "2024-03-31"],
                      "total_value": [100000.0, 101000.0],
                      "invested_cost": [100000.0, 100000.0],
                      "total_return": [0.0, 0.01],
                  })),
            patch("zfundpilot.api.fetch_macro.fetch_macro_baseline",
                  return_value=baseline_res),
        ):
            result = get_portfolio_benchmark("CPI")

        # 建仓日 2024-03-15：基期=100.5，3-15 无月末 → ffill 0
        assert result[0]["CPI"] == 0.0
        # 2024-03-31：101.5/100.5 - 1 ≈ 0.995%
        assert result[1]["CPI"] == round(101.5 / 100.5 - 1, 6)
