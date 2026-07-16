import { useApi } from "@/lib/useApi"
import { useMemo, useEffect } from "react"
import { api } from "@/api/client"
import type { PortfolioSummary, DistributionItem, EstimateSummary } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import { money, pct, signedMoney, pnlColor, localDateStr } from "@/lib/format"
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts"
import { Wallet, TrendingUp, DollarSign, ArrowUpFromLine, Calendar, Activity } from "lucide-react"
import type { ElementType } from "react"

const PIE_COLORS = ["#1E40AF", "#3B82F6", "#60A5FA", "#93C5FD", "#D97706", "#F59E0B", "#6366F1"]

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
  return (
    <Card className="card-hover col-span-1 lg:col-span-1">
      <CardContent className="p-4 md:p-5">
        <p className="text-xs font-medium text-muted-foreground">当前市值</p>
        <p className="mt-1 text-2xl font-bold tabular-nums fade-in-up text-foreground">{money(summary.total_value)}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums">
          <span className="text-muted-foreground">总盈亏</span>
          <span className={`font-medium ${pnlColor(summary.total_pnl)}`}>
            {signedMoney(summary.total_pnl)} <span className="text-muted-foreground">({pct(summary.total_return)})</span>
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
          <span>浮动 {signedMoney(summary.unrealized_pnl)}</span>
          <span>已实现 {signedMoney(summary.realized_pnl)}</span>
        </div>
      </CardContent>
    </Card>
  )
}

function MetricCard({ icon: Icon, label, value, sub, color }: {
  icon: ElementType; label: string; value: string; sub?: string; color?: string
}) {
  return (
    <Card className="card-hover">
      <CardContent className="flex items-center justify-between p-4 md:p-5">
        <div className="space-y-0.5">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className={`text-lg md:text-xl font-bold tabular-nums fade-in-up ${color ?? ""}`}>{value}</p>
          {sub && <p className={`text-xs tabular-nums ${color ?? "text-muted-foreground"}`}>{sub}</p>}
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-50">
          <Icon className="h-5 w-5 text-slate-400" />
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
  const { data: summary, loading: sl, error: se, reload: reloadSummary } = useApi<PortfolioSummary>(() => api.getSummary())

  const dailyLabel = useMemo(() => {
    if (!summary?.as_of_date) return "今日收益"
    const today = localDateStr()
    if (summary.as_of_date === today) return "今日收益"
    const yesterday = localDateStr(new Date(Date.now() - 86400000))
    if (summary.as_of_date === yesterday) return "昨日收益"
    const d = new Date(summary.as_of_date + "T00:00:00")
    return `${d.getMonth() + 1}/${d.getDate()}收益`
  }, [summary])
  const { data: typeDist } = useApi<DistributionItem[]>(() => api.getDistribution("fund_type"))
  const { data: channelDist } = useApi<DistributionItem[]>(() => api.getDistribution("channel"))
  const { data: sectorDist } = useApi<DistributionItem[]>(() => api.getDistribution("sector"))

  const { data: estimate, reload: reloadEstimate } = useApi<EstimateSummary>(() => api.getEstimate())
  useEffect(() => {
    const interval = setInterval(reloadEstimate, 60000)
    return () => clearInterval(interval)
  }, [reloadEstimate])

  const hasEstimate = estimate && estimate.funds.some((f) => f.ok)

  if (se) return <ErrorState message={se} onRetry={reloadSummary} />
  if (sl || !summary) return <div className="flex min-h-[60vh] items-center justify-center"><LogoSpinner className="h-16 w-16" /></div>

  const noData = summary.holding_count === 0
  if (noData) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl md:text-2xl font-bold">组合总览</h1>
        <Card>
          <CardContent className="py-20 text-center text-muted-foreground">
            还没有交易记录。请到「交易管理」添加买入/卖出流水或导入 CSV。
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl md:text-2xl font-bold tracking-tight">组合总览</h1>
        {summary.max_single_name && (
          <p className="text-sm text-muted-foreground">
            最大单持仓：<span className="font-medium text-foreground">{summary.max_single_name}</span>
            {" "}占比 <span className="font-mono font-medium">{pct(summary.max_single_weight)}</span>
          </p>
        )}
      </div>

      {/* Row 1: Period returns — compact cards, no icons */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 md:gap-4">
        <CompactCard label="今日估算" value={hasEstimate ? signedMoney(estimate!.total_estimated_pnl) : "—"} sub={hasEstimate ? `${pct(estimate!.estimated_return)} · ${estimate!.gztime.slice(11, 16) || ""}` : "休市/无估值"} color={hasEstimate ? pnlColor(estimate!.total_estimated_pnl) : undefined} />
        <CompactCard label={dailyLabel} value={signedMoney(summary.daily_pnl)} sub={pct(summary.daily_return)} color={pnlColor(summary.daily_pnl)} />
        <CompactCard label="本周收益" value={signedMoney(summary.week_pnl)} sub={pct(summary.week_return)} color={pnlColor(summary.week_pnl)} />
        <CompactCard label="本月收益" value={signedMoney(summary.month_pnl)} sub={pct(summary.month_return)} color={pnlColor(summary.month_pnl)} />
        <CompactCard label="今年收益" value={signedMoney(summary.year_pnl)} sub={pct(summary.year_return)} color={pnlColor(summary.year_pnl)} />
      </div>

      {/* Row 2: Hero + portfolio metrics — 3-col with hero card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-4">
        <HeroCard summary={summary} />
        <MetricCard icon={Wallet} label="持仓成本" value={money(summary.total_cost)} />
        <MetricCard icon={Wallet} label="持仓基金数" value={`${summary.holding_count} 只`} sub={`净值日期 ${summary.as_of_date ?? "未更新"}`} />
      </div>

      {/* Row 3: Transaction summary + max concentration — 2-col */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 md:gap-4">
        <Card className="card-hover">
          <CardContent className="p-4 md:p-5">
            <p className="text-xs font-medium text-muted-foreground">累计买入 / 卖出 / 分红</p>
            <p className="mt-1 text-sm md:text-base font-bold tabular-nums">
              <span className="text-blue-600">{money(summary.total_buy)}</span>
              <span className="text-muted-foreground mx-1.5">/</span>
              <span className="text-amber-600">{money(summary.total_sell)}</span>
              <span className="text-muted-foreground mx-1.5">/</span>
              <span className="text-purple-600">{money(summary.total_dividend)}</span>
            </p>
          </CardContent>
        </Card>
        <MetricCard icon={Calendar} label="最大单基金占比" value={pct(summary.max_single_weight)} sub={summary.max_single_name || undefined} />
      </div>

      {/* Row 4: Charts — bar chart spans 2 cols, pies 1 col each */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 md:gap-4">
        <Card className="card-hover lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">板块分布</CardTitle></CardHeader>
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
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">资产类型</CardTitle></CardHeader>
          <CardContent>
            {typeDist && typeDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={typeDist} dataKey="market_value" nameKey="fund_type" cx="50%" cy="50%" outerRadius={75} innerRadius={40} paddingAngle={2}>
                    {typeDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip content={<ChartTooltip nameKey="fund_type" />} />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">渠道分布</CardTitle></CardHeader>
          <CardContent>
            {channelDist && channelDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={channelDist.map(d => ({ ...d, channel: d.channel || "未标注" }))} dataKey="market_value" nameKey="channel" cx="50%" cy="50%" outerRadius={75} innerRadius={40} paddingAngle={2}>
                    {channelDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip content={<ChartTooltip nameKey="channel" />} />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
