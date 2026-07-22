import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { RiskReport, Advice } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import { Badge } from "@/components/ui/badge"
import { pct, pnlColor } from "@/lib/format"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { ShieldAlert, AlertTriangle, Info, Lightbulb } from "lucide-react"
import type { ReactNode } from "react"
import MetricCard from "@/components/MetricCard"

const FLAG_STYLES: Record<string, { icon: ReactNode; variant: "destructive" | "warning" | "default" }> = {
  danger: { icon: <ShieldAlert className="h-5 w-5 text-destructive" />, variant: "destructive" },
  warning: { icon: <AlertTriangle className="h-5 w-5 text-warning" />, variant: "warning" },
  info: { icon: <Info className="h-5 w-5 text-primary" />, variant: "default" },
}

export default function Risk() {
  const { data: report, loading: rl, error: re, reload: reloadReport } = useApi<RiskReport>(() => api.getRiskReport())
  const { data: advice, loading: al } = useApi<Advice[]>(() => api.getRebalanceAdvice())

  if (re) return <ErrorState message={re} onRetry={reloadReport} />
  if (rl || !report) return <LoadingState />

  return (
    <div className="space-y-6">
      <PageHeader title="风险与建议" />

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <MetricCard label="最大回撤" value={report.max_drawdown != null ? pct(report.max_drawdown) : "数据不足"} color={pnlColor(report.max_drawdown ?? 0)} />
        <MetricCard label="年化波动率" value={report.volatility != null ? pct(report.volatility) : "数据不足"} />
        <MetricCard label="最大单基金占比" value={pct(report.max_single_weight)} sub={report.max_single_name} />
        <MetricCard label="集中度 HHI" value={report.hhi.toFixed(3)} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 md:gap-4">
        <MetricCard label="权益类占比" value={pct(report.equity_weight)} />
        <MetricCard label="债券类占比" value={pct(report.bond_weight)} />
        <MetricCard label="QDII 占比" value={pct(report.qdii_weight)} />
      </div>

      {/* Risk flags */}
      <Card>
        <CardHeader><CardTitle className="text-base">风险提示</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {report.flags.map((f, i) => {
            const style = FLAG_STYLES[f.level] ?? FLAG_STYLES.info
            return (
              <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                {style.icon}
                <div>
                  <p className="font-medium">
                    <Badge variant={style.variant} className="mr-2">{f.title}</Badge>
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">{f.detail}</p>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* Rebalance advice */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Lightbulb className="h-5 w-5 text-warning" />
            结构优化建议
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">以下为组合结构建议，非交易指令。</p>
          {al && advice && advice.length > 0 ? (
            advice.map((a, i) => (
              <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary">
                  {i + 1}
                </span>
                <div>
                  <Badge variant="outline" className="mr-2">{a.category}</Badge>
                  <span className="text-sm text-muted-foreground">{a.text}</span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState title="暂无建议" size="sm" />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
