const STORAGE_KEY = "zfundpilot_ui_theme"

export type UiTheme = "light" | "dark" | "system"

const DEFAULT_THEME: UiTheme = "system"

export function getUiTheme(): UiTheme {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === "light" || v === "dark" || v === "system") return v
    return DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function saveUiTheme(theme: UiTheme): void {
  try { localStorage.setItem(STORAGE_KEY, theme) } catch {}
  applyUiTheme(theme)
}

export function applyUiTheme(theme: UiTheme): void {
  const root = document.documentElement
  const isDark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)
  if (isDark) root.classList.add("dark")
  else root.classList.remove("dark")
}

export function initUiTheme(): () => void {
  applyUiTheme(getUiTheme())
  const mql = window.matchMedia("(prefers-color-scheme: dark)")
  const handler = () => {
    if (getUiTheme() === "system") applyUiTheme("system")
  }
  mql.addEventListener("change", handler)
  return () => mql.removeEventListener("change", handler)
}
