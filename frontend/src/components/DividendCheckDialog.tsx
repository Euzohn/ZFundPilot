import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { useLang } from "@/i18n/LanguageContext"
import { api } from "@/api/client"
import type { DividendAlert } from "@/api/types"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import LogoSpinner from "@/components/LogoSpinner"
import EmptyState from "@/components/EmptyState"
import { money } from "@/lib/format"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { Gift, ArrowRight, RefreshCw, X } from "lucide-react"

interface DividendCheckDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function DividendCheckDialog({ open, onOpenChange }: DividendCheckDialogProps) {
  const { t } = useLang()
  const navigate = useNavigate()
  const [alerts, setAlerts] = useState<DividendAlert[]>([])
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)

  const loadAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const result = await api.getDividendAlerts("pending")
      setAlerts(result)
    } catch {
      toast.error(t.transactions.dividendCheckFailed)
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (!open) return
    let active = true
    setLoading(true)
    api.getDividendAlerts("pending")
      .then(r => { if (active) setAlerts(r) })
      .catch(() => { if (active) toast.error(t.transactions.dividendCheckFailed) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, t])

  const handleRescan = async () => {
    setScanning(true)
    try {
      const result = await api.scanDividends()
      if (result.found === 0) {
        toast.success(t.transactions.noUnrecordedDividends)
      } else {
        toast.success(t.transactions.scanResult.replace("{found}", String(result.found)).replace("{new}", String(result.new)))
      }
      await loadAlerts()
    } catch {
      toast.error(t.transactions.scanFailed)
    } finally {
      setScanning(false)
    }
  }

  const handleConfirm = (alert: DividendAlert, overrideMethod?: string) => {
    const method = overrideMethod ?? alert.dividend_method
    const action = method === "reinvest" ? "reinvest" : "dividend"
    const date = method === "reinvest" ? (alert.ex_date ?? "") : (alert.pay_date ?? "")
    const perShare = alert.per_share ?? 0
    const note = method === "reinvest"
      ? `红利再投资(${perShare.toFixed(4)}元/份)`
      : `分红(${perShare.toFixed(4)}元/份,登记日${alert.record_date ?? ""})`
    onOpenChange(false)
    navigate(`/transactions?action=${action}&code=${alert.fund_code}&date=${date}&amount=${alert.estimated_amount ?? 0}&note=${encodeURIComponent(note)}&alert_id=${alert.id}`)
  }

  const handleIgnore = async (alertId: number) => {
    try {
      await api.updateDividendAlert(alertId, "ignored")
      setAlerts(prev => prev.filter(a => a.id !== alertId))
    } catch {
      toast.error(t.transactions.ignoreFailed)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Gift className="h-5 w-5" />
            {t.transactions.dividendAlertsTitle}
          </DialogTitle>
          <DialogDescription>{t.transactions.dividendCheckDesc}</DialogDescription>
        </DialogHeader>

        <div className="flex justify-end pb-2">
          <Button variant="outline" size="sm" onClick={handleRescan} disabled={scanning}>
            {scanning ? <LogoSpinner className="h-4 w-4 mr-1.5" /> : <RefreshCw className="h-4 w-4 mr-1.5" />}
            {t.transactions.rescan}
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <LogoSpinner className="h-6 w-6" />
          </div>
        ) : alerts.length === 0 ? (
          <EmptyState title={t.transactions.dividendAlertsEmpty} className="py-12" />
        ) : (
          <div className="flex-1 overflow-y-auto space-y-2">
            {alerts.map((alert) => (
              <DividendAlertRow
                key={alert.id}
                alert={alert}
                onConfirm={handleConfirm}
                onIgnore={handleIgnore}
              />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function DividendAlertRow({ alert, onConfirm, onIgnore }: {
  alert: DividendAlert
  onConfirm: (alert: DividendAlert, overrideMethod?: string) => void
  onIgnore: (alertId: number) => void
}) {
  const { t } = useLang()
  const [method, setMethod] = useState(alert.dividend_method)
  const isReinvest = method === "reinvest"

  return (
    <div className="rounded-lg border border-border p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{alert.fund_code}</span>
            <span className="text-sm truncate">{alert.fund_name}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
            <span>{t.transactions.exDate}: {alert.ex_date}</span>
            <span>·</span>
            <span>{(alert.per_share ?? 0).toFixed(4)} {t.transactions.perShare}</span>
            <span>·</span>
            <span>{t.transactions.holding}: {(alert.held_shares ?? 0).toFixed(2)}</span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-lg font-semibold tabular-nums text-primary">
            {money(alert.estimated_amount ?? 0)}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">{t.fundDetail.dividendMethod}:</span>
          <div className="flex rounded-md border border-border overflow-hidden">
            <button
              onClick={() => setMethod("cash")}
              className={cn("px-2 py-0.5 text-xs",
                !isReinvest ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted/50")}
            >{t.transactions.dividend}</button>
            <button
              onClick={() => setMethod("reinvest")}
              className={cn("px-2 py-0.5 text-xs",
                isReinvest ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted/50")}
            >{t.transactions.reinvest}</button>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground" onClick={() => onIgnore(alert.id)}>
            <X className="h-3.5 w-3.5 mr-0.5" />
            {t.transactions.ignore}
          </Button>
          <Button size="sm" onClick={() => onConfirm(alert, method)}>
            {isReinvest ? t.transactions.recordReinvest : t.transactions.recordDividend}
            <ArrowRight className="h-3.5 w-3.5 ml-1" />
          </Button>
        </div>
      </div>
    </div>
  )
}
