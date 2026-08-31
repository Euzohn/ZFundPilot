import { useState, useMemo, useEffect } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary, CurvePoint, BenchmarkPoint, ChannelPnLPoint, Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import ErrorState from "@/components/ErrorState"
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { money, pct, signedMoney, pnlColor, localDateStr } from "@/lib/format"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { cn } from "@/lib/utils"
import { BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, ComposedChart, Cell, ReferenceLine } from "recharts"
import PnLCalendar from "@/components/PnLCalendar"
import TpSlAlertsPanel from "@/components/TpSlAlertsPanel"
import { BarChart3, CalendarDays } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { getChannelColors, getChannelColorsAsync, getPalette } from "@/lib/channelColors"
import { RANGE_DAYS } from "@/lib/rangeLabels"
import { makeSortHeader } from "@/components/SortHeader"
import { useLang } from "@/i18n/LanguageContext"
import { CHART_COLORS } from "@/lib/chartPalette"

const PALETTE = getPalette()

const BENCHMARK_DEFS = [
  { code: "000300", labelKey: "benchmarkHS300" as const, color: CHART_COLORS[1] },
  { code: "000001", labelKey: "benchmarkSSE" as const, color: CHART_COLORS[2] },
  { code: "399006", labelKey: "benchmarkGEM" as const, color: CHART_COLORS[5] },
]

function ChannelTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number; color: string }[]; label?: string }) {
  const { t } = useLang()
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + p.value, 0)
  return (
    <div className="bg-card rounded-lg border border-border p-2 text-xs shadow-sm">
      <p className="font-medium text-foreground mb-1">{label}</p>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.dataKey}:</span>
          <span className={`font-medium tabular-nums ${p.value >= 0 ? "text-gain" : "text-loss"}`}>{signedMoney(p.value)}</span>
        </div>
      ))}
      <div className="mt-1 pt-1 border-t border-border flex justify-between">
        <span className="text-muted-foreground">{t.common.total}</span>
        <span className={`font-bold tabular-nums ${total >= 0 ? "text-gain" : "text-loss"}`}>{signedMoney(total)}</span>
      </div>
    </div>
  )
}

export default function Returns() {
  const { data: summary, loading: sl, error: se, reload: reloadSummary } = useApi<PortfolioSummary>(() => api.getSummary())
  const { data: curve, loading: curveLoading } = useApi<CurvePoint[]>(() => api.getPortfolioCurve())
  const { data: channelPnl, loading: channelPnlLoading } = useApi<ChannelPnLPoint[]>(() => api.getChannelPnl())
  const { data: positions, loading: positionsLoading } = useApi<Position[]>(() => api.getPositions(true))
  const [sortField, setSortField] = useState("return_rate")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [pnlMode, setPnlMode] = useState<"day" | "week" | "month" | "year">("day")
  const [pnlDays, setPnlDays] = useState(30)
  const [pnlAggRange, setPnlAggRange] = useState<"3m" | "6m" | "1y" | "all">("1y")
  const [chartView, setChartView] = useState<"bar" | "calendar">("bar")
  const [curveRange, setCurveRange] = useState<"1m" | "3m" | "6m" | "1y" | "all">("1y")
  const [channelColors, setChannelColors] = useState<Record<string, string>>(() => getChannelColors())
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set())
  const [benchmarks, setBenchmarks] = useState<Set<string>>(new Set(["000300"]))
  const [benchmarkData, setBenchmarkData] = useState<BenchmarkPoint[] | null>(null)
  const { t } = useLang()

  const toggleLegend = (e: { dataKey?: unknown; value?: unknown }) => {
    const key = String(e.dataKey || e.value)
    setHiddenKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const toggleBenchmark = (code: string) => {
    setBenchmarks(prev => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  useEffect(() => {
    if (benchmarks.size === 0) { setBenchmarkData(null); return }
    let active = true
    api.getPortfolioBenchmark([...benchmarks])
      .then(data => { if (active) setBenchmarkData(data) })
      .catch(() => { if (active) setBenchmarkData(null) })
    return () => { active = false }
  }, [benchmarks])

  useEffect(() => {
    getChannelColorsAsync().then(setChannelColors).catch(() => {})
  }, [])

  const openPositions = positions?.filter((p) => p.is_open) ?? []
  const allPositions = positions ?? []
  const closedCount = allPositions.length - openPositions.length

  const toggleSort = (field: string) => {
    if (sortField === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else { setSortField(field); setSortDir("desc") }
  }

  const sortedPositions = useMemo(() => {
    return [...allPositions].sort((a, b) => {
      const getVal = (p: Position): number | string => {
        switch (sortField) {
          case "fund_code": return p.fund_code
          case "fund_name": return p.fund_name
          case "channel": return p.channel || ""
          case "total_cost": return p.total_cost
          case "market_value": return p.market_value
          case "unrealized_pnl": return p.unrealized_pnl
          case "return_rate": return p.return_rate ?? -999
          case "realized_pnl": return p.realized_pnl
          case "dividend_total": return p.dividend_total
          case "weight": return p.weight
          default: return 0
        }
      }
      const va = getVal(a)
      const vb = getVal(b)
      const cmp = typeof va === "string" && typeof vb === "string" ? va.localeCompare(vb) : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [allPositions, sortField, sortDir])

  // 从 curve 计算每日 diff（供日历视图用）
  const dailyDiffs = useMemo(() => {
    if (!curve || curve.length < 2) return []
    const data: { date: string; pnl: number }[] = []
    for (let i = 1; i < curve.length; i++) {
      const diff = (curve[i].total_value - curve[i - 1].total_value)
                 - (curve[i].invested_cost - curve[i - 1].invested_cost)
      data.push({ date: curve[i].date, pnl: Math.round(diff * 100) / 100 })
    }
    return data
  }, [curve])

  // 按时间区间过滤组合曲线 + 计算累计收益 + 合并基准数据
  const filteredCurve = useMemo(() => {
    if (!curve?.length) return []
    let data = curve
    if (curveRange !== "all") {
      const days = RANGE_DAYS[curveRange]
      const d = new Date()
      d.setDate(d.getDate() - days)
      const cutoff = localDateStr(d)
      data = curve.filter(p => p.date >= cutoff)
    }
    // 基准数据按日期建 Map
    const benchMap = new Map<string, Record<string, number>>()
    if (benchmarkData) {
      for (const bp of benchmarkData) {
        const row: Record<string, number> = {}
        for (const key of Object.keys(bp)) {
          if (key !== "date" && typeof bp[key] === "number") {
            row[key] = bp[key] as number
          }
        }
        benchMap.set(bp.date, row)
      }
    }
    return data.map(p => {
      const row: Record<string, string | number> = { ...p, profit: Math.round((p.total_value - p.invested_cost) * 100) / 100 }
      const bench = benchMap.get(p.date)
      if (bench) Object.assign(row, bench)
      return row
    })
  }, [curve, curveRange, benchmarkData])

  const channels = useMemo(() => {
    if (!channelPnl?.length) return []
    const set = new Set<string>()
    for (const d of channelPnl) {
      for (const k of Object.keys(d)) {
        if (k !== "date") set.add(k)
      }
    }
    return [...set].sort()
  }, [channelPnl])

  // 按模式聚合收益波动数据（按渠道拆分，用于堆叠柱状图）
  const pnlData = useMemo(() => {
    if (!channelPnl?.length || channels.length === 0) return []

    if (pnlMode === "day") {
      return channelPnl.slice(-pnlDays)
    }

    // 周/月/年聚合 — 先按区间过滤
    let filtered = channelPnl
    if (pnlAggRange !== "all") {
      const days = RANGE_DAYS[pnlAggRange]
      const d = new Date()
      d.setDate(d.getDate() - days)
      const cutoff = localDateStr(d)
      filtered = channelPnl.filter(p => p.date >= cutoff)
    }

    const buckets: Record<string, Record<string, string | number>> = {}
    for (const d of filtered) {
      const dt = new Date(d.date + "T00:00:00")
      let key: string, label: string

      if (pnlMode === "week") {
        const day = dt.getDay() || 7
        const monday = new Date(dt)
        monday.setDate(dt.getDate() - day + 1)
        key = localDateStr(monday)
        label = `${monday.getMonth() + 1}/${monday.getDate()}`
      } else if (pnlMode === "month") {
        key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`
        label = `${dt.getFullYear()}/${dt.getMonth() + 1}`
      } else {
        key = String(dt.getFullYear())
        label = String(dt.getFullYear())
      }

      if (!buckets[key]) {
        buckets[key] = { label, sortKey: key }
        for (const ch of channels) buckets[key][ch] = 0
      }
      for (const ch of channels) {
        buckets[key][ch] = Math.round((Number(buckets[key][ch]) + Number(d[ch] || 0)) * 100) / 100
      }
    }

    return Object.values(buckets)
      .sort((a, b) => String(a.sortKey).localeCompare(String(b.sortKey)))
      .map(({ label, sortKey, ...rest }) => ({ date: String(label), ...rest }))
  }, [channelPnl, channels, pnlMode, pnlDays, pnlAggRange])

  if (se) return <ErrorState message={se} onRetry={reloadSummary} />
  if (sl || !summary) return <LoadingState />

  const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })

  // 汇总行
  const totals = {
    total_cost: openPositions.reduce((s, p) => s + p.total_cost, 0),
    market_value: openPositions.reduce((s, p) => s + p.market_value, 0),
    unrealized_pnl: openPositions.reduce((s, p) => s + p.unrealized_pnl, 0),
    realized_pnl: allPositions.reduce((s, p) => s + p.realized_pnl, 0),
    dividend_total: allPositions.reduce((s, p) => s + (p.dividend_total || 0), 0),
  }
  const totalRet = totals.total_cost ? totals.market_value / totals.total_cost - 1 : null

  // 收益率排序图数据
  const chartRows = openPositions
    .filter((p) => p.return_rate != null)
    .map((p) => ({ name: p.fund_name, rate: p.return_rate as number }))
    .sort((a, b) => b.rate - a.rate)

  return (
    <div className="space-y-6">
      <PageHeader title={t.returns.title} />

      {/* Metrics — 详细指标，不与总览重复 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">{t.returns.holdingCost}</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{money(summary.total_cost)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">{t.returns.unrealizedPnl}</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.unrealized_pnl)}`}>{signedMoney(summary.unrealized_pnl)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">{t.returns.realizedPnl}</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.realized_pnl)}`}>{signedMoney(summary.realized_pnl)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">{t.returns.buySellDividend}</p>
          <p className="mt-1 text-sm md:text-base font-bold tabular-nums">
            <span className="text-primary">{money(summary.total_buy)}</span>
            <span className="text-muted-foreground mx-1">/</span>
            <span className="text-warning">{money(summary.total_sell)}</span>
            <span className="text-muted-foreground mx-1">/</span>
            <span className="text-info">{money(summary.total_dividend)}</span>
          </p>
        </CardContent></Card>
      </div>

      {/* TP/SL Alerts */}
      <TpSlAlertsPanel />

      {/* P&L fluctuation chart — 日/周/月/年收益波动 */}
      {channelPnlLoading ? <LoadingState size="sm" className="py-4" /> : pnlData.length > 0 && (
        <Card className="card-hover">
          <CardHeader className="pb-2 flex-row items-center justify-between flex-wrap gap-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.returns.pnlFluctuation}</CardTitle>
            <div className="flex flex-wrap items-center gap-1">
              {([["day", t.returns.day], ["week", t.returns.week], ["month", t.returns.month], ["year", t.returns.year]] as const).map(([key, label]) => (
                <Button key={key} size="sm" variant={pnlMode === key ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                  onClick={() => setPnlMode(key)}>
                  {label}
                </Button>
              ))}
              {pnlMode === "day" && chartView === "bar" && (
                <>
                  <span className="text-muted-foreground mx-0.5">|</span>
                  {([7, 30, 90] as const).map((d) => (
                    <Button key={d} size="sm" variant={pnlDays === d ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                      onClick={() => setPnlDays(d)}>
                      {`${d}${t.returns.daysSuffix}`}
                    </Button>
                  ))}
                </>
              )}
              {pnlMode !== "day" && chartView === "bar" && (
                <>
                  <span className="text-muted-foreground mx-0.5">|</span>
                  {(["3m", "6m", "1y", "all"] as const).map(r => (
                    <Button key={r} size="sm" variant={pnlAggRange === r ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                      onClick={() => setPnlAggRange(r)}>
                      {t.rangeLabels[r as keyof typeof t.rangeLabels] ?? r}
                    </Button>
                  ))}
                </>
              )}
              <>
                <span className="text-muted-foreground mx-0.5">|</span>
                <Button size="sm" variant={chartView === "bar" ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                  onClick={() => setChartView("bar")}>
                  <BarChart3 className="h-3 w-3" />
                </Button>
                <Button size="sm" variant={chartView === "calendar" ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                  onClick={() => setChartView("calendar")}>
                  <CalendarDays className="h-3 w-3" />
                </Button>
              </>
            </div>
          </CardHeader>
          <CardContent>
            {chartView === "calendar" ? (
              <PnLCalendar data={dailyDiffs} mode={pnlMode} />
            ) : (
              <ResponsiveContainer width="100%" height={pnlMode === "day" ? 200 : 240}>
                <BarChart data={pnlData} margin={{ left: 10, right: 10, top: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" fontSize={10} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v: number) => `${v >= 0 ? '+' : ''}${(v / 1000).toFixed(1)}k`} fontSize={10} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChannelTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke="hsl(var(--border))" />
                  {channels.map((ch, i) => (
                    <Bar key={ch} dataKey={ch} stackId="a" fill={channelColors[ch] ?? PALETTE[i % PALETTE.length]} radius={i === channels.length - 1 ? [3, 3, 0, 0] : undefined} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      )}

      {/* Portfolio curve */}
      <Card className="card-hover">
        <CardHeader className="pb-2 flex-row items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.returns.portfolioCurve}</CardTitle>
            <div className="flex items-center gap-1">
              {BENCHMARK_DEFS.map(bd => {
                const active = benchmarks.has(bd.code)
                return (
                  <button
                    key={bd.code}
                    type="button"
                    onClick={() => toggleBenchmark(bd.code)}
                    className={cn(
                      "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                      active
                        ? "border-border bg-background text-foreground"
                        : "border-transparent text-muted-foreground/50 hover:text-muted-foreground"
                    )}
                  >
                    <span className="inline-block w-2 h-2 rounded-full" style={{ background: active ? bd.color : "currentColor" }} />
                    {t.returns[bd.labelKey]}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="flex items-center gap-1">
            {(["1m", "3m", "6m", "1y", "all"] as const).map(r => (
              <Button key={r} size="sm" variant={curveRange === r ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                onClick={() => setCurveRange(r)}>
                {t.rangeLabels[r as keyof typeof t.rangeLabels] ?? r}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {curveLoading ? <LoadingState size="sm" /> : filteredCurve.length >= 2 ? (
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={filteredCurve} margin={{ left: 10, right: 5, top: 5 }}>
                <defs>
                  <linearGradient id="valueGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="value" tickFormatter={(v: number) => `¥${(v / 1000).toFixed(0)}k`} fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="return" orientation="right" tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                <Tooltip formatter={(value: number, name: string) => {
                  const benchLabels = BENCHMARK_DEFS.map(bd => t.returns[bd.labelKey])
                  if (name === t.returns.totalReturnRate || benchLabels.includes(name)) return [`${(value * 100).toFixed(2)}%`, name]
                  return [money(value), name]
                }} labelStyle={{ color: 'hsl(var(--foreground))' }} contentStyle={{ background: "hsl(var(--card))", borderRadius: 8, border: '1px solid hsl(var(--border))' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} onClick={toggleLegend} />
                <Area yAxisId="value" type="monotone" dataKey="total_value" name={t.returns.portfolioValue} stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#valueGradient)" hide={hiddenKeys.has("total_value")} />
                <Line yAxisId="value" type="monotone" dataKey="invested_cost" name={t.returns.investedCost} stroke="hsl(var(--chart-4))" strokeWidth={2} dot={false} hide={hiddenKeys.has("invested_cost")} />
                <Line yAxisId="value" type="monotone" dataKey="profit" name={t.returns.totalReturn} stroke="var(--gain-500)" strokeWidth={2} dot={false} hide={hiddenKeys.has("profit")} />
                <Line yAxisId="return" type="monotone" dataKey="total_return" name={t.returns.totalReturnRate} stroke="hsl(var(--chart-5))" strokeWidth={2} dot={false} hide={hiddenKeys.has("total_return")} />
                {BENCHMARK_DEFS.filter(bd => benchmarks.has(bd.code)).map(bd => (
                  <Line key={bd.code} yAxisId="return" type="monotone" dataKey={bd.code} name={t.returns[bd.labelKey]} stroke={bd.color} strokeWidth={1.5} strokeDasharray="5 5" dot={false} connectNulls hide={hiddenKeys.has(bd.code)} />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              {t.returns.curveNoDataHint}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Per-fund table */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">{t.returns.perFundDetail}</CardTitle></CardHeader>
        <CardContent>
          {positionsLoading ? <LoadingState size="sm" /> : allPositions.length === 0 ? (
            <EmptyState title={t.returns.noPositions} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <SortHeader field="fund_code">{t.common.code}</SortHeader>
                  <SortHeader field="fund_name">{t.common.name}</SortHeader>
                  <SortHeader field="channel">{t.common.channel}</SortHeader>
                  <SortHeader field="total_cost" className="text-right">{t.returns.holdingCost}</SortHeader>
                  <SortHeader field="market_value" className="text-right">{t.returns.currentValue}</SortHeader>
                  <SortHeader field="unrealized_pnl" className="text-right">{t.returns.unrealizedPnl}</SortHeader>
                  <SortHeader field="return_rate" className="text-right">{t.returns.return}</SortHeader>
                  <SortHeader field="realized_pnl" className="text-right">{t.returns.realized}</SortHeader>
                  <SortHeader field="dividend_total" className="text-right">{t.actionLabels.dividend}</SortHeader>
                  <SortHeader field="weight" className="text-right">{t.returns.weight}</SortHeader>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedPositions.map((p) => (
                  <TableRow key={`${p.fund_code}-${p.channel}`} className={cn(!p.is_open && "opacity-60")}>
                    <TableCell className="font-mono text-xs">{p.fund_code}</TableCell>
                    <TableCell className="font-medium">
                      <span className="flex items-center gap-1.5">
                        {p.fund_name}
                        {!p.is_open && <Badge variant="secondary" className="text-[10px] px-1 py-0 h-4">{t.returns.closed}</Badge>}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{p.channel || "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.total_cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.market_value)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</TableCell>
                    <TableCell className={`text-right tabular-nums font-medium ${pnlColor(p.return_rate)}`}>{pct(p.return_rate)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.realized_pnl)}`}>{money(p.realized_pnl)}</TableCell>
                    <TableCell className="text-right tabular-nums text-primary">{p.dividend_total ? money(p.dividend_total) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{pct(p.weight)}</TableCell>
                  </TableRow>
                ))}
                {/* 汇总行 */}
                <TableRow className="border-t-2 border-border bg-muted/50 font-medium">
                  <TableCell colSpan={3} className="text-sm">
                    {closedCount > 0
                      ? t.returns.totalSummaryWithClosed.replace("{n}", String(openPositions.length)).replace("{m}", String(closedCount))
                      : t.returns.totalSummary.replace("{n}", String(openPositions.length))}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{money(totals.total_cost)}</TableCell>
                  <TableCell className="text-right tabular-nums">{money(totals.market_value)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${pnlColor(totals.unrealized_pnl)}`}>{money(totals.unrealized_pnl)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${pnlColor(totalRet)}`}>{pct(totalRet)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${pnlColor(totals.realized_pnl)}`}>{money(totals.realized_pnl)}</TableCell>
                  <TableCell className="text-right tabular-nums text-primary">{totals.dividend_total ? money(totals.dividend_total) : "—"}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">100%</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Return ranking — horizontal bar chart with color coding */}
      {chartRows.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">{t.returns.returnRanking}</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={Math.max(200, chartRows.length * 36)}>
              <BarChart data={chartRows} layout="vertical" margin={{ left: 10, right: 40, top: 5 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" />
                <XAxis type="number" tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`} fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={140} fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} tickFormatter={(name: string) => name.length > 8 ? name.slice(0, 8) + '…' : name} />
                <Tooltip formatter={(v: number) => pct(v)} labelStyle={{ color: 'hsl(var(--foreground))' }} itemStyle={{ color: 'hsl(var(--foreground))' }} contentStyle={{ background: "hsl(var(--card))", borderRadius: 8, border: '1px solid hsl(var(--border))' }} />
                <ReferenceLine x={0} stroke="hsl(var(--border))" />
                <Bar dataKey="rate" radius={[0, 4, 4, 0]}>
                  {chartRows.map((row, i) => (
                    <Cell key={i} fill={row.rate >= 0 ? "var(--gain-500)" : "var(--loss-500)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
