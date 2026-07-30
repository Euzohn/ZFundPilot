import { useApi } from "@/lib/useApi"
import { useMemo, useEffect } from "react"
import { api } from "@/api/client"
import type { PortfolioSummary, DistributionItem, EstimateSummary } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import { money, pct, signedMoney, pnlColor, localDateStr } from "@/lib/format"
import { isMarketOpen } from "@/lib/market"
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts"
import { Wallet, TrendingUp, DollarSign, ArrowUpFromLine, Calendar, Activity } from "lucide-react"
import { CHART_COLORS } from "@/lib/chartPalette"
import MetricCard from "@/components/MetricCard"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { useLang } from "@/i18n/LanguageContext"
import { translateFundType, translateChannel } from "@/lib/taxonomyLabels"

function CompactCard({ label, value, sub, color }: {
  label: string; value: string; sub?: string; color?: string
}) {
  return (
    <Card className="card-hover">
      <CardContent className="p-4 md:p-5">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums fade-in-up ${color ?? ""}`}>{value}</p>
        {sub && <p className={`text-xs tabular-nums ${color ?? "text-muted-foreground"}`}>{sub}</p>}
      </CardContent>
    </Card>
  )
}

function HeroCard({ summary }: { summary: PortfolioSummary }) {
  const { t } = useLang()
  return (
    <Card className="card-hover col-span-1 lg:col-span-1">
      <CardContent className="p-4 md:p-5">
        <p className="text-xs font-medium text-muted-foreground">{t.overview.totalValue}</p>
        <p className="mt-1 text-2xl font-bold tabular-nums fade-in-up text-foreground">{money(summary.total_value)}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums">
          <span className="text-muted-foreground">{t.overview.totalPnl}</span>
          <span className={`font-medium ${pnlColor(summary.total_pnl)}`}>
            {signedMoney(summary.total_pnl)} <span className="text-muted-foreground">({pct(summary.total_return)})</span>
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
          <span>{t.overview.unrealized} {signedMoney(summary.unrealized_pnl)}</span>
          <span>{t.overview.realized} {signedMoney(summary.realized_pnl)}</span>
        </div>
      </CardContent>
    </Card>
  )
}

function ChartTooltip({ active, payload, nameKey }: any) {
  if (!active || !payload?.length) return null
  const label = nameKey ? payload[0].payload?.[nameKey] : payload[0].name
  return (
    <div className="rounded-lg border bg-card px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-foreground">{label ?? payload[0].name}</p>
      <p className="text-sm font-bold tabular-nums text-primary">{money(payload[0].value as number)}</p>
    </div>
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
  const { data: typeDist } = useApi<DistributionItem[]>(() => api.getDistribution("fund_type"))
  const { data: channelDist } = useApi<DistributionItem[]>(() => api.getDistribution("channel"))
  const { data: sectorDist } = useApi<DistributionItem[]>(() => api.getDistribution("sector"))

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
        <PageHeader title={t.overview.title} />
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
        <PageHeader title={t.overview.title} tracking="tight" actions={summary.max_single_name ? (
          <p className="text-sm text-muted-foreground">
            {t.overview.maxHolding}：<span className="font-medium text-foreground">{summary.max_single_name}</span>
            {" "}{t.overview.weight} <span className="font-mono font-medium">{pct(summary.max_single_weight)}</span>
          </p>
        ) : undefined} />

      {/* Row 1: Period returns — compact cards, no icons */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 md:gap-4">
        <CompactCard label={t.overview.estNav} value={hasEstimate ? signedMoney(estimate!.total_estimated_pnl) : "—"} sub={hasEstimate ? `${pct(estimate!.estimated_return)} · ${estimate!.gztime.slice(11, 16) || ""}` : undefined} color={hasEstimate ? pnlColor(estimate!.total_estimated_pnl) : undefined} />
        <CompactCard label={dailyLabel} value={signedMoney(summary.daily_pnl)} sub={pct(summary.daily_return)} color={pnlColor(summary.daily_pnl)} />
        <CompactCard label={t.overview.weekPnl} value={signedMoney(summary.week_pnl)} sub={pct(summary.week_return)} color={pnlColor(summary.week_pnl)} />
        <CompactCard label={t.overview.monthPnl} value={signedMoney(summary.month_pnl)} sub={pct(summary.month_return)} color={pnlColor(summary.month_pnl)} />
        <CompactCard label={t.overview.yearPnl} value={signedMoney(summary.year_pnl)} sub={pct(summary.year_return)} color={pnlColor(summary.year_pnl)} />
      </div>

      {/* Row 2: Hero + portfolio metrics — 3-col with hero card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-4">
        <HeroCard summary={summary} />
        <MetricCard fade icon={Wallet} label={t.overview.totalCost} value={money(summary.total_cost)} />
        <MetricCard fade icon={Wallet} label={t.overview.holdingCount} value={`${summary.holding_count} ${t.common.units}`} sub={`${t.overview.navDate} ${summary.as_of_date ?? t.overview.notUpdated}`} />
      </div>

      {/* Row 3: Transaction summary + max concentration — 2-col */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 md:gap-4">
        <Card className="card-hover">
          <CardContent className="p-4 md:p-5">
            <p className="text-xs font-medium text-muted-foreground">{t.overview.buySellDividend}</p>
            <p className="mt-1 text-sm md:text-base font-bold tabular-nums">
              <span className="text-primary">{money(summary.total_buy)}</span>
              <span className="text-muted-foreground mx-1.5">/</span>
              <span className="text-warning">{money(summary.total_sell)}</span>
              <span className="text-muted-foreground mx-1.5">/</span>
              <span className="text-info">{money(summary.total_dividend)}</span>
            </p>
          </CardContent>
        </Card>
        <MetricCard fade icon={Calendar} label={t.overview.maxSingleWeight} value={pct(summary.max_single_weight)} sub={summary.max_single_name || undefined} />
      </div>

      {/* Row 4: Charts — bar chart spans 2 cols, pies 1 col each */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 md:gap-4">
        <Card className="card-hover lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.overview.sectorDist}</CardTitle></CardHeader>
          <CardContent>
            {sectorDist && sectorDist.length > 0 ? (
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
            {typeDist && typeDist.length > 0 ? (
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
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">{t.overview.channelDist}</CardTitle></CardHeader>
          <CardContent>
            {channelDist && channelDist.length > 0 ? (
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
