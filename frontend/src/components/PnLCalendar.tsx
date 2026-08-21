import { useState, useMemo } from "react"
import { money, localDateStr } from "@/lib/format"
import { cn } from "@/lib/utils"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { useLang } from "@/i18n/LanguageContext"

interface PnlDay {
  date: string
  pnl: number
}

type CalendarMode = "day" | "week" | "month" | "year"

interface Props {
  data: PnlDay[]
  mode?: CalendarMode
}

function getPnlBg(pnl: number | null, maxAbs: number): string {
  if (pnl === null || pnl === 0) return "bg-muted/50"
  const intensity = Math.min(Math.abs(pnl) / maxAbs, 1)
  if (pnl > 0) {
    if (intensity > 0.8) return "bg-gain-400 text-gain-950"
    if (intensity > 0.6) return "bg-gain-300 text-gain-900"
    if (intensity > 0.4) return "bg-gain-200 text-gain-800"
    if (intensity > 0.2) return "bg-gain-100 text-gain-700"
    return "bg-gain-50 text-gain-600"
  } else {
    if (intensity > 0.8) return "bg-loss-400 text-loss-950"
    if (intensity > 0.6) return "bg-loss-300 text-loss-900"
    if (intensity > 0.4) return "bg-loss-200 text-loss-800"
    if (intensity > 0.2) return "bg-loss-100 text-loss-700"
    return "bg-loss-50 text-loss-600"
  }
}

function formatCompactPnl(pnl: number, tenThousand: string): string {
  const sign = pnl >= 0 ? "+" : ""
  if (Math.abs(pnl) >= 10000) return `${sign}${(pnl / 10000).toFixed(1)}${tenThousand}`
  if (Math.abs(pnl) >= 1000) return `${sign}${(pnl / 1000).toFixed(1)}k`
  return `${sign}${pnl.toFixed(0)}`
}

export default function PnLCalendar({ data, mode = "day" }: Props) {
  const { t } = useLang()

  // 每日 P&L map（日视图）
  const pnlMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const d of data) m[d.date] = d.pnl
    return m
  }, [data])

  // 周聚合：Monday-anchor 分桶
  const weeklyMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const d of data) {
      const dt = new Date(d.date + "T00:00:00")
      const day = dt.getDay() || 7
      const monday = new Date(dt)
      monday.setDate(dt.getDate() - day + 1)
      const key = localDateStr(monday)
      if (!m[key]) m[key] = 0
      m[key] += d.pnl
    }
    for (const k of Object.keys(m)) m[k] = Math.round(m[k] * 100) / 100
    return m
  }, [data])

  // 月聚合：YYYY-MM 分桶
  const monthlyMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const d of data) {
      const dt = new Date(d.date + "T00:00:00")
      const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`
      if (!m[key]) m[key] = 0
      m[key] += d.pnl
    }
    for (const k of Object.keys(m)) m[k] = Math.round(m[k] * 100) / 100
    return m
  }, [data])

  // 年聚合：YYYY 分桶
  const yearlyMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const d of data) {
      const dt = new Date(d.date + "T00:00:00")
      const key = String(dt.getFullYear())
      if (!m[key]) m[key] = 0
      m[key] += d.pnl
    }
    for (const k of Object.keys(m)) m[k] = Math.round(m[k] * 100) / 100
    return m
  }, [data])

  // 按当前模式归一化强度
  const maxAbs = useMemo(() => {
    if (data.length === 0) return 1
    let values: number[]
    if (mode === "day") values = data.map((d) => Math.abs(d.pnl))
    else if (mode === "week") values = Object.values(weeklyMap).map(Math.abs)
    else if (mode === "month") values = Object.values(monthlyMap).map(Math.abs)
    else values = Object.values(yearlyMap).map(Math.abs)
    return Math.max(...values, 1)
  }, [data, mode, weeklyMap, monthlyMap, yearlyMap])

  // 默认定位到最近有数据的月份/年份
  const [viewYear, setViewYear] = useState(() => {
    if (data.length > 0) return new Date(data[data.length - 1].date + "T00:00:00").getFullYear()
    return new Date().getFullYear()
  })
  const [viewMonth, setViewMonth] = useState(() => {
    if (data.length > 0) return new Date(data[data.length - 1].date + "T00:00:00").getMonth()
    return new Date().getMonth()
  })

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear((y) => y - 1) }
    else setViewMonth((m) => m - 1)
  }
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear((y) => y + 1) }
    else setViewMonth((m) => m + 1)
  }
  const prevYear = () => setViewYear((y) => y - 1)
  const nextYear = () => setViewYear((y) => y + 1)

  const unit = t.components.pnlCalendarUnit[mode]
  const renderSummary = (sum: number, win: number, total: number) =>
    total > 0 && (
      <span className="ml-2 text-xs text-muted-foreground">
        <span className={sum >= 0 ? "text-gain" : "text-loss"}>{money(sum)}</span>
        {" · "}
        {t.components.pnlCalendarWinLose.replace(/\{win\}/g, String(win)).replace(/\{lose\}/g, String(total - win)).replace(/\{u\}/g, unit)}
      </span>
    )

  // ---- Day 视图：月历网格 ----
  const dayCells = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1)
    const lastDay = new Date(viewYear, viewMonth + 1, 0)
    const startWeekday = firstDay.getDay()
    const daysInMonth = lastDay.getDate()
    const arr: ({ date: string; day: number; pnl: number | null } | null)[] = []
    for (let i = 0; i < startWeekday; i++) arr.push(null)
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`
      arr.push({ date: dateStr, day: d, pnl: dateStr in pnlMap ? pnlMap[dateStr] : null })
    }
    return arr
  }, [viewYear, viewMonth, pnlMap])
  const dayMonthLabel = t.components.monthLabel.replace("{y}", String(viewYear)).replace("{m}", String(viewMonth + 1))
  const dayPnls = dayCells.filter((c): c is { date: string; day: number; pnl: number } => c !== null && c.pnl !== null)
  const daySum = dayPnls.reduce((s, c) => s + c.pnl, 0)
  const dayWin = dayPnls.filter((c) => c.pnl > 0).length

  // ---- Week 视图：12 行月份，每行 5 列周 cell ----
  const weekRows = useMemo(() => {
    const rows: { label: string; weeks: { key: string; label: string; pnl: number | null }[] }[] = []
    for (let m = 0; m < 12; m++) {
      const weeks: { key: string; label: string; pnl: number | null }[] = []
      let d = new Date(viewYear, m, 1)
      while (d.getDay() !== 1 && d.getMonth() === m) d.setDate(d.getDate() + 1)
      while (d.getMonth() === m && d.getFullYear() === viewYear) {
        const key = localDateStr(d)
        weeks.push({ key, label: `${d.getMonth() + 1}/${d.getDate()}`, pnl: key in weeklyMap ? weeklyMap[key] : null })
        d.setDate(d.getDate() + 7)
      }
      rows.push({ label: t.components.months[m], weeks })
    }
    return rows
  }, [viewYear, weeklyMap, t])
  const yearWeeks = Object.entries(weeklyMap)
    .filter(([k]) => k.startsWith(String(viewYear)))
    .map(([, p]) => p)
  const weekSum = yearWeeks.reduce((s, p) => s + p, 0)
  const weekWin = yearWeeks.filter((p) => p > 0).length

  // ---- Month 视图：4×3 月格 ----
  const monthCells = useMemo(() => {
    const cells: { month: number; label: string; pnl: number | null }[] = []
    for (let m = 0; m < 12; m++) {
      const key = `${viewYear}-${String(m + 1).padStart(2, "0")}`
      cells.push({ month: m, label: t.components.months[m], pnl: key in monthlyMap ? monthlyMap[key] : null })
    }
    return cells
  }, [viewYear, monthlyMap, t])
  const yearMonths = monthCells.filter((c) => c.pnl !== null)
  const monthSum = yearMonths.reduce((s, c) => s + (c.pnl || 0), 0)
  const monthWin = yearMonths.filter((c) => (c.pnl || 0) > 0).length

  // ---- Year 视图：所有年份平铺 ----
  const yearCells = useMemo(() => {
    return Object.entries(yearlyMap)
      .map(([year, pnl]) => ({ year: parseInt(year), pnl }))
      .sort((a, b) => a.year - b.year)
  }, [yearlyMap])
  const totalSum = yearCells.reduce((s, c) => s + c.pnl, 0)
  const yearWin = yearCells.filter((c) => c.pnl > 0).length

  return (
    <div className="space-y-3">
      {/* 顶部导航 */}
      {mode === "day" ? (
        <div className="flex items-center justify-between">
          <button onClick={prevMonth} className="flex h-7 w-7 items-center justify-center rounded hover:bg-accent transition-colors">
            <ChevronLeft className="h-4 w-4 text-muted-foreground" />
          </button>
          <div className="text-center">
            <span className="text-sm font-medium">{dayMonthLabel}</span>
            {renderSummary(daySum, dayWin, dayPnls.length)}
          </div>
          <button onClick={nextMonth} className="flex h-7 w-7 items-center justify-center rounded hover:bg-accent transition-colors">
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>
      ) : mode === "year" ? (
        <div className="text-center">
          <span className="text-sm font-medium">{t.components.pnlCalendarTitle}</span>
          {renderSummary(totalSum, yearWin, yearCells.length)}
        </div>
      ) : (
        <div className="flex items-center justify-between">
          <button onClick={prevYear} className="flex h-7 w-7 items-center justify-center rounded hover:bg-accent transition-colors">
            <ChevronLeft className="h-4 w-4 text-muted-foreground" />
          </button>
          <div className="text-center">
            <span className="text-sm font-medium">{t.components.yearLabel.replace("{y}", String(viewYear))}</span>
            {renderSummary(mode === "week" ? weekSum : monthSum, mode === "week" ? weekWin : monthWin, mode === "week" ? yearWeeks.length : yearMonths.length)}
          </div>
          <button onClick={nextYear} className="flex h-7 w-7 items-center justify-center rounded hover:bg-accent transition-colors">
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>
      )}

      {/* 主体网格 */}
      {mode === "day" && (
        <>
          <div className="grid grid-cols-7 gap-1">
            {t.components.weekdays.map((w) => (
              <div key={w} className="text-center text-[11px] font-medium text-muted-foreground pb-0.5">{w}</div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {dayCells.map((cell, i) => {
              if (cell === null) return <div key={i} className="aspect-square" />
              const bgClass = getPnlBg(cell.pnl, maxAbs)
              return (
                <div
                  key={i}
                  className={cn("aspect-square rounded flex flex-col items-center justify-center p-0.5 transition-colors", bgClass)}
                  title={cell.pnl !== null ? `${cell.date}: ${money(cell.pnl)}` : cell.date}
                >
                  <span className="text-[10px] leading-none opacity-70">{cell.day}</span>
                  {cell.pnl !== null && (
                    <span className="text-[9px] leading-tight tabular-nums font-medium mt-0.5">
                      {formatCompactPnl(cell.pnl, t.common.tenThousand)}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}

      {mode === "week" && (
        <div className="space-y-1.5">
          {weekRows.map((row) => (
            <div key={row.label} className="grid grid-cols-[2rem_1fr] items-center gap-1">
              <span className="text-[11px] text-muted-foreground text-right pr-1">{row.label}</span>
              <div className="grid grid-cols-5 gap-1">
                {row.weeks.map((w) => {
                  const bgClass = getPnlBg(w.pnl, maxAbs)
                  return (
                    <div
                      key={w.key}
                      className={cn("aspect-square rounded flex flex-col items-center justify-center p-0.5 transition-colors", bgClass)}
                      title={w.pnl !== null ? `${w.key}: ${money(w.pnl)}` : w.key}
                    >
                      <span className="text-[9px] leading-none opacity-70">{w.label}</span>
                      {w.pnl !== null && (
                        <span className="text-[9px] leading-tight tabular-nums font-medium mt-0.5">
                          {formatCompactPnl(w.pnl, t.common.tenThousand)}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {mode === "month" && (
        <div className="grid grid-cols-4 gap-2">
          {monthCells.map((c) => {
            const bgClass = getPnlBg(c.pnl, maxAbs)
            return (
              <div
                key={c.month}
                className={cn("rounded-lg flex flex-col items-center justify-center p-2 aspect-[4/3] transition-colors", bgClass)}
                title={c.pnl !== null ? `${viewYear}-${String(c.month + 1).padStart(2, "0")}: ${money(c.pnl)}` : undefined}
              >
                <span className="text-xs font-medium opacity-80">{c.label}</span>
                {c.pnl !== null && (
                  <span className="text-sm tabular-nums font-bold mt-1">{formatCompactPnl(c.pnl, t.common.tenThousand)}</span>
                )}
              </div>
            )
          })}
        </div>
      )}

      {mode === "year" && (
        <div className="flex flex-wrap gap-2 justify-center">
          {yearCells.map((c) => {
            const bgClass = getPnlBg(c.pnl, maxAbs)
            return (
              <div
                key={c.year}
                className={cn("rounded-lg flex flex-col items-center justify-center px-6 py-3 min-w-[110px] transition-colors", bgClass)}
                title={`${c.year}: ${money(c.pnl)}`}
              >
                <span className="text-sm font-bold opacity-80">{c.year}</span>
                <span className="text-base tabular-nums font-bold mt-1">{formatCompactPnl(c.pnl, t.common.tenThousand)}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
