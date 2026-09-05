import { Fragment, useEffect, useState } from "react"
import { BarChart3, ChevronRight, PieChart as PieChartIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { IndustryExposure, IndustryFundContribution } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
  PieChart, Pie, ResponsiveContainer,
} from "recharts"
import { money, pct } from "@/lib/format"
import { chartColor } from "@/lib/chartPalette"
import { translateIndustry, translateFundType } from "@/lib/taxonomyLabels"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import { useLang } from "@/i18n/LanguageContext"

const UNPENETRATED_KEY = "__unpenetrated__"
const UNPENETRATED_COLOR = "hsl(var(--muted-foreground))"

function ExposureTooltip({
  active, payload, total,
}: { active?: boolean; payload?: Array<{ name?: string; value?: number }>; total: number }) {
  if (!active || !payload?.length) return null
  const v = (payload[0].value as number) ?? 0
  return (
    <div className="rounded-lg border bg-card px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-foreground">{payload[0].name}</p>
      <p className="text-sm font-bold tabular-nums text-primary">{money(v)}</p>
      <p className="text-xs tabular-nums text-muted-foreground">{pct(total > 0 ? v / total : 0)}</p>
    </div>
  )
}

function SummaryCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="card-hover">
      <CardContent className="p-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="mt-1 text-lg font-bold tabular-nums text-foreground">{value}</p>
        {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export default function IndustryExposurePanel() {
  const { t } = useLang()
  const [chartType, setChartType] = useState<"bar" | "pie">(() =>
    localStorage.getItem("zfundpilot_industryChartType") === "pie" ? "pie" : "bar")
  useEffect(() => { localStorage.setItem("zfundpilot_industryChartType", chartType) }, [chartType])
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const toggleIndustry = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }
  const { data, loading, error, reload } = useApi<IndustryExposure>(() => api.getIndustryExposure())

  if (loading) return <LoadingState size="md" />
  if (error || !data) return <ErrorState message={error ?? undefined} onRetry={reload} />
  if (!data.ok || (data.items.length === 0 && data.unpenetrated_market_value <= 0)) {
    return <EmptyState title={t.positions.noIndustryData} description={t.positions.noIndustryDataHint} />
  }

  const total = data.total_market_value
  const equityTotal = data.equity_total_market_value
  const equityCoverage = equityTotal > 0 ? data.equity_penetrated_market_value / equityTotal : 0
  const nonEquityMv = total - equityTotal

  const chartData = [
    ...data.items.map((item) => ({
      key: item.industry,
      name: translateIndustry(item.industry),
      market_value: item.market_value,
      isUnpenetrated: false,
      funds: item.funds ?? [],
    })),
    ...(data.unpenetrated_market_value > 0
      ? [{
          key: UNPENETRATED_KEY,
          name: t.positions.unpenetrated,
          market_value: data.unpenetrated_market_value,
          isUnpenetrated: true,
          funds: [] as IndustryFundContribution[],
        }]
      : []),
  ]

  const fillFor = (d: (typeof chartData)[number]) =>
    d.isUnpenetrated ? UNPENETRATED_COLOR : chartColor(chartData.indexOf(d))

  const fundsFor = (d: (typeof chartData)[number]) =>
    d.isUnpenetrated ? "—" : String(data.items.find((i) => i.industry === d.key)?.funds_count ?? 0)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <SummaryCard label={t.positions.equityCoverage} value={pct(equityCoverage)} sub={t.positions.equityCoverageHint} />
        <SummaryCard label={t.positions.penetratedFunds} value={`${data.funds_with_data} / ${data.funds_count}`} />
        <SummaryCard label={t.positions.reportQuarter} value={data.quarter || "—"} />
        <SummaryCard label={t.positions.unpenetrated} value={money(data.unpenetrated_market_value)} sub={t.positions.unpenetratedHint} />
        <SummaryCard label={t.positions.nonEquityFunds} value={money(nonEquityMv)} />
      </div>

      <p className="text-xs text-muted-foreground">{t.positions.industryExposureHint}</p>

      <Card className="card-hover">
        <CardHeader className="pb-2">
          <div className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.positions.industryExposure}</CardTitle>
            <div className="inline-flex rounded-lg border border-border p-0.5">
              <button
                type="button"
                onClick={() => setChartType("bar")}
                title={t.positions.chartBar}
                aria-pressed={chartType === "bar"}
                className={cn(
                  "flex items-center justify-center rounded-md p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                  chartType === "bar" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <BarChart3 className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setChartType("pie")}
                title={t.positions.chartPie}
                aria-pressed={chartType === "pie"}
                className={cn(
                  "flex items-center justify-center rounded-md p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                  chartType === "pie" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <PieChartIcon className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {chartType === "bar" ? (
            <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 24)}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 10, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" />
                <XAxis type="number" tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} fontSize={11} tick={{ fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={92} fontSize={11} tick={{ fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
                <Bar dataKey="market_value" radius={[0, 4, 4, 0]} barSize={12}>
                  {chartData.map((d) => <Cell key={d.key} fill={fillFor(d)} stroke="none" />)}
                </Bar>
                <Tooltip content={<ExposureTooltip total={total} />} cursor={{ fill: "hsl(var(--primary))", opacity: 0.08 }} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(260, chartData.length * 24)}>
              <PieChart>
                <Pie data={chartData} dataKey="market_value" nameKey="name" cx="50%" cy="50%" outerRadius={90} innerRadius={50} paddingAngle={2}>
                  {chartData.map((d) => <Cell key={d.key} fill={fillFor(d)} stroke="none" />)}
                </Pie>
                <Tooltip content={<ExposureTooltip total={total} />} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card className="card-hover">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">{t.positions.industry}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t.positions.industry}</TableHead>
                <TableHead className="text-right">{t.positions.industryMarketValue}</TableHead>
                <TableHead className="text-right">{t.positions.industryWeight}</TableHead>
                <TableHead className="text-right">{t.positions.fundsCovered}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {chartData.map((d) => (
                <Fragment key={d.key}>
                  <TableRow>
                    <TableCell className="w-8 p-2 pr-0">
                      {d.isUnpenetrated ? null : (
                        <button
                          type="button"
                          onClick={() => toggleIndustry(d.key)}
                          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                          aria-label={t.positions.expandIndustry}
                          aria-expanded={expanded.has(d.key)}
                        >
                          <ChevronRight className={cn("h-4 w-4 transition-transform duration-200", expanded.has(d.key) && "rotate-90")} />
                        </button>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: fillFor(d) }} />
                        <span>{d.name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{money(d.market_value)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(total > 0 ? d.market_value / total : 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fundsFor(d)}</TableCell>
                  </TableRow>
                  {!d.isUnpenetrated && expanded.has(d.key) && (
                    <TableRow className="bg-muted/30 border-t-0">
                      <TableCell colSpan={5} className="p-3 pt-0">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-muted-foreground">
                              <th className="py-1 text-left font-medium">{t.positions.fundName}</th>
                              <th className="py-1 text-right font-medium">{t.positions.contributionMv}</th>
                              <th className="py-1 text-right font-medium">{t.positions.shareOfIndustry}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {d.funds.map((f) => (
                              <tr key={f.fund_code} className="border-t border-border/60">
                                <td className="py-1.5">
                                  <span>{f.fund_name || f.fund_code}</span>
                                  {f.fund_name && <span className="ml-2 font-mono text-[10px] text-muted-foreground">{f.fund_code}</span>}
                                </td>
                                <td className="py-1.5 text-right tabular-nums">{money(f.market_value)}</td>
                                <td className="py-1.5 text-right tabular-nums">{pct(d.market_value > 0 ? f.market_value / d.market_value : 0)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {data.funds_missing.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer select-none text-sm font-medium text-muted-foreground hover:text-foreground">
            {t.positions.missingFunds} ({data.funds_missing.length})
            <span className="ml-2 text-xs text-muted-foreground">{t.positions.missingFundsHint}</span>
          </summary>
          <div className="mt-2">
            <Card className="card-hover">
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t.positions.fundCode}</TableHead>
                      <TableHead>{t.positions.fundName}</TableHead>
                      <TableHead>{t.positions.fundType}</TableHead>
                      <TableHead className="text-right">{t.positions.industryMarketValue}</TableHead>
                      <TableHead>{t.positions.missingFundsReason}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.funds_missing.map((m) => (
                      <TableRow key={m.fund_code}>
                        <TableCell className="font-mono text-xs">{m.fund_code}</TableCell>
                        <TableCell>{m.fund_name || m.fund_code}</TableCell>
                        <TableCell>
                          <span className={m.is_equity ? "text-foreground" : "text-muted-foreground"}>
                            {translateFundType(m.fund_type)}
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{money(m.market_value)}</TableCell>
                        <TableCell>
                          <span className={m.is_equity ? "text-amber-600" : "text-muted-foreground"}>
                            {m.is_equity
                              ? m.reason === "parse_error" ? t.positions.reasonParseError : t.positions.reasonNoData
                              : t.positions.expectedNoData}
                          </span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        </details>
      )}
    </div>
  )
}
