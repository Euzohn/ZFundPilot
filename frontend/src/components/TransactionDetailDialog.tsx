import type { Transaction } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { money, navStr } from "@/lib/format"
import { Pencil, Receipt, Hash, Wallet, Banknote, PieChart, DollarSign, FileText, Clock, ArrowUpRight } from "lucide-react"
import { useLang } from "@/i18n/LanguageContext"

interface Props {
  tx: Transaction | null
  fundName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onEdit?: (tx: Transaction) => void
  onViewFund?: (fundCode: string) => void
}

function actionBadge(tx: Transaction, actionLabels: Record<string, string>) {
  const variant = tx.action === "buy" ? "success" : tx.action === "sell" ? "destructive" : "outline"
  const extra = tx.action === "dividend" ? "text-primary border-primary/30 bg-primary/10" : tx.action === "reinvest" ? "text-info border-info/30 bg-info/10" : ""
  return (
    <Badge variant={variant} className={extra}>
      {actionLabels[tx.action] ?? tx.action}
    </Badge>
  )
}

function Row({ icon: Icon, label, value, mono }: { icon: React.ComponentType<{ className?: string }>; label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-muted/30 px-3 py-2.5">
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground/60" />
      <div className="flex-1 min-w-0">
        <p className="text-[11px] leading-none text-muted-foreground/70 mb-1">{label}</p>
        <p className={mono ? "font-mono text-sm tabular-nums" : "text-sm"}>{value}</p>
      </div>
    </div>
  )
}

export default function TransactionDetailDialog({ tx, fundName, open, onOpenChange, onEdit, onViewFund }: Props) {
  const { t } = useLang()
  if (!tx) return null

  const navValue = tx.action === "dividend"
    ? "—"
    : tx.nav != null
      ? navStr(tx.nav)
      : <Badge variant="outline" className="text-warning border-warning/40 bg-warning/10 text-[11px] px-1.5 py-0">{t.transactions.pendingConfirm}</Badge>

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
              <Receipt className="h-5 w-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-base">{t.components.transactionDetailTitle}</DialogTitle>
              <DialogDescription asChild>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="font-mono text-xs">{tx.fund_code}</span>
                  {fundName && <span className="text-xs text-muted-foreground/70">· {fundName}</span>}
                </div>
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
          <span className="text-xs text-muted-foreground/70">{t.transactions.actionLabel}</span>
          {actionBadge(tx, t.actionLabels)}
          <span className="mx-1 text-muted-foreground/30">|</span>
          <span className="text-xs text-muted-foreground/70">{t.transactions.dateLabel}</span>
          <span className="text-sm">{tx.date}</span>
          
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <Row icon={DollarSign} label={t.transactions.amountLabel} value={tx.amount != null ? money(tx.amount) : "—"} mono />
          <Row icon={PieChart} label={t.transactions.sharesLabel} value={tx.shares?.toFixed(2) ?? "—"} mono />
          <Row icon={Hash} label={t.transactions.navLabel} value={navValue} mono />
          <Row icon={Banknote} label={t.transactions.feeLabel} value={tx.fee ? money(tx.fee) : "—"} mono />
          <Row icon={Wallet} label={t.transactions.channelLabel} value={tx.channel || <span className="text-muted-foreground/60">{t.common.unlabeled}</span>} />
          <Row icon={Clock} label={t.transactions.t1Label} value={tx.is_t1 ? t.aiChat.afterClose : t.aiChat.beforeClose} />
        </div>

        {tx.note && (
          <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground/60 mt-0.5" />
            <div>
              <p className="text-[11px] leading-none text-muted-foreground/70 mb-1">{t.transactions.noteLabel}</p>
              <p className="text-sm">{tx.note}</p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t.common.close}</Button>
          {onViewFund && (
            <Button variant="outline" onClick={() => { onViewFund(tx.fund_code); onOpenChange(false) }}>
              <ArrowUpRight className="h-4 w-4 mr-1.5" /> {t.common.viewFund}
            </Button>
          )}
          {onEdit && (
            <Button onClick={() => { onEdit(tx); onOpenChange(false) }}>
              <Pencil className="h-4 w-4 mr-1.5" /> {t.common.edit}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}