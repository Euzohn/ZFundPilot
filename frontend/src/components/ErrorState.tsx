import { AlertTriangle, RotateCw } from "lucide-react"
import { cn } from "@/lib/utils"
import { useLang } from "@/i18n/LanguageContext"

interface ErrorStateProps {
  message?: string
  onRetry?: () => void
  size?: "sm" | "md" | "lg"
}

export default function ErrorState({ message, onRetry, size = "lg" }: ErrorStateProps) {
  const { t } = useLang()
  const spinnerSize = size === "sm" ? "h-6 w-6" : size === "md" ? "h-8 w-8" : "h-10 w-10"
  const heightCls = size === "lg" ? "min-h-[60vh]" : size === "md" ? "py-8" : "py-4"
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 text-center", heightCls)}>
      <AlertTriangle className={spinnerSize} />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{t.components.errorStateDefault}</p>
        {message && <p className="text-xs text-muted-foreground">{message}</p>}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
        >
          <RotateCw className="h-4 w-4" />
          {t.components.retry}
        </button>
      )}
    </div>
  )
}
