"""akshare 接口兼容层（跨版本批量改名 + 进程级 V8 串行化）。

akshare 1.20.4x 起批量重命名接口（见其 ``data/renames.json``），旧名直接
从顶层导出中移除。项目同时兼容新旧版本：优先使用新名，回退旧名。

V8 串行化背景：多个 akshare 数据源内部用 py_mini_racer(V8) 解 JS
（乐咕、新浪指数日线、交易日历等），V8 **非线程安全**——不同线程
同时创建/执行会直接让进程 SIGTRAP。应用内多线程并发使用这些接口
（估值 worker、定时刷新任务、HTTP 请求线程池）必然踩中。这里在
py_mini_racer 引擎层打一处进程级锁（幂等），覆盖所有数据源、跨
akshare 版本生效，不需要维护「哪些接口用 V8」的版本相关清单。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

# 进程级 V8 锁（RLock：MiniRacer 的构造/eval/call 共用；多个线程各用各的
# MiniRacer 实例同样会 SIGTRAP，所以构造也要串行）
_MINIRACER_LOCK = threading.RLock()
_MINIRACER_PATCHED = False


def _ensure_v8_serialized() -> None:
    """幂等地给 py_mini_racer 的 MiniRacer 加进程级锁。

    akshare 内部的裸 requests 无超时问题的兜底见
    ``valuation._ensure_requests_timeout``，两者互补。
    """
    global _MINIRACER_PATCHED
    if _MINIRACER_PATCHED:
        return
    import py_mini_racer

    # 注意：闭包内直接引用模块级全局 _MINIRACER_LOCK（调用时查找），
    # 便于测试注入带并发计数的锁验证串行性
    original_init = py_mini_racer.MiniRacer.__init__
    original_eval = py_mini_racer.MiniRacer.eval
    original_call = py_mini_racer.MiniRacer.call

    def locked_init(self: Any, *args: Any, **kwargs: Any) -> None:
        with _MINIRACER_LOCK:
            original_init(self, *args, **kwargs)

    def locked_eval(self: Any, *args: Any, **kwargs: Any) -> Any:
        with _MINIRACER_LOCK:
            return original_eval(self, *args, **kwargs)

    def locked_call(self: Any, *args: Any, **kwargs: Any) -> Any:
        with _MINIRACER_LOCK:
            return original_call(self, *args, **kwargs)

    py_mini_racer.MiniRacer.__init__ = locked_init  # type: ignore[method-assign]
    py_mini_racer.MiniRacer.eval = locked_eval  # type: ignore[method-assign]
    py_mini_racer.MiniRacer.call = locked_call  # type: ignore[method-assign]
    _MINIRACER_PATCHED = True


def resolve(*names: str) -> Callable[..., Any]:
    """按顺序返回第一个存在的 akshare 顶层接口。

    全部不存在时抛 ``AttributeError``，由调用方按既有异常路径降级。
    """
    import akshare as ak

    for name in names:
        fn = getattr(ak, name, None)
        if fn is not None:
            return fn
    raise AttributeError(f"akshare 缺少接口：{' / '.join(names)}")


def call(*names: str, **kwargs: Any) -> Any:
    """按顺序调用第一个存在的 akshare 顶层接口。"""
    return resolve(*names)(**kwargs)


# 导入即生效（api 启动必然导入本模块；幂等，多处调用无副作用）
_ensure_v8_serialized()
