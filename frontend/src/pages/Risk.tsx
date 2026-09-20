import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { HealthReport, HealthDimension } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import ErrorState from "@/components/ErrorState"
import { Badge } from "@/components/ui/badge"
import { pct, pnlColor } from "@/lib/format"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { ShieldAlert, AlertTriangle, Info, Lightbulb, Activity } from "lucide-react"
import type { ReactNode } from "react"
import MetricCard from "@/components/MetricCard"
import { useLang } from "@/i18n/LanguageContext"
import { translateRiskFlag, translateAdvice } from "@/lib/backendLabels"

const FLAG_STYLES: Record<string, { icon: ReactNode; variant: "destructive" | "warning" | "default" }> = {
  danger: { icon: <ShieldAlert className="h-5 w-5 text-destructive" />, variant: "destructive" },
  warning: { icon: <AlertTriangle className="h-5 w-5 text-warning" />, variant: "warning" },
  info: { icon: <Info className="h-5 w-5 text-primary" />, variant: "default" },
}

const SCORE_COLOR: Record<string, string> = {
  excellent: "text-success",
  good: "text-success",
  fair: "text-warning",
  attention: "text-orange-500",
  danger: "text-destructive",
}

const STATUS_COLOR: Record<string, string> = {
  good: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
}

const BAR_BG: Record<string, string> = {
  excellent: "bg-success",
  good: "bg-success",
  fair: "bg-warning",
  attention: "bg-orange-500",
  danger: "bg-destructive",
}

const TIER_BG: Record<string, string> = {
  excellent: "bg-success/10",
  good: "bg-success/10",
  fair: "bg-warning/10",
  attention: "bg-orange-500/10",
  danger: "bg-destructive/10",
}

const STATUS_BAR: Record<string, string> = {
  good: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
}

export default function Risk() {
  const { data: hr, loading, error, reload } = useApi<HealthReport>(() => api.getHealthReport())
  const { t } = useLang()

  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !hr) return <LoadingState />

  const report = hr.risk_report
  const advice = hr.advice

  const tierLabels: Record<string, string> = {
    excellent: t.health.tierExcellent,
    good: t.health.tierGood,
    fair: t.health.tierFair,
    attention: t.health.tierAttention,
    danger: t.health.tierDanger,
  }
  const dimLabels: Record<string, string> = {
    allocation: t.health.allocation,
    risk: t.health.risk,
    liquidity: t.health.liquidity,
    return: t.health.return,
  }

  const dimMetric = (dim: HealthDimension): { label: string; value: string } | null => {
    const m = dim.metrics
    if (dim.name === "allocation") {
      const w = m.max_single_weight as number | undefined
      return w != null && w > 0 ? { label: t.risk.maxSingleWeight, value: pct(w) } : null
    }
    if (dim.name === "risk") {
      const dd = m.max_drawdown as number | null | undefined
      return dd != null ? { label: t.risk.maxDrawdown, value: pct(dd) } : null
    }
    if (dim.name === "liquidity") {
      const sw = m.stable_weight as number | undefined
      return sw != null ? { label: t.health.stableWeight, value: pct(sw) } : null
    }
    if (dim.name === "return") {
      const ar = m.annualized_return as number | null | undefined
      return ar != null ? { label: t.health.return, value: pct(ar) } : null
    }
    return null
  }

  const tierVariant = (tier: string) => {
    if (tier === "danger" || tier === "attention") return "destructive" as const
    if (tier === "fair") return "warning" as const
    return "default" as const
  }

  return (
    <div className="space-y-6">
      <PageHeader title={t.health.title} subtitle={t.health.subtitle} icon={<Activity className="h-5 w-5" />} />

      {/* 体检评级 Banner */}
      <Card className="card-hover">
        <CardContent className="p-4 md:p-5 flex items-center gap-4">
          <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full ${TIER_BG[hr.overall_tier] ?? "bg-muted"}`}>
            <span className={`text-2xl font-bold tabular-nums ${SCORE_COLOR[hr.overall_tier] ?? "text-primary"}`}>
              {hr.overall_score}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-muted-foreground">{t.health.overallScore}</p>
              <Badge variant={tierVariant(hr.overall_tier)}>{tierLabels[hr.overall_tier] ?? hr.overall_tier}</Badge>
            </div>
            <div className="mt-1.5 h-2 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${BAR_BG[hr.overall_tier] ?? "bg-primary"}`}
                style={{ width: `${Math.max(2, hr.overall_score)}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 四维评分卡 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        {hr.dimensions.map((dim) => {
          const metric = dimMetric(dim)
          return (
            <Card key={dim.name} className="card-hover overflow-hidden">
              <div className={`h-1 w-full ${STATUS_BAR[dim.status] ?? "bg-muted"}`} />
              <CardContent className="p-4 md:p-5 text-center">
                <p className="text-xs font-medium text-muted-foreground">{dimLabels[dim.name] ?? dim.name}</p>
                <p className={`mt-1 text-2xl font-bold tabular-nums ${STATUS_COLOR[dim.status] ?? "text-foreground"}`}>
                  {dim.score}
                </p>
                {metric && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {metric.label} {metric.value}
                  </p>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* 风险指标明细 */}
      <Card>
        <CardHeader><CardTitle className="text-base">{t.risk.title}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
            <MetricCard label={t.risk.maxDrawdown} value={report.max_drawdown != null ? pct(report.max_drawdown) : t.risk.insufficientData} color={pnlColor(report.max_drawdown ?? 0)} />
            <MetricCard label={t.risk.annualVolatility} value={report.volatility != null ? pct(report.volatility) : t.risk.insufficientData} />
            <MetricCard label={t.risk.maxSingleWeight} value={pct(report.max_single_weight)} sub={report.max_single_name} />
            <MetricCard label={t.risk.concentrationHHI} value={report.hhi.toFixed(3)} />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 md:gap-4">
            <MetricCard label={t.risk.equityWeight} value={pct(report.equity_weight)} />
            <MetricCard label={t.risk.bondWeight} value={pct(report.bond_weight)} />
            <MetricCard label={t.risk.qdiiWeight} value={pct(report.qdii_weight)} />
            <MetricCard label={t.health.stableWeight} value={pct(hr.stable_weight)} />
          </div>
        </CardContent>
      </Card>

      {/* 风险提示 */}
      <Card>
        <CardHeader><CardTitle className="text-base">{t.risk.riskFlags}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {report.flags.map((f, i) => {
            const style = FLAG_STYLES[f.level] ?? FLAG_STYLES.info
            const { title, detail } = translateRiskFlag(f)
            return (
              <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                {style.icon}
                <div>
                  <p className="font-medium">
                    <Badge variant={style.variant} className="mr-2">{title}</Badge>
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* 结构优化建议 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Lightbulb className="h-5 w-5 text-warning" />
            {t.risk.structureSuggestions}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t.risk.adviceDisclaimer}</p>
          {advice && advice.length > 0 ? (
            advice.map((a, i) => {
              const { category, text } = translateAdvice(a)
              return (
                <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary">
                    {i + 1}
                  </span>
                  <div>
                    <Badge variant="outline" className="mr-2">{category}</Badge>
                    <span className="text-sm text-muted-foreground">{text}</span>
                  </div>
                </div>
              )
            })
          ) : (
            <EmptyState title={t.risk.noSuggestions} size="sm" />
          )}
        </CardContent>
      </Card>
    </div>
  )
}