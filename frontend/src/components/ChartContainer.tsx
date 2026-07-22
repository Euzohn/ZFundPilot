import { ResponsiveContainer } from "recharts"
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface ChartContainerProps {
  children: ReactNode
  height?: number
  mobileHeight?: number
  className?: string
}

export default function ChartContainer({
  children,
  height = 350,
  mobileHeight = 260,
  className,
}: ChartContainerProps) {
  return (
    <div className={cn("w-full", className)}>
      <div className="block sm:hidden">
        <ResponsiveContainer width="100%" height={mobileHeight}>
          {children as any}
        </ResponsiveContainer>
      </div>
      <div className="hidden sm:block">
        <ResponsiveContainer width="100%" height={height}>
          {children as any}
        </ResponsiveContainer>
      </div>
    </div>
  )
}