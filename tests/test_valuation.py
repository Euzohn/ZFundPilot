"""指数估值（valuation）测试：百分位/窗口/温度、缓存降级、provider、HTTP 端点。"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db, valuation
from zfundpilot.valuation import IndexMeta


# ---------------------------------------------------------------------------
# 测试数据 / 假数据源
# ---------------------------------------------------------------------------
def make_series(months: int, start_year: int = 2012) -> list[dict]:
    """构造震荡的月度 PE/PB 序列（month 末用 28 日即可，仅需可解析且升序）。"""
    points: list[dict] = []
    year, month = start_year, 1
    for index in range(months):
        points.append(
            {
                "date": f"{year}-{month:02d}-28",
                "pe": round(12 + 4 * math.sin(index / 7), 2),
                "pb": round(1.5 + 0.5 * math.sin(index / 9 + 1), 3),
            }
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return points


class FakeProvider(valuation.ValuationProvider):
    name = "fake"

    def __init__(self, points: list[dict] | None = None, fail: bool = False):
        self.points = points if points is not None else make_series(150)
        self.fail = fail
        self.calls: list[str] = []

    def fetch_history(self, meta: IndexMeta) -> list[dict] | None:
        self.calls.append(meta.code)
        if self.fail:
            return None
        return self.points


@pytest.fixture(autouse=True)
def _fast_legulegu(monkeypatch):
    """测试不等待真实请求间隔/退避，且失败状态不跨用例残留。"""
    monkeypatch.setattr(valuation, "_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(valuation, "_RETRY_BACKOFF", (0.0, 0.0))
    valuation._last_errors.clear()
    valuation._last_failed_at.clear()
    valuation._breaker_until = 0.0
    valuation._consecutive_failures = 0


class SlowProvider(valuation.ValuationProvider):
    """慢速 provider：记录并发度，用于验证串行与后台续跑。"""

    name = "slow"

    def __init__(self, delay: float = 0.05, fail: bool = False):
        self.delay = delay
        self.fail = fail
        self.points = make_series(150)
        self.calls: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def fetch_history(self, meta: IndexMeta) -> list[dict] | None:
        with self._lock:
            self.calls.append(meta.code)
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            time.sleep(self.delay)
            return None if self.fail else self.points
        finally:
            with self._lock:
                self.concurrent -= 1


def wait_idle(timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not valuation.is_refreshing():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    return TestClient(api.app)


# ---------------------------------------------------------------------------
# 百分位 / 温度 / 窗口
# ---------------------------------------------------------------------------
class TestPercentile:
    def test_middle(self):
        assert valuation.percentile([1.0, 2.0, 3.0], 2.0) == 33.3

    def test_min_and_max(self):
        assert valuation.percentile([1.0, 2.0, 3.0], 1.0) == 0.0
        assert valuation.percentile([1.0, 2.0, 3.0], 4.0) == 100.0

    def test_ties_are_not_less(self):
        assert valuation.percentile([2.0, 2.0, 3.0], 2.0) == 0.0

    def test_missing(self):
        assert valuation.percentile([], 1.0) is None
        assert valuation.percentile([1.0], None) is None


class TestClassifyTemperature:
    @pytest.mark.parametrize(
        "pct,want",
        [
            (0.0, "low"),
            (29.9, "low"),
            (30.0, "fair"),
            (50.0, "fair"),
            (70.0, "fair"),
            (70.1, "high"),
            (100.0, "high"),
            (None, "unknown"),
        ],
    )
    def test_thresholds(self, pct, want):
        assert valuation.classify_temperature(pct) == want


class TestSelectWindow:
    def test_short_history_uses_all(self):
        points = make_series(60)  # 5 年
        window, selected = valuation.select_window(points, years=10)
        assert window == "all"
        assert selected == points

    def test_long_history_truncates(self):
        points = make_series(180)  # 15 年
        window, selected = valuation.select_window(points, years=10)
        assert window == "10y"
        assert 115 <= len(selected) <= 125
        # 窗口首点距末点不超过 10 年
        first = datetime.strptime(selected[0]["date"], "%Y-%m-%d")
        last = datetime.strptime(selected[-1]["date"], "%Y-%m-%d")
        assert last - first <= timedelta(days=365.25 * 10)

    def test_empty(self):
        assert valuation.select_window([]) == ("all", [])


class TestRollingPercentiles:
    def test_all_history_expanding(self):
        points = [
            {"date": "2020-01-31", "pe": 1.0},
            {"date": "2020-02-29", "pe": 2.0},
            {"date": "2020-03-31", "pe": 3.0},
        ]
        assert valuation.rolling_percentiles(points, "pe", years=None) == [
            0.0,
            50.0,
            66.7,
        ]

    def test_date_window_excludes_old_points(self):
        points = [
            {"date": "2000-01-31", "pe": 100.0},
            {"date": "2019-01-31", "pe": 10.0},
            {"date": "2020-01-31", "pe": 20.0},
            {"date": "2021-01-31", "pe": 15.0},
        ]
        ten_year = valuation.rolling_percentiles(points, "pe", years=10)
        all_history = valuation.rolling_percentiles(points, "pe", years=None)
        assert ten_year[-1] == 33.3  # [10, 20, 15]
        assert all_history[-1] == 25.0  # [100, 10, 20, 15] 中只有 10 更小

    def test_none_values(self):
        points = [
            {"date": "2020-01-31", "pe": None},
            {"date": "2020-02-29", "pe": 2.0},
        ]
        assert valuation.rolling_percentiles(points, "pe", years=None) == [None, 0.0]


class TestHistoryPoints:
    def test_none_value_kept_in_output(self):
        points = [
            {"date": "2020-01-31", "pe": None, "pb": 1.0},
            {"date": "2020-02-29", "pe": 2.0, "pb": 2.0},
        ]
        out = valuation.history_points(points, "all")
        assert out[0]["pe"] is None and out[0]["pe_percentile"] is None
        assert out[1]["pe_percentile"] == 0.0

    def test_window_changes_result(self):
        points = [
            {"date": "2000-01-31", "pe": 100.0},
            {"date": "2019-01-31", "pe": 10.0},
            {"date": "2020-01-31", "pe": 20.0},
            {"date": "2021-01-31", "pe": 15.0},
        ]
        assert valuation.history_points(points, "10y")[-1]["pe_percentile"] == 33.3
        assert valuation.history_points(points, "all")[-1]["pe_percentile"] == 25.0

    def test_empty(self):
        assert valuation.history_points([], "10y") == []


# ---------------------------------------------------------------------------
# build_valuation
# ---------------------------------------------------------------------------
class TestBuildValuation:
    def test_long_history(self):
        meta = valuation.INDEX_BY_CODE["000300"]
        val = valuation.build_valuation(meta, make_series(150))
        assert val.ok
        assert val.index_code == "000300"
        assert val.window == "10y"
        assert val.history_months == 150
        assert 115 <= val.window_months <= 125
        assert val.pe is not None and val.pb is not None
        assert val.temperature in ("low", "fair", "high")
        assert val.data_date == "2024-06-28"  # 2012-01 起 150 个月
        assert val.updated_at

    def test_short_history_all_window(self):
        meta = valuation.INDEX_BY_CODE["000905"]
        val = valuation.build_valuation(meta, make_series(60))
        assert val.window == "all"
        assert val.window_months == 60

    def test_window_override_all(self):
        meta = valuation.INDEX_BY_CODE["000300"]
        val = valuation.build_valuation(meta, make_series(150), window_override="all")
        assert val.window == "all"
        assert val.window_months == 150

    def test_empty_is_degraded(self):
        meta = valuation.INDEX_BY_CODE["000300"]
        val = valuation.build_valuation(meta, [])
        assert val.ok is False
        assert val.temperature == "unknown"


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
class TestMergeSeries:
    def test_forward_fill_mismatched_dates(self):
        pe_df = pd.DataFrame(
            {"日期": ["2024-01-31", "2024-03-31"], "滚动市盈率": [12.0, 13.0]}
        )
        pb_df = pd.DataFrame(
            {"日期": ["2024-02-29", "2024-03-31"], "市净率": [1.2, 1.3]}
        )
        points = valuation.merge_series(pe_df, pb_df)
        assert [p["date"] for p in points] == [
            "2024-01-31",
            "2024-02-29",
            "2024-03-31",
        ]
        assert points[0] == {"date": "2024-01-31", "pe": 12.0, "pb": None}
        assert points[1] == {"date": "2024-02-29", "pe": 12.0, "pb": 1.2}
        assert points[2] == {"date": "2024-03-31", "pe": 13.0, "pb": 1.3}

    def test_empty(self):
        assert valuation.merge_series(pd.DataFrame(), pd.DataFrame()) == []


class TestLeguleguProvider:
    def test_success(self, monkeypatch):
        import akshare

        pe_df = pd.DataFrame(
            {"日期": ["2024-01-31"], "滚动市盈率": [12.0]}
        )
        pb_df = pd.DataFrame({"日期": ["2024-01-31"], "市净率": [1.2]})
        monkeypatch.setattr(akshare, "stock_index_pe_lg", lambda symbol: pe_df)
        monkeypatch.setattr(akshare, "stock_index_pb_lg", lambda symbol: pb_df)
        points = valuation.LeguleguValuationProvider().fetch_history(
            valuation.INDEX_BY_CODE["000300"]
        )
        assert points == [{"date": "2024-01-31", "pe": 12.0, "pb": 1.2}]

    def test_failure_returns_none(self, monkeypatch):
        import akshare

        def boom(symbol):
            raise RuntimeError("csrf failed")

        monkeypatch.setattr(akshare, "stock_index_pe_lg", boom)
        monkeypatch.setattr(akshare, "stock_index_pb_lg", boom)
        assert (
            valuation.LeguleguValuationProvider().fetch_history(
                valuation.INDEX_BY_CODE["000300"]
            )
            is None
        )


# ---------------------------------------------------------------------------
# 韭圈儿 Provider / 回退链
# ---------------------------------------------------------------------------
class TestJqSymbol:
    def test_shanghai_codes(self):
        assert valuation._jq_symbol("000300") == "000300.SH"
        assert valuation._jq_symbol("000905") == "000905.SH"
        assert valuation._jq_symbol("000015") == "000015.SH"

    def test_shenzhen_codes(self):
        assert valuation._jq_symbol("399330") == "399330.SZ"
        assert valuation._jq_symbol("399673") == "399673.SZ"


class TestParseJqPoints:
    def test_basic_parse_sorted(self):
        data = [
            ["日期", "收盘价", "pe", "pb", "roe"],
            ["2024-01-03", "4000.0", "13.5", "1.33", "0.10"],
            ["2024-01-02", "3990.0", "13.4", "1.32", "0.10"],
        ]
        points = valuation._parse_jq_points(data)
        assert [p["date"] for p in points] == ["2024-01-02", "2024-01-03"]
        assert points[0]["pe"] == 13.4 and points[0]["pb"] == 1.32

    def test_zero_values_treated_as_missing(self):
        data = [
            ["日期", "收盘价", "pe", "pb", "roe"],
            ["2024-01-02", "0", "0", "0", "0"],
            ["2024-01-03", "4000", "13.5", "1.33", "0.1"],
        ]
        points = valuation._parse_jq_points(data)
        assert points[0]["pe"] is None and points[0]["pb"] is None
        assert points[1]["pe"] == 13.5

    def test_malformed_rows_skipped(self):
        data = [
            ["日期", "收盘价", "pe", "pb", "roe"],
            ["bad-date", "0", "0", "0", "0"],
            ["2024-01-03"],
            ["2024-01-04", "4000", "abc", "1.33", "0.1"],
        ]
        points = valuation._parse_jq_points(data)
        assert len(points) == 1
        assert points[0]["date"] == "2024-01-04"
        assert points[0]["pe"] is None

    def test_empty_or_bad_shape(self):
        assert valuation._parse_jq_points(None) == []
        assert valuation._parse_jq_points([]) == []
        assert valuation._parse_jq_points([["日期"]]) == []
        assert valuation._parse_jq_points([["foo", "bar"], ["1", "2"]]) == []


class _FakeJqResponse:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._payload


class TestJiucaishuoProvider:
    def _payload(self):
        return {
            "code": 0,
            "message": "ok",
            "data": [
                ["日期", "收盘价", "pe", "pb", "roe"],
                ["2024-01-02", "3990.0", "13.4", "1.32", "0.10"],
                ["2024-01-03", "4000.0", "13.5", "1.33", "0.10"],
            ],
        }

    def test_success(self, monkeypatch):
        import requests

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return _FakeJqResponse(self._payload())

        monkeypatch.setattr(requests, "post", fake_post)
        points = valuation.JiucaishuoValuationProvider().fetch_history(
            valuation.INDEX_BY_CODE["000300"]
        )
        assert points is not None and len(points) == 2
        assert points[-1]["pe"] == 13.5
        assert captured["json"]["code"] == "000300.SH"
        assert captured["json"]["start_time"] == valuation._JQ_START
        assert captured["timeout"] == valuation._JQ_TIMEOUT
        assert not valuation._last_errors

    def test_upstream_error_code_fails(self, monkeypatch):
        import requests

        monkeypatch.setattr(
            requests, "post", lambda url, **kw: _FakeJqResponse({"code": 1, "message": "bad"})
        )
        points = valuation.JiucaishuoValuationProvider().fetch_history(
            valuation.INDEX_BY_CODE["000300"]
        )
        assert points is None
        assert "000300" in valuation._last_errors

    def test_http_error_fails(self, monkeypatch):
        import requests

        monkeypatch.setattr(
            requests, "post", lambda url, **kw: _FakeJqResponse({}, status=503)
        )
        points = valuation.JiucaishuoValuationProvider().fetch_history(
            valuation.INDEX_BY_CODE["000300"]
        )
        assert points is None
        assert "韭圈儿" in valuation._last_errors["000300"]

    def test_empty_data_fails(self, monkeypatch):
        import requests

        monkeypatch.setattr(
            requests,
            "post",
            lambda url, **kw: _FakeJqResponse(
                {"code": 0, "data": [["日期", "收盘价", "pe", "pb", "roe"]]}
            ),
        )
        assert (
            valuation.JiucaishuoValuationProvider().fetch_history(
                valuation.INDEX_BY_CODE["000300"]
            )
            is None
        )


class TestFallbackProvider:
    class _Stub(valuation.ValuationProvider):
        def __init__(self, name: str, points):
            self.name = name
            self._points = points
            self.calls = 0

        def fetch_history(self, meta):
            self.calls += 1
            return self._points

    def test_primary_success_skips_secondary(self):
        primary = self._Stub("primary", [{"date": "2024-01-02", "pe": 13.0, "pb": 1.3}])
        secondary = self._Stub("secondary", [{"date": "2024-01-02", "pe": 1.0, "pb": 1.0}])
        fb = valuation.FallbackValuationProvider(primary, secondary)
        points = fb.fetch_history(valuation.INDEX_BY_CODE["000300"])
        assert points == [{"date": "2024-01-02", "pe": 13.0, "pb": 1.3}]
        assert fb.name == "primary"
        assert secondary.calls == 0

    def test_primary_fail_uses_secondary(self):
        primary = self._Stub("primary", None)
        secondary = self._Stub("legulegu", [{"date": "2024-01-02", "pe": 12.0, "pb": 1.2}])
        fb = valuation.FallbackValuationProvider(primary, secondary)
        points = fb.fetch_history(valuation.INDEX_BY_CODE["000300"])
        assert points is not None
        assert fb.name == "legulegu"
        assert primary.calls == 1 and secondary.calls == 1

    def test_both_fail(self):
        primary = self._Stub("primary", None)
        secondary = self._Stub("secondary", None)
        fb = valuation.FallbackValuationProvider(primary, secondary)
        assert fb.fetch_history(valuation.INDEX_BY_CODE["000300"]) is None
        assert fb.name == "primary"


class TestSpanMonths:
    def test_monthly_series(self):
        points = [{"date": f"{y}-{m:02d}-28"} for y, m in [(2012, 1), (2024, 6)]]
        assert valuation._span_months(points) == 150

    def test_daily_series_counts_months(self):
        points = [{"date": "2016-01-04"}, {"date": "2016-12-30"}]
        assert valuation._span_months(points) == 12

    def test_empty(self):
        assert valuation._span_months([]) == 0


# ---------------------------------------------------------------------------
# 缓存 / 刷新 / 降级
# ---------------------------------------------------------------------------
class TestListValuations:
    def test_empty_cache_fetches_all(self, temp_db, monkeypatch):
        fake = FakeProvider()
        monkeypatch.setattr(valuation, "get_provider", lambda: fake)
        values = valuation.list_valuations()
        assert len(values) == 12
        assert all(v.ok and not v.stale for v in values)
        assert len(fake.calls) == 12
        assert len(db.get_index_valuations()) == 12

    def test_fresh_cache_skips_fetch(self, temp_db):
        valuation.list_valuations(provider=FakeProvider())
        boom = FakeProvider(fail=True)
        values = valuation.list_valuations(provider=boom)
        assert boom.calls == []
        assert all(v.ok and not v.stale for v in values)

    def test_stale_cache_falls_back(self, temp_db):
        valuation.list_valuations(provider=FakeProvider())
        boom = FakeProvider(fail=True)
        values = valuation.list_valuations(provider=boom, ttl_hours=-1)
        assert len(boom.calls) == 12
        assert all(v.ok and v.stale for v in values)
        assert all(v.pe is not None for v in values)

    def test_no_cache_failure_degrades(self, temp_db):
        values = valuation.list_valuations(provider=FakeProvider(fail=True))
        assert all(not v.ok for v in values)
        assert all(v.temperature == "unknown" for v in values)
        assert all(v.message for v in values)

    def test_refresh_forces_fetch(self, temp_db):
        valuation.list_valuations(provider=FakeProvider())
        fake = FakeProvider()
        valuation.list_valuations(refresh=True, provider=fake)
        assert len(fake.calls) == 12

    def test_registry_order_preserved(self, temp_db):
        values = valuation.list_valuations(provider=FakeProvider())
        assert [v.index_code for v in values] == [
            m.code for m in valuation.INDEX_REGISTRY
        ]


class TestSerializedFetch:
    """乐咕调用必须串行（V8 非线程安全），且超时后后台继续抓取落库。"""

    def test_calls_never_overlap(self, temp_db):
        provider = SlowProvider(delay=0.01)
        valuation.list_valuations(provider=provider)
        assert provider.max_concurrent == 1
        assert len(provider.calls) == 12

    def test_background_continues_after_timeout(self, temp_db):
        provider = SlowProvider(delay=0.15)
        values = valuation.list_valuations(provider=provider, timeout=0.05)
        assert any(not v.ok for v in values)  # 有界等待先返回部分结果
        assert valuation.is_refreshing() is True
        assert wait_idle()  # 后台任务继续完成
        assert len(db.get_index_valuations()) == 12
        again = valuation.list_valuations(provider=provider)
        assert all(v.ok and not v.stale for v in again)

    def test_single_flight_dedup(self, temp_db):
        provider = SlowProvider(delay=0.1)
        valuation.list_valuations(provider=provider, timeout=0.01)
        valuation.list_valuations(provider=provider, timeout=0.01)
        assert wait_idle()
        assert sorted(provider.calls) == sorted(
            meta.code for meta in valuation.INDEX_REGISTRY
        )

    def test_background_failure_keeps_placeholder(self, temp_db):
        provider = SlowProvider(delay=0.01, fail=True)
        values = valuation.list_valuations(provider=provider, timeout=5.0)
        assert all(not v.ok for v in values)
        assert wait_idle()
        assert db.get_index_valuations() == []


class TestLgCallRetry:
    def test_retries_then_succeeds(self):
        calls: list[str] = []

        def flaky(symbol):
            calls.append(symbol)
            if len(calls) < 3:
                raise RuntimeError("429")
            return "ok"

        assert valuation._lg_call(flaky, "沪深300") == "ok"
        assert len(calls) == 3

    def test_gives_up_after_max_attempts(self):
        calls: list[str] = []

        def boom(symbol):
            calls.append(symbol)
            raise RuntimeError("429")

        with pytest.raises(RuntimeError):
            valuation._lg_call(boom, "沪深300")
        assert len(calls) == 3


class TestRequestsTimeout:
    """旧版 akshare 乐咕请求不带 timeout：必须注入默认超时，防止串行队列永远挂起。"""

    def test_default_timeout_injected(self, monkeypatch):
        import requests
        from requests.adapters import HTTPAdapter

        valuation._ensure_requests_timeout()
        captured: dict = {}

        def fake_send(self, request, **kwargs):
            captured.update(kwargs)
            raise requests.exceptions.ConnectionError("stop")

        monkeypatch.setattr(HTTPAdapter, "send", fake_send)
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get("https://example.invalid")
        assert captured["timeout"] == valuation._HTTP_TIMEOUT

    def test_explicit_timeout_preserved(self, monkeypatch):
        import requests
        from requests.adapters import HTTPAdapter

        valuation._ensure_requests_timeout()
        captured: dict = {}

        def fake_send(self, request, **kwargs):
            captured.update(kwargs)
            raise requests.exceptions.ConnectionError("stop")

        monkeypatch.setattr(HTTPAdapter, "send", fake_send)
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get("https://example.invalid", timeout=5)
        assert captured["timeout"] == 5


class TestFailureMessage:
    """降级占位必须带上失败原因，便于在服务器侧定位网络/反爬问题。"""

    def test_placeholder_carries_error(self, temp_db):
        class BoomProvider(valuation.ValuationProvider):
            name = "boom"

            def fetch_history(self, meta):
                raise RuntimeError("connect timeout")

        values = valuation.list_valuations(provider=BoomProvider(), timeout=5.0)
        assert all(not v.ok for v in values)
        assert all("connect timeout" in v.message for v in values)
        # 成功后清除失败原因（手动刷新绕过失败冷却）
        again = valuation.list_valuations(provider=FakeProvider(), refresh=True)
        assert all(v.ok for v in again)
        assert not valuation._last_errors

    def test_legulegu_failure_recorded(self, temp_db, monkeypatch):
        import akshare

        def boom(symbol):
            raise RuntimeError("504 Gateway Time-out")

        monkeypatch.setattr(akshare, "stock_index_pe_lg", boom)
        # 显式指定乐咕源：默认源已切换为韭圈儿（主）+ 乐咕（备），
        # 本用例只验证乐咕失败原因的记录与透出。
        values = valuation.list_valuations(
            provider=valuation.LeguleguValuationProvider(), timeout=5.0
        )
        assert all(not v.ok for v in values)
        assert all("504" in v.message for v in values)


class TestFailureCooldown:
    """失败后冷却期内不自动重提：否则上游不可达时队列永远不空，页面永远「刷新中」。"""

    def test_failed_codes_not_resubmitted(self, temp_db):
        boom = FakeProvider(fail=True)
        values = valuation.list_valuations(provider=boom, timeout=5.0)
        assert all(not v.ok for v in values)
        assert len(boom.calls) == 12
        assert valuation.is_refreshing() is False
        # 冷却期内的后续请求（含前端轮询）不再重提
        again = valuation.list_valuations(provider=boom, timeout=5.0)
        assert all(not v.ok for v in again)
        assert len(boom.calls) == 12
        assert valuation.is_refreshing() is False

    def test_force_refresh_bypasses_cooldown(self, temp_db):
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        assert len(boom.calls) == 12
        valuation.list_valuations(provider=boom, refresh=True, timeout=5.0)
        assert len(boom.calls) == 24

    def test_cooldown_expiry_allows_retry(self, temp_db, monkeypatch):
        # 本用例只验证单只冷却语义，关掉全站熔断避免干扰
        monkeypatch.setattr(valuation, "_BREAKER_THRESHOLD", 10_000)
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        monkeypatch.setattr(valuation, "_FAILURE_COOLDOWN", 0.0)
        valuation.list_valuations(provider=boom, timeout=5.0)
        assert len(boom.calls) == 24

    def test_success_after_cooldown_via_history(self, temp_db):
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        # 展开单只历史是显式动作，不受冷却限制
        result = valuation.get_history("000300", provider=FakeProvider())
        assert result is not None and result["ok"]
        assert "000300" not in valuation._last_failed_at


class TestCircuitBreaker:
    """全站不可用（如上游 WAF 封禁服务器 IP、整站 504）时连续失败触发全局熔断。

    仅靠单只 5 分钟冷却，整站失败时每 5 分钟仍会重提一整轮请求，
    可能让上游频控封禁一直续期。熔断后自动请求静默 1 小时，
    手动刷新/展开历史可穿透，任一成功立即合闸。
    """

    def test_trips_after_consecutive_failures(self, temp_db, monkeypatch):
        monkeypatch.setattr(valuation, "_BREAKER_THRESHOLD", 3)
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        # 本批已排队的任务仍会执行完（熔断在提交时检查）
        assert len(boom.calls) == 12
        assert valuation._breaker_until > time.monotonic()
        # 熔断期内的自动请求（含前端轮询）不再触碰上游
        again = valuation.list_valuations(provider=boom, timeout=5.0)
        assert len(boom.calls) == 12
        assert all(not v.ok for v in again)
        assert valuation.is_refreshing() is False

    def test_force_refresh_bypasses_breaker(self, temp_db, monkeypatch):
        monkeypatch.setattr(valuation, "_BREAKER_THRESHOLD", 3)
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        assert valuation._breaker_until > 0
        valuation.list_valuations(provider=boom, refresh=True, timeout=5.0)
        assert len(boom.calls) == 24

    def test_history_bypasses_and_success_closes_breaker(self, temp_db, monkeypatch):
        monkeypatch.setattr(valuation, "_BREAKER_THRESHOLD", 3)
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        assert valuation._breaker_until > 0
        # 展开单只历史是显式动作，可穿透熔断；成功立即合闸
        result = valuation.get_history("000300", provider=FakeProvider())
        assert result is not None and result["ok"]
        assert valuation._breaker_until == 0.0
        assert valuation._consecutive_failures == 0

    def test_breaker_expiry_allows_retry(self, temp_db, monkeypatch):
        monkeypatch.setattr(valuation, "_BREAKER_THRESHOLD", 3)
        boom = FakeProvider(fail=True)
        valuation.list_valuations(provider=boom, timeout=5.0)
        assert len(boom.calls) == 12
        # 模拟熔断与单只冷却同时到期
        monkeypatch.setattr(valuation, "_breaker_until", 0.0)
        monkeypatch.setattr(valuation, "_FAILURE_COOLDOWN", 0.0)
        valuation.list_valuations(provider=boom, timeout=5.0)
        assert len(boom.calls) == 24

    def test_partial_failures_do_not_trip(self, temp_db, monkeypatch):
        monkeypatch.setattr(valuation, "_BREAKER_THRESHOLD", 3)

        class FlakyProvider(valuation.ValuationProvider):
            name = "flaky"

            def __init__(self):
                self.calls: list[str] = []

            def fetch_history(self, meta):
                self.calls.append(meta.code)
                # 每 3 只失败 1 只：失败不连续累计到阈值（成功会清零）
                if len(self.calls) % 3 == 0:
                    return None
                return make_series(150)

        valuation.list_valuations(provider=FlakyProvider(), timeout=5.0)
        assert valuation._breaker_until == 0.0
        assert valuation._consecutive_failures < 3


class TestRefreshProgress:
    """刷新进度快照必须反映「当前正在做什么」（前端横幅展示）。"""

    def test_current_code_tracked_serially(self, temp_db):
        seen: list[str | None] = []

        class SpyProvider(valuation.ValuationProvider):
            name = "spy"

            def fetch_history(self, meta):
                seen.append(valuation._current_code)
                return make_series(150)

        valuation.list_valuations(provider=SpyProvider())
        assert seen == [meta.code for meta in valuation.INDEX_REGISTRY]
        assert valuation._current_code is None
        assert valuation.refresh_progress() == {
            "total": 12,
            "remaining": 0,
            "current": None,
            "current_code": None,
            "failed": 0,
        }

    def test_progress_during_background(self, temp_db):
        provider = SlowProvider(delay=0.15)
        valuation.list_valuations(provider=provider, timeout=0.05)
        progress = valuation.refresh_progress()
        assert progress["total"] == 12
        assert progress["remaining"] > 0
        names = {meta.name for meta in valuation.INDEX_REGISTRY}
        assert progress["current"] is None or progress["current"] in names
        assert wait_idle()
        progress = valuation.refresh_progress()
        assert progress["remaining"] == 0
        assert progress["current"] is None

    def test_failed_count(self, temp_db):
        valuation.list_valuations(provider=FakeProvider(fail=True), timeout=5.0)
        progress = valuation.refresh_progress()
        assert progress["failed"] == 12
        assert progress["remaining"] == 0


class TestGetHistory:
    def test_cached_history_and_consistency(self, temp_db):
        valuation.list_valuations(provider=FakeProvider())
        current = valuation.list_valuations()[0]
        result = valuation.get_history("000300")
        assert result is not None and result["ok"]
        assert result["points"]
        # 历史曲线最后一点的滚动百分位必须与列表当前百分位一致
        assert result["points"][-1]["pe_percentile"] == current.pe_percentile

    def test_window_override(self, temp_db):
        points = [
            {"date": "2000-01-31", "pe": 100.0, "pb": 3.0},
            {"date": "2019-01-31", "pe": 10.0, "pb": 1.0},
            {"date": "2020-01-31", "pe": 20.0, "pb": 2.0},
            {"date": "2021-01-31", "pe": 15.0, "pb": 1.5},
        ]
        valuation.list_valuations(provider=FakeProvider(points=points))
        ten_year = valuation.get_history("000300")
        all_history = valuation.get_history("000300", window="all")
        assert ten_year["points"][-1]["pe_percentile"] == 33.3
        assert all_history["points"][-1]["pe_percentile"] == 25.0

    def test_unknown_code(self, temp_db):
        assert valuation.get_history("999999") is None

    def test_no_cache_failure_degrades(self, temp_db):
        result = valuation.get_history("000300", provider=FakeProvider(fail=True))
        assert result is not None
        assert result["ok"] is False
        assert result["points"] == []
        assert result["index"]["ok"] is False

    def test_no_cache_success_stores(self, temp_db):
        result = valuation.get_history("000300", provider=FakeProvider())
        assert result["ok"] is True
        assert db.get_index_valuation("000300") is not None


class TestTrackingFunds:
    def test_keyword_match_and_collision_exclusion(self, monkeypatch):
        from zfundpilot import fund_filter

        universe = [
            {"code": "000001", "name": "华夏中证100指数A", "type": "指数型", "sector": "其它"},
            {"code": "000002", "name": "华夏中证1000指数A", "type": "指数型", "sector": "其它"},
            {"code": "000003", "name": "易方达沪深300ETF联接A", "type": "指数型", "sector": "沪深300"},
            {"code": "000004", "name": "易方达蓝筹精选混合", "type": "混合型", "sector": "其它"},
        ]
        monkeypatch.setattr(fund_filter, "load_fund_universe", lambda: universe)

        mid = valuation.tracking_funds(valuation.INDEX_BY_CODE["000903"])
        assert [f["code"] for f in mid] == ["000001"]

        broad = valuation.tracking_funds(valuation.INDEX_BY_CODE["000300"])
        assert [f["code"] for f in broad] == ["000003"]
        assert broad[0]["index_tag"] == "broad"

    def test_limit(self, monkeypatch):
        from zfundpilot import fund_filter

        universe = [
            {"code": f"{i:06d}", "name": f"沪深300ETF联接{i}", "type": "指数型", "sector": ""}
            for i in range(30)
        ]
        monkeypatch.setattr(fund_filter, "load_fund_universe", lambda: universe)
        assert len(valuation.tracking_funds(valuation.INDEX_BY_CODE["000300"], limit=20)) == 20

    def test_universe_failure_returns_empty(self, monkeypatch):
        from zfundpilot import fund_filter

        def boom():
            raise RuntimeError("universe down")

        monkeypatch.setattr(fund_filter, "load_fund_universe", boom)
        assert valuation.tracking_funds(valuation.INDEX_BY_CODE["000300"]) == []


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------
class TestValuationEndpoints:
    def test_list_ok(self, client, monkeypatch):
        monkeypatch.setattr(valuation, "get_provider", lambda: FakeProvider())
        response = client.get("/api/valuation/indices")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert len(body["indices"]) == 12
        assert body["degraded"] is False
        assert body["refreshing"] is False
        assert body["progress"] == {
            "total": 12,
            "remaining": 0,
            "current": None,
            "current_code": None,
            "failed": 0,
        }
        assert body["as_of"]
        item = body["indices"][0]
        assert item["index_code"] == "000300"
        assert item["window"] in ("10y", "all")
        assert item["temperature"] in ("low", "fair", "high")
        assert item["stale"] is False

    def test_list_degraded(self, client, monkeypatch):
        monkeypatch.setattr(valuation, "get_provider", lambda: FakeProvider(fail=True))
        body = client.get("/api/valuation/indices").json()
        assert body["ok"] is True  # 请求本身成功
        assert body["degraded"] is True
        assert all(item["ok"] is False for item in body["indices"])
        assert body["progress"]["failed"] == 12

    def test_list_refresh_param(self, client, monkeypatch):
        monkeypatch.setattr(valuation, "get_provider", lambda: FakeProvider())
        assert client.get("/api/valuation/indices").status_code == 200
        assert client.get("/api/valuation/indices?refresh=1").status_code == 200

    def test_history_ok(self, client, monkeypatch):
        monkeypatch.setattr(valuation, "get_provider", lambda: FakeProvider())
        response = client.get("/api/valuation/indices/000300/history")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["index"]["index_code"] == "000300"
        assert body["points"]
        assert {"date", "pe", "pb", "pe_percentile", "pb_percentile"} <= set(
            body["points"][0]
        )

    def test_history_window_param(self, client, monkeypatch):
        monkeypatch.setattr(valuation, "get_provider", lambda: FakeProvider())
        assert (
            client.get("/api/valuation/indices/000300/history?window=all").status_code
            == 200
        )

    def test_history_unknown_404(self, client):
        assert client.get("/api/valuation/indices/999999/history").status_code == 404

    def test_funds_ok(self, client, monkeypatch):
        monkeypatch.setattr(
            valuation,
            "tracking_funds",
            lambda meta, limit=20: [
                {
                    "code": "000001",
                    "name": meta.keyword + "ETF联接A",
                    "type": "指数型",
                    "sector": "",
                    "index_tag": "broad",
                }
            ][:limit],
        )
        response = client.get("/api/valuation/indices/000300/funds?limit=5")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["funds"][0]["code"] == "000001"

    def test_funds_unknown_404(self, client):
        assert client.get("/api/valuation/indices/999999/funds").status_code == 404

    def test_requires_auth_when_enabled(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
        assert TestClient(api.app).get("/api/valuation/indices").status_code == 401
