import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary, CurvePoint, Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart } from "recharts"
import { TrendingUp } from "lucide-react"

export default function Returns() {
  const { data: summary, loading: sl } = useApi<PortfolioSummary>(() => api.getSummary())
  const { data: curve } = useApi<CurvePoint[]>(() => api.getPortfolioCurve())
  const { data: positions } = useApi<Position[]>(() => api.getPositions())

  if (sl || !summary) return <div className="py-20 text-center text-muted-foreground">加载中...</div>

  const openPositions = positions?.filter((p) => p.is_open) ?? []
  const chartRows = openPositions
    .filter((p) => p.return_rate != null)
    .map((p) => ({ name: `${p.fund_name}·${p.channel || "未标注"}`, 收益率: p.return_rate as number }))
    .sort((a, b) => a.收益率 - b.收益率)

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">收益分析</h1>

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <Card className="card-hover"><CardContent className="p-4 md:p-5">
          <p className="text-xs font-medium text-muted-foreground">当前市值</p>
          <p className="mt-1 text-lg md:text-xl font-bold tabular-nums">{money(summary.total_value)}</p>
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
          <p className="text-xs font-medium text-muted-foreground">总收益率</p>
          <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${pnlColor(summary.total_return)}`}>{pct(summary.total_return)}</p>
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
        <CardHeader><CardTitle className="text-base">单基金收益明细</CardTitle></CardHeader>
        <CardContent>
          {openPositions.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无持仓数据</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>代码</TableHead><TableHead>名称</TableHead><TableHead>渠道</TableHead>
                  <TableHead className="text-right">持仓成本</TableHead>
                  <TableHead className="text-right">当前市值</TableHead>
                  <TableHead className="text-right">浮动盈亏</TableHead>
                  <TableHead className="text-right">收益率</TableHead>
                  <TableHead className="text-right">已实现</TableHead>
                  <TableHead className="text-right">占比</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openPositions.map((p) => (
                  <TableRow key={`${p.fund_code}-${p.channel}`}>
                    <TableCell className="font-mono text-xs">{p.fund_code}</TableCell>
                    <TableCell className="font-medium">{p.fund_name}</TableCell>
                    <TableCell>{p.channel || "未标注"}</TableCell>
                    <TableCell className="text-right">{money(p.total_cost)}</TableCell>
                    <TableCell className="text-right">{money(p.market_value)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(p.return_rate)}`}>{pct(p.return_rate)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(p.realized_pnl)}`}>{money(p.realized_pnl)}</TableCell>
                    <TableCell className="text-right">{pct(p.weight)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Return ranking */}
      {chartRows.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">浮动收益率排序</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={Math.max(200, chartRows.length * 36)}>
              <LineChart data={chartRows} layout="vertical" margin={{ left: 80 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`} fontSize={11} />
                <YAxis type="category" dataKey="name" width={140} fontSize={11} tick={{ fill: "#64748b" }} />
                <Tooltip formatter={(v: number) => pct(v)} />
                <Line type="monotone" dataKey="收益率" stroke="#3b82f6" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
