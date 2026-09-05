import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  icon?: ReactNode
  tracking?: "default" | "tight"
  truncate?: boolean
  className?: string
}

export default function PageHeader({
  title,
  subtitle,
  actions,
  icon,
  tracking = "tight",
  truncate = false,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="flex items-center gap-2 min-w-0 flex-1">
        {icon && <span className="shrink-0 text-primary">{icon}</span>}
        <div className="min-w-0">
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
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
