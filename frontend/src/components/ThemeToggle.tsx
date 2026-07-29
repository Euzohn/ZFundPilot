import { useState, useEffect } from "react"
import { Sun, Moon, Monitor } from "lucide-react"
import { cn } from "@/lib/utils"
import { getUiTheme, saveUiTheme, applyUiTheme, type UiTheme } from "@/lib/theme"
import { useLang } from "@/i18n/LanguageContext"

interface ThemeToggleProps {
  variant?: "icon" | "segmented"
  className?: string
  label?: string
}

const ORDER: UiTheme[] = ["light", "dark", "system"]

export default function ThemeToggle({ variant = "icon", className, label }: ThemeToggleProps) {
  const { t } = useLang()
  const [theme, setTheme] = useState<UiTheme>(getUiTheme)

  useEffect(() => {
    applyUiTheme(theme)
  }, [theme])

  const LABEL: Record<UiTheme, string> = {
    light: t.theme.light,
    dark: t.theme.dark,
    system: t.theme.system,
  }

  if (variant === "icon") {
    const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor
    const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length]
    return (
      <button
        type="button"
        onClick={() => {
          setTheme(next)
          saveUiTheme(next)
        }}
        className={cn(
          "flex items-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
          className,
        )}
        title={`${t.theme.toggle}：${LABEL[theme]}`}
        aria-label={`${t.theme.toggle}，${t.theme.current.replace("{val}", LABEL[theme])}`}
      >
        <Icon className="h-4 w-4 shrink-0" />
        {label && <span className="whitespace-nowrap">{label}</span>}
      </button>
    )
  }

  return (
    <div className={cn("inline-flex rounded-lg border border-border p-0.5", className)}>
      {(
        [
          { v: "light", icon: Sun, label: t.theme.light },
          { v: "dark", icon: Moon, label: t.theme.dark },
          { v: "system", icon: Monitor, label: t.theme.system },
        ] as const
      ).map(({ v, icon: Icon, label }) => (
        <button
          key={v}
          type="button"
          onClick={() => {
            setTheme(v)
            saveUiTheme(v)
          }}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
            theme === v
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-pressed={theme === v}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  )
}
