import { useState, useMemo, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Position, Transaction, Fund, FundEstimate, FundHoldings as FundHoldingsType, FundRanking, FundProfile } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, signedMoney, navStr, pnlColor, localDateStr } from "@/lib/format"
import { RANGE_DAYS } from "@/lib/rangeLabels"
import { isMarketOpen } from "@/lib/market"
import { getColorForChannel } from "@/lib/channelColors"
import { translateFundType, translateSector, translateChannel, translateRiskLevel, FUND_TYPE_DOT, RISK_LEVEL_DOT } from "@/lib/taxonomyLabels"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { useLang } from "@/i18n/LanguageContext"
import { useCompare } from "@/contexts/CompareContext"
import { ArrowLeft, TrendingUp, TrendingDown, GitCompare, Star, Repeat, Pencil, Trash2, ChevronDown } from "lucide-react"
import { ComposedChart, Line, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, PieChart, Pie, LineChart } from "recharts"
import MetricCard from "@/components/MetricCard"
import ConfirmDialog from "@/components/ConfirmDialog"
import TransactionDetailDialog from "@/components/TransactionDetailDialog"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"

export default function FundDetail() {
  const { t } = useLang()
  const { code } = useParams<{ code: string }>()
  const navigate = useNavigate()
  const { addCode, hasCode, removeCode } = useCompare()
  const { data: watchlist, reload: reloadWatchlist } = useApi(() => api.getWatchlist(), [])
  const inWatchlist = watchlist?.some(w => w.fund_code === code) ?? false
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [viewingTx, setViewingTx] = useState<Transaction | null>(null)
  const [navRange, setNavRange] = useState<"1m" | "3m" | "6m" | "1y" | "hold" | "tx" | "custom">("1y")
  const [customStart, setCustomStart] = useState("")
  const [customEnd, setCustomEnd] = useState("")

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
  const { data: holdingsData } = useApi<FundHoldingsType>(() => api.getFundHoldings(code!), [code])
  const { data: rankingData } = useApi<FundRanking>(() => api.getFundRanking(code!), [code])
  const { data: profileData } = useApi<FundProfile>(() => api.getFundProfile(code!), [code])
  useEffect(() => {
    if (!fundEstimate?.ok) return
    const interval = setInterval(() => {
      if (!isMarketOpen()) return
      reloadEstimate()
    }, 60000)
    return () => clearInterval(interval)
  }, [reloadEstimate, fundEstimate])

  // 净值图表数据：时间区间过滤 + 每日收益计算（必须在 early return 之前）
  const chartData = useMemo(() => {
    if (!navHistory?.length) return []
    const sorted = [...navHistory].sort((a, b) => a.date.localeCompare(b.date))

    // 时间区间过滤
    let cutoff: string | null = null
    let cutoffEnd: string | null = null
    if (navRange === "hold") {
      if (txs?.length) {
        cutoff = [...txs].map(t => t.date).sort()[0]
      }
    } else if (navRange === "tx") {
      // 交易区间：第一笔交易 → 最后一笔卖出
      if (txs?.length) {
        const sortedTxDates = [...txs].map(t => t.date).sort()
        cutoff = sortedTxDates[0]
        const sellDates = txs.filter(t => t.action === "sell").map(t => t.date).sort()
        if (sellDates.length > 0) {
          cutoffEnd = sellDates[sellDates.length - 1]
        }
      }
    } else if (navRange === "custom") {
      if (customStart) cutoff = customStart
      if (customEnd) cutoffEnd = customEnd
    } else {
      const days = RANGE_DAYS[navRange]
      if (days) {
        const d = new Date()
        d.setDate(d.getDate() - days)
        cutoff = localDateStr(d)
      }
    }
    const filtered = cutoff
      ? sorted.filter(d => d.date >= cutoff && (!cutoffEnd || d.date <= cutoffEnd))
      : sorted

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
      let pnlReturn = 0
      if (prevNav != null) {
        const shares = sharesBefore(d.date)
        pnl = Math.round((d.nav - prevNav) * shares * 100) / 100
        pnlReturn = (d.nav - prevNav) / prevNav
      }
      return { ...d, pnl, pnlReturn, _tx: txMap[d.date] || null }
    })
  }, [navHistory, navRange, txs])

  if (fundError) return <ErrorState message={fundError} onRetry={reloadFund} />
  if (fundLoading) return <LoadingState />

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
      toast.success(t.common.deleted)
      reloadTxs()
    } catch (e) { toast.error(`${t.common.deleteFailed}: ${e}`) }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="icon" onClick={() => navigate("/positions")} className="shrink-0">
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1 min-w-0">
          <PageHeader title={fund?.fund_name ?? code} tracking="tight" truncate className="min-w-0" />
          <div className="mt-1 flex items-center gap-2 flex-wrap text-sm">
            <span className="font-mono text-muted-foreground">{code}</span>
            {fund?.fund_type && (
              <Badge variant="secondary" className="font-normal gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${FUND_TYPE_DOT[fund.fund_type] ?? "bg-zinc-400"}`} />
                {translateFundType(fund.fund_type)}
              </Badge>
            )}
            {fund?.sector && <Badge variant="outline" className="font-normal">{translateSector(fund.sector)}</Badge>}
            {fund?.tracking_index && (
              <Badge variant="outline" className="font-normal gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
                {t.fundDetail.trackingIndex}: {fund.tracking_index}
              </Badge>
            )}
            {fund && (
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold cursor-pointer hover:bg-muted/50 transition-colors"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                    {t.fundDetail.dividendMethod}: {fund.dividend_method === "reinvest" ? t.transactions.reinvest : t.transactions.dividend}
                    <ChevronDown className="h-3 w-3 text-muted-foreground" />
                  </button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-1" align="center">
                  <div className="flex flex-col gap-0.5">
                    <button
                      onClick={async () => {
                        try { await api.updateDividendMethod(code!, "cash"); await reloadFund(); toast.success(t.transactions.dividend) }
                        catch { toast.error(t.common.operationFailed) }
                      }}
                      className={cn("px-3 py-1.5 text-left text-xs rounded-sm hover:bg-muted/50",
                        fund.dividend_method !== "reinvest" && "text-primary font-medium")}
                    >{t.transactions.dividend}</button>
                    <button
                      onClick={async () => {
                        try { await api.updateDividendMethod(code!, "reinvest"); await reloadFund(); toast.success(t.transactions.reinvest) }
                        catch { toast.error(t.common.operationFailed) }
                      }}
                      className={cn("px-3 py-1.5 text-left text-xs rounded-sm hover:bg-muted/50",
                        fund.dividend_method === "reinvest" && "text-primary font-medium")}
                    >{t.transactions.reinvest}</button>
                  </div>
                </PopoverContent>
              </Popover>
            )}
            {openPositions.length === 1 && (
              <Badge variant="outline" className="font-normal gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: getColorForChannel(openPositions[0].channel) }} />
                {translateChannel(openPositions[0].channel)}
              </Badge>
            )}
            {profileData?.risk_level && (
              <Badge variant="outline" className="font-normal gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${RISK_LEVEL_DOT[profileData.risk_level] ?? "bg-zinc-400"}`} />
                {translateRiskLevel(profileData.risk_level)}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
            <Button
              size="sm"
              variant="outline"
              className={cn(
                "h-8 w-8 p-0",
                code && hasCode(code)
                  ? "text-blue-500 border-blue-500/30 hover:bg-blue-500/5"
                  : "text-muted-foreground border-border hover:bg-accent"
              )}
              onClick={() => {
                if (code && hasCode(code)) {
                  removeCode(code)
                } else if (code) {
                  addCode(code)
                }
              }}
              title={code && hasCode(code) ? t.fundDetail.removeFromCompare : t.fundDetail.addToCompare}
            >
              <GitCompare className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant="outline"
              className={cn(
                "h-8 w-8 p-0",
                inWatchlist
                  ? "text-amber-500 border-amber-500/30 hover:bg-amber-500/5"
                  : "text-muted-foreground border-border hover:bg-accent"
              )}
              onClick={async () => {
                if (!code) return
                try {
                  if (inWatchlist) {
                    await api.removeFromWatchlist(code)
                    reloadWatchlist()
                    toast.success(t.watchlist.removed)
                  } else {
                    await api.addToWatchlist(code)
                    reloadWatchlist()
                    toast.success(t.watchlist.added)
                  }
                } catch (e) {
                  toast.error(`${t.common.operationFailed}: ${e}`)
                }
              }}
              title={inWatchlist ? t.watchlist.removeFromWatchlist : t.watchlist.addToWatchlist}
            >
              <Star className={cn("h-4 w-4", inWatchlist && "fill-amber-500")} />
            </Button>
          <Button
            size="sm"
            variant="outline"
            className="text-gain border-gain/30 hover:bg-gain/5"
            onClick={() => {
              const ch = openPositions.length === 1 ? `&channel=${encodeURIComponent(openPositions[0].channel)}` : ""
              navigate(`/transactions?code=${code}&action=buy${ch}`)
            }}
          >
            <TrendingUp className="h-4 w-4" /> {t.transactions.buy}
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
              <TrendingDown className="h-4 w-4" /> {t.transactions.sell}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            className="text-primary border-primary/30 hover:bg-primary/5"
            onClick={() => {
              const ch = openPositions.length === 1 ? `&channel=${encodeURIComponent(openPositions[0].channel)}` : ""
              navigate(`/transactions?tab=auto-invest&code=${code}${ch}`)
            }}
          >
            <Repeat className="h-4 w-4" /> {t.transactions.autoInvestShort}
          </Button>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <MetricCard size="sm" label={t.fundDetail.heldShares} value={totalShares.toFixed(2)} />
        <MetricCard size="sm" label={t.positions.cost} value={money(totalCost)} />
        <MetricCard size="sm" label={t.fundDetail.avgCost} value={navStr(avgCost)} />
        <MetricCard size="sm" label={t.positions.latestNav} value={navStr(latestNav)} sub={showEstimate ? `${latestDate} · ${t.fundDetail.estimate} ${navStr(fundEstimate!.gsz)} ${pct(fundEstimate!.gszzl / 100)} · ${fundEstimate!.gztime.slice(5, 16)}` : latestDate ?? undefined} subColor={showEstimate ? pnlColor(fundEstimate!.gszzl / 100) : undefined} />
        <MetricCard size="sm" label={t.positions.marketValue} value={money(totalValue)} />
        <MetricCard size="sm" label={t.fundDetail.unrealizedPnl} value={signedMoney(totalUnrealized)} color={pnlColor(totalUnrealized)} />
        <MetricCard size="sm" label={t.fundDetail.realizedPnl} value={signedMoney(totalRealized)} color={pnlColor(totalRealized)} />
        <MetricCard size="sm" label={t.positions.returnRate} value={pct(returnRate)} color={pnlColor(returnRate)} sub={latestNav != null && avgCost != null && latestNav < avgCost ? `${t.fundDetail.breakEven} ${pct(avgCost / latestNav - 1)}` : undefined} subColor="text-warning" />
      </div>

      {/* 基金档案信息栏 */}
      {profileData?.ok && (
        <Card className="card-hover">
          <CardContent className="py-3">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              {profileData.manager && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileManager}</span>
                  <span className="font-medium">{profileData.manager}</span>
                </div>
              )}
              {profileData.manager_career_days != null && profileData.manager_career_days > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileCareer}</span>
                  <span className="font-medium tabular-nums">{Math.round(profileData.manager_career_days / 365)} {t.fundDetail.profileYearsUnit}</span>
                </div>
              )}
              {profileData.scale != null && profileData.scale > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileScale}</span>
                  <span className="font-medium tabular-nums">{profileData.scale.toFixed(2)} {t.fundDetail.profileScaleUnit}</span>
                </div>
              )}
              {profileData.tenure_return != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileTenureReturn}</span>
                  <span className={`font-medium tabular-nums ${profileData.tenure_return >= 0 ? "text-gain" : "text-loss"}`}>{profileData.tenure_return >= 0 ? "+" : ""}{profileData.tenure_return.toFixed(2)}%</span>
                </div>
              )}
              {profileData.management_fee != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileManagementFee}</span>
                  <span className="font-medium tabular-nums">{(profileData.management_fee * 100).toFixed(2)}%</span>
                </div>
              )}
              {profileData.custodian_fee != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileCustodianFee}</span>
                  <span className="font-medium tabular-nums">{(profileData.custodian_fee * 100).toFixed(2)}%</span>
                </div>
              )}
              {profileData.sales_fee != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{t.fundDetail.profileSalesFee}</span>
                  <span className="font-medium tabular-nums">{(profileData.sales_fee * 100).toFixed(2)}%</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 各渠道持仓 */}
      {openPositions.length > 1 && (
        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.fundDetail.byChannel}</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.common.channel}</TableHead>
                  <TableHead className="text-right">{t.common.shares}</TableHead>
                  <TableHead className="text-right">{t.positions.cost}</TableHead>
                  <TableHead className="text-right">{t.fundDetail.avgCost}</TableHead>
                  <TableHead className="text-right">{t.positions.marketValue}</TableHead>
                  <TableHead className="text-right">{t.fundDetail.unrealizedPnl}</TableHead>
                  <TableHead className="w-20">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openPositions.map((p) => (
                  <TableRow key={p.channel}>
                    <TableCell>{p.channel || t.fundDetail.untagged}</TableCell>
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
          <CardTitle className="text-sm font-medium text-muted-foreground">{t.fundDetail.navTrend}</CardTitle>
          <div className="flex items-center gap-1">
            {(["1m", "3m", "6m", "1y", "hold", "tx", "custom"] as const).map(r => (
              <Button key={r} size="sm" variant={navRange === r ? "default" : "outline"} className="h-6 px-2 text-[11px]"
                onClick={() => setNavRange(r)}>
                {t.rangeLabels[r as keyof typeof t.rangeLabels] ?? r}
              </Button>
            ))}
          </div>
          {navRange === "custom" && (
            <div className="flex items-center gap-2 mt-2">
              <Input type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} className="h-7 text-xs w-36" />
              <span className="text-xs text-muted-foreground">{t.fundDetail.to}</span>
              <Input type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} className="h-7 text-xs w-36" />
            </div>
          )}
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
                            {t.fundDetail.dailyPnl} {signedMoney(d.pnl)}
                            {d.pnlReturn != null && ` (${pct(d.pnlReturn)})`}
                          </p>
                        )}
                        {txInfo && txInfo.length > 0 && (
                          <div className="mt-1 space-y-0.5 border-t pt-1">
                            {txInfo.map((tx, i) => (
                              <p key={i} className={`text-xs tabular-nums ${tx.action === 'buy' ? 'text-gain' : tx.action === 'sell' ? 'text-loss' : tx.action === 'dividend' ? 'text-primary' : 'text-info'}`}>
                                {t.actionLabels[tx.action as keyof typeof t.actionLabels] ?? tx.action}
                                {tx.date !== label && <span className="text-muted-foreground"> ({tx.date})</span>}
                                {tx.amount ? ` ${money(tx.amount)}` : ''}
                                {tx.shares ? ` ${tx.shares.toFixed(2)} ${t.fundDetail.sharesUnit}` : ''}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  }}
                />
                {avgCost && <ReferenceLine yAxisId="nav" y={avgCost} stroke="hsl(var(--muted-foreground))" strokeDasharray="5 5" label={{ value: `${t.fundDetail.avgCost} ${navStr(avgCost)}`, fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />}
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
            <EmptyState title={t.fundDetail.navHistoryInsufficient} size="lg" />
          )}
        </CardContent>
      </Card>

      {/* 同类排名走势 */}
      {rankingData?.ok && rankingData.points?.length > 0 && (
        <Card className="card-hover">
          <CardHeader className="pb-2 flex-row items-center justify-between flex-wrap gap-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.fundDetail.rankTrend}</CardTitle>
            <span className="text-xs text-muted-foreground/60">{t.fundDetail.rankLowerBetter}</span>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={rankingData.points} margin={{ left: 10, right: 10, top: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} minTickGap={40} tickFormatter={(v: string) => v.slice(0, 7)} />
                <YAxis reversed fontSize={11} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
                <Tooltip
                  itemStyle={{ color: "hsl(var(--foreground))" }}
                  contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12, color: "hsl(var(--foreground))" }}
                  formatter={(v: number) => [`${v.toFixed(2)}%`, t.fundDetail.rankPercentile]}
                  labelFormatter={(label: string) => label}
                />
                <Line type="monotone" dataKey="percentile" stroke="hsl(var(--chart-3))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Fund holdings: asset allocation + top 10 stocks */}
      {holdingsData?.ok && holdingsData.holdings?.length > 0 && (
        <Card className="card-hover">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-muted-foreground">{t.fundDetail.topHoldings}</CardTitle>
              {holdingsData.quarter && (
                <span className="text-xs text-muted-foreground/60">{t.fundDetail.quarter}: {holdingsData.quarter}</span>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-[200px_1fr]">
              {/* Asset allocation pie chart */}
              <div>
                <p className="text-xs text-muted-foreground/70 mb-2">{t.fundDetail.assetAllocation}</p>
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: t.fundDetail.stock, value: holdingsData.stock_ratio, fill: "hsl(var(--chart-1))" },
                        { name: t.fundDetail.other, value: Math.max(0, 1 - holdingsData.stock_ratio), fill: "hsl(var(--muted))" },
                      ]}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={40}
                      outerRadius={70}
                      paddingAngle={2}
                    >
                      <Cell fill="hsl(var(--chart-1))" />
                      <Cell fill="hsl(var(--muted))" />
                    </Pie>
                    <Tooltip
                      formatter={(v: number, n: string) => [`${(v * 100).toFixed(2)}%`, n]}
                      itemStyle={{ color: "hsl(var(--foreground))" }}
                      contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12, color: "hsl(var(--foreground))" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex justify-center gap-3 text-xs">
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full" style={{ background: "hsl(var(--chart-1))" }} />
                    {t.fundDetail.stock} {(holdingsData.stock_ratio * 100).toFixed(1)}%
                  </span>
                </div>
              </div>

              {/* Top 10 holdings table */}
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">{t.common.code}</TableHead>
                      <TableHead className="text-xs">{t.common.name}</TableHead>
                      <TableHead className="text-xs text-right">{t.fundDetail.weight}</TableHead>
                      <TableHead className="text-xs text-right">{t.fundDetail.holdingsValue}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {holdingsData.holdings.map((h, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs">{h.stock_code}</TableCell>
                        <TableCell className="text-xs">{h.stock_name}</TableCell>
                        <TableCell className="text-right text-xs tabular-nums">
                          <span className={h.weight >= 0.05 ? "text-warning font-medium" : ""}>
                            {(h.weight * 100).toFixed(2)}%
                          </span>
                        </TableCell>
                        <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                          {h.market_value > 0 ? `${(h.market_value / 10000).toFixed(2)}亿` : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Transaction history */}
      <Card className="card-hover">
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.transactions.title}</CardTitle></CardHeader>
        <CardContent>
          {!txs || txs.length === 0 ? (
            <EmptyState title={t.fundDetail.noTransactions} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.common.date}</TableHead>
                  <TableHead>{t.common.actions}</TableHead>
                  <TableHead>{t.common.channel}</TableHead>
                  <TableHead className="text-right">{t.common.amount}</TableHead>
                  <TableHead className="text-right">{t.common.shares}</TableHead>
                  <TableHead className="text-right">{t.common.nav}</TableHead>
                  <TableHead className="text-right">{t.common.fee}</TableHead>
                  <TableHead>{t.common.note}</TableHead>
                  <TableHead className="w-20">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {txs.map((tx) => (
                  <TableRow key={tx.id} onClick={() => setViewingTx(tx)} className="cursor-pointer">
                    <TableCell>{tx.date}</TableCell>
                    <TableCell>
                      <Badge
                        variant={tx.action === "buy" ? "success" : tx.action === "sell" ? "destructive" : "outline"}
                        className={tx.action === "dividend" ? "text-primary border-primary/30 bg-primary/10" : tx.action === "reinvest" ? "text-info border-info/30 bg-info/10" : ""}
                      >
                        {t.actionLabels[tx.action as keyof typeof t.actionLabels] ?? tx.action}
                      </Badge>
                    </TableCell>
                    <TableCell>{tx.channel || t.fundDetail.untagged}</TableCell>
                    <TableCell className="text-right tabular-nums">{tx.amount ? money(tx.amount) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{tx.shares?.toFixed(2) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{tx.nav?.toFixed(4) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{tx.fee || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{tx.note}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" onClick={(e) => { e.stopPropagation(); handleEdit(tx) }}>
                          <Pencil className="h-4 w-4 text-primary" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(tx.id!) }}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {txs && txs.length > 0 && <p className="mt-3 text-sm text-muted-foreground">{t.fundDetail.txCount.replace("{n}", String(txs.length))}</p>}
        </CardContent>
      </Card>

      {/* 详情弹窗 */}
      <TransactionDetailDialog
        tx={viewingTx}
        fundName={fund?.fund_name}
        open={viewingTx != null}
        onOpenChange={(open) => { if (!open) setViewingTx(null) }}
        onEdit={(tx) => { setViewingTx(null); handleEdit(tx) }}
      />

      {/* 删除确认弹窗 */}
      <ConfirmDialog
        open={confirmDeleteId != null}
        onOpenChange={(open) => { if (!open) setConfirmDeleteId(null) }}
        title={t.fundDetail.confirmDeleteTitle}
        description={<>{t.fundDetail.confirmDeleteTxDesc}<strong>{t.fundDetail.irreversible}</strong></>}
        confirmText={t.common.delete}
        tone="destructive"
        onConfirm={async () => {
          if (confirmDeleteId != null) await handleDelete(confirmDeleteId)
        }}
      />
    </div>
  )
}
