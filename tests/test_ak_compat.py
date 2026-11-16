"""akshare 跨版本改名兼容层 + 进程级 V8 串行化测试。"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from zfundpilot import ak_compat


def _fake_ak(**attrs) -> ModuleType:
    module = ModuleType("akshare")
    for name, value in attrs.items():
        setattr(module, name, value)
    return module


class _CountingLock:
    """带并发计数的上下文锁：统计同时持锁的**线程数**（忽略同线程重入）。

    py_mini_racer 的 ``__init__`` 会嵌套调用 ``self.eval``（bootstrap），
    简单计数器会把这种同线程重入误判为并发。
    """

    def __init__(self):
        import threading

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


def test_resolve_prefers_new_name():
    new = MagicMock(name="new")
    old = MagicMock(name="old")
    with patch.dict(
        sys.modules,
        {"akshare": _fake_ak(index_zh_daily_sina=new, stock_zh_index_daily=old)},
    ):
        assert ak_compat.resolve("index_zh_daily_sina", "stock_zh_index_daily") is new


def test_resolve_falls_back_to_legacy_name():
    old = MagicMock(name="old")
    with patch.dict(
        sys.modules, {"akshare": _fake_ak(stock_zh_index_daily=old)}
    ):
        assert ak_compat.resolve("index_zh_daily_sina", "stock_zh_index_daily") is old


def test_resolve_all_missing_raises():
    with patch.dict(sys.modules, {"akshare": _fake_ak()}):
        with pytest.raises(AttributeError, match="index_zh_daily_sina"):
            ak_compat.resolve("index_zh_daily_sina", "stock_zh_index_daily")


def test_call_passes_kwargs_to_resolved_function():
    new = MagicMock(return_value="df")
    with patch.dict(sys.modules, {"akshare": _fake_ak(index_zh_daily_sina=new)}):
        result = ak_compat.call(
            "index_zh_daily_sina",
            "stock_zh_index_daily",
            symbol="sh000300",
        )

    assert result == "df"
    new.assert_called_once_with(symbol="sh000300")


class TestV8Serialization:
    """V8（py_mini_racer）非线程安全，多线程并发构造/eval 会 SIGTRAP。

    多个数据源（乐咕/新浪/交易日历）、多个线程（估值 worker、定时刷新、
    HTTP 线程池）都会进 V8；进程级锁必须保证同一时刻只有一个线程进入
    构造/执行，否则服务在服务器上随机崩溃（多次 ERR_CONNECTION_REFUSED
    的根因之一）。
    """

    def test_patch_installed_and_idempotent(self):
        import py_mini_racer

        patched_eval = py_mini_racer.MiniRacer.eval
        ak_compat._ensure_v8_serialized()
        assert py_mini_racer.MiniRacer.eval is patched_eval
        assert ak_compat._MINIRACER_PATCHED is True

    def test_eval_and_call_still_work(self):
        import py_mini_racer

        ctx = py_mini_racer.MiniRacer()
        assert ctx.eval("1 + 1") == 2
        assert ctx.call("Math.max", 3, 7) == 7

    def test_concurrent_use_is_serialized(self, monkeypatch):
        import threading

        import py_mini_racer

        counting = _CountingLock()
        monkeypatch.setattr(ak_compat, "_MINIRACER_LOCK", counting)

        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(10):
                    ctx = py_mini_racer.MiniRacer()
                    assert ctx.eval("1 + 1") == 2
                    assert ctx.call("Math.max", 3, 7) == 7
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"并发进入 V8 出现异常: {errors}"
        assert counting.max_entries == 1, (
            f"同一时刻有 {counting.max_entries} 个线程进入 V8，"
            "串行锁未生效时线上会随机 SIGTRAP"
        )
