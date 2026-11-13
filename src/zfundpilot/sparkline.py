"""选基列表迷你走势：近 N 个交易日净值归一化序列。

只读 DB 净值历史，不触发在线拉取；单只读取失败降级为空序列，
不阻塞整页（与 filter_funds 的指标增强降级策略一致）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import db

logger = logging.getLogger(__name__)

MAX_CODES = 50
DEFAULT_POINTS = 250  # 约一个交易年

_CODE_RE = re.compile(r"^\d{6}$")


@dataclass
class Sparkline:
    code: str
    points: list[float] = field(default_factory=list)
    start: str = ""
    end: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "points": self.points,
            "start": self.start,
            "end": self.end,
        }


def parse_codes(raw: str) -> list[str]:
    """解析逗号分隔的基金代码（去重保序，校验 6 位数字与数量上限）。

    非法格式或超限抛 ValueError，由 API 层转为 400。
    """
    codes: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(","):
        code = part.strip()
        if not code or code in seen:
            continue
        if not _CODE_RE.fullmatch(code):
            raise ValueError(f"基金代码格式错误: {code}")
        seen.add(code)
        codes.append(code)
    if len(codes) > MAX_CODES:
        raise ValueError(f"一次最多查询 {MAX_CODES} 只基金")
    return codes


def build_sparkline(code: str, limit: int = DEFAULT_POINTS) -> Sparkline:
    """读取最近 limit 条净值并归一化（首值=1）；有效点不足 2 个返回空序列。"""
    rows = db.get_nav_history_tail(code, limit)
    points: list[float] = []
    dates: list[str] = []
    base: float | None = None
    for row in rows:
        try:
            nav = float(row["nav"])
        except (TypeError, ValueError, KeyError):
            continue
        if nav <= 0:
            continue
        if base is None:
            base = nav
        points.append(round(nav / base, 6))
        dates.append(str(row["date"]))
    if len(points) < 2:
        return Sparkline(code=code)
    return Sparkline(code=code, points=points, start=dates[0], end=dates[-1])


def build_sparklines(codes: list[str], limit: int = DEFAULT_POINTS) -> list[Sparkline]:
    """批量构建迷你走势；单只异常降级为空序列。"""
    result: list[Sparkline] = []
    for code in codes:
        try:
            result.append(build_sparkline(code, limit))
        except Exception:  # noqa: BLE001
            logger.warning("迷你走势读取失败 %s", code, exc_info=True)
            result.append(Sparkline(code=code))
    return result
