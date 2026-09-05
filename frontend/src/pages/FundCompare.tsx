import { useState, useCallback, useMemo, useEffect } from "react"
import { useSearchParams } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { FundCompareItem } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { translateFundType, translateSector } from "@/lib/taxonomyLabels"
import { translateMessage } from "@/lib/backendLabels"
import ErrorState from "@/components/ErrorState"
import { pct } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useLang } from "@/i18n/LanguageContext"
import { useCompare } from "@/contexts/CompareContext"
import { GitCompare, Search, BarChart3, Table2, TrendingUp, Activity, DollarSign, X, Trash2 } from "lucide-react"
import {
  LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from "recharts"
import { CHART_COLORS } from "@/lib/chartPalette"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

function AddSection({ loading }: { loading: boolean }) {
  const { t } = useLang()
  const { addCode, addCodes } = useCompare()
  const [raw, setRaw] = useState("")
  const [error, setError] = useState("")

  const handleAdd = () => {
    const codes = raw.split(/[,，\s\n]+/).map((s) => s.trim()).filter(Boolean)
    if (codes.length === 0) { setError(t.compare.enterCode); return }
    const invalid = codes.filter((c) => !/^\d{6}$/.test(c))
    if (invalid.length > 0) { setError(`${t.compare.invalidCode}${invalid.join(", ")}`); return }
    setError("")
    setRaw("")
    if (codes.length === 1) {
      addCode(codes[0])
    } else {
      addCodes(codes)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={raw}
          onChange={(e) => { setRaw(e.target.value); setError("") }}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) handleAdd() }}
          placeholder={t.compare.inputPlaceholder}
          className="h-9 text-sm flex-1"
        />
        <Button size="sm" onClick={handleAdd} disabled={loading}>
          <Search className="mr-1 h-4 w-4" />
          {t.compare.addFund}
        </Button>
      </div>
      {error && <p className="text-xs text-loss-600">{error}</p>}
    </div>
  )
}

function Cell({ value, suffix = "" }: { value: number | null | undefined; suffix?: string }) {
  if (value == null) return <span className="text-muted-foreground">—</span>
  const isPct = typeof value === "number" && suffix === "%"
  const display = isPct ? pct(value) : typeof value === "number" ? value.toLocaleString() : String(value)
  const color = isPct ? (value > 0 ? "text-gain-600" : value < 0 ? "text-loss-600" : "") : ""
  return <span className={cn("tabular-nums", color)}>{display}{!isPct ? suffix : ""}</span>
}

function ReturnCell({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-muted-foreground">—</span>
  const color = value > 0 ? "text-gain-600" : value < 0 ? "text-loss-600" : ""
  return <span className={cn("tabular-nums font-medium", color)}>{pct(value)}</span>
}

function CompareTable({ funds, labelMap, valueKey, format }: {
  funds: FundCompareItem[]
  labelMap: Record<string, string>
  valueKey: "returns" | "risk"
  format: "pct" | "number"
}) {
  const { t } = useLang()
  const keys = Object.keys(labelMap)
  return (
    <div className="overflow-x-auto rounded-md border">
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow className="bg-muted/50">
            <TableHead className="sticky left-0 bg-muted/50 px-3 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">{t.compare.metric}</TableHead>
            {funds.map((f) => (
              <TableHead key={f.code} className="px-3 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">{f.name || f.code}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => (
            <TableRow key={key} className="border-t border-border/50">
              <TableCell className="sticky left-0 bg-background px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{labelMap[key]}</TableCell>
              {funds.map((f) => (
                <TableCell key={f.code} className="px-3 py-2 text-right text-xs">
                  {format === "pct"
                    ? <ReturnCell value={f[valueKey]?.[key] as number | null | undefined} />
                    : <Cell value={f[valueKey]?.[key] as number | null | undefined} />
                  }
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function InfoTable({ funds }: { funds: FundCompareItem[] }) {
  const { t } = useLang()
  const rows = [
    { label: t.common.code, render: (f: FundCompareItem) => <span className="font-mono">{f.code}</span> },
    { label: t.common.name, render: (f: FundCompareItem) => f.name || "—" },
    { label: t.common.type, render: (f: FundCompareItem) => translateFundType(f.type) },
    { label: t.compare.sector, render: (f: FundCompareItem) => f.sector ? translateSector(f.sector) : "—" },
    { label: t.compare.inceptionDate, render: (f: FundCompareItem) => f.inception_date || "—" },
    { label: t.compare.scale, render: (f: FundCompareItem) => f.scale != null ? `${f.scale.toFixed(1)} ${t.compare.scaleUnit}` : "—" },
    { label: t.compare.manager, render: (f: FundCompareItem) => f.manager || "—" },
    { label: t.positions.latestNav, render: (f: FundCompareItem) => f.latest_nav != null ? f.latest_nav.toFixed(4) : "—" },
    { label: t.positions.navDate, render: (f: FundCompareItem) => f.latest_date || "—" },
    { label: t.compare.managementFee, render: (f: FundCompareItem) => f.management_fee != null ? pct(f.management_fee) : "—" },
    { label: t.compare.custodianFee, render: (f: FundCompareItem) => f.custodian_fee != null ? pct(f.custodian_fee) : "—" },
    { label: t.compare.salesFee, render: (f: FundCompareItem) => f.sales_fee != null ? pct(f.sales_fee) : "—" },
  ]
  return (
    <div className="overflow-x-auto rounded-md border">
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow className="bg-muted/50">
            <TableHead className="sticky left-0 bg-muted/50 px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.compare.metric}</TableHead>
            {funds.map((f) => (
              <TableHead key={f.code} className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">{f.name || f.code}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ label, render }) => (
            <TableRow key={label} className="border-t border-border/50">
              <TableCell className="sticky left-0 bg-background px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{label}</TableCell>
              {funds.map((f) => (
                <TableCell key={f.code} className="px-3 py-2 text-right text-xs">{render(f)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

const NAV_CHART_COLORS = CHART_COLORS

function NavChart({ navSeries }: { navSeries: Record<string, { date: string; value: number }[]> }) {
  const { t } = useLang()
  const codes = Object.keys(navSeries).filter((c) => navSeries[c].length > 0)
  if (codes.length === 0) return <EmptyState title={t.compare.noNavData} size="lg" />

  const merged = navSeries[codes[0]].map((p) => {
    const row: Record<string, string | number | null> = { date: p.date }
    row[codes[0]] = p.value
    return row
  })
  for (let i = 1; i < codes.length; i++) {
    const map = new Map(navSeries[codes[i]].map((p) => [p.date, p.value]))
    for (const row of merged) {
      row[codes[i]] = map.get(row.date as string) ?? null
    }
  }

  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={merged}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="date" fontSize={11} tick={{ fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
        <YAxis fontSize={11} tick={{ fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
          formatter={(value: number, name: string) => [value.toFixed(2), name]}
        />
        <Legend
          formatter={(value: string) => <span className="text-xs text-foreground">{value}</span>}
        />
        {codes.map((code, i) => (
          <Line
            key={code}
            type="monotone"
            dataKey={code}
            stroke={NAV_CHART_COLORS[i % NAV_CHART_COLORS.length]}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function CorrelationMatrix({ funds, correlations }: { funds: FundCompareItem[]; correlations: (number | null)[][] }) {
  const { t } = useLang()
  if (!correlations || correlations.length < 2) return <EmptyState title={t.compare.correlationHint} size="lg" />

  return (
    <div className="overflow-x-auto">
      <Table className="mx-auto text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="px-2 py-1" />
            {funds.map((f) => (
              <TableHead key={f.code} className="px-2 py-1 text-xs text-muted-foreground font-medium max-w-[80px] truncate" title={f.name}>
                {f.code}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {funds.map((f, i) => (
            <TableRow key={f.code}>
              <TableCell className="px-2 py-1 text-xs text-muted-foreground font-medium max-w-[80px] truncate" title={f.name}>
                {f.code}
              </TableCell>
              {funds.map((_, j) => {
                const v = correlations[i][j]
                const intensity = v != null ? Math.abs(v) : 0
                const bg = v != null
                  ? v >= 0
                    ? `hsl(var(--chart-3) / ${Math.max(0.08, intensity)})`
                    : `hsl(var(--chart-2) / ${Math.max(0.08, intensity)})`
                  : "transparent"
                return (
                  <TableCell
                    key={j}
                    className="px-2 py-1 text-center text-xs tabular-nums font-medium"
                    style={{ background: bg, color: intensity > 0.5 ? "white" : "hsl(var(--foreground))" }}
                    title={`${f.name} vs ${funds[j].name}: ${v != null ? v.toFixed(3) : "—"}`}
                  >
                    {v != null ? v.toFixed(2) : "—"}
                  </TableCell>
                )
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-2 flex items-center justify-center gap-2 text-[10px] text-muted-foreground">
        <span>{t.compare.negativeCorrelation}</span>
        <div className="flex h-3 w-32 rounded overflow-hidden border border-border">
          <div className="h-full flex-1" style={{ background: "hsl(var(--chart-2))" }} />
          <div className="h-full flex-1" style={{ background: "hsl(var(--chart-2) / 0.6)" }} />
          <div className="h-full flex-1" style={{ background: "hsl(var(--muted))" }} />
          <div className="h-full flex-1" style={{ background: "hsl(var(--chart-3) / 0.6)" }} />
          <div className="h-full flex-1" style={{ background: "hsl(var(--chart-3))" }} />
        </div>
        <span>{t.compare.positiveCorrelation}</span>
      </div>
    </div>
  )
}

export default function FundCompare() {
  const { t } = useLang()
  const [searchParams, setSearchParams] = useSearchParams()
  const { codes, addCodes, removeCode, clear, count } = useCompare()

  useEffect(() => {
    const q = searchParams.get("codes") || ""
    const urlCodes = q.split(",").filter((c) => /^\d{6}$/.test(c))
    if (urlCodes.length > 0) {
      addCodes(urlCodes)
      setSearchParams({}, { replace: true })
    }
  }, [])

  const RISK_LABELS: Record<string, string> = {
    max_drawdown: t.compare.maxDrawdown,
    volatility: t.compare.annualVolatility,
    sharpe: t.compare.sharpeRatio,
    calmar: t.compare.calmarRatio,
    win_rate: t.compare.winRate,
  }

  const fetcher = useCallback(() => {
    if (codes.length === 0) return Promise.resolve(null)
    return api.compareFunds(codes)
  }, [codes])

  const { data, loading, error, reload } = useApi(fetcher, [codes.join(",")])

  const okFunds = useMemo(() => data?.funds?.filter((f) => f.ok) ?? [], [data])
  const failedFunds = useMemo(() => data?.funds?.filter((f) => !f.ok) ?? [], [data])

  return (
    <div className="space-y-6">
      <PageHeader title={t.compare.title} icon={<GitCompare className="h-5 w-5" />} />

      <Card>
        <CardContent className="p-4">
          <AddSection loading={loading} />
        </CardContent>
      </Card>

      {count > 0 && (
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs text-muted-foreground">
                {t.compare.resultCount.replace("{total}", String(count)).replace("{shown}", String(count))}
              </p>
              <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground" onClick={clear}>
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                {t.common.clear}
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {codes.map((code) => (
                <Badge key={code} variant="secondary" className="gap-1.5 pl-2 pr-1 py-1 text-xs font-normal">
                  <span className="font-mono">{code}</span>
                  <button
                    onClick={() => removeCode(code)}
                    title={t.compare.removeFund}
                    className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20 transition-colors"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {error && <ErrorState message={error} onRetry={reload} />}

      {loading && (
        <LoadingState className="min-h-[40vh]" />
      )}

      {!loading && !error && data && !data.ok && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">{translateMessage(data.msg_code, data.message)}</CardContent>
        </Card>
      )}

      {!loading && !error && data && data.ok && okFunds.length === 0 && count > 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            {t.compare.startCompare}
          </CardContent>
        </Card>
      )}

      {!loading && !error && count === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            {t.compare.noFundsHint}
          </CardContent>
        </Card>
      )}

      {!loading && !error && data && data.ok && okFunds.length > 0 && (
        <>
          {failedFunds.length > 0 && (
            <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              {t.compare.fetchFailed}{failedFunds.map((f) => `${f.code}(${translateMessage(f.msg_code, f.message)})`).join("；")}
            </div>
          )}

          <Tabs defaultValue="info">
            <TabsList className="grid w-full grid-cols-5 sm:inline-flex sm:w-auto">
              <TabsTrigger value="info" className="gap-1"><Table2 className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t.compare.basicInfo}</span></TabsTrigger>
              <TabsTrigger value="returns" className="gap-1"><TrendingUp className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t.compare.returnPerformance}</span></TabsTrigger>
              <TabsTrigger value="risk" className="gap-1"><Activity className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t.compare.riskCompare}</span></TabsTrigger>
              <TabsTrigger value="chart" className="gap-1"><BarChart3 className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t.compare.navTrend}</span></TabsTrigger>
              <TabsTrigger value="correlation" className="gap-1"><DollarSign className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t.compare.correlation}</span></TabsTrigger>
            </TabsList>

            <TabsContent value="info" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t.compare.basicInfo}</CardTitle></CardHeader>
                <CardContent><InfoTable funds={okFunds} /></CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="returns" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t.compare.returnPerformance}</CardTitle></CardHeader>
                <CardContent>
                  <CompareTable funds={okFunds} labelMap={{ ...t.periodLabels }} valueKey="returns" format="pct" />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="risk" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t.compare.riskCompare}</CardTitle></CardHeader>
                <CardContent>
                  <CompareTable funds={okFunds} labelMap={RISK_LABELS} valueKey="risk" format="pct" />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="chart" className="mt-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{t.compare.navTrendNormalized}</CardTitle>
                </CardHeader>
                <CardContent>
                  <NavChart navSeries={data.nav_series ?? {}} />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="correlation" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t.compare.correlation}</CardTitle></CardHeader>
                <CardContent>
                  <CorrelationMatrix funds={okFunds} correlations={data.correlations ?? []} />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  )
}