import LogoSpinner from "@/components/LogoSpinner"
import { cn } from "@/lib/utils"

interface LoadingStateProps {
  size?: "xs" | "sm" | "md" | "lg"
  fullscreen?: boolean
  className?: string
}

export default function LoadingState({ size = "lg", fullscreen = false, className }: LoadingStateProps) {
  const spinnerSize =
    size === "xs" ? "h-6 w-6"
    : size === "sm" ? "h-8 w-8"
    : size === "md" ? "h-10 w-10"
    : "h-16 w-16"
  const heightCls =
    fullscreen || size === "lg" ? "min-h-[60vh]"
    : size === "md" ? "py-8"
    : size === "sm" ? "py-4"
    : "py-2"
  return (
    <div className={cn("flex items-center justify-center", heightCls, className)}>
      <LogoSpinner className={spinnerSize} />
    </div>
  )
}
