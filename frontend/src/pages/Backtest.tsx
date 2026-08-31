import { useState, useMemo, useCallback } from "react"
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts"
import { TrendingUp, Play, X } from "lucide-react"
import PageHeader from "@/components/PageHeader"
import MetricCard from "@/components/MetricCard"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { api } from "@/api/client"
import type { BacktestResult } from "@/api/types"
import { money, pct, pnlColor } from "@/lib/format"
import { useLang } from "@/i18n/LanguageContext"
import { useCountUp } from "@/hooks/useCountUp"

const CADENCE_VALUES = ["month", "biweek", "week"] as const
const formatSharpe = (n: number) => n.toFixed(2)

function BacktestKpi({ result, strategy }: { result: BacktestResult; strategy: "dca" | "lumpsum" }) {
  const { t } = useLang()

  const invested = useCountUp(result.invested_capital, money)
  const finalValue = useCountUp(result.net_final_value, money)
  const annualReturn = useCountUp(result.annualized_return ?? 0, pct)
  const sharpe = useCountUp(result.sharpe_ratio ?? 0, formatSharpe)

  if (strategy === "dca") {
    return (
      <>
        <MetricCard label={t.backtest.dcaTotalInvested} value={invested} sub={`${result.total_periods} ${t.backtest.periodsUnit} · ${t.common.fee} ${money(result.total_fees)}`} />
        <MetricCard label={t.backtest.dcaFinalValue} value={finalValue} sub={`${t.backtest.returnLabel} ${pct(result.total_return)}`} color={pnlColor(result.total_return)} />
        <MetricCard label={t.backtest.dcaAnnualReturn} value={result.annualized_return != null ? annualReturn : "—"} sub={`${t.backtest.maxDrawdown} ${pct(result.max_drawdown)}`} color={pnlColor(result.annualized_return)} />
        <MetricCard label={t.backtest.dcaSharpe} value={result.sharpe_ratio != null ? sharpe : "—"} sub={t.backtest.riskFreeRate} />
      </>
    )
  }

  return (
    <>
      <MetricCard label={t.backtest.lumpSumStrategy} value={invested} sub={`${t.common.fee} ${money(result.total_fees)}`} />
      <MetricCard label={t.backtest.lumpsumFinalValue} value={finalValue} sub={`${t.backtest.returnLabel} ${pct(result.total_return)}`} color={pnlColor(result.total_return)} />
      <MetricCard label={t.backtest.lumpsumAnnualReturn} value={result.annualized_return != null ? annualReturn : "—"} sub={`${t.backtest.maxDrawdown} ${pct(result.max_drawdown)}`} color={pnlColor(result.annualized_return)} />
      <MetricCard label={t.backtest.lumpsumSharpe} value={result.sharpe_ratio != null ? sharpe : "—"} sub={t.backtest.riskFreeRate} />
    </>
  )
}

function defaultStartDate(): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 3)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function defaultEndDate(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export default function Backtest() {
  const { t } = useLang()
  const cadenceLabels: Record<string, string> = {
    month: t.backtest.monthly,
    biweek: t.backtest.biweekly,
    week: t.backtest.weekly,
  }
  const [fundCodeInput, setFundCodeInput] = useState("")
  const [fundCodes, setFundCodes] = useState<string[]>([])
  const [startDate, setStartDate] = useState(defaultStartDate())
  const [endDate, setEndDate] = useState(defaultEndDate())
  const [amount, setAmount] = useState("1000")
  const [cadence, setCadence] = useState("month")
  const [includeLumpsum, setIncludeLumpsum] = useState(true)

  const [results, setResults] = useState<BacktestResult[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addFundCode = useCallback(() => {
    const codes = fundCodeInput
      .split(/[\s,，]+/)
      .map((s) => s.trim())
      .filter((s) => /^\d{6}$/.test(s))
    const newCodes = [...new Set([...fundCodes, ...codes])]
    setFundCodes(newCodes)
    setFundCodeInput("")
  }, [fundCodeInput, fundCodes])

  const removeFundCode = useCallback((code: string) => {
    setFundCodes((prev) => prev.filter((c) => c !== code))
  }, [])

  const runBacktest = useCallback(async () => {
    if (fundCodes.length === 0) {
      setError(t.backtest.fundRequired)
      return
    }
    const amt = parseFloat(amount)
    if (!amt || amt <= 0) {
      setError(t.backtest.amountRequired)
      return
    }
    if (startDate >= endDate) {
      setError(t.backtest.dateRangeInvalid)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const res = await api.runDcaBacktest({
        fund_codes: fundCodes,
        start_date: startDate,
        end_date: endDate,
        amount_per_period: amt,
        cadence,
        include_lumpsum: includeLumpsum,
      })
      setResults(res.results)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [fundCodes, startDate, endDate, amount, cadence, includeLumpsum])

  // 按基金分组结果
  const groupedResults = useMemo(() => {
    if (!results) return []
    const groups: Record<string, { dca?: BacktestResult; lumpsum?: BacktestResult }> = {}
    for (const r of results) {
      if (!groups[r.fund_code]) groups[r.fund_code] = {}
      if (r.strategy === "dca") groups[r.fund_code].dca = r
      else groups[r.fund_code].lumpsum = r
    }
    return Object.entries(groups).map(([code, g]) => ({ code, ...g }))
  }, [results])

  // 图表数据：选定第一个基金的 dca vs lumpsum 曲线合并
  const [selectedFund, setSelectedFund] = useState<string>("")
  const chartFund = selectedFund || groupedResults[0]?.code || ""
  const chartData = useMemo(() => {
    const group = groupedResults.find((g) => g.code === chartFund)
    if (!group) return []
    const dca = group.dca
    const lump = group.lumpsum
    const allDates = new Set<string>([
      ...(dca?.curve || []).map((c) => c.date),
      ...(lump?.curve || []).map((c) => c.date),
    ])
    const dcaMap = new Map((dca?.curve || []).map((c) => [c.date, c]))
    const lumpMap = new Map((lump?.curve || []).map((c) => [c.date, c]))
    return [...allDates].sort().map((date) => ({
      date,
      dca_value: dcaMap.get(date)?.value ?? null,
      dca_invested: dcaMap.get(date)?.invested ?? null,
      lump_value: lumpMap.get(date)?.value ?? null,
      lump_invested: lumpMap.get(date)?.invested ?? null,
    }))
  }, [groupedResults, chartFund])

  const selectedDca = groupedResults.find((g) => g.code === chartFund)?.dca

  return (
    <div className="space-y-6">
      <PageHeader
        title={t.backtest.title}
        subtitle={t.backtest.subtitle}
      />

      {/* 输入区 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            {t.backtest.params}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 基金代码输入 */}
          <div className="space-y-2">
            <label className="text-sm font-medium">{t.backtest.fundCode}</label>
            <div className="flex gap-2">
              <Input
                placeholder={t.backtest.fundCodePlaceholder}
                value={fundCodeInput}
                onChange={(e) => setFundCodeInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    addFundCode()
                  }
                }}
                className="flex-1"
              />
              <Button onClick={addFundCode} variant="secondary">{t.common.add}</Button>
            </div>
            {fundCodes.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {fundCodes.map((code) => (
                  <span
                    key={code}
                    className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs font-medium"
                  >
                    {code}
                    <button
                      onClick={() => removeFundCode(code)}
                      title={t.common.remove}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 日期 + 金额 + 频率 */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t.backtest.startDate}</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t.backtest.endDate}</label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t.backtest.amount} (¥)</label>
              <Input
                type="number"
                min="1"
                step="100"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t.backtest.cadence}</label>
              <Select value={cadence} onChange={(e) => setCadence(e.target.value)}>
                {CADENCE_VALUES.map((v) => (
                  <option key={v} value={v}>{cadenceLabels[v]}</option>
                ))}
              </Select>
            </div>
          </div>

          {/* 选项 + 按钮 */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={includeLumpsum}
                onCheckedChange={(v) => setIncludeLumpsum(v === true)}
              />
              {t.backtest.compareLumpsum}
            </label>
            <Button onClick={runBacktest} disabled={loading || fundCodes.length === 0}>
              <Play className="mr-1 h-4 w-4" />
              {loading ? t.backtest.running : t.backtest.runBacktest}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 加载 / 错误 / 空状态 */}
      {loading && (
        <div className="flex min-h-[30vh] flex-col items-center justify-center gap-2">
          <LoadingState size="md" />
          <p className="text-sm text-muted-foreground">{t.backtest.runningHint}</p>
        </div>
      )}
      {error && <ErrorState message={error} />}
      {!loading && !error && !results && (
        <EmptyState title={t.backtest.noResult} description={t.backtest.noResultHint} />
      )}

      {/* 结果 */}
      {!loading && !error && results && results.length > 0 && (
        <div className="space-y-6">
          {/* KPI 卡片：每基金×策略 */}
          {groupedResults.map(({ code, dca, lumpsum }) => (
            <div key={code} className="space-y-2">
              <h3 className="text-sm font-bold">
                {dca?.fund_name || code}（{code}）
              </h3>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {dca && <BacktestKpi result={dca} strategy="dca" />}
                {lumpsum && <BacktestKpi result={lumpsum} strategy="lumpsum" />}
              </div>
            </div>
          ))}

          <Tabs defaultValue="chart">
            <TabsList>
              <TabsTrigger value="chart">{t.backtest.cumulativeCurve}</TabsTrigger>
              <TabsTrigger value="detail">{t.backtest.periodDetail}</TabsTrigger>
              <TabsTrigger value="compare">{t.backtest.fundCompare}</TabsTrigger>
            </TabsList>

            {/* 累计曲线 */}
            <TabsContent value="chart">
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>{t.backtest.cumulativeValueCurve}</CardTitle>
                    {groupedResults.length > 1 && (
                      <Select
                        value={chartFund}
                        onChange={(e) => setSelectedFund(e.target.value)}
                        className="w-40"
                      >
                        {groupedResults.map((g) => (
                          <option key={g.code} value={g.code}>
                            {g.code} {g.dca?.fund_name || ""}
                          </option>
                        ))}
                      </Select>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  {chartData.length > 1 ? (
                    <ResponsiveContainer width="100%" height={400}>
                      <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis
                          dataKey="date"
                          tick={{ fontSize: 11 }}
                          tickFormatter={(d: string) => d.slice(0, 7)}
                        />
                        <YAxis
                          yAxisId="left"
                          tick={{ fontSize: 11 }}
                          tickFormatter={(v: number) => v >= 10000 ? `${(v / 10000).toFixed(0)}${t.common.tenThousand}` : String(v)}
                        />
                        <Tooltip
                          formatter={(v, name) => {
                            const val = typeof v === "number" ? v : null
                            return [val != null ? money(val) : "—", name]
                          }}
                          labelFormatter={(l: string) => l}
                        />
                        <Legend />
                        {includeLumpsum && (
                          <>
                            <Line
                              yAxisId="left"
                              type="monotone"
                              dataKey="lump_value"
                              name={t.backtest.lumpsumValue}
                              stroke="hsl(var(--chart-1))"
                              strokeWidth={2}
                              dot={false}
                              connectNulls
                            />
                            <Line
                              yAxisId="left"
                              type="monotone"
                              dataKey="lump_invested"
                              name={t.backtest.lumpSumStrategy}
                              stroke="hsl(var(--chart-1))"
                              strokeWidth={1}
                              strokeDasharray="4 2"
                              dot={false}
                              connectNulls
                            />
                          </>
                        )}
                        <Area
                          yAxisId="left"
                          type="monotone"
                          dataKey="dca_value"
                          name={t.backtest.dcaValue}
                          stroke="hsl(var(--chart-2))"
                          fill="hsl(var(--chart-2))"
                          fillOpacity={0.1}
                          strokeWidth={2}
                          dot={false}
                          connectNulls
                        />
                        <Line
                          yAxisId="left"
                          type="monotone"
                          dataKey="dca_invested"
                          name={t.backtest.dcaInvested}
                          stroke="hsl(var(--chart-2))"
                          strokeWidth={1}
                          strokeDasharray="4 2"
                          dot={false}
                          connectNulls
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  ) : (
                    <EmptyState title={t.backtest.insufficientData} description={t.backtest.insufficientDataHint} />
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 每期明细 */}
            <TabsContent value="detail">
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>{t.backtest.dcaPeriodDetail}</CardTitle>
                    {groupedResults.length > 1 && (
                      <Select
                        value={chartFund}
                        onChange={(e) => setSelectedFund(e.target.value)}
                        className="w-40"
                      >
                        {groupedResults.map((g) => (
                          <option key={g.code} value={g.code}>
                            {g.code} {g.dca?.fund_name || ""}
                          </option>
                        ))}
                      </Select>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  {selectedDca && selectedDca.periods_detail.length > 0 ? (
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>{t.backtest.plannedDate}</TableHead>
                            <TableHead>{t.backtest.actualDate}</TableHead>
                            <TableHead className="text-right">{t.common.nav}</TableHead>
                            <TableHead className="text-right">{t.common.amount}</TableHead>
                            <TableHead className="text-right">{t.common.fee}</TableHead>
                            <TableHead className="text-right">{t.backtest.invested}</TableHead>
                            <TableHead className="text-right">{t.common.shares}</TableHead>
                            <TableHead className="text-right">{t.backtest.cumulativeShares}</TableHead>
                            <TableHead className="text-right">{t.backtest.cumulativeInvested}</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {selectedDca.periods_detail.map((p, i) => (
                            <TableRow key={i}>
                              <TableCell className="tabular-nums">{p.planned_date}</TableCell>
                              <TableCell className="tabular-nums">{p.actual_date}</TableCell>
                              <TableCell className="text-right tabular-nums">{p.nav.toFixed(4)}</TableCell>
                              <TableCell className="text-right tabular-nums">{money(p.amount)}</TableCell>
                              <TableCell className="text-right tabular-nums text-muted-foreground">{money(p.fee)}</TableCell>
                              <TableCell className="text-right tabular-nums">{money(p.invested)}</TableCell>
                              <TableCell className="text-right tabular-nums">{p.shares.toFixed(4)}</TableCell>
                              <TableCell className="text-right tabular-nums">{p.cumulative_shares.toFixed(4)}</TableCell>
                              <TableCell className="text-right tabular-nums">{money(p.cumulative_invested)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  ) : (
                    <EmptyState title={t.backtest.noDetail} description={t.backtest.noDetailHint} />
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 基金对比表 */}
            <TabsContent value="compare">
              <Card>
                <CardHeader>
                  <CardTitle>{t.backtest.fundCompare}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t.backtest.fund}</TableHead>
                          <TableHead>{t.backtest.strategy}</TableHead>
                          <TableHead className="text-right">{t.backtest.totalInvested}</TableHead>
                          <TableHead className="text-right">{t.backtest.finalValue}</TableHead>
                          <TableHead className="text-right">{t.backtest.returnRate}</TableHead>
                          <TableHead className="text-right">{t.backtest.annualized}</TableHead>
                          <TableHead className="text-right">{t.backtest.maxDrawdown}</TableHead>
                          <TableHead className="text-right">{t.backtest.sharpe}</TableHead>
                          <TableHead className="text-right">{t.common.fee}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {results.map((r, i) => (
                          <TableRow key={i}>
                            <TableCell className="font-medium">
                              {r.fund_name}（{r.fund_code}）
                            </TableCell>
                            <TableCell>
                              <span className="rounded bg-muted px-1.5 py-0.5 text-xs">
                                {r.strategy === "dca" ? t.backtest.dcaLabel : t.backtest.lumpsumLabel}
                              </span>
                            </TableCell>
                            <TableCell className="text-right tabular-nums">{money(r.invested_capital)}</TableCell>
                            <TableCell className="text-right tabular-nums">{money(r.net_final_value)}</TableCell>
                            <TableCell className={`text-right tabular-nums ${pnlColor(r.total_return)}`}>
                              {pct(r.total_return)}
                            </TableCell>
                            <TableCell className={`text-right tabular-nums ${pnlColor(r.annualized_return)}`}>
                              {pct(r.annualized_return)}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-loss">
                              {pct(r.max_drawdown)}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : "—"}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-muted-foreground">
                              {money(r.total_fees)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {/* 免责声明 */}
          <p className="text-xs text-muted-foreground">
            {t.backtest.disclaimer}
          </p>
        </div>
      )}
    </div>
  )
}
