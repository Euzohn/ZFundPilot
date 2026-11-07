"""HTTP 请求 ID 与统一错误响应包。

错误响应同时保留旧版 ``detail`` 字段与新 ``error`` 对象，便于客户端平滑迁移：

- ``detail``：既有 FastAPI / 业务错误原样保留（旧客户端不受影响）；
- ``error``：``{code, message, request_id, retryable, details?, retry_after?}``；
- ``request_id``：与响应头 ``X-Request-ID`` 一致，便于服务端排障。

``code`` 是稳定、可供程序判断的错误码；``message`` 是中文兜底文案，客户端应优先
按 ``code`` 做本地化，而不是匹配文案。
"""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar, Token
from typing import Any

from fastapi import HTTPException

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")

_request_id_var: ContextVar[str] = ContextVar("zfund_request_id", default="")

DEFAULT_ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

DEFAULT_ERROR_MESSAGES: dict[int, str] = {
    400: "请求参数不合法",
    401: "未认证或凭证无效",
    403: "没有执行该操作的权限",
    404: "请求的资源不存在",
    405: "请求方法不被允许",
    409: "请求与当前状态冲突",
    422: "请求参数校验失败",
    429: "请求过于频繁，请稍后重试",
    500: "服务器内部错误",
    503: "服务暂时不可用，请稍后重试",
}

RETRYABLE_STATUS_CODES = frozenset({429, 503})


def normalize_request_id(value: str | None) -> str:
    """沿用调用方传入的合法请求 ID，否则生成新的。

    只接受 ASCII 字母、数字和 ``._:-``，长度 8–64，避免把任意头内容回显到
    响应头或日志（防头注入）。
    """
    if value and _REQUEST_ID_RE.fullmatch(value):
        return value
    return uuid.uuid4().hex


def set_request_id(value: str) -> Token[str]:
    """设置当前请求 ID，返回可用于恢复的 token。"""
    return _request_id_var.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str:
    """返回当前请求 ID；不在请求上下文时返回空串。"""
    return _request_id_var.get()


class ApiError(HTTPException):
    """可携带稳定错误码的 ``HTTPException``。

    不改变 ``detail`` 的既有形状（字符串或 dict），只额外提供 ``code`` 等元数据，
    供统一错误包使用；普通 ``HTTPException`` 仍按状态码与 ``detail.code`` 推导。
    """

    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        retry_after: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


def _split_detail(detail: Any) -> tuple[str | None, str | None, Any]:
    """从既有 ``detail`` 中拆出 code / message / 其余细节。"""
    if isinstance(detail, dict):
        rest = dict(detail)
        code = rest.pop("code", None)
        message = rest.pop("message", None)
        return (
            code if isinstance(code, str) else None,
            message if isinstance(message, str) else None,
            rest or None,
        )
    if isinstance(detail, str):
        return None, detail, None
    return None, None, detail


def build_error_payload(
    *,
    request_id: str,
    status_code: int,
    detail: Any = None,
    code: str | None = None,
    message: str | None = None,
    details: Any = None,
    retryable: bool | None = None,
    retry_after: int | None = None,
) -> dict[str, Any]:
    """构造兼容旧客户端的统一错误响应体。"""
    detail_code, detail_message, detail_rest = _split_detail(detail)
    resolved_code = code or detail_code or DEFAULT_ERROR_CODES.get(
        status_code, "http_error")
    resolved_message = (
        message or detail_message
        or DEFAULT_ERROR_MESSAGES.get(status_code, "请求失败"))
    if details is None:
        details = detail_rest
    if retryable is None:
        retryable = status_code in RETRYABLE_STATUS_CODES

    error: dict[str, Any] = {
        "code": resolved_code,
        "message": resolved_message,
        "request_id": request_id,
        "retryable": retryable,
    }
    if details is not None:
        error["details"] = details
    if retry_after is not None:
        error["retry_after"] = retry_after
    return {"detail": detail, "error": error, "request_id": request_id}
