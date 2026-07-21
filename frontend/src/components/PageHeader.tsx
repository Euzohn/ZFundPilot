import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  tracking?: "default" | "tight"
  truncate?: boolean
  className?: string
}

export default function PageHeader({
  title,
  subtitle,
  actions,
  tracking = "default",
  truncate = false,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0 flex-1">
        <h1
          className={cn(
            "text-xl md:text-2xl font-bold",
            tracking === "tight" && "tracking-tight",
            truncate && "truncate",
          )}
        >
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
