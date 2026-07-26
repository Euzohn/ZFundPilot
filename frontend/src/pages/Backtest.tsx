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

const CADENCE_OPTIONS = [
  { value: "month", label: "每月" },
  { value: "biweek", label: "双周" },
  { value: "week", label: "每周" },
]

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
      setError("请至少添加一只基金")
      return
    }
    const amt = parseFloat(amount)
    if (!amt || amt <= 0) {
      setError("每期金额必须大于 0")
      return
    }
    if (startDate >= endDate) {
      setError("起始日期必须早于结束日期")
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
        title="定投回测"
        subtitle="历史净值回测定投策略，对比一次性投入"
      />

      {/* 输入区 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            回测参数
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 基金代码输入 */}
          <div className="space-y-2">
            <label className="text-sm font-medium">基金代码</label>
            <div className="flex gap-2">
              <Input
                placeholder="输入6位基金代码，逗号或空格分隔"
                value={fundCodeInput}
                onChange={(e) => setFundCodeInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    addFundCode()
                  }
                }}
                className="flex-1"
              />
              <Button onClick={addFundCode} variant="secondary">添加</Button>
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
              <label className="text-sm font-medium">起始日期</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">结束日期</label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">每期金额 (¥)</label>
              <Input
                type="number"
                min="1"
                step="100"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">定投频率</label>
              <Select value={cadence} onChange={(e) => setCadence(e.target.value)}>
                {CADENCE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
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
              对比一次性投入
            </label>
            <Button onClick={runBacktest} disabled={loading || fundCodes.length === 0}>
              <Play className="mr-1 h-4 w-4" />
              {loading ? "回测中..." : "开始回测"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 加载 / 错误 / 空状态 */}
      {loading && (
        <div className="flex min-h-[30vh] flex-col items-center justify-center gap-2">
          <LoadingState size="md" />
          <p className="text-sm text-muted-foreground">正在回测，可能需要拉取净值数据...</p>
        </div>
      )}
      {error && <ErrorState message={error} />}
      {!loading && !error && !results && (
        <EmptyState title="尚未回测" description="填写参数后点击「开始回测」" />
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
                {dca && (
                  <>
                    <MetricCard
                      label="定投总投入"
                      value={money(dca.invested_capital)}
                      sub={`${dca.total_periods} 期 · 手续费 ${money(dca.total_fees)}`}
                    />
                    <MetricCard
                      label="定投终值"
                      value={money(dca.net_final_value)}
                      sub={`收益 ${pct(dca.total_return)}`}
                      color={pnlColor(dca.total_return)}
                    />
                    <MetricCard
                      label="定投年化"
                      value={pct(dca.annualized_return)}
                      sub={`最大回撤 ${pct(dca.max_drawdown)}`}
                      color={pnlColor(dca.annualized_return)}
                    />
                    <MetricCard
                      label="定投夏普"
                      value={dca.sharpe_ratio != null ? dca.sharpe_ratio.toFixed(2) : "—"}
                      sub={`无风险利率 3%`}
                    />
                  </>
                )}
                {lumpsum && (
                  <>
                    <MetricCard
                      label="一次性投入"
                      value={money(lumpsum.invested_capital)}
                      sub={`手续费 ${money(lumpsum.total_fees)}`}
                    />
                    <MetricCard
                      label="一次性终值"
                      value={money(lumpsum.net_final_value)}
                      sub={`收益 ${pct(lumpsum.total_return)}`}
                      color={pnlColor(lumpsum.total_return)}
                    />
                    <MetricCard
                      label="一次性年化"
                      value={pct(lumpsum.annualized_return)}
                      sub={`最大回撤 ${pct(lumpsum.max_drawdown)}`}
                      color={pnlColor(lumpsum.annualized_return)}
                    />
                    <MetricCard
                      label="一次性夏普"
                      value={lumpsum.sharpe_ratio != null ? lumpsum.sharpe_ratio.toFixed(2) : "—"}
                      sub={`无风险利率 3%`}
                    />
                  </>
                )}
              </div>
            </div>
          ))}

          <Tabs defaultValue="chart">
            <TabsList>
              <TabsTrigger value="chart">累计曲线</TabsTrigger>
              <TabsTrigger value="detail">每期明细</TabsTrigger>
              <TabsTrigger value="compare">基金对比</TabsTrigger>
            </TabsList>

            {/* 累计曲线 */}
            <TabsContent value="chart">
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>累计市值曲线</CardTitle>
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
                          tickFormatter={(v: number) => v >= 10000 ? `${(v / 10000).toFixed(0)}万` : String(v)}
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
                              name="一次性市值"
                              stroke="#3b82f6"
                              strokeWidth={2}
                              dot={false}
                              connectNulls
                            />
                            <Line
                              yAxisId="left"
                              type="monotone"
                              dataKey="lump_invested"
                              name="一次性投入"
                              stroke="#3b82f6"
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
                          name="定投市值"
                          stroke="#10b981"
                          fill="#10b981"
                          fillOpacity={0.1}
                          strokeWidth={2}
                          dot={false}
                          connectNulls
                        />
                        <Line
                          yAxisId="left"
                          type="monotone"
                          dataKey="dca_invested"
                          name="定投投入"
                          stroke="#10b981"
                          strokeWidth={1}
                          strokeDasharray="4 2"
                          dot={false}
                          connectNulls
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  ) : (
                    <EmptyState title="数据不足" description="该基金在所选区间内净值数据不足以生成曲线" />
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 每期明细 */}
            <TabsContent value="detail">
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>定投每期明细</CardTitle>
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
                            <TableHead>计划日</TableHead>
                            <TableHead>实际日</TableHead>
                            <TableHead className="text-right">净值</TableHead>
                            <TableHead className="text-right">金额</TableHead>
                            <TableHead className="text-right">手续费</TableHead>
                            <TableHead className="text-right">投入</TableHead>
                            <TableHead className="text-right">份额</TableHead>
                            <TableHead className="text-right">累计份额</TableHead>
                            <TableHead className="text-right">累计投入</TableHead>
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
                    <EmptyState title="无明细" description="该基金无定投明细数据" />
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 基金对比表 */}
            <TabsContent value="compare">
              <Card>
                <CardHeader>
                  <CardTitle>基金对比</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>基金</TableHead>
                          <TableHead>策略</TableHead>
                          <TableHead className="text-right">总投入</TableHead>
                          <TableHead className="text-right">终值</TableHead>
                          <TableHead className="text-right">收益率</TableHead>
                          <TableHead className="text-right">年化</TableHead>
                          <TableHead className="text-right">最大回撤</TableHead>
                          <TableHead className="text-right">夏普</TableHead>
                          <TableHead className="text-right">手续费</TableHead>
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
                                {r.strategy === "dca" ? "定投" : "一次性"}
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
            * 历史回测结果不代表未来收益，仅供参考。手续费按基金公开费率计算，实际费率以交易渠道为准。
          </p>
        </div>
      )}
    </div>
  )
}
