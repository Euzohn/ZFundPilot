import { Languages } from "lucide-react"
import { cn } from "@/lib/utils"
import { useLang } from "@/i18n/LanguageContext"

interface LanguageToggleProps {
  variant?: "icon" | "segmented"
  className?: string
  label?: string
}

export default function LanguageToggle({ variant = "icon", className, label }: LanguageToggleProps) {
  const { lang, toggleLang } = useLang()

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={toggleLang}
        className={cn(
          "flex items-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
          className,
        )}
        title={lang === "zh" ? "Switch to English" : "切换到中文"}
        aria-label={lang === "zh" ? "Switch to English" : "切换到中文"}
      >
        <Languages className="h-4 w-4 shrink-0" />
        {label && <span className="whitespace-nowrap">{label}</span>}
      </button>
    )
  }

  return (
    <div className={cn("inline-flex rounded-lg border border-border p-0.5", className)}>
      {(["zh", "en"] as const).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => lang !== v && toggleLang()}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
            lang === v
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-pressed={lang === v}
        >
          {v === "zh" ? "中文" : "EN"}
        </button>
      ))}
    </div>
  )
}
