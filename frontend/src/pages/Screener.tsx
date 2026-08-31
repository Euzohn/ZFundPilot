import { useState, useCallback, useEffect, useMemo, useRef } from "react"
import { api } from "@/api/client"
import type { FundFilterItem } from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { translateFundType, translateSector } from "@/lib/taxonomyLabels"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { makeSortHeader } from "@/components/SortHeader"
import { pct, pnlColor } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useLang } from "@/i18n/LanguageContext"
import { useCompare } from "@/contexts/CompareContext"
import { toast } from "sonner"
import { Search, RefreshCw, Check, Star, GitCompare, Loader2 } from "lucide-react"

type SortField = "code" | "1y" | "max_drawdown" | "volatility" | "scale"

export default function Screener() {
  const { t } = useLang()
  const { addCodes } = useCompare()

  const [types, setTypes] = useState<string[]>([])
  const [sectors, setSectors] = useState<string[]>([])
  const [keyword, setKeyword] = useState("")
  const [results, setResults] = useState<FundFilterItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [metricsLoading, setMetricsLoading] = useState(false)
  const [error, setError] = useState("")
  const [searched, setSearched] = useState(false)
  const [sortField, setSortField] = useState<SortField>("1y")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [availTypes, setAvailTypes] = useState<string[]>([])
  const [availSectors, setAvailSectors] = useState<string[]>([])

  const skipAutoSearch = useRef(true)
  const searchIdRef = useRef(0)

  useEffect(() => {
    api.getKeywordMaps().then((m) => {
      setAvailTypes(m.available_types)
      setAvailSectors(m.available_sectors)
    }).catch(() => {})
  }, [])

  const isCodeSearch = (kw: string) => /^\d{6}$/.test(kw)

  const handleSearch = useCallback(async () => {
    const kw = keyword.trim()
    const codeMode = isCodeSearch(kw)
    const searchTypes = codeMode ? [] : types
    const searchSectors = codeMode ? [] : sectors
    const mySearchId = ++searchIdRef.current

    setSearched(true)
    setError("")
    setSelected(new Set())
    setMetricsLoading(false)

    // Phase 1: basic results (fast)
    setLoading(true)
    setResults([])
    setTotal(0)
    try {
      const res = await api.filterFunds({
        types: searchTypes, sectors: searchSectors, keyword: kw, limit: 50, offset: 0,
        with_metrics: false,
      })
      if (mySearchId !== searchIdRef.current) return
      if (res.ok) {
        setResults(res.funds)
        setTotal(res.total)
      } else {
        setError(res.message)
        setLoading(false)
        return
      }
    } catch (e: unknown) {
      if (mySearchId !== searchIdRef.current) return
      setError(e instanceof Error ? e.message : t.screener.searchFailed)
      setLoading(false)
      return
    }
    setLoading(false)

    // Phase 2: enrich with metrics (slow, non-blocking)
    if (mySearchId !== searchIdRef.current) return
    setMetricsLoading(true)
    try {
      const res2 = await api.filterFunds({
        types: searchTypes, sectors: searchSectors, keyword: kw, limit: 50, offset: 0,
        with_metrics: true,
      })
      if (mySearchId !== searchIdRef.current) return
      if (res2.ok) {
        const metricsMap = new Map(res2.funds.map(f => [f.code, f]))
        setResults(prev => prev.map(f => {
          const m = metricsMap.get(f.code)
          return m ? { ...f, returns: m.returns, risk: m.risk, scale: m.scale, manager: m.manager, inception_date: m.inception_date } : f
        }))
      }
    } catch {
      // silently fail — basic results still usable
    } finally {
      if (mySearchId === searchIdRef.current) setMetricsLoading(false)
    }
  }, [types, sectors, keyword, t.screener.searchFailed])

  // Auto-search on filter chip change
  useEffect(() => {
    if (skipAutoSearch.current) {
      skipAutoSearch.current = false
      return
    }
    handleSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [types, sectors])

  const toggleType = (tp: string) => {
    setTypes((prev) => prev.includes(tp) ? prev.filter((x) => x !== tp) : [...prev, tp])
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

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((d) => d === "asc" ? "desc" : "asc")
    } else {
      setSortField(field as SortField)
      setSortDir("desc")
    }
  }

  const getSortValue = (f: FundFilterItem, field: SortField): number | string => {
    switch (field) {
      case "code": return f.code
      case "1y": return f.returns?.["1y"] ?? -Infinity
      case "max_drawdown": return f.risk?.max_drawdown ?? Infinity
      case "volatility": return f.risk?.volatility ?? Infinity
      case "scale": return f.scale ?? -Infinity
    }
  }

  const sorted = useMemo(() => {
    const copy = [...results]
    copy.sort((a, b) => {
      const va = getSortValue(a, sortField)
      const vb = getSortValue(b, sortField)
      const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
    return copy
  }, [results, sortField, sortDir])

  const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })

  const handleAddToCompare = () => {
    if (selected.size === 0) return
    addCodes(Array.from(selected))
    setSelected(new Set())
    toast.success(t.screener.addedToCompare.replace("{count}", String(selected.size)))
  }

  const handleAddSelectedToWatchlist = async () => {
    for (const code of selected) {
      try { await api.addToWatchlist(code) } catch { /* skip duplicates */ }
    }
    toast.success(t.watchlist.added)
    setSelected(new Set())
  }

  const codeMode = isCodeSearch(keyword.trim())

  const MetricCell = ({ value, color }: { value: number | null | undefined; color?: string }) => {
    if (value != null) {
      return <span className={cn("tabular-nums font-medium", color)}>{pct(value)}</span>
    }
    if (metricsLoading) {
      return <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/50" />
    }
    return <span className="text-muted-foreground">—</span>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Search className="h-5 w-5 text-primary" />
        <PageHeader title={t.screener.title} tracking="tight" />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="space-y-4">
            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">{t.compare.assetType}</p>
              <div className="flex flex-wrap gap-2">
                {availTypes.map((tp) => (
                  <label key={tp} className={cn(
                    "inline-flex cursor-pointer items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    types.includes(tp) ? "border-primary/40 bg-primary/10 text-primary" : "border-border hover:bg-muted/50",
                  )}>
                    <input type="checkbox" checked={types.includes(tp)} onChange={() => toggleType(tp)} className="sr-only" />
                    {types.includes(tp) && <Check className="h-3 w-3" />}
                    {tp}
                  </label>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">{t.compare.sector}</p>
              <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto">
                {availSectors.map((s) => (
                  <label key={s} className={cn(
                    "inline-flex cursor-pointer items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors shrink-0",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    sectors.includes(s) ? "border-primary/40 bg-primary/10 text-primary" : "border-border hover:bg-muted/50",
                  )}>
                    <input type="checkbox" checked={sectors.includes(s)} onChange={() => toggleSector(s)} className="sr-only" />
                    {sectors.includes(s) && <Check className="h-3 w-3" />}
                    {s}
                  </label>
                ))}
              </div>
            </div>

            <div className="flex gap-2">
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) handleSearch() }}
                placeholder={t.compare.nameOrCode}
                className="h-9 text-sm flex-1"
              />
              <Button size="sm" onClick={handleSearch} disabled={loading}>
                {loading ? <RefreshCw className="mr-1 h-4 w-4 animate-spin" /> : <Search className="mr-1 h-4 w-4" />}
                {loading ? t.screener.loadingMetrics : t.common.search}
              </Button>
            </div>

            {codeMode && (types.length > 0 || sectors.length > 0) && (
              <p className="text-xs text-muted-foreground">{t.screener.codeSearchHint}</p>
            )}
            {error && <p className="text-xs text-loss-600">{error}</p>}
          </div>
        </CardContent>
      </Card>

      {loading && (
        <Card>
          <CardContent className="py-16">
            <LoadingState />
          </CardContent>
        </Card>
      )}

      {!loading && !error && results.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <p className="text-xs text-muted-foreground">
                {t.compare.resultCount.replace("{total}", String(total)).replace("{shown}", String(results.length))}
              </p>
              {metricsLoading && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {t.screener.metricsLoading}
                </span>
              )}
            </div>
            {selected.size > 0 && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={handleAddToCompare}>
                  <GitCompare className="mr-1 h-3.5 w-3.5" />
                  {t.screener.addToCompare} ({selected.size})
                </Button>
                <Button size="sm" variant="outline" onClick={handleAddSelectedToWatchlist}>
                  <Star className="mr-1 h-3.5 w-3.5" />
                  {t.screener.addToWatchlist} ({selected.size})
                </Button>
              </div>
            )}
          </div>

          <div className="overflow-x-auto rounded-md border">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead className="w-8 px-2 py-2 text-left" />
                  <SortHeader field="code" className="px-2 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">{t.common.code}</SortHeader>
                  <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.name}</TableHead>
                  <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.type}</TableHead>
                  <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">{t.compare.sector}</TableHead>
                  <SortHeader field="1y" className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">{t.screener.return1y}</SortHeader>
                  <SortHeader field="max_drawdown" className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">{t.compare.maxDrawdown}</SortHeader>
                  <SortHeader field="volatility" className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">{t.compare.volatility}</SortHeader>
                  <SortHeader field="scale" className="px-2 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">{t.compare.scale}</SortHeader>
                  <TableHead className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">{t.compare.manager}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((f) => (
                  <TableRow key={f.code} className="border-t border-border/50">
                    <TableCell className="px-2 py-1.5">
                      <input type="checkbox" checked={selected.has(f.code)} onChange={() => toggleSelect(f.code)} className="h-4 w-4 accent-blue-600" aria-label={`${f.code} ${f.name}`} />
                    </TableCell>
                    <TableCell className="px-2 py-1.5 font-mono text-xs">{f.code}</TableCell>
                    <TableCell className="max-w-[200px] truncate px-2 py-1.5 text-xs" title={f.name}>{f.name}</TableCell>
                    <TableCell className="px-2 py-1.5 text-xs">{translateFundType(f.type)}</TableCell>
                    <TableCell className="px-2 py-1.5 text-xs">{f.sector ? translateSector(f.sector) : "—"}</TableCell>
                    <TableCell className="px-2 py-1.5 text-right text-xs">
                      <MetricCell value={f.returns?.["1y"]} color={pnlColor(f.returns?.["1y"] ?? 0)} />
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right text-xs">
                      <MetricCell value={f.risk?.max_drawdown} color="text-loss-600" />
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right text-xs">
                      <MetricCell value={f.risk?.volatility} />
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right text-xs tabular-nums">
                      {f.scale != null ? f.scale.toFixed(1) : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="max-w-[100px] truncate px-2 py-1.5 text-xs text-muted-foreground" title={f.manager}>{f.manager || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}

      {!loading && !error && results.length === 0 && searched && (
        <Card>
          <CardContent className="py-16">
            <EmptyState title={t.screener.noResults} size="lg" />
          </CardContent>
        </Card>
      )}

      {!loading && !error && results.length === 0 && !searched && (
        <Card>
          <CardContent className="py-16">
            <EmptyState title={t.screener.empty} size="lg" />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
