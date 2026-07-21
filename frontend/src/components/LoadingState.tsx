import LogoSpinner from "@/components/LogoSpinner"
import { cn } from "@/lib/utils"

interface LoadingStateProps {
  size?: "sm" | "md" | "lg"
  fullscreen?: boolean
  className?: string
}

export default function LoadingState({ size = "lg", fullscreen = false, className }: LoadingStateProps) {
  const spinnerSize = size === "sm" ? "h-8 w-8" : size === "md" ? "h-10 w-10" : "h-16 w-16"
  const padding = size === "sm" ? "py-4" : size === "md" ? "py-8" : "min-h-[60vh]"
  const heightCls = fullscreen ? "min-h-[60vh]" : padding
  return (
    <div className={cn("flex items-center justify-center", heightCls, className)}>
      <LogoSpinner className={spinnerSize} />
    </div>
  )
}
