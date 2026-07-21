import { useState } from "react"
import type { CalcFeeResponse } from "@/api/types"
import { money } from "@/lib/format"
import { cn } from "@/lib/utils"
import { ChevronDown, ChevronUp, Info } from "lucide-react"

interface Props {
  result: CalcFeeResponse
  action: "buy" | "sell"
  className?: string
}

export default function FeeBreakdownCard({ result, action, className }: Props) {
  const [open, setOpen] = useState(false)

  if (!result.label || result.label === "费率未知" || result.label === "金额为空" || result.label === "份额为空" || result.label === "日期为空") {
    return null
  }

  const hasLots = result.lots && result.lots.length > 0

  return (
    <div className={cn("mt-1.5 text-xs", className)}>
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <Info className="h-3 w-3 shrink-0" />
        <span>
          {result.label}
          {result.fee > 0 && (
            <span className="ml-1 font-medium text-foreground">
              → {money(result.fee)}
            </span>
          )}
          {result.fee === 0 && (
            <span className="ml-1 text-success">免手续费</span>
          )}
        </span>
        {hasLots && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="ml-auto inline-flex items-center gap-0.5 text-muted-foreground hover:text-foreground transition-colors"
          >
            {open ? "收起明细" : "查看明细"}
            {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        )}
      </div>

      {hasLots && open && (
        <div className="mt-2 rounded border border-border bg-muted/50 p-2 space-y-1">
          {action === "sell" && (
            <>
              <p className="text-[11px] font-medium text-muted-foreground mb-1.5">FIFO 赎回明细</p>
              {result.lots!.map((lot, i) => (
                <div key={i} className="flex items-center justify-between text-[11px]">
                  <span className="text-muted-foreground">
                    {lot.buy_date ? (
                      <>买 {lot.buy_date.slice(2).replace("-", "/")}</>
                    ) : (
                      <>超额部分</>
                    )}
                    {" "}{lot.used_shares.toFixed(2)}份
                    <span className="ml-1 text-muted-foreground/70">
                      持有{lot.days_held}天
                    </span>
                  </span>
                  <span className="tabular-nums">
                    {(lot.rate * 100).toFixed(2)}%{lot.fee > 0 && <span className="ml-1">→ {money(lot.fee)}</span>}
                  </span>
                </div>
              ))}
              <div className="pt-1 mt-1 border-t border-border flex items-center justify-between text-xs font-medium">
                <span>合计</span>
                <span className="tabular-nums">{money(result.fee)}</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}