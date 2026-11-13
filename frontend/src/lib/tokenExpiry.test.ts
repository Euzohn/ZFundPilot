import { describe, expect, it } from "vitest"

import { isTokenExpiringSoon, TOKEN_EXPIRING_SOON_DAYS } from "./tokenExpiry"

const NOW = Date.parse("2026-11-14T00:00:00Z")
const DAY_MS = 24 * 60 * 60 * 1000

describe("isTokenExpiringSoon", () => {
  it("阈值默认为 7 天", () => {
    expect(TOKEN_EXPIRING_SOON_DAYS).toBe(7)
  })

  it("未来 7 天内返回 true", () => {
    const inThreeDays = new Date(NOW + 3 * DAY_MS).toISOString()
    expect(isTokenExpiringSoon(inThreeDays, undefined, NOW)).toBe(true)
  })

  it("恰好 7 天边界返回 true", () => {
    const inSevenDays = new Date(NOW + 7 * DAY_MS).toISOString()
    expect(isTokenExpiringSoon(inSevenDays, undefined, NOW)).toBe(true)
  })

  it("超过 7 天返回 false", () => {
    const inEightDays = new Date(NOW + 8 * DAY_MS).toISOString()
    expect(isTokenExpiringSoon(inEightDays, undefined, NOW)).toBe(false)
  })

  it("已过期返回 false（由后端 active=false 展示已过期）", () => {
    const oneDayAgo = new Date(NOW - DAY_MS).toISOString()
    expect(isTokenExpiringSoon(oneDayAgo, undefined, NOW)).toBe(false)
  })

  it("空值或非法时间返回 false", () => {
    expect(isTokenExpiringSoon(null, undefined, NOW)).toBe(false)
    expect(isTokenExpiringSoon(undefined, undefined, NOW)).toBe(false)
    expect(isTokenExpiringSoon("", undefined, NOW)).toBe(false)
    expect(isTokenExpiringSoon("not-a-date", undefined, NOW)).toBe(false)
  })

  it("支持自定义阈值天数", () => {
    const inTenDays = new Date(NOW + 10 * DAY_MS).toISOString()
    expect(isTokenExpiringSoon(inTenDays, 7, NOW)).toBe(false)
    expect(isTokenExpiringSoon(inTenDays, 14, NOW)).toBe(true)
  })
})