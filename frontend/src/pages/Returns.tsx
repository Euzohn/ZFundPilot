import { useState, useMemo } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary, CurvePoint, Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import { cn } from "@/lib/utils"
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart, Cell, ReferenceLine } from "recharts"
import { ChevronUp, ChevronDown } from "lucide-react"

export default function Returns() {
  const { data: summary, loading: sl } = useApi<PortfolioSummary>(() => api.getSummary())
  const { data: curve } = useApi<CurvePoint[]>(() => api.getPortfolioCurve())
  const { data: positions } = useApi<Position[]>(() => api.getPositions())
  const [sortField, setSortField] = useState("return_rate")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

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

  if (sl || !summary) return <div className="py-20 text-center text-muted-foreground">加载中...</div>

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

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 md:gap-4">
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">当前市值</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{money(summary.total_value)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">持仓成本</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{money(summary.total_cost)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">总盈亏</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.total_pnl)}`}>{signedMoney(summary.total_pnl)}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">浮动 {signedMoney(summary.unrealized_pnl)} · 已实现 {signedMoney(summary.realized_pnl)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">总收益率</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.total_return)}`}>{pct(summary.total_return)}</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">持仓基金数</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{summary.holding_count} 只</p>
        </CardContent></Card>
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">最大单基金占比</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{pct(summary.max_single_weight)}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground truncate">{summary.max_single_name}</p>
        </CardContent></Card>
      </div>

      {/* Portfolio curve */}
      <Card className="card-hover">
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">组合收益曲线</CardTitle></CardHeader>
        <CardContent>
          {curve && curve.length >= 2 ? (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={curve} margin={{ left: 10, right: 10, top: 5 }}>
                <defs>
                  <linearGradient id="valueGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v: number) => `¥${(v / 1000).toFixed(0)}k`} fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v: number) => money(v)} labelStyle={{ color: '#1e293b' }} contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="total_value" name="组合市值" stroke="#3B82F6" strokeWidth={2} fill="url(#valueGradient)" />
                <Line type="monotone" dataKey="invested_cost" name="累计净投入" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="5 5" dot={false} />
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
