import { useApi } from "@/lib/useApi"
import { useMemo, useEffect } from "react"
import { api } from "@/api/client"
import type { PortfolioSummary, DistributionItem, EstimateSummary } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import ErrorState from "@/components/ErrorState"
import { money, pct, signedMoney, pnlColor, localDateStr } from "@/lib/format"
import { isMarketOpen } from "@/lib/market"
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts"
import { Wallet, Calendar, LayoutDashboard, ArrowLeftRight, Database } from "lucide-react"
import { CHART_COLORS } from "@/lib/chartPalette"
import MetricCard from "@/components/MetricCard"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { useLang } from "@/i18n/LanguageContext"
import { translateFundType, translateChannel, translateRiskLevel } from "@/lib/taxonomyLabels"
import { Link } from "react-router-dom"

function HeroCard({ summary }: { summary: PortfolioSummary }) {
  const { t } = useLang()
  return (
    <Card className="card-hover col-span-1 lg:col-span-1">
      <CardContent className="p-4 md:p-5">
        <p className="text-xs font-medium text-muted-foreground">{t.overview.totalValue}</p>
        <p className="mt-1 text-3xl md:text-4xl font-bold tabular-nums text-foreground">{money(summary.total_value)}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums">
          <span className="text-muted-foreground">{t.overview.totalPnl}</span>
          <span className={`font-medium ${pnlColor(summary.total_pnl)}`}>
            {signedMoney(summary.total_pnl)} <span className="text-muted-foreground">({pct(summary.total_return)})</span>
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

interface ChartTooltipProps {
  active?: boolean
  payload?: Array<{ name?: string; value?: number; payload?: Record<string, unknown> }>
  nameKey?: string
}

function ChartTooltip({ active, payload, nameKey }: ChartTooltipProps) {
  if (!active || !payload?.length) return null
  const label = (nameKey ? payload[0].payload?.[nameKey] : payload[0].name) as string | undefined
  return (
    <div className="rounded-lg border bg-card px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-foreground">{label ?? payload[0].name}</p>
      <p className="text-sm font-bold tabular-nums text-primary">{money(payload[0].value as number)}</p>
    </div>
  )
}

function DataStatusBanner({ summary }: { summary: PortfolioSummary }) {
  const { t } = useLang()
  const ds = summary.data_status
  const staleFunds = (ds?.missing_nav_fund_count ?? 0) + (ds?.stale_nav_fund_count ?? 0)
  const pendingT1 = ds?.pending_t1_transaction_count ?? 0
  const navLabel = summary.as_of_date
    ? t.overview.latestFormalNav.replace("{date}", summary.as_of_date)
    : t.overview.noFormalNav
  const allClear = staleFunds === 0 && pendingT1 === 0
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col gap-2 p-3 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <Database className="h-3.5 w-3.5" />
            {navLabel}
          </span>
          <span className={`tabular-nums ${staleFunds > 0 ? "text-warning font-medium" : "text-muted-foreground"}`}>
            {t.overview.staleFunds} {staleFunds} {t.common.units}
          </span>
          <span className={`tabular-nums ${pendingT1 > 0 ? "text-warning font-medium" : "text-muted-foreground"}`}>
            {t.overview.pendingT1} {pendingT1} {t.overview.txUnits}
          </span>
          {allClear && (
            <span className="text-success">{t.overview.allClear}</span>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <Link
            to="/nav"
            className="inline-flex h-7 items-center rounded-md border border-input bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          >
            {t.overview.viewNav}
          </Link>
          <Link
            to="/transactions?tab=list"
            className="inline-flex h-7 items-center rounded-md border border-input bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          >
            {t.overview.viewTransactions}
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Overview() {
  const { t } = useLang()
  const { data: summary, loading: sl, error: se, reload: reloadSummary } = useApi<PortfolioSummary>(() => api.getSummary())

  const dailyLabel = useMemo(() => {
    if (!summary?.as_of_date) return t.overview.dailyPnl
    const today = localDateStr()
    if (summary.as_of_date === today) return t.overview.dailyPnl
    const yesterday = localDateStr(new Date(Date.now() - 86400000))
    if (summary.as_of_date === yesterday) return t.overview.yesterdayPnl
    const d = new Date(summary.as_of_date + "T00:00:00")
    return `${d.getMonth() + 1}/${d.getDate()}${t.overview.pnlSuffix}`
  }, [summary, t])
  const { data: typeDist, loading: typeDistLoading } = useApi<DistributionItem[]>(() => api.getDistribution("fund_type"))
  const { data: channelDist, loading: channelDistLoading } = useApi<DistributionItem[]>(() => api.getDistribution("channel"))
  const { data: sectorDist, loading: sectorDistLoading } = useApi<DistributionItem[]>(() => api.getDistribution("sector"))
  const { data: riskDist, loading: riskDistLoading } = useApi<DistributionItem[]>(() => api.getDistribution("risk_level"))

  const { data: estimate, reload: reloadEstimate } = useApi<EstimateSummary>(() => api.getEstimate())

  const hasEstimate = estimate?.funds.some(f => f.ok) ?? false

  useEffect(() => {
    if (!hasEstimate) return
    const interval = setInterval(() => {
      if (!isMarketOpen()) return
      reloadEstimate()
    }, 60000)
    return () => clearInterval(interval)
  }, [reloadEstimate, hasEstimate])

  if (se) return <ErrorState message={se} onRetry={reloadSummary} />
  if (sl || !summary) return <LoadingState />

  const noData = summary.holding_count === 0
  if (noData) {
    return (
      <div className="space-y-6">
        <PageHeader title={t.overview.title} icon={<LayoutDashboard className="h-5 w-5" />} />
        <Card>
          <CardContent className="py-20 text-center text-muted-foreground">
            {t.overview.noHoldingsHint}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
        <PageHeader title={t.overview.title} icon={<LayoutDashboard className="h-5 w-5" />} />

      {/* Row 1: Period returns — compact cards, no icons */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 md:gap-4">
        <MetricCard label={t.overview.estNav} value={hasEstimate ? signedMoney(estimate!.total_estimated_pnl) : "—"} sub={hasEstimate ? `${pct(estimate!.estimated_return)} · ${estimate!.gztime.slice(11, 16) || ""}` : undefined} color={hasEstimate ? pnlColor(estimate!.total_estimated_pnl) : undefined} />
        <MetricCard label={dailyLabel} value={signedMoney(summary.daily_pnl)} sub={pct(summary.daily_return)} color={pnlColor(summary.daily_pnl)} />
        <MetricCard label={t.overview.weekPnl} value={signedMoney(summary.week_pnl)} sub={pct(summary.week_return)} color={pnlColor(summary.week_pnl)} />
        <MetricCard label={t.overview.monthPnl} value={signedMoney(summary.month_pnl)} sub={pct(summary.month_return)} color={pnlColor(summary.month_pnl)} />
        <MetricCard label={t.overview.yearPnl} value={signedMoney(summary.year_pnl)} sub={pct(summary.year_return)} color={pnlColor(summary.year_pnl)} />
      </div>

      {/* Row 2: Hero + portfolio metrics — 3-col with hero card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-4">
        <HeroCard summary={summary} />
        <Card className="card-hover h-full">
          <CardContent className="p-4 md:p-5 h-full flex items-center justify-between">
            <div className="space-y-0.5">
              <p className="text-xs font-medium text-muted-foreground">{t.overview.totalCost}</p>
              <p className="font-bold tabular-nums text-lg md:text-xl">{money(summary.total_cost)}</p>
              {summary.annualized_return != null && (
                <p className={`text-xs tabular-nums ${pnlColor(summary.annualized_return)}`}>
                  {t.returns.annualized} {pct(summary.annualized_return)}
                </p>
              )}
              <p className="text-xs tabular-nums text-muted-foreground">
                {t.overview.unrealized} {signedMoney(summary.unrealized_pnl)} · {t.overview.realized} {signedMoney(summary.realized_pnl)}
              </p>
            </div>
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Wallet className="h-5 w-5" />
            </div>
          </CardContent>
        </Card>
        <MetricCard icon={Wallet} iconTone="info" label={t.overview.holdingCount} value={`${summary.holding_count} ${t.common.units}`} sub={`${t.overview.navDate} ${summary.as_of_date ?? t.overview.notUpdated}`} />
      </div>

      {/* Row 3: Transaction summary + max concentration — 2-col */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 md:gap-4">
        <Card className="card-hover h-full">
          <CardContent className="p-4 md:p-5 h-full flex items-center justify-between">
            <div className="space-y-0.5">
              <p className="text-xs font-medium text-muted-foreground">{t.overview.buySellDividend}</p>
              <p className="text-sm md:text-base font-bold tabular-nums">
                <span className="text-primary">{money(summary.total_buy)}</span>
                <span className="text-muted-foreground mx-1.5">/</span>
                <span className="text-warning">{money(summary.total_sell)}</span>
                <span className="text-muted-foreground mx-1.5">/</span>
                <span className="text-info">{money(summary.total_dividend)}</span>
              </p>
            </div>
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-info/10 text-info">
              <ArrowLeftRight className="h-5 w-5" />
            </div>
          </CardContent>
        </Card>
        <MetricCard icon={Calendar} iconTone="warning" label={t.overview.maxSingleWeight} value={pct(summary.max_single_weight)} sub={summary.max_single_name || undefined} />
      </div>

      {/* Data status banner — formal NAV freshness + T+1 pending */}
      <DataStatusBanner summary={summary} />

      {/* Row 4: Charts — bar chart spans 2 cols, pies 1 col each */}
      <div className="grid grid-cols-1 lg:grid-cols-4 xl:grid-cols-5 gap-3 md:gap-4">
        <Card className="card-hover lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.overview.sectorDist}</CardTitle></CardHeader>
          <CardContent>
            {sectorDistLoading ? <LoadingState size="sm" /> : sectorDist && sectorDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={sectorDist.slice(0, 12)} layout="vertical" margin={{ left: 10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" />
                  <XAxis type="number" tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="sector" width={65} fontSize={11} tick={{ fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                  <Bar dataKey="market_value" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} barSize={14} />
                  <Tooltip content={<ChartTooltip nameKey="sector" />} cursor={{ fill: 'hsl(var(--primary))', opacity: 0.08 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <EmptyState title={t.common.noData} size="lg" />}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.overview.typeDist}</CardTitle></CardHeader>
          <CardContent>
            {typeDistLoading ? <LoadingState size="sm" /> : typeDist && typeDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={typeDist.map(d => ({ ...d, fund_type: translateFundType(String(d.fund_type)) }))} dataKey="market_value" nameKey="fund_type" cx="50%" cy="50%" outerRadius={75} innerRadius={40} paddingAngle={2}>
                    {typeDist.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip content={<ChartTooltip nameKey="fund_type" />} />
                </PieChart>
              </ResponsiveContainer>
            ) : <EmptyState title={t.common.noData} size="lg" />}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.overview.riskDist}</CardTitle></CardHeader>
          <CardContent>
            {riskDistLoading ? <LoadingState size="sm" /> : riskDist && riskDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={riskDist.map(d => ({ ...d, risk_level: translateRiskLevel(String(d.risk_level)) }))} dataKey="market_value" nameKey="risk_level" cx="50%" cy="50%" outerRadius={75} innerRadius={40} paddingAngle={2}>
                    {riskDist.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip content={<ChartTooltip nameKey="risk_level" />} />
                </PieChart>
              </ResponsiveContainer>
            ) : <EmptyState title={t.common.noData} size="lg" />}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.overview.channelDist}</CardTitle></CardHeader>
          <CardContent>
            {channelDistLoading ? <LoadingState size="sm" /> : channelDist && channelDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={channelDist.map(d => ({ ...d, channel: translateChannel(String(d.channel || t.common.unlabeled)) }))} dataKey="market_value" nameKey="channel" cx="50%" cy="50%" outerRadius={75} innerRadius={40} paddingAngle={2}>
                    {channelDist.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip content={<ChartTooltip nameKey="channel" />} />
                </PieChart>
              </ResponsiveContainer>
            ) : <EmptyState title={t.common.noData} size="lg" />}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
