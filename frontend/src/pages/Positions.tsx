import { useState, useMemo, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Position, EstimateSummary } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import LogoSpinner from "@/components/LogoSpinner"
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
import { TrendingUp, TrendingDown, ChevronRight, ChevronUp, ChevronDown, Search } from "lucide-react"
import { makeSortHeader } from "@/components/SortHeader"
import { useLang } from "@/i18n/LanguageContext"

export default function Positions() {
  const navigate = useNavigate()
  const { t } = useLang()
  const [showClosed, setShowClosed] = useState(() => localStorage.getItem("zfundpilot_showClosed") === "true")
  const [channelFilter, setChannelFilter] = useState(() => localStorage.getItem("zfundpilot_channelFilter") ?? "")
  const [searchQuery, setSearchQuery] = useState("")
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

  // 持久化渠道筛选和显示已清仓选项
  useEffect(() => { localStorage.setItem("zfundpilot_showClosed", String(showClosed)) }, [showClosed])
  useEffect(() => { localStorage.setItem("zfundpilot_channelFilter", channelFilter) }, [channelFilter])

  const today = localDateStr()

  const view = positions
    ? (showClosed ? positions : positions.filter((p) => p.is_open)).filter((p) => !channelFilter || p.channel === channelFilter)
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

  return (
    <div className="space-y-6">
      {loading ? (
        <LoadingState />
      ) : !positions ? (
        <ErrorState message={error ?? undefined} onRetry={reload} />
      ) : (
      <>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <PageHeader title={t.positions.title} />
        <div className="flex items-center gap-2">
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
          <Select value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)} className="h-8 text-xs w-32">
            <option value="">{t.positions.allChannels}</option>
            {availableChannels.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
          <Button variant="outline" size="sm" onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? t.positions.hideClosed : t.positions.showClosed}
          </Button>
        </div>
      </div>

      {/* 按基金合并视图（主视图，简洁） */}
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
                    >
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium max-w-[160px] truncate" title={m.name}>{m.name}</span>
                          <span className="font-mono text-xs text-muted-foreground">{code}</span>
                          {m.trackingIndex && (
                            <span className="text-xs text-muted-foreground">跟踪 {m.trackingIndex}</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell><Badge variant="outline">{translateFundType(m.type)}</Badge></TableCell>
                      <TableCell>{m.sector ? <Badge variant="secondary" className="font-normal">{translateSector(m.sector)}</Badge> : <span className="text-xs text-muted-foreground">—</span>}</TableCell>
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
                          >
                            <TrendingUp className="h-3 w-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs text-loss border-loss/30 hover:bg-loss/5"
                            onClick={() => navigate(`/transactions?code=${code}&action=sell${m.channel ? `&channel=${encodeURIComponent(m.channel)}` : ""}`)}
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

      {/* 已清仓记录（仅在 showClosed 时显示） */}
      {showClosed && (
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
      )}
      </>
      )}
    </div>
  )
}