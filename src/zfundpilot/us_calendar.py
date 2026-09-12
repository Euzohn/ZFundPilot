"""美国证券市场（NYSE）交易日历。

纯算法推算纽交所全天休市日，无需联网或第三方依赖，适合离线调度场景。
用于 QDII 基金定投计划：美股休市的国内工作日不应执行申购
（QDII 基金在美股休市日通常暂停申购/无法确认）。

涵盖纽交所 10 个全天休市日：
- 固定日期 + 周末顺延（Sat→前周五, Sun→后周一）：元旦、Juneteenth(6/19)、
  独立日(7/4)、圣诞(12/25)
- 浮动日期：MLK(1月第3个周一)、总统日(2月第3个周一)、阵亡将士纪念日
  (5月最后一个周一)、劳工节(9月第1个周一)、感恩节(11月第4个周四)
- Good Friday：复活节前一个周五（复活节由 Computus 算法推算）
- 跨年元旦顺延：若次年元旦为周六，则顺延日前一年 12/31 为休市日
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import lru_cache


def _easter_sunday(year: int) -> date:
    """匿名格里高利 Computus 算法推算复活节周日。"""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, target_dow: int, n: int) -> date:
    """返回 year-month 中第 n 个 target_dow（0=周一..6=周日）的日期。"""
    first = date(year, month, 1)
    offset = (target_dow - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, target_dow: int) -> date:
    """返回 year-month 中最后一个 target_dow 的日期。"""
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    offset = (last.weekday() - target_dow) % 7
    return last - timedelta(days=offset)


def _observed(d: date) -> date:
    """固定日期休市日的顺延规则：周六→前周五，周日→后周一，工作日不变。"""
    if d.weekday() == 5:  # 周六 → 前周五
        return d - timedelta(days=1)
    if d.weekday() == 6:  # 周日 → 后周一
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=8)
def us_market_holidays(year: int) -> set[date]:
    """返回某年中纽交所全天休市的日期集合。

    跨年元旦：若次年 1/1 为周六（顺延日前一年 12/31），则该 12/31 归入本年集合。
    """
    holidays: set[date] = set()

    # 固定日期 + 顺延
    holidays.add(_observed(date(year, 1, 1)))          # 元旦
    holidays.add(_observed(date(year, 6, 19)))          # Juneteenth
    holidays.add(_observed(date(year, 7, 4)))           # 独立日
    holidays.add(_observed(date(year, 12, 25)))         # 圣诞

    # 浮动日期（第 n 个周几 / 最后一个周几）
    holidays.add(_nth_weekday(year, 1, 0, 3))           # MLK：1月第3个周一
    holidays.add(_nth_weekday(year, 2, 0, 3))            # 总统日：2月第3个周一
    holidays.add(_last_weekday(year, 5, 0))             # 阵亡将士纪念日：5月最后一个周一
    holidays.add(_nth_weekday(year, 9, 0, 1))           # 劳工节：9月第1个周一
    holidays.add(_nth_weekday(year, 11, 3, 4))          # 感恩节：11月第4个周四

    # Good Friday：复活节前一个周五
    holidays.add(_easter_sunday(year) - timedelta(days=2))

    # 跨年元旦：次年 1/1 若为周六 → 顺延日 12/31 落在本年
    next_new_year_obs = _observed(date(year + 1, 1, 1))
    if next_new_year_obs.year == year:
        holidays.add(next_new_year_obs)

    # 清理顺延后落到非本年的日期（如元旦为周六时 observed 是前一年 12/31）
    holidays = {d for d in holidays if d.year == year}
    return holidays


def is_us_market_holiday(d: date) -> bool:
    """判断某日是否为美股休市日（仅含全天休市，不含提前收盘日）。"""
    return d in us_market_holidays(d.year)


def is_us_trading_day(d: date) -> bool:
    """判断某日是否为美股交易日（工作日且非休市日）。"""
    return d.weekday() < 5 and not is_us_market_holiday(d)
