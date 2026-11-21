import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { formatLargeCN, formatRelativeTime, formatRelativeTimeTz } from "./format"
import { getCurrentLang } from "@/i18n/LanguageContext"

vi.mock("@/i18n/LanguageContext", () => ({ getCurrentLang: vi.fn(() => "zh") }))

beforeEach(() => {
  vi.mocked(getCurrentLang).mockReturnValue("zh")
})

describe("formatLargeCN（输入单位：万元）", () => {
  it("中文界面按亿显示", () => {
    expect(formatLargeCN(12345)).toBe("1.23亿")
    expect(formatLargeCN(1000000)).toBe("100.00亿")
  })

  it("空值/非正值显示 —", () => {
    expect(formatLargeCN(null)).toBe("—")
    expect(formatLargeCN(undefined)).toBe("—")
    expect(formatLargeCN(0)).toBe("—")
    expect(formatLargeCN(-5)).toBe("—")
  })

  describe("英文界面 M/B/T 分支", () => {
    beforeEach(() => {
      vi.mocked(getCurrentLang).mockReturnValue("en")
    })

    it("M 分支：yi < 100（1 亿 = 100M）", () => {
      expect(formatLargeCN(50000)).toBe("500.00M") // 5 亿 = 500M
      expect(formatLargeCN(999999)).toBe("9999.99M")
    })

    it("B 分支边界：100 亿 = 10B（回归：旧代码误显示 100.00B）", () => {
      expect(formatLargeCN(1000000)).toBe("10.00B")
    })

    it("B 分支：1B = 10 亿，值为 yi/10", () => {
      expect(formatLargeCN(5500000)).toBe("55.00B") // 550 亿
      expect(formatLargeCN(99000000)).toBe("990.00B") // 9900 亿，未到 T
    })

    it("T 分支边界：10000 亿 = 1T", () => {
      expect(formatLargeCN(100000000)).toBe("1.00T")
      expect(formatLargeCN(250000000)).toBe("2.50T")
    })
  })
})

describe("相对时间回退月/日的解析口径", () => {
  const ORIGINAL_TZ = process.env.TZ

  beforeAll(() => {
    // 固定东八区：UTC 晚间记录的本地日期已是次日，可区分两种解析口径
    process.env.TZ = "Asia/Shanghai"
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-11-20T12:00:00Z"))
  })

  afterAll(() => {
    vi.useRealTimers()
    if (ORIGINAL_TZ === undefined) delete process.env.TZ
    else process.env.TZ = ORIGINAL_TZ
  })

  afterEach(() => {
    vi.mocked(getCurrentLang).mockReturnValue("zh")
  })

  it("30 天内的相对文案不受影响", () => {
    expect(formatRelativeTime("2026-11-20 11:59:30")).toBe("刚刚")
    expect(formatRelativeTime("2026-11-20 11:30:00")).toBe("30 分钟前")
    expect(formatRelativeTime("2026-11-20 02:00:00")).toBe("10 小时前")
    expect(formatRelativeTime("2026-11-19 12:00:00")).toBe("昨天")
    expect(formatRelativeTime("2026-11-15 12:00:00")).toBe("5 天前")
  })

  it("超过 30 天回退月/日：与入口 UTC 语义一致（回归：旧代码按本地时间裸解析差一天）", () => {
    // UTC 2026-10-01 20:00 = 东八区 2026-10-02 04:00，应显示本地日期 10 月 2 日
    expect(formatRelativeTime("2026-10-01 20:00:00")).toBe("10 月 2 日")
    vi.mocked(getCurrentLang).mockReturnValue("en")
    expect(formatRelativeTime("2026-10-01 20:00:00")).toBe("10/2")
  })

  it("带时区路径与 UTC 路径对同一时刻显示一致", () => {
    expect(formatRelativeTimeTz("2026-10-01T20:00:00+00:00")).toBe("10 月 2 日")
    expect(formatRelativeTimeTz("2026-10-02T04:00:00+08:00")).toBe("10 月 2 日")
  })

  it("非法时间返回空串", () => {
    expect(formatRelativeTime("not-a-date")).toBe("")
    expect(formatRelativeTimeTz("garbage")).toBe("")
  })
})
