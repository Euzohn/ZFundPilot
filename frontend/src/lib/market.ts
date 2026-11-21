// A 股交易时段为北京时间（UTC+8）9:30-11:30 / 13:00-15:00，
// 统一换算到 UTC+8 判断，不依赖设备本地时区（自部署场景用户可能在任意时区）。
export function isMarketOpen(date: Date = new Date()): boolean {
  const cn = new Date(date.getTime() + 8 * 60 * 60 * 1000)
  const day = cn.getUTCDay()
  if (day === 0 || day === 6) return false
  const t = cn.getUTCHours() * 60 + cn.getUTCMinutes()
  return (t >= 570 && t <= 690) || (t >= 780 && t <= 900)
}
