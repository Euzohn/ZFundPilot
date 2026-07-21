import { TableHead } from "@/components/ui/table"
import { ChevronUp, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ComponentType, ReactNode } from "react"

interface SortHeaderConfig {
  sortField: string
  sortDir: "asc" | "desc"
  toggleSort: (field: string) => void
}

interface SortHeaderProps {
  field: string
  children: ReactNode
  className?: string
}

/**
 * 创建绑定 sort state 的 SortHeader 组件。
 *
 * 用法:
 *   const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })
 *   <SortHeader field="value">市值</SortHeader>
 *
 * 注意:返回的是新组件类型,每次调用都会创建。
 * 对于 SortHeader 这种纯展示组件,remount 开销可忽略;
 * 若要进一步优化,可在调用方用 useMemo 包裹依赖。
 */
export function makeSortHeader({ sortField, sortDir, toggleSort }: SortHeaderConfig): ComponentType<SortHeaderProps> {
  return function SortHeader({ field, children, className }: SortHeaderProps) {
    const active = sortField === field
    return (
      <TableHead
        className={cn("cursor-pointer select-none", active && "text-foreground", className)}
        onClick={() => toggleSort(field)}
      >
        <span className="inline-flex items-center gap-1">
          {children}
          {active && (sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
        </span>
      </TableHead>
    )
  }
}
