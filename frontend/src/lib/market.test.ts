import { afterAll, describe, expect, it } from "vitest"
import { isMarketOpen } from "./market"

// A 股时段按 UTC+8 判断，结果必须与设备时区无关。
// 用多个时区跑同一组 UTC 时刻用例（2026-11-16 为周一，11-14/15 为周末）。
const ORIGINAL_TZ = process.env.TZ

afterAll(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ
  else process.env.TZ = ORIGINAL_TZ
})

const CASES: Array<[string, boolean]> = [
  // 上午盘 9:30-11:30（含边界）
  ["2026-11-16T01:29:00Z", false], // 09:29
  ["2026-11-16T01:30:00Z", true], // 09:30（纽约此时为周日晚，旧代码误判休市）
  ["2026-11-16T03:30:00Z", true], // 11:30
  ["2026-11-16T03:31:00Z", false], // 11:31 午休
  // 午休
  ["2026-11-16T04:59:00Z", false], // 12:59
  // 下午盘 13:00-15:00（含边界）
  ["2026-11-16T05:00:00Z", true], // 13:00
  ["2026-11-16T07:00:00Z", true], // 15:00
  ["2026-11-16T07:01:00Z", false], // 15:01
  // 盘前/盘后
  ["2026-11-16T00:00:00Z", false], // 08:00
  ["2026-11-16T08:00:00Z", false], // 16:00
  // 周末（UTC+8 的周六/周日）
  ["2026-11-14T02:00:00Z", false], // 周六 10:00
  ["2026-11-15T03:00:00Z", false], // 周日 11:00
  // 星期按 UTC+8 换算：UTC 周五晚已是北京时间周六
  ["2026-11-13T17:00:00Z", false], // 周六 01:00
  // UTC 周日晚已是北京时间周一（但非交易时段）
  ["2026-11-15T17:00:00Z", false], // 周一 01:00
]

for (const tz of ["America/New_York", "UTC", "Asia/Shanghai"]) {
  describe(`设备时区 ${tz}`, () => {
    it.each(CASES)("%s → %s", (iso, expected) => {
      process.env.TZ = tz
      expect(isMarketOpen(new Date(iso))).toBe(expected)
    })
  })
}
