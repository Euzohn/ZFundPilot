import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { HealthReport, HealthDimension, DistributionItem, Advice } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import ErrorState from "@/components/ErrorState"
import { Badge } from "@/components/ui/badge"
import { pct, pnlColor, money } from "@/lib/format"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { ShieldAlert, AlertTriangle, Info, Lightbulb, Activity, ChevronDown, ArrowUp, ArrowDown } from "lucide-react"
import { useState, type ReactNode } from "react"
import MetricCard from "@/components/MetricCard"
import { useLang } from "@/i18n/LanguageContext"
import {
  translateRiskFlag, translateAdvice, translateAdviceMetric,
  translateSimulationMetric, translateSimulationRule, translateAdviceRisk,
} from "@/lib/backendLabels"
import { translateRiskLevel, RISK_LEVEL_DOT, RISK_LEVEL_ORDER } from "@/lib/taxonomyLabels"
import { cn } from "@/lib/utils"

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

// 可演算的建议类型（simulation 为空时提示「无法演算」）
const ADJUSTMENT_CODES = new Set([
  "concentration_high", "concentration_mid", "equity_heavy",
  "bond_low", "qdii_high", "sector_concentrated", "tech_heavy",
])

function fmtSimMetric(key: string, value: number): string {
  return key === "allocation_score" ? String(Math.round(value)) : pct(value)
}

/** 行动清单条目：结论 + 可展开四段（依据/涉及持仓/模拟调整前后/风险限制）。 */
function AdviceItem({ advice: a, index }: { advice: Advice; index: number }) {
  const { t } = useLang()
  const [open, setOpen] = useState(false)
  const { category, text } = translateAdvice(a)
  const evidence = a.evidence ?? []
  const positions = a.positions ?? []
  const risks = a.risks ?? []
  const sim = a.simulation ?? null
  const hasDetails = evidence.length > 0 || positions.length > 0 || sim !== null || risks.length > 0
  const showUnavailable = !sim && ADJUSTMENT_CODES.has(a.code)

  return (
    <div className="rounded-md border p-3">
      <div className="flex items-start gap-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <Badge variant="outline" className="mr-2">{category}</Badge>
          <span className="text-sm text-muted-foreground">{text}</span>
        </div>
        {hasDetails && (
          <button
            type="button"
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
            aria-controls={`advice-detail-${index}`}
            className="flex shrink-0 items-center gap-1 rounded p-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {open ? t.risk.collapse : t.risk.expand}
            <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </div>
      {open && hasDetails && (
        <div id={`advice-detail-${index}`} className="mt-3 space-y-3 border-t pt-3 text-sm">
          {evidence.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">{t.risk.evidence}</p>
              <ul className="space-y-1">
                {evidence.map((e, i) => (
                  <li key={i} className="text-muted-foreground">
                    {translateAdviceMetric(e.metric)}
                    {e.params?.sector ? ` · ${e.params.sector}` : ""}
                    ：<span className="font-medium text-foreground">{pct(e.value)}</span>
                    {e.threshold != null && <>，{t.risk.threshold} {Math.round(e.threshold * 100)}%</>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {positions.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">{t.risk.involvedPositions}</p>
              <ul className="space-y-1">
                {positions.map((p, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 text-muted-foreground">
                    <span className="truncate">
                      {p.name}{p.channel ? ` · ${p.channel}` : ""}
                    </span>
                    <span className="shrink-0 tabular-nums">{pct(p.weight)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(sim || showUnavailable) && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">{t.risk.simulation}</p>
              {sim ? (
                <>
                  <p className="text-xs text-muted-foreground">{translateSimulationRule(sim.rule, sim.params)}</p>
                  <table className="mt-1 w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground">
                        <th className="pb-1 text-left font-normal">{t.risk.simMetric}</th>
                        <th className="pb-1 text-right font-normal">{t.risk.before}</th>
                        <th className="pb-1 text-right font-normal">{t.risk.after}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.keys(sim.before).map(k => (
                        <tr key={k} className="border-t border-border/50">
                          <td className="py-1 text-muted-foreground">{translateSimulationMetric(k)}</td>
                          <td className="py-1 text-right tabular-nums">{fmtSimMetric(k, sim.before[k])}</td>
                          <td className="py-1 text-right font-medium tabular-nums">
                            {fmtSimMetric(k, sim.after[k])}
                            {sim.after[k] - sim.before[k] > 1e-9 && (
                              <ArrowUp className="ml-0.5 inline h-3 w-3 text-muted-foreground" />
                            )}
                            {sim.before[k] - sim.after[k] > 1e-9 && (
                              <ArrowDown className="ml-0.5 inline h-3 w-3 text-muted-foreground" />
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-1 text-xs text-muted-foreground">{t.risk.simulationNote}</p>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">{t.risk.simulationUnavailable}</p>
              )}
            </div>
          )}
          {risks.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">{t.risk.risks}</p>
              <ul className="list-disc space-y-1 pl-4">
                {risks.map((r, i) => (
                  <li key={i} className="text-xs text-muted-foreground">{translateAdviceRisk(r)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Risk() {
  const { data: hr, loading, error, reload } = useApi<HealthReport>(() => api.getHealthReport())
  const { data: riskDist, loading: riskDistLoading } = useApi<DistributionItem[]>(() => api.getDistribution("risk_level"))
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

      {/* 持仓风险等级分布 */}
      <Card>
        <CardHeader><CardTitle className="text-base">{t.risk.riskLevelDist}</CardTitle></CardHeader>
        <CardContent>
          {riskDistLoading ? <LoadingState size="sm" /> : riskDist && riskDist.length > 0 ? (
            <div className="space-y-3">
              {[
                ...RISK_LEVEL_ORDER.filter(level => riskDist.some(d => String(d.risk_level) === level)),
                ...riskDist.map(d => String(d.risk_level)).filter(level => !RISK_LEVEL_ORDER.includes(level)),
              ].map(level => {
                const item = riskDist.find(d => String(d.risk_level) === level)!
                const weight = item.weight as number
                return (
                  <div key={level} className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5 w-20 shrink-0">
                      <span className={`h-2 w-2 rounded-full ${RISK_LEVEL_DOT[level] ?? "bg-zinc-400"}`} />
                      <span className="text-sm">{translateRiskLevel(level)}</span>
                    </div>
                    <div className="flex-1 h-6 rounded-full bg-muted/50 overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all", RISK_LEVEL_DOT[level] ?? "bg-zinc-400")}
                        style={{ width: `${Math.max(2, weight * 100)}%` }}
                      />
                    </div>
                    <span className="text-sm tabular-nums w-12 text-right">{pct(weight)}</span>
                    <span className="text-xs tabular-nums text-muted-foreground w-20 text-right">{money(item.market_value as number)}</span>
                  </div>
                )
              })}
            </div>
          ) : <EmptyState title={t.common.noData} size="sm" />}
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

      {/* 行动清单（可解释结构建议） */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Lightbulb className="h-5 w-5 text-warning" />
            {t.risk.actionList}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t.risk.adviceDisclaimer}</p>
          <p className="text-xs text-muted-foreground">{t.risk.actionListHint}</p>
          {advice && advice.length > 0 ? (
            advice.map((a, i) => <AdviceItem key={i} advice={a} index={i} />)
          ) : (
            <EmptyState title={t.risk.noSuggestions} size="sm" />
          )}
        </CardContent>
      </Card>
    </div>
  )
}