"""akshare 接口兼容层（跨版本批量改名）。

akshare 1.20.4x 起批量重命名接口（见其 ``data/renames.json``），旧名直接
从顶层导出中移除。项目同时兼容新旧版本：优先使用新名，回退旧名。

本模块只做名称解析，不改变参数/返回结构；调用方仍需按原接口传参。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


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
