"""净值抓取原生化安全回归（选基页 mini_racer 并发段错误修复）。

背景：选基指标增强为 6 线程并发，每只未缓存净值的基金都会走
``akshare.fund_open_fund_info_em``——该接口每次调用都创建/销毁一个
mini_racer(V8) 上下文。``ak_compat`` 的类级锁只串行 init/eval/call，未覆盖
销毁（close/__del__），并发「创建 + 销毁」竞态 → ``libmini_racer.so`` 段错误
（服务器 dmesg 实锤：同一指令偏移、近空指针解引用，曾致整站崩溃循环）。

修复：
- 方案一：``fetch_nav_history`` 改纯 Python 的 ``_fetch_via_eastmoney`` 优先
  （与 AkShare 读同一份 pingzhongdata 的 Data_netWorthTrend，不经 V8），
  AkShare 降为兜底 → 选基/定时净值/对比/详情更新四条路径不再触 V8。
- 方案二：``ak_compat.serialized()`` 全生命周期锁，包裹仍用
  ``fund_open_fund_info_em`` 的净值兜底/同类排名/分红检测，连同销毁一起串行。

本文件用例不依赖真实 mini_racer/akshare（全部 stub + 计数锁），可在任意环境跑。
"""

import sys
import threading
import time
from types import ModuleType
from unittest.mock import patch

import pytest

from zfundpilot import ak_compat, fetch_dividend, fetch_fund


class _CountingLock:
    """带并发计数的上下文锁：统计同时持锁的线程数（忽略同线程重入）。

    与 tests/test_ak_compat.py 的同名工具一致：serialized() 内部会嵌套触发
    类级 patch 的同线程重入，简单计数器会误判为并发。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._guard = threading.Lock()
        self._depth = threading.local()
        self.entries = 0
        self.max_entries = 0

    def __enter__(self):
        self._lock.acquire()
        depth = getattr(self._depth, "value", 0)
        with self._guard:
            if depth == 0:
                self.entries += 1
                self.max_entries = max(self.max_entries, self.entries)
        self._depth.value = depth + 1
        return self

    def __exit__(self, *exc_info):
        depth = self._depth.value
        self._depth.value = depth - 1
        with self._guard:
            if depth == 1:
                self.entries -= 1
        self._lock.release()


def _nav_points(source: str) -> list:
    return [fetch_fund.NavPoint(
        fund_code="000001", date="2026-01-01", nav=1.0, source=source)]


# ---------------------------------------------------------------------------
# 方案一：净值抓取纯 Python 优先，热路径不触 V8
# ---------------------------------------------------------------------------

def test_nav_history_prefers_eastmoney_and_skips_akshare(monkeypatch):
    points = _nav_points("eastmoney")
    monkeypatch.setattr(fetch_fund, "_fetch_via_eastmoney", lambda code: points)

    def _no_akshare(code):
        raise AssertionError("eastmoney 成功时不应触发 AkShare/V8 路径")

    monkeypatch.setattr(fetch_fund, "_fetch_via_akshare", _no_akshare)
    assert fetch_fund.fetch_nav_history("000001") == points


def test_nav_history_falls_back_to_akshare(monkeypatch):
    points = _nav_points("akshare")

    def _eastmoney_fail(code):
        raise RuntimeError("eastmoney down")

    monkeypatch.setattr(fetch_fund, "_fetch_via_eastmoney", _eastmoney_fail)
    monkeypatch.setattr(fetch_fund, "_fetch_via_akshare", lambda code: points)
    monkeypatch.setattr(fetch_fund.time, "sleep", lambda s: None)
    assert fetch_fund.fetch_nav_history("000001") == points


def test_concurrent_nav_fetch_never_touches_akshare(monkeypatch):
    """选基指标增强回归：6 线程并发抓净值，绝不能再进 AkShare/V8。

    若有人把数据源顺序调回 AkShare 优先，本用例的 spy 会被并发调用而失败。
    """
    points = _nav_points("eastmoney")
    monkeypatch.setattr(fetch_fund, "_fetch_via_eastmoney", lambda code: points)
    akshare_calls: list[str] = []

    def _spy(code):
        akshare_calls.append(code)
        return points

    monkeypatch.setattr(fetch_fund, "_fetch_via_akshare", _spy)
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(5):
                fetch_fund.fetch_nav_history("000001")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发净值抓取出现异常: {errors}"
    assert akshare_calls == [], (
        "选基并发净值抓取触发了 AkShare/V8，会 libmini_racer.so 段错误；"
        "必须保持纯 Python 的 eastmoney 优先"
    )


# ---------------------------------------------------------------------------
# 方案二：仍用 fund_open_fund_info_em 的调用点，整段调用（含销毁）持锁串行
# ---------------------------------------------------------------------------

def _record_lock_during_akshare(monkeypatch, invoke):
    """stub akshare：在 fund_open_fund_info_em 被调时记录当前持锁线程数后抛错。

    抛错是为了不必构造合法 DataFrame——调用点各自的异常路径会兜住，而锁状态
    已在真实调用发生的那一刻被记录。返回 (每次调用时的持锁数, 计数锁)。
    """
    counting = _CountingLock()
    monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)
    seen: list[int] = []

    def stub(symbol, indicator):
        seen.append(counting.entries)
        raise RuntimeError("stub: 记录锁状态后即止")

    fake = ModuleType("akshare")
    fake.fund_open_fund_info_em = stub
    with patch.dict(sys.modules, {"akshare": fake}):
        invoke()
    return seen, counting


def test_nav_fallback_holds_lock_during_akshare_call(monkeypatch):
    def invoke():
        with pytest.raises(RuntimeError):
            fetch_fund._fetch_via_akshare("000001")

    seen, _ = _record_lock_during_akshare(monkeypatch, invoke)
    assert seen and all(e >= 1 for e in seen), (
        "AkShare 净值兜底调用期间必须持有全生命周期锁（含 V8 上下文销毁）"
    )


def test_ranking_holds_lock_during_akshare_call(monkeypatch):
    fetch_fund._ranking_cache.clear()

    def invoke():
        fetch_fund.fetch_fund_ranking("999999")  # 内部兜住异常

    seen, _ = _record_lock_during_akshare(monkeypatch, invoke)
    assert seen and all(e >= 1 for e in seen), "同类排名调用期间必须持锁"


def test_dividend_holds_lock_during_akshare_call(monkeypatch):
    fetch_dividend._DIV_CACHE.clear()

    def invoke():
        fetch_dividend._fetch_fund_dividends("999999")  # 内部兜住异常

    seen, _ = _record_lock_during_akshare(monkeypatch, invoke)
    assert seen and all(e >= 1 for e in seen), "分红检测调用期间必须持锁"


def test_concurrent_akshare_calls_serialized(monkeypatch):
    """6 线程并发走 fund_open_fund_info_em，整段调用必须串行（max_entries==1）。"""
    counting = _CountingLock()
    monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)

    def stub(symbol, indicator):
        time.sleep(0.002)  # 制造窗口：未串行时必然重叠
        raise RuntimeError("stub")

    fake = ModuleType("akshare")
    fake.fund_open_fund_info_em = stub
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(5):
                try:
                    fetch_fund._fetch_via_akshare("000001")
                except RuntimeError:
                    pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with patch.dict(sys.modules, {"akshare": fake}):
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, f"并发调用出现异常: {errors}"
    assert counting.max_entries == 1, (
        f"同一时刻有 {counting.max_entries} 个线程进入 fund_open_fund_info_em，"
        "整段调用（含 V8 销毁）未串行，线上会 libmini_racer.so 段错误"
    )


def test_serialized_is_reentrant():
    """serialized() 用 RLock，嵌套（类级 patch 会同线程重入）不得死锁。"""
    with ak_compat.serialized():
        with ak_compat.serialized():
            pass
