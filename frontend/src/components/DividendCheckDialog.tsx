import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useLang } from "@/i18n/LanguageContext"
import { api } from "@/api/client"
import type { DividendEvent } from "@/api/types"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import LogoSpinner from "@/components/LogoSpinner"
import EmptyState from "@/components/EmptyState"
import { money } from "@/lib/format"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { Gift, ArrowRight } from "lucide-react"

interface DividendCheckDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function DividendCheckDialog({ open, onOpenChange }: DividendCheckDialogProps) {
  const { t } = useLang()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [events, setEvents] = useState<DividendEvent[]>([])
  const [fetched, setFetched] = useState(false)

  const handleCheck = async () => {
    setLoading(true)
    try {
      const result = await api.checkDividends()
      setEvents(result)
      setFetched(true)
      if (result.length === 0) {
        toast.success(t.transactions.noUnrecordedDividends)
      }
    } catch {
      toast.error(t.transactions.dividendCheckFailed)
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = (ev: DividendEvent, overrideMethod?: string) => {
    const method = overrideMethod ?? ev.dividend_method
    const action = method === "reinvest" ? "reinvest" : "dividend"
    const date = method === "reinvest" ? ev.ex_date : ev.pay_date
    const note = method === "reinvest"
      ? `红利再投资(${ev.per_share.toFixed(4)}元/份)`
      : `分红(${ev.per_share.toFixed(4)}元/份,登记日${ev.record_date})`
    onOpenChange(false)
    navigate(`/transactions?action=${action}&code=${ev.fund_code}&date=${date}&amount=${ev.estimated_amount}&note=${encodeURIComponent(note)}`)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Gift className="h-5 w-5" />
            {t.transactions.dividendCheck}
          </DialogTitle>
          <DialogDescription>{t.transactions.dividendCheckDesc}</DialogDescription>
        </DialogHeader>

        {!fetched ? (
          <div className="flex flex-col items-center justify-center py-12 gap-4">
            <p className="text-sm text-muted-foreground">{t.transactions.dividendCheckPrompt}</p>
            <Button onClick={handleCheck} disabled={loading}>
              {loading ? <LogoSpinner className="h-4 w-4 mr-1.5" /> : <Gift className="h-4 w-4 mr-1.5" />}
              {t.transactions.checkNow}
            </Button>
          </div>
        ) : events.length === 0 ? (
          <EmptyState title={t.transactions.noUnrecordedDividends} className="py-12" />
        ) : (
          <div className="flex-1 overflow-y-auto space-y-2">
            {events.map((ev, i) => (
              <DividendEventRow key={`${ev.fund_code}-${ev.ex_date}-${i}`} ev={ev} onConfirm={handleConfirm} />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function DividendEventRow({ ev, onConfirm }: {
  ev: DividendEvent
  onConfirm: (ev: DividendEvent, overrideMethod?: string) => void
}) {
  const { t } = useLang()
  const [method, setMethod] = useState(ev.dividend_method)
  const isReinvest = method === "reinvest"

  return (
    <div className="rounded-lg border border-border p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{ev.fund_code}</span>
            <span className="text-sm truncate">{ev.fund_name}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
            <span>{t.transactions.exDate}: {ev.ex_date}</span>
            <span>·</span>
            <span>{ev.per_share.toFixed(4)} {t.transactions.perShare}</span>
            <span>·</span>
            <span>{t.transactions.holding}: {ev.held_shares.toFixed(2)}</span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-lg font-semibold tabular-nums text-primary">
            {money(ev.estimated_amount)}
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
        <Button size="sm" onClick={() => onConfirm(ev, method)}>
          {isReinvest ? t.transactions.recordReinvest : t.transactions.recordDividend}
          <ArrowRight className="h-3.5 w-3.5 ml-1" />
        </Button>
      </div>
    </div>
  )
}
