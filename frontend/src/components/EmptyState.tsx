import type { ReactNode, ElementType } from "react"
import { cn } from "@/lib/utils"

interface EmptyStateProps {
  title: string
  description?: string
  icon?: ElementType
  action?: ReactNode
  size?: "sm" | "default" | "lg"
  className?: string
}

export default function EmptyState({
  title,
  description,
  icon: Icon,
  action,
  size = "default",
  className,
}: EmptyStateProps) {
  const padding = size === "sm" ? "py-4" : size === "lg" ? "py-12" : "py-8"
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", padding, className)}>
      {Icon && <Icon className="mb-2 h-8 w-8 text-muted-foreground/60" />}
      <p className="text-sm text-muted-foreground">{title}</p>
      {description && <p className="mt-1 text-xs text-muted-foreground/70">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
