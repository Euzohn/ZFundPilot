import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { IndustryExposure } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
  PieChart, Pie, ResponsiveContainer,
} from "recharts"
import { money, pct } from "@/lib/format"
import { chartColor } from "@/lib/chartPalette"
import { translateIndustry } from "@/lib/taxonomyLabels"
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
  const { data, loading, error, reload } = useApi<IndustryExposure>(() => api.getIndustryExposure())

  if (loading) return <LoadingState size="md" />
  if (error || !data) return <ErrorState message={error ?? undefined} onRetry={reload} />
  if (!data.ok || (data.items.length === 0 && data.unpenetrated_market_value <= 0)) {
    return <EmptyState title={t.positions.noIndustryData} description={t.positions.noIndustryDataHint} />
  }

  const total = data.total_market_value
  const coverage = total > 0 ? data.penetrated_market_value / total : 0

  const chartData = [
    ...data.items.map((item) => ({
      key: item.industry,
      name: translateIndustry(item.industry),
      market_value: item.market_value,
      isUnpenetrated: false,
    })),
    ...(data.unpenetrated_market_value > 0
      ? [{
          key: UNPENETRATED_KEY,
          name: t.positions.unpenetrated,
          market_value: data.unpenetrated_market_value,
          isUnpenetrated: true,
        }]
      : []),
  ]

  const fillFor = (d: (typeof chartData)[number]) =>
    d.isUnpenetrated ? UNPENETRATED_COLOR : chartColor(chartData.indexOf(d))

  const fundsFor = (d: (typeof chartData)[number]) =>
    d.isUnpenetrated ? "—" : String(data.items.find((i) => i.industry === d.key)?.funds_count ?? 0)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryCard label={t.positions.lookThroughCoverage} value={pct(coverage)} />
        <SummaryCard label={t.positions.penetratedFunds} value={`${data.funds_with_data} / ${data.funds_count}`} />
        <SummaryCard label={t.positions.reportQuarter} value={data.quarter || "—"} />
        <SummaryCard label={t.positions.unpenetrated} value={money(data.unpenetrated_market_value)} sub={t.positions.unpenetratedHint} />
      </div>

      <p className="text-xs text-muted-foreground">{t.positions.industryExposureHint}</p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="card-hover lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.positions.industryExposure}</CardTitle>
          </CardHeader>
          <CardContent>
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
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.positions.industryWeight}</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 24)}>
              <PieChart>
                <Pie data={chartData} dataKey="market_value" nameKey="name" cx="50%" cy="50%" outerRadius={90} innerRadius={50} paddingAngle={2}>
                  {chartData.map((d) => <Cell key={d.key} fill={fillFor(d)} stroke="none" />)}
                </Pie>
                <Tooltip content={<ExposureTooltip total={total} />} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card className="card-hover">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">{t.positions.industry}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.positions.industry}</TableHead>
                <TableHead className="text-right">{t.positions.industryMarketValue}</TableHead>
                <TableHead className="text-right">{t.positions.industryWeight}</TableHead>
                <TableHead className="text-right">{t.positions.fundsCovered}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {chartData.map((d) => (
                <TableRow key={d.key}>
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
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
