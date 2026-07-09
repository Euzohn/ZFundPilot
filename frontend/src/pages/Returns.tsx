import { useState, useMemo, useEffect } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary, CurvePoint, ChannelPnLPoint, Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import { cn } from "@/lib/utils"
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart, Cell, ReferenceLine } from "recharts"
import PnLCalendar from "@/components/PnLCalendar"
import { ChevronUp, ChevronDown, BarChart3, CalendarDays } from "lucide-react"
import { getChannelColors, getChannelColorsAsync, getPalette } from "@/lib/channelColors"

const PALETTE = getPalette()
const CURVE_RANGE_DAYS: Record<string, number> = { "1m": 30, "3m": 90, "6m": 180, "1y": 365 }
const CURVE_RANGE_LABELS: Record<string, string> = { "1m": "1月", "3m": "3月", "6m": "6月", "1y": "1年", "all": "全部" }
const AGG_RANGE_DAYS: Record<string, number> = { "3m": 90, "6m": 180, "1y": 365 }
const AGG_RANGE_LABELS: Record<string, string> = { "3m": "3月", "6m": "6月", "1y": "1年", "all": "全部" }

function ChannelTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + p.value, 0)
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-2 text-xs shadow-sm">
      <p className="font-medium text-slate-700 mb-1">{label}</p>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-600">{p.dataKey}:</span>
          <span className={`font-medium tabular-nums ${p.value >= 0 ? "text-emerald-600" : "text-red-500"}`}>{signedMoney(p.value)}</span>
        </div>
      ))}
      <div className="mt-1 pt-1 border-t border-slate-100 flex justify-between">
        <span className="text-slate-500">合计</span>
        <span className={`font-bold tabular-nums ${total >= 0 ? "text-emerald-600" : "text-red-500"}`}>{signedMoney(total)}</span>
      </div>
    </div>
  )
}

export default function Returns() {
  const { data: summary, loading: sl } = useApi<PortfolioSummary>(() => api.getSummary())
  const { data: curve } = useApi<CurvePoint[]>(() => api.getPortfolioCurve())
  const { data: channelPnl } = useApi<ChannelPnLPoint[]>(() => api.getChannelPnl())
  const { data: positions } = useApi<Position[]>(() => api.getPositions())
  const [sortField, setSortField] = useState("return_rate")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [pnlMode, setPnlMode] = useState<"day" | "week" | "month" | "year">("day")
  const [pnlDays, setPnlDays] = useState(30)
  const [pnlAggRange, setPnlAggRange] = useState<"3m" | "6m" | "1y" | "all">("1y")
  const [chartView, setChartView] = useState<"bar" | "calendar">("bar")
  const [curveRange, setCurveRange] = useState<"1m" | "3m" | "6m" | "1y" | "all">("1y")
  const [channelColors, setChannelColors] = useState<Record<string, string>>(() => getChannelColors())

  useEffect(() => {
    getChannelColorsAsync().then(setChannelColors).catch(() => {})
  }, [])

  const openPositions = positions?.filter((p) => p.is_open) ?? []

  const toggleSort = (field: string) => {
    if (sortField === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else { setSortField(field); setSortDir("desc") }
  }

  const sortedPositions = useMemo(() => {
    return [...openPositions].sort((a, b) => {
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
  }, [openPositions, sortField, sortDir])

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

  // 按时间区间过滤组合曲线 + 计算累计收益
  const filteredCurve = useMemo(() => {
    if (!curve?.length) return []
    let data = curve
    if (curveRange !== "all") {
      const days = CURVE_RANGE_DAYS[curveRange]
      const d = new Date()
      d.setDate(d.getDate() - days)
      const cutoff = d.toISOString().slice(0, 10)
      data = curve.filter(p => p.date >= cutoff)
    }
    return data.map(p => ({ ...p, profit: Math.round((p.total_value - p.invested_cost) * 100) / 100 }))
  }, [curve, curveRange])

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
      const days = AGG_RANGE_DAYS[pnlAggRange]
      const d = new Date()
      d.setDate(d.getDate() - days)
      const cutoff = d.toISOString().slice(0, 10)
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
        key = monday.toISOString().slice(0, 10)
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

  if (sl || !summary) return <div className="flex min-h-[60vh] items-center justify-center"><LogoSpinner className="h-16 w-16" /></div>

  function SortHeader({ field, children, className }: { field: string; children: React.ReactNode; className?: string }) {
    const active = sortField === field
    return (
      <TableHead className={cn("cursor-pointer select-none", active ? "text-foreground" : "", className)} onClick={() => toggleSort(field)}>
        <span className="inline-flex items-center gap-1">
          {children}
          {active && (sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
        </span>
      </TableHead>
    )
  }

  // 汇总行
  const totals = {
    total_cost: openPositions.reduce((s, p) => s + p.total_cost, 0),
    market_value: openPositions.reduce((s, p) => s + p.market_value, 0),
    unrealized_pnl: openPositions.reduce((s, p) => s + p.unrealized_pnl, 0),
    realized_pnl: openPositions.reduce((s, p) => s + p.realized_pnl, 0),
    dividend_total: openPositions.reduce((s, p) => s + (p.dividend_total || 0), 0),
  }
  const totalRet = totals.total_cost ? totals.market_value / totals.total_cost - 1 : null

  // 收益率排序图数据
  const chartRows = openPositions
    .filter((p) => p.return_rate != null)
    .map((p) => ({ name: p.fund_name, rate: p.return_rate as number }))
    .sort((a, b) => b.rate - a.rate)

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">收益分析</h1>

      {/* Metrics — 详细指标，不与总览重复 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">持仓成本</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{money(summary.total_cost)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">浮动盈亏</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.unrealized_pnl)}`}>{signedMoney(summary.unrealized_pnl)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">已实现盈亏</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.realized_pnl)}`}>{signedMoney(summary.realized_pnl)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">累计买入 / 卖出 / 分红</p>
          <p className="mt-1 text-sm md:text-base font-bold tabular-nums">
            <span className="text-blue-600">{money(summary.total_buy)}</span>
            <span className="text-muted-foreground mx-1">/</span>
            <span className="text-amber-600">{money(summary.total_sell)}</span>
            <span className="text-muted-foreground mx-1">/</span>
            <span className="text-purple-600">{money(summary.total_dividend)}</span>
          </p>
        </CardContent></Card>
      </div>

      {/* P&L fluctuation chart — 日/周/月/年收益波动 */}
      {pnlData.length > 0 && (
        <Card className="card-hover">
          <CardHeader className="pb-2 flex-row items-center justify-between flex-wrap gap-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">收益波动</CardTitle>
            <div className="flex flex-wrap items-center gap-1">
              {([["day", "日"], ["week", "周"], ["month", "月"], ["year", "年"]] as const).map(([key, label]) => (
                <Button key={key} size="sm" variant={pnlMode === key ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                  onClick={() => { setPnlMode(key); if (key !== "day") setChartView("bar") }}>
                  {label}
                </Button>
              ))}
              {pnlMode === "day" && chartView === "bar" && (
                <>
                  <span className="text-muted-foreground mx-0.5">|</span>
                  {([7, 30, 90] as const).map((d) => (
                    <Button key={d} size="sm" variant={pnlDays === d ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                      onClick={() => setPnlDays(d)}>
                      {d}天
                    </Button>
                  ))}
                </>
              )}
              {pnlMode !== "day" && (
                <>
                  <span className="text-muted-foreground mx-0.5">|</span>
                  {(["3m", "6m", "1y", "all"] as const).map(r => (
                    <Button key={r} size="sm" variant={pnlAggRange === r ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                      onClick={() => setPnlAggRange(r)}>
                      {AGG_RANGE_LABELS[r]}
                    </Button>
                  ))}
                </>
              )}
              {pnlMode === "day" && (
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
              )}
            </div>
          </CardHeader>
          <CardContent>
            {pnlMode === "day" && chartView === "calendar" ? (
              <PnLCalendar data={dailyDiffs} />
            ) : (
              <ResponsiveContainer width="100%" height={pnlMode === "day" ? 200 : 240}>
                <BarChart data={pnlData} margin={{ left: 10, right: 10, top: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="date" fontSize={10} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v: number) => `${v >= 0 ? '+' : ''}${(v / 1000).toFixed(1)}k`} fontSize={10} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChannelTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke="#cbd5e1" />
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
          <CardTitle className="text-sm font-medium text-muted-foreground">组合收益曲线</CardTitle>
          <div className="flex items-center gap-1">
            {(["1m", "3m", "6m", "1y", "all"] as const).map(r => (
              <Button key={r} size="sm" variant={curveRange === r ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                onClick={() => setCurveRange(r)}>
                {CURVE_RANGE_LABELS[r]}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {filteredCurve.length >= 2 ? (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={filteredCurve} margin={{ left: 10, right: 5, top: 5 }}>
                <defs>
                  <linearGradient id="valueGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="value" tickFormatter={(v: number) => `¥${(v / 1000).toFixed(0)}k`} fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="return" orientation="right" tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                <Tooltip formatter={(value: number, name: string) => {
                  if (name === "累计收益率") return [`${(value * 100).toFixed(2)}%`, name]
                  return [money(value), name]
                }} labelStyle={{ color: '#1e293b' }} contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area yAxisId="value" type="monotone" dataKey="total_value" name="组合市值" stroke="#3B82F6" strokeWidth={2} fill="url(#valueGradient)" />
                <Line yAxisId="value" type="monotone" dataKey="invested_cost" name="累计净投入" stroke="#f59e0b" strokeWidth={2} dot={false} />
                <Line yAxisId="value" type="monotone" dataKey="profit" name="累计收益" stroke="#10b981" strokeWidth={2} dot={false} />
                <Line yAxisId="return" type="monotone" dataKey="total_return" name="累计收益率" stroke="#8b5cf6" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              净值历史不足，先到「净值更新」抓取数据后再查看曲线。
            </p>
          )}
        </CardContent>
      </Card>

      {/* Per-fund table */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">单基金收益明细</CardTitle></CardHeader>
        <CardContent>
          {openPositions.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无持仓数据</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <SortHeader field="fund_code">代码</SortHeader>
                  <SortHeader field="fund_name">名称</SortHeader>
                  <SortHeader field="channel">渠道</SortHeader>
                  <SortHeader field="total_cost" className="text-right">持仓成本</SortHeader>
                  <SortHeader field="market_value" className="text-right">当前市值</SortHeader>
                  <SortHeader field="unrealized_pnl" className="text-right">浮动盈亏</SortHeader>
                  <SortHeader field="return_rate" className="text-right">收益率</SortHeader>
                  <SortHeader field="realized_pnl" className="text-right">已实现</SortHeader>
                  <SortHeader field="dividend_total" className="text-right">分红</SortHeader>
                  <SortHeader field="weight" className="text-right">占比</SortHeader>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedPositions.map((p) => (
                  <TableRow key={`${p.fund_code}-${p.channel}`}>
                    <TableCell className="font-mono text-xs">{p.fund_code}</TableCell>
                    <TableCell className="font-medium">{p.fund_name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{p.channel || "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.total_cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.market_value)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</TableCell>
                    <TableCell className={`text-right tabular-nums font-medium ${pnlColor(p.return_rate)}`}>{pct(p.return_rate)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.realized_pnl)}`}>{money(p.realized_pnl)}</TableCell>
                    <TableCell className="text-right tabular-nums text-blue-600">{p.dividend_total ? money(p.dividend_total) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{pct(p.weight)}</TableCell>
                  </TableRow>
                ))}
                {/* 汇总行 */}
                <TableRow className="border-t-2 border-slate-200 bg-slate-50/50 font-medium">
                  <TableCell colSpan={3} className="text-sm">合计（{openPositions.length} 只）</TableCell>
                  <TableCell className="text-right tabular-nums">{money(totals.total_cost)}</TableCell>
                  <TableCell className="text-right tabular-nums">{money(totals.market_value)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${pnlColor(totals.unrealized_pnl)}`}>{money(totals.unrealized_pnl)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${pnlColor(totalRet)}`}>{pct(totalRet)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${pnlColor(totals.realized_pnl)}`}>{money(totals.realized_pnl)}</TableCell>
                  <TableCell className="text-right tabular-nums text-blue-600">{totals.dividend_total ? money(totals.dividend_total) : "—"}</TableCell>
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
          <CardHeader className="pb-2"><CardTitle className="text-base">浮动收益率排序</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={Math.max(200, chartRows.length * 36)}>
              <BarChart data={chartRows} layout="vertical" margin={{ left: 10, right: 40, top: 5 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                <XAxis type="number" tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`} fontSize={11} tick={{ fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={120} fontSize={11} tick={{ fill: "#64748b" }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v: number) => pct(v)} contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} />
                <ReferenceLine x={0} stroke="#cbd5e1" />
                <Bar dataKey="rate" radius={[0, 4, 4, 0]}>
                  {chartRows.map((row, i) => (
                    <Cell key={i} fill={row.rate >= 0 ? "#10b981" : "#ef4444"} />
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
