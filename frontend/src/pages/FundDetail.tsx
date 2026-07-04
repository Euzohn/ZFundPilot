import { useParams, useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Position, Transaction, Fund } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, signedMoney, navStr, pnlColor } from "@/lib/format"
import { toast } from "sonner"
import { ArrowLeft, TrendingUp, TrendingDown } from "lucide-react"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts"

const ACTION_LABELS: Record<string, string> = { buy: "买入", sell: "卖出" }

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card className="card-hover">
      <CardContent className="p-3 md:p-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={`mt-1 text-base md:text-lg font-bold tabular-nums ${color ?? ""}`}>{value}</p>
      </CardContent>
    </Card>
  )
}

export default function FundDetail() {
  const { code } = useParams<{ code: string }>()
  const navigate = useNavigate()

  const { data: fund, loading: fundLoading } = useApi<Fund>(() => api.getFund(code!), [code])
  const { data: positions } = useApi<Position[]>(() => api.getPositions(true), [])
  const { data: txs } = useApi<Transaction[]>(() =>
    api.getTransactionsByFund(code!).then((rows) =>
      rows.sort((a, b) => b.date.localeCompare(a.date) || (b.id ?? 0) - (a.id ?? 0)),
    ), [code])
  const { data: navHistory } = useApi<{ date: string; nav: number }[]>(
    () => api.getNavHistory(code!).then((rows) => rows.map((r) => ({ date: r.date, nav: r.nav }))),
    [code],
  )

  if (fundLoading) return <div className="py-20 text-center text-muted-foreground">加载中...</div>

  // 筛选该基金的所有持仓（跨渠道）
  const fundPositions = positions?.filter((p) => p.fund_code === code) ?? []
  const openPositions = fundPositions.filter((p) => p.is_open)

  // 汇总（跨渠道合并）
  const totalShares = openPositions.reduce((s, p) => s + p.held_shares, 0)
  const totalCost = openPositions.reduce((s, p) => s + p.total_cost, 0)
  const totalValue = openPositions.reduce((s, p) => s + p.market_value, 0)
  const totalUnrealized = openPositions.reduce((s, p) => s + p.unrealized_pnl, 0)
  const totalRealized = fundPositions.reduce((s, p) => s + p.realized_pnl, 0)
  const avgCost = totalShares > 0 ? totalCost / totalShares : null
  const latestNav = openPositions[0]?.latest_nav ?? null
  const returnRate = totalCost > 0 ? totalValue / totalCost - 1 : null

  // 交易日期查找表
  const txMap: Record<string, Transaction[]> = {}
  txs?.forEach(t => {
    if (!txMap[t.date]) txMap[t.date] = []
    txMap[t.date].push(t)
  })

  // 净值图表数据（最近 180 天），带上交易标记
  const chartData = navHistory
    ? [...navHistory]
        .sort((a, b) => a.date.localeCompare(b.date))
        .slice(-180)
        .map(d => ({ ...d, _tx: txMap[d.date] || null }))
    : []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="icon" onClick={() => navigate("/positions")} className="shrink-0">
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-xl md:text-2xl font-bold tracking-tight truncate">{fund?.fund_name ?? code}</h1>
            <span className="font-mono text-sm text-muted-foreground">{code}</span>
            {fund?.fund_type && <Badge variant="secondary">{fund.fund_type}</Badge>}
            {fund?.sector && <Badge variant="outline">{fund.sector}</Badge>}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            size="sm"
            variant="outline"
            className="text-gain border-gain/30 hover:bg-gain/5"
            onClick={() => navigate(`/transactions?code=${code}&action=buy`)}
          >
            <TrendingUp className="h-4 w-4" /> 买入
          </Button>
          {openPositions.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="text-loss border-loss/30 hover:bg-loss/5"
              onClick={() => navigate(`/transactions?code=${code}&action=sell`)}
            >
              <TrendingDown className="h-4 w-4" /> 卖出
            </Button>
          )}
        </div>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <MetricCard label="持有份额" value={totalShares.toFixed(2)} />
        <MetricCard label="持仓成本" value={money(totalCost)} />
        <MetricCard label="持仓均价" value={navStr(avgCost)} />
        <MetricCard label="最新净值" value={navStr(latestNav)} />
        <MetricCard label="当前市值" value={money(totalValue)} />
        <MetricCard label="浮动盈亏" value={signedMoney(totalUnrealized)} color={pnlColor(totalUnrealized)} />
        <MetricCard label="已实现盈亏" value={signedMoney(totalRealized)} color={pnlColor(totalRealized)} />
        <MetricCard label="收益率" value={pct(returnRate)} color={pnlColor(returnRate)} />
      </div>

      {/* 各渠道持仓 */}
      {openPositions.length > 1 && (
        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">各渠道持仓</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>渠道</TableHead>
                  <TableHead className="text-right">份额</TableHead>
                  <TableHead className="text-right">成本</TableHead>
                  <TableHead className="text-right">均价</TableHead>
                  <TableHead className="text-right">市值</TableHead>
                  <TableHead className="text-right">浮动盈亏</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openPositions.map((p) => (
                  <TableRow key={p.channel}>
                    <TableCell>{p.channel || "未标注"}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.held_shares.toFixed(2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.total_cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">{navStr(p.avg_cost_nav)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.market_value)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* NAV history chart */}
      <Card className="card-hover">
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">净值走势</CardTitle></CardHeader>
        <CardContent>
          {chartData.length >= 2 ? (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData} margin={{ left: 10, right: 10, top: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                <YAxis fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null
                    const d = payload[0].payload
                    const txInfo = d._tx as Transaction[] | null
                    return (
                      <div className="rounded-lg border bg-white px-3 py-2 shadow-lg">
                        <p className="text-xs font-medium text-muted-foreground">{label}</p>
                        <p className="text-sm font-bold tabular-nums text-primary">{navStr(d.nav)}</p>
                        {txInfo && txInfo.length > 0 && (
                          <div className="mt-1 space-y-0.5 border-t pt-1">
                            {txInfo.map((t, i) => (
                              <p key={i} className={`text-xs tabular-nums ${t.action === 'buy' ? 'text-gain' : 'text-loss'}`}>
                                {t.action === 'buy' ? '↑ 买入' : '↓ 卖出'}
                                {t.amount ? ` ${money(t.amount)}` : ''}
                                {t.shares ? ` ${t.shares.toFixed(2)} 份` : ''}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  }}
                />
                {avgCost && <ReferenceLine y={avgCost} stroke="#94a3b8" strokeDasharray="5 5" label={{ value: `均价 ${navStr(avgCost)}`, fontSize: 11, fill: '#94a3b8' }} />}
                <Line
                  type="monotone"
                  dataKey="nav"
                  stroke="#3B82F6"
                  strokeWidth={2}
                  dot={(props: any) => {
                    const { cx, cy, payload } = props
                    if (!payload?.date || cx == null || cy == null) return <g />
                    const txList: Transaction[] | null = payload._tx
                    if (!txList || txList.length === 0) return <g />
                    const hasBuy = txList.some(t => t.action === 'buy')
                    const hasSell = txList.some(t => t.action === 'sell')
                    const both = hasBuy && hasSell
                    return (
                      <g>
                        {hasBuy && (
                          <circle cx={both ? cx - 3 : cx} cy={cy} r={4} fill="#16a34a" stroke="#fff" strokeWidth={2} />
                        )}
                        {hasSell && (
                          <circle cx={both ? cx + 3 : cx} cy={cy} r={4} fill="#dc2626" stroke="#fff" strokeWidth={2} />
                        )}
                      </g>
                    )
                  }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">净值历史不足，先到「净值更新」抓取数据。</p>
          )}
        </CardContent>
      </Card>

      {/* Transaction history */}
      <Card className="card-hover">
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">交易记录</CardTitle></CardHeader>
        <CardContent>
          {!txs || txs.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无交易记录</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日期</TableHead>
                  <TableHead>操作</TableHead>
                  <TableHead>渠道</TableHead>
                  <TableHead className="text-right">金额</TableHead>
                  <TableHead className="text-right">份额</TableHead>
                  <TableHead className="text-right">净值</TableHead>
                  <TableHead className="text-right">手续费</TableHead>
                  <TableHead>备注</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {txs.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell>{t.date}</TableCell>
                    <TableCell>
                      <Badge variant={t.action === "buy" ? "success" : "destructive"}>
                        {ACTION_LABELS[t.action] ?? t.action}
                      </Badge>
                    </TableCell>
                    <TableCell>{t.channel || "未标注"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.amount ? money(t.amount) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.shares?.toFixed(2) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.nav?.toFixed(4) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.fee || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{t.note}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {txs && txs.length > 0 && <p className="mt-3 text-sm text-muted-foreground">共 {txs.length} 笔交易</p>}
        </CardContent>
      </Card>
    </div>
  )
}
