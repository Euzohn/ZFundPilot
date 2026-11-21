"""V8 全生命周期锁全覆盖回归（残留路径统一，v0.28.1 跟进加固）。

v0.28.1 后净值热路径不再触 V8，净值兜底/同类排名/分红检测已包
``ak_compat.serialized()``。经函数级验证，进程内其余 V8 使用方共三处：

- 乐咕估值兜底 ``valuation._lg_call``（stock_index_pe_lg / stock_index_pb_lg）
- 新浪交易日历 ``fetch_fund.fetch_trade_calendar``（calendar_trade_date_hist_sina）
- 新浪指数日线 ``fetch_estimate._fetch_index_daily_sina``（index_zh_daily_sina，
  OCR 审计补加固：内部创建 MiniRacer，调度器线程与 FastAPI 线程池并发可竞态）

（宏观/重仓/行业/申购状态等接口均为纯 Python JSON，不触 V8。）

三处原有各自的域锁（_V8_LOCK / _trade_cal_lock 等）已把本域内整段调用串行，
但**跨锁域**并发「创建 + 销毁」V8 上下文仍可能竞态——类级锁只盖
init/eval/call，不盖 close/__del__。修复：实际 akshare 调用外嵌套
``serialized()``，全进程 V8 生命周期统一到同一把进程级锁。

本文件用例不依赖真实 mini_racer/akshare（全部 stub + 计数锁）。
"""

import sys
import threading
import time
from types import ModuleType
from unittest.mock import patch

from zfundpilot import ak_compat, fetch_estimate, fetch_fund, valuation


class _CountingLock:
    """带并发计数的上下文锁：统计同时持锁的线程数（忽略同线程重入）。

    与 tests/test_ak_compat.py / test_nav_native_safety.py 的同名工具一致。
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


def test_lg_call_holds_miniracer_lock(monkeypatch):
    """乐咕兜底：实际 akshare 调用期间必须持进程级全生命周期锁。"""
    counting = _CountingLock()
    monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)
    monkeypatch.setattr(valuation, "_REQUEST_INTERVAL", 0)  # 跳过限频等待
    seen: list[int] = []

    def stub(symbol):
        seen.append(counting.entries)
        return object()

    valuation._lg_call(stub, "000300")
    assert seen and all(e >= 1 for e in seen), (
        "乐咕估值调用期间必须持 ak_compat.serialized() 锁（含 V8 上下文销毁）"
    )


def test_trade_calendar_holds_miniracer_lock(monkeypatch):
    """交易日历：实际 akshare 调用期间必须持进程级全生命周期锁。"""
    counting = _CountingLock()
    monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)
    monkeypatch.setattr(fetch_fund, "_trade_cal_cache", set())
    monkeypatch.setattr(fetch_fund, "_trade_cal_cache_ts", 0.0)
    seen: list[int] = []

    def stub():
        seen.append(counting.entries)
        return {"trade_date": ["2026-01-02"]}

    fake = ModuleType("akshare")
    fake.calendar_trade_date_hist_sina = stub
    with patch.dict(sys.modules, {"akshare": fake}):
        fetch_fund.fetch_trade_calendar()
    assert seen and all(e >= 1 for e in seen), (
        "交易日历调用期间必须持 ak_compat.serialized() 锁（含 V8 上下文销毁）"
    )


def test_sina_index_holds_miniracer_lock(monkeypatch):
    """新浪指数日线：实际 akshare 调用期间必须持进程级全生命周期锁。"""
    counting = _CountingLock()
    monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)
    seen: list[int] = []

    def stub(symbol):
        seen.append(counting.entries)
        return object()

    fake = ModuleType("akshare")
    fake.index_zh_daily_sina = stub
    with patch.dict(sys.modules, {"akshare": fake}):
        fetch_estimate._fetch_index_daily_sina("sh000300")
    assert seen and all(e >= 1 for e in seen), (
        "新浪指数日线调用期间必须持 ak_compat.serialized() 锁（含 V8 上下文销毁）"
    )


def test_cross_domain_v8_calls_serialized(monkeypatch):
    """跨锁域回归：乐咕 + 日历 + 新浪指数并发，全进程 V8 生命周期必须串行。

    三处各持不同的域锁；若实际调用未嵌套 serialized()，多域会同时进入
    「创建+销毁」窗口，max_entries > 1。
    """
    counting = _CountingLock()
    monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)
    monkeypatch.setattr(valuation, "_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(fetch_fund, "_trade_cal_cache", set())
    monkeypatch.setattr(fetch_fund, "_trade_cal_cache_ts", 0.0)
    monkeypatch.setattr(fetch_fund, "_TRADE_CAL_CACHE_TTL", 0)  # 每次都真实抓取

    def lg_stub(symbol):
        time.sleep(0.002)  # 制造窗口：未统一锁时必然跨域重叠
        return object()

    def cal_stub():
        time.sleep(0.002)
        return {"trade_date": ["2026-01-02"]}

    def sina_stub(symbol):
        time.sleep(0.002)
        return object()

    fake = ModuleType("akshare")
    fake.calendar_trade_date_hist_sina = cal_stub
    fake.index_zh_daily_sina = sina_stub
    errors: list[Exception] = []

    def lg_worker():
        try:
            for _ in range(5):
                valuation._lg_call(lg_stub, "000300")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def cal_worker():
        try:
            for _ in range(5):
                fetch_fund.fetch_trade_calendar()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def sina_worker():
        try:
            for _ in range(5):
                fetch_estimate._fetch_index_daily_sina("sh000300")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with patch.dict(sys.modules, {"akshare": fake}):
        threads = [threading.Thread(target=lg_worker) for _ in range(3)]
        threads += [threading.Thread(target=cal_worker) for _ in range(3)]
        threads += [threading.Thread(target=sina_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, f"跨域并发调用出现异常: {errors}"
    assert counting.max_entries == 1, (
        f"同一时刻有 {counting.max_entries} 个线程处于 V8 调用段，"
        "乐咕/日历/新浪指数跨锁域未统一到 serialized()，线上可能 libmini_racer.so 段错误"
    )
