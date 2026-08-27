import { useState, useEffect, useCallback, useRef } from "react"
import { useLang } from "@/i18n/LanguageContext"
import { api } from "@/api/client"
import type { ParsedTxItem, ParsedHoldingItem, ReconcileResponse, Transaction } from "@/api/types"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { toast } from "sonner"
import { getChannels } from "@/lib/channels"
import { Camera, Upload, Loader2, Image as ImageIcon, X, RefreshCw, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface ScreenshotImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onImported?: () => void
}

type Mode = "transactions" | "holdings"

function todayStr(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export default function ScreenshotImportDialog({ open, onOpenChange, onImported }: ScreenshotImportDialogProps) {
  const { t } = useLang()
  const channels = getChannels()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<Mode>("transactions")
  const [channel, setChannel] = useState(channels[0] || "")
  const [image, setImage] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string>("")
  const [parsing, setParsing] = useState(false)
  const [parseError, setParseError] = useState("")
  const [txItems, setTxItems] = useState<ParsedTxItem[]>([])
  const [holdingItems, setHoldingItems] = useState<ParsedHoldingItem[]>([])
  const [reconcileResult, setReconcileResult] = useState<ReconcileResponse | null>(null)
  const [selectedDiff, setSelectedDiff] = useState<Set<number>>(new Set())
  const [reconciling, setReconciling] = useState(false)
  const [importing, setImporting] = useState(false)

  // Reset when dialog closes
  useEffect(() => {
    if (!open) {
      setImage(null)
      setImagePreview("")
      setParseError("")
      setTxItems([])
      setHoldingItems([])
      setReconcileResult(null)
      setSelectedDiff(new Set())
      setParsing(false)
      setReconciling(false)
      setImporting(false)
    }
  }, [open])

  // Cleanup object URL
  useEffect(() => {
    if (imagePreview) return () => URL.revokeObjectURL(imagePreview)
  }, [imagePreview])

  const handleImageSelect = (file: File | null | undefined) => {
    if (!file || !file.type.startsWith("image/")) {
      toast.error(t.transactions.screenshotParseFailed.replace("{error}", "not an image"))
      return
    }
    setImage(file)
    setImagePreview(URL.createObjectURL(file))
    setParseError("")
    setTxItems([])
    setHoldingItems([])
    setReconcileResult(null)
  }

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile()
        if (file) { handleImageSelect(file); e.preventDefault(); break }
      }
    }
  }, [t])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleImageSelect(file)
  }, [t])

  const handleParse = async () => {
    if (!image) return
    setParsing(true)
    setParseError("")
    setTxItems([])
    setHoldingItems([])
    setReconcileResult(null)
    try {
      const result = await api.parseScreenshot(image, mode, channel)
      if (!result.ok) {
        setParseError(result.error)
        return
      }
      if (mode === "transactions") {
        setTxItems(result.items as ParsedTxItem[])
      } else {
        setHoldingItems(result.items as ParsedHoldingItem[])
      }
    } catch (e) {
      setParseError(String(e))
    } finally {
      setParsing(false)
    }
  }

  const handleReconcile = async () => {
    const valid = holdingItems.filter(it => it.fund_code && it.code_status === "exact")
    if (valid.length === 0) {
      toast.error(t.transactions.screenshotNoItems)
      return
    }
    setReconciling(true)
    try {
      const result = await api.reconcileHoldings(
        valid.map(it => ({ fund_code: it.fund_code!, shares: it.shares, market_value: it.market_value })),
        channel,
      )
      setReconcileResult(result)
      // Default-select all buy/new/sell (not maybe_sold)
      const defaultSel = new Set<number>()
      result.items.forEach((it, i) => {
        if (it.status !== "ok" && it.status !== "maybe_sold") defaultSel.add(i)
      })
      setSelectedDiff(defaultSel)
    } catch (e) {
      toast.error(String(e))
    } finally {
      setReconciling(false)
    }
  }

  const toggleDiff = (i: number) => {
    setSelectedDiff(prev => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  const handleConfirmImport = async () => {
    let txs: Transaction[] = []
    if (mode === "transactions") {
      txs = txItems
        .filter(it => it.fund_code && /^\d{6}$/.test(it.fund_code))
        .map(it => ({
          fund_code: it.fund_code!,
          action: it.action || "buy",
          date: it.date || todayStr(),
          amount: it.amount,
          shares: it.shares,
          nav: it.nav,
          fee: it.fee ?? 0,
          channel: it.channel || channel,
          note: it.note || "",
          is_t1: it.is_t1 || false,
        }))
    } else if (reconcileResult) {
      txs = reconcileResult.items
        .filter((_, i) => selectedDiff.has(i))
        .filter(it => it.suggested_tx)
        .map(it => ({
          fund_code: it.suggested_tx!.fund_code,
          action: it.suggested_tx!.action,
          date: todayStr(),
          amount: it.suggested_tx!.amount,
          shares: it.suggested_tx!.shares,
          nav: it.suggested_tx!.nav,
          fee: it.suggested_tx!.fee,
          channel: it.suggested_tx!.channel || channel,
          note: it.suggested_tx!.note,
          is_t1: it.suggested_tx!.is_t1,
        }))
    }
    if (txs.length === 0) {
      toast.error(t.transactions.screenshotNoSelected)
      return
    }
    setImporting(true)
    try {
      const res = await api.confirmImport(txs, false, true)
      toast.success(t.transactions.screenshotImportSuccess.replace("{n}", String(res.imported)))
      onOpenChange(false)
      onImported?.()
    } catch (e) {
      toast.error(`${t.transactions.importFailed}: ${e}`)
    } finally {
      setImporting(false)
    }
  }

  const updateTxItem = (idx: number, patch: Partial<ParsedTxItem>) => {
    setTxItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))
  }
  const updateHoldingItem = (idx: number, patch: Partial<ParsedHoldingItem>) => {
    setHoldingItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))
  }

  const hasImage = !!image
  const hasParsed = mode === "transactions" ? txItems.length > 0 : holdingItems.length > 0
  const validTxCount = txItems.filter(it => it.fund_code && /^\d{6}$/.test(it.fund_code)).length
  const selectedTxCount = mode === "transactions"
    ? validTxCount
    : reconcileResult ? reconcileResult.items.filter((_, i) => selectedDiff.has(i)).length : 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col" onCloseAutoFocus={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Camera className="h-5 w-5" />
            {t.transactions.screenshotImportTitle}
          </DialogTitle>
          <DialogDescription>{t.transactions.screenshotImportHint}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {/* Mode + Channel */}
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <Label className="mb-1 block text-xs text-muted-foreground">{t.transactions.screenshotSelectChannel}</Label>
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-xs"
              >
                <option value="">{t.transactions.screenshotSelectChannelHint}</option>
                {channels.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="flex gap-1 rounded-lg border border-border p-0.5">
              <button
                onClick={() => { setMode("transactions"); setTxItems([]); setReconcileResult(null) }}
                className={cn("rounded px-3 py-1 text-xs font-medium transition-colors",
                  mode === "transactions" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
              >
                {t.transactions.screenshotModeTx}
              </button>
              <button
                onClick={() => { setMode("holdings"); setHoldingItems([]); setReconcileResult(null) }}
                className={cn("rounded px-3 py-1 text-xs font-medium transition-colors",
                  mode === "holdings" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
              >
                {t.transactions.screenshotModeHoldings}
              </button>
            </div>
            <p className="text-[10px] text-muted-foreground pb-1">
              {mode === "transactions" ? t.transactions.screenshotModeTxHint : t.transactions.screenshotModeHoldingsHint}
            </p>
          </div>

          {/* Upload area */}
          {!hasParsed && !reconcileResult && (
            <div
              onPaste={handlePaste}
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              className="relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border/60 p-8 text-center transition-colors hover:border-primary/40"
            >
              {imagePreview ? (
                <div className="relative">
                  <img src={imagePreview} alt="preview" className="max-h-48 rounded-md object-contain" />
                  <button
                    onClick={() => { setImage(null); setImagePreview("") }}
                    className="absolute -top-2 -right-2 rounded-full bg-destructive text-destructive-foreground p-1"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ) : (
                <>
                  <ImageIcon className="h-10 w-10 text-muted-foreground/40 mb-2" />
                  <p className="text-sm text-muted-foreground">{t.transactions.screenshotPaste}</p>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => handleImageSelect(e.target.files?.[0])}
              />
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload className="mr-1.5 h-3.5 w-3.5" />
                {t.transactions.screenshotUpload}
              </Button>
            </div>
          )}

          {/* Parse button */}
          {hasImage && !hasParsed && !reconcileResult && (
            <Button onClick={handleParse} disabled={parsing} className="w-full">
              {parsing ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Camera className="mr-1.5 h-4 w-4" />}
              {parsing ? t.transactions.screenshotParsing : t.transactions.screenshotUpload}
            </Button>
          )}

          {/* Parse error */}
          {parseError && (
            <div className="rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2 text-xs text-destructive">
              {t.transactions.screenshotParseFailed.replace("{error}", parseError)}
            </div>
          )}

          {/* Transactions preview */}
          {mode === "transactions" && txItems.length > 0 && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {t.transactions.screenshotPreviewTx.replace("{n}", String(txItems.length))}
              </p>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">{t.transactions.fundCode}</th>
                      <th className="px-2 py-1.5 text-left font-medium">{t.transactions.action}</th>
                      <th className="px-2 py-1.5 text-left font-medium">{t.transactions.dateLabel}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.transactions.amountYuan}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.common.shares}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.common.nav}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txItems.map((it, idx) => (
                      <tr key={idx} className={cn("border-t", !it.fund_code || !/^\d{6}$/.test(it.fund_code) ? "bg-destructive/5" : "")}>
                        <td className="px-2 py-1">
                          <FundCodeCell item={it} onChange={(patch) => updateTxItem(idx, patch)} />
                          <span className="block text-[10px] text-muted-foreground truncate max-w-[120px]">{it.fund_name}</span>
                        </td>
                        <td className="px-2 py-1">
                          <select
                            value={it.action}
                            onChange={(e) => updateTxItem(idx, { action: e.target.value })}
                            className="h-7 rounded border border-border bg-background px-1 text-xs"
                          >
                            <option value="buy">{t.transactions.buy}</option>
                            <option value="sell">{t.transactions.sell}</option>
                            <option value="dividend">{t.transactions.dividend}</option>
                            <option value="reinvest">{t.transactions.reinvest}</option>
                          </select>
                        </td>
                        <td className="px-2 py-1">
                          <Input
                            type="date"
                            value={it.date || ""}
                            onChange={(e) => updateTxItem(idx, { date: e.target.value })}
                            className="h-7 text-xs w-[120px]"
                          />
                        </td>
                        <td className="px-2 py-1 text-right">
                          <Input
                            type="number"
                            value={it.amount ?? ""}
                            onChange={(e) => updateTxItem(idx, { amount: e.target.value ? Number(e.target.value) : null })}
                            className="h-7 text-xs text-right w-[100px]"
                            placeholder="—"
                          />
                        </td>
                        <td className="px-2 py-1 text-right">
                          <Input
                            type="number"
                            value={it.shares ?? ""}
                            onChange={(e) => updateTxItem(idx, { shares: e.target.value ? Number(e.target.value) : null })}
                            className="h-7 text-xs text-right w-[100px]"
                            placeholder="—"
                          />
                        </td>
                        <td className="px-2 py-1 text-right">
                          <Input
                            type="number"
                            value={it.nav ?? ""}
                            onChange={(e) => updateTxItem(idx, { nav: e.target.value ? Number(e.target.value) : null })}
                            className="h-7 text-xs text-right w-[80px]"
                            placeholder="—"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {validTxCount}/{txItems.length} {t.transactions.screenshotConfirmImport.replace("{n}", "").trim()}
                </p>
                <Button onClick={handleConfirmImport} disabled={importing || validTxCount === 0}>
                  {importing ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-1.5 h-4 w-4" />}
                  {t.transactions.screenshotConfirmImport.replace("{n}", String(validTxCount))}
                </Button>
              </div>
            </div>
          )}

          {/* Holdings preview */}
          {mode === "holdings" && holdingItems.length > 0 && !reconcileResult && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">
                  {t.transactions.screenshotPreviewHoldings.replace("{n}", String(holdingItems.length))}
                </p>
                <Button onClick={handleReconcile} disabled={reconciling} size="sm">
                  {reconciling ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1.5 h-4 w-4" />}
                  {t.transactions.screenshotReconcile}
                </Button>
              </div>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">{t.transactions.fundCode}</th>
                      <th className="px-2 py-1.5 text-left font-medium">{t.transactions.fundName}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.common.shares}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.positions.marketValue}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdingItems.map((it, idx) => (
                      <tr key={idx} className={cn("border-t", !it.fund_code || !/^\d{6}$/.test(it.fund_code) ? "bg-destructive/5" : "")}>
                        <td className="px-2 py-1">
                          <FundCodeCell item={it} onChange={(patch) => updateHoldingItem(idx, patch)} />
                        </td>
                        <td className="px-2 py-1 text-muted-foreground max-w-[160px] truncate">{it.fund_name}</td>
                        <td className="px-2 py-1 text-right">
                          <Input
                            type="number"
                            value={it.shares ?? ""}
                            onChange={(e) => updateHoldingItem(idx, { shares: e.target.value ? Number(e.target.value) : null })}
                            className="h-7 text-xs text-right w-[100px]"
                            placeholder="—"
                          />
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">
                          {it.market_value != null ? it.market_value.toFixed(2) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Reconcile result */}
          {reconcileResult && (
            <div className="space-y-3">
              <p className="text-sm font-medium">{t.transactions.screenshotReconcile}</p>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-2 py-1.5 w-8"></th>
                      <th className="px-2 py-1.5 text-left font-medium">{t.transactions.fundCode}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.transactions.screenshotReconciledShares}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.transactions.screenshotShares}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t.transactions.screenshotDelta}</th>
                      <th className="px-2 py-1.5 text-center font-medium">{t.transactions.screenshotSuggestedAction}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconcileResult.items.map((it, idx) => (
                      <tr key={idx} className={cn("border-t",
                        it.status === "ok" ? "opacity-50" : "",
                        it.status === "maybe_sold" ? "bg-warning/5" : "",
                      )}>
                        <td className="px-2 py-1.5 text-center">
                          {it.status !== "ok" && (
                            <Checkbox checked={selectedDiff.has(idx)} onCheckedChange={() => toggleDiff(idx)} />
                          )}
                        </td>
                        <td className="px-2 py-1.5 font-mono">{it.fund_code}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{it.recorded_shares.toFixed(2)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{it.screenshot_shares.toFixed(2)}</td>
                        <td className={cn("px-2 py-1.5 text-right tabular-nums", it.delta > 0 ? "text-success" : it.delta < 0 ? "text-destructive" : "")}>
                          {it.delta > 0 ? "+" : ""}{it.delta.toFixed(2)}
                        </td>
                        <td className="px-2 py-1.5 text-center">
                          {it.status === "ok" ? "✓" :
                           it.status === "buy" ? t.transactions.buy :
                           it.status === "sell" ? t.transactions.sell :
                           it.status === "new" ? t.transactions.screenshotStatusNew :
                           it.status === "maybe_sold" ? t.transactions.screenshotStatusMaybeSold : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between">
                <Button variant="ghost" size="sm" onClick={() => { setReconcileResult(null); setSelectedDiff(new Set()) }}>
                  ← {t.transactions.screenshotModeHoldings}
                </Button>
                <Button onClick={handleConfirmImport} disabled={importing || selectedTxCount === 0}>
                  {importing ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-1.5 h-4 w-4" />}
                  {t.transactions.screenshotConfirmImport.replace("{n}", String(selectedTxCount))}
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Fund code cell: 3 states (exact/multiple/none) ──
function FundCodeCell({ item, onChange }: {
  item: { fund_code: string | null; code_status: string; candidates: { code: string; name: string }[] }
  onChange: (patch: Partial<ParsedTxItem & ParsedHoldingItem>) => void
}) {
  if (item.code_status === "exact" && item.fund_code) {
    return <span className="font-mono text-xs">{item.fund_code}</span>
  }
  if (item.code_status === "multiple" && item.candidates.length > 0) {
    return (
      <select
        value=""
        onChange={(e) => onChange({ fund_code: e.target.value, code_status: "exact", candidates: [] })}
        className="h-7 rounded border border-border bg-background px-1 text-xs w-[110px]"
      >
        <option value="">{t_placeholder}</option>
        {item.candidates.map(c => <option key={c.code} value={c.code}>{c.code} {c.name.slice(0, 10)}</option>)}
      </select>
    )
  }
  return (
    <Input
      type="text"
      value={item.fund_code || ""}
      onChange={(e) => onChange({ fund_code: e.target.value, code_status: /^\d{6}$/.test(e.target.value) ? "exact" : "none" })}
      className="h-7 text-xs w-[110px] font-mono"
      placeholder="000000"
      maxLength={6}
    />
  )
}

// Placeholder for the select option (kept simple to avoid i18n complexity in sub-component)
const t_placeholder = "选择..."
