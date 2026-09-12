"""美国证券市场（NYSE）交易日历测试。

验证：
1. 2026 年 10 个全天休市日（含独立日周末顺延到 7/3 observed）
2. 周末/普通工作日不误判
3. 跨年元旦顺延（2021-12-31 为 observed，因 2022-01-01 周六）
4. 复活节/Good Friday 边界年份
5. is_us_trading_day 语义
"""
from datetime import date

from zfundpilot.us_calendar import (
    _easter_sunday,
    is_us_market_holiday,
    is_us_trading_day,
    us_market_holidays,
)


class TestEasterComputus:
    """验证复活节推算（已知值）。"""

    def test_easter_2024(self):
        assert _easter_sunday(2024) == date(2024, 3, 31)

    def test_easter_2025(self):
        assert _easter_sunday(2025) == date(2025, 4, 20)

    def test_easter_2026(self):
        assert _easter_sunday(2026) == date(2026, 4, 5)

    def test_easter_2027(self):
        assert _easter_sunday(2027) == date(2027, 3, 28)


class TestHolidays2026:
    """2026 年纽交所全天休市日断言。"""

    def test_new_year(self):
        # 2026-01-01 周四，不顺延
        assert is_us_market_holiday(date(2026, 1, 1)) is True
        assert is_us_market_holiday(date(2026, 1, 2)) is False

    def test_mlk(self):
        # 1月第3个周一 = 2026-01-19
        assert is_us_market_holiday(date(2026, 1, 19)) is True
        assert is_us_market_holiday(date(2026, 1, 12)) is False

    def test_presidents_day(self):
        # 2月第3个周一 = 2026-02-16
        assert is_us_market_holiday(date(2026, 2, 16)) is True

    def test_good_friday(self):
        # 复活节 4/5 → Good Friday 4/3
        assert is_us_market_holiday(date(2026, 4, 3)) is True
        assert is_us_market_holiday(date(2026, 4, 2)) is False

    def test_memorial_day(self):
        # 5月最后一个周一 = 2026-05-25
        assert is_us_market_holiday(date(2026, 5, 25)) is True
        assert is_us_market_holiday(date(2026, 5, 18)) is False

    def test_juneteenth(self):
        # 2026-06-19 周五，不顺延
        assert is_us_market_holiday(date(2026, 6, 19)) is True

    def test_independence_day_observed(self):
        # 2026-07-04 周六 → observed 2026-07-03 周五
        assert is_us_market_holiday(date(2026, 7, 3)) is True
        assert is_us_market_holiday(date(2026, 7, 4)) is False  # 周六本身不算休市日（周末）

    def test_labor_day(self):
        # 9月第1个周一 = 2026-09-07
        assert is_us_market_holiday(date(2026, 9, 7)) is True

    def test_thanksgiving(self):
        # 11月第4个周四 = 2026-11-26
        assert is_us_market_holiday(date(2026, 11, 26)) is True

    def test_christmas(self):
        # 2026-12-25 周五，不顺延
        assert is_us_market_holiday(date(2026, 12, 25)) is True

    def test_all_2026_holidays(self):
        """2026 年完整休市日集合（10 个）。"""
        expected = {
            date(2026, 1, 1),    # 元旦
            date(2026, 1, 19),   # MLK
            date(2026, 2, 16),   # 总统日
            date(2026, 4, 3),    # Good Friday
            date(2026, 5, 25),   # 阵亡将士纪念日
            date(2026, 6, 19),   # Juneteenth
            date(2026, 7, 3),    # 独立日 observed
            date(2026, 9, 7),    # 劳工节
            date(2026, 11, 26),  # 感恩节
            date(2026, 12, 25),  # 圣诞
        }
        assert us_market_holidays(2026) == expected

    def test_2026_no_cross_year_observed(self):
        """2027-01-01 周五 → 不顺延，2026 无 12/31 observed。"""
        assert is_us_market_holiday(date(2026, 12, 31)) is False


class TestCrossYearNewYear:
    """跨年元旦 observed 归入上一年。"""

    def test_2021_12_31_is_holiday(self):
        """2022-01-01 周六 → observed 2021-12-31 周五，归入 2021 集合。"""
        assert is_us_market_holiday(date(2021, 12, 31)) is True

    def test_2022_01_01_is_weekend_not_holiday(self):
        """2022-01-01 周六本身不算休市日（周末不单列）。"""
        assert is_us_market_holiday(date(2022, 1, 1)) is False

    def test_2022_01_03_is_trading_day(self):
        """2022-01-03 周一不是休市日（observed 已在 12/31）。"""
        assert is_us_market_holiday(date(2022, 1, 3)) is False


class TestWeekendAndOrdinaryDays:
    """周末和普通工作日不应被误判为休市日。"""

    def test_saturday_not_holiday(self):
        assert is_us_market_holiday(date(2026, 3, 14)) is False  # 周六

    def test_sunday_not_holiday(self):
        assert is_us_market_holiday(date(2026, 3, 15)) is False  # 周日

    def test_ordinary_weekday_not_holiday(self):
        assert is_us_market_holiday(date(2026, 3, 16)) is False  # 周一


class TestUsTradingDay:
    """is_us_trading_day 语义。"""

    def test_weekend_not_trading(self):
        assert is_us_trading_day(date(2026, 3, 14)) is False  # 周六
        assert is_us_trading_day(date(2026, 3, 15)) is False  # 周日

    def test_holiday_not_trading(self):
        assert is_us_trading_day(date(2026, 7, 3)) is False  # 独立日 observed

    def test_ordinary_weekday_trading(self):
        assert is_us_trading_day(date(2026, 3, 16)) is True  # 周一

    def test_day_after_independence_trading(self):
        assert is_us_trading_day(date(2026, 7, 6)) is True  # 周一，独立日后首个交易日
