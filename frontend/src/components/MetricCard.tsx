import type { ElementType } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface MetricCardProps {
  label: string
  value: string
  sub?: string
  color?: string
  subColor?: string
  icon?: ElementType
  size?: "default" | "sm"
  fade?: boolean
}

export default function MetricCard({
  label,
  value,
  sub,
  color,
  subColor,
  icon: Icon,
  size = "default",
  fade = false,
}: MetricCardProps) {
  const padding = size === "sm" ? "p-3 md:p-4" : "p-4 md:p-5"
  const valueSize = size === "sm" ? "text-base md:text-lg" : "text-lg md:text-xl"
  const subCls = subColor ?? color ?? "text-muted-foreground"

  return (
    <Card className="card-hover">
      <CardContent className={cn("flex items-center justify-between", padding)}>
        <div className="space-y-0.5">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className={cn("font-bold tabular-nums", valueSize, fade && "fade-in-up", color)}>{value}</p>
          {sub && <p className={cn("text-xs tabular-nums", subCls)}>{sub}</p>}
        </div>
        {Icon && (
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted/50">
            <Icon className="h-5 w-5 text-muted-foreground" />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
