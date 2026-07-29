export function isMarketOpen(date: Date = new Date()): boolean {
  const day = date.getDay()
  if (day === 0 || day === 6) return false
  const t = date.getHours() * 60 + date.getMinutes()
  return (t >= 570 && t <= 690) || (t >= 780 && t <= 900)
}
