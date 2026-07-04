import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary, DistributionItem } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts"
import { Wallet, TrendingUp, TrendingDown, DollarSign, PiggyBank, ArrowDownToLine, ArrowUpFromLine, Calendar } from "lucide-react"

const PIE_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#6366f1"]

function MetricCard({ icon: Icon, label, value, sub, color }: {
  icon: React.ElementType; label: string; value: string; sub?: string; color?: string
}) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className={`mt-1 text-xl font-bold ${color ?? ""}`}>{value}</p>
          {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
        </div>
        <Icon className="h-8 w-8 text-slate-300" />
      </CardContent>
    </Card>
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
          <CardContent className="py-16 text-center text-muted-foreground">
            还没有交易记录。请到「交易管理」添加买入/卖出流水或导入 CSV。
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">组合总览</h1>
        {summary.max_single_name && (
          <p className="text-sm text-muted-foreground">
            最大单持仓：{summary.max_single_name} 占比 {pct(summary.max_single_weight)}
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
        <Card>
          <CardHeader><CardTitle className="text-base">资产类型</CardTitle></CardHeader>
          <CardContent>
            {typeDist && typeDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie data={typeDist} dataKey="market_value" nameKey="fund_type" cx="50%" cy="50%" outerRadius={80} innerRadius={40} label>
                    {typeDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => money(v)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">渠道分布</CardTitle></CardHeader>
          <CardContent>
            {channelDist && channelDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie data={channelDist.map(d => ({ ...d, channel: d.channel || "未标注" }))} dataKey="market_value" nameKey="channel" cx="50%" cy="50%" outerRadius={80} innerRadius={40} label>
                    {channelDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => money(v)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">板块分布</CardTitle></CardHeader>
          <CardContent>
            {sectorDist && sectorDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={sectorDist.slice(0, 12)} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tickFormatter={(v: number) => `¥${(v / 1000).toFixed(0)}k`} fontSize={12} />
                  <YAxis type="category" dataKey="sector" width={70} fontSize={11} />
                  <Bar dataKey="market_value" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  <Tooltip formatter={(v: number) => money(v)} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="py-12 text-center text-sm text-muted-foreground">暂无数据</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
