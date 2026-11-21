"""基金筛选指标增强的有界执行测试：快照不改入参、并发额度满时快速拒绝。"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from zfundpilot import fund_filter


def _item(code: str = "005827") -> fund_filter.FundFilterItem:
    return fund_filter.FundFilterItem(
        code=code, name="测试基金", type="混合型", sector="科技")


def test_enrich_page_metrics_returns_snapshot_without_mutating_items(monkeypatch):
    items = [_item()]
    snapshot = {
        "scale": 100.0,
        "manager": "经理",
        "inception_date": "2018-01-01",
        "returns": {"1y": 0.1},
        "risk": {"volatility": 0.2},
    }
    monkeypatch.setattr(
        fund_filter, "_enrich_snapshot", lambda item: dict(snapshot))

    snapshots, stats = fund_filter.enrich_page_metrics(items, timeout=5)

    assert snapshots == {"005827": snapshot}
    assert stats.requested is True
    assert stats.attempted == 1
    assert stats.succeeded == 1
    assert stats.failed == 0
    assert stats.timed_out == 0
    assert stats.complete is True
    # 只返回快照，不写回原对象，避免超时后序列化被后台线程改写
    assert items[0].returns is None
    assert items[0].risk is None
    assert items[0].scale is None


def test_enrich_page_metrics_rejects_when_gate_is_full(monkeypatch):
    gate = threading.BoundedSemaphore(1)
    assert gate.acquire(blocking=False)
    monkeypatch.setattr(fund_filter, "_ENRICH_GATE", gate)

    with pytest.raises(fund_filter.EnrichmentBusy):
        fund_filter.enrich_page_metrics([_item()], timeout=1)

    gate.release()


def test_enrich_page_metrics_empty_page_is_complete():
    snapshots, stats = fund_filter.enrich_page_metrics([], timeout=1)

    assert snapshots == {}
    assert stats.attempted == 0
    assert stats.complete is True


def _snapshot(scale: float = 100.0) -> dict:
    return {
        "scale": scale,
        "manager": "经理",
        "inception_date": "2018-01-01",
        "institution_ratio": None,
        "individual_ratio": None,
        "internal_ratio": None,
        "holder_report_date": "",
        "returns": {"1y": 0.1},
        "risk": {"volatility": 0.2},
    }


def test_enrich_with_metrics_applies_completed_snapshots(monkeypatch):
    monkeypatch.setattr(
        fund_filter, "_enrich_snapshot", lambda item: _snapshot())
    items = [_item()]

    fund_filter._enrich_with_metrics(items)

    assert items[0].scale == 100.0
    assert items[0].manager == "经理"
    assert items[0].returns == {"1y": 0.1}
    assert items[0].risk == {"volatility": 0.2}


def test_enrich_with_metrics_failure_clears_returns_and_risk(monkeypatch):
    def boom(item):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(fund_filter, "_enrich_snapshot", boom)
    items = [_item()]

    fund_filter._enrich_with_metrics(items)

    assert items[0].returns == {}
    assert items[0].risk == {}
    assert items[0].scale is None


def test_enrich_with_metrics_timeout_no_post_return_mutation(monkeypatch):
    """超时项不写回；后台线程稍后完成也不得改写已返回的对象。"""
    release = threading.Event()
    started = threading.Event()

    def slow_snapshot(item):
        started.set()
        assert release.wait(5)
        return _snapshot(scale=999.0)

    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(fund_filter, "_EXECUTOR", executor)
    monkeypatch.setattr(fund_filter, "_enrich_snapshot", slow_snapshot)
    monkeypatch.setattr(fund_filter, "_ENRICH_WITH_METRICS_TIMEOUT", 0.05)

    items = [_item()]
    fund_filter._enrich_with_metrics(items)

    assert started.wait(2)
    # 超时项保持原值，未被写回
    assert items[0].scale is None
    assert items[0].returns is None
    assert items[0].risk is None

    release.set()
    executor.shutdown(wait=True)  # 等后台任务真正结束
    # 返回之后对象不再被后台线程改写（快照式，而非 _enrich_one 直写）
    assert items[0].scale is None
    assert items[0].returns is None
    assert items[0].risk is None


def test_enrich_with_metrics_partial_completion_snapshot(monkeypatch):
    """部分完成：只写回已完成项，未完成项保持原值且事后不被改写。"""
    release = threading.Event()

    def snapshot(item):
        if item.code == "000001":
            return _snapshot(scale=1.0)
        assert release.wait(5)
        return _snapshot(scale=999.0)

    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(fund_filter, "_EXECUTOR", executor)
    monkeypatch.setattr(fund_filter, "_enrich_snapshot", snapshot)
    monkeypatch.setattr(fund_filter, "_ENRICH_WITH_METRICS_TIMEOUT", 0.5)

    items = [_item("000001"), _item("000002")]
    fund_filter._enrich_with_metrics(items)

    assert items[0].scale == 1.0
    assert items[1].scale is None

    release.set()
    executor.shutdown(wait=True)
    assert items[0].scale == 1.0
    assert items[1].scale is None
