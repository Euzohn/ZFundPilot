import { useState, useEffect, useCallback, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { useLang } from "@/i18n/LanguageContext"
import { api } from "@/api/client"
import type { DividendAlert } from "@/api/types"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import LogoSpinner from "@/components/LogoSpinner"
import EmptyState from "@/components/EmptyState"
import ConfirmDialog from "@/components/ConfirmDialog"
import { money } from "@/lib/format"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { Gift, ArrowRight, RefreshCw, X, Trash2 } from "lucide-react"

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
  const [deletingAlertId, setDeletingAlertId] = useState<number | null>(null)
  // 关闭动画结束后的跳转目标：在 onCloseAutoFocus 里执行，
  // 确保预填跳转发生在弹窗卸载、背景 aria-hidden 解除之后
  const pendingNav = useRef<string | null>(null)

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
      if (result.cleaned > 0) {
        toast.info(t.transactions.scanCleaned.replace("{cleaned}", String(result.cleaned)))
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
    // 现金分红同样锚定除息日：净值下跌发生在除息日，后端按流水日冲减投入成本，
    // 记在发放日（通常晚 1~3 个交易日）会让除息日留下虚假亏损、发放日出现虚假收益。
    // 与再投资口径一致取 ex_date，仅当提醒未携带除息日时退回发放日。
    const date = alert.ex_date ?? alert.pay_date ?? ""
    const perShare = alert.per_share ?? 0
    const note = method === "reinvest"
      ? t.transactions.dividendReinvestNote.replace("{perShare}", perShare.toFixed(4))
      : t.transactions.dividendCashNote
        .replace("{perShare}", perShare.toFixed(4))
        .replace("{date}", alert.record_date ?? "")
    const channelParam = alert.channel
      ? `&channel=${encodeURIComponent(alert.channel)}`
      : ""
    pendingNav.current = `/transactions?action=${action}&code=${alert.fund_code}&date=${date}&amount=${alert.estimated_amount ?? 0}&note=${encodeURIComponent(note)}${channelParam}&alert_id=${alert.id}`
    onOpenChange(false)
  }

  const handleIgnore = async (alertId: number) => {
    try {
      await api.updateDividendAlert(alertId, "ignored")
      setAlerts(prev => prev.filter(a => a.id !== alertId))
    } catch {
      toast.error(t.transactions.ignoreFailed)
    }
  }

  const handleDelete = async (alertId: number) => {
    try {
      await api.deleteDividendAlert(alertId)
      // 仅删除成功后才移除列表项（与 handleIgnore 一致），失败时保留以免误导用户
      setAlerts(prev => prev.filter(a => a.id !== alertId))
    } catch {
      toast.error(t.common.deleteFailed)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          if (pendingNav.current) {
            const target = pendingNav.current
            pendingNav.current = null
            navigate(target)
          }
        }}
      >
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
                onDelete={(id) => setDeletingAlertId(id)}
              />
            ))}
          </div>
        )}
      </DialogContent>
      <ConfirmDialog
        open={deletingAlertId !== null}
        onOpenChange={(open) => { if (!open) setDeletingAlertId(null) }}
        title={t.common.delete}
        tone="destructive"
        onConfirm={() => { if (deletingAlertId !== null) { handleDelete(deletingAlertId); setDeletingAlertId(null) } }}
      />
    </Dialog>
  )
}

function DividendAlertRow({ alert, onConfirm, onIgnore, onDelete }: {
  alert: DividendAlert
  onConfirm: (alert: DividendAlert, overrideMethod?: string) => void
  onIgnore: (alertId: number) => void
  onDelete: (alertId: number) => void
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
            {alert.channel && (
              <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                {alert.channel}
              </span>
            )}
          </div>
          <div className="mt-1 flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
            <span>{t.transactions.exDate}: {alert.ex_date}</span>
            <span>·</span>
            <span>{(alert.per_share ?? 0).toFixed(4)} {t.transactions.perShare}</span>
            <span>·</span>
            <span>{t.transactions.holding.replace("{n}", (alert.held_shares ?? 0).toFixed(2))}</span>
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
          <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-destructive" onClick={() => onDelete(alert.id)} title={t.common.delete}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
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
