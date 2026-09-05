import { useState, useMemo, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { EstimateSummary } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Select } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, signedMoney, pnlColor, localDateStr } from "@/lib/format"
import { isMarketOpen } from "@/lib/market"
import { translateFundType, translateSector } from "@/lib/taxonomyLabels"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, ChevronRight, ChevronUp, ChevronDown, Search, LayoutGrid, List, Wallet } from "lucide-react"
import { makeSortHeader } from "@/components/SortHeader"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import IndustryExposurePanel from "@/components/IndustryExposurePanel"
import { useLang } from "@/i18n/LanguageContext"

export default function Positions() {
  const navigate = useNavigate()
  const { t } = useLang()
  const [activeTab, setActiveTab] = useState("list")
  const [channelFilter, setChannelFilter] = useState(() => localStorage.getItem("zfundpilot_channelFilter") ?? "")
  const [searchQuery, setSearchQuery] = useState("")
  const [viewMode, setViewMode] = useState<"list" | "grid">(() => localStorage.getItem("zfundpilot_positionsView") === "grid" ? "grid" : "list")
  const [sortField, setSortField] = useState("value")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [closedSortField, setClosedSortField] = useState("realized")
  const [closedSortDir, setClosedSortDir] = useState<"asc" | "desc">("desc")
  const { data: positions, loading, error, reload } = useApi(() => api.getPositions(true))
  const { data: estimate, reload: reloadEstimate } = useApi<EstimateSummary>(() => api.getEstimate())

  const hasEstimate = estimate?.funds.some(f => f.ok) ?? false

  useEffect(() => {
    if (!hasEstimate) return
    const interval = setInterval(() => {
      if (!isMarketOpen()) return
      reloadEstimate()
    }, 60000)
    return () => clearInterval(interval)
  }, [reloadEstimate, hasEstimate])

  const estimateMap = useMemo(() => {
    if (!estimate) return {}
    const m: Record<string, { gszzl: number; pnl: number; shares: number; ok: boolean }> = {}
    for (const f of estimate.funds) {
      if (f.ok || f.prev_value > 0) m[f.fund_code] = { gszzl: f.gszzl, pnl: f.estimated_pnl, shares: f.held_shares, ok: f.ok }
    }
    return m
  }, [estimate])

  const availableChannels = useMemo(() => {
    if (!positions) return []
    const set = new Set(positions.map((p) => p.channel).filter(Boolean))
    return Array.from(set).sort()
  }, [positions])

  // 持久化渠道筛选
  useEffect(() => { localStorage.setItem("zfundpilot_channelFilter", channelFilter) }, [channelFilter])
  useEffect(() => { localStorage.setItem("zfundpilot_positionsView", viewMode) }, [viewMode])

  const today = localDateStr()

  const view = positions
    ? positions.filter((p) => p.is_open).filter((p) => !channelFilter || p.channel === channelFilter)
    : []

  // 按基金合并（跨渠道）
  const merged: Record<string, { name: string; type: string; sector: string; trackingIndex: string; value: number; cost: number; pnl: number; shares: number; avgCost: number | null; latestNav: number | null; channels: number; latestDate: string | null; channel: string | null }> = {}
  for (const p of view.filter((p) => p.is_open)) {
    const m = merged[p.fund_code] ?? { name: p.fund_name, type: p.fund_type, sector: p.sector, trackingIndex: p.tracking_index || "", value: 0, cost: 0, pnl: 0, shares: 0, avgCost: null, latestNav: p.latest_nav, channels: 0, latestDate: p.latest_date, channel: p.channel }
    m.value += p.market_value
    m.cost += p.total_cost
    m.pnl += p.unrealized_pnl
    m.shares += p.held_shares
    m.channels += 1
    m.latestDate = p.latest_date
    if (m.channel !== p.channel) m.channel = null  // 多渠道时置空
    merged[p.fund_code] = m
  }
  for (const m of Object.values(merged)) {
    m.avgCost = m.shares > 0 ? m.cost / m.shares : null
  }
  const mergedRows = Object.entries(merged).sort((a, b) => b[1].value - a[1].value)

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDir("desc")
    }
  }

  const sortedRows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    const filtered = q
      ? mergedRows.filter(([code, m]) =>
          m.name.toLowerCase().includes(q) ||
          code.toLowerCase().includes(q) ||
          (m.sector && m.sector.toLowerCase().includes(q)) ||
          m.type.toLowerCase().includes(q)
        )
      : mergedRows
    return [...filtered].sort(([, a], [, b]) => {
      const getVal = (m: typeof a): number | string => {
        switch (sortField) {
          case "name": return m.name
          case "type": return m.type
          case "sector": return m.sector
          case "value": return m.value
          case "pnl": return m.pnl
          case "return": return m.cost ? m.value / m.cost - 1 : -999
          case "channels": return m.channels
          default: return m.value
        }
      }
      const va = getVal(a)
      const vb = getVal(b)
      const cmp = typeof va === "string" && typeof vb === "string"
        ? va.localeCompare(vb)
        : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [mergedRows, sortField, sortDir, searchQuery])

  const maxDate = sortedRows.reduce((best, [, m]) =>
    m.latestDate && (!best || m.latestDate > best) ? m.latestDate : best,
    null as string | null,
  )

  const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })

  const totalValue = viewMode === "grid" ? sortedRows.reduce((s, [, m]) => s + m.value, 0) : 0
  const totalPnl = viewMode === "grid" ? sortedRows.reduce((s, [, m]) => s + m.pnl, 0) : 0

  return (
    <div className="space-y-6">
      {loading ? (
        <LoadingState />
      ) : !positions ? (
        <ErrorState message={error ?? undefined} onRetry={reload} />
      ) : (
      <>
      <PageHeader title={t.positions.title} icon={<Wallet className="h-5 w-5" />} />
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-2">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <TabsList>
            <TabsTrigger value="list">{t.positions.listTab}</TabsTrigger>
            <TabsTrigger value="exposure">{t.positions.industryExposure}</TabsTrigger>
            <TabsTrigger value="closed">{t.positions.closedTab}</TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-2">
            {activeTab === "list" && (
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t.positions.searchPlaceholder}
                  className="h-8 w-44 pl-7 text-xs"
                />
              </div>
            )}
            {(activeTab === "list" || activeTab === "closed") && (
              <Select value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)} className="h-8 text-xs w-32">
                <option value="">{t.positions.allChannels}</option>
                {availableChannels.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            )}
            {activeTab === "list" && viewMode === "grid" && (
              <Select value={sortField} onChange={(e) => { setSortField(e.target.value); setSortDir("desc") }} className="h-8 text-xs w-32" aria-label={t.positions.sortBy}>
                <option value="value">{t.positions.sortValue}</option>
                <option value="pnl">{t.positions.sortPnl}</option>
                <option value="return">{t.positions.sortReturn}</option>
                <option value="name">{t.positions.sortName}</option>
              </Select>
            )}
            {activeTab === "list" && (
              <div className="flex items-center rounded-md border border-border overflow-hidden">
                <Button
                  variant={viewMode === "list" ? "default" : "ghost"}
                  size="sm"
                  className="h-8 px-2 rounded-none"
                  onClick={() => setViewMode("list")}
                  title={t.positions.viewList}
                >
                  <List className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant={viewMode === "grid" ? "default" : "ghost"}
                  size="sm"
                  className="h-8 px-2 rounded-none"
                  onClick={() => setViewMode("grid")}
                  title={t.positions.viewGrid}
                >
                  <LayoutGrid className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}
          </div>
        </div>
        <TabsContent value="list" className="space-y-4">

      {/* 按基金合并视图（主视图） */}
      {viewMode === "list" ? (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {t.positions.listTitle}
            {maxDate && <span className="ml-2 text-xs font-normal">{t.positions.navAsOf} {maxDate}</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
            {sortedRows.length === 0 ? (
            <EmptyState title={t.positions.noPositions} />
          ) : (
            <Table>
              <TableHeader>
                  <TableRow>
                    <SortHeader field="name">{t.common.name}</SortHeader>
                    <SortHeader field="type">{t.common.type}</SortHeader>
                    <SortHeader field="sector">{t.common.sector}</SortHeader>
                    <SortHeader field="value" className="text-right">{t.positions.marketValue}</SortHeader>
                    <SortHeader field="pnl" className="text-right">{t.positions.pnl}</SortHeader>
                    <SortHeader field="return" className="text-right">{t.positions.returnRate}</SortHeader>
                    <TableHead className="text-right">{t.positions.dailyChange}</TableHead>
                    <SortHeader field="channels" className="text-right">{t.common.channel}</SortHeader>
                    <TableHead className="w-20">{t.common.actions}</TableHead>
                    <TableHead className="w-8"></TableHead>
                  </TableRow>
              </TableHeader>
              <TableBody>
                {sortedRows.map(([code, m]) => {
                  const ret = m.cost ? m.value / m.cost - 1 : null
                  const breakevenGain = m.avgCost && m.latestNav && m.latestNav < m.avgCost ? m.avgCost / m.latestNav - 1 : null
                  return (
                    <TableRow
                      key={code}
                      className="cursor-pointer"
                      onClick={() => navigate(`/fund/${code}`)}
                      tabIndex={0}
                      role="button"
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(`/fund/${code}`) } }}
                    >
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium max-w-[160px] truncate" title={m.name}>{m.name}</span>
                          <span className="font-mono text-xs text-muted-foreground">{code}</span>
                        </div>
                      </TableCell>
                      <TableCell><Badge variant="outline">{translateFundType(m.type)}</Badge></TableCell>
                      <TableCell>
                        <div className="flex flex-col items-start gap-0.5">
                          {m.sector ? <Badge variant="outline" className="font-normal">{translateSector(m.sector)}</Badge> : <span className="text-xs text-muted-foreground">—</span>}
                          {m.trackingIndex && (
                            <span className="text-xs text-muted-foreground">{m.trackingIndex}</span>
                          )}
                        </div>
                      </TableCell>
<TableCell className="text-right tabular-nums font-medium">
                        <div className="flex flex-col items-end">
                          <span>{money(m.value)}</span>
                          <span className={`text-xs font-normal ${m.latestDate === today ? "text-muted-foreground" : "text-warning"}`}>
                            {m.latestDate ?? "—"}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className={`text-right tabular-nums ${pnlColor(m.pnl)}`}>{money(m.pnl)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${pnlColor(ret)}`}>
                        <div className="flex flex-col items-end">
                          <span>{pct(ret)}</span>
                          {breakevenGain != null && (
                            <span className="text-xs font-normal text-warning">{t.positions.breakeven} {pct(breakevenGain)}</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {estimateMap[code] != null ? (() => {
                          const e = estimateMap[code]
                          const scaledPnl = e.shares ? (m.shares / e.shares) * e.pnl : e.pnl
                          return (
                            <div className="flex flex-col items-end">
                              <span className={cn(pnlColor(e.gszzl / 100), !e.ok && "opacity-70")}>
                                {pct(e.gszzl / 100)}
                                {e.ok && <span className="ml-0.5 text-[10px] opacity-50">{t.positions.estLabel}</span>}
                              </span>
                              {!e.ok && e.pnl !== 0 && (
                                <span className={cn("text-xs font-normal", pnlColor(scaledPnl))}>
                                  {signedMoney(scaledPnl)}
                                </span>
                              )}
                            </div>
                          )
                        })() : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{m.channels}</TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs text-gain border-gain/30 hover:bg-gain/5"
                            onClick={() => navigate(`/transactions?code=${code}&action=buy${m.channel ? `&channel=${encodeURIComponent(m.channel)}` : ""}`)}
                            title={t.transactions.buy}
                          >
                            <TrendingUp className="h-3 w-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs text-loss border-loss/30 hover:bg-loss/5"
                            onClick={() => navigate(`/transactions?code=${code}&action=sell${m.channel ? `&channel=${encodeURIComponent(m.channel)}` : ""}`)}
                            title={t.transactions.sell}
                          >
                            <TrendingDown className="h-3 w-3" />
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <ChevronRight className="h-4 w-4" />
                      </TableCell>
                    </TableRow>
                  )
                })}
                {(() => {
                  const totalValue = sortedRows.reduce((s, [, m]) => s + m.value, 0)
                  const totalCost = sortedRows.reduce((s, [, m]) => s + m.cost, 0)
                  const totalPnl = sortedRows.reduce((s, [, m]) => s + m.pnl, 0)
                  const totalRet = totalCost ? totalValue / totalCost - 1 : null
                  const totalEstPnl = sortedRows.reduce((s, [code, m]) => {
                    const e = estimateMap[code]
                    if (!e?.shares) return s
                    return s + (m.shares / e.shares) * e.pnl
                  }, 0)
                  const hasFilteredEstimate = sortedRows.some(([code]) => estimateMap[code] != null)
                  return (
                    <TableRow className="border-t-2 border-border bg-muted/80 [&>td]:py-2.5 [&>td]:font-bold [&>td]:text-sm">
                      <TableCell colSpan={3} className="text-foreground">{t.common.total}（{sortedRows.length} {t.common.units}）</TableCell>
                      <TableCell className="text-right tabular-nums text-foreground">{money(totalValue)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${pnlColor(totalPnl)}`}>{money(totalPnl)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${pnlColor(totalRet)}`}>{pct(totalRet)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${hasFilteredEstimate ? pnlColor(totalEstPnl) : ""}`}>
                        {hasFilteredEstimate ? signedMoney(totalEstPnl) : "—"}
                      </TableCell>
                      <TableCell colSpan={3}></TableCell>
                    </TableRow>
                  )
                })()}
              </TableBody>
            </Table>
          )}
          <p className="mt-3 text-sm text-muted-foreground">{t.positions.fundCountHint.replace("{n}", String(sortedRows.length))}</p>
        </CardContent>
      </Card>
      ) : (
      <div className="space-y-4">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{t.positions.listTitle}{maxDate && <span className="ml-2 text-xs">{t.positions.navAsOf} {maxDate}</span>}</span>
        </div>
        {sortedRows.length === 0 ? (
          <EmptyState title={t.positions.noPositions} />
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {sortedRows.map(([code, m]) => {
                const ret = m.cost ? m.value / m.cost - 1 : null
                const breakevenGain = m.avgCost && m.latestNav && m.latestNav < m.avgCost ? m.avgCost / m.latestNav - 1 : null
                const est = estimateMap[code]
                const scaledEstPnl = est?.shares ? (m.shares / est.shares) * est.pnl : est?.pnl
                const weight = totalValue > 0 ? (m.value / totalValue) * 100 : 0
                const weightColor = m.pnl >= 0 ? "bg-gain-500" : breakevenGain != null ? "bg-loss-500" : "bg-muted-foreground"
                return (
                  <div
                    key={code}
                    className="card-hover bg-card rounded-xl p-5 cursor-pointer"
                    onClick={() => navigate(`/fund/${code}`)}
                    tabIndex={0}
                    role="button"
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(`/fund/${code}`) } }}
                  >
                    {/* Header */}
                    <div className="flex items-start justify-between mb-4">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-sm truncate" title={m.name}>{m.name}</p>
                          <span className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground shrink-0">{translateFundType(m.type)}</span>
                        </div>
                        <p className="font-mono text-xs text-muted-foreground mt-0.5">
                          {code}{m.sector ? ` · ${translateSector(m.sector)}` : ""}{m.trackingIndex ? ` · ${m.trackingIndex}` : ""}{` · ${m.channels} ${t.positions.channelCount}`}
                        </p>
                      </div>
                      <div className="flex gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 w-7 p-0 text-gain border-gain/30 hover:bg-gain/5"
                          onClick={() => navigate(`/transactions?code=${code}&action=buy${m.channel ? `&channel=${encodeURIComponent(m.channel)}` : ""}`)}
                          title={t.transactions.buy}
                        >
                          <TrendingUp className="h-3 w-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 w-7 p-0 text-loss border-loss/30 hover:bg-loss/5"
                          onClick={() => navigate(`/transactions?code=${code}&action=sell${m.channel ? `&channel=${encodeURIComponent(m.channel)}` : ""}`)}
                          title={t.transactions.sell}
                        >
                          <TrendingDown className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                    {/* Main: value + return */}
                    <div className="flex items-end justify-between mb-3">
                      <div>
                        <p className="text-xs text-muted-foreground mb-0.5">{t.positions.marketValue}</p>
                        <p className="text-xl font-bold tabular-nums">{money(m.value)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground mb-0.5">{t.positions.returnRate}</p>
                        {ret != null ? (
                          <p className={cn("text-xl font-bold tabular-nums", pnlColor(ret))}>{pct(ret)}</p>
                        ) : (
                          <p className="text-sm font-medium text-warning">T+1</p>
                        )}
                      </div>
                    </div>
                    {/* Weight bar */}
                    <div className="mb-3">
                      <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                        <span>{t.positions.weight}</span>
                        <span className="tabular-nums">{pct(weight / 100)}</span>
                      </div>
                      <div className="h-1 rounded-full bg-muted-foreground/15 overflow-hidden">
                        <div className={cn("h-full rounded-full transition-all", weightColor)} style={{ width: `${Math.min(weight, 100)}%` }} />
                      </div>
                    </div>
                    {/* Detail grid */}
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs tabular-nums pt-3 border-t border-border/50">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">{t.positions.pnl}</span>
                        <span className={cn("font-medium", pnlColor(m.pnl))}>{money(m.pnl)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">{t.positions.dailyChange}</span>
                        {est != null ? (
                          <span className={cn(pnlColor(est.gszzl / 100), !est.ok && "opacity-70")}>
                            {pct(est.gszzl / 100)}{est.ok && <span className="ml-0.5 text-[10px] opacity-50">{t.positions.estLabel}</span>}
                          </span>
                        ) : <span className="text-muted-foreground">—</span>}
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">{t.positions.costPerUnit}</span>
                        <span>{m.avgCost != null ? `¥${m.avgCost.toFixed(4)}` : "—"}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">{t.positions.latestNav}</span>
                        {m.latestNav != null ? (
                          <span>{m.latestNav.toFixed(4)} <span className="text-muted-foreground text-[10px]">{m.latestDate}</span></span>
                        ) : <span className="text-muted-foreground">—</span>}
                      </div>
                      {!est?.ok && scaledEstPnl != null && scaledEstPnl !== 0 && (
                        <div className="flex justify-between col-span-2">
                          <span className="text-muted-foreground">{t.positions.dailyChange}</span>
                          <span className={cn(pnlColor(scaledEstPnl))}>{signedMoney(scaledEstPnl)}</span>
                        </div>
                      )}
                      {breakevenGain != null && (
                        <div className="flex justify-between col-span-2">
                          <span className="text-warning">{t.positions.breakeven}</span>
                          <span className="text-warning tabular-nums">{pct(breakevenGain)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
            {/* Summary strip */}
            <div className="rounded-xl border border-border/50 bg-card px-5 py-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{t.positions.fundCountHintGrid.replace("{n}", String(sortedRows.length))}</span>
                <div className="flex items-center gap-6 tabular-nums">
                  <span className="text-muted-foreground">{t.positions.positionsTotal} <strong className="text-foreground">{money(totalValue)}</strong></span>
                  <span className={cn(pnlColor(totalPnl))}>{t.positions.pnl} <strong>{money(totalPnl)}</strong></span>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
      )}
        </TabsContent>
        <TabsContent value="exposure" className="space-y-4">
          <IndustryExposurePanel />
        </TabsContent>
        <TabsContent value="closed" className="space-y-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t.positions.closedRecords}</CardTitle>
          </CardHeader>
          <CardContent>
            {(() => {
              const openCodes = new Set(positions.filter(p => p.is_open).map(p => p.fund_code))
              const closed = positions.filter((p) => !p.is_open && !openCodes.has(p.fund_code) && (!channelFilter || p.channel === channelFilter))
              const closedMerged: Record<string, { name: string; realized: number; channels: number }> = {}
              for (const p of closed) {
                const m = closedMerged[p.fund_code] ?? { name: p.fund_name, realized: 0, channels: 0 }
                m.realized += p.realized_pnl
                m.channels += 1
                closedMerged[p.fund_code] = m
              }
              const closedEntries = Object.entries(closedMerged)
              const toggleClosedSort = (field: string) => {
                if (closedSortField === field) setClosedSortDir((d) => (d === "asc" ? "desc" : "asc"))
                else { setClosedSortField(field); setClosedSortDir("desc") }
              }
              const closedSorted = [...closedEntries].sort(([, a], [, b]) => {
                const va = closedSortField === "name" ? a.name : closedSortField === "channels" ? a.channels : a.realized
                const vb = closedSortField === "name" ? b.name : closedSortField === "channels" ? b.channels : b.realized
                const cmp = typeof va === "string" && typeof vb === "string" ? va.localeCompare(vb) : (va as number) - (vb as number)
                return closedSortDir === "asc" ? cmp : -cmp
              })
              function ClosedSortHeader({ field, children, className }: { field: string; children: React.ReactNode; className?: string }) {
                const active = closedSortField === field
                return (
                  <TableHead className={cn("cursor-pointer select-none", active ? "text-foreground" : "", className)} onClick={() => toggleClosedSort(field)}>
                    <span className="inline-flex items-center gap-1">
                      {children}
                      {active && (closedSortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
                    </span>
                  </TableHead>
                )
              }
              if (closedSorted.length === 0) return <p className="py-4 text-center text-muted-foreground">{t.positions.noClosedRecords}</p>
              return (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <ClosedSortHeader field="name">{t.common.name}</ClosedSortHeader>
                      <ClosedSortHeader field="realized" className="text-right">{t.positions.realizedPnl}</ClosedSortHeader>
                      <ClosedSortHeader field="channels" className="text-right">{t.positions.channelCount}</ClosedSortHeader>
                      <TableHead className="w-8"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {closedSorted.map(([code, m]) => (
                      <TableRow
                        key={code}
                        className="cursor-pointer"
                        onClick={() => navigate(`/fund/${code}`)}
                      >
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium max-w-[160px] truncate" title={m.name}>{m.name}</span>
                            <span className="font-mono text-xs text-muted-foreground">{code}</span>
                          </div>
                        </TableCell>
                        <TableCell className={`text-right tabular-nums ${pnlColor(m.realized)}`}>{money(m.realized)}</TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">{m.channels}</TableCell>
                        <TableCell className="text-muted-foreground"><ChevronRight className="h-4 w-4" /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )
            })()}
          </CardContent>
        </Card>
        </TabsContent>
      </Tabs>
      </>
      )}
    </div>
  )
}