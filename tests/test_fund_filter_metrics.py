"""基金筛选指标增强的有界执行测试：快照不改入参、并发额度满时快速拒绝。"""

from __future__ import annotations

import threading

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
