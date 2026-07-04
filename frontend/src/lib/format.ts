export function money(v: number | null | undefined): string {
  if (v == null) return "—"
  return `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—"
  return `${(v * 100).toFixed(digits)}%`
}

export function signedMoney(v: number | null | undefined): string {
  if (v == null) return "—"
  const sign = v >= 0 ? "+" : "-"
  return `${sign}¥${Math.abs(v).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function navStr(v: number | null | undefined): string {
  if (v == null) return "—"
  return v.toFixed(4)
}

export function pnlColor(v: number | null | undefined): string {
  if (v == null) return ""
  if (v > 0) return "text-green-600"
  if (v < 0) return "text-red-600"
  return ""
}
