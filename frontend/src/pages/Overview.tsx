import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary, DistributionItem } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts"
import { Wallet, TrendingUp, TrendingDown, DollarSign, PiggyBank, ArrowUpFromLine, ArrowDownToLine, Calendar } from "lucide-react"
import type { ElementType } from "react"

const PIE_COLORS = ["#1E40AF", "#3B82F6", "#60A5FA", "#93C5FD", "#D97706", "#F59E0B", "#6366F1"]

function MetricCard({ icon: Icon, label, value, sub, color }: {
  icon: ElementType; label: string; value: string; sub?: string; color?: string
}) {
  return (
    <Card className="card-hover">
      <CardContent className="flex items-center justify-between p-5">
        <div className="space-y-0.5">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className={`text-xl font-bold tabular-nums fade-in-up ${color ?? ""}`}>{value}</p>
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
  return (
    <div className="rounded-lg border bg-white px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-foreground">{payload[0].name}</p>
      <p className="text-sm font-bold tabular-nums text-primary">{money(payload[0].value as number)}</p>
    </div>
  )
}

export default function Overview() {
  const { data: summary, loading: sl } = useApi<PortfolioSummary>(() => api.getSummary())
  const { data: typeDist } = useApi<DistributionItem[]>(() => api.getDistribution("fund_type"))
  const { data: channelDist } = useApi<DistributionItem[]>(() => api.getDistribution("channel"))
  const { data: sectorDist } = useApi<DistributionItem[]>(() => api.getDistribution("sector"))

  if (sl || !summary) return <div className="py-20 text-center text-muted-foreground">加载中...</div>

  const noData = summary.holding_count === 0
  if (noData) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">组合总览</h1>
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">组合总览</h1>
        {summary.max_single_name && (
          <p className="text-sm text-muted-foreground">
            最大单持仓：<span className="font-medium text-foreground">{summary.max_single_name}</span>
            {" "}占比 <span className="font-mono font-medium">{pct(summary.max_single_weight)}</span>
          </p>
        )}
      </div>

      {/* Metrics row 1 */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard icon={Wallet} label="当前持仓成本" value={money(summary.total_cost)} />
        <MetricCard icon={DollarSign} label="当前市值" value={money(summary.total_value)} />
        <MetricCard icon={TrendingUp} label="浮动盈亏" value={signedMoney(summary.unrealized_pnl)} sub={pct(summary.total_return)} color={pnlColor(summary.unrealized_pnl)} />
        <MetricCard icon={TrendingDown} label="已实现盈亏" value={signedMoney(summary.realized_pnl)} color={pnlColor(summary.realized_pnl)} />
      </div>

      {/* Metrics row 2 */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard icon={PiggyBank} label="总盈亏（浮动+已实现）" value={signedMoney(summary.total_pnl)} color={pnlColor(summary.total_pnl)} />
        <MetricCard icon={ArrowUpFromLine} label="累计买入 / 卖出" value={`${money(summary.total_buy)} / ${money(summary.total_sell)}`} />
        <MetricCard icon={Wallet} label="持仓数量" value={`${summary.holding_count} 个`} />
        <MetricCard icon={Calendar} label="净值日期" value={summary.as_of_date ?? "未更新"} />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">资产类型</CardTitle></CardHeader>
          <CardContent>
            {typeDist && typeDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={typeDist} dataKey="market_value" nameKey="fund_type" cx="50%" cy="50%" outerRadius={75} innerRadius={40} paddingAngle={2}>
                    {typeDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip content={<ChartTooltip />} />
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
                  <Tooltip content={<ChartTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">板块分布</CardTitle></CardHeader>
          <CardContent>
            {sectorDist && sectorDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={sectorDist.slice(0, 12)} layout="vertical" margin={{ left: 10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                  <XAxis type="number" tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} fontSize={11} tick={{ fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="sector" width={65} fontSize={11} tick={{ fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <Bar dataKey="market_value" fill="#1E40AF" radius={[0, 4, 4, 0]} barSize={14} />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: '#3B82F6', opacity: 0.08 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
