import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { api } from "@/api/client"
import type {
  IndexValuation,
  IndexValuationListResponse,
  TrackedFund,
  ValuationHistoryResponse,
} from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import { makeSortHeader } from "@/components/SortHeader"
import { translateIndexTag } from "@/lib/taxonomyLabels"
import { cn } from "@/lib/utils"
import { useLang } from "@/i18n/LanguageContext"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChevronDown, ChevronRight, Gauge, Loader2, RefreshCw } from "lucide-react"

type SortField = "name" | "pe_percentile" | "pb_percentile" | "temperature"

// 温度徽章配色（低估绿 / 合理灰 / 高估红）
const TEMP_STYLE: Record<string, string> = {
  low: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  fair: "border-slate-400/30 bg-slate-400/10 text-slate-600 dark:text-slate-300",
  high: "border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400",
  unknown: "border-border bg-muted text-muted-foreground",
}

const TEMP_RANK: Record<string, number> = { low: 0, fair: 1, high: 2, unknown: -1 }

function fmtTime(iso: string): string {
  return iso ? iso.replace("T", " ").slice(0, 16) : "—"
}

/** 百分位单元格：数值 + 迷你进度条（<30 绿 / >70 红 / 其余灰）。 */
function PercentileCell({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-muted-foreground">—</span>
  }
  const color = value < 30 ? "bg-emerald-500" : value > 70 ? "bg-rose-500" : "bg-slate-400"
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", color)}
          style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
        />
      </div>
      <span className="w-12 text-right tabular-nums">{value.toFixed(1)}%</span>
    </div>
  )
}

function TemperatureBadge({ temperature }: { temperature: string }) {
  const { t } = useLang()
  const label =
    temperature === "low"
      ? t.valuation.tempLow
      : temperature === "fair"
        ? t.valuation.tempFair
        : temperature === "high"
          ? t.valuation.tempHigh
          : t.valuation.tempUnknown
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap",
        TEMP_STYLE[temperature] ?? TEMP_STYLE.unknown,
      )}
    >
      {label}
    </span>
  )
}

export default function Valuation() {
  const { t } = useLang()

  const [data, setData] = useState<IndexValuationListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState("")
  const [sortField, setSortField] = useState<SortField>("pe_percentile")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")

  const [expanded, setExpanded] = useState("")
  const [history, setHistory] = useState<Record<string, ValuationHistoryResponse>>({})
  const [historyLoading, setHistoryLoading] = useState<Record<string, boolean>>({})
  const [historyError, setHistoryError] = useState<Record<string, string>>({})
  const [funds, setFunds] = useState<Record<string, TrackedFund[]>>({})
  const [fundsLoading, setFundsLoading] = useState<Record<string, boolean>>({})

  const load = useCallback(
    async (force: boolean) => {
      if (force) setRefreshing(true)
      else setLoading(true)
      setError("")
      try {
        const res = await api.getIndexValuations(force)
        setData(res)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : t.valuation.loadFailed)
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [t.valuation.loadFailed],
  )

  useEffect(() => {
    load(false)
  }, [load])

  const toggleExpand = (code: string) => {
    if (expanded === code) {
      setExpanded("")
      return
    }
    setExpanded(code)

    if (!history[code]) {
      setHistoryLoading((prev) => ({ ...prev, [code]: true }))
      setHistoryError((prev) => ({ ...prev, [code]: "" }))
      api
        .getIndexValuationHistory(code)
        .then((res) => setHistory((prev) => ({ ...prev, [code]: res })))
        .catch((e: unknown) =>
          setHistoryError((prev) => ({
            ...prev,
            [code]: e instanceof Error ? e.message : t.valuation.historyFailed,
          })),
        )
        .finally(() => setHistoryLoading((prev) => ({ ...prev, [code]: false })))
    }

    if (!funds[code]) {
      setFundsLoading((prev) => ({ ...prev, [code]: true }))
      api
        .getIndexValuationFunds(code)
        .then((res) => setFunds((prev) => ({ ...prev, [code]: res.funds })))
        .catch(() => setFunds((prev) => ({ ...prev, [code]: [] })))
        .finally(() => setFundsLoading((prev) => ({ ...prev, [code]: false })))
    }
  }

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field as SortField)
      setSortDir("asc")
    }
  }

  const sorted = useMemo(() => {
    const items = data ? [...data.indices] : []
    items.sort((a, b) => {
      let va: number | string
      let vb: number | string
      if (sortField === "name") {
        va = a.index_name
        vb = b.index_name
      } else if (sortField === "temperature") {
        va = TEMP_RANK[a.temperature] ?? -1
        vb = TEMP_RANK[b.temperature] ?? -1
      } else {
        va = a[sortField] ?? Infinity
        vb = b[sortField] ?? Infinity
      }
      const cmp =
        typeof va === "string"
          ? va.localeCompare(vb as string)
          : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
    return items
  }, [data, sortField, sortDir])

  const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })

  const windowLabel = (window: string) =>
    window === "all" ? t.valuation.windowAll : t.valuation.window10y

  const renderExpanded = (item: IndexValuation) => {
    const code = item.index_code
    const detail = history[code]
    const isLoading = historyLoading[code]
    const err = historyError[code]
    const tracked = funds[code] ?? []
    const fundsBusy = fundsLoading[code]

    return (
      <TableRow key={`${code}-detail`} className="bg-muted/20 hover:bg-muted/20">
        <TableCell colSpan={10} className="p-4">
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-xs font-medium text-foreground">
                {t.valuation.historyTitle.replace(
                  "{window}",
                  detail ? windowLabel(detail.index.window) : windowLabel(item.window),
                )}
              </p>
              {isLoading && <LoadingState size="sm" />}
              {!isLoading && err && (
                <p className="text-xs text-loss-600">{err}</p>
              )}
              {!isLoading && !err && detail && detail.points.length > 0 && (
                <div className="h-[260px]">
                  <ResponsiveContainer width="100%" height={260}>
                    <LineChart data={detail.points}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis
                        dataKey="date"
                        fontSize={10}
                        tick={{ fill: "hsl(var(--muted-foreground))" }}
                        axisLine={false}
                        tickLine={false}
                        minTickGap={48}
                      />
                      <YAxis
                        domain={[0, 100]}
                        fontSize={10}
                        tick={{ fill: "hsl(var(--muted-foreground))" }}
                        axisLine={false}
                        tickLine={false}
                        width={36}
                        tickFormatter={(value: number) => `${value}%`}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "hsl(var(--card))",
                          border: "1px solid hsl(var(--border))",
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                        formatter={(value: number | string, name: string) => [
                          `${Number(value).toFixed(1)}%`,
                          name,
                        ]}
                      />
                      <Legend
                        formatter={(value: string) => (
                          <span className="text-xs text-foreground">{value}</span>
                        )}
                      />
                      <ReferenceLine
                        y={30}
                        stroke="hsl(var(--muted-foreground))"
                        strokeDasharray="4 4"
                      />
                      <ReferenceLine
                        y={70}
                        stroke="hsl(var(--muted-foreground))"
                        strokeDasharray="4 4"
                      />
                      <Line
                        type="monotone"
                        dataKey="pe_percentile"
                        name={t.valuation.chartPe}
                        stroke="#3b82f6"
                        strokeWidth={1.8}
                        dot={false}
                        connectNulls
                      />
                      <Line
                        type="monotone"
                        dataKey="pb_percentile"
                        name={t.valuation.chartPb}
                        stroke="#f59e0b"
                        strokeWidth={1.8}
                        dot={false}
                        connectNulls
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              {!isLoading && !err && detail && detail.points.length === 0 && (
                <p className="text-xs text-muted-foreground">{t.valuation.empty}</p>
              )}
            </div>

            <div>
              <p className="mb-2 text-xs font-medium text-foreground">
                {t.valuation.trackingFunds}
                {fundsBusy && (
                  <Loader2 className="ml-1 inline h-3 w-3 animate-spin text-muted-foreground" />
                )}
              </p>
              {!fundsBusy && tracked.length === 0 && (
                <p className="text-xs text-muted-foreground">{t.valuation.noFunds}</p>
              )}
              {tracked.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {tracked.map((fund) => (
                    <Link
                      key={fund.code}
                      to={`/fund/${fund.code}`}
                      className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs transition-colors hover:bg-accent"
                    >
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {fund.code}
                      </span>
                      <span className="truncate">{fund.name}</span>
                      {fund.index_tag && (
                        <span className="shrink-0 text-[10px] text-muted-foreground">
                          {translateIndexTag(fund.index_tag)}
                        </span>
                      )}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </TableCell>
      </TableRow>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t.valuation.title}
        subtitle={t.valuation.subtitle}
        icon={<Gauge className="h-5 w-5" />}
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => load(true)}
            disabled={loading || refreshing}
          >
            {refreshing ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-4 w-4" />
            )}
            {t.valuation.refresh}
          </Button>
        }
      />

      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">{t.valuation.note}</p>
        <p className="text-xs text-muted-foreground">
          {data?.as_of
            ? t.valuation.asOf.replace("{date}", data.as_of)
            : t.valuation.expandHint}
        </p>
      </div>

      {data?.degraded && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          {t.valuation.degraded}
        </div>
      )}

      {loading && (
        <Card>
          <CardContent className="py-16">
            <LoadingState />
          </CardContent>
        </Card>
      )}

      {!loading && error && (
        <Card>
          <CardContent>
            <ErrorState message={error} onRetry={() => load(false)} />
          </CardContent>
        </Card>
      )}

      {!loading && !error && data && data.indices.length === 0 && (
        <Card>
          <CardContent className="py-16">
            <EmptyState title={t.valuation.empty} size="lg" />
          </CardContent>
        </Card>
      )}

      {!loading && !error && sorted.length > 0 && (
        <div className="overflow-x-auto rounded-md border">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead className="w-6 px-1 py-2" />
                <SortHeader
                  field="name"
                  className="px-2 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap"
                >
                  {t.valuation.index}
                </SortHeader>
                <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">
                  {t.common.code}
                </TableHead>
                <TableHead className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">
                  {t.valuation.pe}
                </TableHead>
                <SortHeader
                  field="pe_percentile"
                  className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap"
                >
                  {t.valuation.pePercentile}
                </SortHeader>
                <TableHead className="px-2 py-2 text-right text-xs font-medium text-muted-foreground">
                  {t.valuation.pb}
                </TableHead>
                <SortHeader
                  field="pb_percentile"
                  className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap"
                >
                  {t.valuation.pbPercentile}
                </SortHeader>
                <SortHeader
                  field="temperature"
                  className="px-2 py-2 text-center text-xs font-medium text-muted-foreground whitespace-nowrap"
                >
                  {t.valuation.temperature}
                </SortHeader>
                <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">
                  {t.valuation.dataDate}
                </TableHead>
                <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">
                  {t.valuation.updatedAt}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((item) => (
                <FragmentRow
                  key={item.index_code}
                  item={item}
                  expanded={expanded === item.index_code}
                  onToggle={() => toggleExpand(item.index_code)}
                  windowLabel={windowLabel}
                  historyMonths={t.valuation.historyMonths}
                  staleLabel={t.valuation.stale}
                  unavailableLabel={t.valuation.unavailable}
                  renderExpanded={renderExpanded}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

/** 主行 + 展开行（fragment 两行，避免在 map 中手写 key）。 */
function FragmentRow({
  item,
  expanded,
  onToggle,
  windowLabel,
  historyMonths,
  staleLabel,
  unavailableLabel,
  renderExpanded,
}: {
  item: IndexValuation
  expanded: boolean
  onToggle: () => void
  windowLabel: (window: string) => string
  historyMonths: string
  staleLabel: string
  unavailableLabel: string
  renderExpanded: (item: IndexValuation) => ReactNode
}) {
  return (
    <>
      <TableRow
        className={cn("cursor-pointer border-t border-border/50", expanded && "bg-muted/30")}
        onClick={onToggle}
      >
        <TableCell className="px-1 py-1.5 text-muted-foreground">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </TableCell>
        <TableCell className="px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium">{item.index_name}</span>
            <span className="rounded border border-border px-1 py-0.5 text-[10px] text-muted-foreground">
              {windowLabel(item.window)}
            </span>
            {item.stale && (
              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">
                {staleLabel}
              </span>
            )}
            {!item.ok && (
              <span className="rounded border border-border bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                {unavailableLabel}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {historyMonths.replace("{count}", String(item.history_months))}
          </p>
        </TableCell>
        <TableCell className="px-2 py-1.5 font-mono text-xs">{item.index_code}</TableCell>
        <TableCell className="px-2 py-1.5 text-right text-xs tabular-nums">
          {item.pe != null ? item.pe.toFixed(2) : <span className="text-muted-foreground">—</span>}
        </TableCell>
        <TableCell className="px-2 py-1.5 text-right text-xs">
          <PercentileCell value={item.pe_percentile} />
        </TableCell>
        <TableCell className="px-2 py-1.5 text-right text-xs tabular-nums">
          {item.pb != null ? item.pb.toFixed(2) : <span className="text-muted-foreground">—</span>}
        </TableCell>
        <TableCell className="px-2 py-1.5 text-right text-xs">
          <PercentileCell value={item.pb_percentile} />
        </TableCell>
        <TableCell className="px-2 py-1.5 text-center">
          <TemperatureBadge temperature={item.temperature} />
        </TableCell>
        <TableCell className="px-2 py-1.5 text-xs text-muted-foreground">
          {item.data_date || "—"}
        </TableCell>
        <TableCell className="px-2 py-1.5 text-xs text-muted-foreground whitespace-nowrap">
          {fmtTime(item.updated_at)}
        </TableCell>
      </TableRow>
      {expanded && renderExpanded(item)}
    </>
  )
}