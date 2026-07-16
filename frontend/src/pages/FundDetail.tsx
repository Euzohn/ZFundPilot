import { useState, useMemo, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Position, Transaction, Fund, FundEstimate } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, signedMoney, navStr, pnlColor, localDateStr } from "@/lib/format"
import { toast } from "sonner"
import { ArrowLeft, TrendingUp, TrendingDown, Pencil, Trash2 } from "lucide-react"
import { ComposedChart, Line, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts"

const ACTION_LABELS: Record<string, string> = { buy: "买入", sell: "卖出", dividend: "分红", reinvest: "再投资" }
const RANGE_DAYS: Record<string, number> = { "1m": 30, "3m": 90, "6m": 180, "1y": 365 }
const RANGE_LABELS: Record<string, string> = { "1m": "1月", "3m": "3月", "6m": "6月", "1y": "1年", "hold": "持仓至今" }

function MetricCard({ label, value, color, sub, subColor }: { label: string; value: string; color?: string; sub?: string; subColor?: string }) {
  return (
    <Card className="card-hover">
      <CardContent className="p-3 md:p-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={`mt-1 text-base md:text-lg font-bold tabular-nums ${color ?? ""}`}>{value}</p>
        {sub && <p className={`text-xs ${subColor ?? "text-muted-foreground"}`}>{sub}</p>}
      </CardContent>
    </Card>
  )
}

export default function FundDetail() {
  const { code } = useParams<{ code: string }>()
  const navigate = useNavigate()
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [navRange, setNavRange] = useState<"1m" | "3m" | "6m" | "1y" | "hold">("1y")

  const { data: fund, loading: fundLoading, error: fundError, reload: reloadFund } = useApi<Fund>(() => api.getFund(code!), [code])
  const { data: positions } = useApi<Position[]>(() => api.getPositions(true), [])
  const { data: txs, reload: reloadTxs } = useApi<Transaction[]>(() =>
    api.getTransactionsByFund(code!).then((rows) =>
      rows.sort((a, b) => b.date.localeCompare(a.date) || (b.id ?? 0) - (a.id ?? 0)),
    ), [code])
  const { data: navHistory } = useApi<{ date: string; nav: number }[]>(
    () => api.getNavHistory(code!).then((rows) => rows.map((r) => ({ date: r.date, nav: r.nav }))),
    [code],
  )
  const { data: fundEstimate, reload: reloadEstimate } = useApi<FundEstimate>(() => api.getFundEstimate(code!), [code])
  useEffect(() => {
    const interval = setInterval(reloadEstimate, 60000)
    return () => clearInterval(interval)
  }, [reloadEstimate])

  // 净值图表数据：时间区间过滤 + 每日收益计算（必须在 early return 之前）
  const chartData = useMemo(() => {
    if (!navHistory?.length) return []
    const sorted = [...navHistory].sort((a, b) => a.date.localeCompare(b.date))

    // 时间区间过滤
    let cutoff: string | null = null
    if (navRange === "hold") {
      if (txs?.length) {
        cutoff = [...txs].map(t => t.date).sort()[0]
      }
    } else {
      const days = RANGE_DAYS[navRange]
      const d = new Date()
      d.setDate(d.getDate() - days)
      cutoff = localDateStr(d)
    }
    const filtered = cutoff ? sorted.filter(d => d.date >= cutoff) : sorted

    // 交易日期查找表：精确匹配净值日，非净值日（周末/筹备期）挂到最近净值日
    const navDateList = filtered.map(d => d.date)
    function findNearestNavDate(txDate: string): string | null {
      if (navDateList.includes(txDate)) return txDate
      const next = navDateList.find(d => d > txDate)
      if (next) return next
      if (navDateList.length > 0) return navDateList[navDateList.length - 1]
      return null
    }
    const txMap: Record<string, Transaction[]> = {}
    txs?.forEach(t => {
      const navDate = findNearestNavDate(t.date)
      if (!navDate) return
      if (!txMap[navDate]) txMap[navDate] = []
      txMap[navDate].push(t)
    })

    // 从全部交易计算每日累计份额（不受时间区间限制）
    const sortedTxs = txs ? [...txs].sort((a, b) => a.date.localeCompare(b.date)) : []
    let cumShares = 0
    const cumByDate: { date: string; shares: number }[] = []
    for (const t of sortedTxs) {
      if (t.action === "buy" || t.action === "reinvest") {
        cumShares += t.shares || 0
      } else if (t.action === "sell") {
        cumShares -= t.shares || 0
      }
      cumByDate.push({ date: t.date, shares: cumShares })
    }

    function sharesBefore(target: string): number {
      let result = 0
      for (const c of cumByDate) {
        if (c.date < target) result = c.shares
        else break
      }
      return result
    }

    return filtered.map((d, i) => {
      const prevNav = i > 0 ? filtered[i - 1].nav : null
      let pnl = 0
      if (prevNav != null) {
        const shares = sharesBefore(d.date)
        pnl = Math.round((d.nav - prevNav) * shares * 100) / 100
      }
      return { ...d, pnl, _tx: txMap[d.date] || null }
    })
  }, [navHistory, navRange, txs])

  if (fundError) return <ErrorState message={fundError} onRetry={reloadFund} />
  if (fundLoading) return <div className="flex min-h-[60vh] items-center justify-center"><LogoSpinner className="h-16 w-16" /></div>

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
  const latestDate = openPositions[0]?.latest_date ?? null
  const returnRate = totalCost > 0 ? totalValue / totalCost - 1 : null
  const showEstimate = fundEstimate?.ok && (!latestDate || latestDate <= fundEstimate.jzrq)

  const handleEdit = (tx: Transaction) => {
    navigate("/transactions", { state: { editTx: tx } })
  }

const handleDelete = async (txId: number) => {
    try {
      await api.deleteTransaction(txId)
      toast.success("已删除")
      reloadTxs()
    } catch (e) { toast.error(`删除失败: ${e}`) }
  }

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
              onClick={() => {
                const ch = openPositions.length === 1 ? `&channel=${encodeURIComponent(openPositions[0].channel)}` : ""
                navigate(`/transactions?code=${code}&action=sell${ch}`)
              }}
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
        <MetricCard label="最新净值" value={navStr(latestNav)} sub={showEstimate ? `${latestDate} · 估算 ${navStr(fundEstimate!.gsz)} ${pct(fundEstimate!.gszzl / 100)} · ${fundEstimate!.gztime.slice(5, 16)}` : latestDate ?? undefined} subColor={showEstimate ? pnlColor(fundEstimate!.gszzl / 100) : undefined} />
        <MetricCard label="当前市值" value={money(totalValue)} />
        <MetricCard label="浮动盈亏" value={signedMoney(totalUnrealized)} color={pnlColor(totalUnrealized)} />
        <MetricCard label="已实现盈亏" value={signedMoney(totalRealized)} color={pnlColor(totalRealized)} />
        <MetricCard label="收益率" value={pct(returnRate)} color={pnlColor(returnRate)} sub={latestNav != null && avgCost != null && latestNav < avgCost ? `回本 ${pct(avgCost / latestNav - 1)}` : undefined} subColor="text-amber-600" />
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
                  <TableHead className="w-20">操作</TableHead>
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
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs text-loss border-loss/30 hover:bg-loss/5"
                        onClick={() => navigate(`/transactions?code=${code}&action=sell&channel=${encodeURIComponent(p.channel)}`)}
                      >
                        <TrendingDown className="h-3 w-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* NAV history chart */}
      <Card className="card-hover">
        <CardHeader className="pb-2 flex-row items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">净值走势</CardTitle>
          <div className="flex items-center gap-1">
            {(["1m", "3m", "6m", "1y", "hold"] as const).map(r => (
              <Button key={r} size="sm" variant={navRange === r ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                onClick={() => setNavRange(r)}>
                {RANGE_LABELS[r]}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {chartData.length >= 2 ? (
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={chartData} margin={{ left: 10, right: 10, top: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="nav" fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                <YAxis yAxisId="pnl" orientation="right" fontSize={10} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v >= 0 ? '+' : ''}${(v / 1000).toFixed(1)}k`} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null
                    const d = payload[0].payload
                    const txInfo = d._tx as Transaction[] | null
                    return (
                      <div className="rounded-lg border bg-card px-3 py-2 shadow-lg">
                        <p className="text-xs font-medium text-muted-foreground">{label}</p>
                        <p className="text-sm font-bold tabular-nums text-primary">{navStr(d.nav)}</p>
                        {d.pnl != null && d.pnl !== 0 && (
                          <p className={`text-xs tabular-nums ${d.pnl >= 0 ? "text-gain" : "text-loss"}`}>
                            当日收益 {signedMoney(d.pnl)}
                          </p>
                        )}
                        {txInfo && txInfo.length > 0 && (
                          <div className="mt-1 space-y-0.5 border-t pt-1">
                            {txInfo.map((t, i) => (
                              <p key={i} className={`text-xs tabular-nums ${t.action === 'buy' ? 'text-gain' : t.action === 'sell' ? 'text-loss' : t.action === 'dividend' ? 'text-blue-500' : 'text-purple-500'}`}>
                                {ACTION_LABELS[t.action] ?? t.action}
                                {t.date !== label && <span className="text-muted-foreground"> ({t.date})</span>}
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
                {avgCost && <ReferenceLine yAxisId="nav" y={avgCost} stroke="hsl(var(--muted-foreground))" strokeDasharray="5 5" label={{ value: `均价 ${navStr(avgCost)}`, fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />}
                <Bar yAxisId="pnl" dataKey="pnl" radius={[2, 2, 0, 0]}>
                  {chartData.map((row, i) => (
                    <Cell key={i} fill={row.pnl >= 0 ? "var(--gain-500)" : "var(--loss-500)"} fillOpacity={0.5} />
                  ))}
                </Bar>
                <Line
                  yAxisId="nav"
                  type="monotone"
                  dataKey="nav"
                  stroke="hsl(var(--primary))"
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
                          <circle cx={both ? cx - 3 : cx} cy={cy} r={4} fill="var(--gain-600)" stroke="#fff" strokeWidth={2} />
                        )}
                        {hasSell && (
                          <circle cx={both ? cx + 3 : cx} cy={cy} r={4} fill="var(--loss-600)" stroke="#fff" strokeWidth={2} />
                        )}
                      </g>
                    )
                  }}
                />
              </ComposedChart>
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
                  <TableHead className="w-20">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {txs.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell>{t.date}</TableCell>
                    <TableCell>
                      <Badge
                        variant={t.action === "buy" ? "success" : t.action === "sell" ? "destructive" : "outline"}
                        className={t.action === "dividend" ? "text-blue-600 border-blue-300 bg-blue-50" : t.action === "reinvest" ? "text-purple-600 border-purple-300 bg-purple-50" : ""}
                      >
                        {ACTION_LABELS[t.action] ?? t.action}
                      </Badge>
                    </TableCell>
                    <TableCell>{t.channel || "未标注"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.amount ? money(t.amount) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.shares?.toFixed(2) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.nav?.toFixed(4) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.fee || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{t.note}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" onClick={() => handleEdit(t)}>
                          <Pencil className="h-4 w-4 text-blue-500" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setConfirmDeleteId(t.id!)}>
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {txs && txs.length > 0 && <p className="mt-3 text-sm text-muted-foreground">共 {txs.length} 笔交易</p>}
        </CardContent>
      </Card>

      {/* 删除确认弹窗 */}
      {confirmDeleteId != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setConfirmDeleteId(null)}>
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold">确认删除</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              确定要删除这笔交易记录吗？此操作<strong>不可撤销</strong>。
            </p>
            <div className="mt-4 flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => setConfirmDeleteId(null)}>
                取消
              </Button>
              <Button variant="destructive" className="flex-1" onClick={async () => {
                await handleDelete(confirmDeleteId)
                setConfirmDeleteId(null)
              }}>
                删除
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
