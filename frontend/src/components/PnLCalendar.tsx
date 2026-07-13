import { useState, useMemo } from "react"
import { money } from "@/lib/format"
import { cn } from "@/lib/utils"
import { ChevronLeft, ChevronRight } from "lucide-react"

interface PnlDay {
  date: string
  pnl: number
}

interface Props {
  data: PnlDay[]
}

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"]

function getPnlBg(pnl: number | null, maxAbs: number): string {
  if (pnl === null || pnl === 0) return "bg-slate-50/60"
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

export default function PnLCalendar({ data }: Props) {
  const pnlMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const d of data) m[d.date] = d.pnl
    return m
  }, [data])

  const maxAbs = useMemo(() => {
    if (data.length === 0) return 1
    return Math.max(...data.map((d) => Math.abs(d.pnl)), 1)
  }, [data])

  // 默认显示最近有数据的月份
  const [viewYear, setViewYear] = useState(() => {
    if (data.length > 0) {
      const last = new Date(data[data.length - 1].date + "T00:00:00")
      return last.getFullYear()
    }
    return new Date().getFullYear()
  })
  const [viewMonth, setViewMonth] = useState(() => {
    if (data.length > 0) {
      const last = new Date(data[data.length - 1].date + "T00:00:00")
      return last.getMonth()
    }
    return new Date().getMonth()
  })

  const monthLabel = `${viewYear}年${viewMonth + 1}月`

  // 生成日历网格
  const cells = useMemo(() => {
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

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear((y) => y - 1) }
    else setViewMonth((m) => m - 1)
  }
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear((y) => y + 1) }
    else setViewMonth((m) => m + 1)
  }

  // 当月汇总
  const monthPnls = cells.filter((c): c is { date: string; day: number; pnl: number } => c !== null && c.pnl !== null)
  const monthSum = monthPnls.reduce((s, c) => s + (c.pnl || 0), 0)
  const monthDays = monthPnls.length
  const winDays = monthPnls.filter((c) => c.pnl > 0).length

  return (
    <div className="space-y-3">
      {/* Month navigation */}
      <div className="flex items-center justify-between">
        <button onClick={prevMonth} className="flex h-7 w-7 items-center justify-center rounded hover:bg-slate-100 transition-colors">
          <ChevronLeft className="h-4 w-4 text-muted-foreground" />
        </button>
        <div className="text-center">
          <span className="text-sm font-medium">{monthLabel}</span>
          {monthDays > 0 && (
            <span className="ml-2 text-xs text-muted-foreground">
              <span className={monthSum >= 0 ? "text-gain" : "text-loss"}>{money(monthSum)}</span>
              {" · "}盈{winDays}天 亏{monthDays - winDays}天
            </span>
          )}
        </div>
        <button onClick={nextMonth} className="flex h-7 w-7 items-center justify-center rounded hover:bg-slate-100 transition-colors">
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </button>
      </div>

      {/* Weekday headers */}
      <div className="grid grid-cols-7 gap-1">
        {WEEKDAYS.map((w) => (
          <div key={w} className="text-center text-[11px] font-medium text-muted-foreground pb-0.5">{w}</div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1">
        {cells.map((cell, i) => {
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
                  {cell.pnl >= 0 ? "+" : ""}{Math.abs(cell.pnl) >= 10000
                    ? `${(cell.pnl / 10000).toFixed(1)}万`
                    : Math.abs(cell.pnl) >= 1000
                      ? `${(cell.pnl / 1000).toFixed(1)}k`
                      : cell.pnl.toFixed(0)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
