import { useState, useCallback, useMemo, useEffect } from "react"
import { useSearchParams } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { FundCompareItem, FundFilterItem, FilterResponse } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import { pct, money } from "@/lib/format"
import { cn } from "@/lib/utils"
import { GitCompare, Search, X, BarChart3, Table2, TrendingUp, Activity, DollarSign, RefreshCw, ChevronDown, ChevronRight, Filter, Check, Plus } from "lucide-react"
import {
  LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from "recharts"

const PERIOD_LABELS: Record<string, string> = {
  "1w": "近1周", "1m": "近1月", "3m": "近3月", "6m": "近6月",
  "1y": "近1年", "3y": "近3年", "ytd": "今年以来", "since": "成立以来",
}
const RISK_LABELS: Record<string, string> = {
  max_drawdown: "最大回撤", volatility: "年化波动率",
  sharpe: "夏普比率", calmar: "卡玛比率", win_rate: "胜率",
}

function InputSection({ onSubmit, loading }: { onSubmit: (codes: string[]) => void; loading: boolean }) {
  const [raw, setRaw] = useState("")
  const [error, setError] = useState("")

  const handleSubmit = () => {
    const codes = raw.split(/[,，\s\n]+/).map((s) => s.trim()).filter(Boolean)
    if (codes.length === 0) { setError("请输入基金代码"); return }
    if (codes.length > 20) { setError("一次最多对比 20 只基金"); return }
    const invalid = codes.filter((c) => !/^\d{6}$/.test(c))
    if (invalid.length > 0) { setError(`无效代码：${invalid.join(", ")}`); return }
    setError("")
    onSubmit(codes)
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={raw}
          onChange={(e) => { setRaw(e.target.value); setError("") }}
          onKeyDown={(e) => { if (e.key === "Enter") handleSubmit() }}
          placeholder="输入基金代码，逗号/空格/换行分隔，如 000001, 161725"
          className="h-9 text-sm flex-1"
        />
        <Button size="sm" onClick={handleSubmit} disabled={loading}>
          {loading ? <RefreshCw className="mr-1 h-4 w-4 animate-spin" /> : <Search className="mr-1 h-4 w-4" />}
          {loading ? "加载中..." : "对比"}
        </Button>
      </div>
      {error && <p className="text-xs text-loss-600">{error}</p>}
    </div>
  )
}

function FilterSection({ onAddToCompare }: { onAddToCompare: (codes: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [types, setTypes] = useState<string[]>([])
  const [sectors, setSectors] = useState<string[]>([])
  const [keyword, setKeyword] = useState("")
  const [results, setResults] = useState<FundFilterItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [availTypes, setAvailTypes] = useState<string[]>([])
  const [availSectors, setAvailSectors] = useState<string[]>([])

  useEffect(() => {
    api.getKeywordMaps().then((m) => {
      setAvailTypes(m.available_types)
      setAvailSectors(m.available_sectors)
    }).catch(() => {})
  }, [])

  const handleSearch = useCallback(async () => {
    setLoading(true)
    setError("")
    setResults([])
    setTotal(0)
    setSelected(new Set())
    try {
      const res = await api.filterFunds({ types, sectors, keyword: keyword.trim(), limit: 50, offset: 0 })
      if (res.ok) {
        setResults(res.funds)
        setTotal(res.total)
      } else {
        setError(res.message)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "筛选请求失败")
    } finally {
      setLoading(false)
    }
  }, [types, sectors, keyword])

  const toggleType = (t: string) => {
    setTypes((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t])
  }

  const toggleSector = (s: string) => {
    setSectors((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])
  }

  const toggleSelect = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code); else next.add(code)
      return next
    })
  }

  const handleAdd = () => {
    if (selected.size > 0) {
      onAddToCompare(Array.from(selected))
    }
  }

  return (
    <Card className="not-prose">
      <CardContent className="p-4">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <Filter className="h-4 w-4" />
          条件筛选
          {(types.length > 0 || sectors.length > 0 || keyword.trim()) && (
            <Badge variant="secondary" className="ml-auto text-[10px]">筛选中</Badge>
          )}
        </button>

        {open && (
          <div className="mt-4 space-y-4">
            {/* Types */}
            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">资产类型</p>
              <div className="flex flex-wrap gap-2">
                {availTypes.map((t) => (
                  <label
                    key={t}
                    className={cn(
                      "inline-flex cursor-pointer items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors",
                      types.includes(t)
                        ? "border-blue-400 bg-blue-50 text-blue-700"
                        : "border-border hover:bg-muted/50",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={types.includes(t)}
                      onChange={() => toggleType(t)}
                      className="sr-only"
                    />
                    {types.includes(t) && <Check className="h-3 w-3" />}
                    {t}
                  </label>
                ))}
              </div>
            </div>

            {/* Sectors */}
            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">板块</p>
              <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto">
                {availSectors.map((s) => (
                  <label
                    key={s}
                    className={cn(
                      "inline-flex cursor-pointer items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors shrink-0",
                      sectors.includes(s)
                        ? "border-blue-400 bg-blue-50 text-blue-700"
                        : "border-border hover:bg-muted/50",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={sectors.includes(s)}
                      onChange={() => toggleSector(s)}
                      className="sr-only"
                    />
                    {sectors.includes(s) && <Check className="h-3 w-3" />}
                    {s}
                  </label>
                ))}
              </div>
            </div>

            {/* Keyword + Search */}
            <div className="flex gap-2">
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSearch() }}
                placeholder="基金名称或代码"
                className="h-9 text-sm flex-1"
              />
              <Button size="sm" onClick={handleSearch} disabled={loading}>
                {loading ? <RefreshCw className="mr-1 h-4 w-4 animate-spin" /> : <Search className="mr-1 h-4 w-4" />}
                {loading ? "搜索中..." : "搜索"}
              </Button>
            </div>

            {/* Error */}
            {error && <p className="text-xs text-loss-600">{error}</p>}

            {/* Results */}
            {results.length > 0 && (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-xs text-muted-foreground">共 {total} 只，显示前 {results.length} 只</p>
                  {selected.size > 0 && (
                    <Button size="sm" variant="outline" onClick={handleAdd}>
                      <Plus className="mr-1 h-3.5 w-3.5" />
                      加入对比 ({selected.size})
                    </Button>
                  )}
                </div>
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-muted/50">
                        <th className="w-8 px-2 py-2 text-left" />
                        <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">代码</th>
                        <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">名称</th>
                        <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">类型</th>
                        <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">板块</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((f) => (
                        <tr key={f.code} className="border-t border-border/50">
                          <td className="px-2 py-1.5">
                            <input
                              type="checkbox"
                              checked={selected.has(f.code)}
                              onChange={() => toggleSelect(f.code)}
                              className="h-4 w-4 accent-blue-600"
                            />
                          </td>
                          <td className="px-2 py-1.5 font-mono text-xs">{f.code}</td>
                          <td className="max-w-[200px] truncate px-2 py-1.5 text-xs" title={f.name}>{f.name}</td>
                          <td className="px-2 py-1.5 text-xs">{f.type}</td>
                          <td className="px-2 py-1.5 text-xs">{f.sector}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {!loading && !error && results.length === 0 && total === 0 && (
              <p className="text-xs text-muted-foreground">选择筛选条件后点击搜索</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
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
  const keys = Object.keys(labelMap)
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted/50">
            <th className="sticky left-0 bg-muted/50 px-3 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">指标</th>
            {funds.map((f) => (
              <th key={f.code} className="px-3 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">{f.name || f.code}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key} className="border-t border-border/50">
              <td className="sticky left-0 bg-white px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{labelMap[key]}</td>
              {funds.map((f) => (
                <td key={f.code} className="px-3 py-2 text-right text-xs">
                  {format === "pct"
                    ? <ReturnCell value={f[valueKey]?.[key] as number | null | undefined} />
                    : <Cell value={f[valueKey]?.[key] as number | null | undefined} />
                  }
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function InfoTable({ funds }: { funds: FundCompareItem[] }) {
  const rows = [
    { label: "代码", render: (f: FundCompareItem) => <span className="font-mono">{f.code}</span> },
    { label: "名称", render: (f: FundCompareItem) => f.name || "—" },
    { label: "类型", render: (f: FundCompareItem) => f.type },
    { label: "板块", render: (f: FundCompareItem) => f.sector || "—" },
    { label: "成立日期", render: (f: FundCompareItem) => f.inception_date || "—" },
    { label: "规模(亿)", render: (f: FundCompareItem) => f.scale != null ? `${f.scale.toFixed(1)} 亿` : "—" },
    { label: "基金经理", render: (f: FundCompareItem) => f.manager || "—" },
    { label: "最新净值", render: (f: FundCompareItem) => f.latest_nav != null ? f.latest_nav.toFixed(4) : "—" },
    { label: "净值日期", render: (f: FundCompareItem) => f.latest_date || "—" },
    { label: "管理费", render: (f: FundCompareItem) => f.management_fee != null ? pct(f.management_fee) : "—" },
    { label: "托管费", render: (f: FundCompareItem) => f.custodian_fee != null ? pct(f.custodian_fee) : "—" },
    { label: "销售服务费", render: (f: FundCompareItem) => f.sales_fee != null ? pct(f.sales_fee) : "—" },
  ]
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted/50">
            <th className="sticky left-0 bg-muted/50 px-3 py-2 text-left text-xs font-medium text-muted-foreground">指标</th>
            {funds.map((f) => (
              <th key={f.code} className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">{f.name || f.code}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, render }) => (
            <tr key={label} className="border-t border-border/50">
              <td className="sticky left-0 bg-white px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{label}</td>
              {funds.map((f) => (
                <td key={f.code} className="px-3 py-2 text-right text-xs">{render(f)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const NAV_CHART_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#be185d", "#059669"]

function NavChart({ navSeries }: { navSeries: Record<string, { date: string; value: number }[]> }) {
  const codes = Object.keys(navSeries).filter((c) => navSeries[c].length > 0)
  if (codes.length === 0) return <p className="py-12 text-center text-sm text-muted-foreground">无净值数据</p>

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
  if (!correlations || correlations.length < 2) return <p className="py-12 text-center text-sm text-muted-foreground">至少需要 2 只基金计算相关性</p>

  const n = correlations.length
  return (
    <div className="overflow-x-auto">
      <table className="mx-auto text-sm">
        <thead>
          <tr>
            <th className="px-2 py-1" />
            {funds.map((f) => (
              <th key={f.code} className="px-2 py-1 text-xs text-muted-foreground font-medium max-w-[80px] truncate" title={f.name}>
                {f.code}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {funds.map((f, i) => (
            <tr key={f.code}>
              <td className="px-2 py-1 text-xs text-muted-foreground font-medium max-w-[80px] truncate" title={f.name}>
                {f.code}
              </td>
              {funds.map((_, j) => {
                const v = correlations[i][j]
                const intensity = v != null ? Math.abs(v) : 0
                const r = Math.round(200 * intensity)
                const g = Math.round(200 * (1 - intensity))
                const bg = v != null && v >= 0 ? `rgb(${r}, ${g}, ${g})` : `rgb(${g}, ${r}, ${g})`
                return (
                  <td
                    key={j}
                    className="px-2 py-1 text-center text-xs tabular-nums font-medium"
                    style={{ background: bg, color: intensity > 0.5 ? "#fff" : "#1e293b" }}
                    title={`${f.name} vs ${funds[j].name}: ${v != null ? v.toFixed(3) : "—"}`}
                  >
                    {v != null ? v.toFixed(2) : "—"}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex items-center justify-center gap-2 text-[10px] text-muted-foreground">
        <span>负相关</span>
        <div className="flex h-3 w-20 rounded overflow-hidden">
          <div className="h-full flex-1" style={{ background: "rgb(200, 200, 200)" }} />
          <div className="h-full flex-1" style={{ background: "rgb(200, 200, 200)" }} />
          <div className="h-full flex-1" style={{ background: "rgb(200, 200, 200)" }} />
          <div className="h-full flex-1" style={{ background: "rgb(0, 200, 200)" }} />
          <div className="h-full flex-1" style={{ background: "rgb(0, 200, 200)" }} />
        </div>
        <span>正相关</span>
      </div>
    </div>
  )
}

export default function FundCompare() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialCodes = useMemo(() => {
    const q = searchParams.get("codes") || ""
    return q.split(",").filter(Boolean)
  }, [])
  const [codes, setCodes] = useState<string[]>(initialCodes)

  const fetcher = useCallback(() => {
    if (codes.length === 0) return Promise.resolve(null)
    return api.compareFunds(codes)
  }, [codes])

  const { data, loading, error, reload } = useApi(fetcher, [codes.join(",")])

  const okFunds = useMemo(() => data?.funds?.filter((f) => f.ok) ?? [], [data])
  const failedFunds = useMemo(() => data?.funds?.filter((f) => !f.ok) ?? [], [data])

  const handleCompare = (newCodes: string[]) => {
    setCodes(newCodes)
    setSearchParams(newCodes.length > 0 ? { codes: newCodes.join(",") } : {}, { replace: true })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <GitCompare className="h-5 w-5 text-blue-500" />
        <h1 className="text-xl md:text-2xl font-bold tracking-tight">基金对比</h1>
      </div>

      <FilterSection onAddToCompare={handleCompare} />

      <Card>
        <CardContent className="p-4">
          <InputSection onSubmit={handleCompare} loading={loading} />
        </CardContent>
      </Card>

      {error && <ErrorState message={error} onRetry={reload} />}

      {loading && (
        <div className="flex min-h-[40vh] items-center justify-center">
          <LogoSpinner className="h-16 w-16" />
        </div>
      )}

      {!loading && !error && data && !data.ok && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">{data.message}</CardContent>
        </Card>
      )}

      {!loading && !error && data && data.ok && okFunds.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            输入基金代码开始对比
          </CardContent>
        </Card>
      )}

      {!loading && !error && data && data.ok && okFunds.length > 0 && (
        <>
          {failedFunds.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              以下基金获取失败：{failedFunds.map((f) => `${f.code}(${f.message})`).join("；")}
            </div>
          )}

          <Tabs defaultValue="info">
            <TabsList className="grid w-full grid-cols-5 sm:inline-flex sm:w-auto">
              <TabsTrigger value="info" className="gap-1"><Table2 className="h-3.5 w-3.5" /><span className="hidden sm:inline">基本信息</span></TabsTrigger>
              <TabsTrigger value="returns" className="gap-1"><TrendingUp className="h-3.5 w-3.5" /><span className="hidden sm:inline">收益表现</span></TabsTrigger>
              <TabsTrigger value="risk" className="gap-1"><Activity className="h-3.5 w-3.5" /><span className="hidden sm:inline">风险指标</span></TabsTrigger>
              <TabsTrigger value="chart" className="gap-1"><BarChart3 className="h-3.5 w-3.5" /><span className="hidden sm:inline">净值走势</span></TabsTrigger>
              <TabsTrigger value="correlation" className="gap-1"><DollarSign className="h-3.5 w-3.5" /><span className="hidden sm:inline">相关性</span></TabsTrigger>
            </TabsList>

            <TabsContent value="info" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">基本信息</CardTitle></CardHeader>
                <CardContent><InfoTable funds={okFunds} /></CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="returns" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">收益表现</CardTitle></CardHeader>
                <CardContent>
                  <CompareTable funds={okFunds} labelMap={PERIOD_LABELS} valueKey="returns" format="pct" />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="risk" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">风险指标</CardTitle></CardHeader>
                <CardContent>
                  <CompareTable funds={okFunds} labelMap={RISK_LABELS} valueKey="risk" format="pct" />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="chart" className="mt-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">净值走势（归一化，基期=100）</CardTitle>
                </CardHeader>
                <CardContent>
                  <NavChart navSeries={data.nav_series ?? {}} />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="correlation" className="mt-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">相关性矩阵</CardTitle></CardHeader>
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