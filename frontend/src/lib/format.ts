import { getCurrentLang } from "@/i18n/LanguageContext"

export function money(v: number | null | undefined): string {
  if (v == null) return "—"
  const lang = getCurrentLang()
  const locale = lang === "zh" ? "zh-CN" : "en-US"
  return `¥${v.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—"
  return `${(v * 100).toFixed(digits)}%`
}

export function signedMoney(v: number | null | undefined): string {
  if (v == null) return "—"
  const sign = v >= 0 ? "+" : "-"
  const lang = getCurrentLang()
  const locale = lang === "zh" ? "zh-CN" : "en-US"
  return `${sign}¥${Math.abs(v).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function navStr(v: number | null | undefined): string {
  if (v == null) return "—"
  return v.toFixed(4)
}

export function pnlColor(v: number | null | undefined): string {
  if (v == null) return ""
  if (v > 0) return "text-gain"
  if (v < 0) return "text-loss"
  return ""
}

export function localDateStr(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

// 相对时间多语言文案（避免引入 i18n 翻译文件造成循环依赖）
const RELATIVE_TIME_ZH = {
  justNow: "刚刚",
  minutesAgo: (n: number) => `${n} 分钟前`,
  hoursAgo: (n: number) => `${n} 小时前`,
  yesterday: "昨天",
  daysAgo: (n: number) => `${n} 天前`,
  monthDay: (m: number, d: number) => `${m} 月 ${d} 日`,
}
const RELATIVE_TIME_EN = {
  justNow: "just now",
  minutesAgo: (n: number) => `${n} min ago`,
  hoursAgo: (n: number) => `${n} hr ago`,
  yesterday: "yesterday",
  daysAgo: (n: number) => `${n} days ago`,
  monthDay: (m: number, d: number) => `${m}/${d}`,
}

/**
 * 相对时间格式化（"刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前 / M 月 D 日"）
 * 后端存的是 UTC（datetime('now')），格式 "YYYY-MM-DD HH:MM:SS"
 */
export function formatRelativeTime(iso: string): string {
  const t = new Date(iso.replace(" ", "T") + "Z").getTime()
  if (isNaN(t)) return ""
  const diff = Date.now() - t
  const min = Math.floor(diff / 60000)
  const tr = getCurrentLang() === "zh" ? RELATIVE_TIME_ZH : RELATIVE_TIME_EN
  if (min < 1) return tr.justNow
  if (min < 60) return tr.minutesAgo(min)
  const hr = Math.floor(min / 60)
  if (hr < 24) return tr.hoursAgo(hr)
  const day = Math.floor(hr / 24)
  if (day === 1) return tr.yesterday
  if (day < 30) return tr.daysAgo(day)
  const d = new Date(iso)
  return tr.monthDay(d.getMonth() + 1, d.getDate())
}

/**
 * Token 数量紧凑格式化（123 / 1.2k / 12k / 1.2m）
 */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1000000) return (n / 1000).toFixed(n < 10000 ? 1 : 0) + "k"
  return (n / 1000000).toFixed(1) + "m"
}
