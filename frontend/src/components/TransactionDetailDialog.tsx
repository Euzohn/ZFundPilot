import type { Transaction } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { money, navStr } from "@/lib/format"
import { ACTION_LABELS } from "@/lib/actionLabels"
import { Pencil, Receipt, Hash, Wallet, Banknote, PieChart, Percent, DollarSign, FileText } from "lucide-react"

interface Props {
  tx: Transaction | null
  fundName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onEdit?: (tx: Transaction) => void
}

function actionBadge(tx: Transaction) {
  const variant = tx.action === "buy" ? "success" : tx.action === "sell" ? "destructive" : "outline"
  const extra = tx.action === "dividend" ? "text-primary border-primary/30 bg-primary/10" : tx.action === "reinvest" ? "text-info border-info/30 bg-info/10" : ""
  return (
    <Badge variant={variant} className={extra}>
      {ACTION_LABELS[tx.action] ?? tx.action}
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

export default function TransactionDetailDialog({ tx, fundName, open, onOpenChange, onEdit }: Props) {
  if (!tx) return null

  const navValue = tx.action === "dividend"
    ? "—"
    : tx.nav != null
      ? navStr(tx.nav)
      : <Badge variant="outline" className="text-warning border-warning/40 bg-warning/10 text-[11px] px-1.5 py-0">待确认</Badge>

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
              <Receipt className="h-5 w-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-base">交易详情</DialogTitle>
              <DialogDescription asChild>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="font-mono text-xs">{tx.fund_code}</span>
                  {fundName && <span className="text-xs text-muted-foreground/70">· {fundName}</span>}
                </div>
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
          <span className="text-xs text-muted-foreground/70">操作</span>
          {actionBadge(tx)}
          <span className="mx-1 text-muted-foreground/30">|</span>
          <span className="text-xs text-muted-foreground/70">日期</span>
          <span className="text-sm">{tx.date}</span>
          <span className="mx-1 text-muted-foreground/30">|</span>
          <span className="text-xs text-muted-foreground/70">渠道</span>
          <span className="text-sm">{tx.channel || <span className="text-muted-foreground/60">未标注</span>}</span>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <Row icon={DollarSign} label="金额" value={tx.amount != null ? money(tx.amount) : "—"} mono />
          <Row icon={PieChart} label="份额" value={tx.shares?.toFixed(2) ?? "—"} mono />
          <Row icon={Hash} label="净值" value={navValue} mono />
          <Row icon={Banknote} label="手续费" value={tx.fee ? money(tx.fee) : "—"} mono />
          <Row icon={Wallet} label="渠道" value={tx.channel || <span className="text-muted-foreground/60">未标注</span>} />
          <Row icon={Percent} label="操作" value={actionBadge(tx)} />
        </div>

        {tx.note && (
          <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground/60 mt-0.5" />
            <div>
              <p className="text-[11px] leading-none text-muted-foreground/70 mb-1">备注</p>
              <p className="text-sm">{tx.note}</p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>关闭</Button>
          {onEdit && (
            <Button onClick={() => { onEdit(tx); onOpenChange(false) }}>
              <Pencil className="h-4 w-4 mr-1.5" /> 编辑
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}