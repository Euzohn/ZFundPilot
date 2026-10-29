import { useState, useCallback, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { WatchlistItem, DeletedWatchlistItem } from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { translateFundType, translateSector } from "@/lib/taxonomyLabels"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import ConfirmDialog from "@/components/ConfirmDialog"
import { Star, Trash2, GitCompare, ArrowLeftRight, ExternalLink, Plus, RotateCcw } from "lucide-react"
import { useLang } from "@/i18n/LanguageContext"
import { useCompare } from "@/contexts/CompareContext"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { makeSortHeader } from "@/components/SortHeader"

export default function Watchlist() {
  const navigate = useNavigate()
  const { t } = useLang()
  const { addCode } = useCompare()
  const [code, setCode] = useState("")
  const [note, setNote] = useState("")
  const [groupName, setGroupName] = useState("")
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState("")
  const [removingCode, setRemovingCode] = useState<string | null>(null)
  const [activeGroup, setActiveGroup] = useState("")
  const [showDeleted, setShowDeleted] = useState(false)
  const [deleted, setDeleted] = useState<DeletedWatchlistItem[]>([])
  const [deletedLoading, setDeletedLoading] = useState(false)
  const [restoringCode, setRestoringCode] = useState<string | null>(null)

  const fetcher = useCallback(() => api.getWatchlist(), [])
  const { data: items, loading, error, reload } = useApi(fetcher)

  const positionsFetcher = useCallback(() => api.getPositions(), [])
  const { data: positions } = useApi(positionsFetcher)

  const heldCodes = useMemo(() => new Set(positions?.map((p) => p.fund_code) ?? []), [positions])

  const groups = useMemo(() => {
    if (!items) return []
    const set = new Set<string>()
    for (const it of items) {
      if (it.group_name) set.add(it.group_name)
    }
    return Array.from(set).sort()
  }, [items])

  const filtered = useMemo(() => {
    if (!items) return []
    if (!activeGroup) return items
    if (activeGroup === "__ungrouped__") return items.filter((it) => !it.group_name)
    return items.filter((it) => it.group_name === activeGroup)
  }, [items, activeGroup])

  type SortField = "code" | "name" | "type" | "sector" | "group" | "added_at"
  const [sortField, setSortField] = useState<SortField>("added_at")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((d) => d === "asc" ? "desc" : "asc")
    } else {
      setSortField(field as SortField)
      setSortDir("desc")
    }
  }

  const getSortValue = (item: WatchlistItem, field: SortField): string => {
    switch (field) {
      case "code": return item.fund_code
      case "name": return item.fund_name ?? ""
      case "type": return item.fund_type ?? ""
      case "sector": return item.sector ?? ""
      case "group": return item.group_name ?? ""
      case "added_at": return item.added_at ?? ""
    }
  }

  const sorted = useMemo(() => {
    const copy = [...filtered]
    copy.sort((a, b) => {
      const va = getSortValue(a, sortField)
      const vb = getSortValue(b, sortField)
      const cmp = va.localeCompare(vb)
      return sortDir === "asc" ? cmp : -cmp
    })
    return copy
  }, [filtered, sortField, sortDir])

  const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })

  const handleAdd = async () => {
    const c = code.trim()
    if (!c) { setAddError(t.watchlist.enterCode); return }
    if (!/^\d{6}$/.test(c)) { setAddError(t.watchlist.invalidCode); return }
    setAdding(true)
    setAddError("")
    try {
      await api.addToWatchlist(c, note.trim(), groupName.trim())
      setCode("")
      setNote("")
      setGroupName("")
      reload()
      toast.success(t.watchlist.added)
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : t.watchlist.addFailed)
    } finally {
      setAdding(false)
    }
  }

  const handleRemove = async (c: string) => {
    const item = items?.find((it) => it.fund_code === c)
    if (!item) return
    try {
      await api.removeFromWatchlist(c, item.revision)
      reload()
      toast.success(t.watchlist.removed)
    } catch (e: unknown) {
      if ((e as { code?: string }).code === "revision_conflict") {
        reload()
        toast.error(t.watchlist.conflictRetry)
      } else {
        toast.error(t.watchlist.removeFailed)
      }
    }
  }

  const handleGroupChange = async (code: string, value: string, revision: number) => {
    try {
      await api.updateWatchlistGroup(code, value.trim(), revision)
      reload()
    } catch (e: unknown) {
      if ((e as { code?: string }).code === "revision_conflict") {
        reload()
        toast.error(t.watchlist.conflictRetry)
      } else {
        toast.error(t.watchlist.groupUpdateFailed)
      }
    }
  }

  const loadDeleted = async () => {
    setDeletedLoading(true)
    try {
      const data = await api.getDeletedWatchlist()
      setDeleted(data.items)
    } catch {
      toast.error(t.watchlist.restoreFailed)
    } finally {
      setDeletedLoading(false)
    }
  }

  const toggleDeleted = () => {
    const next = !showDeleted
    setShowDeleted(next)
    if (next) loadDeleted()
  }

  const handleRestore = async (item: DeletedWatchlistItem) => {
    setRestoringCode(item.fund_code)
    try {
      await api.restoreWatchlistItem(item.fund_code, item.revision)
      toast.success(t.watchlist.restored)
      await loadDeleted()
      reload()
    } catch (e: unknown) {
      if ((e as { code?: string }).code === "revision_conflict") {
        await loadDeleted()
        toast.error(t.watchlist.conflictRetry)
      } else {
        toast.error(t.watchlist.restoreFailed)
      }
    } finally {
      setRestoringCode(null)
    }
  }

  const addToCompare = (c: string) => {
    addCode(c)
    toast.success(t.watchlist.addedToCompare)
  }
  const buyFund = (c: string) => navigate(`/transactions?code=${c}&action=buy`)
  const viewDetail = (c: string) => navigate(`/fund/${c}`)

  return (
    <div className="space-y-6">
      <PageHeader title={t.watchlist.title} icon={<Star className="h-5 w-5" />} />

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              value={code}
              onChange={(e) => { setCode(e.target.value); setAddError("") }}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) handleAdd() }}
              placeholder={t.watchlist.codePlaceholder}
              className="h-9 text-sm sm:w-40"
            />
            <Input
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) handleAdd() }}
              placeholder={t.watchlist.groupPlaceholder}
              className="h-9 text-sm sm:w-32"
              list="watchlist-groups"
            />
            <datalist id="watchlist-groups">
              {groups.map((g) => <option key={g} value={g} />)}
            </datalist>
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) handleAdd() }}
              placeholder={t.watchlist.notePlaceholder}
              className="h-9 text-sm flex-1"
            />
            <Button size="sm" onClick={handleAdd} disabled={adding}>
              <Plus className="mr-1 h-4 w-4" />
              {adding ? t.common.processing : t.watchlist.addToWatchlist}
            </Button>
          </div>
          {addError && <p className="mt-2 text-xs text-loss-600">{addError}</p>}
        </CardContent>
      </Card>

      {loading && <LoadingState />}
      {error && <ErrorState message={error} onRetry={reload} />}

      {!loading && !error && items && items.length === 0 && (
        <Card>
          <CardContent className="py-16">
            <EmptyState title={t.watchlist.empty} size="lg" />
          </CardContent>
        </Card>
      )}

      {!loading && !error && items && items.length > 0 && (
        <>
          {/* Group selector */}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setActiveGroup("")}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs transition-colors",
                !activeGroup ? "border-primary/40 bg-primary/10 text-primary" : "border-border hover:bg-muted/50",
              )}
            >
              {t.watchlist.allGroups} ({items.length})
            </button>
            {groups.map((g) => {
              const count = items.filter((it) => it.group_name === g).length
              return (
                <button
                  key={g}
                  onClick={() => setActiveGroup(g)}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition-colors",
                    activeGroup === g ? "border-primary/40 bg-primary/10 text-primary" : "border-border hover:bg-muted/50",
                  )}
                >
                  {g} ({count})
                </button>
              )
            })}
            {items.some((it) => !it.group_name) && (
              <button
                onClick={() => setActiveGroup("__ungrouped__")}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs transition-colors",
                  activeGroup === "__ungrouped__" ? "border-primary/40 bg-primary/10 text-primary" : "border-border hover:bg-muted/50",
                )}
              >
                {t.watchlist.ungrouped} ({items.filter((it) => !it.group_name).length})
              </button>
            )}
          </div>

          <div className="overflow-x-auto rounded-md border">
            <Table className="w-full text-sm [&_td]:px-2 [&_th]:px-2 sm:[&_td]:px-3 sm:[&_th]:px-3">
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <SortHeader field="code" className="sticky left-0 z-20 bg-muted/50 border-r border-border/60 px-3 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">{t.common.code}</SortHeader>
                  <SortHeader field="name" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.name}</SortHeader>
                  <SortHeader field="type" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.type}</SortHeader>
                  <SortHeader field="sector" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.compare.sector}</SortHeader>
                  <SortHeader field="group" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.watchlist.group}</SortHeader>
                  <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.note}</TableHead>
                  <SortHeader field="added_at" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.watchlist.addedAt}</SortHeader>
                  <TableHead className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((item) => (
                  <TableRow key={item.fund_code} className="border-t border-border/50">
                    <TableCell className="sticky left-0 z-10 bg-background border-r border-border/60 px-3 py-2 font-mono text-xs whitespace-nowrap">{item.fund_code}</TableCell>
                    <TableCell className="max-w-[200px] px-3 py-2 text-xs">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate" title={item.fund_name}>{item.fund_name || "—"}</span>
                        {heldCodes.has(item.fund_code) && (
                          <Badge variant="outline" className="shrink-0 text-success border-success/40 bg-success/10 text-[10px] px-1.5 py-0">
                            {t.watchlist.held}
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs">{item.fund_type ? translateFundType(item.fund_type) : "—"}</TableCell>
                    <TableCell className="px-3 py-2 text-xs">
                      <div className="flex flex-col gap-0.5">
                        <span>{item.sector ? translateSector(item.sector) : "—"}</span>
                        {item.tracking_index && (
                          <span className="text-muted-foreground">{item.tracking_index}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs">
                      <Input
                        defaultValue={item.group_name}
                        onBlur={(e) => {
                          const v = e.target.value.trim()
                          if (v !== item.group_name) handleGroupChange(item.fund_code, v, item.revision)
                        }}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) e.currentTarget.blur() }}
                        placeholder={t.watchlist.groupPlaceholder}
                        className="h-7 w-24 text-xs"
                        list="watchlist-groups"
                      />
                    </TableCell>
                    <TableCell className="max-w-[120px] truncate px-3 py-2 text-xs text-muted-foreground" title={item.note}>
                      {item.note || "—"}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs text-muted-foreground">{item.added_at?.slice(0, 10) ?? "—"}</TableCell>
                    <TableCell className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => viewDetail(item.fund_code)} title={t.watchlist.viewDetail}>
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => addToCompare(item.fund_code)} title={t.watchlist.compare}>
                          <GitCompare className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => buyFund(item.fund_code)} title={t.watchlist.buy}>
                          <ArrowLeftRight className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-loss-600 hover:text-loss-700" onClick={() => setRemovingCode(item.fund_code)} title={t.common.delete}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
      <div className="space-y-2">
        <Button variant="ghost" size="sm" onClick={toggleDeleted}>
          <RotateCcw className="mr-1 h-3.5 w-3.5" />
          {t.watchlist.recentlyDeleted}
        </Button>
        {showDeleted && (
          <Card>
            <CardContent className="p-3">
              {deletedLoading ? (
                <p className="text-xs text-muted-foreground">{t.common.loading}</p>
              ) : deleted.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t.watchlist.nothingDeleted}</p>
              ) : (
                <ul className="divide-y divide-border/50">
                  {deleted.map((item) => (
                    <li key={item.fund_code} className="flex flex-wrap items-center gap-2 py-2 text-xs">
                      <span className="font-mono">{item.fund_code}</span>
                      <span className="truncate">{item.fund_name || "—"}</span>
                      {item.group_name && <Badge variant="outline">{item.group_name}</Badge>}
                      <span className="text-muted-foreground">
                        {t.watchlist.deletedAt}: {item.deleted_at.slice(0, 10)}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        className="ml-auto h-7"
                        disabled={restoringCode === item.fund_code}
                        onClick={() => handleRestore(item)}
                      >
                        {t.watchlist.restore}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <ConfirmDialog
        open={removingCode !== null}
        onOpenChange={(open) => { if (!open) setRemovingCode(null) }}
        title={t.watchlist.removeFromWatchlist}
        description={t.common.confirmDelete}
        tone="destructive"
        onConfirm={() => { if (removingCode) { handleRemove(removingCode); setRemovingCode(null) } }}
      />
    </div>
  )
}
