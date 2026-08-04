import { useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { WatchlistItem } from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { translateFundType, translateSector } from "@/lib/taxonomyLabels"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import { Star, Trash2, GitCompare, ArrowLeftRight, ExternalLink, Plus } from "lucide-react"
import { useLang } from "@/i18n/LanguageContext"
import { toast } from "sonner"

export default function Watchlist() {
  const navigate = useNavigate()
  const { t } = useLang()
  const [code, setCode] = useState("")
  const [note, setNote] = useState("")
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState("")

  const fetcher = useCallback(() => api.getWatchlist(), [])
  const { data: items, loading, error, reload } = useApi(fetcher)

  const handleAdd = async () => {
    const c = code.trim()
    if (!c) { setAddError(t.watchlist.enterCode); return }
    if (!/^\d{6}$/.test(c)) { setAddError(t.watchlist.invalidCode); return }
    setAdding(true)
    setAddError("")
    try {
      await api.addToWatchlist(c, note.trim())
      setCode("")
      setNote("")
      reload()
      toast.success(t.watchlist.added)
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : t.watchlist.addFailed)
    } finally {
      setAdding(false)
    }
  }

  const handleRemove = async (c: string) => {
    try {
      await api.removeFromWatchlist(c)
      reload()
      toast.success(t.watchlist.removed)
    } catch {
      toast.error(t.watchlist.removeFailed)
    }
  }

  const addToCompare = (c: string) => {
    navigate(`/compare?codes=${c}`)
  }

  const buyFund = (c: string) => {
    navigate(`/transactions?code=${c}&action=buy`)
  }

  const viewDetail = (c: string) => {
    navigate(`/fund/${c}`)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Star className="h-5 w-5 text-primary" />
        <PageHeader title={t.watchlist.title} tracking="tight" />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              value={code}
              onChange={(e) => { setCode(e.target.value); setAddError("") }}
              onKeyDown={(e) => { if (e.key === "Enter") handleAdd() }}
              placeholder={t.watchlist.codePlaceholder}
              className="h-9 text-sm sm:w-40"
            />
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleAdd() }}
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
        <div className="overflow-x-auto rounded-md border">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.code}</TableHead>
                <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.name}</TableHead>
                <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.type}</TableHead>
                <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.compare.sector}</TableHead>
                <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.common.note}</TableHead>
                <TableHead className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{t.watchlist.addedAt}</TableHead>
                <TableHead className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">{t.common.actions}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.fund_code} className="border-t border-border/50">
                  <TableCell className="px-3 py-2 font-mono text-xs">{item.fund_code}</TableCell>
                  <TableCell className="max-w-[200px] truncate px-3 py-2 text-xs" title={item.fund_name}>
                    {item.fund_name || "—"}
                  </TableCell>
                  <TableCell className="px-3 py-2 text-xs">{item.fund_type ? translateFundType(item.fund_type) : "—"}</TableCell>
                  <TableCell className="px-3 py-2 text-xs">{item.sector ? translateSector(item.sector) : "—"}</TableCell>
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
                      <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-loss-600 hover:text-loss-700" onClick={() => handleRemove(item.fund_code)} title={t.common.delete}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
