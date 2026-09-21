import type { ElementType } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type IconTone = "default" | "primary" | "success" | "warning" | "danger" | "info"

const ICON_TONE: Record<IconTone, string> = {
  default: "bg-muted/50 text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-destructive/10 text-destructive",
  info: "bg-info/10 text-info",
}

interface MetricCardProps {
  label: string
  value: string
  sub?: string
  color?: string
  subColor?: string
  icon?: ElementType
  iconTone?: IconTone
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
  iconTone = "default",
  size = "default",
  fade = false,
}: MetricCardProps) {
  const padding = size === "sm" ? "p-3 md:p-4" : "p-4 md:p-5"
  const valueSize = size === "sm" ? "text-base md:text-lg" : "text-lg md:text-xl"
  const subCls = subColor ?? color ?? "text-muted-foreground"

  return (
    <Card className="card-hover">
      <CardContent className={cn("flex h-full items-center justify-between", padding)}>
        <div className="space-y-0.5">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className={cn("font-bold tabular-nums", valueSize, fade && "fade-in-up", color)}>{value}</p>
          {sub && <p className={cn("text-xs tabular-nums", subCls)}>{sub}</p>}
        </div>
        {Icon && (
          <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", ICON_TONE[iconTone])}>
            <Icon className="h-5 w-5" />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
